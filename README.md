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
chimeras were removed. In the cohorts we later measured, chimeras accounted for
**12.5-22.7 % of reads**, all of it flowing into denoising, classification and every
downstream result built on them.

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

The core has **no external dependencies**; it reads JSON and TSV with the standard
library. That is deliberate: an audit must run wherever the pipeline runs, without
dragging in a dependency tree of its own. PyYAML is optional, and only needed for
YAML profiles.

## Use

```bash
# audit a cohort with the bundled QIIME 2 / DADA2 profile
ampliconaudit artifacts/

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

report = profiles.get("qiime2-dada2").audit(ArtifactReader("artifacts/"))
print(report.n_fail, "failures across", len(report.samples), "samples")
```

## Adapting it to your pipeline

A profile is data, not code: it names the files your pipeline writes and what must
hold inside them. See [`examples/qiime2-dada2.json`](examples/qiime2-dada2.json) for
the bundled profile expressed as a file, and [`docs/usage.md`](docs/usage.md) for the
field reference.

## Cost

Auditing 50 samples takes **70 ms end to end**, including interpreter startup. Nothing
is re-processed; only artifacts are read. The audit can be left switched on
permanently.

## Validation

On a five-arm ablation over 48 gut samples from three independent public studies plus
two mock-community runs, the audit reported 250 failures against the pipeline before
repair and **zero** after all repairs. Each intermediate arm reported failures for
precisely its still-missing repair and none other.

The artifacts behind that, all 250 sample snapshots, are in [`data/`](data/), so
the tables in the paper can be rebuilt from scratch:

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
