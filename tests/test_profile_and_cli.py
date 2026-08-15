"""Profiles must be declarable as data, and the CLI must be scriptable."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ampliconaudit import ArtifactReader, load_profile_file, profile_from_dict, profiles
from ampliconaudit.cli import main

CUSTOM = {
    "name": "custom",
    "description": "minimal hand-written profile",
    "sample_marker": "classification_summary.json",
    "contracts": [{
        "name": "step_contract:chimera",
        "artifact": "{name}.chimera_stats.json",
        "expected": {"mode": "uchime_ref"},
    }],
}


def test_profile_can_be_declared_as_data(chimera_skipped_cohort: Path):
    report = profile_from_dict(CUSTOM).audit(ArtifactReader(chimera_skipped_cohort))
    assert report.n_fail == 3  # one per sample


def test_profile_loads_from_json_file(tmp_path: Path, chimera_skipped_cohort: Path):
    spec = tmp_path / "custom.json"
    spec.write_text(json.dumps(CUSTOM), encoding="utf-8")
    report = load_profile_file(spec).audit(ArtifactReader(chimera_skipped_cohort))
    assert report.n_fail == 3


def test_unknown_profile_names_the_available_ones():
    with pytest.raises(KeyError) as exc:
        profiles.get("no-such-profile")
    assert "qiime2-dada2" in str(exc.value)


def test_cli_exit_codes_gate_a_pipeline(healthy_cohort: Path, chimera_skipped_cohort: Path,
                                        tmp_path: Path):
    assert main([str(healthy_cohort)]) == 0
    assert main([str(chimera_skipped_cohort)]) == 1
    assert main([str(tmp_path / "does-not-exist")]) == 2


def test_cli_writes_a_machine_readable_report(chimera_skipped_cohort: Path, tmp_path: Path):
    out = tmp_path / "nested" / "report.json"
    assert main([str(chimera_skipped_cohort), "--json", str(out), "--quiet"]) == 1
    findings = json.loads(out.read_text(encoding="utf-8"))
    assert findings and all({"check", "severity", "message"} <= set(f) for f in findings)


def test_cli_lists_builtin_profiles(capsys):
    assert main(["ignored", "--list-profiles"]) == 0
    assert "qiime2-dada2" in capsys.readouterr().out


def test_target_restricts_the_cohort(tmp_path: Path):
    """--target scopes the audit so one bad cohort does not fail an unrelated one."""
    import shutil

    good = tmp_path / "runA" / "S1"
    good.mkdir(parents=True)
    (good / "classification_summary.json").write_text(
        json.dumps({"blast_16s_confirmed": 7}), encoding="utf-8")
    (good / "S1.chimera_stats.json").write_text(
        json.dumps({"mode": "uchime_ref", "input_reads": 10, "output_reads": 9,
                    "chimeric_reads": 1}), encoding="utf-8")
    (good / "dada2_invocation.json").write_text(
        json.dumps({"passed_kwargs": {}, "expected_from_config": {}}), encoding="utf-8")

    bad = tmp_path / "runB" / "S1"
    bad.mkdir(parents=True)
    shutil.copy(good / "classification_summary.json", bad)
    shutil.copy(good / "dada2_invocation.json", bad)
    (bad / "S1.chimera_stats.json").write_text(
        json.dumps({"mode": "legacy_skip", "input_reads": 10, "output_reads": 10,
                    "chimeric_reads": 0}), encoding="utf-8")

    assert main([str(tmp_path), "--target", "runA", "--quiet"]) == 0
    assert main([str(tmp_path), "--target", "runB", "--quiet"]) == 1
