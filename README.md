# ampliconaudit

Post-hoc detection of **silent failures** in amplicon taxonomic pipelines: steps that
exit with status 0 and write a well-formed output file while the result is quietly
degraded or wrong.

Conventional error handling reacts to exceptions and non-zero exit codes, and is blind
to this failure mode by construction. `ampliconaudit` reads the artifacts a pipeline has
already written and applies three complementary classes of check.

## Why this exists

A production 16S pipeline invoked `vsearch --uchime2_ref`. The pinned version did not
support that flag, the call failed, and an exception handler copied the input to the
output instead of stopping. Every run reported that chimera removal had completed. No
chimeras were removed. In the cohorts we later measured, chimeras accounted for a
median **11.9 % of reads** (1.5–35.3 %), all of it flowing into denoising,
classification and every downstream result built on them.

Nothing in the logs, exit codes or output file formats was wrong. That is what makes
these failures silent, and why they need a different kind of check.

## The three check classes

| class | question it answers | failure it catches |
|---|---|---|
| **step contract** | did the step run the tool it reports running? | a step that reports success without executing |
| **cohort invariant** | are the cohort statistics internally consistent? | a result that is wrong only in aggregate |
| **configuration provenance** | did every configured parameter reach the call? | parameters computed, logged, then dropped |

Using all three matters because each class is blind to what the other two catch.

## Install

```bash
git clone https://github.com/kurekj/ampliconaudit
cd ampliconaudit
pip install -e .
```

Python 3.9 or newer. Nothing else to install.

The core has **no external dependencies**; it reads JSON, TSV and the zip archives
QIIME 2 artifacts are made of with the standard library. That is deliberate: an audit
must run wherever the pipeline runs, without dragging in a dependency tree of its own.
PyYAML is optional, and only needed for YAML profiles.

## Two bundled profiles

| profile | what it reads | layout |
|---|---|---|
| `qiime2-dada2-wrapper` | the records of the wrapper pipeline around QIIME 2/DADA2 that the paper reports on (`*.chimera_stats.json`, `dada2_invocation.json`, `classification_summary.json`, `blast_16s_raw.tsv`); these are the wrapper's own files, not QIIME 2 output | one directory per sample |
| `qiime2-export` | what a **stock QIIME 2** workflow leaves after `qiime tools export`: the q2-dada2 denoising statistics (`stats.tsv`, one row per sample), the provenance embedded in `table.qza`, and the classifier's `taxonomy.tsv` | one directory per run |

The wrapper profile was called `qiime2-dada2` in release 1.0; that name is still
accepted.

## Use

```bash
# audit a cohort of the wrapper pipeline
ampliconaudit artifacts/

# audit stock QIIME 2 exports (see docs/usage.md for the expected files)
ampliconaudit exports/ --profile qiime2-export

# restrict to one run, write a machine-readable report
ampliconaudit artifacts/ --target run-2024-03 --json audit.json

# use your own profile
ampliconaudit artifacts/ --profile-file my-pipeline.json
```

Exit codes make it usable as a gate:

| code | meaning |
|---|---|
| 0 | clean |
| 1 | at least one FAIL |
| 2 | no samples found |

```bash
ampliconaudit artifacts/ || { echo "pipeline output is not trustworthy"; exit 1; }
```

As a library:

```python
from ampliconaudit import ArtifactReader, profiles

report = profiles.get("qiime2-dada2-wrapper").audit(ArtifactReader("artifacts/"))
print(report.n_fail, "failures across", len(report.samples), "samples")
```

## Adapting it to your pipeline

A profile is data, not code: it names the files your pipeline writes and what must
hold inside them. Both bundled profiles are in [`examples/`](examples/) as files;
[`docs/usage.md`](docs/usage.md) is the field reference, including the two layouts,
the two provenance sources (an invocation record written by the pipeline, or the
`action.yaml` inside a QIIME 2 artifact) and the ratio form of the cohort invariant.

## Cost

Auditing 50 samples takes **70 ms end to end**, including interpreter startup. Nothing
is re-processed; only artifacts are read. The audit can be left switched on
permanently.

## Validation

Four silent failures were found in the production pipeline: a skipped chimera step, a
species consensus diluted by low-identity hits, a taxonomy-rank renaming that zeroed
every species call, and DADA2 parameters that never reached the call. On a six-arm
ablation over 48 gut samples from three independent public studies plus two
mock-community runs (`data/`), the audit reports:

* 250 FAIL against the pipeline before repair (50 step-contract, 200 provenance) and
  **zero** after all repairs, each intermediate arm failing for precisely its
  still-missing repair;
* one cohort-invariant FAIL per cohort when the rank renaming is re-introduced
  (arm `rank`), where no species is confirmed although species-level hits exist;
* the consensus dilution only as a WARN of the ratio invariant added in 1.1
  (confirmed ASVs / ASVs with a species-level hit = 0.32 before repair, 0.96 after);
  the three classes as shipped in 1.0 could not see it;
* the dropped DADA2 parameters as 200 provenance FAIL, although they change no
  result, because the configured values happen to equal the q2-dada2 defaults; a
  parameter that is computed, logged and dropped is the case the provenance class
  exists for, whatever its value.

The mock communities settle what "more species confirmations" means: on the run that
matches the declared ZymoBIOMICS composition, all eight genera and no other are
recovered in every arm, five of eight species are named correctly in every arm but
`rank`, and the repairs change the number of spurious ASVs, not the confirmed species
calls.

The `qiime2-export` profile was run on the exports of a stock QIIME 2 2026.1 workflow
over the same 50 runs (`data/stock/`): 0 FAIL, 12 WARN, all in one study whose
heterogeneity spacers left eight samples with reads one or two nucleotides shorter than
the truncation length, so DADA2 kept under one percent of their reads while the run
completed normally. The warnings point at exactly those samples. Everything behind
these statements is in [`data/`](data/):

```bash
pip install -e . scipy
python scripts/reproduce.py
```

## Citing

See [CITATION.cff](CITATION.cff).

## Funding

Developed within project **GUT-DIET-MAP** (NUTRITECH2/0019/2025), funded by the
National Centre for Research and Development (NCBR), Poland, under the NUTRITECH II
programme, an artificial intelligence system for personalising dietary interventions
and assessing diet-related disease risk from 16S rRNA microbiome profiles.

## License

MIT, see [LICENSE](LICENSE).
