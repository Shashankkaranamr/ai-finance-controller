"""Money. Integer paise only -- there is no float anywhere in this package.

BRIEF Sec 3.2: "All money is integer paise. Never use floats anywhere in the
pipeline." A float in a reconciliation engine accumulates representation error,
which makes `residual == 0` both unachievable and untestable.

We go one step further than the brief: rates and percentages are carried as
integer basis points too (see report/metrics.py), so `tests/test_no_floats.py`
can assert that the *entire* package is float-free by AST scan. That turns a
style rule into a checkable property.
"""
from __future__ import annotations

from typing import NewType

Paise = NewType("Paise", int)

BPS = 10_000  # basis points in 1.0 (100%)


def rupees_to_paise(rupees: int, paise: int = 0) -> Paise:
    """Build paise from whole rupees. Never parses a float."""
    if not 0 <= paise < 100:
        raise ValueError(f"paise component out of range: {paise}")
    return Paise(rupees * 100 + paise)


def apply_rate_bps(amount: Paise, rate_bps: int) -> Paise:
    """amount * rate, rounded half-up, in integer arithmetic.

    Half-up rather than banker's rounding because that is what Indian fee
    schedules do, and because it is the rule we can state in one line and test.
    Defined for non-negative amounts; the pipeline has no negative gross values.
    """
    if amount < 0:
        raise ValueError(f"apply_rate_bps expects a non-negative amount, got {amount}")
    return Paise((amount * rate_bps + BPS // 2) // BPS)


def ratio_bps(numerator: int, denominator: int) -> int:
    """A rate as integer basis points, rounded half-up. 9873 == 98.73%.

    Returns 0 for an empty denominator: a rate over nothing is reported as 0
    alongside its denominator, never as a crash or a silent NaN.
    """
    if denominator == 0:
        return 0
    return (numerator * BPS + denominator // 2) // denominator


def format_bps(rate_bps: int) -> str:
    """9873 -> '98.73%'. Display only; the stored value stays an int."""
    whole, frac = divmod(abs(rate_bps), 100)
    sign = "-" if rate_bps < 0 else ""
    return f"{sign}{whole}.{frac:02d}%"


def format_inr(amount: Paise) -> str:
    """Indian digit grouping: 12345678901 paise -> 'Rs 12,34,56,789.01'.

    Lakh/crore grouping (last 3 digits, then pairs) rather than thousands --
    a finance reviewer reads the wrong magnitude out of Western grouping.
    """
    negative = amount < 0
    value = -amount if negative else amount
    rupees, paise = divmod(value, 100)

    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail

    return f"{'-' if negative else ''}Rs {digits}.{paise:02d}"
