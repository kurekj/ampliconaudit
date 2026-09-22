"""Built-in profiles.

``qiime2-dada2-wrapper`` audits the wrapper pipeline around QIIME 2 and DADA2
that the accompanying paper reports on: the four artifacts it reads are
written by that wrapper (a chimera-step record, a DADA2 invocation record, a
per-sample classification summary and the raw BLAST hit table), not by QIIME 2
or DADA2 themselves. It is the worked example for writing a profile against a
pipeline's own bookkeeping.

``qiime2-export`` audits what a stock QIIME 2 workflow leaves behind after
``qiime tools export``: the denoising statistics of ``q2-dada2`` (one row per
sample), the provenance QIIME 2 embeds in every artifact, and the taxonomy
table of ``q2-feature-classifier``. It needs no change to the workflow.
"""
from __future__ import annotations

from .profile import InvariantSpec, Profile, ProvenanceSpec, StepContractSpec

#: Species-level identity threshold, in percent. A BLAST hit at or above this
#: identity is evidence that a species-level call was available.
SPECIES_IDENTITY_THRESHOLD = 98.7

#: Fraction of the ASVs with species-level evidence that a healthy consensus
#: step is expected to confirm. Calibrated on the ablation in the paper (the
#: repaired pipeline attains 0.90-1.00 per gut sample, the diluted one 0.19-0.81,
#: 0.32 over the cohort); it is a WARN, not a FAIL, for that reason.
CONFIRMATION_RATIO_FLOOR = 0.5

QIIME2_DADA2_WRAPPER = Profile(
    name="qiime2-dada2-wrapper",
    description=(
        "Wrapper pipeline around QIIME 2 and DADA2 (16S/18S rRNA): vsearch "
        "reference-based chimera removal, DADA2 denoising, BLAST species "
        "confirmation. Reads the wrapper's own records, not stock QIIME 2 output."
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
            evidence_id_column=0,  # qseqid: one ASV counts once
            evidence_column=2,  # pident in BLAST tabular format 6
            evidence_threshold=SPECIES_IDENTITY_THRESHOLD,
            outcome_artifact="classification_summary.json",
            outcome_field="blast_16s_confirmed",
            min_outcome_ratio=CONFIRMATION_RATIO_FLOOR,
            message=(
                f"hits at >= {SPECIES_IDENTITY_THRESHOLD}% identity exist, yet no "
                f"species was confirmed anywhere in the cohort"
            ),
        ),
    ],
)

#: Consensus (or classifier confidence) at or above which a feature assigned
#: to at least genus rank counts as evidence that the reference resolves it.
TAXONOMY_CONFIDENCE_THRESHOLD = 0.9

QIIME2_EXPORT = Profile(
    name="qiime2-export",
    description=(
        "Stock QIIME 2 workflow after 'qiime tools export': q2-dada2 denoising "
        "statistics (one row per sample), the action provenance embedded in the "
        "feature table, and the q2-feature-classifier taxonomy."
    ),
    layout="run-table",
    sample_marker="stats.tsv",
    sample_id_column="sample-id",
    contracts=[
        StepContractSpec(
            name="step_contract:dada2",
            artifact="stats.tsv",
            required_fields=["input", "filtered", "denoised", "merged", "non-chimeric"],
            # Each stage of denoise-paired can only remove reads.
            monotonic=[("non-chimeric", "merged"), ("merged", "denoised"),
                       ("denoised", "filtered"), ("filtered", "input")],
            # No chimera removed at all is legal but implausible in PCR
            # amplicons; the same condition the wrapper profile expresses as
            # a zero counter.
            suspicious_equal=[("non-chimeric", "merged")],
            # A sample that keeps under a tenth of its reads through the
            # quality filter has usually been truncated past its read length
            # or is not the amplicon the run assumes; the run still completes.
            suspicious_fraction=[("filtered", "input", 0.1)],
        ),
    ],
    provenance=[
        ProvenanceSpec(
            name="provenance:dada2",
            artifact="table.qza",
            source="qza",
            # The analyst's configured values: put them here or in a
            # dada2_config.json next to the export.
            configured_file="dada2_config.json",
        ),
    ],
    invariants=[
        InvariantSpec(
            name="cohort:species_assignment",
            evidence_artifact="taxonomy.tsv",
            evidence_id_column=None,  # one row per feature already
            evidence_column=2,  # Confidence / Consensus
            evidence_threshold=TAXONOMY_CONFIDENCE_THRESHOLD,
            evidence_pattern=r"g__[^;\s]",  # ...and resolved at least to genus
            evidence_pattern_column=1,
            outcome_artifact="taxonomy.tsv",
            outcome_column=1,  # Taxon
            outcome_pattern=r"s__[^;\s]",  # a non-empty species rank
            # A reference taxonomy without species ranks would look the same,
            # so this is a heuristic and warns rather than fails.
            zero_severity="WARN",
            message=(
                f"features resolved to genus at consensus >= {TAXONOMY_CONFIDENCE_THRESHOLD} "
                "exist, yet no feature carries a species rank anywhere in the run"
            ),
        ),
    ],
)

BUILTIN: dict[str, Profile] = {
    QIIME2_DADA2_WRAPPER.name: QIIME2_DADA2_WRAPPER,
    QIIME2_EXPORT.name: QIIME2_EXPORT,
}

#: Names accepted for compatibility with the 1.0 release.
ALIASES: dict[str, str] = {"qiime2-dada2": QIIME2_DADA2_WRAPPER.name}


def get(name: str) -> Profile:
    """Look up a built-in profile by name (aliases of older names accepted)."""
    name = ALIASES.get(name, name)
    try:
        return BUILTIN[name]
    except KeyError:
        available = ", ".join(sorted(BUILTIN)) or "(none)"
        raise KeyError(f"unknown profile {name!r}; available: {available}") from None
