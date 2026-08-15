"""ampliconaudit: post-hoc detection of silent failures in amplicon pipelines.

A silent failure is a step that exits with status 0 and writes a well-formed
output file while the result is quietly degraded or wrong. Exception handling
cannot see it. This package reads the artifacts a pipeline leaves behind and
applies three complementary classes of check: step contracts, cohort
invariants, and configuration-to-execution provenance.

Typical use::

    from ampliconaudit import ArtifactReader, profiles

    report = profiles.get("qiime2-dada2").audit(ArtifactReader("artifacts/"))
    if not report.clean:
        raise SystemExit(report.exit_code())
"""
from .core import ArtifactReader, AuditReport, Finding, Severity
from .profile import (
    InvariantSpec,
    Profile,
    ProvenanceSpec,
    StepContractSpec,
    load_profile_file,
    profile_from_dict,
)
from . import checks, profiles

__version__ = "1.0.0"

__all__ = [
    "ArtifactReader",
    "AuditReport",
    "Finding",
    "Severity",
    "Profile",
    "StepContractSpec",
    "ProvenanceSpec",
    "InvariantSpec",
    "load_profile_file",
    "profile_from_dict",
    "checks",
    "profiles",
    "__version__",
]
