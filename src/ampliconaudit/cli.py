"""Command-line interface.

    ampliconaudit ARTIFACTS_DIR [--profile NAME | --profile-file PATH]
                  [--target SUBDIR] [--json REPORT] [--quiet]

Exit code 0 means clean, 1 means at least one FAIL, 2 means no samples were
found. The codes are what make the audit usable as a gate in CI or a Makefile.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import profiles
from .core import ArtifactReader, Severity
from .profile import load_profile_file


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ampliconaudit",
        description="Detect silent failures in amplicon taxonomic pipelines.",
    )
    ap.add_argument("artifacts", type=Path,
                    help="root directory holding per-sample pipeline artifacts")
    ap.add_argument("--profile", default="qiime2-dada2",
                    help="built-in profile name (default: qiime2-dada2)")
    ap.add_argument("--profile-file", type=Path, default=None,
                    help="path to a JSON/YAML profile; overrides --profile")
    ap.add_argument("--target", default="",
                    help="restrict the audit to a subdirectory of ARTIFACTS_DIR")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the findings to this file as JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="print only the summary line")
    ap.add_argument("--list-profiles", action="store_true",
                    help="list built-in profiles and exit")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_profiles:
        for name, prof in sorted(profiles.BUILTIN.items()):
            print(f"{name}\n    {prof.description}")
        return 0

    profile = (load_profile_file(args.profile_file) if args.profile_file
               else profiles.get(args.profile))

    report = profile.audit(ArtifactReader(args.artifacts), args.target)

    if not report.samples:
        where = args.artifacts / args.target if args.target else args.artifacts
        print(f"No samples found under {where} "
              f"(looking for {profile.sample_marker})", file=sys.stderr)
        return report.exit_code()

    if not args.quiet:
        for finding in report.findings:
            stream = sys.stderr if finding.severity is Severity.FAIL else sys.stdout
            print(finding, file=stream)

    print(f"{profile.name}: {len(report.samples)} samples, "
          f"{report.n_fail} FAIL, {report.n_warn} WARN")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(report.to_json(), encoding="utf-8")
        print(f"report written to {args.json}")

    return report.exit_code()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
