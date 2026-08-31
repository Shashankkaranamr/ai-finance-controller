"""World simulator -- truth first, views derived from it (BRIEF Sec 5).

Never generate three files and try to label them afterwards: the labels would
encode the matcher's own assumptions, and the eval would measure agreement with
ourselves rather than accuracy.

INCREMENT 1 WORLD
-----------------
One merchant, net settlement, single gateway, mixed instrument profile. The whole
Sec 3.3 deduction stack except TDS 194-O (out by persona, PLAN.md Assumption 1):
MDR by slab, GST on MDR, rolling reserve withheld and released, refund offsets,
chargeback reversals and their separate per-dispute fee, third-party transfers,
and instant `setlod_*` settlements with their own fee.

All four Sec 3.1 line types are produced: payment, refund, transfer, adjustment.
Adjustments carry a `component` so the reason for the debit survives into truth
rather than being guessed at by whoever reads the report later.

THE SIGN CONVENTION, ONCE
-------------------------
Every truth component is a POSITIVE amount that widens the gross-to-cash gap,
except RESERVE_RELEASE which is money coming back and is carried negative. So for
every settlement, with no per-kind branching anywhere downstream:

    sum(payment.amount) - bank_credit - sum(components) == 0

`test_world_components_close_the_gap` asserts exactly that over every settlement
of both seeds. It is the identity this entire module exists to satisfy, and it is
what lets Increment 2 measure a residual distribution rather than argue about one.

WHAT IS DELIBERATELY STILL ABSENT
---------------------------------
Tier 1 decomposition, any LLM, FX, multi-gateway, a second merchant. Increment 1
adds data and measurement, not resolver capability -- see PLAN.md, Increment 1.
"""
from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from ..domain.graph import ComponentType, ExceptionType
from ..domain.identities import quote_fee_at
from ..domain.rates import (CARD_ISSUERS, CHARGEBACK_FEE_PAISE, INSTANT_SETTLEMENT_FEE_BPS,
                            INSTRUMENT_MIX, RESERVE_HOLD_DAYS, ROLLING_RESERVE_BPS,
                            RULE_VERSION, Instrument)
from ..domain.truth import GroundTruth, TruthComponent, TruthEdge, TruthUnit
from ..money import Paise, apply_rate_bps
from .narration import SPLIT_DEV

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_UTR_TAIL = "abcdefghijklmnopqrstuvwxyz0123456789"

BPS_DENOMINATOR = 10_000

# Sec 5 asks for 60-90 days and 15-25 settlement cycles. 88 days on a 4-day
# cycle gives 22 of them, and ~1,700 line items -- comfortably inside both
# bands without sitting on either edge.
DEFAULT_DAYS = 88


# --- configuration ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AnomalyRates:
    """Injection rates, in basis points of the population they apply to.

    Integers, not percentages: the whole package is float-free, and a rate that
    cannot be written as a literal cannot drift into the money path.

    These are TUNED AGAINST A MEASURED INTRINSIC CLEAN RATE (85-92%, PLAN.md
    Increment 1 gate condition 4), not chosen to look plausible. See RUN_LOG.md
    for what they actually produced.
    """

    # applied per book entry / payment line
    book_amount_mismatch_bps: int = 400
    duplicate_payment_bps: int = 90
    mdr_slab_mismatch_bps: int = 500
    gst_mismatch_bps: int = 260
    on_hold_bps: int = 350
    # applied per payment: does it get refunded / disputed at all
    refund_bps: int = 700
    dispute_bps: int = 220
    # applied per dispute
    chargeback_unlinked_bps: int = 3000
    # whole-run counts, not rates -- these are single events, and a rate over 22
    # settlements would make the count jump between seeds for no modelled reason
    refund_orphan_count: int = 9
    missing_bank_credit_count: int = 1
    unmatched_bank_credit_count: int = 2
    duplicate_utr_count: int = 1
    # Cycles settled instantly (setlod_*) rather than on schedule. A COUNT, not
    # a rate: at ~9% over 22 cycles a seed can legitimately draw zero, and the
    # eval seed did -- leaving INSTANT_SETTLEMENT_FEE absent from the deduction
    # stack on one seed but not the other. A gate condition that holds on dev
    # and not on eval is worse than one that fails on both.
    instant_settlement_count: int = 2
    # share of orders whose invoice date straddles the month-end close
    period_cutoff_bps: int = 1600
    # third-party payouts per cycle
    transfers_per_cycle: tuple[int, int] = (0, 2)


@dataclass(frozen=True, slots=True)
class GenConfig:
    seed: str
    split: str = SPLIT_DEV                 # which narration families render
    n_days: int = DEFAULT_DAYS
    cycle_length_days: int = 4             # -> 22 settlement cycles (Sec 5: 15-25)
    orders_per_day: tuple[int, int] = (14, 22)
    amount_range_paise: tuple[int, int] = (5_000, 500_000)   # Rs 50 -- Rs 5,000
    start_date: date = date(2026, 4, 1)
    settlement_lag_days: int = 2           # T+2 from cycle close
    anomalies: AnomalyRates = field(default_factory=AnomalyRates)

    @property
    def n_cycles(self) -> int:
        return self.n_days // self.cycle_length_days


# --- entities -----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    receipt: str
    customer_id: str
    gross: Paise
    created_on: date
    invoice_on: date          # what the ERP booked; differs at a period cutoff
    instrument: Instrument
    card_issuer: str | None
    anomaly: ExceptionType | None = None
    booked_gross: Paise | None = None   # ERP value when it disagrees with truth


@dataclass(frozen=True, slots=True)
class LineItem:
    """One row of the Razorpay settlement recon report (Sec 3.1).

    A single type covering all four `type` values, because the rollup identity
    and the settlement membership grain treat them uniformly -- the differences
    live in debit/credit and in `component`, not in the shape of the record.
    """

    line_id: str              # setlodp_* -- the recon line's entity_id
    kind: str                 # payment | refund | transfer | adjustment
    amount: Paise
    fee: Paise                # INCLUSIVE of tax
    tax: Paise
    debit: Paise
    credit: Paise
    settlement_id: str
    created_on: date
    settled_on: date
    posted_on: date
    order_id: str | None = None
    order_receipt: str | None = None
    payment_id: str | None = None      # own id for a payment; the target for a refund
    refund_id: str | None = None
    transfer_id: str | None = None
    adjustment_id: str | None = None
    dispute_id: str | None = None
    instrument: Instrument | None = None
    card_issuer: str | None = None
    on_hold: bool = False
    settled: bool = True
    component: ComponentType | None = None   # what this line IS, for adjustments
    notes: str = ""
    description: str = ""
    anomaly: ExceptionType | None = None
    # The originating settlement for a reserve release. Carried as a reference in
    # `notes` on the derived view; kept typed here so truth never has to parse it.
    releases_settlement_id: str | None = None

    @property
    def net(self) -> int:
        return int(self.credit) - int(self.debit)


@dataclass(frozen=True, slots=True)
class Settlement:
    settlement_id: str
    utr: str
    cycle_index: int
    capture_from: date
    capture_to: date
    settled_on: date
    is_instant: bool
    amount: Paise = Paise(0)          # filled once its line items exist
    has_bank_credit: bool = True
    anomaly: ExceptionType | None = None


@dataclass(frozen=True, slots=True)
class ExtraBankCredit:
    """A bank credit with no settlement behind it, or a duplicate of one.

    Modelled explicitly rather than as a mutation of the derived view, so that
    ground truth knows about it at injection time (Sec 5: never label after
    the fact).
    """

    bank_ref: str
    value_date: date
    amount: Paise
    utr: str
    anomaly: ExceptionType
    narration_override: str | None = None


@dataclass(slots=True)
class World:
    config: GenConfig
    orders: list[Order] = field(default_factory=list)
    lines: list[LineItem] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    extra_bank_credits: list[ExtraBankCredit] = field(default_factory=list)
    # settlement_id -> ComponentType -> paise. Built during simulation, not after.
    components: dict[str, dict[ComponentType, int]] = field(default_factory=dict)

    def lines_of(self, settlement_id: str) -> list[LineItem]:
        return [line for line in self.lines if line.settlement_id == settlement_id]

    def settled_gross(self, settlement_id: str) -> Paise:
        """Expected gross for a settlement: settled payment lines only.

        An on_hold line is reported but has not moved, so it is not part of
        what this settlement was ever going to pay out. This is the `expected`
        side of the bank-to-settlement decomposition, and getting it wrong is
        the difference between a real residual and a self-inflicted one.
        """
        return Paise(sum(int(line.amount) for line in self.lines_of(settlement_id)
                         if line.kind == "payment" and line.settled))


# --- deterministic streams ----------------------------------------------------

def _stream(seed: str, name: str) -> random.Random:
    """An independent, named random stream.

    Separate streams per concern mean that changing how disputes are generated
    does not shift every order id downstream -- run-to-run diffs stay legible,
    and a tuning change to one anomaly rate does not reshuffle the whole world.

    Seeded from a stable CRC: Python's builtin hash() is salted per process and
    must never touch a seeding path in a system claiming byte-identical runs.
    """
    return random.Random(zlib.crc32(f"{seed}:{name}".encode("utf-8")))


def _rid(rng: random.Random, prefix: str, n: int = 14) -> str:
    return prefix + "".join(rng.choice(_ID_ALPHABET) for _ in range(n))


def _utr(rng: random.Random) -> str:
    """Razorpay-shaped UTR: 10 digits then 6 lowercase alphanumerics."""
    return f"{rng.randrange(10**9, 10**10)}" + "".join(
        rng.choice(_UTR_TAIL) for _ in range(6))


def _fires(rng: random.Random, rate_bps: int) -> bool:
    return rng.randrange(BPS_DENOMINATOR) < rate_bps


def _pick_instrument(rng: random.Random) -> Instrument:
    """Weighted choice in integer arithmetic -- no float weights anywhere."""
    total = sum(weight for _, weight in INSTRUMENT_MIX)
    roll = rng.randrange(total)
    for instrument, weight in INSTRUMENT_MIX:
        if roll < weight:
            return instrument
        roll -= weight
    return INSTRUMENT_MIX[-1][0]


def _add_component(world: World, settlement_id: str,
                   kind: ComponentType, amount: int) -> None:
    if amount == 0:
        return
    bucket = world.components.setdefault(settlement_id, {})
    bucket[kind] = bucket.get(kind, 0) + amount


# --- the simulation -----------------------------------------------------------

def build_world(config: GenConfig) -> World:
    world = World(config=config)
    _build_cycles(world)
    _build_payments(world)
    _build_transfers(world)
    _build_refunds(world)
    _build_disputes(world)
    _build_reserve(world)
    _inject_slab_and_gst_anomalies(world)
    _close_settlements(world)
    _inject_bank_anomalies(world)
    return world


def _build_cycles(world: World) -> None:
    config = world.config
    rng = _stream(config.seed, "cycles")

    instant = set(rng.sample(range(config.n_cycles),
                             config.anomalies.instant_settlement_count))

    for cycle in range(config.n_cycles):
        capture_from = config.start_date + timedelta(days=cycle * config.cycle_length_days)
        capture_to = capture_from + timedelta(days=config.cycle_length_days - 1)
        is_instant = cycle in instant
        # An instant settlement lands the day the cycle closes; a scheduled one
        # takes T+2. That difference is the whole point of setlod_* (Sec 3.4).
        settled_on = capture_to + timedelta(
            days=0 if is_instant else config.settlement_lag_days)
        world.settlements.append(Settlement(
            settlement_id=_rid(rng, "setlod_" if is_instant else "setl_"),
            utr=_utr(rng),
            cycle_index=cycle,
            capture_from=capture_from,
            capture_to=capture_to,
            settled_on=settled_on,
            is_instant=is_instant,
        ))


def _build_payments(world: World) -> None:
    config = world.config
    rng = _stream(config.seed, "payments")
    anomalies = config.anomalies

    for settlement in world.settlements:
        day = settlement.capture_from
        while day <= settlement.capture_to:
            for _ in range(rng.randint(*config.orders_per_day)):
                _emit_order_and_payment(world, rng, settlement, day)
            day += timedelta(days=1)

    # A duplicate payment is the SAME order paid twice -- a real and common break.
    # Injected after the fact against the finished population so the rate applies
    # to the whole run rather than to whichever cycle happened to be first.
    payments = [line for line in world.lines if line.kind == "payment"]
    for payment in list(payments):
        if payment.anomaly is None and _fires(rng, anomalies.duplicate_payment_bps):
            world.lines.append(replace(
                payment,
                line_id=_rid(rng, "setlodp_"),
                payment_id=_rid(rng, "pay_"),
                anomaly=ExceptionType.DUPLICATE_PAYMENT,
                description="Duplicate capture on an order already paid",
            ))


def _emit_order_and_payment(world: World, rng: random.Random,
                            settlement: Settlement, day: date) -> None:
    config = world.config
    anomalies = config.anomalies

    gross = Paise(rng.randrange(*config.amount_range_paise))
    instrument = _pick_instrument(rng)
    issuer = rng.choice(CARD_ISSUERS) if instrument.method == "card" else None
    base, tax, fee = quote_fee_at(gross, instrument.rate_bps)

    order_id = _rid(rng, "order_")
    receipt = f"rcpt-{rng.randrange(10**6, 10**7)}"

    # Period cutoff: the ERP books the invoice in the previous month while the
    # gateway captures in this one. Books and bank disagree CORRECTLY (Sec 3.4),
    # so this is explained-but-notable, never a break.
    invoice_on = day
    order_anomaly: ExceptionType | None = None
    if day.day <= 2 and _fires(rng, anomalies.period_cutoff_bps):
        invoice_on = day - timedelta(days=day.day)
        order_anomaly = ExceptionType.PERIOD_CUTOFF_TIMING

    # ERP manual entry error: the books carry a different gross to the gateway.
    booked_gross: Paise | None = None
    if order_anomaly is None and _fires(rng, anomalies.book_amount_mismatch_bps):
        drift = rng.choice((-500, -100, 100, 500, 1000))
        booked_gross = Paise(max(1, int(gross) + drift))
        order_anomaly = ExceptionType.BOOK_AMOUNT_MISMATCH

    world.orders.append(Order(
        order_id=order_id, receipt=receipt,
        customer_id=f"cust_{rng.randrange(10**5, 10**6)}",
        gross=gross, created_on=day, invoice_on=invoice_on,
        instrument=instrument, card_issuer=issuer,
        anomaly=order_anomaly, booked_gross=booked_gross,
    ))

    # on_hold: captured, reported, and never settled. The gateway is holding it
    # legitimately -- notable, not a break.
    #
    # An unsettled line carries NO fee and NO credit: nothing has moved yet, so
    # the gateway has charged nothing. Reporting a fee on it would break the
    # closing identity in a way that looks like an unexplained residual, and we
    # would then be measuring our own generator bug as a finding. The line still
    # appears in the report, which is what makes it visible to a reconciler --
    # and its `amount` is excluded from expected gross by `settled_gross`.
    on_hold = _fires(rng, anomalies.on_hold_bps)
    if on_hold:
        fee, tax = Paise(0), Paise(0)

    world.lines.append(LineItem(
        line_id=_rid(rng, "setlodp_"),
        kind="payment",
        amount=gross, fee=fee, tax=tax,
        debit=Paise(0),
        credit=Paise(0) if on_hold else Paise(int(gross) - int(fee)),
        settlement_id=settlement.settlement_id,
        created_on=day,
        settled_on=settlement.settled_on,
        posted_on=settlement.settled_on,
        order_id=order_id, order_receipt=receipt,
        payment_id=_rid(rng, "pay_"),
        instrument=instrument, card_issuer=issuer,
        on_hold=on_hold, settled=not on_hold,
        anomaly=ExceptionType.ON_HOLD_NOT_SETTLED if on_hold else None,
        description=f"Payment capture via {instrument.method}",
    ))


def _build_transfers(world: World) -> None:
    """Third-party payouts. Sec 3.2: transfer debit = amount + fee."""
    rng = _stream(world.config.seed, "transfers")
    low, high = world.config.anomalies.transfers_per_cycle

    for settlement in world.settlements:
        for _ in range(rng.randint(low, high)):
            amount = Paise(rng.randrange(50_000, 800_000))
            _base, tax, fee = quote_fee_at(amount, 200)
            world.lines.append(LineItem(
                line_id=_rid(rng, "setlodp_"),
                kind="transfer",
                amount=amount, fee=fee, tax=tax,
                debit=Paise(int(amount) + int(fee)), credit=Paise(0),
                settlement_id=settlement.settlement_id,
                created_on=settlement.capture_to,
                settled_on=settlement.settled_on,
                posted_on=settlement.settled_on,
                transfer_id=_rid(rng, "trf_"),
                description="Payout to linked account",
            ))


def _build_refunds(world: World) -> None:
    """Refunds, which mostly debit a LATER cycle than the payment they reverse.

    Sec 3.4 calls this out as structural: a refund for a payment settled in cycle
    N appears as a debit in cycle N+k. That crossing is timing, not a break, and
    it is the first real test of the REFUND_TO_PAYMENT grain declared on
    hypothesis in Increment 0.
    """
    config = world.config
    rng = _stream(config.seed, "refunds")
    settlements = sorted(world.settlements, key=lambda s: s.settled_on)

    for payment in [line for line in world.lines if line.kind == "payment"]:
        if payment.on_hold or not _fires(rng, config.anomalies.refund_bps):
            continue

        refund_on = payment.created_on + timedelta(days=rng.randint(3, 26))
        target = _settlement_on_or_after(settlements, refund_on)
        if target is None:
            continue    # falls off the end of the extract; the payment just stands

        crossed = target.settlement_id != payment.settlement_id
        amount = payment.amount if _fires(rng, 4000) else Paise(
            max(100, int(payment.amount) // rng.randint(2, 4)))

        world.lines.append(LineItem(
            line_id=_rid(rng, "setlodp_"),
            kind="refund",
            amount=amount, fee=Paise(0), tax=Paise(0),
            debit=amount, credit=Paise(0),
            settlement_id=target.settlement_id,
            created_on=refund_on,
            settled_on=target.settled_on,
            posted_on=target.settled_on,
            order_id=payment.order_id, order_receipt=payment.order_receipt,
            payment_id=payment.payment_id,
            refund_id=_rid(rng, "rfnd_"),
            instrument=payment.instrument, card_issuer=payment.card_issuer,
            anomaly=ExceptionType.REFUND_CROSS_CYCLE if crossed else None,
            description="Refund against captured payment",
        ))

    _build_orphan_refunds(world, rng, settlements)


def _build_orphan_refunds(world: World, rng: random.Random,
                          settlements: list[Settlement]) -> None:
    """THE DECLARED BLIND SPOT (PLAN.md Inc 1 gate condition 5).

    A refund whose original payment was captured BEFORE the extract window opens.
    The payment is not in the data at all -- not in books, not in the settlement
    report, nowhere. No tier can link it, and that includes an LLM: there is
    nothing to link it to. The system is expected to fail on this class, we say
    so in the README, and the failure is a property of the extract rather than of
    the matcher.
    """
    config = world.config
    for _ in range(config.anomalies.refund_orphan_count):
        target = settlements[rng.randrange(len(settlements))]
        amount = Paise(rng.randrange(20_000, 400_000))
        world.lines.append(LineItem(
            line_id=_rid(rng, "setlodp_"),
            kind="refund",
            amount=amount, fee=Paise(0), tax=Paise(0),
            debit=amount, credit=Paise(0),
            settlement_id=target.settlement_id,
            created_on=target.capture_to,
            settled_on=target.settled_on,
            posted_on=target.settled_on,
            payment_id=_rid(rng, "pay_"),      # a real id; the payment predates the window
            refund_id=_rid(rng, "rfnd_"),
            anomaly=ExceptionType.REFUND_ORPHANED,
            description="Refund against a payment captured before this extract",
        ))


def _settlement_on_or_after(settlements: list[Settlement], day: date) -> Settlement | None:
    return next((s for s in settlements if s.capture_from >= day
                 or (s.capture_from <= day <= s.capture_to)), None)


def _build_disputes(world: World) -> None:
    """Chargebacks: a reversal AND a separate per-dispute fee (Sec 3.3).

    Two line items, never one. They come apart in the real world -- the reversal
    gets booked and the fee does not -- which is exactly why the taxonomy carries
    CHARGEBACK_FEE_UNBOOKED as its own code.
    """
    config = world.config
    rng = _stream(config.seed, "disputes")
    anomalies = config.anomalies
    settlements = sorted(world.settlements, key=lambda s: s.settled_on)

    for payment in [line for line in world.lines if line.kind == "payment"]:
        if payment.instrument is None or payment.instrument.method != "card":
            continue
        if payment.on_hold or not _fires(rng, anomalies.dispute_bps):
            continue

        raised_on = payment.created_on + timedelta(days=rng.randint(10, 40))
        target = _settlement_on_or_after(settlements, raised_on)
        if target is None:
            continue

        dispute_id = _rid(rng, "disp_")
        unlinked = _fires(rng, anomalies.chargeback_unlinked_bps)

        world.lines.append(LineItem(
            line_id=_rid(rng, "setlodp_"),
            kind="adjustment",
            amount=payment.amount, fee=Paise(0), tax=Paise(0),
            debit=payment.amount, credit=Paise(0),
            settlement_id=target.settlement_id,
            created_on=raised_on,
            settled_on=target.settled_on,
            posted_on=target.settled_on,
            order_id=None if unlinked else payment.order_id,
            payment_id=payment.payment_id,
            adjustment_id=_rid(rng, "adj_"),
            dispute_id=dispute_id,
            component=ComponentType.CHARGEBACK_REVERSAL,
            anomaly=ExceptionType.CHARGEBACK_UNLINKED if unlinked else None,
            description="Chargeback reversal of disputed payment",
        ))

        # A SEPARATE line item from the reversal, always. Sec 3.3 is explicit, and
        # the two coming apart is the whole reason the fee is worth typing.
        world.lines.append(LineItem(
            line_id=_rid(rng, "setlodp_"),
            kind="adjustment",
            amount=Paise(CHARGEBACK_FEE_PAISE), fee=Paise(0), tax=Paise(0),
            debit=Paise(CHARGEBACK_FEE_PAISE), credit=Paise(0),
            settlement_id=target.settlement_id,
            created_on=raised_on,
            settled_on=target.settled_on,
            posted_on=target.settled_on,
            adjustment_id=_rid(rng, "adj_"),
            dispute_id=dispute_id,
            component=ComponentType.CHARGEBACK_FEE,
            description="Per-dispute chargeback fee",
        ))


def _build_reserve(world: World) -> None:
    """Rolling reserve: withheld on every cycle, released RESERVE_HOLD_DAYS later.

    Sec 3.3 is emphatic that a reserve is a receivable from the gateway and not
    settled cash. Modelled as two adjustment lines -- a debit when withheld, a
    credit when released -- so the money is visible on both legs and the release
    carries a typed reference back to the cycle it came from.
    """
    rng = _stream(world.config.seed, "reserve")
    by_cycle = sorted(world.settlements, key=lambda s: s.cycle_index)
    withheld: dict[str, tuple[Settlement, Paise]] = {}

    for settlement in by_cycle:
        payments = [line for line in world.lines
                    if line.settlement_id == settlement.settlement_id
                    and line.kind == "payment" and not line.on_hold]
        base = Paise(sum(int(line.credit) for line in payments))
        reserve = apply_rate_bps(base, ROLLING_RESERVE_BPS)
        if reserve == 0:
            continue

        withheld[settlement.settlement_id] = (settlement, reserve)
        world.lines.append(LineItem(
            line_id=_rid(rng, "setlodp_"),
            kind="adjustment",
            amount=reserve, fee=Paise(0), tax=Paise(0),
            debit=reserve, credit=Paise(0),
            settlement_id=settlement.settlement_id,
            created_on=settlement.capture_to,
            settled_on=settlement.settled_on,
            posted_on=settlement.settled_on,
            adjustment_id=_rid(rng, "adj_"),
            component=ComponentType.ROLLING_RESERVE,
            anomaly=ExceptionType.RESERVE_WITHHELD,
            description="Rolling reserve withheld",
        ))

    # Releases: a matured hold credited back on the first cycle settling at or
    # after origin + RESERVE_HOLD_DAYS.
    for origin_id, (origin, reserve) in sorted(withheld.items()):
        due = origin.settled_on + timedelta(days=RESERVE_HOLD_DAYS)
        target = next((s for s in by_cycle if s.settled_on >= due), None)
        if target is None:
            continue    # hold has not matured inside this extract
        world.lines.append(LineItem(
            line_id=_rid(rng, "setlodp_"),
            kind="adjustment",
            amount=reserve, fee=Paise(0), tax=Paise(0),
            debit=Paise(0), credit=reserve,
            settlement_id=target.settlement_id,
            created_on=due,
            settled_on=target.settled_on,
            posted_on=target.settled_on,
            adjustment_id=_rid(rng, "adj_"),
            component=ComponentType.RESERVE_RELEASE,
            releases_settlement_id=origin_id,
            description="Rolling reserve released",
            notes=f"release_of={origin_id}",
        ))


def _inject_slab_and_gst_anomalies(world: World) -> None:
    """Fee anomalies, injected onto payment lines that are otherwise clean.

    MDR_SLAB_MISMATCH is the gateway charging off-contract. It is invisible to
    Tier 0 by construction -- Tier 0 only knows the fee the report states, and
    the report states this one consistently. Detecting it needs the rate card in
    domain/rates.py, which is exactly the Tier 0 / Tier 1 boundary.
    """
    config = world.config
    rng = _stream(config.seed, "fees")
    anomalies = config.anomalies

    for index, line in enumerate(world.lines):
        if line.kind != "payment" or line.anomaly is not None:
            continue

        if _fires(rng, anomalies.mdr_slab_mismatch_bps):
            # Charged at a rate the contract does not carry.
            wrong_rate = line.instrument.rate_bps + rng.choice((25, 50, 75, 100))
            _base, tax, fee = quote_fee_at(line.amount, wrong_rate)
            world.lines[index] = replace(
                line, fee=fee, tax=tax,
                credit=Paise(int(line.amount) - int(fee)),
                anomaly=ExceptionType.MDR_SLAB_MISMATCH,
                description="Payment capture (fee charged off-contract)")
            continue

        # A zero-fee line (UPI is zero-MDR) has no GST breakout to skew, and
        # nudging tax above fee there would make the MDR base negative -- an
        # impossible shape, not a realistic mismatch.
        if int(line.tax) > 3 and _fires(rng, anomalies.gst_mismatch_bps):
            # tax no longer equals 18% of (fee - tax). Fee is unchanged, so the
            # rollup still holds and ONLY the GST identity catches it.
            skewed = int(line.tax) + rng.choice((-3, -2, -1, 1, 2, 3))
            world.lines[index] = replace(
                line, tax=Paise(min(int(line.fee), max(1, skewed))),
                anomaly=ExceptionType.GST_ON_MDR_MISMATCH,
                description="Payment capture (GST breakout inconsistent)")


def _close_settlements(world: World) -> None:
    """Compute each settlement's amount, and record the true component split.

    `amount` is computed here ONCE from the line items, and then the derived
    settlement view reports it as its own independently sourced field (D-003).
    The rollup identity is only a real cross-check because the resolver has to
    recompute it from the report's line items and compare.

    EVERY deduction must exist as a LINE ITEM, not merely as an adjustment to the
    total. The instant-settlement fee was briefly modelled by subtracting it from
    `amount` directly, and that silently broke the rollup for every setlod_* cycle
    -- the report's own line items no longer summed to its own total, and Tier 0
    correctly reported a ROLLUP_MISMATCH that was ours, not the data's. If money
    moves, a row says so.
    """
    rng = _stream(world.config.seed, "close")

    for index, settlement in enumerate(world.settlements):
        if settlement.is_instant:
            prelim = sum(line.net for line in world.lines_of(settlement.settlement_id))
            fee = apply_rate_bps(Paise(max(0, prelim)), INSTANT_SETTLEMENT_FEE_BPS)
            if fee:
                world.lines.append(LineItem(
                    line_id=_rid(rng, "setlodp_"),
                    kind="adjustment",
                    amount=fee, fee=Paise(0), tax=Paise(0),
                    debit=fee, credit=Paise(0),
                    settlement_id=settlement.settlement_id,
                    created_on=settlement.capture_to,
                    settled_on=settlement.settled_on,
                    posted_on=settlement.settled_on,
                    adjustment_id=_rid(rng, "adj_"),
                    component=ComponentType.INSTANT_SETTLEMENT_FEE,
                    description="On-demand settlement fee",
                ))

        lines = world.lines_of(settlement.settlement_id)
        amount = Paise(sum(line.net for line in lines))

        payments = [line for line in lines if line.kind == "payment"]
        _add_component(world, settlement.settlement_id, ComponentType.MDR,
                       sum(int(p.fee) - int(p.tax) for p in payments))
        _add_component(world, settlement.settlement_id, ComponentType.GST_ON_MDR,
                       sum(int(p.tax) for p in payments))
        _add_component(world, settlement.settlement_id, ComponentType.REFUND_OFFSET,
                       sum(int(line.amount) for line in lines if line.kind == "refund"))
        _add_component(world, settlement.settlement_id, ComponentType.TRANSFER_OUT,
                       sum(int(line.debit) for line in lines if line.kind == "transfer"))
        for kind in (ComponentType.CHARGEBACK_REVERSAL, ComponentType.CHARGEBACK_FEE,
                     ComponentType.ROLLING_RESERVE, ComponentType.INSTANT_SETTLEMENT_FEE):
            _add_component(world, settlement.settlement_id, kind,
                           sum(int(line.debit) for line in lines if line.component is kind))
        # Money coming back is carried negative -- the one signed component, so
        # that residual = expected - actual - sum(components) never branches.
        _add_component(world, settlement.settlement_id, ComponentType.RESERVE_RELEASE,
                       -sum(int(line.credit) for line in lines
                            if line.component is ComponentType.RESERVE_RELEASE))

        world.settlements[index] = replace(settlement, amount=amount)

    # A settlement that nets to zero or below has no bank credit to explain, and
    # the whole headline grain is bank-credit shaped. Guard rather than model it:
    # a negative settlement is a real shape, but it is a different exception class
    # and inventing it here would be scope the gate did not ask for.
    for settlement in world.settlements:
        if int(settlement.amount) <= 0:
            raise AssertionError(
                f"settlement {settlement.settlement_id} netted to "
                f"{int(settlement.amount)} paise; refund/dispute rates are too high "
                "for the payment volume in a cycle")


def _inject_bank_anomalies(world: World) -> None:
    """Anomalies that live on the bank side of the world."""
    config = world.config
    rng = _stream(config.seed, "bank_anomalies")
    anomalies = config.anomalies
    settlements = sorted(world.settlements, key=lambda s: s.cycle_index)

    # A settlement processed with no bank credit at all. The absence IS the
    # anomaly -- there is no marker in the data for a reconciler to find.
    chosen = rng.sample(range(len(settlements)), anomalies.missing_bank_credit_count)
    for position in chosen:
        settlement = settlements[position]
        index = world.settlements.index(settlement)
        world.settlements[index] = replace(
            settlement, has_bank_credit=False,
            anomaly=ExceptionType.MISSING_BANK_CREDIT)

    live = [s for s in world.settlements if s.has_bank_credit]

    # A credit in the bank with no settlement behind it: another payer entirely.
    for _ in range(anomalies.unmatched_bank_credit_count):
        day = config.start_date + timedelta(days=rng.randrange(config.n_days))
        stray_utr = _utr(rng)
        world.extra_bank_credits.append(ExtraBankCredit(
            bank_ref=f"bc_{stray_utr}",
            value_date=day,
            amount=Paise(rng.randrange(100_000, 2_000_000)),
            utr=stray_utr,
            anomaly=ExceptionType.UNMATCHED_BANK_CREDIT,
            narration_override=(
                f"NEFT CR-ACME DISTRIBUTORS PVT LTD-{stray_utr}-VENDORPAY"),
        ))

    # The same UTR on two credits. The bank double-posted; the money arrived once.
    for _ in range(anomalies.duplicate_utr_count):
        if not live:
            break
        source = live[rng.randrange(len(live))]
        world.extra_bank_credits.append(ExtraBankCredit(
            bank_ref=f"bc_{source.utr}_dup",
            value_date=source.settled_on,
            amount=source.amount,
            utr=source.utr,
            anomaly=ExceptionType.DUPLICATE_UTR,
        ))


# --- ground truth -------------------------------------------------------------

def emit_ground_truth(world: World) -> GroundTruth:
    """Truth is emitted from the simulator, never inferred from the views."""
    units: list[TruthUnit] = []
    edges: list[TruthEdge] = []

    payments_by_id = {line.payment_id: line for line in world.lines
                      if line.kind == "payment" and line.payment_id}

    for order in world.orders:
        units.append(TruthUnit(
            "book_entry", order.order_id, int(order.gross),
            order.anomaly.code if order.anomaly else None,
            order.anomaly.is_break if order.anomaly else False))

    for line in world.lines:
        units.append(TruthUnit(
            "line_item", line.line_id, int(line.amount),
            line.anomaly.code if line.anomaly else None,
            line.anomaly.is_break if line.anomaly else False))
        edges.append(TruthEdge("settlement_to_line", line.settlement_id, line.line_id))

        if line.kind == "payment" and line.order_id:
            edges.append(TruthEdge("line_to_book", line.line_id, line.order_id))

        # The refund->payment grain, declared on hypothesis in Inc 0 and exercised
        # for the first time here. Orphan refunds get NO edge: the payment is not
        # in the extract, so there is no truth to link to -- and an edge to a
        # non-existent unit would quietly make the blind spot look resolvable.
        if line.kind == "refund" and line.payment_id in payments_by_id:
            edges.append(TruthEdge(
                "refund_to_payment", line.line_id,
                payments_by_id[line.payment_id].line_id))

    for settlement in world.settlements:
        units.append(TruthUnit(
            "settlement", settlement.settlement_id, int(settlement.amount),
            settlement.anomaly.code if settlement.anomaly else None,
            settlement.anomaly.is_break if settlement.anomaly else False))
        if settlement.has_bank_credit:
            bank_uid = bank_uid_for(settlement)
            units.append(TruthUnit(
                "bank_credit", bank_uid, int(settlement.amount), None, False))
            edges.append(TruthEdge(
                "bank_to_settlement", bank_uid, settlement.settlement_id))

    for extra in world.extra_bank_credits:
        units.append(TruthUnit(
            "bank_credit", extra.bank_ref, int(extra.amount),
            extra.anomaly.code, extra.anomaly.is_break))

    components = {
        settlement_id: tuple(
            TruthComponent(kind.value, amount)
            for kind, amount in sorted(bucket.items(), key=lambda kv: kv[0].value)
            if amount != 0)
        for settlement_id, bucket in world.components.items()
    }

    return GroundTruth(
        seed=world.config.seed,
        units=tuple(units),
        edges=tuple(edges),
        components=components,
    )


def bank_uid_for(settlement: Settlement) -> str:
    """Bank rows have no natural key, so derive a stable one from the settlement.

    Deterministic and independent of row order -- the alternative, a positional
    counter, would change every id whenever an upstream row count moved.
    """
    return f"bc_{settlement.utr}"


RULE_VERSION_USED = RULE_VERSION
