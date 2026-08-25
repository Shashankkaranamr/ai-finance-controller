"""Tier 0 -- deterministic join and identity checking. No rules table, no LLM.

The boundary between Tier 0 and Tier 1 is worth stating precisely, because it is
easy to blur and the ablation table depends on it:

  Tier 0 reads the fee and tax that the SOURCE DATA reports, and checks the
  identities of BRIEF Sec 3.2 (rollup, tie-out, fee inclusive of tax).

  Tier 1 computes what the fee SHOULD have been from a contracted slab table and
  compares. That is where MDR_SLAB_MISMATCH becomes meaningful.

So Tier 0 can legitimately produce a fully typed decomposition of gross into
cash + MDR + GST, because every component is reported rather than inferred. What
it cannot do is tell you the gateway overcharged you.
"""
from __future__ import annotations

from ..audit.log import AuditLog
from ..domain.graph import (ComponentType, Decomposition, EdgeKind, EdgeStatus, Evidence,
                            ExceptionType, ReconEdge, Tier, VarianceComponent)
from ..domain.identities import RULE_VERSION, gst_on_mdr_holds, rollup, bank_tie_out_holds
from ..generate.narration import parse_utr
from ..ingest.load import Repository
from ..money import Paise, format_inr
from ..report.exceptions import SUBJECT_EDGE, SUBJECT_UNIT, ExceptionRecord


def resolve(repo: Repository, audit: AuditLog) -> tuple[list[ReconEdge], list[ExceptionRecord]]:
    edges: list[ReconEdge] = []
    exceptions: list[ExceptionRecord] = []

    members_by_settlement = repo.lines_by_settlement()
    settlement_by_utr = repo.settlement_by_utr()

    _resolve_settlement_lines(repo, members_by_settlement, edges, exceptions, audit)
    _resolve_line_to_book(repo, edges, exceptions, audit)
    matched_settlements = _resolve_bank_credits(
        repo, members_by_settlement, settlement_by_utr, edges, exceptions, audit)
    _flag_missing_bank_credits(repo, matched_settlements, exceptions, audit)

    edges.sort(key=lambda e: e.sort_key())
    return edges, exceptions


# --- settlement <-> line items (1:N, membership + set-level rollup) -----------

def _resolve_settlement_lines(repo, members_by_settlement, edges, exceptions, audit) -> None:
    for settlement_id in sorted(repo.settlements):
        settlement = repo.settlements[settlement_id]
        members = members_by_settlement.get(settlement_id, [])

        computed = rollup([Paise(m.credit) for m in members],
                          [Paise(m.debit) for m in members])
        holds = int(computed) == int(settlement.amount)

        # The identity is a property of the SET, so it decides the status of every
        # edge in the set -- which is exactly why it lives here and not on an edge.
        status = EdgeStatus.EXPLAINED if holds else EdgeStatus.MATCHED
        for member in members:
            edges.append(ReconEdge(
                kind=EdgeKind.SETTLEMENT_TO_LINE,
                src_uid=settlement_id,
                dst_uid=member.entity_id,
                status=status,
                tier=Tier.T0_DETERMINISTIC,
                confidence=100,
                evidence=(
                    Evidence("settlement_id_exact",
                             f"line {member.entity_id} carries settlement_id {settlement_id}",
                             (f"line_item:{member.entity_id}", f"settlement:{settlement_id}")),
                    Evidence("rollup_identity",
                             f"sum(credit) - sum(debit) = {int(computed)} vs "
                             f"settlement.amount = {int(settlement.amount)}"
                             f" [{'holds' if holds else 'MISMATCH'}]",
                             (f"settlement:{settlement_id}",)),
                ),
            ))

        if not holds:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.ROLLUP_MISMATCH, SUBJECT_UNIT, settlement_id,
                Paise(abs(int(settlement.amount) - int(computed))),
                hypothesis=(
                    f"Settlement reports {format_inr(Paise(settlement.amount))} but its "
                    f"{len(members)} line items sum to {format_inr(computed)}. "
                    "Either a line item is missing from the report or the total is stale."),
                evidence=(Evidence("rollup_identity",
                                   f"expected {int(settlement.amount)}, computed {int(computed)}",
                                   (f"settlement:{settlement_id}",)),)))
            audit.record("rollup_mismatch", settlement=settlement_id,
                         reported=int(settlement.amount), computed=int(computed))
        else:
            audit.record("rollup_verified", settlement=settlement_id,
                         amount=int(settlement.amount), line_items=len(members))


# --- line item <-> book entry (1:1) -------------------------------------------

def _resolve_line_to_book(repo, edges, exceptions, audit) -> None:
    for entity_id in sorted(repo.lines):
        line = repo.lines[entity_id]
        book = repo.books.get(line.order_id)
        if book is None:
            continue   # Inc 0 generates none of these; Inc 1's anomalies will.

        decomposition = Decomposition(
            expected=Paise(book.gross_amount),
            actual=Paise(line.amount),
            components=(),          # ERP and gateway should agree exactly on gross
        )
        agrees = decomposition.is_fully_explained

        edge = ReconEdge(
            kind=EdgeKind.LINE_TO_BOOK,
            src_uid=entity_id,
            dst_uid=book.order_id,
            status=EdgeStatus.EXPLAINED if agrees else EdgeStatus.MATCHED,
            tier=Tier.T0_DETERMINISTIC,
            confidence=100,
            evidence=(Evidence("order_id_exact",
                               f"line {entity_id} carries order_id {book.order_id}",
                               (f"line_item:{entity_id}", f"book_entry:{book.order_id}")),),
            decomposition=decomposition,
        )
        edges.append(edge)

        if not agrees:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.BOOK_AMOUNT_MISMATCH, SUBJECT_EDGE, edge.ref,
                Paise(abs(int(decomposition.residual))),
                hypothesis=(
                    f"Books show {format_inr(Paise(book.gross_amount))} for order "
                    f"{book.order_id}; the gateway reports {format_inr(Paise(line.amount))}."),
                evidence=edge.evidence))
            audit.record_edge("book_amount_mismatch", edge,
                              residual=int(decomposition.residual))


# --- bank credit <-> settlement (1:1, the headline grain) ---------------------

def _resolve_bank_credits(repo, members_by_settlement, settlement_by_utr,
                          edges, exceptions, audit) -> set[str]:
    matched: set[str] = set()

    for bank_ref in sorted(repo.bank):
        credit = repo.bank[bank_ref]

        # NOTE: we read `narration` only. `narration_family` is generator
        # provenance and reading it would leak the answer into the resolver.
        utr = parse_utr(credit.narration)
        if utr is None:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.NARRATION_UNPARSEABLE, SUBJECT_UNIT, bank_ref,
                Paise(credit.amount),
                hypothesis=("No UTR-shaped token found in the narration. "
                            "Narration shape is outside the known template families."),
                confidence=100,
                evidence=(Evidence("narration_raw", credit.narration,
                                   (f"bank_credit:{bank_ref}",)),)))
            audit.record("narration_unparseable", bank_credit=bank_ref)
            continue

        settlement = settlement_by_utr.get(utr)
        if settlement is None:
            # The extracted UTR is only ever a candidate; it is verified by exact
            # lookup, so a bad extraction cannot survive into a match.
            exceptions.append(ExceptionRecord.build(
                ExceptionType.UNMATCHED_BANK_CREDIT, SUBJECT_UNIT, bank_ref,
                Paise(credit.amount),
                hypothesis=(f"Extracted UTR {utr} matches no known settlement. "
                            "Likely a non-gateway receipt or another aggregator."),
                evidence=(Evidence("utr_extracted", f"utr={utr} from narration",
                                   (f"bank_credit:{bank_ref}",)),)))
            audit.record("unmatched_bank_credit", bank_credit=bank_ref, utr=utr)
            continue

        matched.add(settlement.id)
        members = members_by_settlement.get(settlement.id, [])

        gross = Paise(sum(m.amount for m in members))
        mdr = Paise(sum(m.fee - m.tax for m in members))
        gst = Paise(sum(m.tax for m in members))
        decomposition = Decomposition(
            expected=gross,
            actual=Paise(credit.amount),
            components=(
                VarianceComponent(ComponentType.MDR, mdr, RULE_VERSION),
                VarianceComponent(ComponentType.GST_ON_MDR, gst, RULE_VERSION),
            ),
        )

        ties_out = bank_tie_out_holds(Paise(credit.amount), Paise(settlement.amount))
        gst_ok = all(gst_on_mdr_holds(Paise(m.fee), Paise(m.tax)) for m in members)
        explained = decomposition.is_fully_explained and ties_out

        evidence = (
            Evidence("utr_exact_match",
                     f"utr {utr} extracted from narration and matched to {settlement.id}",
                     (f"bank_credit:{bank_ref}", f"settlement:{settlement.id}")),
            Evidence("bank_tie_out",
                     f"bank credit {int(credit.amount)} vs settlement.amount "
                     f"{int(settlement.amount)} [{'exact' if ties_out else 'DIFFERS'}]",
                     (f"bank_credit:{bank_ref}", f"settlement:{settlement.id}")),
            Evidence("variance_decomposition",
                     f"gross {int(gross)} - cash {int(credit.amount)} = "
                     f"MDR {int(mdr)} + GST {int(gst)}; residual "
                     f"{int(decomposition.residual)}",
                     (f"settlement:{settlement.id}",)),
            Evidence("gst_on_mdr_rule",
                     f"tax == round_half_up((fee - tax) * 18%) for all {len(members)} "
                     f"lines [{'holds' if gst_ok else 'VIOLATED'}]",
                     (f"settlement:{settlement.id}",)),
        )

        edge = ReconEdge(
            kind=EdgeKind.BANK_TO_SETTLEMENT,
            src_uid=bank_ref,
            dst_uid=settlement.id,
            status=EdgeStatus.EXPLAINED if explained else EdgeStatus.MATCHED,
            tier=Tier.T0_DETERMINISTIC,
            confidence=100 if explained else 60,
            evidence=evidence,
            decomposition=decomposition,
        )
        edges.append(edge)
        audit.record_edge("bank_to_settlement_resolved", edge,
                          residual=int(decomposition.residual),
                          gross=int(gross), cash=int(credit.amount))

        if not explained:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.AMOUNT_VARIANCE_UNEXPLAINED, SUBJECT_EDGE, edge.ref,
                Paise(abs(int(decomposition.residual))),
                hypothesis=(
                    f"After subtracting MDR {format_inr(mdr)} and GST {format_inr(gst)}, "
                    f"{format_inr(Paise(abs(int(decomposition.residual))))} of the gap "
                    "between gross and cash is unaccounted for."),
                confidence=70,
                evidence=edge.evidence))

    return matched


# --- settlements with no bank credit at all ----------------------------------

def _flag_missing_bank_credits(repo, matched_settlements, exceptions, audit) -> None:
    """The absence of an edge, not a bad edge -- see report/exceptions.py."""
    for settlement_id in sorted(repo.settlements):
        if settlement_id in matched_settlements:
            continue
        settlement = repo.settlements[settlement_id]
        exceptions.append(ExceptionRecord.build(
            ExceptionType.MISSING_BANK_CREDIT, SUBJECT_UNIT, settlement_id,
            Paise(settlement.amount),
            hypothesis=(
                f"Settlement {settlement_id} (UTR {settlement.utr}) was processed on "
                f"{settlement.created_at.isoformat()} for "
                f"{format_inr(Paise(settlement.amount))}, but no bank credit carrying "
                "that UTR appears in the statement."),
            evidence=(
                Evidence("settlement_processed",
                         f"status={settlement.status}, utr={settlement.utr}, "
                         f"amount={int(settlement.amount)}",
                         (f"settlement:{settlement_id}",)),
                Evidence("bank_search_exhausted",
                         f"no narration among {len(repo.bank)} bank credits yielded "
                         f"utr {settlement.utr}",
                         (f"settlement:{settlement_id}",)),
            )))
        audit.record("missing_bank_credit", settlement=settlement_id,
                     utr=settlement.utr, amount=int(settlement.amount))
