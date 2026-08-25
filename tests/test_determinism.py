"""Same seed must produce byte-identical output. Increment 0 exit gate, item 6.

BRIEF Sec 8 lists non-deterministic output as a failure mode to engineer against.
Establishing it now, when there is almost no code, is far cheaper than retrofitting
it once a response cache and an LLM are in the path -- and Increment 3's caching
claim depends on this property already holding.
"""
from __future__ import annotations

from pathlib import Path

from recon.generate.derive import generate
from recon.generate.world import GenConfig
from recon.resolve import pipeline


def _generate_into(root: Path, seed: str = "dev") -> Path:
    data_dir = root / "data"
    generate(GenConfig(seed=seed, n_cycles=6), data_dir)
    return data_dir


def test_generator_is_byte_identical_across_runs(tmp_path):
    first = _generate_into(tmp_path / "a")
    second = _generate_into(tmp_path / "b")

    for name in ("books.jsonl", "settlement_lines.jsonl", "settlements.jsonl",
                 "bank.jsonl", "ground_truth.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), \
            f"{name} differs between two runs of the same seed"


def test_metrics_json_is_byte_identical_across_runs(tmp_path):
    data_dir = _generate_into(tmp_path)

    first = pipeline.run(data_dir, tmp_path / "out1")
    second = pipeline.run(data_dir, tmp_path / "out2")

    assert (first.out_dir / "metrics.json").read_bytes() \
        == (second.out_dir / "metrics.json").read_bytes()
    assert first.run_id == second.run_id, "idempotency key must be stable for identical inputs"


def test_audit_log_body_is_byte_identical_across_runs(tmp_path):
    """The header carries the real wall-clock time and is expected to differ.

    Everything after it must not. This is a stronger claim than dropping
    timestamps to make the file compare equal.
    """
    data_dir = _generate_into(tmp_path)

    first = pipeline.run(data_dir, tmp_path / "out1")
    second = pipeline.run(data_dir, tmp_path / "out2")

    body_a = (first.out_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    body_b = (second.out_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()[1:]

    assert body_a == body_b
    assert len(body_a) > 5, "an audit trail of a few lines is not an audit trail"


def test_a_different_seed_produces_different_data(tmp_path):
    """Guards against the seed being ignored, which would make the held-out
    methodology meaningless while every determinism test still passed."""
    dev = _generate_into(tmp_path / "dev", seed="dev")
    other = _generate_into(tmp_path / "eval", seed="eval")

    assert (dev / "bank.jsonl").read_bytes() != (other / "bank.jsonl").read_bytes()


def test_run_id_changes_when_inputs_change(tmp_path):
    data_dir = _generate_into(tmp_path)
    before = pipeline.run(data_dir, tmp_path / "out1").run_id

    bank = data_dir / "bank.jsonl"
    rows = bank.read_text(encoding="utf-8").splitlines()
    bank.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")

    after = pipeline.run(data_dir, tmp_path / "out2").run_id
    assert before != after, "idempotency key must track input content"
