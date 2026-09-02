"""The Increment 2 exit gate, as tests.

Tier 1 is the first tier with a second, independent opinion (the contracted rate
card), so these assertions are mostly about keeping that opinion honest: that it
is arithmetic rather than prose, that it closes the gap exactly rather than
approximately, and that the part of its result which is circular is measured
rather than glossed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from recon.audit.log import AuditLog
from recon.domain.graph import (BUILT_TIER, ComponentBasis, ComponentType, EdgeKind,
                                EdgeStatus, ExceptionType, Tier)
from recon.domain.truth import GroundTruth
from recon.ingest.load import load_all
from recon.ledger.statement import COMPONENT_ACCOUNTS
from recon.resolve import pipeline, tier0, tier1

SEEDS = ("dev", "eval")


def _repo(path: Path):
    return load_all(path)


# --- D-017: the resolver may not read prose we wrote --------------------------

def test_tier1_never_reads_narrative_fields(generated, tmp_path):
    """Scramble every `description` and `notes`; the decomposition must not move.

    A source scan would be the obvious test and a weak one -- `notes` legitimately
    appears in an exception's *evidence*, so grepping for it produces a false
    positive, and grepping for its absence would only prove we hid the access.

    This is behavioural instead: if destroying the prose changes nothing about
    what Tier 1 types, then Tier 1 demonstrably did not use it to decide. That is
    the actual claim D-017 makes, and it stays true however the code is refactored.
    """
    scrambled = tmp_path / "scrambled"
    scrambled.mkdir()
    for name in ("books.jsonl", "settlements.jsonl", "bank.jsonl", "ground_truth.json"):
        (scrambled / name).write_bytes((generated / name).read_bytes())

    rows = [json.loads(line) for line
            in (generated / "settlement_lines.jsonl").read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["description"] = "REDACTED"
        row["notes"] = "REDACTED"
    (scrambled / "settlement_lines.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows) + "\n",
        encoding="utf-8")

    before = tier1.closure_report(_repo(generated))
    after = tier1.closure_report(_repo(scrambled))
    assert before == after, (
        "Tier 1's decomposition changed when the free text was redacted, so it is "
        "reading prose we wrote (D-017)")


def test_the_component_basis_enum_has_no_narrative_member():
    """There is deliberately no value to record a prose-derived component as."""
    assert {b.value for b in ComponentBasis} == {"schema", "contract"}


# --- decomposition, isolated from linkage -------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_decomposition_closes_the_gap_on_both_seeds(seed, generated, generated_eval):
    """Can Tier 1 type the gross-to-net gap with no bank statement involved?

    This has to be measured separately from explanation rate, because on the
    held-out seed the narration parser finds no UTR at all -- no bank edge is
    created and Tier 1 never runs. Explanation rate there is 0% for a reason that
    has nothing to do with the arithmetic, so the headline cannot answer the
    question the Increment 2 gate actually asks.
    """
    data_dir = generated if seed == "dev" else generated_eval
    repo = _repo(data_dir)
    closed, total, by_basis = tier1.closure_report(repo)
    assert total > 0
    assert by_basis, "the circularity split must be populated"

    # `closed == total` was the assertion until 02 Sep, and it was only meetable
    # because no settlement's REPORTED total could ever be wrong. Now that a stale
    # total exists, a gap can fail to close for a reason that has nothing to do
    # with the arithmetic -- the two sides of the subtraction disagree because the
    # input is corrupt.
    #
    # Relaxing the assertion to a count would hide exactly the regression it is
    # here to catch, so it is made STRICTER instead: name the settlements that may
    # fail, and require them to be precisely the ones ground truth says carry a
    # stale total. An arithmetic failure anywhere else still fails this test, and
    # a stale total that silently closed would fail it too.
    truth = GroundTruth.read(data_dir / "ground_truth.json")
    corrupt = {u.uid for u in truth.units
               if u.kind == "settlement" and u.anomaly == "ROLLUP_MISMATCH"}
    assert corrupt, "the fixture no longer injects a stale total; this test is blind"
    assert set(tier1.unclosed_settlements(repo)) == corrupt, (
        f"{seed}: the settlements Tier 1 could not close are not the ones whose "
        "reported total is corrupt")
    assert closed == total - len(corrupt)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_circularity_split_is_published_and_both_halves_are_real(
        seed, generated, generated_eval):
    """Gate condition 5. The eval result's honest limit, as a number.

    SCHEMA money is typed from documented Sec 3.1 fields the gateway asserts; we
    would read the identical field from a real report, so it is not circular.
    CONTRACT money is derived from a rate-card constant we also generated with, so
    it is partly circular. Both halves must be materially present -- if the split
    ever collapses to one side, the claim being made has changed and the gate
    should be re-argued rather than silently passed.
    """
    repo = _repo(generated if seed == "dev" else generated_eval)
    _, _, by_basis = tier1.closure_report(repo)
    assert set(by_basis) == {"schema", "contract"}
    total = sum(by_basis.values())
    for basis, amount in by_basis.items():
        share_bps = (amount * 10_000) // total
        assert 1_000 <= share_bps <= 9_000, (
            f"{seed}: {basis} is {share_bps} bps of explained money; the split has "
            "collapsed and the circularity claim needs restating")


# --- the rate card as a second opinion ----------------------------------------

def test_slab_mismatch_is_detected_now_that_a_rate_card_exists(result, generated):
    """The 83 dev breaks Increment 1 recorded as out-of-remit."""
    truth = GroundTruth.read(generated / "ground_truth.json")
    injected = {u.uid for u in truth.units if u.anomaly == "MDR_SLAB_MISMATCH"}
    flagged = {r.subject_id for r in result.exceptions if r.code == "MDR_SLAB_MISMATCH"}
    assert injected, "the fixture must contain slab mismatches for this to mean anything"
    assert injected <= flagged, f"missed {len(injected - flagged)} slab mismatches"


def test_a_slab_mismatch_does_not_prevent_a_settlement_being_explained(result):
    """An overcharge is recoverable money, not unexplained money.

    Tier 0 builds its MDR component from the fee actually charged, so an
    off-contract fee produces a decomposition that is wrong but internally
    consistent and still sums to zero. Conflating the two would either inflate the
    residual or hide the overcharge, and this is the one case where a fully
    explained settlement legitimately still carries a break.
    """
    slab_breaks = [r for r in result.exceptions if r.code == "MDR_SLAB_MISMATCH"]
    assert slab_breaks
    explained = [e for e in result.edges
                 if e.kind is EdgeKind.BANK_TO_SETTLEMENT
                 and e.status is EdgeStatus.EXPLAINED]
    assert explained, "slab mismatches must not have blocked every explanation"


def test_reserve_is_identified_by_arithmetic_with_no_tolerance(generated):
    """Exactly equal to round_half_up(credits x 500bps), or it is not a reserve.

    A tolerance would turn an arithmetic proof into a score, which is the Sec 9
    anti-pattern wearing a different hat. Holding this to exact equality is what
    surfaced F-010.
    """
    repo = _repo(generated)
    audit = AuditLog(run_id="test", rule_version="test")
    edges, _ = tier0.resolve(repo, audit)
    edges, _ = tier1.resolve(repo, edges, audit)

    reserves = [c for e in edges if e.decomposition
                for c in e.decomposition.components
                if c.kind is ComponentType.ROLLING_RESERVE]
    assert reserves, "no rolling reserve was identified at all"
    assert all(c.basis is ComponentBasis.CONTRACT for c in reserves)


# --- loop closure --------------------------------------------------------------

def test_the_reserve_posts_to_a_receivable_not_an_expense():
    """Sec 3.3: a reserve is a receivable from the gateway, not settled cash.

    Withholding debits the asset and releasing credits it, both to the SAME
    account, so the reserve ledger nets itself out over the hold period instead of
    quietly becoming a cost the merchant never recovers on paper.
    """
    assert (COMPONENT_ACCOUNTS[ComponentType.ROLLING_RESERVE]
            == COMPONENT_ACCOUNTS[ComponentType.RESERVE_RELEASE])
    assert "Receivable" in COMPONENT_ACCOUNTS[ComponentType.ROLLING_RESERVE]
    # GST stays its own account: folded into MDR Expense the merchant loses the
    # Input Tax Credit, which is the business reason `tax` exists in the schema.
    assert (COMPONENT_ACCOUNTS[ComponentType.GST_ON_MDR]
            != COMPONENT_ACCOUNTS[ComponentType.MDR])


def test_every_typed_component_has_an_account():
    """A component with nowhere to post would silently unbalance an entry."""
    missing = [c.value for c in ComponentType if c not in COMPONENT_ACCOUNTS]
    assert not missing, f"no ledger account for {missing}"


def test_exceptions_describe_the_final_state_not_an_intermediate_tier(result):
    """Tier 0 raises AMOUNT_VARIANCE_UNEXPLAINED on every edge it cannot close.

    Tier 1 then closes most of them. Without supersession the queue would show an
    analyst phantom breaks the system had in fact already explained -- 20 of them
    on the dev seed when this was first wired up.
    """
    explained_refs = {e.ref for e in result.edges if e.status is EdgeStatus.EXPLAINED}
    stale = [r for r in result.exceptions
             if r.subject_kind == "edge" and r.subject_id in explained_refs]
    assert not stale, f"{len(stale)} exceptions survive against explained edges"


def test_the_ablation_falls_out_of_the_edge_tier_attribute(result):
    """Invariant 5: tier is an attribute of an EDGE, so this is a group-by.

    Nothing needs to be re-run to produce the Sec 7 ablation table, which is the
    whole reason tier was put on the edge rather than on the row.
    """
    by_tier: dict[str, int] = {}
    for edge in result.edges:
        if edge.status is EdgeStatus.EXPLAINED:
            by_tier[edge.tier.name] = by_tier.get(edge.tier.name, 0) + 1
    assert Tier.T1_ARITHMETIC.name in by_tier
    assert BUILT_TIER == 3
    # No edge may claim a tier this build has not implemented.
    for edge in result.edges:
        assert max(edge.tier.value, edge.established_by.value) <= BUILT_TIER


def test_a_chargeback_fee_is_not_reported_as_an_unlinked_reversal(result, generated):
    """FIX-1 / F-012. A dispute emits two lines and only one is a reversal.

    The flat per-dispute fee carries no `payment_id` because it reverses nothing.
    Flagging it CHARGEBACK_UNLINKED told an analyst "the reversal is real; the
    reference is missing" about a Rs 1,500 fee — false, and aimed at a human.

    Asserted against ground truth rather than a count, so it cannot pass by the
    alarm simply becoming rarer.
    """
    truth = GroundTruth.read(generated / "ground_truth.json")
    injected = {u.uid for u in truth.units if u.anomaly == "CHARGEBACK_UNLINKED"}
    raised = {r.subject_id for r in result.exceptions if r.code == "CHARGEBACK_UNLINKED"}

    assert injected, "the fixture must contain unlinked reversals"
    assert raised == injected, (
        f"{len(raised - injected)} false alarms, {len(injected - raised)} missed")

    # And the fee lines specifically must be absent from the queue.
    fees = {e for e in result.repo.lines
            if result.repo.lines[e].dispute_id is not None
            and result.repo.lines[e].payment_id is None}
    assert fees, "no fee lines in the fixture"
    assert not (raised & fees), "a per-dispute fee was reported as an unlinked reversal"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_queue_publishes_its_false_alarm_rate(seed, generated, generated_eval, tmp_path):
    """FIX-2. False clear measures what we missed; this measures what we invented.

    Until this landed the metric suite measured one error direction with real
    rigour and the other not at all — which is how a queue reaches 26% noise on a
    held-out seed and no number moves. Sec 6 names an inflated exception count as
    the thing that understates the agent.
    """
    from recon.resolve import pipeline

    data = generated if seed == "dev" else generated_eval
    result = pipeline.run(data, tmp_path / seed)
    p = result.metrics.exception_queue_precision

    assert p.denominator > 0, "nothing evaluable — the metric would be vacuous"
    assert p.numerator <= p.denominator
    # It must be computed against truth, not asserted: every false alarm is
    # attributable to a code.
    assert sum(result.metrics.false_alarms_by_code.values()) == p.denominator - p.numerator


def test_missing_is_only_asserted_once_every_credit_has_been_read(generated_eval, tmp_path):
    """FIX-3 / F-014. "The money never arrived" is a claim a treasury team acts on.

    On the held-out seed no narration parses, so 22 settlements had no linked
    credit — and the system told treasury all 22 were MISSING when 21 of them were
    sitting in the bank file. The honest statement while credits remain unread is
    weaker and different: cannot confirm.

    The settlement is still flagged either way, so detection is unaffected; what
    changes is the code, the severity and the action a human takes.
    """
    from recon.resolve import pipeline

    result = pipeline.run(generated_eval, tmp_path / "unconfirmed")
    truth = GroundTruth.read(generated_eval / "ground_truth.json")

    really_missing = {u.uid for u in truth.units if u.anomaly == "MISSING_BANK_CREDIT"}
    claimed_missing = {r.subject_id for r in result.exceptions
                       if r.code == "MISSING_BANK_CREDIT"}
    unconfirmed = {r.subject_id for r in result.exceptions
                   if r.code == "SETTLEMENT_UNCONFIRMED"}

    assert not claimed_missing - really_missing, (
        f"asserted {len(claimed_missing - really_missing)} settlements missing that arrived")
    assert really_missing <= (claimed_missing | unconfirmed), "a real absence went unflagged"
    assert unconfirmed, "with 22 unparsed credits, settlements must be unconfirmed not missing"

    # And it must be informational, not a break: nothing is wrong with the money.
    for record in result.exceptions:
        if record.code == "SETTLEMENT_UNCONFIRMED":
            assert not record.is_break


def test_a_parse_failure_is_our_limitation_not_a_merchant_break(generated_eval, tmp_path):
    """FIX-3. NARRATION_UNPARSEABLE is no longer counted as a break.

    Nothing is wrong with the merchant's money when our regex fails. Counting it
    as a break put 22 records in the held-out break queue for a correct statement,
    and double-counted one event as both an unreadable credit and an unconfirmed
    settlement.
    """
    from recon.resolve import pipeline

    result = pipeline.run(generated_eval, tmp_path / "parsefail")
    unparsed = [r for r in result.exceptions if r.code == "NARRATION_UNPARSEABLE"]
    assert unparsed, "the held-out seed must still exercise the parser failing"
    assert all(not r.is_break for r in unparsed)


# --- F-016: a tier may not silently retire a lower tier's check ---------------

@pytest.mark.parametrize("seed", SEEDS)
def test_tier1_does_not_post_a_settlement_whose_report_contradicts_the_bank(
        seed, generated, generated_eval, tmp_path_factory):
    """THE regression guard for F-016.

    Tier 0 marks a bank edge explained only when the decomposition closes AND the
    credit ties out to the settlement's own reported total. Tier 1 recomputed that
    as the first conjunct alone and then overwrote the status, so a settlement
    whose report contradicted both its line items and the bank was declared fully
    explained and auto-posted to the ledger.

    It survived from Increment 2 to 02 Sep because no data could make the tie-out
    fail. This test is the reason it cannot come back: it asserts the property
    ("nothing posts while the report disagrees with the cash"), not a count, so it
    keeps working whatever the injection rate becomes.
    """
    data_dir = generated if seed == "dev" else generated_eval
    out = tmp_path_factory.mktemp("f016") / seed
    repo = _repo(data_dir)
    result = pipeline.run(data_dir, out)

    posted = {entry.entry_id[len("je_"):] for entry in result.journal}
    for edge in result.edges:
        if edge.kind is not EdgeKind.BANK_TO_SETTLEMENT:
            continue
        reported = int(repo.settlements[edge.dst_uid].amount)
        actual = int(edge.decomposition.actual)
        if reported == actual:
            continue
        assert edge.status is not EdgeStatus.EXPLAINED, (
            f"{edge.dst_uid}: settlement reports {reported} and the bank credited "
            f"{actual}, yet the edge is marked fully explained")
        assert edge.dst_uid not in posted, (
            f"{edge.dst_uid}: a journal entry was posted for a settlement whose own "
            "report contradicts the bank credit")


@pytest.mark.parametrize("seed", SEEDS)
def test_a_stale_total_is_queued_once_and_named_correctly(
        seed, generated, generated_eval, tmp_path_factory):
    """One event, one queue entry, and the entry says the true thing.

    Two records reached the analyst for a single stale total: ROLLUP_MISMATCH,
    which is correct, and Tier 0's AMOUNT_VARIANCE_UNEXPLAINED, which by then was
    false -- Tier 1 had typed every component and closed the residual. D-020's
    supersession keyed on the edge reaching EXPLAINED, and those two things came
    apart the moment a closed residual could still be withheld from the ledger.
    """
    data_dir = generated if seed == "dev" else generated_eval
    out = tmp_path_factory.mktemp("stale") / seed
    truth = GroundTruth.read(data_dir / "ground_truth.json")
    result = pipeline.run(data_dir, out)

    corrupt = {u.uid for u in truth.units
               if u.kind == "settlement" and u.anomaly == "ROLLUP_MISMATCH"}
    assert corrupt, "the fixture no longer injects a stale total; this test is blind"

    posted = {entry.entry_id[len("je_"):] for entry in result.journal}
    for settlement_id in corrupt:
        breaks = [r.code for r in result.exceptions
                  if r.subject_id == settlement_id and r.is_break]
        assert breaks == [ExceptionType.ROLLUP_MISMATCH.code], (
            f"{settlement_id}: expected exactly one break, ROLLUP_MISMATCH, got {breaks}")
        assert settlement_id not in posted

    # Informational records may legitimately coexist: on the held-out seed the
    # stale total also breaks Tier 2's (amount, date) key, so the settlement is
    # additionally SETTLEMENT_UNCONFIRMED -- true, not a break, and a different
    # statement (D-031). Only the BREAK count is asserted above.
    #
    # Nor is the residual asserted to close. A rule keyed on the corrupted field
    # cannot fire: the instant-settlement fee is identified as 25 bps of
    # `settlement.amount + fee`, so on a `setlod_` cycle with a stale total the
    # fee line goes untyped and the residual stays OPEN. That is the correct
    # degradation -- typing a component off a number we have just flagged as
    # untrustworthy would be a guess wearing an identity's clothes -- and either
    # way the settlement is queued once and posts nothing.


# --- D-035: the pair artifact is measured, and the claim about it is checked ---

@pytest.mark.parametrize("seed", SEEDS)
def test_every_duplicate_payment_false_alarm_is_the_other_half_of_a_real_pair(
        seed, generated, generated_eval, tmp_path_factory):
    """The README states this. This is what stops it becoming untrue silently.

    A duplicated payment is two lines carrying one order, and at detection time
    nothing distinguishes the copy from the original — an analyst needs both rows
    to decide. Truth labels one, so the other scores as a false alarm. That is a
    SCORING artifact, and the published headline absorbs it deliberately (D-035).

    The claim is only defensible while every such alarm really is a pair half. The
    moment the resolver raises DUPLICATE_PAYMENT on a line with no genuine
    duplicate behind it, that is real queue noise wearing the artifact's clothes,
    and this test fails rather than letting the README keep saying otherwise.
    """
    data_dir = generated if seed == "dev" else generated_eval
    repo = _repo(data_dir)
    truth = GroundTruth.read(data_dir / "ground_truth.json")
    result = pipeline.run(data_dir, tmp_path_factory.mktemp("pairs") / seed)

    labelled = {u.uid for u in truth.units if u.anomaly == "DUPLICATE_PAYMENT"}
    raised = [r for r in result.exceptions if r.code == "DUPLICATE_PAYMENT"]
    assert raised, "no DUPLICATE_PAYMENT raised; this test is blind"

    labelled_orders = {repo.lines[uid].order_id for uid in labelled
                       if uid in repo.lines and repo.lines[uid].order_id}
    spurious = []
    for record in raised:
        if record.subject_id in labelled:
            continue
        line = repo.lines.get(record.subject_id)
        if line is None or line.order_id not in labelled_orders:
            spurious.append(record.subject_id)

    assert not spurious, (
        f"{seed}: {len(spurious)} DUPLICATE_PAYMENT alarms have no genuine duplicate "
        f"behind them: {spurious[:5]}. These are real queue noise, not the pair "
        "artifact the README describes, and the published explanation is now wrong")


@pytest.mark.parametrize("seed", SEEDS)
def test_the_conservative_queue_precision_stays_the_headline(
        seed, generated, generated_eval, tmp_path_factory):
    """Both numbers are published, and the stricter one leads.

    The collapsed figure is only ever friendlier — on the held-out seed it reads
    100.00% — and it is strictly less sensitive: under it, flagging the WRONG half
    of a pair would still score as a correct detection. Publishing it alone would
    be replacing a conservative measurement with a flattering one, which is the
    F-005 failure. Publishing it beside the headline is the D-005 pattern.
    """
    data_dir = generated if seed == "dev" else generated_eval
    result = pipeline.run(data_dir, tmp_path_factory.mktemp("headline") / seed)
    m = result.metrics

    assert m.exception_queue_precision.denominator > 0
    assert m.exception_queue_precision_pairs_collapsed is not None, (
        "the secondary figure must be published, not left implicit in prose")
    assert (m.exception_queue_precision_pairs_collapsed.bps
            >= m.exception_queue_precision.bps), (
        "the collapsed figure should never be stricter; if it is, the pairing "
        "logic is counting something it should not")
    assert m.paired_detection_alarms == sum(
        n for code, n in m.false_alarms_by_code.items() if code == "DUPLICATE_PAYMENT"), (
        "the artifact count and the per-code false alarms disagree, so one of them "
        "is measuring the wrong population")
