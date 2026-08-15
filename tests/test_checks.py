"""Each check must fire on its own failure mode and stay silent on the others.

The second half matters as much as the first: a check that also fires on
unrelated failures cannot be used to attribute a cause, and an audit whose
findings cannot be attributed gets ignored.
"""
from __future__ import annotations

from pathlib import Path

from ampliconaudit import ArtifactReader, Severity, profiles


def audit(root: Path):
    return profiles.get("qiime2-dada2").audit(ArtifactReader(root))


def checks_that_failed(report) -> set[str]:
    return {f.check for f in report.findings if f.severity is Severity.FAIL}


def test_healthy_cohort_is_clean(healthy_cohort: Path):
    report = audit(healthy_cohort)
    assert report.samples, "fixture must produce discoverable samples"
    assert report.n_fail == 0
    assert report.clean
    assert report.exit_code() == 0


def test_skipped_chimera_step_is_detected(chimera_skipped_cohort: Path):
    report = audit(chimera_skipped_cohort)
    assert "step_contract:chimera" in checks_that_failed(report)
    assert report.exit_code() == 1


def test_skipped_chimera_does_not_trip_other_checks(chimera_skipped_cohort: Path):
    failed = checks_that_failed(audit(chimera_skipped_cohort))
    assert "provenance:dada2" not in failed
    assert "cohort:species_confirmation" not in failed


def test_dropped_parameters_are_detected(dropped_params_cohort: Path):
    report = audit(dropped_params_cohort)
    assert "provenance:dada2" in checks_that_failed(report)
    messages = " ".join(f.message for f in report.findings)
    assert "trunc_q" in messages and "pooling_method" in messages


def test_dropped_parameters_do_not_trip_other_checks(dropped_params_cohort: Path):
    failed = checks_that_failed(audit(dropped_params_cohort))
    assert "step_contract:chimera" not in failed
    assert "cohort:species_confirmation" not in failed


def test_missing_confirmation_is_detected_only_in_aggregate(no_confirmation_cohort: Path):
    report = audit(no_confirmation_cohort)
    assert "cohort:species_confirmation" in checks_that_failed(report)
    cohort_findings = [f for f in report.findings
                       if f.check == "cohort:species_confirmation"]
    # The failure is a property of the cohort, so it must not be attributed to
    # any single sample - each one looks individually plausible.
    assert all(f.sample is None for f in cohort_findings)
    assert len(cohort_findings) == 1


def test_missing_confirmation_does_not_trip_other_checks(no_confirmation_cohort: Path):
    failed = checks_that_failed(audit(no_confirmation_cohort))
    assert "step_contract:chimera" not in failed
    assert "provenance:dada2" not in failed


def test_zero_chimeras_after_real_run_is_a_warning_not_a_failure(tmp_path: Path):
    """Zero chimeras is legal but implausible in PCR amplicons."""
    import json
    d = tmp_path / "S1"
    d.mkdir(parents=True)
    (d / "classification_summary.json").write_text(
        json.dumps({"blast_16s_confirmed": 5}), encoding="utf-8")
    (d / "S1.chimera_stats.json").write_text(
        json.dumps({"mode": "uchime_ref", "input_reads": 1000,
                    "output_reads": 1000, "chimeric_reads": 0}), encoding="utf-8")
    (d / "dada2_invocation.json").write_text(
        json.dumps({"passed_kwargs": {}, "expected_from_config": {}}), encoding="utf-8")

    report = audit(tmp_path)
    assert report.n_fail == 0
    assert report.n_warn == 1
    assert report.exit_code() == 0


def test_filter_cannot_emit_more_reads_than_it_received(tmp_path: Path):
    import json
    d = tmp_path / "S1"
    d.mkdir(parents=True)
    (d / "classification_summary.json").write_text(
        json.dumps({"blast_16s_confirmed": 5}), encoding="utf-8")
    (d / "S1.chimera_stats.json").write_text(
        json.dumps({"mode": "uchime_ref", "input_reads": 100,
                    "output_reads": 500, "chimeric_reads": 3}), encoding="utf-8")
    (d / "dada2_invocation.json").write_text(
        json.dumps({"passed_kwargs": {}, "expected_from_config": {}}), encoding="utf-8")

    report = audit(tmp_path)
    assert "step_contract:chimera" in checks_that_failed(report)


def test_corrupt_artifact_is_a_finding_not_a_crash(healthy_cohort: Path):
    """An unreadable artifact is itself a silent failure."""
    (healthy_cohort / "S1" / "S1.chimera_stats.json").write_text("{ not json",
                                                             encoding="utf-8")
    report = audit(healthy_cohort)
    assert "step_contract:chimera" in checks_that_failed(report)


def test_empty_directory_reports_no_samples(tmp_path: Path):
    report = audit(tmp_path)
    assert report.samples == []
    assert report.exit_code() == 2
