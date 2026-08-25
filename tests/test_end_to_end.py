"""The Increment 0 exit gate, as tests.

Every assertion here maps to a numbered gate condition in PLAN.md.
"""
from __future__ import annotations

import json

from recon.domain.graph import EdgeKind, EdgeStatus
from recon.report.exceptions import SUBJECT_UNIT


# --- gate 3: the five artifacts exist ----------------------------------------

def test_all_artifacts_written(result):
    for name in ("metrics.json", "recon_statement.md", "exceptions.jsonl",
                 "journal_entries.jsonl", "audit.jsonl", "run_summary.json"):
        path = result.out_dir / name
        assert path.exists(), f"missing artifact {name}"
        assert path.stat().st_size > 0, f"empty artifact {name}"


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
    assert result.journal, "no journal entries produced"
    for entry in result.journal:
        assert entry.balances, f"unbalanced entry {entry.entry_id}"


def test_journal_entry_has_the_expected_account_structure(result):
    entry = result.journal[0]
    accounts = {line.account for line in entry.lines}
    assert accounts == {"Bank", "MDR Expense", "GST Input Credit", "Trade Receivable"}

    # GST is its own line because it is reclaimable as Input Tax Credit. If it were
    # folded into MDR Expense the merchant would lose the claim.
    gst = next(l for l in entry.lines if l.account == "GST Input Credit")
    assert int(gst.debit) > 0 and int(gst.credit) == 0


# --- gate 5: exactly one typed exception, with evidence ----------------------

def test_exactly_one_seeded_missing_bank_credit(result):
    breaks = [r for r in result.exceptions if r.is_break]
    assert len(breaks) == 1, f"expected one break, got {[r.code for r in breaks]}"

    record = breaks[0]
    assert record.code == "MISSING_BANK_CREDIT"
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
    # The whole point: the easy number is perfect while coverage is not.
    assert metrics.explanation_rate_bank.bps == 10_000
    assert metrics.settlement_coverage.bps < 10_000


def test_no_false_clears_on_clean_data(result):
    assert result.metrics.false_clear_rate.numerator == 0
    assert result.metrics.exception_detection_recall.numerator == 1
    assert result.metrics.exception_typing_accuracy.bps == 10_000


def test_linkage_precision_and_recall_are_perfect_on_clean_data(result):
    """Increment 0's data has one anomaly and no ambiguity. Anything below 100%
    here is a bug in the resolver, not a finding about the data."""
    assert result.metrics.linkage_precision.bps == 10_000
    assert result.metrics.linkage_recall.bps == 10_000


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
