"""The drift registry: properties every scenario must hold, on both seeds.

Written before the live run, because every realism addition this week has found
something and the ones that found the most were checked hardest. The registry is
pre-registered in RUN_LOG (03 Sep) with a prediction per scenario, so a scenario
that quietly stops testing what it claims would corrupt a published number.

The property that nearly went missing is `test_every_scenario_quarantines_its_
whole_view`. S9 originally renamed `amount`->`fees` and `fees`->`amount`, a pure
swap between two real fields. Every key stayed valid, Pydantic accepted the row,
nothing quarantined, and `map_schema` -- which only ever sees quarantined rows --
would never have run. The scenario would have reported a clean pass having tested
nothing at all.

Both seeds throughout (invariant 12). Everything works on tmp copies; nothing here
reads or writes `data/generated/` (invariant 13, F-011).
"""
from __future__ import annotations

import json

import pytest

from recon.generate import drift
from recon.ingest.load import (BANK_VIEW, BOOKS_VIEW, LINES_VIEW, SETTLEMENTS_VIEW,
                               load_all)
from recon.ingest.schemas import (BankCreditRow, BookEntryRow, SettlementLineRow,
                                  SettlementRow)
from recon.resolve import pipeline

MODEL_FOR_VIEW = {
    BOOKS_VIEW: BookEntryRow,
    LINES_VIEW: SettlementLineRow,
    SETTLEMENTS_VIEW: SettlementRow,
    BANK_VIEW: BankCreditRow,
}

# The absence-based claims each view's rows are the evidence for (F-018).
ABSENCE_CLAIMS = {
    BANK_VIEW: {"MISSING_BANK_CREDIT"},
    SETTLEMENTS_VIEW: {"UNMATCHED_BANK_CREDIT"},
    LINES_VIEW: {"ROLLUP_MISMATCH", "REFUND_ORPHANED"},
    BOOKS_VIEW: set(),
}

SEEDS = ("dev", "eval")
NAMES = [s.name for s in drift.SCENARIOS]


def _seed_dir(request, seed):
    return request.getfixturevalue("generated" if seed == "dev" else "generated_eval")


# --- registry shape -----------------------------------------------------------

def test_the_suite_is_the_size_it_was_pre_registered_at():
    """Ten. A scenario added or dropped after the fact changes what the published
    accuracy is out of, so the count is pinned rather than left to drift."""
    assert len(drift.SCENARIOS) == 10
    assert len(set(NAMES)) == 10, "scenario names must be unique -- they key the results"


def test_every_scenario_names_a_real_view_and_real_fields():
    """A typo in a rename would silently produce a scenario that renames nothing,
    quarantine nothing, and pass every other test in this file."""
    for scenario in drift.SCENARIOS:
        model = MODEL_FOR_VIEW[scenario.view]
        for original, _ in scenario.renames:
            assert original in model.model_fields, (
                f"{scenario.name}: {original!r} is not a field on {model.__name__}")


def test_only_the_swap_scenario_renames_onto_a_field_that_already_exists():
    """THE TRAP THAT MADE S9 TEST NOTHING.

    Renaming a column to a name the model already declares keeps the row valid, so
    it never quarantines and `map_schema` never runs. S9 does it deliberately -- it
    is the swap under test -- and pairs it with a third rename that forces the
    quarantine. Any OTHER scenario doing this is a silent no-op.
    """
    for scenario in drift.SCENARIOS:
        fields = set(MODEL_FOR_VIEW[scenario.view].model_fields)
        collides = {new for _, new in scenario.renames if new in fields}
        if scenario.name == "S9_settlements_swap":
            assert collides, "S9 must still exercise a name-on-name collision"
        else:
            assert not collides, (
                f"{scenario.name}: renames onto existing field(s) {sorted(collides)}; "
                "that view will validate cleanly and the scenario will test nothing")


# --- behaviour, on both seeds -------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_every_scenario_quarantines_its_whole_view(request, tmp_path, seed, name):
    """`map_schema` only ever sees quarantined rows. A scenario whose view still
    loads is a scenario that tests nothing, and it would report as a pass."""
    scenario = drift.BY_NAME[name]
    src = _seed_dir(request, seed)
    repo = load_all(drift.apply(scenario, src, tmp_path / name))

    lost = repo.quarantined_by_file()
    assert lost.get(scenario.view, 0) > 0, f"{name} quarantined nothing"
    assert set(lost) == {scenario.view}, "a scenario must disturb exactly one view"
    assert not repo.view_is_complete(scenario.view)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_truth_mapping_is_total_and_inverts_every_rename(request, tmp_path, seed, name):
    """The scoring key. If truth is wrong the accuracy number measures our
    transcription, so it is derived from the file rather than hand-written."""
    scenario = drift.BY_NAME[name]
    src = _seed_dir(request, seed)
    truth = drift.truth_mapping(scenario, src)
    observed = drift.observed_columns(scenario, src)

    assert sorted(truth) == sorted(observed), "truth must cover every observed column"
    for original, new in scenario.renames:
        assert truth[new] == original
    # And it must actually describe the file that `apply` writes.
    drifted = drift.apply(scenario, src, tmp_path / name)
    rows = [json.loads(line) for line in
            drifted.joinpath(scenario.view).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert set(rows[0]) <= set(truth), "the drifted file carries a column truth omits"


@pytest.mark.parametrize("seed", SEEDS)
def test_applying_a_scenario_never_mutates_the_source(request, tmp_path, seed):
    """Every other gate measures against the generated seed. A scenario is a view
    of it, never a change to it."""
    src = _seed_dir(request, seed)
    before = {p.name: p.read_bytes() for p in sorted(src.glob("*.jsonl"))}
    for scenario in drift.SCENARIOS:
        drift.apply(scenario, src, tmp_path / f"m_{scenario.name}")
    after = {p.name: p.read_bytes() for p in sorted(src.glob("*.jsonl"))}
    assert before == after


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_drift_is_deterministic(request, tmp_path, seed, name):
    """Same seed, same scenario, byte-identical output (invariant 2). The registry
    carries no RNG, and this is what keeps it that way."""
    scenario = drift.BY_NAME[name]
    src = _seed_dir(request, seed)
    one = drift.apply(scenario, src, tmp_path / f"{name}_a")
    two = drift.apply(scenario, src, tmp_path / f"{name}_b")
    assert (one.joinpath(scenario.view).read_bytes()
            == two.joinpath(scenario.view).read_bytes())


# --- the F-018 guard, now over ten shapes instead of four ---------------------

@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_no_drifted_view_produces_a_false_absence_claim(request, tmp_path, seed, name):
    """Rules-only, no adjudicator. Whatever the model does later, the deterministic
    floor must hold: a view we could not read supports no claim about what is
    missing from it."""
    scenario = drift.BY_NAME[name]
    result = pipeline.run(drift.apply(scenario, _seed_dir(request, seed), tmp_path / name),
                          tmp_path / f"out_{name}")

    published = {r.code for r in result.exceptions}
    leaked = published & ABSENCE_CLAIMS[scenario.view]
    assert not leaked, f"{name}: still claims {sorted(leaked)} about a view it never read"
    assert [r for r in result.exceptions if r.code == "SOURCE_VIEW_INCOMPLETE"]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_the_batch_completes_and_links_nothing_wrong(request, tmp_path, seed, name):
    """Sec 8: quarantine rather than abort. And precision is the number that must
    survive a drifted input, because a link made on misread data is the one failure
    the ledger cannot absorb."""
    scenario = drift.BY_NAME[name]
    result = pipeline.run(drift.apply(scenario, _seed_dir(request, seed), tmp_path / name),
                          tmp_path / f"out_{name}")

    assert result.statement.foots
    for entry in result.journal:
        assert entry.balances
    assert result.metrics.linkage_precision.bps == 10_000, (
        f"{name}: a drifted view produced a wrong link")
