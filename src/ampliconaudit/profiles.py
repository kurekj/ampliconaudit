"""Built-in profiles.

``qiime2_dada2`` is the reference implementation: it audits a 16S/18S rRNA
pipeline built on QIIME 2 and DADA2 with reference-based chimera removal and
BLAST-based species confirmation. It is the profile used for the results
reported in the accompanying paper, and the worked example for writing your
own.
"""
from __future__ import annotations

from .profile import InvariantSpec, Profile, ProvenanceSpec, StepContractSpec

#: Species-level identity threshold, in percent. A BLAST hit at or above this
#: identity is evidence that a species-level call was available.
SPECIES_IDENTITY_THRESHOLD = 98.7

QIIME2_DADA2 = Profile(
    name="qiime2-dada2",
    description=(
        "16S/18S rRNA pipeline: reference-based chimera removal (vsearch), "
        "DADA2 denoising, BLAST species confirmation."
    ),
    sample_marker="classification_summary.json",
    contracts=[
        StepContractSpec(
            name="step_contract:chimera",
            # Pipelines commonly prefix per-sample files with the sample name;
            # {name} expands to the basename of the sample key.
            artifact="{name}.chimera_stats.json",
            required_fields=["mode", "input_reads", "output_reads"],
            # A pinned tool version that silently dropped an unsupported flag
            # is exactly how this check earns its place: the step reported
            # success while copying its input to its output unchanged.
            expected={"mode": "uchime_ref"},
            monotonic=[("output_reads", "input_reads")],
            suspicious_zero=["chimeric_reads"],
        ),
    ],
    provenance=[
        ProvenanceSpec(
            name="provenance:dada2",
            artifact="dada2_invocation.json",
        ),
    ],
    invariants=[
        InvariantSpec(
            name="cohort:species_confirmation",
            evidence_artifact="blast_16s_raw.tsv",
            evidence_column=2,  # pident in BLAST tabular format 6
            evidence_threshold=SPECIES_IDENTITY_THRESHOLD,
            outcome_artifact="classification_summary.json",
            outcome_field="blast_16s_confirmed",
            message=(
                f"hits at >= {SPECIES_IDENTITY_THRESHOLD}% identity exist, yet no "
                f"species was confirmed anywhere in the cohort"
            ),
        ),
    ],
)

BUILTIN: dict[str, Profile] = {
    QIIME2_DADA2.name: QIIME2_DADA2,
}


def get(name: str) -> Profile:
    """Look up a built-in profile by name."""
    try:
        return BUILTIN[name]
    except KeyError:
        available = ", ".join(sorted(BUILTIN)) or "(none)"
        raise KeyError(f"unknown profile {name!r}; available: {available}") from None
