"""Profiles bind the generic checks to one pipeline's artifact layout.

A profile is data, not code: it names the files a pipeline writes, the fields
inside them and the thresholds that make a value implausible. Adapting the
audit to a different pipeline means writing a profile, not modifying the
checks.

Two layouts are supported. In the ``sample-dirs`` layout every sample is a
directory holding its own artifacts, which is how a wrapper pipeline that
processes samples one at a time leaves them. In the ``run-table`` layout a
run directory holds one table with one row per sample (the denoising
statistics QIIME 2 exports) next to run-level artifacts such as the feature
table and the taxonomy; the rows are the samples.

Profiles can be declared in Python (see :mod:`ampliconaudit.profiles`) or
loaded from a JSON/YAML file with :func:`load_profile_file`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .core import ArtifactReader, AuditReport, Finding, Severity
from . import checks


@dataclass
class StepContractSpec:
    """One step-contract check: which artifact, and what must hold in it."""

    name: str
    artifact: str
    required_fields: list[str] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    monotonic: list[tuple[str, str]] = field(default_factory=list)
    suspicious_zero: list[str] = field(default_factory=list)
    suspicious_equal: list[tuple[str, str]] = field(default_factory=list)
    suspicious_fraction: list[tuple[str, str, float]] = field(default_factory=list)


@dataclass
class ProvenanceSpec:
    """One provenance check: which record to compare against configuration.

    ``source`` is ``invocation`` for a JSON record the pipeline writes itself
    (``executed_key`` and ``configured_key`` name its two blocks) or ``qza``
    for the ``action.yaml`` QIIME 2 embeds in every artifact, in which case
    the configured values come from ``expected`` and/or from the JSON file
    named by ``configured_file`` (relative to the run directory).
    """

    name: str
    artifact: str
    source: str = "invocation"
    executed_key: str = "passed_kwargs"
    configured_key: str = "expected_from_config"
    expected: dict[str, Any] = field(default_factory=dict)
    configured_file: Optional[str] = None


@dataclass
class InvariantSpec:
    """One cohort invariant, expressed over two artifacts.

    ``evidence_*`` locates raw evidence (a column in a TSV crossing a
    threshold); the evidence *count* of a sample is the number of distinct
    values of ``evidence_id_column`` (``None``: the number of rows) that cross
    it. ``outcome_*`` locates the aggregate the evidence should have produced:
    a counter in a JSON summary (``outcome_field``) or, when
    ``outcome_pattern`` is set, the number of rows of a TSV whose column
    ``outcome_column`` matches that regular expression.

    With ``evidence_pattern`` a row counts as evidence only if column
    ``evidence_pattern_column`` also matches that regular expression (for a
    taxonomy table: only rows that reach a given rank). ``zero_severity``
    (``FAIL`` or ``WARN``) is the severity of the zero case.

    The invariant fails when evidence exists and the outcome is absent from
    the whole cohort, and warns when ``min_outcome_ratio`` is set and the
    outcome falls below that fraction of the evidence. A sample whose
    evidence or outcome artifact cannot be read is a FAIL of its own and is
    left out of the sums.
    """

    name: str
    evidence_artifact: str
    evidence_column: int
    evidence_threshold: float
    outcome_artifact: str
    outcome_field: str = ""
    message: str = ""
    evidence_id_column: Optional[int] = 0
    outcome_pattern: Optional[str] = None
    outcome_column: int = 1
    min_outcome_ratio: Optional[float] = None
    evidence_pattern: Optional[str] = None
    evidence_pattern_column: int = 1
    zero_severity: str = "FAIL"


@dataclass
class Profile:
    """A complete description of one pipeline's auditable surface."""

    name: str
    sample_marker: str
    contracts: list[StepContractSpec] = field(default_factory=list)
    provenance: list[ProvenanceSpec] = field(default_factory=list)
    invariants: list[InvariantSpec] = field(default_factory=list)
    description: str = ""
    layout: str = "sample-dirs"
    sample_id_column: str = ""

    def audit(self, reader: ArtifactReader, target: str = "") -> AuditReport:
        """Run every check this profile declares over a cohort."""
        if self.layout == "run-table":
            return self._audit_run_table(reader, target)
        if self.layout != "sample-dirs":
            raise ValueError(f"unknown layout {self.layout!r}")

        samples = reader.discover_samples(self.sample_marker, target)
        report = AuditReport(samples=samples)

        for sample in samples:
            for spec in self.contracts:
                report.extend(checks.step_contract(
                    reader, sample, spec.artifact,
                    check_name=spec.name,
                    required_fields=spec.required_fields,
                    expected=spec.expected,
                    monotonic=spec.monotonic,
                    suspicious_zero=spec.suspicious_zero,
                    suspicious_equal=spec.suspicious_equal,
                    suspicious_fraction=spec.suspicious_fraction,
                ))
            for spec in self.provenance:
                if spec.source == "qza":
                    report.extend(checks.qza_provenance(
                        reader, sample, spec.artifact, check_name=spec.name,
                        configured=_configured_values(reader, sample, spec)))
                else:
                    report.extend(checks.config_provenance(
                        reader, sample, spec.artifact,
                        check_name=spec.name,
                        executed_key=spec.executed_key,
                        configured_key=spec.configured_key,
                    ))

        for spec in self.invariants:
            report.extend(checks.cohort_invariant(
                samples,
                check_name=spec.name,
                evidence=_evidence_count(reader, spec, per_sample=True),
                outcome=_outcome_count(reader, spec, per_sample=True),
                message=spec.message,
                min_outcome_ratio=spec.min_outcome_ratio,
                zero_severity=Severity(spec.zero_severity),
            ))
        return report

    def _audit_run_table(self, reader: ArtifactReader, target: str) -> AuditReport:
        """Run-table layout: runs are directories holding the marker table."""
        runs = reader.discover_samples(self.sample_marker, target)
        report = AuditReport()
        for run in runs:
            prefix = f"{run}/" if run not in ("", ".") else ""
            rows, err = reader.read_tsv_table(f"{prefix}{self.sample_marker}")
            if rows is None:
                report.samples.append(run)
                report.extend([Finding("layout:run-table", Severity.FAIL,
                                       f"{self.sample_marker}: {err}", run)])
                continue
            id_col = self.sample_id_column or (next(iter(rows[0])) if rows else "")
            for row in rows:
                sample = f"{prefix}{row.get(id_col, '?')}"
                report.samples.append(sample)
                for spec in self.contracts:
                    report.extend(checks.step_contract(
                        reader, sample, spec.artifact, data=row,
                        check_name=spec.name,
                        required_fields=spec.required_fields,
                        expected=spec.expected,
                        monotonic=spec.monotonic,
                        suspicious_zero=spec.suspicious_zero,
                        suspicious_equal=spec.suspicious_equal,
                        suspicious_fraction=spec.suspicious_fraction,
                    ))
            for spec in self.provenance:
                if spec.source == "qza":
                    report.extend(checks.qza_provenance(
                        reader, run, spec.artifact, check_name=spec.name,
                        configured=_configured_values(reader, run, spec)))
                else:
                    report.extend(checks.config_provenance(
                        reader, run, spec.artifact, check_name=spec.name,
                        executed_key=spec.executed_key,
                        configured_key=spec.configured_key))
            for spec in self.invariants:
                report.extend(checks.cohort_invariant(
                    [run],
                    check_name=spec.name,
                    evidence=_evidence_count(reader, spec, per_sample=False),
                    outcome=_outcome_count(reader, spec, per_sample=False),
                    message=f"{spec.message} [run {run}]",
                    min_outcome_ratio=spec.min_outcome_ratio,
                    zero_severity=Severity(spec.zero_severity),
                ))
        return report


def _relative(reader: ArtifactReader, key: str, artifact: str, per_sample: bool) -> str:
    if per_sample:
        return reader.resolve(key, artifact)
    return f"{key}/{artifact}" if key not in ("", ".") else artifact


def _configured_values(reader: ArtifactReader, key: str,
                       spec: ProvenanceSpec) -> Optional[dict[str, Any]]:
    """The configured values, or None when the configured file cannot be read."""
    configured = dict(spec.expected)
    if spec.configured_file:
        data, _ = reader.read_json(_relative(reader, key, spec.configured_file, False))
        if data is None:
            return None
        configured.update(data)
    return configured


def _evidence_count(reader: ArtifactReader, spec: InvariantSpec,
                    per_sample: bool) -> Callable[[str], Optional[float]]:
    """Number of distinct evidence ids (or rows) crossing the threshold; None if unreadable."""
    pattern = re.compile(spec.evidence_pattern) if spec.evidence_pattern else None

    def evidence(key: str) -> Optional[float]:
        rel = _relative(reader, key, spec.evidence_artifact, per_sample)
        if not (reader.root / rel).exists():
            return None
        cols = [spec.evidence_column]
        if spec.evidence_id_column is not None:
            cols.insert(0, spec.evidence_id_column)
        if pattern is not None:
            cols.append(spec.evidence_pattern_column)
        ids: set[str] = set()
        n = 0
        for parts in reader.iter_tsv_columns(rel, cols):
            value = parts[1] if spec.evidence_id_column is not None else parts[0]
            try:
                if float(value) < spec.evidence_threshold:
                    continue
            except ValueError:
                continue
            if pattern is not None and not pattern.search(parts[-1]):
                continue
            if spec.evidence_id_column is None:
                n += 1
            else:
                ids.add(parts[0])
        return float(n if spec.evidence_id_column is None else len(ids))
    return evidence


def _outcome_count(reader: ArtifactReader, spec: InvariantSpec,
                   per_sample: bool) -> Callable[[str], Optional[float]]:
    """The outcome counter of a sample (or run); None if its artifact is unreadable."""
    if spec.outcome_pattern:
        pattern = re.compile(spec.outcome_pattern)

        def outcome_rows(key: str) -> Optional[float]:
            rel = _relative(reader, key, spec.outcome_artifact, per_sample)
            if not (reader.root / rel).exists():
                return None
            return float(sum(1 for (v,) in reader.iter_tsv_columns(rel, [spec.outcome_column])
                             if pattern.search(v)))
        return outcome_rows

    def outcome(key: str) -> Optional[float]:
        data, _ = reader.read_json(_relative(reader, key, spec.outcome_artifact, per_sample))
        if data is None:
            return None
        value = data.get(spec.outcome_field, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0
    return outcome


def load_profile_file(path: Path | str) -> Profile:
    """Load a profile from JSON, or from YAML when PyYAML is installed."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "YAML profiles need PyYAML: pip install 'ampliconaudit[yaml]'"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return profile_from_dict(data)


def profile_from_dict(data: dict[str, Any]) -> Profile:
    return Profile(
        name=data["name"],
        description=data.get("description", ""),
        sample_marker=data["sample_marker"],
        layout=data.get("layout", "sample-dirs"),
        sample_id_column=data.get("sample_id_column", ""),
        contracts=[StepContractSpec(
            name=c["name"],
            artifact=c["artifact"],
            required_fields=list(c.get("required_fields", [])),
            expected=dict(c.get("expected", {})),
            monotonic=[tuple(pair) for pair in c.get("monotonic", [])],
            suspicious_zero=list(c.get("suspicious_zero", [])),
            suspicious_equal=[tuple(pair) for pair in c.get("suspicious_equal", [])],
            suspicious_fraction=[(t[0], t[1], float(t[2])) for t in c.get("suspicious_fraction", [])],
        ) for c in data.get("contracts", [])],
        provenance=[ProvenanceSpec(
            name=p["name"],
            artifact=p["artifact"],
            source=p.get("source", "invocation"),
            executed_key=p.get("executed_key", "passed_kwargs"),
            configured_key=p.get("configured_key", "expected_from_config"),
            expected=dict(p.get("expected", {})),
            configured_file=p.get("configured_file"),
        ) for p in data.get("provenance", [])],
        invariants=[InvariantSpec(
            name=i["name"],
            evidence_artifact=i["evidence_artifact"],
            evidence_column=int(i["evidence_column"]),
            evidence_threshold=float(i["evidence_threshold"]),
            outcome_artifact=i["outcome_artifact"],
            outcome_field=i.get("outcome_field", ""),
            message=i.get("message", ""),
            evidence_id_column=(None if i.get("evidence_id_column", 0) is None
                                else int(i.get("evidence_id_column", 0))),
            outcome_pattern=i.get("outcome_pattern"),
            outcome_column=int(i.get("outcome_column", 1)),
            min_outcome_ratio=(None if i.get("min_outcome_ratio") is None
                               else float(i["min_outcome_ratio"])),
            evidence_pattern=i.get("evidence_pattern"),
            evidence_pattern_column=int(i.get("evidence_pattern_column", 1)),
            zero_severity=str(i.get("zero_severity", "FAIL")),
        ) for i in data.get("invariants", [])],
    )
