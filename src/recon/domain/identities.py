"""The BRIEF Sec 3.2 arithmetic identities, as pure functions.

These are the credibility layer. Every one of them is a property test in
tests/test_identities.py, and the generator is built to satisfy them exactly so
that any deviation in the data is a real finding rather than our own bug.

THE ONE THING PEOPLE GET WRONG
------------------------------
`fee` is INCLUSIVE of `tax`. From the brief's transfer example:

    amount=100000, fee=296, tax=46  ->  debit = 100296   (NOT 100342)

`tax` is a memo breakout of the GST already inside `fee`, present so the merchant
can claim Input Tax Credit. Adding tax to fee double-counts it.

A DISCREPANCY IN THE BRIEF'S OWN EXAMPLE
----------------------------------------
That same example does not satisfy its own stated GST rule:

    mdr_base = fee - tax = 296 - 46 = 250
    250 * 18% = 45,  but the example says tax = 46      <- one paise off

There is no base that yields exactly 46 at 18% and still sums to 296
(46 / 0.18 = 255.6, while 296 - 46 = 250). So either production data rounds on a
pre-rounded base, or the documented example is illustrative rather than exact.

We do not paper over it. We state one canonical rule (below), generate data that
satisfies it exactly, and treat any deviation as the GST_ON_MDR_MISMATCH
exception, which is already in the Sec 6 taxonomy. In production that mismatch is
a thing a controller genuinely wants flagged, so this is the correct modelling
rather than a workaround. See test_brief_transfer_example_violates_its_own_gst_rule.
"""
from __future__ import annotations

from ..money import Paise, apply_rate_bps
from .rates import GST_RATE_BPS, RULE_VERSION  # noqa: F401  -- re-exported below

# --- Contracted rates ---------------------------------------------------------
# The rate CARD lives in domain/rates.py, which is the single source of truth for
# what a fee should have been. This module owns the arithmetic that turns a rate
# into a fee, and the identities that must hold over the result.
#
# MDR_RATE_BPS is the Increment 0 flat rate, kept only as the default for
# `quote_fee`. Increment 1 quotes per instrument via `quote_fee_at`, because a
# single rate makes MDR_SLAB_MISMATCH undetectable by construction.
MDR_RATE_BPS = 200    # 2.00%


# --- Fee construction (generator side) ----------------------------------------

def quote_fee_at(amount: Paise, mdr_rate_bps: int) -> tuple[Paise, Paise, Paise]:
    """Return (mdr_base, tax, fee) at a given MDR rate, fee INCLUSIVE of tax.

    The canonical rule referenced in the module docstring: compute the MDR base
    from gross, then GST on that base, then fee = base + tax. Rounding is
    half-up at each step, which is what makes the result reproducible rather
    than dependent on evaluation order.
    """
    base = apply_rate_bps(amount, mdr_rate_bps)
    tax = apply_rate_bps(base, GST_RATE_BPS)
    return base, tax, Paise(int(base) + int(tax))


def quote_fee(amount: Paise) -> tuple[Paise, Paise, Paise]:
    """`quote_fee_at` at the Increment 0 flat rate. Kept for the identity tests,
    which are about the arithmetic and not about any particular slab."""
    return quote_fee_at(amount, MDR_RATE_BPS)


# --- Identity checks (resolver side) ------------------------------------------

def mdr_base(fee: Paise, tax: Paise) -> Paise:
    """MDR net of the GST that is already inside `fee`."""
    return Paise(int(fee) - int(tax))


def expected_gst(base: Paise) -> Paise:
    return apply_rate_bps(base, GST_RATE_BPS)


def gst_on_mdr_holds(fee: Paise, tax: Paise) -> bool:
    """tax == round_half_up(mdr_base * 18%). Fires GST_ON_MDR_MISMATCH when False.

    Total over every input, including nonsense. `tax` reported ABOVE `fee` makes
    the MDR base negative, which is impossible when fee is inclusive of tax -- so
    it is the strongest possible form of this mismatch, and the honest answer is
    False rather than an exception. A checker that crashes on the very data it
    exists to catch is a checker that gets wrapped in a try/except and ignored.
    """
    base = mdr_base(fee, tax)
    if int(base) < 0:
        return False
    return int(tax) == int(expected_gst(base))


def payment_credit(amount: Paise, fee: Paise) -> Paise:
    """Payment line: credit = amount - fee.   100000 - 2900 = 97100"""
    return Paise(int(amount) - int(fee))


def refund_debit(amount: Paise) -> Paise:
    """Refund line: debit = amount, credit = 0."""
    return amount


def transfer_debit(amount: Paise, fee: Paise) -> Paise:
    """Transfer line: debit = amount + fee.   100000 + 296 = 100296

    Note the sign difference from payment: on a transfer the merchant pays the
    fee on top, rather than having it netted out of a credit.
    """
    return Paise(int(amount) + int(fee))


# --- Set-level identities -----------------------------------------------------
# These are properties of a GROUP of line items, which is exactly why the 1:N
# settlement->line grain is modelled as a set of binary edges with the identity
# checked over the set (PLAN.md, approved grain model) rather than stored on any
# single edge.

def rollup(credits: list[Paise], debits: list[Paise]) -> Paise:
    """settlement.amount = sum(credit) - sum(debit) over its line items."""
    return Paise(sum(int(c) for c in credits) - sum(int(d) for d in debits))


def rollup_holds(settlement_amount: Paise,
                 credits: list[Paise], debits: list[Paise]) -> bool:
    return int(settlement_amount) == int(rollup(credits, debits))


def bank_tie_out_holds(bank_credit_amount: Paise, settlement_amount: Paise) -> bool:
    """On a NET-settlement merchant the tie-out is exact, not approximate.

    Deductions are already inside settlement.amount, so any difference at all is
    a break rather than an expected fee gap. This is the identity that makes
    "explanation rate" a meaningful headline number.
    """
    return int(bank_credit_amount) == int(settlement_amount)
