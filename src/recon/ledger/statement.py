"""Loop closure: the reconciliation statement, and balanced journal entries.

BRIEF Sec 4.1: the run must end in artifacts a controller would actually use.
Sec 1.3: "closes one finance-ops LOOP" means it ends in an action or artifact,
not a report a human then redoes.

WHY THIS IS IN INCREMENT 0 AT ALL (PLAN.md deviation #5)
--------------------------------------------------------
The footing identity is not a feature, it is a CONSTRAINT ON THE ENTITY MODEL.
Discovering at Increment 4 that our entities cannot produce a balancing statement
would invalidate everything built beneath them. On clean data it is nearly trivial
to make foot -- which is exactly why it costs almost nothing to prove now.

WHY IT IS A REAL TEST AND NOT A TAUTOLOGY
------------------------------------------
Each term comes from a DIFFERENT source:

    gross_sales           <- the BOOKS view
    settlements_received  <- the BANK view
    explained_variance    <- the RESOLVER's typed components
    exceptions_gross      <- the EXCEPTION QUEUE
    closing_receivable    <- what the books still carry as unsettled

It foots only if all four agree. Get the MDR arithmetic wrong by one paise and
cash + variance no longer equals the gross it relieved, and the statement fails.

ONE SUBTLETY WORTH STATING
---------------------------
The queue prioritises by CASH at risk (settlement.amount, net of fees already
deducted). The statement uses GROSS for the same settlements, because gross is
what the receivable was raised at. Both are right in their own context; the
statement prints the reconciling note so the two numbers are never mistaken for
a disagreement.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..domain.graph import ComponentType, EdgeKind, EdgeStatus, ReconEdge
from ..money import Paise, format_inr


@dataclass(frozen=True, slots=True)
class JournalLine:
    account: str
    debit: Paise
    credit: Paise

    def to_json(self) -> dict:
        return {"account": self.account, "debit": int(self.debit), "credit": int(self.credit)}


@dataclass(frozen=True, slots=True)
class JournalEntry:
    entry_id: str
    narrative: str
    lines: tuple[JournalLine, ...]

    @property
    def balances(self) -> bool:
        return (sum(int(l.debit) for l in self.lines)
                == sum(int(l.credit) for l in self.lines))

    def to_json(self) -> dict:
        return {"entry_id": self.entry_id, "narrative": self.narrative,
                "balances": self.balances, "lines": [l.to_json() for l in self.lines]}


@dataclass(frozen=True, slots=True)
class ReconStatement:
    opening_receivable: Paise
    gross_sales: Paise
    settlements_received: Paise
    explained_variance: Paise
    exceptions_gross: Paise
    closing_receivable: Paise
    exceptions_cash_at_risk: Paise

    @property
    def computed_closing(self) -> Paise:
        return Paise(int(self.opening_receivable) + int(self.gross_sales)
                     - int(self.settlements_received) - int(self.explained_variance)
                     - int(self.exceptions_gross))

    @property
    def foots(self) -> bool:
        return int(self.computed_closing) == int(self.closing_receivable)

    @property
    def difference(self) -> Paise:
        return Paise(int(self.computed_closing) - int(self.closing_receivable))

    def to_json(self) -> dict:
        return {
            "opening_receivable": int(self.opening_receivable),
            "gross_sales": int(self.gross_sales),
            "settlements_received": int(self.settlements_received),
            "explained_variance": int(self.explained_variance),
            "exceptions_gross": int(self.exceptions_gross),
            "closing_receivable": int(self.closing_receivable),
            "computed_closing": int(self.computed_closing),
            "difference": int(self.difference),
            "foots": self.foots,
        }

    def render(self) -> str:
        lines = [
            "# Reconciliation Statement",
            "",
            "Each term is sourced from a different system. It foots only if they agree.",
            "",
            "| Line | Source | Amount |",
            "|---|---|---:|",
            f"| {'Opening trade receivable':<44} | prior close | "
            f"{format_inr(self.opening_receivable):>20} |",
            f"| {'+ Gross sales':<44} | books | {format_inr(self.gross_sales):>20} |",
            f"| {'- Settlements received':<44} | bank | "
            f"{format_inr(self.settlements_received):>20} |",
            f"| {'- Explained variance (full deduction stack)':<44} | resolver | "
            f"{format_inr(self.explained_variance):>20} |",
            f"| {'- Exceptions, at gross':<44} | queue | "
            f"{format_inr(self.exceptions_gross):>20} |",
            # No padding inside the bold markers: trailing spaces there stop
            # markdown from rendering the emphasis at all.
            f"| **= Computed closing receivable** | | "
            f"**{format_inr(self.computed_closing)}** |",
            f"| {'Expected closing receivable':<44} | books | "
            f"{format_inr(self.closing_receivable):>20} |",
            f"| {'Difference':<44} | | {format_inr(self.difference):>20} |",
            "",
            f"**FOOTS: {'YES' if self.foots else 'NO'}**"
            + ("" if self.foots else "  <-- the run has failed; do not trust these numbers"),
            "",
            "## Note on the exception figure",
            "",
            f"The queue prioritises by cash at risk ({format_inr(self.exceptions_cash_at_risk)}), "
            f"net of fees the gateway already deducted. This statement uses gross "
            f"({format_inr(self.exceptions_gross)}) because gross is what the receivable "
            "was raised at. The difference is the whole deduction stack on the "
            "unsettled cycles -- fees, GST, reserve, refunds and disputes.",
        ]
        return "\n".join(lines) + "\n"


def build(edges: list[ReconEdge], repo, opening_receivable: Paise = Paise(0)) -> ReconStatement:
    members_by_settlement = repo.lines_by_settlement()

    explained_bank = [e for e in edges
                      if e.kind is EdgeKind.BANK_TO_SETTLEMENT
                      and e.status is EdgeStatus.EXPLAINED]
    explained_ids = {e.dst_uid for e in explained_bank}

    gross_sales = sum(b.gross_amount for b in repo.books.values())
    settlements_received = sum(int(e.decomposition.actual) for e in explained_bank)

    # EVERY typed component, not just MDR and GST. Tier 1 types seven more, and
    # summing a subset here is what stopped the statement footing the moment it
    # landed. The identity below is exactly what makes this a cross-source check:
    # cash comes from the bank, variance from the resolver, gross from the
    # settlement report, and they have to agree without being told to.
    explained_variance = sum(
        int(c.amount)
        for e in explained_bank
        for c in e.decomposition.components)

    # Settled PAYMENT lines only -- the same population Tier 0 and Tier 1 call
    # `expected`. Summing every line type would double-count a refund, which is
    # already a deduction inside the variance.
    def settled_gross(settlement_id: str) -> int:
        return sum(m.amount for m in members_by_settlement.get(settlement_id, [])
                   if m.is_settled_payment)

    relieved_gross = sum(settled_gross(sid) for sid in sorted(explained_ids))

    unexplained_ids = sorted(set(repo.settlements) - explained_ids)
    exceptions_gross = sum(settled_gross(sid) for sid in unexplained_ids)
    exceptions_cash = sum(repo.settlements[sid].amount for sid in unexplained_ids)

    # Orders that are in no settlement at all -- genuinely still in transit.
    closing_receivable = gross_sales - relieved_gross - exceptions_gross

    return ReconStatement(
        opening_receivable=opening_receivable,
        gross_sales=Paise(gross_sales),
        settlements_received=Paise(settlements_received),
        explained_variance=Paise(explained_variance),
        exceptions_gross=Paise(exceptions_gross),
        closing_receivable=Paise(closing_receivable),
        exceptions_cash_at_risk=Paise(exceptions_cash),
    )


# Where each typed component lands in the ledger. The two that matter:
#
#   GST on MDR is its OWN account, not folded into MDR Expense, because it is
#   reclaimable as Input Tax Credit -- buried inside an expense the merchant
#   loses the claim. That is the business reason `tax` exists in the Sec 3.1
#   schema at all.
#
#   Rolling reserve is a RECEIVABLE, not an expense (BRIEF Sec 3.3: "a receivable
#   from the gateway, not settled cash"). Withholding debits the asset, releasing
#   credits it, and both post to the same account -- so the reserve ledger nets
#   itself out over the hold period instead of quietly becoming a cost.
COMPONENT_ACCOUNTS: dict[ComponentType, str] = {
    ComponentType.MDR: "MDR Expense",
    ComponentType.GST_ON_MDR: "GST Input Credit",
    ComponentType.REFUND_OFFSET: "Refunds",
    ComponentType.TRANSFER_OUT: "Vendor Payouts",
    ComponentType.CHARGEBACK_REVERSAL: "Chargeback Losses",
    ComponentType.CHARGEBACK_FEE: "Chargeback Fees",
    ComponentType.ROLLING_RESERVE: "Rolling Reserve Receivable",
    ComponentType.RESERVE_RELEASE: "Rolling Reserve Receivable",
    ComponentType.INSTANT_SETTLEMENT_FEE: "Settlement Fees",
}


def journal_entries(edges: list[ReconEdge], repo) -> list[JournalEntry]:
    """One balanced entry per fully explained settlement.

    Dr Bank / Dr <each typed component> / Cr Trade Receivable.

    It balances by construction rather than by arrangement: an edge is EXPLAINED
    only when `gross - cash - sum(components) == 0`, so debits (cash plus every
    component) equal the credit (gross) identically. Nothing is posted for a
    settlement that is not fully explained -- an accounting system that posts a
    half-understood entry is worse than one that posts none and raises an
    exception.
    """
    members_by_settlement = repo.lines_by_settlement()
    entries: list[JournalEntry] = []

    explained = sorted(
        (e for e in edges
         if e.kind is EdgeKind.BANK_TO_SETTLEMENT and e.status is EdgeStatus.EXPLAINED),
        key=lambda e: e.dst_uid)

    for edge in explained:
        cash = int(edge.decomposition.actual)
        gross = sum(m.amount for m in members_by_settlement.get(edge.dst_uid, [])
                    if m.is_settled_payment)

        # Net by account first: reserve withheld and reserve released share one
        # account and must not appear as two opposing lines on the same entry.
        netted: dict[str, int] = {}
        for component in edge.decomposition.components:
            account = COMPONENT_ACCOUNTS[component.kind]
            netted[account] = netted.get(account, 0) + int(component.amount)

        lines = [JournalLine("Bank", Paise(cash), Paise(0))]
        for account, amount in sorted(netted.items()):
            if amount == 0:
                continue
            lines.append(JournalLine(account, Paise(max(amount, 0)),
                                     Paise(max(-amount, 0))))
        lines.append(JournalLine("Trade Receivable", Paise(0), Paise(gross)))

        entries.append(JournalEntry(
            entry_id=f"je_{edge.dst_uid}",
            narrative=f"Settlement {edge.dst_uid} received via bank credit {edge.src_uid}",
            lines=tuple(lines),
        ))

    return entries


def write_journal(path: Path, entries: list[JournalEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.to_json(), sort_keys=True,
                                    separators=(",", ":")) + "\n")
