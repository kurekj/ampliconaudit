"""The 1.1 additions: the outcome-ratio form of the cohort invariant, the
suspicious-equal contract, the run-table layout for stock QIIME 2 exports and
the provenance read from a QIIME 2 artifact's own action record."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from ampliconaudit import ArtifactReader, Severity, profile_from_dict, profiles
from ampliconaudit.cli import main

from conftest import HEALTHY_DADA2, _sample


def _diluted(root: Path, confirmed: int) -> None:
    """Three samples, each with ten ASVs at species-level identity."""
    for i in (1, 2, 3):
        _sample(root, f"S{i}", chimera_mode="uchime_ref", chimeric_reads=120,
                dada2_passed=dict(HEALTHY_DADA2), dada2_config=dict(HEALTHY_DADA2),
                confirmed=confirmed, best_identity=99.6)
        lines = [f"asv{k}\tref{k}\t99.{k}\t250\t0\t0\n" for k in range(10)]
        lines += [f"asv{k}\tref{k}b\t91.0\t250\t0\t0\n" for k in range(10)]  # second hits
        (root / f"S{i}" / "blast_16s_raw.tsv").write_text("".join(lines), encoding="utf-8")


def test_ratio_below_floor_is_a_warning_not_a_failure(tmp_path: Path):
    _diluted(tmp_path, confirmed=3)  # 9 confirmed of 30 evidence ASVs = 0.30
    report = profiles.get("qiime2-dada2-wrapper").audit(ArtifactReader(tmp_path))
    ratio = [f for f in report.findings if f.check == "cohort:species_confirmation"]
    assert len(ratio) == 1 and ratio[0].severity is Severity.WARN
    assert "9/30" in ratio[0].message
    assert report.exit_code() == 0  # a WARN does not fail the gate


def test_ratio_at_or_above_floor_is_silent(tmp_path: Path):
    _diluted(tmp_path, confirmed=9)  # 27 of 30 = 0.90
    report = profiles.get("qiime2-dada2-wrapper").audit(ArtifactReader(tmp_path))
    assert not [f for f in report.findings if f.check == "cohort:species_confirmation"]


def test_evidence_counts_distinct_asvs_not_hits(tmp_path: Path):
    """Fifty hits of one ASV are one piece of evidence, not fifty."""
    _diluted(tmp_path, confirmed=9)
    for i in (1, 2, 3):
        p = tmp_path / f"S{i}" / "blast_16s_raw.tsv"
        p.write_text(p.read_text(encoding="utf-8")
                     + "".join(f"asv0\tref0_{k}\t99.9\t250\t0\t0\n" for k in range(50)),
                     encoding="utf-8")
    report = profiles.get("qiime2-dada2-wrapper").audit(ArtifactReader(tmp_path))
    assert not [f for f in report.findings if f.check == "cohort:species_confirmation"]


def test_old_profile_name_is_still_accepted():
    assert profiles.get("qiime2-dada2") is profiles.get("qiime2-dada2-wrapper")


def test_cli_lists_both_builtin_profiles(capsys):
    assert main(["ignored", "--list-profiles"]) == 0
    out = capsys.readouterr().out
    assert "qiime2-dada2-wrapper" in out and "qiime2-export" in out


# ---------------------------------------------------------------- run-table layout

ACTION_YAML = """\
execution:
    uuid: 0f1b2c3d-0000-4000-8000-000000000001
    runtime:
        start: 2026-09-21T21:00:00
action:
    type: method
    plugin: !ref 'environment:plugins:dada2'
    action: denoise_paired
    inputs:
    -   demultiplexed_seqs: 0f1b2c3d-0000-4000-8000-000000000002
    parameters:
    -   trunc_len_f: 230
    -   trunc_len_r: 220
    -   trim_left_f: 0
    -   max_ee_f: 2.0
    -   max_ee_r: 2.0
    -   trunc_q: 2
    -   pooling_method: independent
    -   chimera_method: consensus
    -   allow_one_off: false
    -   n_threads: 24
    output-name: table
transformers:
    output:
    -   from: BIOMV210Format
"""


def _qza(path: Path, action_yaml: str = ACTION_YAML) -> None:
    uuid = "0f1b2c3d-0000-4000-8000-0000000000aa"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{uuid}/metadata.yaml", f"uuid: {uuid}\ntype: FeatureTable[Frequency]\n")
        z.writestr(f"{uuid}/provenance/action/action.yaml", action_yaml)
        # the ancestors' records live deeper and must not be confused with this one
        z.writestr(f"{uuid}/provenance/artifacts/x/action/action.yaml",
                   "action:\n    parameters:\n    -   decoy: 1\n")


STATS = (
    "sample-id\tinput\tfiltered\tpercentage of input passed filter\tdenoised\tmerged\t"
    "percentage of input merged\tnon-chimeric\tpercentage of input non-chimeric\n"
    "#q2:types\tnumeric\tnumeric\tnumeric\tnumeric\tnumeric\tnumeric\tnumeric\tnumeric\n"
    "S1\t1000\t900\t90.0\t880\t800\t80.0\t760\t76.0\n"
    "S2\t2000\t1800\t90.0\t1750\t1600\t80.0\t1500\t75.0\n"
)

TAXONOMY = (
    "Feature ID\tTaxon\tConsensus\n"
    "f1\td__Bacteria; p__Firmicutes; c__Bacilli; o__Lactobacillales; f__Lactobacillaceae; "
    "g__Limosilactobacillus; s__Limosilactobacillus_fermentum\t1.0\n"
    "f2\td__Bacteria; p__Firmicutes; c__Bacilli; o__Bacillales; f__Bacillaceae; g__Bacillus; s__\t0.95\n"
    "f3\tUnassigned\t0.6\n"
)

CONFIG = {"trunc_len_f": 230, "trunc_len_r": 220, "max_ee_f": 2.0, "trunc_q": 2,
          "pooling_method": "independent", "chimera_method": "consensus"}


def _run(root: Path, stats: str = STATS, taxonomy: str = TAXONOMY,
         config: dict | None = None, action_yaml: str = ACTION_YAML) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "stats.tsv").write_text(stats, encoding="utf-8")
    (root / "taxonomy.tsv").write_text(taxonomy, encoding="utf-8")
    _qza(root / "table.qza", action_yaml)
    (root / "dada2_config.json").write_text(
        json.dumps(CONFIG if config is None else config), encoding="utf-8")
    return root


def test_stock_export_healthy_run_is_clean(tmp_path: Path):
    _run(tmp_path / "runA")
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    assert report.samples == ["runA/S1", "runA/S2"]
    assert report.n_fail == 0 and report.n_warn == 0
    assert report.exit_code() == 0


def test_stock_export_row_contract_catches_a_stage_that_added_reads(tmp_path: Path):
    bad = STATS.replace("S2\t2000\t1800\t90.0\t1750\t1600\t80.0\t1500\t75.0",
                        "S2\t2000\t1800\t90.0\t1750\t1600\t80.0\t1700\t85.0")
    _run(tmp_path / "runA", stats=bad)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    fails = [f for f in report.findings if f.severity is Severity.FAIL]
    assert len(fails) == 1 and fails[0].sample == "runA/S2"
    assert "non-chimeric=1700 exceeds merged=1600" in fails[0].message


def test_stock_export_zero_chimeras_removed_is_a_warning(tmp_path: Path):
    warn = STATS.replace("S1\t1000\t900\t90.0\t880\t800\t80.0\t760\t76.0",
                         "S1\t1000\t900\t90.0\t880\t800\t80.0\t800\t80.0")
    _run(tmp_path / "runA", stats=warn)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    assert report.n_fail == 0 and report.n_warn == 1
    assert report.findings[0].sample == "runA/S1"


def test_qza_provenance_compares_action_record_with_configuration(tmp_path: Path):
    _run(tmp_path / "runA", config={"trunc_len_f": 250, "pooling_method": "pseudo",
                                    "min_fold_parent_over_abundance": 1.0})
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    msgs = [f.message for f in report.findings if f.check == "provenance:dada2"]
    assert len(msgs) == 3
    assert any("trunc_len_f" in m and "230" in m and "250" in m for m in msgs)
    assert any("pooling_method" in m and "'independent'" in m for m in msgs)
    assert any("min_fold_parent_over_abundance" in m and "NOT passed" in m for m in msgs)
    assert all(f.sample == "runA" for f in report.findings if f.check == "provenance:dada2")


def test_qza_provenance_reads_the_artifacts_own_record_not_its_ancestors(tmp_path: Path):
    _run(tmp_path / "runA", config={"decoy": 1})
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    assert any("decoy" in f.message and "NOT passed" in f.message for f in report.findings)


def test_missing_qza_is_a_finding_not_a_crash(tmp_path: Path):
    _run(tmp_path / "runA")
    (tmp_path / "runA" / "table.qza").unlink()
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    assert any(f.check == "provenance:dada2" and "file not found" in f.message
               for f in report.findings)


def test_stock_export_invariant_fires_when_species_rank_is_absent_everywhere(tmp_path: Path):
    truncated = TAXONOMY.replace("s__Limosilactobacillus_fermentum", "s__")
    _run(tmp_path / "runA", taxonomy=truncated)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    inv = [f for f in report.findings if f.check == "cohort:species_assignment"]
    assert len(inv) == 1 and inv[0].severity is Severity.WARN and inv[0].sample is None
    assert "runA" in inv[0].message


def test_run_table_layout_audits_each_run_separately(tmp_path: Path):
    _run(tmp_path / "runA")
    _run(tmp_path / "runB", taxonomy=TAXONOMY.replace("s__Limosilactobacillus_fermentum", "s__"))
    (tmp_path / "runB" / "dada2_config.json").unlink()
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    assert len(report.samples) == 4
    assert report.n_fail == 1 and report.n_warn == 1
    assert main([str(tmp_path), "--profile", "qiime2-export", "--target", "runA", "--quiet"]) == 0
    assert main([str(tmp_path), "--profile", "qiime2-export", "--target", "runB", "--quiet"]) == 1


def test_run_table_profile_can_be_declared_as_data(tmp_path: Path):
    _run(tmp_path / "runA")
    spec = {"name": "mine", "layout": "run-table", "sample_marker": "stats.tsv",
            "sample_id_column": "sample-id",
            "contracts": [{"name": "step_contract:dada2", "artifact": "stats.tsv",
                           "monotonic": [["filtered", "input"]],
                           "suspicious_equal": [["non-chimeric", "merged"]]}],
            "provenance": [{"name": "provenance:dada2", "artifact": "table.qza",
                            "source": "qza", "expected": {"trunc_q": 2}}],
            "invariants": [{"name": "cohort:species_assignment",
                            "evidence_artifact": "taxonomy.tsv", "evidence_column": 2,
                            "evidence_id_column": None, "evidence_threshold": 0.9,
                            "outcome_artifact": "taxonomy.tsv", "outcome_column": 1,
                            "outcome_pattern": "s__[^;\\s]", "message": "no species"}]}
    report = profile_from_dict(spec).audit(ArtifactReader(tmp_path))
    assert report.samples == ["runA/S1", "runA/S2"] and report.n_fail == 0


def test_stock_export_warns_when_the_filter_kept_almost_nothing(tmp_path: Path):
    """A truncation length past the read length drops nearly every read; the run
    still completes and exports a well-formed table."""
    starved = STATS.replace("S1\t1000\t900\t90.0\t880\t800\t80.0\t760\t76.0",
                            "S1\t80000\t201\t0.25\t112\t78\t0.1\t71\t0.09")
    _run(tmp_path / "runA", stats=starved)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    assert report.n_fail == 0 and report.n_warn == 1
    assert "filtered=201" in report.findings[0].message and "0.3%" in report.findings[0].message


# ---------------------------------------------------------------- unreadable or malformed inputs

def test_missing_configured_file_is_a_failure(tmp_path: Path):
    """A comparison against nothing must not read as a clean run."""
    _run(tmp_path / "runA")
    (tmp_path / "runA" / "dada2_config.json").unlink()
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    prov = [f for f in report.findings if f.check == "provenance:dada2"]
    assert len(prov) == 1 and prov[0].severity is Severity.FAIL
    assert report.exit_code() == 1


def test_missing_taxonomy_is_a_failure_not_zero_evidence(tmp_path: Path):
    _run(tmp_path / "runA")
    (tmp_path / "runA" / "taxonomy.tsv").unlink()
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    inv = [f for f in report.findings if f.check == "cohort:species_assignment"]
    assert len(inv) == 1 and inv[0].severity is Severity.FAIL and "cannot be read" in inv[0].message


def test_missing_blast_table_is_a_failure_for_that_sample(healthy_cohort: Path):
    (healthy_cohort / "S2" / "blast_16s_raw.tsv").unlink()
    report = profiles.get("qiime2-dada2-wrapper").audit(ArtifactReader(healthy_cohort))
    inv = [f for f in report.findings if f.check == "cohort:species_confirmation"]
    assert len(inv) == 1 and inv[0].severity is Severity.FAIL and inv[0].sample == "S2"


def test_malformed_or_missing_counts_are_failures(tmp_path: Path):
    bad = STATS.replace("S1\t1000\t900\t90.0\t880\t800\t80.0\t760\t76.0",
                        "S1\t1000\tinvalid\t90.0\t880\t800\t80.0\t760\t76.0")
    _run(tmp_path / "runA", stats=bad)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    msgs = [f.message for f in report.findings if f.severity is Severity.FAIL]
    assert any("'filtered' is 'invalid', not a valid count" in m for m in msgs)
    no_merged = STATS.replace("\tmerged\t", "\tmerged_x\t")
    _run(tmp_path / "runB", stats=no_merged)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path), "runB")
    assert any("required field 'merged' missing" in f.message for f in report.findings)


def test_genus_only_taxonomy_warns_rather_than_fails(tmp_path: Path):
    """High consensus without a species rank anywhere is a heuristic signal only."""
    genus_only = TAXONOMY.replace("s__Limosilactobacillus_fermentum", "s__")
    _run(tmp_path / "runA", taxonomy=genus_only)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    inv = [f for f in report.findings if f.check == "cohort:species_assignment"]
    assert len(inv) == 1 and inv[0].severity is Severity.WARN
    assert report.exit_code() == 0


def test_unassigned_features_are_not_evidence(tmp_path: Path):
    unassigned = "Feature ID\tTaxon\tConsensus\nf1\tUnassigned\t1.0\nf2\td__Bacteria; p__Firmicutes\t1.0\n"
    _run(tmp_path / "runA", taxonomy=unassigned)
    report = profiles.get("qiime2-export").audit(ArtifactReader(tmp_path))
    assert not [f for f in report.findings if f.check == "cohort:species_assignment"]
