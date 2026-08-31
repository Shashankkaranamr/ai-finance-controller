from __future__ import annotations

from pathlib import Path

import pytest

from recon.generate.derive import generate
from recon.generate.narration import SPLIT_EVAL
from recon.generate.world import GenConfig
from recon.resolve import pipeline


# 24 days is 6 settlement cycles -- enough for cross-cycle refunds and a
# matured reserve release to exist, small enough to keep the suite fast. The
# full 88-day world is exercised by the gate run, not by every test.
TEST_DAYS = 24


@pytest.fixture(scope="session")
def generated(tmp_path_factory) -> Path:
    """A small generated dev seed, built once per test session."""
    data_dir = tmp_path_factory.mktemp("data") / "dev"
    generate(GenConfig(seed="dev", n_days=TEST_DAYS), data_dir)
    return data_dir


@pytest.fixture(scope="session")
def generated_eval(tmp_path_factory) -> Path:
    """The HELD-OUT seed: a different world AND held-out narration families."""
    data_dir = tmp_path_factory.mktemp("data_eval") / "eval"
    generate(GenConfig(seed="eval", n_days=TEST_DAYS, split=SPLIT_EVAL), data_dir)
    return data_dir


@pytest.fixture(scope="session")
def result(generated, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("out") / "dev"
    return pipeline.run(generated, out_dir)


@pytest.fixture(scope="session")
def result_eval(generated_eval, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("out_eval") / "eval"
    return pipeline.run(generated_eval, out_dir)
