# Validation data

Everything needed to reproduce the five-arm ablation reported in the paper.

```bash
pip install -e . scipy
python scripts/reproduce.py
```

That rebuilds `reports/` and `tables/` from `artifacts/` and prints Tables 3
and 4 of the paper. It takes a few seconds; nothing is re-sequenced.

## artifacts/

The files the audit reads, for all five arms (`baseline`, `F1`, `F2`, `F3`,
`all`) over 50 samples each, so 250 sample snapshots:

| file | what the audit takes from it |
|---|---|
| `<sample>.chimera_stats.json` | step contract: tool mode, read counts |
| `dada2_invocation.json` | provenance: configured vs passed parameters |
| `classification_summary.json` | cohort invariant: species confirmations |
| `blast_16s_raw.tsv` | cohort invariant: hit identities |

The five arms differ only in three environment variables, one per repair:

| arm | `CHIMERA_MODE` | `LCA_IDENTITY_MARGIN` | `DADA2_PASS_PARAMS` |
|---|---|---|---|
| `baseline` | `legacy_skip` | `0` | `false` |
| `F1` | `uchime_ref` | `0` | `false` |
| `F2` | `legacy_skip` | `0.5` | `false` |
| `F3` | `legacy_skip` | `0` | `true` |
| `all` | `uchime_ref` | `0.5` | `true` |

`legacy_skip` is the silent failure itself: the step writes
`chimeric_reads: 0`, leaves `output_reads` equal to `input_reads`, records no
`vsearch_cmd`, and reports success.

## accessions.tsv

The 50 sequencing runs: 48 human gut samples from three public studies and two
ZymoBIOMICS mock-community libraries.

| bioproject | condition | samples |
|---|---|---|
| PRJNA420417 | atherosclerosis | 16 |
| PRJNA732664 | coeliac disease | 16 |
| PRJNA763023 | colorectal cancer | 16 |
| PRJNA1084203 | ZymoBIOMICS mock (Zymo.R1) | 1 |
| PRJNA1365733 | ZymoBIOMICS mock (Zymo.R2) | 1 |

All runs are paired-end 2x250 nt or longer and cover the V3-V4 region, which we
confirmed per cohort from the merged-read length distribution rather than from
the metadata annotation. To fetch the reads:

```bash
cut -f2 data/accessions.tsv | tail -n +2 | while read acc; do
    fasterq-dump --split-files "$acc"
done
```

## reports/

One `audit.json` per arm, written by `scripts/reproduce.py`. These are the
FAIL and WARN counts in Table 3.

## tables/

| file | content |
|---|---|
| `table_audit_matrix.csv` | findings per arm, check and severity |
| `table_per_sample.csv` | per-sample ASV counts, species confirmations and chimera rate |

## What is not here

Raw FASTQ and merged reads are not redistributed; they are public under the
accessions above. The reference databases are named with their versions in
Table 2 of the paper.
