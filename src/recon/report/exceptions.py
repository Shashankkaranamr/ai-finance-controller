"""The honest exception list (BRIEF Sec 4, Tier 4).

Each entry carries the type, confidence, the evidence chain, the agent's best
hypothesis, a suggested action and an owner -- so an analyst can act without
re-deriving the finding. Prioritised by value at risk, because finance triages by
money, not by row count.

A FINDING ABOUT THE GRAIN MODEL
-------------------------------
The approved model attaches exceptions to EDGES. That works for "these two units
are linked but the amounts do not reconcile". It cannot express the most common
break of all: "this settlement has no bank credit at all". An unmatched unit is
the ABSENCE of an edge, and absence is not a thing you can hang evidence on.

So an exception's subject is a unit OR an edge. This is the first place the
Increment 0 skeleton pushed back on the design, and it is recorded in RUN_LOG.md
as expected learning rather than patched over silently.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..domain.graph import Evidence, ExceptionType
from ..money import Paise, format_inr

SUBJECT_UNIT = "unit"
SUBJECT_EDGE = "edge"


# What an analyst should do, and who owns it. Vague exceptions waste more time
# than they save, so every type names an action and a queue.
PLAYBOOK: dict[ExceptionType, tuple[str, str]] = {
    ExceptionType.MISSING_BANK_CREDIT: (
        "Confirm whether the settlement is still in transit (T+2 not yet elapsed) "
        "before treating it as missing; if elapsed, raise with the gateway quoting the UTR.",
        "treasury"),
    ExceptionType.UNMATCHED_BANK_CREDIT: (
        "Identify the payer. Likely a non-gateway receipt or a second aggregator; "
        "do not force-match to an open settlement.",
        "treasury"),
    ExceptionType.AMOUNT_VARIANCE_UNEXPLAINED: (
        "Residual survives the full deduction decomposition. Compare the fee actually "
        "charged against the contracted slab for this method.",
        "finance-ops"),
    ExceptionType.ROLLUP_MISMATCH: (
        "Settlement total disagrees with the sum of its own line items. Re-pull the "
        "recon report for this settlement_id before investigating the bank side.",
        "finance-ops"),
    ExceptionType.BOOK_AMOUNT_MISMATCH: (
        "ERP and gateway disagree on the order amount. Check for a manual invoice edit.",
        "finance-ops"),
    ExceptionType.REFUND_ORPHANED: (
        "Refund has no locatable parent payment. Check prior periods before writing off.",
        "finance-ops"),
    ExceptionType.NARRATION_UNPARSEABLE: (
        "No UTR could be extracted from the narration. Match manually and add the "
        "narration shape to the template registry.",
        "finance-ops"),
    ExceptionType.RESERVE_WITHHELD: (
        "Informational: rolling reserve withheld. Confirm the release date is tracked.",
        "treasury"),
    ExceptionType.REFUND_CROSS_CYCLE: (
        "Informational: refund debits a later cycle than its payment. Timing, not a break.",
        "finance-ops"),
    ExceptionType.PERIOD_CUTOFF_TIMING: (
        "Informational: straddles the period close. Must not be counted as a break.",
        "finance-ops"),
}


@dataclass(frozen=True, slots=True)
class ExceptionRecord:
    code: str
    is_break: bool
    subject_kind: str          # SUBJECT_UNIT | SUBJECT_EDGE
    subject_id: str
    amount_at_risk: Paise
    confidence: int            # 0-100 int
    hypothesis: str
    suggested_action: str
    owner: str
    evidence: tuple[Evidence, ...] = ()

    @classmethod
    def build(cls, exception: ExceptionType, subject_kind: str, subject_id: str,
              amount_at_risk: Paise, hypothesis: str, confidence: int = 100,
              evidence: tuple[Evidence, ...] = ()) -> "ExceptionRecord":
        action, owner = PLAYBOOK[exception]
        return cls(
            code=exception.code,
            is_break=exception.is_break,
            subject_kind=subject_kind,
            subject_id=subject_id,
            amount_at_risk=amount_at_risk,
            confidence=confidence,
            hypothesis=hypothesis,
            suggested_action=action,
            owner=owner,
            evidence=evidence,
        )

    def to_json(self) -> dict:
        return {
            "code": self.code,
            "is_break": self.is_break,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "amount_at_risk": int(self.amount_at_risk),
            "amount_at_risk_display": format_inr(self.amount_at_risk),
            "confidence": self.confidence,
            "hypothesis": self.hypothesis,
            "suggested_action": self.suggested_action,
            "owner": self.owner,
            "evidence": [e.to_json() for e in self.evidence],
        }


def prioritise(records: list[ExceptionRecord]) -> list[ExceptionRecord]:
    """Breaks first, then by value at risk. Ties broken by id for determinism."""
    return sorted(records,
                  key=lambda r: (not r.is_break, -int(r.amount_at_risk), r.subject_id))


def write_queue(path: Path, records: list[ExceptionRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in prioritise(records):
            handle.write(json.dumps(record.to_json(), sort_keys=True,
                                    separators=(",", ":")) + "\n")
