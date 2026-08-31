"""Tier 1 -- arithmetic variance decomposition against the contracted rate card.

Tier 0 checks the identities that hold between the numbers the report *states*.
Tier 1 is the first tier with a second, independent opinion: `domain/rates.py`.
That is the whole boundary, and it gives Tier 1 two jobs that are easy to conflate:

  (a) CLOSE THE RESIDUAL. Type the components Tier 0 cannot -- refund offsets,
      transfers, chargeback reversals and fees, rolling reserve, reserve release,
      instant settlement fee -- until `expected - actual - sum(components) == 0`.

  (b) DETECT OFF-CONTRACT FEES. Compare the fee actually charged against the slab
      for that method/network/card type.

(b) does NOT move the residual, and that is worth stating because it looks like it
should. Tier 0 builds its MDR component from the fee actually charged, so an
overcharge produces a decomposition that is wrong but internally consistent and
still sums to zero. `MDR_SLAB_MISMATCH` is recoverable money, not unexplained
money. It is the only reason a fully explained settlement can still carry a break.

WHAT THIS MODULE MAY NOT READ
-----------------------------
`description` and `notes`. Both are free text WE wrote, so typing an adjustment
off "Rolling reserve withheld" would be circular (D-015 one tier up) and would be
the fuzzy string matching BRIEF Sec 9 names as the single thing most likely to
sink this submission. `test_tier1_never_reads_narrative_fields` enforces it by
scanning this module's source.

So a rolling reserve is identified the only honest way available: it is the
adjustment debit equal to `round_half_up(settled credits x 500bps)`. Exactly
equal -- no tolerance. A tolerance would turn an arithmetic proof into a score,
which is the same anti-pattern wearing a different hat. Getting that exact match
to hold required fixing a real generator bug (F-010), which is the kind of thing
this constraint is *for*.

EVERY COMPONENT RECORDS ITS BASIS
---------------------------------
`ComponentBasis.SCHEMA` for anything read off a documented Sec 3.1 field the
gateway itself asserts; `CONTRACT` for anything derived from a rate-card constant
we also generated with. The metrics publish the split, so the honest limit of the
eval result is a number rather than a caveat in prose.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..audit.log import AuditLog
from ..domain.graph import (ComponentBasis, ComponentType, Decomposition, EdgeKind,
                            EdgeStatus, Evidence, ExceptionType, ReconEdge, Tier,
                            VarianceComponent)
from ..domain.rates import (CHARGEBACK_FEE_PAISE, INSTANT_SETTLEMENT_FEE_BPS,
                            RESERVE_HOLD_DAYS, ROLLING_RESERVE_BPS, RULE_VERSION,
                            mdr_rate_bps)
from ..ingest.load import Repository
from ..money import Paise, apply_rate_bps, format_inr
from ..report.exceptions import SUBJECT_EDGE, SUBJECT_UNIT, ExceptionRecord

INSTANT_SETTLEMENT_PREFIX = "setlod_"


def resolve(repo: Repository, edges: list[ReconEdge],
            audit: AuditLog) -> tuple[list[ReconEdge], list[ExceptionRecord]]:
    """Upgrade Tier 0's MATCHED bank edges by typing what remains.

    Returns the full edge list with bank edges replaced, plus new exceptions.
    Tier 0's edges are not mutated: `resolved_at` returns a new edge and the audit
    log carries the transition, so the graph never holds two versions of a truth.
    """
    members_by_settlement = repo.lines_by_settlement()
    exceptions: list[ExceptionRecord] = []

    # Pass 1: identify every rolling reserve, so pass 2 can tie releases back to
    # the cycle they came from. A release is only meaningful relative to a
    # withholding, so this genuinely needs two passes over the settlements.
    withheld = _identify_reserves(repo, members_by_settlement, exceptions, audit)

    out: list[ReconEdge] = []
    for edge in edges:
        if edge.kind is not EdgeKind.BANK_TO_SETTLEMENT or edge.status is not EdgeStatus.MATCHED:
            out.append(edge)
            continue
        out.append(_decompose(repo, edge, members_by_settlement.get(edge.dst_uid, []),
                              withheld, exceptions, audit))

    _check_contracted_fees(repo, exceptions, audit)

    out.sort(key=lambda e: e.sort_key())
    return out, exceptions


# --- rolling reserve ----------------------------------------------------------

def _expected_reserve(members) -> Paise:
    """5% of what the gateway actually credited on settled payment lines.

    "Actually credited" matters: the reserve is a percentage of the net after the
    fee, so it must be computed from the credits as reported, including any fee
    charged off-contract. F-010 was this the wrong way round.
    """
    base = Paise(sum(m.credit for m in members if m.is_settled_payment))
    return apply_rate_bps(base, ROLLING_RESERVE_BPS)


def _is_plain_debit_adjustment(line) -> bool:
    return (line.type == "adjustment" and line.dispute_id is None
            and line.debit > 0 and line.credit == 0)


def _identify_reserves(repo, members_by_settlement, exceptions, audit) -> dict:
    """Locate the reserve line on every settlement, arithmetically.

    Returns {settlement_id: (value_date, amount)} for the release matcher.
    """
    found: dict[str, tuple[date, int]] = {}

    for settlement_id in sorted(repo.settlements):
        members = members_by_settlement.get(settlement_id, [])
        expected = _expected_reserve(members)
        if int(expected) == 0:
            continue

        match = next((m for m in members
                      if _is_plain_debit_adjustment(m) and m.debit == int(expected)), None)
        if match is None:
            continue

        settlement = repo.settlements[settlement_id]
        found[settlement_id] = (settlement.created_at, int(expected))
        exceptions.append(ExceptionRecord.build(
            ExceptionType.RESERVE_WITHHELD, SUBJECT_UNIT, match.entity_id,
            Paise(match.debit),
            hypothesis=(
                f"{format_inr(Paise(match.debit))} withheld as rolling reserve on "
                f"{settlement_id} — exactly {ROLLING_RESERVE_BPS} bps of the "
                f"{format_inr(Paise(sum(m.credit for m in members if m.is_settled_payment)))} "
                "credited. This is a receivable from the gateway, not lost money, and it "
                f"is due back after {RESERVE_HOLD_DAYS} days."),
            confidence=100,
            evidence=(Evidence("reserve_rate_identity",
                               f"debit {match.debit} == round_half_up(credits x "
                               f"{ROLLING_RESERVE_BPS}bps) = {int(expected)}",
                               (f"line_item:{match.entity_id}",
                                f"settlement:{settlement_id}")),)))
        audit.record("reserve_identified", settlement=settlement_id,
                     line=match.entity_id, amount=int(expected))
    return found


def _match_release(line, settlement, withheld: dict) -> str | None:
    """Tie a reserve release back to the cycle it was withheld from.

    Matched on amount AND a matured hold, never on `notes` — which carries the
    answer in plain text and is therefore exactly what we may not look at. The
    reference does appear in the exception's evidence, for a human to verify;
    it just does not participate in the decision.
    """
    for origin_id, (origin_date, amount) in sorted(withheld.items()):
        if amount != line.credit:
            continue
        if (settlement.created_at - origin_date).days >= RESERVE_HOLD_DAYS:
            return origin_id
    return None


# --- the decomposition --------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TypedComponents:
    """The typed split of one settlement's gross-to-net gap, plus the lines that
    produced it so the caller can build evidence without re-deriving anything."""

    components: tuple[VarianceComponent, ...]
    reserve_line: object | None
    instant_line: object | None
    releases: tuple[tuple[object, str | None], ...]   # (line, originating settlement)


def type_components(settlement, members, withheld: dict) -> TypedComponents:
    """Type every deduction on a settlement from the report and the rate card.

    Deliberately takes no bank credit and no ground truth. That is what lets the
    same code answer two different questions: "does this bank credit reconcile?"
    (via `_decompose`) and "can the gross-to-net gap be typed at all, with no
    linkage involved?" (via `closure_report`). One implementation, so the rules
    cannot drift between the headline and the diagnostic.
    """
    out: list[VarianceComponent] = []

    def add(kind: ComponentType, amount: int, basis: ComponentBasis) -> None:
        if amount:
            out.append(VarianceComponent(kind, Paise(amount), RULE_VERSION, basis))

    # --- schema-derived: the gateway's own `type` and `dispute_id` fields ------
    add(ComponentType.REFUND_OFFSET,
        sum(m.debit for m in members if m.type == "refund"), ComponentBasis.SCHEMA)
    add(ComponentType.TRANSFER_OUT,
        sum(m.debit for m in members if m.type == "transfer"), ComponentBasis.SCHEMA)

    disputed = [m for m in members if m.type == "adjustment" and m.dispute_id is not None]
    # `dispute_id` says both lines belong to a dispute (schema); only the rate
    # card separates the flat per-dispute fee from the reversal (contract).
    add(ComponentType.CHARGEBACK_FEE,
        sum(m.debit for m in disputed if m.amount == CHARGEBACK_FEE_PAISE),
        ComponentBasis.CONTRACT)
    add(ComponentType.CHARGEBACK_REVERSAL,
        sum(m.debit for m in disputed if m.amount != CHARGEBACK_FEE_PAISE),
        ComponentBasis.SCHEMA)

    # --- contract-derived: identified by arithmetic against the rate card -----
    expected_reserve = _expected_reserve(members)
    reserve_line = next((m for m in members if _is_plain_debit_adjustment(m)
                         and m.debit == int(expected_reserve)), None)
    if reserve_line is not None:
        add(ComponentType.ROLLING_RESERVE, reserve_line.debit, ComponentBasis.CONTRACT)

    instant_line = None
    if settlement.id.startswith(INSTANT_SETTLEMENT_PREFIX):
        # The fee is charged on the pre-fee net, which is `amount + fee`.
        instant_line = next(
            (m for m in members
             if _is_plain_debit_adjustment(m) and m is not reserve_line
             and m.debit == int(apply_rate_bps(Paise(settlement.amount + m.debit),
                                               INSTANT_SETTLEMENT_FEE_BPS))), None)
        if instant_line is not None:
            add(ComponentType.INSTANT_SETTLEMENT_FEE, instant_line.debit,
                ComponentBasis.CONTRACT)

    releases: list[tuple[object, str | None]] = []
    for line in members:
        if line.type != "adjustment" or line.credit == 0 or line.dispute_id is not None:
            continue
        # Money coming back is carried negative -- the one signed component, so the
        # residual is always expected - actual - sum(components) with no branching.
        add(ComponentType.RESERVE_RELEASE, -line.credit, ComponentBasis.CONTRACT)
        releases.append((line, _match_release(line, settlement, withheld)))

    return TypedComponents(tuple(out), reserve_line, instant_line, tuple(releases))


def _decompose(repo, edge: ReconEdge, members, withheld, exceptions, audit) -> ReconEdge:
    settlement = repo.settlements[edge.dst_uid]
    typed = type_components(settlement, members, withheld)
    components = list(edge.decomposition.components) + list(typed.components)
    evidence = list(edge.evidence)

    if typed.reserve_line is not None:
        evidence.append(Evidence(
            "rolling_reserve",
            f"adjustment {typed.reserve_line.entity_id} debits "
            f"{typed.reserve_line.debit}, exactly {ROLLING_RESERVE_BPS} bps of settled credits",
            (f"line_item:{typed.reserve_line.entity_id}",)))
    if typed.instant_line is not None:
        evidence.append(Evidence(
            "instant_settlement_fee",
            f"on-demand settlement {settlement.id}: {typed.instant_line.debit} is "
            f"{INSTANT_SETTLEMENT_FEE_BPS} bps of the pre-fee net",
            (f"line_item:{typed.instant_line.entity_id}",)))

    for line, origin in typed.releases:
        if origin is None:
            exceptions.append(ExceptionRecord.build(
                ExceptionType.RESERVE_RELEASE_UNMATCHED, SUBJECT_UNIT, line.entity_id,
                Paise(line.credit),
                hypothesis=(
                    f"{format_inr(Paise(line.credit))} credited back as a reserve release, "
                    "but no withheld reserve of that amount has matured into this cycle. "
                    "The credit is real; the cycle it came from cannot be established from "
                    "this extract."),
                evidence=(Evidence("release_unmatched",
                                   f"credit {line.credit}, no matured withholding of that "
                                   f"amount among {len(withheld)} identified reserves",
                                   (f"line_item:{line.entity_id}",)),
                          # `notes` is shown to a HUMAN as corroboration; it took no
                          # part in the decision above (D-017).
                          Evidence("gateway_reference_unverified", line.notes or "(none)",
                                   (f"line_item:{line.entity_id}",)))))
            audit.record("reserve_release_unmatched", line=line.entity_id,
                         amount=line.credit)
        else:
            evidence.append(Evidence(
                "reserve_release_matched",
                f"{line.credit} credited back, matching the reserve withheld on {origin} "
                f"and matured after {RESERVE_HOLD_DAYS} days",
                (f"line_item:{line.entity_id}", f"settlement:{origin}")))

    decomposition = Decomposition(
        expected=edge.decomposition.expected,
        actual=edge.decomposition.actual,
        components=tuple(components),
    )
    explained = decomposition.is_fully_explained

    evidence.append(Evidence(
        "tier1_decomposition",
        f"{len(components)} typed components; residual "
        f"{int(decomposition.residual)} [{'closed' if explained else 'OPEN'}]",
        (f"settlement:{settlement.id}",)))

    upgraded = edge.resolved_at(
        Tier.T1_ARITHMETIC,
        EdgeStatus.EXPLAINED if explained else EdgeStatus.MATCHED,
        confidence=100 if explained else 60,
        evidence=tuple(evidence),
        decomposition=decomposition,
    )
    audit.record_edge("tier1_decomposed", upgraded,
                      residual=int(decomposition.residual), components=len(components))

    if not explained:
        exceptions.append(ExceptionRecord.build(
            ExceptionType.AMOUNT_VARIANCE_UNEXPLAINED, SUBJECT_EDGE, upgraded.ref,
            Paise(abs(int(decomposition.residual))),
            hypothesis=(
                f"{format_inr(Paise(abs(int(decomposition.residual))))} survives the full "
                "deduction decomposition. Every contracted component has been applied, so "
                "this is not a fee, a reserve or a refund we failed to type."),
            confidence=70,
            evidence=tuple(evidence)))

    return upgraded


# --- the decomposition, isolated from linkage ---------------------------------

def closure_report(repo) -> tuple[int, int, dict[str, int]]:
    """Can Tier 1 type the gross-to-net gap, with no bank statement involved?

    WHY THIS EXISTS. On the held-out seed the narration parser finds no UTR, so
    no bank edge is ever created and Tier 1 never runs. Explanation rate on eval
    is therefore 0% for a reason that has nothing to do with the arithmetic --
    which means the headline cannot tell us whether Tier 1's rules hold on data
    they were not tuned against. That question is the whole point of the
    Increment 2 circularity gate, so it needs a measurement that linkage cannot
    mask.

    So: for every settlement, compare `sum(settled payment amounts)` against the
    settlement's own reported `amount`, and ask whether the typed components close
    that gap exactly.

    This uses NO ground truth and NO bank statement. Its two sides come from two
    independently derived views -- line items from the recon report, `amount` from
    the settlement entity (D-003) -- so it is a real cross-check rather than a
    restatement. What it deliberately does NOT prove is generalisation to a
    merchant on a different contract; see the basis split it returns.

    Returns (closed, total, money explained by ComponentBasis).
    """
    members_by_settlement = repo.lines_by_settlement()
    withheld = {sid: (repo.settlements[sid].created_at, int(_expected_reserve(ms)))
                for sid, ms in members_by_settlement.items()
                if int(_expected_reserve(ms)) > 0
                and any(_is_plain_debit_adjustment(m) and m.debit == int(_expected_reserve(ms))
                        for m in ms)}

    closed = 0
    by_basis: dict[str, int] = {}
    settlement_ids = sorted(repo.settlements)
    for settlement_id in settlement_ids:
        settlement = repo.settlements[settlement_id]
        members = members_by_settlement.get(settlement_id, [])
        typed = type_components(settlement, members, withheld)

        gross = sum(m.amount for m in members if m.is_settled_payment)
        reported_fees = sum(m.fee for m in members if m.is_settled_payment)
        gap = gross - int(settlement.amount) - reported_fees
        if gap - sum(int(c.amount) for c in typed.components) == 0:
            closed += 1
        for component in typed.components:
            by_basis[component.basis.value] = (
                by_basis.get(component.basis.value, 0) + abs(int(component.amount)))

    return closed, len(settlement_ids), by_basis


# --- (b) the contracted fee check ---------------------------------------------

def _check_contracted_fees(repo, exceptions, audit) -> None:
    """Reported fee vs the slab for that instrument.

    This is the first check in the system that needs a second opinion rather than
    an internal identity, and it is the reason `domain/rates.py` exists. Note it
    does not affect any residual: Tier 0 built its MDR component from the fee
    actually charged, so an overcharge is self-consistent and still sums to zero.
    The money is recoverable from the gateway, which is why the exception exists.
    """
    for entity_id in sorted(repo.lines):
        line = repo.lines[entity_id]
        if not line.is_settled_payment or line.method is None:
            continue

        try:
            rate = mdr_rate_bps(line.method, line.card_network, line.card_type)
        except KeyError:
            continue    # an unpriced instrument is a rate-card gap, not an overcharge

        base = apply_rate_bps(Paise(line.amount), rate)
        expected_fee = int(base) + int(apply_rate_bps(base, 1800))
        if line.fee == expected_fee:
            continue

        overcharge = line.fee - expected_fee
        exceptions.append(ExceptionRecord.build(
            ExceptionType.MDR_SLAB_MISMATCH, SUBJECT_UNIT, entity_id,
            Paise(abs(overcharge)),
            hypothesis=(
                f"Line {entity_id} was charged {format_inr(Paise(line.fee))} on "
                f"{format_inr(Paise(line.amount))} via {line.method}"
                f"{'/' + line.card_network if line.card_network else ''}"
                f"{'/' + line.card_type if line.card_type else ''}. The contracted slab is "
                f"{rate} bps, which gives {format_inr(Paise(expected_fee))} inclusive of GST "
                f"— a difference of {format_inr(Paise(abs(overcharge)))} "
                f"{'over' if overcharge > 0 else 'under'}-charged."),
            evidence=(Evidence("contracted_slab",
                               f"method={line.method} network={line.card_network} "
                               f"type={line.card_type} -> {rate} bps; expected fee "
                               f"{expected_fee}, reported {line.fee}",
                               (f"line_item:{entity_id}",)),)))
        audit.record("mdr_slab_mismatch", line=entity_id, reported=line.fee,
                     expected=expected_fee, rate_bps=rate)
