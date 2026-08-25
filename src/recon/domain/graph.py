"""Reconciliation graph -- the load-bearing grain model.

Reconciliation is not a pipeline over rows. It is a graph of typed edges between
units drawn from three sources. An edge asserts "these two units are the same
money", and carries the arithmetic that explains why their amounts differ.

Tier is an attribute of an EDGE, never of a row. That is what makes the ablation
table (BRIEF Sec 7) fall out by construction instead of being reconstructed later.

Reviewed and signed off before any dependent code existed. See PLAN.md,
"Approved grain model", for the two structural calls and the rejected alternatives.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum

from ..money import Paise


class UnitKind(Enum):
    BOOK_ENTRY = "book_entry"      # ERP: order / invoice
    LINE_ITEM = "line_item"        # Razorpay recon line (payment|refund|transfer|adjustment)
    SETTLEMENT = "settlement"      # setl_* rollup
    BANK_CREDIT = "bank_credit"    # one lump credit on the statement


class EdgeKind(Enum):
    BANK_TO_SETTLEMENT = "bank_to_settlement"  # 1:1  via settlement_utr in narration
    SETTLEMENT_TO_LINE = "settlement_to_line"  # 1:N  via settlement_id
    LINE_TO_BOOK = "line_to_book"              # 1:1  via order_id / order_receipt
    REFUND_TO_PAYMENT = "refund_to_payment"    # 1:1  via payment_id, may cross cycles
                                               # HYPOTHESIS -- PLAN.md uncertainty #1


class Cardinality(Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    """Declares a grain. Makes the metric denominator machine-readable rather
    than a decision buried in report code."""

    src: UnitKind
    dst: UnitKind
    cardinality: Cardinality
    natural_key: str          # what Tier 0 joins on -- documentation and audit
    is_headline_grain: bool   # counts toward the published explanation rate
    bears_variance: bool      # can the two sides legitimately differ in amount?


EDGE_SPECS: dict[EdgeKind, EdgeSpec] = {
    # Gross-vs-cash. This is where MDR, GST, reserve and disputes land.
    EdgeKind.BANK_TO_SETTLEMENT: EdgeSpec(
        UnitKind.BANK_CREDIT, UnitKind.SETTLEMENT,
        Cardinality.ONE_TO_ONE, "settlement_utr",
        is_headline_grain=True, bears_variance=True),
    # Membership, not variance: a line either belongs to the settlement or it does
    # not. The rollup identity is a property of the whole edge SET, checked in
    # identities.rollup_holds(), not of any single edge.
    EdgeKind.SETTLEMENT_TO_LINE: EdgeSpec(
        UnitKind.SETTLEMENT, UnitKind.LINE_ITEM,
        Cardinality.ONE_TO_MANY, "settlement_id",
        is_headline_grain=False, bears_variance=False),
    # ERP vs gateway on the same order. Usually agrees; when it does not, that is
    # a manual-entry error and a real break.
    EdgeKind.LINE_TO_BOOK: EdgeSpec(
        UnitKind.LINE_ITEM, UnitKind.BOOK_ENTRY,
        Cardinality.ONE_TO_ONE, "order_id",
        is_headline_grain=True, bears_variance=True),
    EdgeKind.REFUND_TO_PAYMENT: EdgeSpec(
        UnitKind.LINE_ITEM, UnitKind.LINE_ITEM,
        Cardinality.ONE_TO_ONE, "payment_id",
        is_headline_grain=False, bears_variance=False),
}


class Tier(Enum):
    """Which resolver produced the edge's current status. Drives the Sec 7 ablation."""

    T0_DETERMINISTIC = 0   # exact key join
    T1_ARITHMETIC = 1      # variance decomposition against contracted rules
    T2_CANDIDATE = 2       # subset-sum / scored candidates
    T3_LLM = 3             # adjudication, always re-verified by T1
    T4_HUMAN = 4           # queued for an analyst


class EdgeStatus(Enum):
    PROPOSED = "proposed"    # a candidate; not accepted, not counted
    MATCHED = "matched"      # linkage established, amounts NOT yet fully explained
    EXPLAINED = "explained"  # linkage + residual == 0, every component typed  <-- headline
    EXCEPTION = "exception"  # terminal, unresolved; carries an ExceptionType
    REJECTED = "rejected"    # verifier killed it -- feeds blocked_hallucination (Sec 8)


class ExceptionType(Enum):
    """BRIEF Sec 6 taxonomy.

    `is_break` separates real breaks from explained-but-notable. Sec 6 is explicit
    that conflating them inflates the exception count and understates the agent.
    """

    MISSING_BANK_CREDIT = ("MISSING_BANK_CREDIT", True)
    UNMATCHED_BANK_CREDIT = ("UNMATCHED_BANK_CREDIT", True)
    AMOUNT_VARIANCE_UNEXPLAINED = ("AMOUNT_VARIANCE_UNEXPLAINED", True)
    ROLLUP_MISMATCH = ("ROLLUP_MISMATCH", True)
    BOOK_AMOUNT_MISMATCH = ("BOOK_AMOUNT_MISMATCH", True)
    REFUND_ORPHANED = ("REFUND_ORPHANED", True)
    NARRATION_UNPARSEABLE = ("NARRATION_UNPARSEABLE", True)
    RESERVE_WITHHELD = ("RESERVE_WITHHELD", False)      # informational
    REFUND_CROSS_CYCLE = ("REFUND_CROSS_CYCLE", False)  # timing, not a break
    PERIOD_CUTOFF_TIMING = ("PERIOD_CUTOFF_TIMING", False)
    # Sec 6 lists 20. Only Inc 0's seeded type plus the shape are needed now; the
    # rest land in Inc 1-2 once the generator says which ones actually fire.

    def __init__(self, code: str, is_break: bool) -> None:
        self.code = code
        self.is_break = is_break


class ComponentType(Enum):
    """A typed slice of the gap between expected gross and actual bank credit."""

    MDR = "mdr"
    GST_ON_MDR = "gst_on_mdr"
    # Inc 1+: TDS_194O, ROLLING_RESERVE, REFUND_OFFSET,
    #         CHARGEBACK_REVERSAL, CHARGEBACK_FEE, FX_DIFF


@dataclass(frozen=True, slots=True)
class VarianceComponent:
    kind: ComponentType
    amount: Paise
    rule_version: str   # which slab/rule produced it -- reproducibility (Sec 4.1)

    def to_json(self) -> dict:
        return {"kind": self.kind.value, "amount": int(self.amount),
                "rule_version": self.rule_version}


@dataclass(frozen=True, slots=True)
class Decomposition:
    """Why the two sides of an edge differ. residual == 0 is the whole game."""

    expected: Paise
    actual: Paise
    components: tuple[VarianceComponent, ...] = ()

    @property
    def residual(self) -> Paise:
        explained = sum(int(c.amount) for c in self.components)
        return Paise(int(self.expected) - int(self.actual) - explained)

    @property
    def is_fully_explained(self) -> bool:
        return self.residual == 0

    def to_json(self) -> dict:
        return {
            "expected": int(self.expected),
            "actual": int(self.actual),
            "residual": int(self.residual),
            "components": [c.to_json() for c in self.components],
        }


@dataclass(frozen=True, slots=True)
class Evidence:
    """One auditable link in the chain. The queue shows these to the analyst."""

    kind: str                    # "utr_exact_match", "rollup_identity", "llm_rationale"
    detail: str
    refs: tuple[str, ...] = ()   # unit ids, e.g. ("bank_credit:bc_0007", "settlement:setl_JW..")

    def to_json(self) -> dict:
        return {"kind": self.kind, "detail": self.detail, "refs": list(self.refs)}


@dataclass(frozen=True, slots=True)
class ReconUnit:
    """Identity and provenance only -- NOT the source record.

    The graph stays small and serializable; full typed records live in the ingest
    repository keyed by (kind, uid). Keeps the audit log readable. Resolvers that
    need `method` / `card_network` / `dispute_id` do a repository lookup.
    """

    kind: UnitKind
    uid: str            # natural key where one exists (setl_*, pay_*); else deterministic
    amount: Paise
    value_date: date
    source: str         # "books" | "settlement_report" | "bank_statement"

    @property
    def ref(self) -> str:
        return f"{self.kind.value}:{self.uid}"


@dataclass(frozen=True, slots=True)
class ReconEdge:
    kind: EdgeKind
    src_uid: str
    dst_uid: str
    status: EdgeStatus
    tier: Tier                              # the tier that produced *this* status
    confidence: int                         # 0-100 int, NOT float -- determinism
    evidence: tuple[Evidence, ...] = ()
    decomposition: Decomposition | None = None
    exception: ExceptionType | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 100:
            raise ValueError(f"confidence out of range: {self.confidence}")
        if (self.status is EdgeStatus.EXCEPTION) != (self.exception is not None):
            raise ValueError(
                f"EXCEPTION status and exception type must agree "
                f"(status={self.status}, exception={self.exception})")
        spec = EDGE_SPECS[self.kind]
        if (self.status is EdgeStatus.EXPLAINED
                and spec.bears_variance
                and self.decomposition is None):
            raise ValueError(
                f"{self.kind.value} is variance-bearing and cannot be EXPLAINED "
                f"without a decomposition")

    @property
    def spec(self) -> EdgeSpec:
        return EDGE_SPECS[self.kind]

    @property
    def ref(self) -> str:
        return f"{self.kind.value}:{self.src_uid}->{self.dst_uid}"

    def sort_key(self) -> tuple[str, str, str]:
        """Deterministic ordering before serialization -- byte-identical runs."""
        return (self.kind.value, self.src_uid, self.dst_uid)

    def resolved_at(self, tier: Tier, status: EdgeStatus, **kw) -> "ReconEdge":
        """Transitions return a new edge; the audit log records the history so the
        edge itself never carries two versions of the truth."""
        return replace(self, tier=tier, status=status, **kw)

    def to_json(self) -> dict:
        return {
            "kind": self.kind.value,
            "src_uid": self.src_uid,
            "dst_uid": self.dst_uid,
            "status": self.status.value,
            "tier": self.tier.name,
            "confidence": self.confidence,
            "evidence": [e.to_json() for e in self.evidence],
            "decomposition": self.decomposition.to_json() if self.decomposition else None,
            "exception": self.exception.code if self.exception else None,
        }
