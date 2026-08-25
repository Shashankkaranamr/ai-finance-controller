"""Metrics. Every numerator and denominator is stated here and in the README.

BRIEF Sec 7: "Ambiguous metrics are the single easiest way to lose a technical
panel. Publish the formulas."

TWO DELIBERATE CHOICES
----------------------
1. EXPLANATION RATE IS THE HEADLINE, not match rate. Exact UTR join clears the
   large majority on any realistic data -- finding the counterparty is easy.
   Explaining the amount to a zero residual with every component typed is the job.
   Match rate is reported alongside as the supporting number so nobody mistakes
   the easy one for the achievement.

2. THE HEADLINE GRAIN CARRIES TWO DENOMINATORS. "Bank credits fully explained /
   total bank credits" cannot see a settlement that never produced a bank credit
   at all -- the worst break in the set would be invisible in the headline. So
   settlement coverage is reported next to it, and both are named in full.

All rates are integer basis points (9873 == 98.73%). No float exists anywhere in
this package, which tests/test_no_floats.py asserts by AST scan.

Wall-clock throughput lives in run_summary.json, NOT here: metrics.json must be
byte-identical across runs (Increment 0 exit gate, item 6) and elapsed time never is.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.graph import EdgeKind, EdgeStatus, ReconEdge
from ..domain.truth import GroundTruth
from ..money import Paise, format_bps, format_inr, ratio_bps
from .exceptions import ExceptionRecord

ACCEPTED = (EdgeStatus.EXPLAINED, EdgeStatus.MATCHED)


@dataclass(frozen=True, slots=True)
class Rate:
    """A rate that always travels with the counts that produced it."""

    numerator: int
    denominator: int
    label: str

    @property
    def bps(self) -> int:
        return ratio_bps(self.numerator, self.denominator)

    def to_json(self) -> dict:
        return {"numerator": self.numerator, "denominator": self.denominator,
                "rate_bps": self.bps, "display": format_bps(self.bps), "label": self.label}

    def line(self) -> str:
        return (f"{self.label:<44} {format_bps(self.bps):>8}  "
                f"({self.numerator}/{self.denominator})")


@dataclass(slots=True)
class Metrics:
    explanation_rate_bank: Rate
    settlement_coverage: Rate
    match_rate_line_items: Rate
    money_weighted_coverage: Rate
    money_total: Paise
    money_explained: Paise
    linkage_precision: Rate
    linkage_recall: Rate
    exception_detection_recall: Rate
    false_clear_rate: Rate
    exception_typing_accuracy: Rate
    counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "headline": {
                "explanation_rate_bank": self.explanation_rate_bank.to_json(),
                "settlement_coverage": self.settlement_coverage.to_json(),
                "money_weighted_coverage": self.money_weighted_coverage.to_json(),
            },
            "supporting": {
                "match_rate_line_items": self.match_rate_line_items.to_json(),
                "money_total_paise": int(self.money_total),
                "money_explained_paise": int(self.money_explained),
            },
            "accuracy": {
                "linkage_precision": self.linkage_precision.to_json(),
                "linkage_recall": self.linkage_recall.to_json(),
                "exception_detection_recall": self.exception_detection_recall.to_json(),
                "false_clear_rate": self.false_clear_rate.to_json(),
                "exception_typing_accuracy": self.exception_typing_accuracy.to_json(),
            },
            "counts": dict(sorted(self.counts.items())),
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"), indent=1),
            encoding="utf-8")

    def render(self) -> str:
        lines = [
            "HEADLINE",
            "  " + self.explanation_rate_bank.line(),
            "  " + self.settlement_coverage.line(),
            "  " + self.money_weighted_coverage.line(),
            f"  {'value reconciled':<44} {format_inr(self.money_explained):>18}"
            f" of {format_inr(self.money_total)}",
            "",
            "SUPPORTING",
            "  " + self.match_rate_line_items.line(),
            "",
            "ACCURACY vs ground truth",
            "  " + self.linkage_precision.line(),
            "  " + self.linkage_recall.line(),
            "  " + self.exception_detection_recall.line(),
            "  " + self.false_clear_rate.line() + "   <-- the dangerous class",
            "  " + self.exception_typing_accuracy.line(),
        ]
        return "\n".join(lines)


def compute(edges: list[ReconEdge], exceptions: list[ExceptionRecord],
            truth: GroundTruth, repo) -> Metrics:
    bank_edges = [e for e in edges if e.kind is EdgeKind.BANK_TO_SETTLEMENT]
    line_edges = [e for e in edges if e.kind is EdgeKind.SETTLEMENT_TO_LINE]

    explained_bank = [e for e in bank_edges if e.status is EdgeStatus.EXPLAINED]
    explained_settlement_ids = {e.dst_uid for e in explained_bank}

    # --- headline -------------------------------------------------------------
    explanation_rate_bank = Rate(
        len(explained_bank), len(repo.bank),
        "explanation rate (bank credits, residual==0)")

    settlement_coverage = Rate(
        len(explained_settlement_ids), len(repo.settlements),
        "settlement coverage (settlements fully explained)")

    # Money-weighted at the settlement grain, on GROSS, because gross is what the
    # receivable was raised at. Sec 7: 95% of records but 60% of value is a bad
    # result, and count-only metrics hide it.
    members_by_settlement = repo.lines_by_settlement()
    money_total = 0
    money_explained = 0
    for settlement_id, members in members_by_settlement.items():
        gross = sum(m.amount for m in members)
        money_total += gross
        if settlement_id in explained_settlement_ids:
            money_explained += gross

    money_weighted_coverage = Rate(
        money_explained, money_total, "money-weighted coverage (gross value)")

    match_rate_line_items = Rate(
        len([e for e in line_edges if e.status is EdgeStatus.EXPLAINED]),
        len(repo.lines), "match rate (line items -> settlement)")

    # --- accuracy vs ground truth --------------------------------------------
    truth_edges = truth.edge_keys()
    predicted = {(e.kind.value, e.src_uid, e.dst_uid) for e in edges if e.status in ACCEPTED}
    correct = predicted & truth_edges

    linkage_precision = Rate(len(correct), len(predicted),
                             "linkage precision (of what we matched)")
    linkage_recall = Rate(len(correct), len(truth_edges),
                          "linkage recall (of true links)")

    # Exception detection: did we flag the units truth says are broken?
    truth_breaks = {u.uid: u for u in truth.anomalous_units(breaks_only=True)}
    flagged_subjects = {r.subject_id for r in exceptions}
    caught = {uid for uid in truth_breaks if uid in flagged_subjects}
    missed = set(truth_breaks) - caught

    exception_detection_recall = Rate(
        len(caught), len(truth_breaks), "exception detection recall (injected breaks caught)")

    # FALSE-CLEAR: an injected break we did not flag is, by definition, one we
    # silently passed as fine. The most dangerous error class in reconciliation:
    # a missed match costs an analyst ten minutes, a false clear means money
    # leaves the reconciliation and nobody looks again.
    false_clear_rate = Rate(len(missed), len(truth_breaks),
                            "FALSE-CLEAR rate (breaks wrongly passed)")

    # Typing: of the breaks we caught, did we give them the right code?
    by_subject: dict[str, str] = {}
    for record in exceptions:
        by_subject.setdefault(record.subject_id, record.code)
    typed_right = sum(1 for uid in caught if by_subject.get(uid) == truth_breaks[uid].anomaly)
    exception_typing_accuracy = Rate(typed_right, len(caught),
                                     "exception typing accuracy (correct code)")

    counts = {
        "edges_total": len(edges),
        "edges_explained": len([e for e in edges if e.status is EdgeStatus.EXPLAINED]),
        "edges_matched_not_explained": len([e for e in edges
                                            if e.status is EdgeStatus.MATCHED]),
        "exceptions_total": len(exceptions),
        "exceptions_breaks": len([r for r in exceptions if r.is_break]),
        "exceptions_informational": len([r for r in exceptions if not r.is_break]),
        "quarantined_rows": len(repo.quarantined),
        "records_ingested": repo.total_records,
        "bank_credits": len(repo.bank),
        "settlements": len(repo.settlements),
        "line_items": len(repo.lines),
        "book_entries": len(repo.books),
    }

    return Metrics(
        explanation_rate_bank=explanation_rate_bank,
        settlement_coverage=settlement_coverage,
        match_rate_line_items=match_rate_line_items,
        money_weighted_coverage=money_weighted_coverage,
        money_total=Paise(money_total),
        money_explained=Paise(money_explained),
        linkage_precision=linkage_precision,
        linkage_recall=linkage_recall,
        exception_detection_recall=exception_detection_recall,
        false_clear_rate=false_clear_rate,
        exception_typing_accuracy=exception_typing_accuracy,
        counts=counts,
    )
