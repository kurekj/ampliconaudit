"""Rebuild Tables 3 and 4 of the paper from the artifacts in data/artifacts.

    python scripts/reproduce.py

Runs the audit over all five ablation arms, writes the reports to
data/reports/, writes the per-sample measurements to data/tables/, and prints
both tables so they can be compared against the paper.

The audit itself needs nothing beyond the standard library. The significance
tests in Table 4 need SciPy:

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

from ampliconaudit import ArtifactReader, profiles  # noqa: E402

ARMS = ("baseline", "F1", "F2", "F3", "all")
COHORTS = ("ablacja_PRJNA420417", "ablacja_PRJNA732664", "ablacja_PRJNA763023")
METRICS = (("blast_16s_confirmed", "Species confirmed"),
           ("total_asvs", "ASVs"),
           ("blast_nt_submitted", "ASVs sent to nt"))


def audit_arms(artifacts: Path, reports: Path) -> dict[str, dict]:
    """Run the bundled profile over each arm and write one report per arm."""
    profile = profiles.get("qiime2-dada2")
    out = {}
    for arm in ARMS:
        report = profile.audit(ArtifactReader(artifacts / arm))
        d = reports / arm
        d.mkdir(parents=True, exist_ok=True)
        (d / "audit.json").write_text(report.to_json(), encoding="utf-8")
        out[arm] = {"samples": len(report.samples),
                    "fail": report.n_fail,
                    "warn": report.n_warn,
                    "findings": report.findings}
    return out


def per_sample(artifacts: Path) -> list[dict]:
    """One row per (arm, sample) with the fields Table 4 is built from."""
    rows = []
    for arm in ARMS:
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


def table4(rows: list[dict]) -> None:
    try:
        from scipy.stats import wilcoxon
    except ImportError:
        print("\nTable 4 skipped: SciPy is not installed (pip install scipy)")
        return

    base = {r["sample"]: r for r in rows if r["arm"] == "baseline"}
    allr = {r["sample"]: r for r in rows if r["arm"] == "all"}
    keys = sorted(set(base) & set(allr))

    print(f"\nTable 4  (n = {len(keys)})")
    print(f"{'Metric':<18}{'baseline':>16}{'all':>16}{'p':>12}{'r':>8}")
    for field, label in METRICS:
        b = [base[k][field] for k in keys]
        a = [allr[k][field] for k in keys]
        # method='auto': SciPy falls back to the normal approximation when the
        # differences contain ties, which they do for all three metrics here.
        # The exact test assumes no ties, so it is not applicable.
        _, p = wilcoxon(b, a)
        r = rank_biserial(b, a)
        print(f"{label:<18}{st.mean(b):>9.1f}+-{st.stdev(b):<5.1f}"
              f"{st.mean(a):>9.1f}+-{st.stdev(a):<5.1f}{p:>12.2g}{abs(r):>8.2f}")

    chim = sorted(r["chimera_pct"] for r in rows
                  if r["arm"] == "all" and r["chimera_pct"] is not None)
    print(f"\nChimeric reads removed, arm 'all': median {st.median(chim):.1f} %, "
          f"range {chim[0]:.1f}-{chim[-1]:.1f} % (n = {len(chim)})")


def main() -> int:
    artifacts = ROOT / "data" / "artifacts"
    if not artifacts.exists():
        print(f"{artifacts} not found", file=sys.stderr)
        return 1

    audits = audit_arms(artifacts, ROOT / "data" / "reports")

    tables = ROOT / "data" / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    print("Table 3")
    print(f"{'Arm':<10}{'Samples':>9}{'FAIL':>7}{'WARN':>7}   decomposition")
    matrix = [("arm", "check", "severity", "n")]
    for arm in ARMS:
        a = audits[arm]
        counts: dict[tuple[str, str], int] = {}
        for f in a["findings"]:
            counts[(f.check, f.severity.value)] = counts.get((f.check, f.severity.value), 0) + 1
        matrix.extend((arm, c, s, n) for (c, s), n in sorted(counts.items()))
        detail = ", ".join(f"{c} {s}={n}" for (c, s), n in sorted(counts.items()))
        print(f"{arm:<10}{a['samples']:>9}{a['fail']:>7}{a['warn']:>7}   {detail}")

    with open(tables / "table_audit_matrix.csv", "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(matrix)

    rows = per_sample(artifacts)
    with open(tables / "table_per_sample.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    table4(rows)
    print(f"\nreports -> {ROOT / 'data' / 'reports'}\ntables  -> {tables}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
