"""Guard (D) — the tier-prefix differential. MONOTONIC EXCLUSION, asserted.

WHY THIS EXISTS
---------------
Two defects on 02 Sep, one day apart, in two different tiers, with one shape:

  F-016  Tier 1 recomputed "explained" without the bank tie-out conjunct Tier 0
         applies, then overwrote the edge status -- posting journal entries for
         settlements whose own report contradicted the bank.
  F-017  Tier 2's candidate pool never consulted `status`, so it corroborated a
         credit against a settlement Tier 0 had queued as failed in the same run.

Both are the same principle broken: *a tier may add explanation, but may never
widen the candidate set, relax a gate, or contradict a fact a lower tier has
already established.* See ARCHITECTURE.md Sec 3a.

WHY A DIFFERENTIAL RATHER THAN MORE PREDICATES
-----------------------------------------------
Each instance already has a regression test asserting its own property. Those
make the two KNOWN instances permanent; they cannot catch a third. A list of
"things no tier may produce" has the same limit one level up -- it only catches
what someone thought to write down.

This asserts the shape instead. Re-run the same data with successively more of
the resolver switched on, and require that adding a tier never makes an earlier
correct answer wrong. It needs no predicate written in advance, which is the
whole point: the third instance will be in a tier that does not exist yet.

WHAT IT DOES NOT COVER, STATED PLAINLY
---------------------------------------
It catches a later tier producing a WRONG LINK or SILENCING A BREAK an earlier
prefix had found. It would have caught F-017 outright. It would NOT have caught
F-016, which produced no wrong link and silenced no exception -- it wrongly
marked an edge explained, and only the tie-out predicate sees that. A guard with
a stated blind spot is worth more than one whose limits are unexamined.
"""
from __future__ import annotations

import pytest

from recon.domain.graph import BUILT_TIER
from recon.domain.truth import GroundTruth
from recon.resolve import pipeline

SEEDS = ("dev", "eval")
PREFIXES = tuple(range(BUILT_TIER + 1))


def _prefix_runs(data_dir, out_root):
    """The same data, resolved once per tier prefix. Ordered T0 .. BUILT_TIER."""
    return [pipeline.run(data_dir, out_root / f"t{t}", max_tier=t) for t in PREFIXES]


@pytest.mark.parametrize("seed", SEEDS)
def test_no_tier_introduces_a_wrong_link(seed, generated, generated_eval, tmp_path):
    """A wrong edge is wrong at any tier, so the count may only go down.

    This is the assertion F-017 would have tripped: Tier 2 linked a credit to a
    settlement that never paid out, taking the held-out bank grain from 18/18 to
    18/19 while every published aggregate still read ~100%.
    """
    data_dir = generated if seed == "dev" else generated_eval
    runs = _prefix_runs(data_dir, tmp_path)

    wrong = [r.metrics.linkage_precision.denominator - r.metrics.linkage_precision.numerator
             for r in runs]
    for tier, (before, after) in enumerate(zip(wrong, wrong[1:])):
        assert after <= before, (
            f"{seed}: tier {tier + 1} introduced {after - before} wrong link(s) "
            f"(wrong edges by prefix: {wrong}). A tier may add explanation; it may "
            "not widen the candidate set into edges a lower tier correctly refused.")


@pytest.mark.parametrize("seed", SEEDS)
def test_no_tier_silences_a_break_an_earlier_prefix_found(
        seed, generated, generated_eval, tmp_path):
    """A real break flagged at prefix N must still be flagged at prefix N+1.

    Supersession (D-020) legitimately RETIRES records -- Tier 1 closes Tier 0's
    AMOUNT_VARIANCE_UNEXPLAINED, and Tier 2 drops NARRATION_UNPARSEABLE for a
    credit it has placed. Those act on EDGE refs and on subjects that are not
    true breaks, so they do not shrink this set. A true break going quiet means a
    tier explained away something real, which is the dangerous direction.
    """
    data_dir = generated if seed == "dev" else generated_eval
    truth = GroundTruth.read(data_dir / "ground_truth.json")
    real_breaks = {u.uid for u in truth.units if u.is_break}
    assert real_breaks, "no injected breaks; this guard would pass vacuously"

    runs = _prefix_runs(data_dir, tmp_path)
    flagged = [{r.subject_id for r in run.exceptions} & real_breaks for run in runs]

    for tier, (before, after) in enumerate(zip(flagged, flagged[1:])):
        lost = before - after
        assert not lost, (
            f"{seed}: tier {tier + 1} silenced {len(lost)} real break(s) that tier "
            f"{tier} had flagged: {sorted(lost)[:5]}. Adding a tier must not "
            "explain away a break an earlier prefix correctly found.")


@pytest.mark.parametrize("seed", SEEDS)
def test_the_prefix_runs_actually_differ(seed, generated, generated_eval, tmp_path):
    """The guard must not pass because `max_tier` does nothing.

    Without this, a refactor that ignored the parameter would leave four
    identical runs and two green assertions that measure nothing -- the same
    vacuous-pass failure as F-011, one level along.
    """
    data_dir = generated if seed == "dev" else generated_eval
    runs = _prefix_runs(data_dir, tmp_path)
    explained = [r.metrics.explanation_rate_bank.numerator for r in runs]
    assert len(set(explained)) > 1, (
        f"{seed}: every tier prefix explained the same {explained[0]} credits, so "
        "max_tier is not switching tiers off and this guard is measuring nothing")
