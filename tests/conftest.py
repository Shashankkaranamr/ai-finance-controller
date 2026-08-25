from __future__ import annotations

from pathlib import Path

import pytest

from recon.generate.derive import generate
from recon.generate.world import GenConfig
from recon.resolve import pipeline


@pytest.fixture(scope="session")
def generated(tmp_path_factory) -> Path:
    """A small generated dev seed, built once per test session."""
    data_dir = tmp_path_factory.mktemp("data") / "dev"
    generate(GenConfig(seed="dev", n_cycles=6), data_dir)
    return data_dir


@pytest.fixture(scope="session")
def result(generated, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("out") / "dev"
    return pipeline.run(generated, out_dir)
