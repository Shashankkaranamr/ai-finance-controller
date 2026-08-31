"""Tier 0 -- deterministic join and identity checking. No rules table, no LLM.

The boundary between Tier 0 and Tier 1 is worth stating precisely, because it is
easy to blur and the ablation table depends on it:

  Tier 0 reads the fee and tax that the SOURCE DATA reports, and checks the
  identities of BRIEF Sec 3.2 (rollup, tie-out, fee inclusive of tax). It also
  joins on exact keys and reads flags and dates that are simply present.

  Tier 1 computes what the fee SHOULD have been from a contracted slab table and
  compares. That is where MDR_SLAB_MISMATCH becomes meaningful.

So Tier 0 can legitimately produce a typed decomposition of gross into cash +
MDR + GST, because every component is reported rather than inferred. What it
cannot do is tell you the gateway overcharged you, or that a debit it can see is
a rolling reserve rather than something else.

WHAT TIER 0 IS ACCOUNTABLE FOR
------------------------------
Exactly the classes marked `detectable_at == 0` in ExceptionType. That set is not
a wish list -- `test_tier0_covers_its_declared_remit` fails if this module leaves
one of them unimplemented. Anything above 0 is deliberately not attempted here,
and shows up in the metrics as out-of-remit rather than as a false clear.
"""
from __future__ import annotations

from ..audit.log import AuditLog
from ..domain.graph import (ComponentBasis, ComponentType, Decomposition, EdgeKind,
                            EdgeStatus, Evidence, ExceptionType, ReconEdge, Tier,
                            VarianceComponent)
from ..domain.identities import (RULE_VERSION, bank_tie_out_holds, expected_gst,
                                 gst_on_mdr_holds, rollup)
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
    _resolve_refunds(repo, edges, exceptions, audit)
    _check_line_flags(repo, exceptions, audit)
    _check_gst_identity(repo, exceptions, audit)
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
    """Only PAYMENT lines reach the books.

    A refund carries an `order_id` too, but the ERP view is sales-grain: there is
    no book entry for the refund itself, and joining one to the original sale
    would assert an identity that is not true -- the two amounts are supposed to
    differ. Emitting that edge would inflate the denominator with links that can
    never be explained, which is precisely the indefensible match rate Sec 7 warns
    about.
    """
    by_order: dict[str, list[str]] = {}

    for entity_id in sorted(repo.lines):
        line = repo.lines[entity_id]
        if line.type != "payment" or line.order_id is None:
            continue
        by_order.setdefault(line.order_id, []).append(entity_id)

        book = repo.books.get(line.order_id)
        if book is None:
            continue

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
            # Subject is the BOOK ENTRY, not the edge. The ERP is where the wrong
            # number was typed, and an exception has to be addressed to the record
            # an analyst would go and fix.
            exceptions.append(ExceptionRecord.build(
                ExceptionType.BOOK_AMOUNT_MISMATCH, SUBJECT_UNIT, book.order_id,
                Paise(abs(int(decomposition.residual))),
                hypothesis=(
                    f"Books show {format_inr(Paise(book.gross_amount))} for order "
                    f"{book.order_id}; the gateway reports {format_inr(Paise(line.amount))}. "
                    "The gateway is the cash-moving system, so the ERP entry is the "
                    "likely error."),
                evidence=edge.evidence))
            audit.record_edge("book_amount_mismatch", edge,
                              residual=int(decomposition.residual))

        # Period cutoff: the ERP booked the invoice in a different month from the
        # capture. Correct on both sides (Sec 3.4) -- notable, never a break.
        if (book.invoice_date.year, book.invoice_date.month) != \
                (line.created_at.year, line.created_at.month):
            exceptions.append(ExceptionRecord.build(
                ExceptionType.PERIOD_CUTOFF_TIMING, SUBJECT_UNIT, book.order_id,
                Paise(line.amount),
                hypothesis=(
                    f"Invoiced {book.invoice_date.isoformat()} but captured "
                    f"{line.created_at.isoformat()}. The order straddles the period "
                    "close; books and bank disagree correctly and this must not be "
                    "counted as a break."),
                confidence=100,
                evidence=(Evidence("period_straddle",
                                   f"invoice_date={book.invoice_date.isoformat()} "
                                   f"created_at={line.created_at.isoformat()}",
                                   (f"book_entry:{book.order_id}",)),)))

    # A 1:1 grain with two lines on one key is a cardinality violation, and the
    # join is what reveals it. Both lines are flagged: they are indistinguishable
    # from here, and an analyst needs to see the pair to decide which to void.
    for order_id, entity_ids in sorted(by_order.items()):
        if len(entity_ids) < 2:
            continue
        for entity_id in entity_ids:
            line = repo.lines[entity_id]
            exceptions.append(ExceptionRecord.build(
                ExceptionType.DUPLICATE_PAYMENT, SUBJECT_UNIT, entity_id,
                Paise(line.amount),
                hypothesis=(
                    f"Order {order_id} carries {len(entity_ids)} settled payment lines "
                    f"({', '.join(sorted(entity_ids))}). LINE_TO_BOOK is a 1:1 grain, so "
                    "one of these is a duplicate capture and the merchant has been "
                    "credited twice."),
                evidence=(Evidence("cardinality_violation",
                                   f"order_id {order_id} -> {len(entity_ids)} payment lines",
                                   tuple(f"line_item:{eid}" for eid in sorted(entity_ids))),)))
        audit.record("duplicate_payment", order=order_id, lines=sorted(entity_ids))


# --- refund <-> payment (1:1, may cross cycles) -------------------------------

def _resolve_refunds(repo, edges, exceptions, audit) -> None:
    """The REFUND_TO_PAYMENT grain, declared on hypothesis in Increment 0.

    This is its first exercise against real data, and it is an exact-key join on
    `payment_id` -- unambiguously Tier 0 work. Two outcomes are interesting:

      * the payment is in the extract, in an EARLIER settlement. That crossing is
        timing and not a break (Sec 3.4), and the binary edge expresses it fine.
      * the payment is not in the extract at all. No edge exists to create. This
        is the declared blind spot, and the exception is subjected on the refund
        line because that is the only record we have.
    """
    payments_by_payment_id = repo.payments_by_payment_id()

    for entity_id in sorted(repo.lines):
        line = repo.lines[entity_id]
        if line.type != "refund":
            continue

        target = payments_by_payment_id.get(line.payment_id) if line.payment_id else None
        if target is None:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.REFUND_ORPHANED, SUBJECT_UNIT, entity_id,
                Paise(line.amount),
                hypothesis=(
                    f"Refund {entity_id} references payment_id {line.payment_id}, which "
                    "does not appear anywhere in this extract. The original capture "
                    "predates the window, so there is nothing in the data to link it to. "
                    "This is a known blind spot, not a matching failure."),
                confidence=100,
                evidence=(Evidence("payment_lookup_exhausted",
                                   f"payment_id={line.payment_id} absent from "
                                   f"{len(payments_by_payment_id)} payment lines",
                                   (f"line_item:{entity_id}",)),)))
            audit.record("refund_orphaned", line=entity_id, payment_id=line.payment_id)
            continue

        crossed = target.settlement_id != line.settlement_id
        edges.append(ReconEdge(
            kind=EdgeKind.REFUND_TO_PAYMENT,
            src_uid=entity_id,
            dst_uid=target.entity_id,
            status=EdgeStatus.EXPLAINED,
            tier=Tier.T0_DETERMINISTIC,
            confidence=100,
            evidence=(
                Evidence("payment_id_exact",
                         f"refund {entity_id} carries payment_id {line.payment_id}, "
                         f"matched to line {target.entity_id}",
                         (f"line_item:{entity_id}", f"line_item:{target.entity_id}")),
                Evidence("cycle_relationship",
                         f"refund settles in {line.settlement_id}, payment settled in "
                         f"{target.settlement_id} "
                         f"[{'crosses cycles' if crossed else 'same cycle'}]",
                         (f"line_item:{entity_id}",)),
            ),
        ))

        if crossed:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.REFUND_CROSS_CYCLE, SUBJECT_UNIT, entity_id,
                Paise(line.amount),
                hypothesis=(
                    f"Refund debits settlement {line.settlement_id} while the payment it "
                    f"reverses settled in {target.settlement_id}. Sec 3.4 timing, fully "
                    "linked and fully explained -- reportable, not a break."),
                confidence=100,
                evidence=(Evidence("cross_cycle_refund",
                                   f"payment settled {target.settled_at.isoformat()}, "
                                   f"refund settled {line.settled_at.isoformat()}",
                                   (f"line_item:{entity_id}",
                                    f"line_item:{target.entity_id}")),)))


# --- flags and references that are simply present -----------------------------

def _check_line_flags(repo, exceptions, audit) -> None:
    """Conditions Tier 0 can read straight off the record."""
    for entity_id in sorted(repo.lines):
        line = repo.lines[entity_id]

        # Captured, reported, and never settled. The gateway is holding it
        # legitimately, so this is notable rather than a break.
        if line.on_hold:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.ON_HOLD_NOT_SETTLED, SUBJECT_UNIT, entity_id,
                Paise(line.amount),
                hypothesis=(
                    f"Line {entity_id} is flagged on_hold and settled=False, so its "
                    f"{format_inr(Paise(line.amount))} was captured but never paid out. "
                    "Books will show the sale and the bank will not show the cash, "
                    "correctly."),
                confidence=100,
                evidence=(Evidence("on_hold_flag",
                                   f"on_hold={line.on_hold} settled={line.settled}",
                                   (f"line_item:{entity_id}",)),)))

        # A dispute reversal that cannot reach the sale it reverses.
        if line.dispute_id is not None and line.order_id is None and line.credit == 0:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.CHARGEBACK_UNLINKED, SUBJECT_UNIT, entity_id,
                Paise(line.amount),
                hypothesis=(
                    f"Adjustment {entity_id} carries dispute_id {line.dispute_id} and "
                    f"debits {format_inr(Paise(line.amount))}, but no order_id, so it "
                    "cannot be tied back to the sale being reversed. The reversal is "
                    "real; the reference is missing."),
                evidence=(Evidence("missing_order_reference",
                                   f"dispute_id={line.dispute_id} order_id=None "
                                   f"payment_id={line.payment_id}",
                                   (f"line_item:{entity_id}",)),)))
            audit.record("chargeback_unlinked", line=entity_id, dispute=line.dispute_id)


def _check_gst_identity(repo, exceptions, audit) -> None:
    """tax == round_half_up((fee - tax) * 18%), per line.

    Checked over REPORTED values only, which is what keeps it inside Tier 0. The
    canonical rule is pinned in domain/identities.py; the brief's own transfer
    example violates it by one paise, and we treat deviation as this exception
    rather than bending the rule to fit the example (D-004).
    """
    for entity_id in sorted(repo.lines):
        line = repo.lines[entity_id]
        if line.fee == 0 and line.tax == 0:
            continue
        if gst_on_mdr_holds(Paise(line.fee), Paise(line.tax)):
            continue

        base = line.fee - line.tax
        # The shortfall against the canonical rule. A negative base is an
        # impossible shape (fee is inclusive of tax), so the whole reported tax
        # is at risk rather than a delta against a rate that cannot be applied.
        shortfall = (abs(line.tax - int(expected_gst(Paise(base)))) if base >= 0
                     else line.tax)
        exceptions.append(ExceptionRecord.build(
            ExceptionType.GST_ON_MDR_MISMATCH, SUBJECT_UNIT, entity_id,
            Paise(shortfall),
            hypothesis=(
                f"Line {entity_id} reports fee {format_inr(Paise(line.fee))} and tax "
                f"{format_inr(Paise(line.tax))}, so the MDR base is "
                f"{format_inr(Paise(base))}. 18% of that base is not the reported tax, "
                "so the GST breakout is inconsistent and the Input Tax Credit claimed "
                "against it would be wrong."),
            evidence=(Evidence("gst_on_mdr_rule",
                               f"fee={line.fee} tax={line.tax} mdr_base={base}",
                               (f"line_item:{entity_id}",)),)))
        audit.record("gst_on_mdr_mismatch", line=entity_id, fee=line.fee, tax=line.tax)


# --- bank credit <-> settlement (1:1, the headline grain) ---------------------

def _resolve_bank_credits(repo, members_by_settlement, settlement_by_utr,
                          edges, exceptions, audit) -> set[str]:
    matched: set[str] = set()

    # Extract first, then group: a UTR carried by two credits is an ambiguity Tier
    # 0 cannot break, and it has to be detected before either credit is linked.
    extracted: dict[str, str | None] = {}
    by_utr: dict[str, list[str]] = {}
    for bank_ref in sorted(repo.bank):
        # NOTE: we read `narration` only. `narration_family` is generator
        # provenance and reading it would leak the answer into the resolver.
        utr = parse_utr(repo.bank[bank_ref].narration)
        extracted[bank_ref] = utr
        if utr is not None:
            by_utr.setdefault(utr, []).append(bank_ref)

    duplicated = {utr for utr, refs in by_utr.items() if len(refs) > 1}

    for bank_ref in sorted(repo.bank):
        credit = repo.bank[bank_ref]
        utr = extracted[bank_ref]

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

        if utr in duplicated:
            # Both credits carry the same UTR. Linking either one would be a
            # coin flip presented as a fact, so Tier 0 links NEITHER and says
            # why. The settlement still counts as reached, so this does not also
            # surface as a missing bank credit.
            settlement = settlement_by_utr.get(utr)
            if settlement is not None:
                matched.add(settlement.id)
            exceptions.append(ExceptionRecord.build(
                ExceptionType.DUPLICATE_UTR, SUBJECT_UNIT, bank_ref,
                Paise(credit.amount),
                hypothesis=(
                    f"UTR {utr} appears on {len(by_utr[utr])} bank credits "
                    f"({', '.join(sorted(by_utr[utr]))}). A UTR identifies one transfer, "
                    "so the bank has double-posted or a second payer reused the "
                    "reference. Not linked: choosing one would be a guess."),
                evidence=(Evidence("utr_collision",
                                   f"utr {utr} -> {sorted(by_utr[utr])}",
                                   tuple(f"bank_credit:{r}" for r in sorted(by_utr[utr]))),)))
            audit.record("duplicate_utr", utr=utr, bank_credits=sorted(by_utr[utr]))
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

        # Expected gross counts SETTLED PAYMENT lines only. An on-hold line is
        # reported but has not moved, and a refund or adjustment is a deduction
        # rather than a sale -- including either would manufacture a residual.
        payments = [m for m in members if m.is_settled_payment]
        gross = Paise(sum(m.amount for m in payments))
        mdr = Paise(sum(m.fee - m.tax for m in payments))
        gst = Paise(sum(m.tax for m in payments))
        decomposition = Decomposition(
            expected=gross,
            actual=Paise(credit.amount),
            components=(
                # Both read off the reported `fee` and `tax` -- documented Sec 3.1
                # fields, so SCHEMA. Tier 0 has no second opinion to compare them
                # against; that is Tier 1's job.
                VarianceComponent(ComponentType.MDR, mdr, RULE_VERSION,
                                  ComponentBasis.SCHEMA),
                VarianceComponent(ComponentType.GST_ON_MDR, gst, RULE_VERSION,
                                  ComponentBasis.SCHEMA),
            ),
        )

        ties_out = bank_tie_out_holds(Paise(credit.amount), Paise(settlement.amount))
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
                    "between gross and cash is unaccounted for. Tier 0 can only type the "
                    "components the report states; a reserve, refund offset or dispute "
                    "debit needs the contracted rate card to name."),
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
