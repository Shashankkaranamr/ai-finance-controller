"""Pydantic schemas for the four source views.

Pydantic guards the boundary where untrusted input enters (and, from Increment 3,
where LLM structured output enters). Inside the pipeline the model is frozen
dataclasses -- see domain/graph.py. Validation at the edge, speed and immutability
in the middle.

`extra="forbid"` is deliberate. BRIEF Sec 8 lists "column renamed" as a failure to
engineer against: with extra fields forbidden, a renamed column fails loudly at
the row that carries it and gets quarantined, instead of silently arriving as
None three tiers later.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class BookEntryRow(BaseModel):
    """ERP / books view."""

    model_config = _STRICT

    order_id: str
    receipt: str
    customer_id: str
    gross_amount: int = Field(ge=0, description="paise")
    currency: Literal["INR"]
    invoice_date: date
    method: str

    @property
    def uid(self) -> str:
        return self.order_id


class SettlementLineRow(BaseModel):
    """Razorpay settlement recon line item (BRIEF Sec 3.1)."""

    model_config = _STRICT

    entity_id: str
    type: Literal["payment", "refund", "transfer", "adjustment"]
    debit: int = Field(ge=0, description="paise")
    credit: int = Field(ge=0, description="paise")
    amount: int = Field(ge=0, description="paise")
    currency: Literal["INR"]
    fee: int = Field(ge=0, description="paise, INCLUSIVE of tax")
    tax: int = Field(ge=0, description="paise, GST component already inside fee")
    on_hold: bool
    settled: bool
    created_at: date
    settled_at: date
    settlement_id: str
    settlement_utr: str
    payment_id: str
    order_id: str
    method: str

    @property
    def uid(self) -> str:
        return self.entity_id

    @property
    def net(self) -> int:
        """Signed contribution to the settlement rollup."""
        return self.credit - self.debit


class SettlementRow(BaseModel):
    """The settlement entity itself -- reported independently of its line items."""

    model_config = _STRICT

    id: str
    entity: Literal["settlement"]
    amount: int = Field(description="paise; can be negative in a heavy-refund cycle")
    status: str
    fees: int = Field(ge=0, description="paise")
    tax: int = Field(ge=0, description="paise")
    utr: str
    created_at: date

    @property
    def uid(self) -> str:
        return self.id


class BankCreditRow(BaseModel):
    """Bank statement credit: one lump per settlement, free-text narration."""

    model_config = _STRICT

    bank_ref: str
    value_date: date
    amount: int = Field(ge=0, description="paise")
    currency: Literal["INR"]
    narration: str
    # Generator provenance. Present in synthetic data, absent from a real
    # statement. Resolvers MUST NOT read it -- doing so would leak the answer.
    narration_family: str | None = None

    @property
    def uid(self) -> str:
        return self.bank_ref
