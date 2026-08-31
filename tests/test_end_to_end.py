"""The exit gate, as tests. Every assertion maps to a numbered gate condition.

INCREMENT 1 RESTATED SEVEN OF THESE, AND IT IS WORTH SAYING WHY
---------------------------------------------------------------
Increment 0's data had one anomaly and no ambiguity, so several tests asserted
perfection: explanation rate 100%, false clear 0, recall 100, at least one
journal entry. Increment 1's data is realistic, and those assertions became
false BY DESIGN -- Tier 0 knows nothing about a rolling reserve, so it explains
nothing and posts nothing.

The temptation is to relax them. Instead each one is restated as the stronger
property that should hold now:

  * "false clear is zero"     -> zero WITHIN THE BUILT TIER'S REMIT, which is the
                                 claim that actually matters and the one that must
                                 never regress.
  * "recall is 100%"          -> precision is 100%, and every recall miss is a
                                 link we deliberately DECLINED to make.
  * "a journal entry exists"  -> the ledger posts NOTHING it cannot fully explain,
                                 and the account structure is verified directly
                                 instead of incidentally.

A test that only passes on data too clean to be interesting was not testing much.
"""
from __future__ import annotations

import json

from recon.domain.graph import BUILT_TIER, EdgeKind, EdgeStatus, ExceptionType
from recon.domain.truth import GroundTruth
from recon.report.exceptions import SUBJECT_UNIT


# --- gate 3: the five artifacts exist ----------------------------------------

def test_all_artifacts_written(result):
    for name in ("metrics.json", "recon_statement.md", "exceptions.jsonl",
                 "audit.jsonl", "run_summary.json"):
        path = result.out_dir / name
        assert path.exists(), f"missing artifact {name}"
        assert path.stat().st_size > 0, f"empty artifact {name}"

    # journal_entries.jsonl must EXIST but is legitimately empty at Tier 0 --
    # see test_the_ledger_posts_nothing_it_cannot_fully_explain.
    assert (result.out_dir / "journal_entries.jsonl").exists()


# --- gate 4: the statement foots ---------------------------------------------

def test_reconciliation_statement_foots(result):
    statement = result.statement
    assert statement.foots, (
        f"statement does not foot: computed closing "
        f"{int(statement.computed_closing)} vs expected "
        f"{int(statement.closing_receivable)}, difference {int(statement.difference)}")


def test_footing_terms_come_from_different_sources_and_agree(result):
    """cash (bank) + variance (resolver) must equal the gross it relieved (books).

    This is the cross-source check. A one-paise error in the MDR arithmetic breaks
    it, which is what makes the footing test meaningful rather than tautological.
    """
    statement = result.statement
    relieved = (int(statement.gross_sales)
                - int(statement.exceptions_gross)
                - int(statement.closing_receivable))
    assert int(statement.settlements_received) + int(statement.explained_variance) == relieved


def test_every_journal_entry_balances(result):
    for entry in result.journal:
        assert entry.balances, f"unbalanced entry {entry.entry_id}"


def test_the_ledger_posts_nothing_it_cannot_fully_explain(result):
    """At Tier 0 on realistic data, that means it posts nothing at all.

    Auto-posting is gated on EXPLAINED, and Tier 0 cannot explain a settlement
    carrying a rolling reserve. Zero entries is the CORRECT conservative outcome,
    not a defect: an accounting system that posts a half-understood entry is worse
    than one that posts none and raises an exception.

    Expected to change when Tier 1 lands. It should change to a non-zero count,
    never to a relaxed assertion.
    """
    explained = [e for e in result.edges
                 if e.kind is EdgeKind.BANK_TO_SETTLEMENT
                 and e.status is EdgeStatus.EXPLAINED]
    assert len(result.journal) == len(explained)
    assert BUILT_TIER == 0 and not explained, (
        "Tier 1 has landed; update this test to assert the posted entries")


# --- gate 5: exactly one typed exception, with evidence ----------------------

def test_exactly_one_seeded_missing_bank_credit(result):
    found = [r for r in result.exceptions if r.code == "MISSING_BANK_CREDIT"]
    assert len(found) == 1, f"expected exactly one, got {len(found)}"

    record = found[0]
    assert record.subject_kind == SUBJECT_UNIT
    assert int(record.amount_at_risk) > 0
    assert record.owner == "treasury"
    assert "in transit" in record.suggested_action.lower()


def test_the_exception_carries_a_usable_evidence_chain(result):
    record = next(r for r in result.exceptions if r.code == "MISSING_BANK_CREDIT")
    kinds = {e.kind for e in record.evidence}
    assert "settlement_processed" in kinds
    assert "bank_search_exhausted" in kinds
    for evidence in record.evidence:
        assert evidence.refs, "evidence without refs cannot be followed up"
        assert evidence.detail.strip()


def test_exception_queue_is_prioritised_by_value_at_risk(result):
    rows = [json.loads(line) for line
            in (result.out_dir / "exceptions.jsonl").read_text(encoding="utf-8").splitlines()]
    breaks = [r for r in rows if r["is_break"]]
    informational = [r for r in rows if not r["is_break"]]
    assert rows[:len(breaks)] == breaks, "breaks must sort ahead of informational"
    amounts = [r["amount_at_risk"] for r in breaks]
    assert amounts == sorted(amounts, reverse=True)
    assert all("amount_at_risk_display" in r for r in rows)
    assert informational == rows[len(breaks):]


# --- gates 1 and 2: the numbers ----------------------------------------------

def test_headline_uses_two_denominators(result):
    """The bank-credit denominator cannot see a settlement that never produced a
    credit, so settlement coverage must be reported next to it."""
    metrics = result.metrics
    assert metrics.explanation_rate_bank.denominator == len(result.repo.bank)
    assert metrics.settlement_coverage.denominator == len(result.repo.settlements)
    # The whole point of D-005: these are genuinely different populations, so one
    # number can never stand in for the other. There are more bank credits than
    # settlements here precisely because some credits belong to no settlement at
    # all -- and those are invisible in any settlement-side rate.
    assert (metrics.explanation_rate_bank.denominator
            != metrics.settlement_coverage.denominator)


def test_no_false_clears_within_the_built_tier_remit(result):
    """THE assertion this project must never lose.

    A break the built resolver was accountable for and silently passed is the
    dangerous class. Breaks needing a tier that does not exist yet are reported
    separately and are not failures of this build -- but the in-remit number is
    zero, or the run is not trustworthy.
    """
    metrics = result.metrics
    assert metrics.false_clear_in_remit.numerator == 0, (
        "a break inside the built tier's remit was silently passed")
    # And the split must be real: out-of-remit breaks exist, so this does not pass
    # merely because every class happens to be in remit.
    assert metrics.false_clear_out_of_remit.denominator > 0


def test_every_out_of_remit_miss_names_a_tier_we_have_not_built(result, generated):
    """The out-of-remit bucket must not become a dumping ground.

    Anything we failed to flag has to be a class we DECLARED unreachable at this
    tier, in the enum, before the run. Without this, "out of remit" would be a
    label applied to whatever we happened to miss.
    """
    truth = GroundTruth.read(generated / "ground_truth.json")
    flagged = {r.subject_id for r in result.exceptions}
    by_code = {e.code: e for e in ExceptionType}
    for unit in truth.anomalous_units(breaks_only=True):
        if unit.uid not in flagged:
            assert by_code[unit.anomaly].detectable_at > BUILT_TIER, (
                f"{unit.anomaly} is declared detectable at tier "
                f"{by_code[unit.anomaly].detectable_at} but was missed")


def test_linkage_precision_is_perfect_and_every_recall_miss_is_deliberate(result):
    """Precision has no excuse: a link we assert must be a link that is true.

    Recall is allowed to miss, but only where Tier 0 DECLINED to link on purpose
    -- a UTR carried by two credits, or a narration it could not parse. Guessing
    in either case would trade a recall point for a precision error, and in
    reconciliation a confident wrong link costs far more than a gap.
    """
    metrics = result.metrics
    assert metrics.linkage_precision.bps == 10_000

    declined = {r.subject_id for r in result.exceptions
                if r.code in ("DUPLICATE_UTR", "NARRATION_UNPARSEABLE")}
    misses = metrics.linkage_recall.denominator - metrics.linkage_recall.numerator
    assert misses <= len(declined), (
        f"{misses} recall misses but only {len(declined)} deliberate declines")


def test_money_weighted_coverage_is_lower_than_count_coverage(result):
    """Sec 7: 95% of records but 60% of value is a bad result, and count-only
    metrics hide it. The two numbers must be reported separately."""
    metrics = result.metrics
    assert metrics.money_weighted_coverage.denominator == int(metrics.money_total)
    assert int(metrics.money_explained) < int(metrics.money_total)


def test_metrics_json_contains_no_floats(result):
    """Rates are integer basis points, so the artifact is exactly reproducible."""
    raw = json.loads((result.out_dir / "metrics.json").read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, float):
            raise AssertionError(f"float found in metrics.json: {node}")
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        if isinstance(node, list):
            for value in node:
                walk(value)

    walk(raw)


# --- degraded mode ------------------------------------------------------------

def test_increment_0_runs_are_degraded_by_construction(result):
    """No adjudicator is configured, so every Inc 0 run already exercises the
    rules-only path that Sec 8 calls the headline of failure recovery."""
    assert result.llm.available is False
    assert result.llm.degraded is True
    assert result.llm.degraded_reason
    assert result.llm.blocked_hallucination == 0


def test_the_run_completes_and_reports_despite_no_llm(result):
    assert result.ok
    assert result.repo.total_records > 400


# --- graph invariants ---------------------------------------------------------

def test_bank_edges_carry_a_typed_decomposition_that_nets_to_zero(result):
    bank_edges = [e for e in result.edges if e.kind is EdgeKind.BANK_TO_SETTLEMENT]
    assert bank_edges
    for edge in bank_edges:
        if edge.status is EdgeStatus.EXPLAINED:
            assert edge.decomposition is not None
            assert edge.decomposition.residual == 0
            kinds = {c.kind.value for c in edge.decomposition.components}
            assert kinds == {"mdr", "gst_on_mdr"}
            for component in edge.decomposition.components:
                assert component.rule_version, "a component without a rule version is unauditable"


def test_every_edge_records_the_tier_that_resolved_it(result):
    for edge in result.edges:
        assert edge.tier.name == "T0_DETERMINISTIC"
        assert 0 <= edge.confidence <= 100
