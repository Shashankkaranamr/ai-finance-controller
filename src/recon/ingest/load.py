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

    for row in _load_jsonl(data_dir / "books.jsonl", BookEntryRow, repo.quarantined):
        repo.books[row.order_id] = row
    for row in _load_jsonl(data_dir / "settlement_lines.jsonl", SettlementLineRow,
                           repo.quarantined):
        repo.lines[row.entity_id] = row
    for row in _load_jsonl(data_dir / "settlements.jsonl", SettlementRow, repo.quarantined):
        repo.settlements[row.id] = row
    for row in _load_jsonl(data_dir / "bank.jsonl", BankCreditRow, repo.quarantined):
        repo.bank[row.bank_ref] = row

    return repo
