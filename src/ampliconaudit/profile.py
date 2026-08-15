"""Profiles bind the generic checks to one pipeline's artifact layout.

A profile is data, not code: it names the files a pipeline writes, the fields
inside them and the thresholds that make a value implausible. Adapting the
audit to a different pipeline means writing a profile, not modifying the
checks.

Profiles can be declared in Python (see :mod:`ampliconaudit.profiles`) or
loaded from a JSON/YAML file with :func:`load_profile_file`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .core import ArtifactReader, AuditReport, Finding
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


@dataclass
class ProvenanceSpec:
    """One provenance check: which invocation record to compare against config."""

    name: str
    artifact: str
    executed_key: str = "passed_kwargs"
    configured_key: str = "expected_from_config"


@dataclass
class InvariantSpec:
    """One cohort invariant, expressed over two artifacts.

    ``evidence_*`` locates raw evidence (a column in a TSV crossing a
    threshold); ``outcome_*`` locates the aggregate the evidence should have
    produced (a counter in a JSON summary).
    """

    name: str
    evidence_artifact: str
    evidence_column: int
    evidence_threshold: float
    outcome_artifact: str
    outcome_field: str
    message: str


@dataclass
class Profile:
    """A complete description of one pipeline's auditable surface."""

    name: str
    sample_marker: str
    contracts: list[StepContractSpec] = field(default_factory=list)
    provenance: list[ProvenanceSpec] = field(default_factory=list)
    invariants: list[InvariantSpec] = field(default_factory=list)
    description: str = ""

    def audit(self, reader: ArtifactReader, target: str = "") -> AuditReport:
        """Run every check this profile declares over a cohort."""
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
                ))
            for spec in self.provenance:
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
                evidence=_threshold_evidence(reader, spec),
                outcome=_counter_outcome(reader, spec),
                message=spec.message,
            ))
        return report


def _threshold_evidence(reader: ArtifactReader, spec: InvariantSpec) -> Callable[[str], bool]:
    def evidence(sample: str) -> bool:
        for raw in reader.iter_tsv_column(reader.resolve(sample, spec.evidence_artifact),
                                          spec.evidence_column):
            try:
                if float(raw) >= spec.evidence_threshold:
                    return True
            except ValueError:
                continue
        return False
    return evidence


def _counter_outcome(reader: ArtifactReader, spec: InvariantSpec) -> Callable[[str], float]:
    def outcome(sample: str) -> float:
        data, _ = reader.read_json(reader.resolve(sample, spec.outcome_artifact))
        if not data:
            return 0.0
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
        contracts=[StepContractSpec(
            name=c["name"],
            artifact=c["artifact"],
            required_fields=list(c.get("required_fields", [])),
            expected=dict(c.get("expected", {})),
            monotonic=[tuple(pair) for pair in c.get("monotonic", [])],
            suspicious_zero=list(c.get("suspicious_zero", [])),
        ) for c in data.get("contracts", [])],
        provenance=[ProvenanceSpec(
            name=p["name"],
            artifact=p["artifact"],
            executed_key=p.get("executed_key", "passed_kwargs"),
            configured_key=p.get("configured_key", "expected_from_config"),
        ) for p in data.get("provenance", [])],
        invariants=[InvariantSpec(
            name=i["name"],
            evidence_artifact=i["evidence_artifact"],
            evidence_column=int(i["evidence_column"]),
            evidence_threshold=float(i["evidence_threshold"]),
            outcome_artifact=i["outcome_artifact"],
            outcome_field=i["outcome_field"],
            message=i["message"],
        ) for i in data.get("invariants", [])],
    )
