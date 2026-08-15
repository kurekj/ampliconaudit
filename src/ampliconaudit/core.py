"""Core data model: findings, severities, and the artifact reader.

The audit never re-processes sequencing data. It reads only the artifacts a
pipeline has already written, which is what makes it cheap enough to run after
every batch. A corrupt or unreadable artifact is itself a silent failure, so
readers return errors as findings instead of raising.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional


class Severity(str, Enum):
    """FAIL means the result is known to be wrong or degraded.

    WARN means the result is suspicious but may be legitimate; it is for
    conditions a human should look at, not for conditions that invalidate the
    run. Keeping the two apart matters: a report that raises false alarms stops
    being read, and at that point the audit has stopped working.
    """

    FAIL = "FAIL"
    WARN = "WARN"


@dataclass(frozen=True)
class Finding:
    """One audit result, tied to the check that produced it."""

    check: str
    severity: Severity
    message: str
    sample: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        where = self.sample or "(cohort)"
        return f"[{self.severity.value}] {self.check} {where}: {self.message}"


@dataclass
class AuditReport:
    """Findings from one audit run, plus the cohort it covered."""

    samples: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def n_fail(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.FAIL)

    @property
    def n_warn(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.WARN)

    @property
    def clean(self) -> bool:
        return self.n_fail == 0

    def exit_code(self) -> int:
        """0 clean, 1 at least one FAIL, 2 no samples found.

        Exit codes make the audit usable as a gate in a CI pipeline or a
        Makefile, which is the point of running it after every batch.
        """
        if not self.samples:
            return 2
        return 1 if self.n_fail else 0

    def to_json(self, indent: int = 2) -> str:
        return json.dumps([f.to_dict() for f in self.findings],
                          indent=indent, ensure_ascii=False)

    def extend(self, findings: Iterable[Finding]) -> None:
        self.findings.extend(findings)


class ArtifactReader:
    """Reads pipeline artifacts under a root directory.

    Every accessor returns ``(value, error)`` rather than raising, because an
    artifact that cannot be parsed is a finding, not a crash.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    @staticmethod
    def resolve(sample: str, artifact: str) -> str:
        """Expand ``{name}`` in an artifact template to the sample's basename.

        Pipelines commonly prefix per-sample files with the sample name
        (``SRR6331821.chimera_stats.json``), so a profile must be able to say
        ``{name}.chimera_stats.json`` rather than hard-coding one layout.
        """
        return f"{sample}/{artifact.format(name=Path(sample).name)}"

    def read_json(self, relative: Path | str) -> tuple[Optional[dict], Optional[str]]:
        p = self.root / relative
        if not p.exists():
            return None, "file not found"
        try:
            return json.loads(p.read_text(encoding="utf-8")), None
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def iter_tsv_column(self, relative: Path | str, column: int) -> Iterable[str]:
        """Stream one column of a TSV without loading the file into memory.

        BLAST hit tables routinely reach hundreds of megabytes; the invariant
        checks only need one column, and often only until the first match.
        """
        p = self.root / relative
        if not p.exists():
            return
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) > column:
                        yield parts[column]
        except (UnicodeDecodeError, OSError):
            return

    def discover_samples(self, marker: str, target: str = "") -> list[str]:
        """Sample keys are directories containing ``marker``, relative to root."""
        base = self.root / target if target else self.root
        if not base.exists():
            return []
        return sorted(
            str(p.parent.relative_to(self.root)).replace("\\", "/")
            for p in base.rglob(marker)
        )
