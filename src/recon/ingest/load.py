"""Ingest: validate at the boundary, quarantine bad rows, never abort the batch.

BRIEF Sec 8: a malformed source file must produce "a clear typed error; quarantine
bad rows rather than aborting". A reconciliation run that dies on row 400 of 2000
is worse than useless -- the controller learns nothing and has to wait for a fix.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..domain.graph import ReconUnit, UnitKind
from ..money import Paise
from .schemas import BankCreditRow, BookEntryRow, SettlementLineRow, SettlementRow

TModel = TypeVar("TModel", bound=BaseModel)

# The four source views, named once so a resolver can ask about a view by the
# same string the quarantine records against it.
BOOKS_VIEW = "books.jsonl"
LINES_VIEW = "settlement_lines.jsonl"
SETTLEMENTS_VIEW = "settlements.jsonl"
BANK_VIEW = "bank.jsonl"


@dataclass(frozen=True, slots=True)
class QuarantinedRow:
    source_file: str
    line_no: int
    error: str
    raw: str

    def to_json(self) -> dict:
        return {"source_file": self.source_file, "line_no": self.line_no,
                "error": self.error, "raw": self.raw}


@dataclass(slots=True)
class Repository:
    """Full typed records, keyed by (kind, uid).

    The graph carries identity only (PLAN.md, approved grain model); resolvers
    that need `method` / `card_network` / `dispute_id` come here for it.
    """

    books: dict[str, BookEntryRow] = field(default_factory=dict)
    lines: dict[str, SettlementLineRow] = field(default_factory=dict)
    settlements: dict[str, SettlementRow] = field(default_factory=dict)
    bank: dict[str, BankCreditRow] = field(default_factory=dict)
    quarantined: list[QuarantinedRow] = field(default_factory=list)

    # -- completeness ----------------------------------------------------------
    #
    # WHY A RESOLVER NEEDS TO ASK THIS
    # --------------------------------
    # Quarantine keeps the batch alive, which is right (Sec 8). But it leaves the
    # resolver reading a view that is silently short of rows, and every claim
    # made FROM THE ABSENCE of a row is then unsound. `extra="forbid"` means a
    # renamed column fails every row of a view identically, so the realistic
    # case is not "one bad row" -- it is the whole view gone, with the resolver
    # cheerfully concluding that nothing was ever there (F-018).

    def quarantined_by_file(self) -> dict[str, int]:
        """How many rows each source view lost. Empty dict on a clean run."""
        counts: dict[str, int] = {}
        for row in self.quarantined:
            counts[row.source_file] = counts.get(row.source_file, 0) + 1
        return counts

    def view_is_complete(self, source_file: str) -> bool:
        """Did this view load every row it contained?

        Deliberately strict: ONE quarantined row is enough to make an
        absence-based claim about that view unsafe, because the resolver cannot
        know whether the row it needed is the row it lost.
        """
        return not any(row.source_file == source_file for row in self.quarantined)

    # -- derived indexes, built once ------------------------------------------

    def lines_by_settlement(self) -> dict[str, list[SettlementLineRow]]:
        index: dict[str, list[SettlementLineRow]] = {}
        for line in self.lines.values():
            index.setdefault(line.settlement_id, []).append(line)
        for members in index.values():
            members.sort(key=lambda r: r.entity_id)   # deterministic ordering
        return index

    def settlement_by_utr(self) -> dict[str, SettlementRow]:
        return {s.utr.lower(): s for s in self.settlements.values()}

    def payments_by_payment_id(self) -> dict[str, SettlementLineRow]:
        """Index for the REFUND_TO_PAYMENT join.

        Payment lines only. A refund carries the payment_id of the capture it
        reverses, so indexing every line type here would let a refund match
        itself and turn the grain into a self-loop.
        """
        return {line.payment_id: line for line in self.lines.values()
                if line.type == "payment" and line.payment_id is not None}

    # -- graph units -----------------------------------------------------------

    def units(self) -> list[ReconUnit]:
        """Project every record into an identity-only graph unit."""
        out: list[ReconUnit] = []
        for b in self.books.values():
            out.append(ReconUnit(UnitKind.BOOK_ENTRY, b.order_id, Paise(b.gross_amount),
                                 b.invoice_date, "books"))
        for line in self.lines.values():
            out.append(ReconUnit(UnitKind.LINE_ITEM, line.entity_id, Paise(line.amount),
                                 line.settled_at, "settlement_report"))
        for s in self.settlements.values():
            out.append(ReconUnit(UnitKind.SETTLEMENT, s.id, Paise(s.amount),
                                 s.created_at, "settlement_report"))
        for credit in self.bank.values():
            out.append(ReconUnit(UnitKind.BANK_CREDIT, credit.bank_ref, Paise(credit.amount),
                                 credit.value_date, "bank_statement"))
        out.sort(key=lambda u: (u.kind.value, u.uid))
        return out

    @property
    def total_records(self) -> int:
        return len(self.books) + len(self.lines) + len(self.settlements) + len(self.bank)


def _load_jsonl(path: Path, model: type[TModel],
                quarantine: list[QuarantinedRow]) -> list[TModel]:
    rows: list[TModel] = []
    if not path.exists():
        raise FileNotFoundError(f"source view missing: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rows.append(model.model_validate(json.loads(raw)))
            except (json.JSONDecodeError, ValidationError) as exc:
                # Quarantine, do not raise. One bad row must not cost the batch.
                quarantine.append(QuarantinedRow(
                    source_file=path.name,
                    line_no=line_no,
                    error=f"{type(exc).__name__}: {exc}"[:400],
                    raw=raw[:200],
                ))
    return rows


def load_all(data_dir: Path) -> Repository:
    """Load the four views. Missing files are fatal; bad rows are quarantined."""
    repo = Repository()

    for row in _load_jsonl(data_dir / BOOKS_VIEW, BookEntryRow, repo.quarantined):
        repo.books[row.order_id] = row
    for row in _load_jsonl(data_dir / LINES_VIEW, SettlementLineRow,
                           repo.quarantined):
        repo.lines[row.entity_id] = row
    for row in _load_jsonl(data_dir / SETTLEMENTS_VIEW, SettlementRow, repo.quarantined):
        repo.settlements[row.id] = row
    for row in _load_jsonl(data_dir / BANK_VIEW, BankCreditRow, repo.quarantined):
        repo.bank[row.bank_ref] = row

    return repo
