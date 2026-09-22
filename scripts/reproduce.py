"""Rebuild the tables of the paper from the artifacts in data/.

    python scripts/reproduce.py

Runs the wrapper-pipeline profile over every ablation arm in data/artifacts
(Table 3), writes the reports to data/reports/ and the per-sample measurements
to data/tables/, prints the effect of the repairs on the 48 gut samples
(Table 4, plus the per-arm means that attribute each effect to one repair),
scores the two mock communities in every arm against their declared
composition (Table 5), and audits the stock QIIME 2 exports in data/stock with
the qiime2-export profile (Table 6).

The audit needs nothing beyond the standard library. The significance tests of
Table 4 need SciPy:

    pip install scipy
"""
from __future__ import annotations

import csv
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from ampliconaudit import ArtifactReader, profiles  # noqa: E402
from score_mock import score_sample  # noqa: E402

ARMS = ("baseline", "F1", "F2", "F3", "rank", "all")
COHORTS = ("ablacja_PRJNA420417", "ablacja_PRJNA732664", "ablacja_PRJNA763023")
MOCKS = ("Zymo.R1", "Zymo.R2")
METRICS = (("blast_16s_confirmed", "Species confirmed"),
           ("total_asvs", "ASVs"),
           ("blast_nt_submitted", "ASVs sent to nt"))


def audit_arms(artifacts: Path, reports: Path, arms) -> dict[str, dict]:
    """Run the wrapper profile over each arm and write one report per arm."""
    profile = profiles.get("qiime2-dada2-wrapper")
    out = {}
    for arm in arms:
        report = profile.audit(ArtifactReader(artifacts / arm))
        d = reports / arm
        d.mkdir(parents=True, exist_ok=True)
        (d / "audit.json").write_text(report.to_json(), encoding="utf-8")
        out[arm] = {"samples": len(report.samples),
                    "fail": report.n_fail,
                    "warn": report.n_warn,
                    "findings": report.findings}
    return out


def per_sample(artifacts: Path, arms) -> list[dict]:
    """One row per (arm, sample) with the fields Table 4 is built from."""
    rows = []
    for arm in arms:
        for cohort in COHORTS:
            for summary in sorted((artifacts / arm / cohort).glob("*/classification_summary.json")):
                sample = summary.parent
                d = json.loads(summary.read_text(encoding="utf-8"))
                chim = sample / f"{sample.name}.chimera_stats.json"
                c = json.loads(chim.read_text(encoding="utf-8")) if chim.exists() else {}
                pct = (100.0 * c["chimeric_reads"] / c["input_reads"]
                       if c.get("input_reads") else None)
                rows.append({"arm": arm,
                             "sample": f"{cohort}/{sample.name}",
                             "total_asvs": d["total_asvs"],
                             "blast_16s_confirmed": d["blast_16s_confirmed"],
                             "blast_nt_submitted": d["blast_nt_submitted"],
                             "chimera_pct": None if pct is None else round(pct, 2)})
    return rows


def rank_biserial(before: list[float], after: list[float]) -> float:
    """Matched-pairs rank-biserial correlation, bounded to [-1, 1].

    The Z/sqrt(N) shortcut is not used: it is not bounded by 1 when the p it
    is derived from comes from the exact test, and a correlation above 1 is
    not a quantity.
    """
    from scipy.stats import rankdata
    diff = [a - b for a, b in zip(after, before) if a != b]
    ranks = rankdata([abs(v) for v in diff])
    pos = sum(r for r, v in zip(ranks, diff) if v > 0)
    neg = sum(r for r, v in zip(ranks, diff) if v < 0)
    return (pos - neg) / ranks.sum()


def table4(rows: list[dict], arms) -> None:
    by_arm = {arm: {r["sample"]: r for r in rows if r["arm"] == arm} for arm in arms}
    keys = sorted(set.intersection(*(set(v) for v in by_arm.values() if v)))

    print(f"\nPer-arm means over the {len(keys)} gut samples (attribution of each effect)")
    print(f"{'Metric':<18}" + "".join(f"{arm:>14}" for arm in arms if by_arm[arm]))
    for field, label in METRICS:
        cells = []
        for arm in arms:
            if not by_arm[arm]:
                continue
            v = [by_arm[arm][k][field] for k in keys]
            cells.append(f"{st.mean(v):>7.1f}+-{st.stdev(v):<5.1f}")
        print(f"{label:<18}" + "".join(cells))

    try:
        from scipy.stats import wilcoxon
    except ImportError:
        print("\nTable 4 skipped: SciPy is not installed (pip install scipy)")
        return

    base, allr = by_arm["baseline"], by_arm["all"]
    print(f"\nTable 4  (n = {len(keys)})")
    print(f"{'Metric':<18}{'baseline':>16}{'all':>16}{'p':>12}{'r':>8}")
    for field, label in METRICS:
        b = [base[k][field] for k in keys]
        a = [allr[k][field] for k in keys]
        # The normal approximation is requested explicitly: the differences
        # contain ties for all three metrics, and the exact distribution
        # assumes none. Zero differences are dropped (SciPy's default
        # 'wilcox' zero method).
        _, p = wilcoxon(b, a, method="approx")
        r = rank_biserial(b, a)
        print(f"{label:<18}{st.mean(b):>9.1f}+-{st.stdev(b):<5.1f}"
              f"{st.mean(a):>9.1f}+-{st.stdev(a):<5.1f}{p:>12.2g}{abs(r):>8.2f}")

    chim = sorted(r["chimera_pct"] for r in rows
                  if r["arm"] == "all" and r["chimera_pct"] is not None)
    print(f"\nChimeric reads removed, arm 'all': median {st.median(chim):.1f} %, "
          f"range {chim[0]:.1f}-{chim[-1]:.1f} % (n = {len(chim)})")


def table5(artifacts: Path, tables: Path, arms) -> None:
    expected_path = ROOT / "data" / "mock_expected.json"
    if not expected_path.exists():
        print("\nTable 5 skipped: data/mock_expected.json missing")
        return
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    rows = []
    for arm in arms:
        for mock in MOCKS:
            d = artifacts / arm / "mock" / mock
            if (d / "table_species.csv").exists():
                rows.append({"arm": arm, **score_sample(d, expected)})
    if not rows:
        print("\nTable 5 skipped: no mock species/genus tables found")
        return
    print("\nTable 5  (mock communities against the declared D6300 composition)")
    print(f"{'Arm':<9}{'Sample':<9}{'ASVs':>5}{'conf':>5}{'sp TP/FP/FN':>13}{'sp F1':>7}"
          f"{'gen TP/FP/FN':>14}{'gen F1':>8}{'decl%':>7}{'BC':>7}  false-positive species")
    for r in rows:
        print(f"{r['arm']:<9}{r['sample']:<9}{r['n_asv']:>5}{r['n_confirmed']:>5}"
              f"{r['species_tp']:>5}/{r['species_fp']}/{r['species_fn']:<4}{r['species_f1']:>7.2f}"
              f"{r['genus_tp']:>6}/{r['genus_fp']}/{r['genus_fn']:<4}{r['genus_f1']:>8.2f}"
              f"{r['declared_genera_pct']:>7.1f}{r['bray_curtis']:>7.3f}  "
              f"{'; '.join(r['fp_species']) or '-'}")
    with open(tables / "table_mock.csv", "w", newline="", encoding="utf-8") as fh:
        flat = [{k: ("; ".join(v) if isinstance(v, list) else v) for k, v in r.items()}
                for r in rows]
        w = csv.DictWriter(fh, fieldnames=list(flat[0]))
        w.writeheader()
        w.writerows(flat)


def table6(stock: Path, reports: Path) -> None:
    if not stock.exists():
        print("\nTable 6 skipped: data/stock missing")
        return
    profile = profiles.get("qiime2-export")
    print("\nTable 6  (stock QIIME 2 exports, profile qiime2-export)")
    print(f"{'Run':<22}{'Samples':>8}{'FAIL':>6}{'WARN':>6}   findings")
    total = 0
    for run in sorted(p.parent for p in stock.rglob("stats.tsv")):
        rel = str(run.relative_to(stock)).replace("\\", "/")
        report = profile.audit(ArtifactReader(stock), rel)
        total += len(report.samples)
        d = reports / "stock" / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "audit.json").write_text(report.to_json(), encoding="utf-8")
        detail = "; ".join(f"{f.severity.value} {f.check} {f.sample or ''}".strip()
                           for f in report.findings) or "clean"
        print(f"{rel:<22}{len(report.samples):>8}{report.n_fail:>6}{report.n_warn:>6}   {detail}")
    print(f"{'total':<22}{total:>8}")


def main() -> int:
    artifacts = ROOT / "data" / "artifacts"
    if not artifacts.exists():
        print(f"{artifacts} not found", file=sys.stderr)
        return 1
    arms = tuple(a for a in ARMS if (artifacts / a).exists())

    audits = audit_arms(artifacts, ROOT / "data" / "reports", arms)

    tables = ROOT / "data" / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    print("Table 3")
    print(f"{'Arm':<10}{'Samples':>9}{'FAIL':>7}{'WARN':>7}   decomposition")
    matrix = [("arm", "check", "severity", "n")]
    for arm in arms:
        a = audits[arm]
        counts: dict[tuple[str, str], int] = {}
        for f in a["findings"]:
            counts[(f.check, f.severity.value)] = counts.get((f.check, f.severity.value), 0) + 1
        matrix.extend((arm, c, s, n) for (c, s), n in sorted(counts.items()))
        detail = ", ".join(f"{c} {s}={n}" for (c, s), n in sorted(counts.items()))
        print(f"{arm:<10}{a['samples']:>9}{a['fail']:>7}{a['warn']:>7}   {detail}")

    with open(tables / "table_audit_matrix.csv", "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(matrix)

    rows = per_sample(artifacts, arms)
    with open(tables / "table_per_sample.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    table4(rows, arms)
    table5(artifacts, tables, arms)
    table6(ROOT / "data" / "stock", ROOT / "data" / "reports")
    print(f"\nreports -> {ROOT / 'data' / 'reports'}\ntables  -> {tables}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
