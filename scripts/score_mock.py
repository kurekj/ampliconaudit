"""Score a mock-community sample against its declared composition.

    python scripts/score_mock.py data/artifacts/all/mock/Zymo.R2 [more sample dirs...]

Each sample directory must hold ``table_species.csv`` (one row per ASV with a
``final_species`` column) and ``table_genus.csv`` (taxonomy string, percent of
reads). The declared composition is ``data/mock_expected.json``.

Species-level precision/recall/F1 count a species as detected when at least
one ASV carries its name (entries ending in " sp." are genus-level calls and
are ignored). Genus-level precision/recall/F1 use the genus table with a 0.1 %
floor, so trace false positives do not dominate a presence/absence score;
the Bray-Curtis dissimilarity is computed on the full, unfloored percentages.
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_DEFAULT = ROOT / "data" / "mock_expected.json"
_GENUS_RE = re.compile(r"g__([^;]+)")


def _synonym_map(expected: dict, key: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, alts in expected.get(key, {}).items():
        out[canonical.lower()] = canonical
        for alt in alts:
            out[alt.lower()] = canonical
    return out


def _canon(name: str, syn: dict[str, str]) -> str:
    return syn.get(name.strip().lower(), name.strip())


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def score_sample(sample_dir: Path, expected: dict, min_genus_pct: float = 0.1) -> dict:
    sample_dir = Path(sample_dir)
    spec_syn = _synonym_map(expected, "species_synonyms")
    gen_syn = _synonym_map(expected, "genus_synonyms")
    expected_species = {c["species"] for c in expected["community"]}
    expected_genera = {c["genus"] for c in expected["community"]}
    expected_pct: dict[str, float] = {}
    for c in expected["community"]:
        expected_pct[c["genus"]] = expected_pct.get(c["genus"], 0.0) + float(c["expected_pct_16s"])

    detected_species: set[str] = set()
    n_asv = n_confirmed = 0
    with open(sample_dir / "table_species.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            n_asv += 1
            if row.get("blast_status") == "confirmed":
                n_confirmed += 1
            name = (row.get("final_species") or "").strip()
            if not name or name.endswith(" sp."):
                continue
            detected_species.add(_canon(name, spec_syn))
    tp_s = detected_species & expected_species
    fp_s = sorted(detected_species - expected_species)
    fn_s = sorted(expected_species - detected_species)
    sp_p, sp_r, sp_f1 = _prf(len(tp_s), len(fp_s), len(fn_s))

    observed_pct: dict[str, float] = {}
    with open(sample_dir / "table_genus.csv", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)  # header: "", sample
        for label, pct in reader:
            m = _GENUS_RE.search(label)
            genus = _canon(m.group(1) if m else label, gen_syn)
            observed_pct[genus] = observed_pct.get(genus, 0.0) + float(pct)
    detected_genera = {g for g, pct in observed_pct.items() if pct >= min_genus_pct}
    tp_g = detected_genera & expected_genera
    fp_g = sorted(detected_genera - expected_genera)
    fn_g = sorted(expected_genera - detected_genera)
    g_p, g_r, g_f1 = _prf(len(tp_g), len(fp_g), len(fn_g))

    keys = set(expected_pct) | set(observed_pct)
    shared = sum(min(expected_pct.get(k, 0.0), observed_pct.get(k, 0.0)) for k in keys)
    total = sum(expected_pct.values()) + sum(observed_pct.values())
    bray_curtis = 1.0 - 2.0 * shared / total if total else 1.0
    declared_share = sum(observed_pct.get(g, 0.0) for g in expected_genera)

    return {
        "sample": sample_dir.name,
        "n_asv": n_asv, "n_confirmed": n_confirmed,
        "species_tp": len(tp_s), "species_fp": len(fp_s), "species_fn": len(fn_s),
        "species_precision": sp_p, "species_recall": sp_r, "species_f1": sp_f1,
        "genus_tp": len(tp_g), "genus_fp": len(fp_g), "genus_fn": len(fn_g),
        "genus_precision": g_p, "genus_recall": g_r, "genus_f1": g_f1,
        "declared_genera_pct": declared_share,
        "bray_curtis": bray_curtis,
        "fp_species": fp_s, "missed_species": fn_s, "fp_genera": fp_g,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sample_dirs", nargs="+", type=Path)
    ap.add_argument("--expected", type=Path, default=EXPECTED_DEFAULT)
    ap.add_argument("--min-genus-pct", type=float, default=0.1)
    args = ap.parse_args(argv)
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    for d in args.sample_dirs:
        r = score_sample(d, expected, args.min_genus_pct)
        print(f"{d}: ASVs {r['n_asv']}, confirmed {r['n_confirmed']}, "
              f"species P/R/F1 {r['species_precision']:.2f}/{r['species_recall']:.2f}/"
              f"{r['species_f1']:.2f}, genus P/R/F1 {r['genus_precision']:.2f}/"
              f"{r['genus_recall']:.2f}/{r['genus_f1']:.2f}, declared genera "
              f"{r['declared_genera_pct']:.1f} % of reads, Bray-Curtis {r['bray_curtis']:.3f}")
        print(f"   false-positive species: {', '.join(r['fp_species']) or '-'}")
        print(f"   missed species: {', '.join(r['missed_species']) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
