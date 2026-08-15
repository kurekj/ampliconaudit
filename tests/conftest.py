"""Fixtures building synthetic artifact trees.

Each fixture writes the artifacts a pipeline would leave behind, in a state
that is either healthy or affected by one specific silent failure. Building
them from scratch keeps the tests independent of any real dataset.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sample(root: Path, name: str, *, chimera_mode: str, chimeric_reads: int,
            dada2_passed: dict, dada2_config: dict, confirmed: int,
            best_identity: float) -> None:
    """Write one sample's artifacts."""
    d = root / name
    _write(d / "classification_summary.json",
           {"blast_16s_confirmed": confirmed, "total_asvs": 100})
    _write(d / f"{name}.chimera_stats.json",
           {"mode": chimera_mode, "input_reads": 1000,
            "output_reads": 1000 - chimeric_reads, "chimeric_reads": chimeric_reads})
    _write(d / "dada2_invocation.json",
           {"passed_kwargs": dada2_passed, "expected_from_config": dada2_config})
    (d / "blast_16s_raw.tsv").write_text(
        f"asv1\tref1\t{best_identity}\t250\t0\t0\n"
        f"asv2\tref2\t91.0\t250\t0\t0\n",
        encoding="utf-8",
    )


HEALTHY_DADA2 = {"max_ee": 2.0, "trunc_q": 2, "pooling_method": "independent"}


def _cohort(tmp_path: Path, subdir: str, **kwargs) -> Path:
    """Build one cohort in its own subdirectory.

    pytest hands the same ``tmp_path`` to every fixture within a test, so
    cohorts written straight into it overwrite one another as soon as a test
    asks for two of them.
    """
    root = tmp_path / subdir
    for i in (1, 2, 3):
        _sample(root, f"S{i}", **kwargs)
    return root


@pytest.fixture
def healthy_cohort(tmp_path: Path) -> Path:
    """Everything ran as configured."""
    return _cohort(tmp_path, "healthy",
                   chimera_mode="uchime_ref", chimeric_reads=120,
                   dada2_passed=dict(HEALTHY_DADA2), dada2_config=dict(HEALTHY_DADA2),
                   confirmed=40, best_identity=99.6)


@pytest.fixture
def chimera_skipped_cohort(tmp_path: Path) -> Path:
    """The chimera step reported success without running the tool."""
    return _cohort(tmp_path, "chimera_skipped",
                   chimera_mode="legacy_skip", chimeric_reads=0,
                   dada2_passed=dict(HEALTHY_DADA2), dada2_config=dict(HEALTHY_DADA2),
                   confirmed=40, best_identity=99.6)


@pytest.fixture
def dropped_params_cohort(tmp_path: Path) -> Path:
    """Configured DADA2 parameters never reached the call."""
    return _cohort(tmp_path, "dropped_params",
                   chimera_mode="uchime_ref", chimeric_reads=120,
                   dada2_passed={"max_ee": 2.0}, dada2_config=dict(HEALTHY_DADA2),
                   confirmed=40, best_identity=99.6)


@pytest.fixture
def no_confirmation_cohort(tmp_path: Path) -> Path:
    """High-identity hits exist, yet nothing was confirmed anywhere."""
    return _cohort(tmp_path, "no_confirmation",
                   chimera_mode="uchime_ref", chimeric_reads=120,
                   dada2_passed=dict(HEALTHY_DADA2), dada2_config=dict(HEALTHY_DADA2),
                   confirmed=0, best_identity=100.0)
    return tmp_path
