"""World simulator -- truth first, views derived from it (BRIEF Sec 5).

Never generate three files and try to label them afterwards: the labels would
encode the matcher's own assumptions, and the eval would measure agreement with
ourselves rather than accuracy.

Increment 0 world: one direct merchant, net settlement, single gateway, T+2,
payments only. No refunds, disputes, reserve or slab variation -- those arrive in
Increment 1. One anomaly class is injected (MISSING_BANK_CREDIT) so the exception
path is exercised end to end rather than left untested.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..domain.graph import ComponentType, ExceptionType
from ..domain.identities import RULE_VERSION, quote_fee
from ..domain.truth import GroundTruth, TruthComponent, TruthEdge, TruthUnit
from ..money import Paise

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_UTR_TAIL = "abcdefghijklmnopqrstuvwxyz0123456789"

METHODS = ("upi", "card", "netbanking")


@dataclass(frozen=True, slots=True)
class GenConfig:
    seed: str
    n_cycles: int = 6
    orders_per_cycle: tuple[int, int] = (28, 40)
    amount_range_paise: tuple[int, int] = (5_000, 500_000)   # Rs 50 -- Rs 5,000
    start_date: date = date(2026, 6, 1)
    settlement_lag_days: int = 2          # T+2
    missing_bank_credit_cycle: int = 3     # inject exactly one MISSING_BANK_CREDIT


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    receipt: str
    customer_id: str
    gross: Paise
    created_on: date
    method: str


@dataclass(frozen=True, slots=True)
class Payment:
    payment_id: str
    line_id: str            # setlodp_* -- the recon line item's entity_id
    order_id: str
    amount: Paise           # gross
    mdr_base: Paise
    tax: Paise
    fee: Paise              # INCLUSIVE of tax
    credit: Paise           # amount - fee
    captured_on: date
    settled_on: date
    settlement_id: str
    method: str


@dataclass(frozen=True, slots=True)
class Settlement:
    settlement_id: str
    utr: str
    settled_on: date
    amount: Paise
    cycle_index: int
    has_bank_credit: bool


@dataclass(slots=True)
class World:
    config: GenConfig
    orders: list[Order] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)


def _rng(seed: str):
    """Seeded from a stable CRC of the seed string.

    Python's builtin hash() is salted per process, so it must never touch a
    seeding path in a system that claims byte-identical runs.
    """
    import random
    return random.Random(zlib.crc32(seed.encode("utf-8")))


def _rid(rng, prefix: str, n: int = 14) -> str:
    return prefix + "".join(rng.choice(_ID_ALPHABET) for _ in range(n))


def _utr(rng) -> str:
    """Razorpay-shaped UTR: 10 digits then 6 lowercase alphanumerics."""
    return f"{rng.randrange(10**9, 10**10)}" + "".join(
        rng.choice(_UTR_TAIL) for _ in range(6))


def build_world(config: GenConfig) -> World:
    rng = _rng(config.seed)
    world = World(config=config)

    for cycle in range(config.n_cycles):
        order_date = config.start_date + timedelta(days=cycle)
        settled_on = order_date + timedelta(days=config.settlement_lag_days)
        settlement_id = _rid(rng, "setl_")
        utr = _utr(rng)

        n_orders = rng.randint(*config.orders_per_cycle)
        cycle_payments: list[Payment] = []

        for _ in range(n_orders):
            gross = Paise(rng.randrange(*config.amount_range_paise))
            base, tax, fee = quote_fee(gross)
            order_id = _rid(rng, "order_")
            order = Order(
                order_id=order_id,
                receipt=f"rcpt-{rng.randrange(10**6, 10**7)}",
                customer_id=f"cust_{rng.randrange(10**5, 10**6)}",
                gross=gross,
                created_on=order_date,
                method=rng.choice(METHODS),
            )
            payment = Payment(
                payment_id=_rid(rng, "pay_"),
                line_id=_rid(rng, "setlodp_"),
                order_id=order_id,
                amount=gross,
                mdr_base=base,
                tax=tax,
                fee=fee,
                credit=Paise(int(gross) - int(fee)),
                captured_on=order_date,
                settled_on=settled_on,
                settlement_id=settlement_id,
                method=order.method,
            )
            world.orders.append(order)
            world.payments.append(payment)
            cycle_payments.append(payment)

        world.settlements.append(Settlement(
            settlement_id=settlement_id,
            utr=utr,
            settled_on=settled_on,
            # Rollup identity by construction: sum(credit) - sum(debit), no debits yet.
            amount=Paise(sum(int(p.credit) for p in cycle_payments)),
            cycle_index=cycle,
            has_bank_credit=(cycle != config.missing_bank_credit_cycle),
        ))

    return world


def emit_ground_truth(world: World) -> GroundTruth:
    """Truth is emitted from the simulator, never inferred from the views."""
    units: list[TruthUnit] = []
    edges: list[TruthEdge] = []
    components: dict[str, tuple[TruthComponent, ...]] = {}

    payments_by_settlement: dict[str, list[Payment]] = {}
    for payment in world.payments:
        payments_by_settlement.setdefault(payment.settlement_id, []).append(payment)

    for order in world.orders:
        units.append(TruthUnit("book_entry", order.order_id, int(order.gross), None, False))

    for payment in world.payments:
        units.append(TruthUnit("line_item", payment.line_id, int(payment.amount), None, False))
        edges.append(TruthEdge("settlement_to_line", payment.settlement_id, payment.line_id))
        edges.append(TruthEdge("line_to_book", payment.line_id, payment.order_id))

    for settlement in world.settlements:
        members = payments_by_settlement.get(settlement.settlement_id, [])
        anomaly = None if settlement.has_bank_credit else ExceptionType.MISSING_BANK_CREDIT
        units.append(TruthUnit(
            "settlement", settlement.settlement_id, int(settlement.amount),
            anomaly.code if anomaly else None,
            anomaly.is_break if anomaly else False))

        # The true decomposition of gross -> cash for this settlement. Stored even
        # when the bank credit is missing, so a later tier cannot "explain" it by
        # accident and have that pass unnoticed.
        components[settlement.settlement_id] = (
            TruthComponent(ComponentType.MDR.value,
                           sum(int(p.mdr_base) for p in members)),
            TruthComponent(ComponentType.GST_ON_MDR.value,
                           sum(int(p.tax) for p in members)),
        )

        if settlement.has_bank_credit:
            bank_uid = bank_uid_for(settlement)
            units.append(TruthUnit("bank_credit", bank_uid, int(settlement.amount), None, False))
            edges.append(TruthEdge("bank_to_settlement", bank_uid, settlement.settlement_id))

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
