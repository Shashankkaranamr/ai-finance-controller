"""The Increment 1 exit gate, as tests.

The generator is the deliverable of this increment, so these are the assertions
that say whether it is faithful -- scale, schema, the deduction stack, the
held-out split, and the one identity everything downstream rests on.

Where a test asserts a BAND rather than a value (scale, intrinsic clean rate), the
band comes from BRIEF Sec 5 and is quoted in the docstring. A band is used because
the exact count is a function of a seeded RNG and pinning it would turn every
tuning change into a test edit, which trains people to update the number instead
of thinking about it.
"""
from __future__ import annotations

import json

from recon.domain.graph import BUILT_TIER, ComponentType, ExceptionType
from recon.domain.rates import MDR_SLABS, Instrument, mdr_rate_bps
from recon.domain.truth import GroundTruth
from recon.generate.narration import FAMILIES, SPLIT_DEV, SPLIT_EVAL, families_for, parse_utr
from recon.generate.world import GenConfig, build_world, emit_ground_truth
from recon.report.exceptions import PLAYBOOK
from recon.resolve import tier0

import pytest

SEEDS = ("dev", "eval")


@pytest.fixture(scope="module")
def worlds():
    """Full-scale worlds for both seeds. Built once; the gate is about scale."""
    return {seed: build_world(GenConfig(seed=seed,
                                        split=SPLIT_EVAL if seed == "eval" else SPLIT_DEV))
            for seed in SEEDS}


# --- gate 1: scale (Sec 5: 1,000-2,000 lines, 60-90 days, 15-25 cycles) -------

@pytest.mark.parametrize("seed", SEEDS)
def test_scale_is_inside_the_brief_bands(worlds, seed):
    world = worlds[seed]
    assert 1_000 <= len(world.lines) <= 2_000, f"{len(world.lines)} line items"
    assert 15 <= len(world.settlements) <= 25, f"{len(world.settlements)} settlements"
    assert 60 <= world.config.n_days <= 90


# --- gate 2: the full Sec 3.1 schema ------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_all_four_line_types_are_present_and_non_trivial(worlds, seed):
    """Sec 3.1: type is payment|refund|transfer|adjustment. All four, for real.

    "Non-trivial" is the point. Emitting one token refund to tick the box would
    let every downstream number be dominated by payments and hide whatever the
    other three break.
    """
    kinds = {}
    for line in worlds[seed].lines:
        kinds[line.kind] = kinds.get(line.kind, 0) + 1
    assert set(kinds) == {"payment", "refund", "transfer", "adjustment"}
    for kind, count in kinds.items():
        assert count >= 10, f"only {count} {kind} lines is a token presence"


@pytest.mark.parametrize("seed", SEEDS)
def test_id_prefixes_mirror_razorpay_exactly(worlds, seed):
    """Sec 3.1 names the prefixes to mirror. A reviewer checks these first."""
    world = worlds[seed]
    assert all(o.order_id.startswith("order_") for o in world.orders)
    assert all(line.line_id.startswith("setlodp_") for line in world.lines)
    for settlement in world.settlements:
        expected = "setlod_" if settlement.is_instant else "setl_"
        assert settlement.settlement_id.startswith(expected)

    for line in world.lines:
        if line.kind == "payment":
            assert line.payment_id.startswith("pay_")
        if line.refund_id is not None:
            assert line.refund_id.startswith("rfnd_")
        if line.transfer_id is not None:
            assert line.transfer_id.startswith("trf_")
        if line.adjustment_id is not None:
            assert line.adjustment_id.startswith("adj_")


def test_derived_report_carries_every_documented_field(tmp_path):
    """`extra="forbid"` makes a missing field fail loudly, so pin the field set.

    A column quietly dropped from the report would otherwise only surface as a
    resolver that mysteriously stopped joining.
    """
    from recon.generate.derive import generate

    generate(GenConfig(seed="dev", n_days=8), tmp_path)
    row = json.loads((tmp_path / "settlement_lines.jsonl").read_text(
        encoding="utf-8").splitlines()[0])
    expected = {
        "entity_id", "type", "debit", "credit", "amount", "currency", "fee", "tax",
        "on_hold", "settled", "created_at", "settled_at", "settlement_id", "posted_at",
        "credit_type", "description", "notes", "payment_id", "settlement_utr",
        "order_id", "order_receipt", "method", "card_network", "card_issuer",
        "card_type", "dispute_id",
    }
    assert set(row) == expected


# --- gate 3: the deduction stack, and the identity that binds it --------------

@pytest.mark.parametrize("seed", SEEDS)
def test_world_components_close_the_gap(worlds, seed):
    """THE identity of this increment, over every settlement of both seeds.

        sum(settled payment amounts) - settlement.amount - sum(components) == 0

    Everything downstream depends on it. If it does not hold, a residual measured
    at Tier 0 is partly OUR arithmetic error rather than the data's, and the
    Increment 2 pivot would be decided on a corrupted number.
    """
    world = worlds[seed]
    truth = emit_ground_truth(world)
    for settlement in world.settlements:
        gross = int(world.settled_gross(settlement.settlement_id))
        components = sum(c.amount for c in truth.components.get(
            settlement.settlement_id, ()))
        assert gross - int(settlement.amount) - components == 0, (
            f"{seed}/{settlement.settlement_id}: gross {gross} "
            f"- amount {int(settlement.amount)} - components {components}")


@pytest.mark.parametrize("seed", SEEDS)
def test_the_whole_deduction_stack_reaches_ground_truth(worlds, seed):
    """Sec 3.3, minus TDS 194-O which is out by persona (PLAN.md Assumption 1)."""
    world = worlds[seed]
    truth = emit_ground_truth(world)
    seen = {c.kind for comps in truth.components.values() for c in comps}
    required = {
        ComponentType.MDR, ComponentType.GST_ON_MDR, ComponentType.ROLLING_RESERVE,
        ComponentType.RESERVE_RELEASE, ComponentType.REFUND_OFFSET,
        ComponentType.CHARGEBACK_REVERSAL, ComponentType.CHARGEBACK_FEE,
        ComponentType.TRANSFER_OUT, ComponentType.INSTANT_SETTLEMENT_FEE,
    }
    missing = {c.value for c in required} - seen
    assert not missing, f"deduction stack incomplete in truth: {missing}"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_rollup_identity_holds_over_every_settlement(worlds, seed):
    """settlement.amount = sum(credit) - sum(debit), Sec 3.2.

    Every deduction must exist as a LINE ITEM, never as a silent adjustment to
    the total. The instant-settlement fee broke this once (F-004) by moving money
    without a row to say so.
    """
    world = worlds[seed]
    for settlement in world.settlements:
        lines = world.lines_of(settlement.settlement_id)
        assert sum(line.net for line in lines) == int(settlement.amount)


@pytest.mark.parametrize("seed", SEEDS)
def test_an_unsettled_line_carries_no_fee_and_no_credit(worlds, seed):
    """on_hold means nothing has moved, so nothing has been charged.

    Reporting a fee on a held line would open a gap with no component behind it,
    and it would read as a data anomaly when in fact it was ours.
    """
    for line in worlds[seed].lines:
        if line.on_hold:
            assert int(line.fee) == 0 and int(line.tax) == 0
            assert int(line.credit) == 0 and int(line.debit) == 0
            assert not line.settled


# --- gate 4: intrinsic realism (Sec 5: 85-92% cleanly resolvable) -------------

@pytest.mark.parametrize("seed", SEEDS)
def test_intrinsic_clean_rate_is_inside_the_realism_band(worlds, seed):
    """Measured from ground truth ALONE, with no resolver involved.

    Sec 5: "~85-92% should be cleanly resolvable. If your data is 50% broken it
    isn't a recon dataset, it's a puzzle." The resolver's own explanation rate
    answers a different question and must not be substituted for this one.
    """
    truth = emit_ground_truth(worlds[seed])
    clean = sum(1 for u in truth.units if u.anomaly is None)
    rate_bps = (clean * 10_000) // len(truth.units)
    assert 8_500 <= rate_bps <= 9_200, (
        f"{seed}: intrinsic clean rate {rate_bps / 100 if False else rate_bps} bps "
        f"({clean}/{len(truth.units)}) is outside the 85-92% realism band")


# --- gate 5: the declared blind spot ------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_orphan_refunds_are_detectable_and_permanently_unresolvable(worlds, seed):
    """The blind spot Sec 5 asks for, stated precisely.

    Two separate claims, and the distinction is the whole point:
      * DETECTABLE at Tier 0 -- the payment_id points at nothing, and we say so.
      * UNRESOLVABLE at any tier -- the original capture is not in the extract, so
        there is no truth edge for any resolver, LLM included, to find.
    """
    assert ExceptionType.REFUND_ORPHANED.detectable_at == 0
    assert ExceptionType.REFUND_ORPHANED.resolvable is False
    assert ExceptionType.REFUND_ORPHANED.is_blind_spot

    world = worlds[seed]
    truth = emit_ground_truth(world)
    orphans = [line for line in world.lines
               if line.anomaly is ExceptionType.REFUND_ORPHANED]
    assert orphans, "the declared blind spot must actually be present"

    payment_ids = {line.payment_id for line in world.lines if line.kind == "payment"}
    linked = {e.src_uid for e in truth.edges if e.kind == "refund_to_payment"}
    for orphan in orphans:
        assert orphan.payment_id not in payment_ids
        # No truth edge: an edge to a unit that does not exist would quietly make
        # the blind spot look resolvable, and recall would punish a resolver for
        # failing to find something that is not there.
        assert orphan.line_id not in linked


def test_exactly_one_exception_class_is_unresolvable():
    """A growing list of "we can never fix this" is how a blind spot becomes an
    excuse. One, declared, defended."""
    unresolvable = [e.code for e in ExceptionType if not e.resolvable]
    assert unresolvable == ["REFUND_ORPHANED"]


# --- gate 6: the held-out narration split -------------------------------------

def test_eval_seed_renders_only_from_held_out_families(tmp_path):
    """Deviation #4: held out at the TEMPLATE level, not just the seed level.

    A held-out seed rendered from the same templates would only test that the RNG
    differs. The parser was written against dev shapes, so the eval shapes are the
    genuine unseen surface.
    """
    from recon.generate.derive import generate

    generate(GenConfig(seed="eval", n_days=24, split=SPLIT_EVAL), tmp_path)
    rows = [json.loads(line) for line
            in (tmp_path / "bank.jsonl").read_text(encoding="utf-8").splitlines()]
    eval_names = {f.name for f in families_for(SPLIT_EVAL)}
    dev_names = {f.name for f in families_for(SPLIT_DEV)}
    families = {r["narration_family"] for r in rows} - {None}
    assert families <= eval_names
    assert not (families & dev_names)


def test_the_dev_and_eval_splits_are_disjoint_and_both_populated():
    dev = families_for(SPLIT_DEV)
    held_out = families_for(SPLIT_EVAL)
    assert dev and held_out
    assert not ({f.name for f in dev} & {f.name for f in held_out})
    assert len(dev) + len(held_out) == len(FAMILIES)


def test_the_deterministic_parser_is_much_weaker_on_held_out_shapes(tmp_path):
    """The number the Increment 3 ablation has to beat, measured before any LLM.

    Publishing it now means it cannot be chosen after the fact to flatter a
    result. It is deliberately NOT asserted as a specific value: what matters is
    that a parser written against dev templates degrades materially on unseen
    ones, which is the premise of Sec 3.5.
    """
    from recon.generate.derive import generate

    rates = {}
    for seed, split in (("dev", SPLIT_DEV), ("eval", SPLIT_EVAL)):
        out = tmp_path / seed
        generate(GenConfig(seed=seed, n_days=24, split=split), out)
        rows = [json.loads(line) for line
                in (out / "bank.jsonl").read_text(encoding="utf-8").splitlines()]
        # Settlement credits only: the injected stray credits carry their own
        # narration and would dilute the comparison.
        rows = [r for r in rows if r["narration_family"] is not None]
        hits = sum(1 for r in rows if parse_utr(r["narration"]) is not None)
        rates[seed] = (hits * 10_000) // len(rows)

    assert rates["dev"] == 10_000, "the parser must be sound on the shapes it saw"
    assert rates["eval"] < 5_000, (
        f"held-out parse rate {rates['eval']} bps is too close to dev; the eval "
        "families are not actually a different surface")


# --- the rate card -------------------------------------------------------------

def test_mdr_varies_by_instrument_or_slab_mismatch_is_undetectable():
    """A single rate would make MDR_SLAB_MISMATCH impossible by construction."""
    rates = {mdr_rate_bps(*key) for key in MDR_SLABS if key[0] is not None}
    assert len(rates) > 3, "a rate card with one rate is not a rate card"
    assert mdr_rate_bps("upi") == 0, "UPI is zero-MDR for merchants in India"
    assert mdr_rate_bps("card", "amex", "credit") > mdr_rate_bps("card", "visa", "debit")


def test_an_unpriced_method_raises_rather_than_defaulting_to_zero():
    """Silently charging 0% for a method we forgot to price would land the
    residual on zero for the wrong reason -- a false clear by construction."""
    with pytest.raises(KeyError):
        mdr_rate_bps("crypto")


def test_every_instrument_in_the_mix_is_priced():
    from recon.domain.rates import INSTRUMENT_MIX

    for instrument, weight in INSTRUMENT_MIX:
        assert weight > 0
        assert isinstance(instrument.rate_bps, int)
    assert isinstance(Instrument("upi").rate_bps, int)


# --- coverage guards -----------------------------------------------------------

def test_playbook_covers_every_exception_type():
    """An exception with no action and no owner wastes more analyst time than it
    saves. The queue is the product surface, not a log."""
    missing = [e.code for e in ExceptionType if e not in PLAYBOOK]
    assert not missing, f"no playbook entry for {missing}"
    for exception, (action, owner) in PLAYBOOK.items():
        assert action.strip() and owner.strip(), exception.code


def test_each_tier_covers_the_remit_it_declares():
    """A class marked `detectable_at == N` must actually be raised by tier N.

    Without this, `detectable_at` would be an aspiration rather than a contract,
    and the false-clear split would quietly relabel real misses as out-of-remit --
    exactly the self-deception the split exists to prevent. Checking the SPECIFIC
    tier, not just "somewhere in the resolver", also stops a class drifting to a
    higher tier than it claims and inflating the earlier tier's apparent reach.
    """
    import inspect

    from recon.resolve import tier1

    sources = {0: inspect.getsource(tier0), 1: inspect.getsource(tier1)}
    wrong = []
    for exception in ExceptionType:
        if exception.detectable_at > BUILT_TIER:
            continue
        if f"ExceptionType.{exception.name}" not in sources[exception.detectable_at]:
            wrong.append(f"{exception.code} (declared tier {exception.detectable_at})")
    assert not wrong, f"declared detectable but never raised by that tier: {wrong}"


def test_built_tier_matches_the_tiers_actually_wired_in():
    """BUILT_TIER must never run ahead of the code. It gates the false-clear
    split, so an optimistic value would hide real defects."""
    from recon.resolve import pipeline

    source = inspect_source(pipeline)
    assert BUILT_TIER == 3
    for tier in ("tier0.resolve", "tier1.resolve", "tier2.resolve", "tier3.resolve"):
        assert tier in source, f"BUILT_TIER claims {tier} but it is not wired in"


def inspect_source(module) -> str:
    import inspect

    return inspect.getsource(module)
