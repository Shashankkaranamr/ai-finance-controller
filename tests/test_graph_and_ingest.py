"""Guardrails on the grain model and the ingest boundary."""
from __future__ import annotations

import json
from datetime import date

import pytest

from recon.domain.graph import (EDGE_SPECS, Decomposition, EdgeKind, EdgeStatus, Evidence,
                                ExceptionType, ReconEdge, Tier, VarianceComponent,
                                ComponentType)
from recon.ingest.load import load_all
from recon.money import Paise, format_bps, format_inr, ratio_bps


# --- the grain model ----------------------------------------------------------

def _edge(**kw):
    base = dict(kind=EdgeKind.SETTLEMENT_TO_LINE, src_uid="setl_a", dst_uid="setlodp_b",
                status=EdgeStatus.MATCHED, tier=Tier.T0_DETERMINISTIC, confidence=100)
    base.update(kw)
    return ReconEdge(**base)


def test_every_edge_kind_declares_its_grain():
    """The metric denominator must be machine-readable, not buried in report code."""
    assert set(EDGE_SPECS) == set(EdgeKind)
    for kind, spec in EDGE_SPECS.items():
        assert spec.natural_key, f"{kind} has no natural key"


def test_exception_status_and_type_must_agree():
    with pytest.raises(ValueError, match="must agree"):
        _edge(status=EdgeStatus.EXCEPTION)
    with pytest.raises(ValueError, match="must agree"):
        _edge(status=EdgeStatus.MATCHED, exception=ExceptionType.MISSING_BANK_CREDIT)


def test_variance_bearing_edge_cannot_be_explained_without_a_decomposition():
    with pytest.raises(ValueError, match="without a decomposition"):
        _edge(kind=EdgeKind.BANK_TO_SETTLEMENT, src_uid="bc_1", dst_uid="setl_a",
              status=EdgeStatus.EXPLAINED)


def test_membership_edge_may_be_explained_without_one():
    """settlement->line is membership, not variance: the rollup identity is a
    property of the edge SET, so fabricating a zero decomposition per edge would
    only pollute the audit log."""
    edge = _edge(status=EdgeStatus.EXPLAINED)
    assert edge.status is EdgeStatus.EXPLAINED
    assert edge.decomposition is None


def test_confidence_is_bounded():
    with pytest.raises(ValueError, match="confidence out of range"):
        _edge(confidence=101)


def test_residual_accounts_for_every_component():
    decomposition = Decomposition(
        expected=Paise(100_000), actual=Paise(97_640),
        components=(VarianceComponent(ComponentType.MDR, Paise(2_000), "v1"),
                    VarianceComponent(ComponentType.GST_ON_MDR, Paise(360), "v1")))
    assert int(decomposition.residual) == 0
    assert decomposition.is_fully_explained


def test_residual_is_nonzero_when_a_component_is_missing():
    decomposition = Decomposition(
        expected=Paise(100_000), actual=Paise(97_640),
        components=(VarianceComponent(ComponentType.MDR, Paise(2_000), "v1"),))
    assert int(decomposition.residual) == 360
    assert not decomposition.is_fully_explained


def test_edges_sort_deterministically():
    edges = [_edge(dst_uid="c"), _edge(dst_uid="a"), _edge(dst_uid="b")]
    assert [e.dst_uid for e in sorted(edges, key=lambda e: e.sort_key())] == ["a", "b", "c"]


def test_exception_types_declare_break_vs_informational():
    """Sec 6: conflating the two inflates the exception count and understates
    the agent."""
    assert ExceptionType.MISSING_BANK_CREDIT.is_break
    assert not ExceptionType.RESERVE_WITHHELD.is_break
    assert not ExceptionType.PERIOD_CUTOFF_TIMING.is_break
    assert not ExceptionType.REFUND_CROSS_CYCLE.is_break


# --- ingest boundary ----------------------------------------------------------

def test_bad_rows_are_quarantined_not_fatal(generated, tmp_path):
    """Sec 8: a run that dies on row 400 of 2000 is worse than useless."""
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    for name in ("books.jsonl", "settlement_lines.jsonl", "settlements.jsonl",
                 "bank.jsonl", "ground_truth.json"):
        (corrupt / name).write_bytes((generated / name).read_bytes())

    bank = corrupt / "bank.jsonl"
    rows = bank.read_text(encoding="utf-8").splitlines()
    rows.append('{"bank_ref":"bc_x","value_date":"not-a-date","amount":1,'
                '"currency":"INR","narration":"x"}')
    rows.append("{ this is not json")
    bank.write_text("\n".join(rows) + "\n", encoding="utf-8")

    repo = load_all(corrupt)
    assert len(repo.quarantined) == 2
    assert repo.bank, "good rows must still load"
    reasons = " ".join(q.error for q in repo.quarantined)
    assert "ValidationError" in reasons and "JSONDecodeError" in reasons
    assert all(q.line_no > 0 for q in repo.quarantined)


def test_a_renamed_column_is_caught_rather_than_silently_none(generated, tmp_path):
    """extra='forbid' turns Sec 8's 'column renamed' failure into a loud one."""
    corrupt = tmp_path / "renamed"
    corrupt.mkdir()
    for name in ("books.jsonl", "settlement_lines.jsonl", "settlements.jsonl",
                 "bank.jsonl", "ground_truth.json"):
        (corrupt / name).write_bytes((generated / name).read_bytes())

    books = corrupt / "books.jsonl"
    rows = books.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["gross_amt"] = first.pop("gross_amount")   # a plausible upstream rename
    rows[0] = json.dumps(first)
    books.write_text("\n".join(rows) + "\n", encoding="utf-8")

    repo = load_all(corrupt)
    assert len(repo.quarantined) == 1
    assert "gross_amt" in repo.quarantined[0].error or "gross_amount" in repo.quarantined[0].error


# --- money --------------------------------------------------------------------

def test_indian_digit_grouping():
    """Western grouping makes a finance reviewer read the wrong magnitude."""
    assert format_inr(Paise(0)) == "Rs 0.00"
    assert format_inr(Paise(12_345)) == "Rs 123.45"
    assert format_inr(Paise(100_000_00)) == "Rs 1,00,000.00"
    # 1234567890 paise = 1,23,45,678 rupees and 90 paise -- lakh/crore grouping,
    # not thousands.
    assert format_inr(Paise(1_234_567_890)) == "Rs 1,23,45,678.90"
    assert format_inr(Paise(-12_345)) == "-Rs 123.45"


def test_rates_are_basis_points_rounded_half_up():
    assert ratio_bps(1, 2) == 5_000
    assert ratio_bps(1, 3) == 3_333
    assert ratio_bps(2, 3) == 6_667
    assert ratio_bps(5, 5) == 10_000
    assert format_bps(9_873) == "98.73%"


def test_a_rate_over_an_empty_denominator_does_not_crash():
    """Reported as 0 alongside its denominator, never as a crash or a silent NaN."""
    assert ratio_bps(0, 0) == 0
