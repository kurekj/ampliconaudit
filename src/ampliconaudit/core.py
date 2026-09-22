"""Core data model: findings, severities, and the artifact reader.

The audit never re-processes sequencing data. It reads only the artifacts a
pipeline has already written, which is what makes it cheap enough to run after
every batch. A corrupt or unreadable artifact is itself a silent failure, so
readers return errors as findings instead of raising.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


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


def scalar(text: str) -> Any:
    """Turn a YAML or TSV scalar into int, float, bool, None or str."""
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1]
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", ""):
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


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
        for (value,) in self.iter_tsv_columns(relative, (column,)):
            yield value

    def iter_tsv_columns(self, relative: Path | str,
                         columns: Sequence[int]) -> Iterable[tuple[str, ...]]:
        """Stream several columns of a TSV at once, as tuples of strings."""
        p = self.root / relative
        if not p.exists():
            return
        need = max(columns) if columns else 0
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) > need:
                        yield tuple(parts[c] for c in columns)
        except (UnicodeDecodeError, OSError):
            return

    def read_tsv_table(self, relative: Path | str) -> tuple[Optional[list[dict]], Optional[str]]:
        """Read a header-led TSV, such as a QIIME 2 export, into row dicts.

        The first line is the header; ``#``-prefixed lines, such as the
        ``#q2:types`` line of a QIIME 2 metadata export, are skipped. Values
        are converted to numbers where they parse as such, so that a step
        contract can compare the columns of a row the way it compares the
        fields of a JSON record.
        """
        p = self.root / relative
        if not p.exists():
            return None, "file not found"
        try:
            header: Optional[list[str]] = None
            rows: list[dict] = []
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if not line.strip() or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if header is None:
                        header = [h.strip() for h in parts]
                        continue
                    rows.append({h: scalar(v) for h, v in zip(header, parts)})
            if header is None:
                return None, "empty table"
            return rows, None
        except (UnicodeDecodeError, OSError) as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def read_qza_action_parameters(self, relative: Path | str) -> tuple[Optional[dict], Optional[str]]:
        """Read the parameters of the action that produced a QIIME 2 artifact.

        Every ``.qza``/``.qzv`` is a zip archive carrying its own provenance;
        ``<uuid>/provenance/action/action.yaml`` lists, under ``parameters:``,
        every parameter of the action with the value it actually ran with,
        defaults included. This is QIIME 2's own record of *what ran*; the
        provenance check compares it with what was configured. Only the flat
        ``- key: value`` entries of that block are read, which is all the check
        needs, so no YAML library is required.
        """
        p = self.root / relative
        if not p.exists():
            return None, "file not found"
        try:
            with zipfile.ZipFile(p) as z:
                names = [n for n in z.namelist()
                         if n.endswith("/provenance/action/action.yaml") and n.count("/") == 3]
                if not names:
                    return None, "no provenance/action/action.yaml in archive"
                text = z.read(names[0]).decode("utf-8")
        except (zipfile.BadZipFile, OSError, UnicodeDecodeError) as exc:
            return None, f"{type(exc).__name__}: {exc}"

        params: dict[str, Any] = {}
        block_indent = -1
        for line in text.splitlines():
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if block_indent < 0:
                if line.strip() == "parameters:":
                    block_indent = indent
                continue
            s = line.strip()
            # YAML puts the items of a list at the indentation of their key or
            # deeper; the block ends at the next key at or above that level.
            if indent < block_indent or (indent == block_indent and not s.startswith("- ")):
                break
            if not s.startswith("- "):
                continue  # continuation of a structured value, not a flat parameter
            key, sep, value = s[2:].partition(":")
            if sep and key.strip():
                params[key.strip()] = scalar(value)
        return params, None

    def discover_samples(self, marker: str, target: str = "") -> list[str]:
        """Sample keys are directories containing ``marker``, relative to root."""
        base = self.root / target if target else self.root
        if not base.exists():
            return []
        return sorted(
            str(p.parent.relative_to(self.root)).replace("\\", "/")
            for p in base.rglob(marker)
        )
