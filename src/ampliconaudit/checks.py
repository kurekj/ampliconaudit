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
) -> list[Finding]:
    """Assert that a step left evidence of having actually run.

    ``expected`` pins fields to required values (e.g. the tool mode a step must
    have used). ``monotonic`` names ``(smaller, larger)`` field pairs that a
    filtering step cannot violate: a filter cannot emit more reads than it was
    given. ``suspicious_zero`` names counters that are legal but implausible at
    zero and therefore warrant a WARN rather than a FAIL.
    """
    data, err = reader.read_json(reader.resolve(sample, artifact))
    if data is None:
        return [Finding(check_name, Severity.FAIL,
                        f"{artifact}: {err}; no evidence the step ran", sample)]

    findings: list[Finding] = []
    for name in required_fields:
        if name not in data:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{artifact}: required field '{name}' missing", sample))

    for name, want in (expected or {}).items():
        got = data.get(name)
        if got != want:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{artifact}: '{name}' is {got!r}, expected {want!r} "
                                    "(the step did not execute the tool it reports)", sample))

    for smaller, larger in monotonic:
        lo, hi = data.get(smaller), data.get(larger)
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
            findings.append(Finding(check_name, Severity.FAIL,
                                    f"{artifact}: {smaller}={lo} exceeds {larger}={hi} "
                                    "(a filtering step cannot add records)", sample))

    for name in suspicious_zero:
        if data.get(name) == 0:
            findings.append(Finding(check_name, Severity.WARN,
                                    f"{artifact}: '{name}' is 0: legal but implausible, "
                                    f"check the reference database", sample))
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
    """
    data, err = reader.read_json(reader.resolve(sample, artifact))
    if data is None:
        return [Finding(check_name, Severity.FAIL,
                        f"{artifact}: {err}; cannot tell what the step was invoked with",
                        sample)]

    executed = data.get(executed_key, {}) or {}
    configured = data.get(configured_key, {}) or {}
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


def cohort_invariant(
    samples: Sequence[str],
    *,
    check_name: str,
    evidence: Callable[[str], bool],
    outcome: Callable[[str], float],
    message: str,
) -> list[Finding]:
    """Assert a statistical expectation that must hold across a whole cohort.

    Some failures are invisible per sample and obvious in aggregate. If the
    evidence for an outcome exists somewhere in the cohort but the outcome
    never occurs anywhere in it, the two cannot both be right, regardless of
    how plausible each individual sample looks.

    ``evidence`` reports whether a sample contains grounds for the outcome;
    ``outcome`` reports how often the outcome actually occurred.
    """
    any_evidence = any(evidence(s) for s in samples)
    total_outcome = sum(outcome(s) for s in samples)
    if any_evidence and total_outcome == 0:
        return [Finding(check_name, Severity.FAIL,
                        f"{message} (cohort of {len(samples)} samples)", None)]
    return []
