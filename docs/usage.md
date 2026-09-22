# Usage

## Command line

```
ampliconaudit ARTIFACTS_DIR [options]
```

| option | effect |
|---|---|
| `--profile NAME` | built-in profile (default `qiime2-dada2-wrapper`; `qiime2-export` for stock QIIME 2 exports) |
| `--profile-file PATH` | JSON or YAML profile; overrides `--profile` |
| `--target SUBDIR` | audit only one subdirectory of `ARTIFACTS_DIR` |
| `--json PATH` | write findings as JSON |
| `--quiet` | print only the summary line |
| `--list-profiles` | list built-in profiles and exit |

Findings at severity FAIL go to stderr and WARN to stdout, so redirecting stdout
(`2>failures.txt >/dev/null`) leaves the failures alone; `--quiet` prints only the
summary line. Exit code 0 means no FAIL; warnings do not change it. The name
`qiime2-dada2` of release 1.0 is still accepted as an alias of `qiime2-dada2-wrapper`.

## Two layouts

### Per-sample directories (`layout: "sample-dirs"`, the default)

The audit discovers samples by looking for a marker file. With the
`qiime2-dada2-wrapper` profile the marker is `classification_summary.json`, so a
cohort looks like:

```
artifacts/
└── run-2024-03/
    ├── sample-01/
    │   ├── classification_summary.json      <- marker
    │   ├── sample-01.chimera_stats.json
    │   ├── dada2_invocation.json
    │   └── blast_16s_raw.tsv
    └── sample-02/
        └── ...
```

Sample keys are directory paths relative to `ARTIFACTS_DIR`, so nesting is free-form.
These four files are written by the wrapper pipeline the profile was built for; QIIME 2
and DADA2 do not write them. Use this layout for any pipeline that keeps its own
per-sample bookkeeping.

### One table per run (`layout: "run-table"`)

A stock QIIME 2 workflow processes a whole run at once and, after
`qiime tools export`, leaves one denoising-statistics table with a row per sample
next to run-level artifacts. The `qiime2-export` profile audits that layout with no
change to the workflow:

```
exports/
└── run-2024-03/
    ├── stats.tsv            <- marker; rows are the samples (qiime tools export of the
    │                           q2-dada2 denoising stats)
    ├── taxonomy.tsv         <- qiime tools export of the FeatureData[Taxonomy]
    ├── table.qza            <- the feature table itself: its provenance is read
    └── dada2_config.json    <- the parameters you configured (see provenance below)
```

Every directory holding the marker table is one run; every row of the table is one
sample (`sample_id_column` names the id column, default the first one). Step contracts
run per row, provenance and invariants per run.

## Writing a profile

A profile has four parts.

```json
{
  "name": "my-pipeline",
  "description": "what this pipeline is",
  "layout": "sample-dirs",
  "sample_marker": "summary.json",
  "contracts": [ ... ],
  "provenance": [ ... ],
  "invariants": [ ... ]
}
```

`{name}` inside any artifact path expands to the sample's directory name, which covers
pipelines that prefix per-sample files (`sample-01.chimera_stats.json`). Two complete
profiles are in [`examples/`](../examples/): `qiime2-dada2-wrapper.json` and
`qiime2-export.json`.

### Step contracts

Assert that a step left evidence of having run.

```json
{
  "name": "step_contract:chimera",
  "artifact": "{name}.chimera_stats.json",
  "required_fields": ["mode", "input_reads", "output_reads"],
  "expected": {"mode": "uchime_ref"},
  "monotonic": [["output_reads", "input_reads"]],
  "suspicious_zero": ["chimeric_reads"]
}
```

| field | meaning |
|---|---|
| `required_fields` | must be present, else FAIL |
| `expected` | must equal the given value, else FAIL |
| `monotonic` | `[smaller, larger]` pairs; a filter cannot emit more than it received; a value that is not a valid count is a FAIL |
| `suspicious_zero` | legal at zero but implausible; produces WARN, not FAIL |
| `suspicious_equal` | `[after, before]` pairs; equal counts mean the step removed nothing; WARN |
| `suspicious_fraction` | `[part, whole, floor]` triples; `part/whole` below `floor` means the step kept almost nothing; WARN |

In the run-table layout the record is a row of the marker table and the field names
are its column names; the `qiime2-export` profile asserts
`input >= filtered >= denoised >= merged >= non-chimeric` on the q2-dada2 statistics
and warns when `non-chimeric == merged`, i.e. when DADA2 removed no chimera at all, and
when `filtered` is below a tenth of `input`, i.e. when the quality filter (which drops
every read shorter than the truncation length) kept almost nothing of a sample.

Keep FAIL and WARN apart. Reviewers stop reading a report once it has produced a few
false alarms, and at that point the audit has stopped working.

### Configuration provenance

Assert that configured parameters reached the executed call. Two sources are supported.

**An invocation record written by the pipeline** (`"source": "invocation"`, the
default):

```json
{
  "passed_kwargs":        {"max_ee": 2.0},
  "expected_from_config": {"max_ee": 2.0, "trunc_q": 2}
}
```

Here `trunc_q` is configured but never passed, so the check reports a FAIL. Declare it
with:

```json
{"name": "provenance:dada2", "artifact": "dada2_invocation.json"}
```

Use `executed_key` and `configured_key` if your pipeline names those blocks differently.
Emitting such a record is the one change a pipeline must make to be auditable this way.
It is worth it: this is the only form that catches a parameter which is computed,
logged and then silently dropped *even when the value it was dropped in favour of is
the library default*.

**The provenance QIIME 2 embeds in every artifact** (`"source": "qza"`):

```json
{"name": "provenance:dada2", "artifact": "table.qza", "source": "qza",
 "configured_file": "dada2_config.json", "expected": {"chimera_method": "consensus"}}
```

Every `.qza` is a zip archive carrying `provenance/action/action.yaml`, which lists the
parameters the producing action ran with, defaults included. The check compares them
with the values you configured, taken from `expected` in the profile and/or from the
JSON file named by `configured_file` in the run directory:

```json
{"trunc_len_f": 230, "trunc_len_r": 220, "max_ee_f": 2.0, "trunc_q": 2,
 "pooling_method": "independent", "chimera_method": "consensus"}
```

A parameter recorded with another value, or absent from the record, is a FAIL; a
`configured_file` that cannot be read is a FAIL too, and an empty set of configured
values is a WARN, because a comparison against nothing must not read as a clean run.
Because the record holds *effective* values, a configured value that was dropped and
happens to equal the default is invisible to this form; only an invocation record
catches that case.

### Cohort invariants

Assert a statistical expectation across the whole cohort. Some failures are invisible
per sample and obvious in aggregate.

```json
{
  "name": "cohort:species_confirmation",
  "evidence_artifact": "blast_16s_raw.tsv",
  "evidence_id_column": 0,
  "evidence_column": 2,
  "evidence_threshold": 98.7,
  "outcome_artifact": "classification_summary.json",
  "outcome_field": "blast_16s_confirmed",
  "min_outcome_ratio": 0.5,
  "message": "high-identity hits exist, yet nothing was confirmed"
}
```

This reads: the *evidence* of a sample is the number of distinct ASVs (column 0 of the
BLAST table) with a hit at >= 98.7 % identity (column 2); the *outcome* is
`blast_16s_confirmed`. If evidence exists anywhere in the cohort and the outcome summed
over the cohort is zero, the invariant is a FAIL: each sample can be individually
plausible, together they cannot be true. With `min_outcome_ratio` the invariant also
warns when the summed outcome falls below that fraction of the summed evidence, which is
how a consensus step that resolves only one ASV in three becomes visible. The zero case
is exact; the ratio is an empirical floor that has to be calibrated (0.5 in the bundled
profile, from the ablation in the paper: a healthy cohort attains 0.90–1.00 per sample,
a diluted one 0.19–0.81), so it is a WARN.

Set `evidence_id_column` to `null` to count rows instead of distinct ids, and
`evidence_pattern` (with `evidence_pattern_column`) to count a row as evidence only when
that column also matches a regular expression. For an outcome that is not a JSON
counter, give `outcome_pattern` and `outcome_column`: the outcome is then the number of
rows of a TSV whose column matches. `qiime2-export` uses both: evidence is a feature
resolved to genus (`g__[^;\s]`) at consensus >= 0.9, the outcome a feature carrying a
species rank (`s__[^;\s]`), and because a reference taxonomy without species ranks would
produce the same picture its zero case is a WARN (`zero_severity`), not a FAIL. A sample
whose evidence or outcome artifact cannot be read is a FAIL of its own and is left out
of the sums: unavailable evidence is not zero evidence.

Invariants relate one evidence artifact to one outcome; an invariant spanning three or
more artifacts must currently be written in Python against `ampliconaudit.checks`.

## Continuous use

```bash
run_pipeline.py "$COHORT"
ampliconaudit artifacts/ --target "$COHORT" --json "reports/$COHORT.json"
```

or, for a stock QIIME 2 run:

```bash
qiime tools export --input-path stats.qza --output-path exports/run-2024-03
qiime tools export --input-path taxonomy.qza --output-path exports/run-2024-03
cp table.qza dada2_config.json exports/run-2024-03/
ampliconaudit exports/ --profile qiime2-export --target run-2024-03
```

At 70 ms for 50 samples the audit costs nothing next to the pipeline itself, so it
can stay on for every cohort.
