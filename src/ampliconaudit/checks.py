"""The three check classes.

Each class detects a failure mode the other two are blind to, so they are
meant to be used together:

* a step contract catches a step that did not run the tool it claims to have run;
* a cohort invariant catches a result that is internally inconsistent across
  samples even though every individual sample looks plausible;
* a provenance check catches configuration that never reached the executed call.

The functions below are pipeline-agnostic. A profile supplies the artifact
names, field names and thresholds; see :mod:`ampliconaudit.profile`.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from .core import ArtifactReader, Finding, Severity


def _count(value: Any) -> Optional[float]:
    """A finite, non-negative number, or None when ``value`` is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        return None
    return value


def contract_findings(
    data: dict,
    where: str,
    sample: Optional[str],
    *,
    check_name: str,
    required_fields: Sequence[str] = (),
    expected: Optional[dict[str, Any]] = None,
    monotonic: Sequence[tuple[str, str]] = (),
    suspicious_zero: Sequence[str] = (),
    suspicious_equal: Sequence[tuple[str, str]] = (),
    suspicious_fraction: Sequence[tuple[str, str, float]] = (),
) -> list[Finding]:
    """The assertions of a step contract, applied to one record.

    ``data`` is a JSON object or one row of a table; ``where`` names the
    artifact in messages. Shared by the per-sample-file and the per-row forms
    of :func:`step_contract`.
    """
    findings: list[Finding] = []
    for name in required_fields:
        if name not in data:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{where}: required field '{name}' missing", sample))

    for name, want in (expected or {}).items():
        got = data.get(name)
        if got != want:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{where}: '{name}' is {got!r}, expected {want!r} "
                                    "(the step did not execute the tool it reports)", sample))

    # Every counter a comparison relies on must be a valid count; a value that
    # is present but not a number is as much a silent failure as a wrong one.
    compared = {f for pair in monotonic for f in pair} | {f for pair in suspicious_equal for f in pair} \
        | {f for t in suspicious_fraction for f in t[:2]}
    for name in sorted(compared):
        if name in data and _count(data[name]) is None:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{where}: '{name}' is {data[name]!r}, not a valid count",
                                    sample))

    for smaller, larger in monotonic:
        lo, hi = _count(data.get(smaller)), _count(data.get(larger))
        if lo is not None and hi is not None and lo > hi:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{where}: {smaller}={lo} exceeds {larger}={hi} "
                                    "(a filtering step cannot add records)", sample))

    for name in suspicious_zero:
        if data.get(name) == 0:
            findings.append(Finding(check_name, Severity.WARN,
                                    f"{where}: '{name}' is 0: legal but implausible, "
                                    f"check the reference database", sample))

    for after, before in suspicious_equal:
        a, b = _count(data.get(after)), _count(data.get(before))
        if a is not None and b is not None and a == b:
            findings.append(Finding(check_name, Severity.WARN,
                                    f"{where}: {after}={a} equals {before}={b}: the step "
                                    "removed nothing, legal but implausible", sample))

    for part, whole, floor in suspicious_fraction:
        a, b = _count(data.get(part)), _count(data.get(whole))
        if a is not None and b is not None and b > 0 and a / b < floor:
            findings.append(Finding(check_name, Severity.WARN,
                                    f"{where}: {part}={a} is {a / b:.1%} of {whole}={b}, below "
                                    f"{floor:.0%}: the step kept almost nothing, legal but implausible",
                                    sample))
    return findings


def step_contract(
    reader: ArtifactReader,
    sample: str,
    artifact: str,
    *,
    check_name: str,
    required_fields: Sequence[str] = (),
    expected: Optional[dict[str, Any]] = None,
    monotonic: Sequence[tuple[str, str]] = (),
    suspicious_zero: Sequence[str] = (),
    suspicious_equal: Sequence[tuple[str, str]] = (),
    suspicious_fraction: Sequence[tuple[str, str, float]] = (),
    data: Optional[dict] = None,
) -> list[Finding]:
    """Assert that a step left evidence of having actually run.

    ``expected`` pins fields to required values (e.g. the tool mode a step must
    have used). ``monotonic`` names ``(smaller, larger)`` field pairs that a
    filtering step cannot violate: a filter cannot emit more reads than it was
    given. ``suspicious_zero`` names counters that are legal but implausible at
    zero and therefore warrant a WARN rather than a FAIL; ``suspicious_equal``
    names ``(after, before)`` pairs whose equality means the step removed
    nothing, the same condition for a pipeline that records counts before and
    after a step rather than the difference; ``suspicious_fraction`` names
    ``(part, whole, floor)`` triples for a step that kept almost nothing
    (``part/whole`` below ``floor``), which is how a run that completed on a
    handful of reads announces itself.

    The record is read from ``artifact`` under the sample directory unless
    ``data`` is given, in which case it is one row of a per-run table and
    ``artifact`` only names that table in messages.
    """
    if data is None:
        data, err = reader.read_json(reader.resolve(sample, artifact))
        if data is None:
            return [Finding(check_name, Severity.FAIL,
                            f"{artifact}: {err}; no evidence the step ran", sample)]
    return contract_findings(data, artifact, sample, check_name=check_name,
                             required_fields=required_fields, expected=expected,
                             monotonic=monotonic, suspicious_zero=suspicious_zero,
                             suspicious_equal=suspicious_equal,
                             suspicious_fraction=suspicious_fraction)


def provenance_findings(
    executed: dict,
    configured: dict,
    *,
    check_name: str,
    sample: Optional[str],
) -> list[Finding]:
    """Compare what a step ran with against what was configured for it."""
    findings: list[Finding] = []
    for name, want in configured.items():
        if name not in executed:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"parameter '{name}' from configuration was NOT passed "
                                    f"to the call", sample))
        elif executed[name] != want:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"parameter '{name}': called with {executed[name]!r}, "
                                    f"configuration says {want!r}", sample))
    return findings


def config_provenance(
    reader: ArtifactReader,
    sample: str,
    artifact: str,
    *,
    check_name: str,
    executed_key: str = "passed_kwargs",
    configured_key: str = "expected_from_config",
) -> list[Finding]:
    """Assert that every configured parameter reached the executed call.

    This is the only class that catches a parameter which is computed, logged
    and then silently dropped before invocation. The configured value stays
    visible in the config file and in the log, so review does not catch it,
    while the tool itself runs on its defaults.

    This form reads an invocation record the pipeline writes itself, holding
    the parameters it passed and the parameters it computed from configuration.
    """
    data, err = reader.read_json(reader.resolve(sample, artifact))
    if data is None:
        return [Finding(check_name, Severity.FAIL,
                        f"{artifact}: {err}; cannot tell what the step was invoked with",
                        sample)]

    executed = data.get(executed_key, {}) or {}
    configured = data.get(configured_key, {}) or {}
    return provenance_findings(executed, configured, check_name=check_name, sample=sample)


def qza_provenance(
    reader: ArtifactReader,
    run: str,
    artifact: str,
    *,
    check_name: str,
    configured: Optional[dict[str, Any]],
) -> list[Finding]:
    """Assert that a QIIME 2 action ran with the configured parameters.

    QIIME 2 records, inside every artifact it writes, the parameters of the
    action that produced it, defaults included. ``configured`` holds the values
    the analyst intended; a parameter absent from the record, or recorded with
    another value, is a FAIL. A parameter that was dropped and happens to equal
    the library default is invisible here, because the record holds effective
    values: that case needs the invocation record of :func:`config_provenance`.
    """
    relative = f"{run}/{artifact}" if run else artifact
    if configured is None:
        return [Finding(check_name, Severity.FAIL,
                        "the configured parameters cannot be read; nothing to compare the "
                        "action record with", run or None)]
    if not configured:
        return [Finding(check_name, Severity.WARN,
                        "no configured parameters given; the action record was not compared",
                        run or None)]
    executed, err = reader.read_qza_action_parameters(relative)
    if executed is None:
        return [Finding(check_name, Severity.FAIL,
                        f"{artifact}: {err}; cannot tell what the action was invoked with",
                        run or None)]
    return provenance_findings(executed, configured, check_name=check_name,
                               sample=run or None)


def cohort_invariant(
    samples: Sequence[str],
    *,
    check_name: str,
    evidence: Callable[[str], Optional[float]],
    outcome: Callable[[str], Optional[float]],
    message: str,
    min_outcome_ratio: Optional[float] = None,
    zero_severity: Severity = Severity.FAIL,
) -> list[Finding]:
    """Assert a statistical expectation that must hold across a whole cohort.

    Some failures are invisible per sample and obvious in aggregate. If the
    evidence for an outcome exists somewhere in the cohort but the outcome
    never occurs anywhere in it, the two cannot both be right, regardless of
    how plausible each individual sample looks. That is a FAIL.

    ``evidence`` reports how much evidence a sample contains (a count; any
    positive value means the evidence exists); ``outcome`` reports how often
    the outcome actually occurred. Either returns ``None`` when its artifact
    cannot be read, which is a FAIL for that sample and excludes it from the
    sums: unavailable evidence is not zero evidence. ``zero_severity`` lets a
    profile downgrade the zero case to a WARN where the implication is a
    heuristic rather than a certainty. With ``min_outcome_ratio`` the invariant
    also asks that the outcome summed over the cohort not fall below that
    fraction of the summed evidence; the zero case is the ratio at 0. A
    shortfall is a WARN, because the ratio a healthy cohort attains is an
    empirical quantity whose threshold has to be calibrated, whereas zero is
    not.
    """
    findings: list[Finding] = []
    total_evidence = total_outcome = 0.0
    n_ok = 0
    for s in samples:
        e, o = evidence(s), outcome(s)
        if e is None or o is None:
            what = "evidence" if e is None else "outcome"
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{what} artifact cannot be read; the sample is excluded "
                                    "from the invariant", s))
            continue
        total_evidence += e
        total_outcome += o
        n_ok += 1
    if total_evidence > 0 and total_outcome == 0:
        findings.append(Finding(check_name, zero_severity,
                                f"{message} (cohort of {n_ok} samples)", None))
    elif (min_outcome_ratio is not None and total_evidence > 0
            and total_outcome / total_evidence < min_outcome_ratio):
        findings.append(Finding(check_name, Severity.WARN,
                                f"outcome/evidence ratio {total_outcome:.0f}/{total_evidence:.0f} = "
                                f"{total_outcome / total_evidence:.2f} is below {min_outcome_ratio} "
                                f"(cohort of {n_ok} samples)", None))
    return findings
