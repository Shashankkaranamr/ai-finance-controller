"""Schema drift: what the resolver may claim when a source view did not load.

BRIEF Sec 8 names "column renamed" as a failure to engineer against, and the
answer at ingest is `extra="forbid"` plus quarantine. That keeps the batch alive.
What it did NOT do was tell the resolver to stop reasoning from the absence of
rows it never read -- so renaming one column in `bank.jsonl` published 21
MISSING_BANK_CREDIT breaks against a statement that had simply never been loaded,
each asserting "Every credit in the statement was read" (F-018).

The property under test is one sentence: AN ABSENCE IS ONLY EVIDENCE WHEN THE
VIEW THAT WOULD HAVE CARRIED THE ROW LOADED COMPLETELY.

Every case works on a COPY of a generated seed in tmp_path. Nothing here reads or
writes `data/generated/` in the working tree (invariant 13, F-011), and every
case runs on both seeds (invariant 12).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from recon.ingest.load import BANK_VIEW, BOOKS_VIEW, LINES_VIEW, SETTLEMENTS_VIEW
from recon.resolve import pipeline

# One column per view whose loss is unmistakable: each is REQUIRED by its model,
# so renaming it fails every row of that view and nothing else.
RENAMES = {
    BANK_VIEW: ("narration", "description"),
    BOOKS_VIEW: ("order_id", "order_ref"),
    LINES_VIEW: ("entity_id", "entity_ref"),
    SETTLEMENTS_VIEW: ("id", "settlement_ref"),
}

# What each view's rows are the EVIDENCE FOR. A claim in this set asserts that
# something is not there, so it is unsound while that view is short of rows.
ABSENCE_CLAIMS = {
    BANK_VIEW: {"MISSING_BANK_CREDIT"},
    SETTLEMENTS_VIEW: {"UNMATCHED_BANK_CREDIT"},
    LINES_VIEW: {"ROLLUP_MISMATCH", "REFUND_ORPHANED"},
    # books.jsonl carries no absence-based claim: a line whose order_id is not in
    # the books is skipped, never flagged. Its failure mode is silent
    # UNDER-reporting, which SOURCE_VIEW_INCOMPLETE is what surfaces.
    BOOKS_VIEW: set(),
}

SEEDS = ("dev", "eval")


def _drifted(src: Path, dst: Path, view: str) -> Path:
    """Copy a generated seed and rename one column in one view."""
    shutil.copytree(src, dst)
    path = dst / view
    old, new = RENAMES[view]
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            row[new] = row.pop(old)
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return dst


def _seed_dir(request, seed: str) -> Path:
    return request.getfixturevalue("generated" if seed == "dev" else "generated_eval")


def _run_drifted(request, tmp_path, seed: str, view: str):
    data = _drifted(_seed_dir(request, seed), tmp_path / f"{seed}_{view}", view)
    return pipeline.run(data, tmp_path / f"out_{seed}_{view}")


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("view", sorted(RENAMES))
def test_a_renamed_column_never_aborts_the_batch(request, tmp_path, seed, view):
    """Sec 8: quarantine bad rows rather than aborting.

    Renaming `id` in settlements.jsonl used to raise KeyError out of Tier 1 and
    kill the run, because `lines_by_settlement()` is keyed off the LINE view and
    can name a settlement the SETTLEMENT view never loaded.
    """
    result = _run_drifted(request, tmp_path, seed, view)

    assert result.statement.foots, "the statement must still foot on a drifted view"
    for entry in result.journal:
        assert entry.balances


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("view", sorted(RENAMES))
def test_an_incomplete_view_is_reported_as_an_exception_not_just_a_counter(
        request, tmp_path, seed, view):
    """A quarantine count is a diagnostic. It sat in the run summary while the
    queue published false breaks beside it, so completeness has to enter the
    queue itself -- typed, owned, and naming the view."""
    result = _run_drifted(request, tmp_path, seed, view)

    raised = [r for r in result.exceptions if r.code == "SOURCE_VIEW_INCOMPLETE"]
    assert len(raised) == 1, f"expected exactly one incomplete-view exception, got {len(raised)}"
    assert raised[0].subject_id == view
    assert raised[0].is_break
    assert raised[0].owner == "data-eng", "this is a pipeline break, not a treasury one"


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("view", sorted(RENAMES))
def test_no_absence_based_claim_survives_an_incomplete_view(request, tmp_path, seed, view):
    """THE assertion of this fix."""
    result = _run_drifted(request, tmp_path, seed, view)

    published = {r.code for r in result.exceptions}
    leaked = published & ABSENCE_CLAIMS[view]
    assert not leaked, (
        f"{view} lost every row, yet the run still claims {sorted(leaked)} -- "
        "each of which asserts that something was not there")


@pytest.mark.parametrize("seed", SEEDS)
def test_a_never_loaded_statement_is_unconfirmed_not_missing(request, tmp_path, seed):
    """The specific cascade from F-018, and the sentence that made it dangerous.

    Detection is not weakened: every settlement is still flagged. The CODE, the
    severity and the suggested action change, and those are what a human acts on
    -- the same distinction D-031 drew for unparsed credits.
    """
    result = _run_drifted(request, tmp_path, seed, BANK_VIEW)

    assert not result.repo.bank, "the drifted view should have loaded no credits"
    missing = [r for r in result.exceptions if r.code == "MISSING_BANK_CREDIT"]
    assert not missing, (
        "asserted money never arrived, on a statement that was never read")

    unconfirmed = [r for r in result.exceptions if r.code == "SETTLEMENT_UNCONFIRMED"]
    assert unconfirmed, "every settlement should still be flagged, just more weakly"
    assert all(not r.is_break for r in unconfirmed)
    for record in unconfirmed:
        assert "quarantined" in record.hypothesis
        assert "NOT an assertion that the money is missing" in record.hypothesis


@pytest.mark.parametrize("seed", SEEDS)
def test_the_completeness_gate_is_inert_on_a_clean_run(request, tmp_path, seed):
    """The guard must cost nothing when nothing is wrong, or it is not a guard
    but a behaviour change. `metrics.json` is byte-identical either way."""
    clean = pipeline.run(_seed_dir(request, seed), tmp_path / f"clean_{seed}")

    assert not clean.repo.quarantined
    assert not [r for r in clean.exceptions if r.code == "SOURCE_VIEW_INCOMPLETE"]
    assert clean.repo.view_is_complete(BANK_VIEW)
    assert clean.repo.quarantined_by_file() == {}
