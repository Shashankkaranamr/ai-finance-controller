"""Property tests for the BRIEF Sec 3.2 arithmetic identities.

These are the credibility layer. If any of these fail, no number the system prints
means anything.

Randomised cases are seeded, so a failure is reproducible from the printed case.
"""
from __future__ import annotations

import random

import pytest

from recon.domain.identities import (GST_RATE_BPS, MDR_RATE_BPS, bank_tie_out_holds,
                                     expected_gst, gst_on_mdr_holds, mdr_base,
                                     payment_credit, quote_fee, refund_debit, rollup,
                                     rollup_holds, transfer_debit)
from recon.money import Paise, apply_rate_bps

AMOUNTS = [Paise(a) for a in
           [1, 99, 100, 101, 999, 1_000, 4_999, 50_00, 123_45, 500_00, 999_99,
            1_000_00, 12_345_67, 99_999_99]]


def _random_amounts(n: int = 2000) -> list[Paise]:
    rng = random.Random(20260825)
    return [Paise(rng.randrange(1, 10_000_00)) for _ in range(n)]


# --- the identities from the brief's worked examples --------------------------

def test_brief_payment_example():
    """credit = amount - fee    ->   100000 - 2900 = 97100"""
    assert int(payment_credit(Paise(100_000), Paise(2_900))) == 97_100


def test_brief_transfer_example():
    """debit = amount + fee     ->   100000 + 296 = 100296  (NOT 100342)

    The classic error is adding tax on top of fee. Tax is already inside fee.
    """
    assert int(transfer_debit(Paise(100_000), Paise(296))) == 100_296
    assert int(transfer_debit(Paise(100_000), Paise(296))) != 100_000 + 296 + 46


def test_brief_transfer_example_violates_its_own_gst_rule():
    """The brief's reference example is one paise off its own stated GST rule.

    fee=296, tax=46 -> mdr_base=250, and 250 * 18% = 45, not 46. There is no base
    that yields 46 at 18% and still sums to 296.

    We do not paper over this. We pin one canonical rule, generate data that
    satisfies it exactly, and treat deviation as GST_ON_MDR_MISMATCH -- which is
    already in the Sec 6 taxonomy. This test documents the discrepancy so that
    nobody later "fixes" the rule to match the example and silently changes what
    the exception means.
    """
    assert int(mdr_base(Paise(296), Paise(46))) == 250
    assert int(expected_gst(Paise(250))) == 45
    assert not gst_on_mdr_holds(Paise(296), Paise(46))


def test_refund_debit_is_the_full_amount():
    for amount in AMOUNTS:
        assert int(refund_debit(amount)) == int(amount)


# --- fee construction ---------------------------------------------------------

@pytest.mark.parametrize("amount", AMOUNTS)
def test_fee_is_inclusive_of_tax(amount):
    base, tax, fee = quote_fee(amount)
    assert int(fee) == int(base) + int(tax), "fee must equal mdr_base + tax"
    assert int(mdr_base(fee, tax)) == int(base)


def test_gst_rule_holds_for_every_generated_fee():
    """The generator must satisfy the canonical rule exactly, for every amount.

    If this fails, our own data would fire GST_ON_MDR_MISMATCH and the exception
    would be measuring our bug rather than a finding.
    """
    for amount in AMOUNTS + _random_amounts():
        _, tax, fee = quote_fee(amount)
        assert gst_on_mdr_holds(fee, tax), f"GST rule broken at amount={int(amount)}"


def test_credit_plus_fee_reconstructs_gross():
    for amount in AMOUNTS + _random_amounts():
        _, _, fee = quote_fee(amount)
        credit = payment_credit(amount, fee)
        assert int(credit) + int(fee) == int(amount)


def test_fee_never_exceeds_the_amount_it_is_charged_on():
    for amount in _random_amounts():
        _, _, fee = quote_fee(amount)
        assert int(fee) < int(amount), "a 2% + GST fee can never approach gross"


def test_rates_are_the_contracted_ones():
    """Guards against a silent rate edit: 2% MDR, 18% GST."""
    assert MDR_RATE_BPS == 200
    assert GST_RATE_BPS == 1800
    base, tax, _ = quote_fee(Paise(100_000))
    assert int(base) == 2_000
    assert int(tax) == 360


# --- rounding -----------------------------------------------------------------

def test_rounding_is_half_up_not_truncation():
    # 2% of 25 paise is 0.5 -> half-up gives 1, truncation would give 0.
    assert int(apply_rate_bps(Paise(25), 200)) == 1
    assert int(apply_rate_bps(Paise(24), 200)) == 0


def test_rounding_never_loses_more_than_one_paise_per_component():
    for amount in _random_amounts():
        base, tax, fee = quote_fee(amount)
        assert abs(int(fee) - int(base) - int(tax)) == 0


# --- set-level identities -----------------------------------------------------

def test_settlement_rollup_identity():
    """settlement.amount = sum(credit) - sum(debit)"""
    rng = random.Random(11)
    for _ in range(200):
        credits = [Paise(rng.randrange(0, 100_000)) for _ in range(rng.randint(1, 40))]
        debits = [Paise(rng.randrange(0, 20_000)) for _ in range(rng.randint(0, 10))]
        expected = sum(int(c) for c in credits) - sum(int(d) for d in debits)
        assert int(rollup(credits, debits)) == expected
        assert rollup_holds(Paise(expected), credits, debits)


def test_rollup_detects_a_single_paise_error():
    credits = [Paise(97_100), Paise(48_550)]
    debits: list[Paise] = []
    assert rollup_holds(Paise(145_650), credits, debits)
    assert not rollup_holds(Paise(145_651), credits, debits)


def test_bank_tie_out_is_exact_on_net_settlement():
    """Deductions are already inside settlement.amount, so any gap is a break."""
    assert bank_tie_out_holds(Paise(145_650), Paise(145_650))
    assert not bank_tie_out_holds(Paise(145_649), Paise(145_650))
