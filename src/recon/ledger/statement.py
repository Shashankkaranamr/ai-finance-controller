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
            f"| {'- Explained variance (MDR + GST)':<44} | resolver | "
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
            "was raised at. The difference is the MDR and GST on the unsettled cycle.",
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
    explained_variance = sum(
        int(c.amount)
        for e in explained_bank
        for c in e.decomposition.components
        if c.kind in (ComponentType.MDR, ComponentType.GST_ON_MDR))

    relieved_gross = sum(
        sum(m.amount for m in members_by_settlement.get(sid, []))
        for sid in sorted(explained_ids))

    unexplained_ids = sorted(set(repo.settlements) - explained_ids)
    exceptions_gross = sum(
        sum(m.amount for m in members_by_settlement.get(sid, []))
        for sid in unexplained_ids)
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


def journal_entries(edges: list[ReconEdge], repo) -> list[JournalEntry]:
    """One balanced entry per fully explained settlement.

    Dr Bank / Dr MDR Expense / Dr GST Input Credit / Cr Trade Receivable.

    GST on MDR is its own line because it is reclaimable as Input Tax Credit --
    buried inside MDR expense the merchant loses the claim. That is the business
    reason the `tax` field exists in the settlement schema at all.
    """
    members_by_settlement = repo.lines_by_settlement()
    entries: list[JournalEntry] = []

    explained = sorted(
        (e for e in edges
         if e.kind is EdgeKind.BANK_TO_SETTLEMENT and e.status is EdgeStatus.EXPLAINED),
        key=lambda e: e.dst_uid)

    for edge in explained:
        components = {c.kind: int(c.amount) for c in edge.decomposition.components}
        cash = int(edge.decomposition.actual)
        mdr = components.get(ComponentType.MDR, 0)
        gst = components.get(ComponentType.GST_ON_MDR, 0)
        gross = sum(m.amount for m in members_by_settlement.get(edge.dst_uid, []))

        entries.append(JournalEntry(
            entry_id=f"je_{edge.dst_uid}",
            narrative=f"Settlement {edge.dst_uid} received via bank credit {edge.src_uid}",
            lines=(
                JournalLine("Bank", Paise(cash), Paise(0)),
                JournalLine("MDR Expense", Paise(mdr), Paise(0)),
                JournalLine("GST Input Credit", Paise(gst), Paise(0)),
                JournalLine("Trade Receivable", Paise(0), Paise(gross)),
            ),
        ))

    return entries


def write_journal(path: Path, entries: list[JournalEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.to_json(), sort_keys=True,
                                    separators=(",", ":")) + "\n")
