# Usage

## Command line

```
ampliconaudit ARTIFACTS_DIR [options]
```

| option | effect |
|---|---|
| `--profile NAME` | built-in profile (default `qiime2-dada2`) |
| `--profile-file PATH` | JSON or YAML profile; overrides `--profile` |
| `--target SUBDIR` | audit only one subdirectory of `ARTIFACTS_DIR` |
| `--json PATH` | write findings as JSON |
| `--quiet` | print only the summary line |
| `--list-profiles` | list built-in profiles and exit |

Findings at severity FAIL go to stderr, WARN to stdout, so `--quiet` plus a redirect
gives you failures alone.

## Expected artifact layout

The audit discovers samples by looking for a marker file. With the bundled profile the
marker is `classification_summary.json`, so a cohort looks like:

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

## Writing a profile

A profile has four parts.

```json
{
  "name": "my-pipeline",
  "description": "what this pipeline is",
  "sample_marker": "summary.json",
  "contracts": [ ... ],
  "provenance": [ ... ],
  "invariants": [ ... ]
}
```

`{name}` inside any artifact path expands to the sample's directory name, which covers
pipelines that prefix per-sample files (`sample-01.chimera_stats.json`).

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
| `monotonic` | `[smaller, larger]` pairs; a filter cannot emit more than it received |
| `suspicious_zero` | legal at zero but implausible; produces WARN, not FAIL |

Keep the two apart. Reviewers stop reading a report once it has produced a few
false alarms, and at that point the audit has stopped working.

### Configuration provenance

Assert that configured parameters reached the executed call. The pipeline must write a
record of the invocation:

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
It is worth it: this is the only class that catches a parameter which is computed,
logged and then silently dropped. The configured value is visible in the config file
and in the log, so it survives review, while the tool itself runs on its defaults.

### Cohort invariants

Assert a statistical expectation across the whole cohort. Some failures are invisible
per sample and obvious in aggregate.

```json
{
  "name": "cohort:species_confirmation",
  "evidence_artifact": "blast_16s_raw.tsv",
  "evidence_column": 2,
  "evidence_threshold": 98.7,
  "outcome_artifact": "classification_summary.json",
  "outcome_field": "blast_16s_confirmed",
  "message": "high-identity hits exist, yet nothing was confirmed"
}
```

This reads: if any sample has a BLAST hit at >= 98.7 % identity (column 2 of tabular
format 6), then `blast_16s_confirmed` summed over the cohort cannot be zero. Both can
be individually plausible; together they cannot be true.

## Continuous use

```bash
run_pipeline.py "$COHORT"
ampliconaudit artifacts/ --target "$COHORT" --json "reports/$COHORT.json"
```

At 70 ms for 50 samples the audit costs nothing next to the pipeline itself, so it
can stay on for every cohort.
