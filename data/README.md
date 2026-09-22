# Validation data

Everything needed to reproduce the ablation, the mock-community scoring and the
stock-QIIME 2 audit reported in the paper.

```bash
pip install -e . scipy
python scripts/reproduce.py
```

That rebuilds `reports/` and `tables/` from `artifacts/` and `stock/` and prints
Tables 3–6 of the paper. It takes a few seconds; nothing is re-sequenced.

## artifacts/

The files the audit reads, for all six arms (`baseline`, `F1`, `F2`, `F3`, `rank`,
`all`) over 50 samples each, so 300 sample snapshots:

| file | what the audit takes from it |
|---|---|
| `<sample>.chimera_stats.json` | step contract: tool mode, read counts |
| `dada2_invocation.json` | provenance: configured vs passed parameters |
| `classification_summary.json` | cohort invariant: species confirmations |
| `blast_16s_raw.tsv` | cohort invariant: hit identities |

The two mock samples additionally carry `table_species.csv` and `table_genus.csv`,
the pipeline's final per-ASV and per-genus tables, which `scripts/score_mock.py`
compares with the declared composition in `mock_expected.json`.

The arms differ only in four environment variables of the pipeline, one per repair:

| arm | `CHIMERA_MODE` | `LCA_IDENTITY_MARGIN` | `DADA2_PASS_PARAMS` | `TAXDUMP_RANK_ALIAS` |
|---|---|---|---|---|
| `baseline` | `legacy_skip` | `0` | `false` | `true` |
| `F1` | `uchime_ref` | `0` | `false` | `true` |
| `F2` | `legacy_skip` | `0.5` | `false` | `true` |
| `F3` | `legacy_skip` | `0` | `true` | `true` |
| `rank` | `uchime_ref` | `0.5` | `true` | `false` |
| `all` | `uchime_ref` | `0.5` | `true` | `true` |

`legacy_skip` is the silent failure itself: the step writes
`chimeric_reads: 0`, leaves `output_reads` equal to `input_reads`, records no
`vsearch_cmd`, and reports success. `TAXDUMP_RANK_ALIAS=false` re-introduces the
fourth failure (the NCBI taxonomy renamed the rank `superkingdom` to `domain` and the
lineage resolver stopped at the first rank, so no ASV could reach species consensus)
with every other repair active; `baseline` keeps the rank alias, because without it
nothing is confirmed and the other three failures cannot be told apart.

## mock_expected.json

The declared composition of the ZymoBIOMICS Microbial Community Standard (D6300) by
16S copy number, with the synonyms of current nomenclature. Species that the V3–V4
region cannot separate from a neighbour are *not* synonyms: the scoring is strict.

## accessions.tsv

The 50 sequencing runs: 48 human gut samples from three public studies and two
libraries deposited as ZymoBIOMICS mock communities.

| bioproject | condition | samples |
|---|---|---|
| PRJNA420417 | atherosclerosis | 16 |
| PRJNA732664 | coeliac disease | 16 |
| PRJNA763023 | colorectal cancer | 16 |
| PRJNA1084203 | ZymoBIOMICS mock (Zymo.R1) | 1 |
| PRJNA1365733 | ZymoBIOMICS mock (Zymo.R2) | 1 |

All runs are paired-end 2x250 nt or longer and cover the V3-V4 region, which we
confirmed per cohort from the merged-read length distribution rather than from
the metadata annotation. Only Zymo.R2 matches the declared composition (the eight
declared genera are 99.9 % of its reads); in Zymo.R1 they are 1.3 %, so it is kept
in the ablation as a sample but cannot serve as ground truth. To fetch the reads:

```bash
cut -f2 data/accessions.tsv | tail -n +2 | while read acc; do
    fasterq-dump --split-files "$acc"
done
```

## stock/

The exports of a stock QIIME 2 2026.1 workflow over the same 50 runs, one directory
per cohort (`qiime tools import` → `cutadapt trim-paired` → `dada2 denoise-paired`,
trunc 230/220, defaults otherwise → `feature-classifier classify-consensus-blast`
against SILVA 138.1 → `qiime tools export`): `stats.tsv`, `taxonomy.tsv`, the
`table.qza`, `stats.qza`, `rep-seqs.qza` and `taxonomy.qza` artifacts, and the
`dada2_config.json` holding the configured DADA2 parameters that the `qiime2-export`
profile compares with the provenance inside `table.qza`. `stock/commands.sh` is the
exact command sequence.

## reports/

One `audit.json` per arm (and per stock run under `reports/stock/`), written by
`scripts/reproduce.py`. These are the FAIL and WARN counts in Tables 3 and 6.

## tables/

| file | content |
|---|---|
| `table_audit_matrix.csv` | findings per arm, check and severity |
| `table_per_sample.csv` | per-sample ASV counts, species confirmations and chimera rate |
| `table_mock.csv` | mock-community scores per arm and sample |

## What is not here

Raw FASTQ and merged reads are not redistributed; they are public under the
accessions above. The reference databases are named with their versions in
Table 2 of the paper.
