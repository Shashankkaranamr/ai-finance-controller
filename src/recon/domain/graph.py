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


# The highest tier actually IMPLEMENTED in this build. One constant, read by the
# false-clear split so that "we did not catch it" can be separated into "we
# silently passed it" and "no resolver for that exists yet". Bump it in the same
# commit that lands a tier -- never ahead of one.
BUILT_TIER = 1


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

    TWO FURTHER AXES, ADDED IN INCREMENT 1
    --------------------------------------
    `detectable_at` is the lowest tier that can FLAG this class. Without it the
    false-clear metric is uninterpretable, because "we did not flag it" bundles
    two completely different failures:

      * a break inside the built resolver's remit that it silently passed. This
        is the dangerous class, and it must be ZERO.
      * a break whose detection needs a tier that does not exist yet. Nothing
        was cleared; nothing looked. Counting that as a false clear would make an
        honest roadmap read as a defect, and would push us either to stop
        generating realistic anomalies or to build every tier at once.

    `resolvable` is whether ANY tier could ever close it, given the data. It is
    a separate question from detection, and conflating the two was a real error
    in the first cut of this enum: Tier 0 detects an orphan refund perfectly
    well -- it can see the payment_id points at nothing -- and no tier, LLM
    included, can ever link it, because the payment is not in the extract. The
    honest claim is "we always find it and we can never fix it", which is
    strictly stronger than "we cannot see it".

    Exactly one class is unresolvable today, and it is the declared blind spot
    (BRIEF Sec 5 asks for one, and says pretending to 100% reads as fake).
    """

    MISSING_BANK_CREDIT = ("MISSING_BANK_CREDIT", True, 0, True)
    UNMATCHED_BANK_CREDIT = ("UNMATCHED_BANK_CREDIT", True, 0, True)
    AMOUNT_VARIANCE_UNEXPLAINED = ("AMOUNT_VARIANCE_UNEXPLAINED", True, 0, True)
    ROLLUP_MISMATCH = ("ROLLUP_MISMATCH", True, 0, True)
    BOOK_AMOUNT_MISMATCH = ("BOOK_AMOUNT_MISMATCH", True, 0, True)
    # The declared blind spot. Tier 0 DETECTS it perfectly (the payment_id points
    # at nothing), and no tier can ever RESOLVE it, because the original capture
    # is not in the extract. See generate/world.py::_build_orphan_refunds.
    REFUND_ORPHANED = ("REFUND_ORPHANED", True, 0, False)
    # Extraction from narration shapes no deterministic parser was written for.
    NARRATION_UNPARSEABLE = ("NARRATION_UNPARSEABLE", True, 0, True)
    # --- Increment 1: declared once the generator could actually produce them ---
    # Needs the contracted rate card to know the fee was wrong. The report is
    # internally consistent, so no identity over reported values can catch it.
    MDR_SLAB_MISMATCH = ("MDR_SLAB_MISMATCH", True, 1, True)
    GST_ON_MDR_MISMATCH = ("GST_ON_MDR_MISMATCH", True, 0, True)
    RESERVE_RELEASE_UNMATCHED = ("RESERVE_RELEASE_UNMATCHED", True, 1, True)
    # A reversal carrying a dispute_id but no order_id: it cannot be tied back
    # to the sale it reverses. Sec 6 words this as "no corresponding book
    # entry"; the mechanism here is the gateway's reference being absent,
    # which is the same failure reached from the side we actually model.
    CHARGEBACK_UNLINKED = ("CHARGEBACK_UNLINKED", True, 0, True)
    DUPLICATE_UTR = ("DUPLICATE_UTR", True, 0, True)
    DUPLICATE_PAYMENT = ("DUPLICATE_PAYMENT", True, 0, True)
    # --- explained-but-notable: real, reportable, and NOT breaks (Sec 6) -------
    # Typing an adjustment as a reserve needs the rate card: the Sec 3.1 schema
    # has no field saying "this debit is a reserve", and reading it out of the
    # free-text description would be the fuzzy matching Sec 9 warns against.
    RESERVE_WITHHELD = ("RESERVE_WITHHELD", False, 1, True)
    REFUND_CROSS_CYCLE = ("REFUND_CROSS_CYCLE", False, 0, True)  # timing, not a break
    PERIOD_CUTOFF_TIMING = ("PERIOD_CUTOFF_TIMING", False, 0, True)
    # on_hold=true, captured and never settled. The gateway is holding the money
    # legitimately, so the books and the bank disagree CORRECTLY. Notable, not a
    # break -- counting it as one would inflate the queue with correct behaviour.
    ON_HOLD_NOT_SETTLED = ("ON_HOLD_NOT_SETTLED", False, 0, True)
    # Sec 6 lists 20. Still undeclared, because the generator cannot yet produce
    # them and a taxonomy entry with no data behind it is a claim we cannot back:
    # TDS_194O_VARIANCE (out by persona), FX_VARIANCE (FX cut),
    # MULTI_GATEWAY_COLLISION (held as the Inc 2 ambiguity lever),
    # PARTIAL_SETTLEMENT (a batch split across cycles is a subset-sum target,
    #   so it belongs with Tier 2 rather than ahead of it),
    # CHARGEBACK_FEE_UNBOOKED (our ERP view is sales-grain: it has no expense
    #   side, so an unbooked fee has nowhere to be missing FROM).

    def __init__(self, code: str, is_break: bool,
                 detectable_at: int, resolvable: bool) -> None:
        self.code = code
        self.is_break = is_break
        self.detectable_at = detectable_at
        self.resolvable = resolvable

    @property
    def is_blind_spot(self) -> bool:
        """Detectable, and never closeable: the evidence is not in the extract."""
        return not self.resolvable

    def in_remit_of(self, built_tier: int) -> bool:
        """Is this class within the remit of a resolver built out to `built_tier`?

        Drives the false-clear split. A break outside the remit was not cleared;
        it was not looked at, and the metrics say which.
        """
        return self.detectable_at <= built_tier


class ComponentType(Enum):
    """A typed slice of the gap between expected gross and actual bank credit."""

    MDR = "mdr"
    GST_ON_MDR = "gst_on_mdr"
    # --- Increment 1: the rest of the Sec 3.3 deduction stack -----------------
    # Sign convention: every component is a POSITIVE amount that reduces the
    # gross-to-cash gap, except RESERVE_RELEASE, which is money coming back and
    # is therefore carried negative. Keeping one convention means the residual is
    # always `expected - actual - sum(components)` with no per-kind branching.
    ROLLING_RESERVE = "rolling_reserve"
    RESERVE_RELEASE = "reserve_release"          # negative: cash returning
    REFUND_OFFSET = "refund_offset"
    CHARGEBACK_REVERSAL = "chargeback_reversal"
    CHARGEBACK_FEE = "chargeback_fee"
    TRANSFER_OUT = "transfer_out"
    INSTANT_SETTLEMENT_FEE = "instant_settlement_fee"
    # Still absent, and deliberately: TDS_194O (out by persona), FX_DIFF (cut).


class ComponentBasis(Enum):
    """HOW a component was typed. The axis the circularity gate turns on.

    Increment 1 established that our residuals are 100% typed by construction
    (D-015), because the world is simulated from the same components that explain
    it. That circularity resurfaces at Tier 1, and this enum is what makes it
    measurable rather than merely confessable:

      SCHEMA   -- read off a documented Sec 3.1 field the GATEWAY asserts
                  (`type == refund`, `dispute_id` present). We would read the
                  identical field from a real report, so this is not circular.
      CONTRACT -- derived from a rate-card constant (reserve rate, per-dispute
                  fee, instant fee rate). A real controller holds these too, but
                  we also generated with them, so it is partly circular and the
                  metrics say how much.

    There is deliberately no NARRATIVE member. Typing a line from `description` or
    `notes` -- prose we wrote -- is banned outright (D-017): it is fully circular
    AND it is the fuzzy string matching Sec 9 names as most likely to sink this.
    Its absence from this enum is the point; there is no value to record it as.
    """

    SCHEMA = "schema"
    CONTRACT = "contract"


@dataclass(frozen=True, slots=True)
class VarianceComponent:
    kind: ComponentType
    amount: Paise
    rule_version: str   # which slab/rule produced it -- reproducibility (Sec 4.1)
    basis: ComponentBasis

    def to_json(self) -> dict:
        return {"kind": self.kind.value, "amount": int(self.amount),
                "rule_version": self.rule_version, "basis": self.basis.value}


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
    # Which tier established the LINKAGE, as opposed to the current status.
    #
    # These come apart the moment an LLM is in the loop: Tier 3 can propose the
    # link, and Tier 1 must still explain the money, so the edge ends up with
    # tier=T1_ARITHMETIC and the adjudicator's contribution vanishes from both the
    # graph and the ablation. Recording it separately keeps `tier` meaning exactly
    # what it always meant -- the tier that produced the current status -- while
    # making "which tier made this edge possible" answerable.
    #
    # None means the linkage and the status came from the same tier.
    linked_by: Tier | None = None

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
    def established_by(self) -> Tier:
        """The tier that made this edge exist. An edge is only explained at tier N
        if BOTH its linkage and its explanation are within N, so the ablation is a
        max over the two rather than a read of either."""
        return self.linked_by or self.tier

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
            "linked_by": self.established_by.name,
        }
