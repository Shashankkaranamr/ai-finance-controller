"""Contracted rate card -- the MDR slab table and the rest of the deduction stack.

Increment 0 carried a single flat 200 bps MDR because a slab table with one row
is a lie about what the system knows. This is the real thing: MDR varies by
`method`, and within cards by `card_network` and `card_type` (BRIEF Sec 3.3).

WHY THIS MODULE IS THE PRECONDITION FOR `MDR_SLAB_MISMATCH`
-----------------------------------------------------------
Tier 0 checks the identities that hold between the numbers the source *reports*.
It can prove `credit = amount - fee` and `tax = 18% of (fee - tax)` without
knowing anything about a contract. What it cannot say is "you were overcharged",
because that requires a second, independent opinion about what the fee should
have been. This table is that opinion. Until it existed, `MDR_SLAB_MISMATCH` had
nothing to compare against, which is why Inc 0 declined to declare it.

That also fixes the Tier 0 / Tier 1 boundary precisely:
  Tier 0 -- identities over reported values.
  Tier 1 -- reported values vs THIS table.

EVERYTHING IS INTEGER BASIS POINTS
----------------------------------
9873 == 98.73%. No float exists in this package (tests/test_no_floats.py scans
for it by AST), so a rate is never a ratio and a percentage is never a literal.

RATE SHAPE
----------
Mirrors the shape of published Indian gateway pricing rather than inventing
numbers: UPI is zero-MDR for merchants (mandated in India since Jan 2020),
domestic cards and netbanking sit around 2%, debit is capped lower, Amex and
international sit higher. The exact values matter far less than the fact that
they VARY by key -- a single rate would make slab mismatch undetectable by
construction, which is the failure this table exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass

RULE_VERSION = "inc1.slab-v1.gst-1800bps.reserve-500bps"

GST_RATE_BPS = 1800   # 18% on the MDR base, unchanged from Inc 0

# --- MDR slab table -----------------------------------------------------------
# Key: (method, card_network, card_type). `None` is a wildcard in that position,
# and a more specific key wins -- see `mdr_rate_bps` for the lookup order.

SlabKey = tuple[str | None, str | None, str | None]

MDR_SLABS: dict[SlabKey, int] = {
    # UPI: zero MDR for merchants. This is not a simplification -- it is the law,
    # and it is why a UPI-heavy merchant's settlements are nearly all cash.
    ("upi", None, None): 0,

    ("netbanking", None, None): 190,
    ("wallet", None, None): 200,

    # Cards, by network and type. Debit is capped well below credit.
    ("card", "visa", "debit"): 90,
    ("card", "mastercard", "debit"): 90,
    ("card", "rupay", "debit"): 60,
    ("card", "visa", "credit"): 200,
    ("card", "mastercard", "credit"): 200,
    ("card", "rupay", "credit"): 180,
    ("card", "amex", "credit"): 350,
    # International issuance, whatever the network.
    ("card", "visa", "international"): 300,
    ("card", "mastercard", "international"): 300,
    ("card", "amex", "international"): 400,

    # Fallback for a card whose network/type did not resolve.
    ("card", None, None): 200,
}

# The order a lookup degrades through. Most specific first; the first hit wins.
_LOOKUP_ORDER: tuple[tuple[bool, bool, bool], ...] = (
    (True, True, True),      # method + network + type
    (True, True, False),     # method + network
    (True, False, False),    # method only
)


def mdr_rate_bps(method: str,
                 card_network: str | None = None,
                 card_type: str | None = None) -> int:
    """The contracted MDR rate in basis points for this instrument.

    Degrades from the most specific key to the least. Raises rather than
    defaulting on an unknown method: silently charging 0% for a method we forgot
    to price would make the residual land on zero for the wrong reason, and a
    residual that is right by accident is exactly what false-clear measures.
    """
    parts = (method, card_network, card_type)
    for mask in _LOOKUP_ORDER:
        key = tuple(part if use else None for part, use in zip(parts, mask))
        if key in MDR_SLABS:
            return MDR_SLABS[key]
    raise KeyError(
        f"no MDR slab for method={method!r} network={card_network!r} type={card_type!r}")


# --- The rest of the deduction stack ------------------------------------------

ROLLING_RESERVE_BPS = 500      # 5% of each settlement, withheld

# BRIEF Sec 3.3 says a reserve is typically held 90-180 days. We model 45.
#
# This is a deliberate, stated deviation. With a 90-day extract and a 90-day
# hold, not one release originating inside the window ever lands inside it, so
# the "release must be matched back to the cycle it came from" requirement --
# the only interesting thing about a reserve -- would go completely unexercised,
# and RESERVE_RELEASE_UNMATCHED would be untestable. 45 days puts both ends of
# the identity inside one extract. The mechanism is what we are modelling; the
# calendar constant is not what makes it credible.
RESERVE_HOLD_DAYS = 45

# Per-dispute fee, flat. Sec 3.3: typically Rs 500-2,000, and a SEPARATE line
# item from the reversal -- conflating them is a real-world booking error and
# CHARGEBACK_FEE_UNBOOKED exists precisely because they come apart.
CHARGEBACK_FEE_PAISE = 150_000     # Rs 1,500

# How long after a transfer is initiated the credit may still post, in calendar
# days. Same class of constant as the reserve rate: CONTRACT knowledge, not
# something read off the data -- a real deployment takes it from the bank's
# posting SLA. It exists because `settled_at != bank value date` (BRIEF Sec 3.4),
# and Tier 2 needs a bound on "could this credit be that settlement" that is a
# fact about settlement mechanics rather than a tolerance chosen to make matches.
#
# 3 days is the widest gap the mechanism can produce: a transfer initiated on a
# Friday, posting one business day later, lands on Monday.
# `test_the_posting_window_bounds_every_generated_credit` fails if the generator
# ever exceeds it, so the two cannot drift apart silently.
BANK_POSTING_WINDOW_DAYS = 3

# Instant (on-demand, setlod_*) settlements carry their own fee on top of MDR.
INSTANT_SETTLEMENT_FEE_BPS = 25    # 0.25%


@dataclass(frozen=True, slots=True)
class Instrument:
    """The payment instrument, which is what the slab is keyed on."""

    method: str
    card_network: str | None = None
    card_type: str | None = None

    @property
    def rate_bps(self) -> int:
        return mdr_rate_bps(self.method, self.card_network, self.card_type)


# The instrument mix for the modelled merchant. Weights are integers so that
# selection stays in integer arithmetic and the generator remains deterministic
# under a seeded RNG. UPI-heavy with real card volume: enough UPI that most
# settlements are nearly all cash, enough card that disputes and a reserve have
# somewhere to land (PLAN.md, Inc 1 scope -- one merchant, mixed profile).
INSTRUMENT_MIX: tuple[tuple[Instrument, int], ...] = (
    (Instrument("upi"), 46),
    (Instrument("netbanking"), 10),
    (Instrument("wallet"), 4),
    (Instrument("card", "visa", "debit"), 12),
    (Instrument("card", "mastercard", "debit"), 6),
    (Instrument("card", "rupay", "debit"), 4),
    (Instrument("card", "visa", "credit"), 10),
    (Instrument("card", "mastercard", "credit"), 4),
    (Instrument("card", "amex", "credit"), 2),
    (Instrument("card", "visa", "international"), 2),
)

CARD_ISSUERS: tuple[str, ...] = ("HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "CITI")
