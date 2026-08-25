"""Bank narration templates, split into dev and eval families.

WHY THE SPLIT EXISTS (PLAN.md deviation #4)
-------------------------------------------
BRIEF Sec 3.5 is right that messy narration is the legitimate place for an LLM.
But *we write the narrations*. If a deterministic parser is authored against the
same templates that generate the evaluation data, the parser wins trivially and
the ablation "proves" the LLM adds nothing -- a fact about our generator, not
about reality. A panel will spot that immediately.

So: templates carry a `split`. Deterministic parsers in this repo are written
ONLY against `dev` families. `eval` families are held out at the TEMPLATE level,
not just the seed level, and the parser author does not tune against them.

Increment 0 generates from `dev` families only; the eval families are declared
here now so the constraint is structural rather than a promise. Increment 1
starts generating from both.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

SPLIT_DEV = "dev"
SPLIT_EVAL = "eval"


@dataclass(frozen=True, slots=True)
class TemplateFamily:
    name: str
    split: str
    template: str
    truncate_at: int | None = None   # some banks cut the field short


# Shapes taken from BRIEF Sec 3.5.
FAMILIES: tuple[TemplateFamily, ...] = (
    TemplateFamily("neft_rzpxfer", SPLIT_DEV,
                   "NEFT CR-RAZORPAY SOFTWARE PVT LTD-{utr}-RZPXFER"),
    TemplateFamily("imps_p2a", SPLIT_DEV,
                   "IMPS/P2A/{ref}/RAZORPAYSOF/SETTLEMENT-{utr}"),
    TemplateFamily("upi_setl", SPLIT_DEV,
                   "UPI-RAZORPAY-SETL-{utr_upper}-PAYMENT FROM PHONE"),

    # --- HELD OUT. Do not read these when writing a parser. ---
    TemplateFamily("neft_truncated", SPLIT_EVAL,
                   "NEFT-RAZORPAYSOFTWAREPVTLT-UTR{utr}", truncate_at=40),
    TemplateFamily("rtgs_no_delimiter", SPLIT_EVAL,
                   "RTGS CR RAZORPAY{utr}SETTLEMENT"),
)


def families_for(split: str) -> tuple[TemplateFamily, ...]:
    return tuple(f for f in FAMILIES if f.split == split)


def render(family: TemplateFamily, utr: str, rng: random.Random) -> str:
    text = family.template.format(
        utr=utr,
        utr_upper=utr.upper(),
        ref=str(rng.randrange(10**11, 10**12)),
    )
    if family.truncate_at is not None:
        text = text[: family.truncate_at]
    return text


# --- Parsing -----------------------------------------------------------------
# Authored against the DEV families only. It is deliberately one generic pattern
# rather than three template-specific ones: a per-template parser would be
# overfitting to data we wrote, and would collapse the moment Inc 1 turns on the
# eval families. When it starts failing there, that failure is the real signal
# about where an LLM earns its place.

import re  # noqa: E402  -- kept next to the pattern it serves

_UTR_PATTERN = re.compile(r"(?<![0-9a-zA-Z])([0-9]{10}[a-z0-9]{6})(?![0-9a-zA-Z])",
                          re.IGNORECASE)


def parse_utr(narration: str) -> str | None:
    """Extract the settlement UTR from a bank narration, or None.

    Returns lowercase. A hit here is only ever a *candidate*: the caller verifies
    it by exact lookup against known settlements, so a bad extraction cannot
    survive into a match.
    """
    match = _UTR_PATTERN.search(narration)
    return match.group(1).lower() if match else None
