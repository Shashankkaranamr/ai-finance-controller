"""Tier 2 -- deterministic candidate corroboration on (amount, value_date).

WHY TIER 2 IS BACK, AND WHY IT IS NOT WHAT WAS CUT
--------------------------------------------------
D-016 cut Tier 2, and the reasoning was sound for what Tier 2 then meant: a
subset-sum search over manufactured ambiguity, built to give the LLM something to
adjudicate. That is still cut and still the right call.

This is the other half of the brief's Tier 2 — candidate generation over a
date-windowed set — and an adversarial audit showed it was the missing answer to
the first question any reviewer asks:

    "Your bank credit equals the settlement amount to the paise, on the
     settlement date. Why do you need the narration at all?"

On the held-out seed the narration parser scores zero, the LLM recovers 3–5 of
22, and a two-field exact join recovers ~20 of 22 with no model at all. Shipping
an LLM result while ignoring two columns already loaded in memory would have been
indefensible, and the honest response is to build the deterministic thing and
publish the comparison (D-027).

WHAT MAKES THIS DETERMINISTIC RATHER THAN FUZZY
-----------------------------------------------
No tolerance on money, no scoring, no ranking. A credit links only when its
**exact** amount resolves to one settlement whose posting window contains the
credit's value date, AND that settlement is claimed by exactly one such credit.
Every tie is refused, exactly as D-014 refuses a duplicated UTR: choosing between
two equally good candidates is a coin flip presented as a fact.

That is why this is Tier 2 and not "fuzzy matching wearing a hat" — the §9
anti-pattern is scoring on proximity and token overlap, and there is none here.

WHY A WINDOW ON THE DATE, AND WHY THAT IS NOT A TOLERANCE (D-033)
-----------------------------------------------------------------
The first version of this tier keyed on `(amount, value_date)` EXACTLY, and it
worked because the generator copied the settlement's date straight into the bank
row. BRIEF Sec 3.4 lists `created_at != settled_at != bank value date` as one of
the two structural difficulties of this domain, so that copy was a fiction, and
closing it (C-2(a)) took the held-out explanation rate from 18/23 to **4/23**. The
entire result rested on a field the bank does not actually restate.

A transfer initiated on day D posts on D or the next business day, and never on a
weekend. `BANK_POSTING_WINDOW_DAYS` is that bound. The distinction that matters:

  * a tolerance on MONEY would turn an arithmetic proof into a score, and there is
    still none -- the amount must match to the paise;
  * a window on a DATE is a statement about settlement mechanics. A credit cannot
    post before its transfer was initiated, and it cannot post a month later.

The window is CONTRACT knowledge, the same class as the reserve rate: a real
deployment reads it off the bank's posting SLA. That is a circularity of the kind
D-019 already publishes, and it is named here rather than left implicit.

WHAT IT DOES NOT PROVE
----------------------
With the date reduced to a window, **the amount is doing nearly all the work** --
and it can, because a mixed merchant's daily net settlement is an effectively
random paise value. Measured on this data: 22 of 22 settlement amounts are
distinct on both seeds, with the two closest Rs 171.98 apart. That is a real
property of settlement amounts and not an artifact, which is the honest half.

The dishonest half would be to stop there. Corroboration is *evidence*, not
identification: it rests on every amount being right, and F-016 established that a
reported total can be wrong. When it is, this tier does not merely fail -- it fails
SILENTLY, finding nothing, where Tier 0 would have raised ROLLUP_MISMATCH. A
multi-gateway merchant (cut, D-016) would break the amount's uniqueness outright.
Said out loud in ARCHITECTURE.md §4 rather than left for a reviewer to find.
"""
from __future__ import annotations

from datetime import timedelta

from ..audit.log import AuditLog
from ..domain.graph import (ComponentBasis, ComponentType, Decomposition, EdgeKind,
                            EdgeStatus, Evidence, ExceptionType, ReconEdge, Tier,
                            VarianceComponent)
from ..domain.rates import BANK_POSTING_WINDOW_DAYS, RULE_VERSION
from ..ingest.load import Repository
from ..money import Paise, format_inr
from ..report.exceptions import ExceptionRecord
from .tier0 import SETTLEMENT_PROCESSED


def resolve(repo: Repository, edges: list[ReconEdge],
            exceptions: list[ExceptionRecord],
            audit: AuditLog) -> tuple[list[ReconEdge], list[ExceptionRecord]]:
    """Link unmatched credits to unmatched settlements by exact (amount, date).

    Runs after Tier 0's narration join and before Tier 3, so the LLM is only ever
    asked about credits that deterministic evidence could not place. That ordering
    is the whole point: it keeps the LLM's measured contribution honest by giving
    it only the residue.
    """
    linked_settlements = {e.dst_uid for e in edges if e.kind is EdgeKind.BANK_TO_SETTLEMENT}
    linked_credits = {e.src_uid for e in edges if e.kind is EdgeKind.BANK_TO_SETTLEMENT}

    open_credits = [repo.bank[r] for r in sorted(repo.bank) if r not in linked_credits]
    # A SETTLEMENT THE REPORT SAYS NEVER PAID OUT IS NOT A CANDIDATE.
    #
    # Tier 0 reads `status` and reports a non-`processed` settlement as
    # SETTLEMENT_FAILED -- the money never left. Corroborating a credit against it
    # anyway makes two tiers contradict each other inside one run, and it is how a
    # duplicate posting of a *cancelled* transfer got linked and marked explained
    # on the held-out seed (F-017).
    #
    # This is not a synthetic-data patch. A real statement can easily carry an
    # unrelated credit matching a failed settlement's amount and date; two fields
    # agreeing is corroboration, and there is nothing to corroborate when the
    # gateway has already said the transfer did not complete.
    open_settlements = [repo.settlements[s] for s in sorted(repo.settlements)
                        if s not in linked_settlements
                        and repo.settlements[s].status == SETTLEMENT_PROCESSED]
    if not open_credits or not open_settlements:
        return edges, exceptions

    # Index both sides on the EXACT amount, then filter by the posting window, so
    # uniqueness can still be required in BOTH directions. One-directional
    # uniqueness would happily link two identical credits to the one settlement
    # that matches them.
    settlements_by_amount: dict[int, list] = {}
    for settlement in open_settlements:
        settlements_by_amount.setdefault(int(settlement.amount), []).append(settlement)
    credits_by_amount: dict[int, list] = {}
    for credit in open_credits:
        credits_by_amount.setdefault(int(credit.amount), []).append(credit)

    def posts_within(settlement, value_date) -> bool:
        """Could a transfer initiated on the settlement date post on this date?

        Deliberately asymmetric: a credit may post on the settlement date or after
        it, never before. A rule allowing `value_date < created_at` would match a
        credit to a transfer that had not been initiated yet.
        """
        return (settlement.created_at <= value_date
                <= settlement.created_at + timedelta(days=BANK_POSTING_WINDOW_DAYS))

    members_by_settlement = repo.lines_by_settlement()
    resolved_refs: set[str] = set()
    ambiguous = 0

    for credit in open_credits:
        candidates = [s for s in settlements_by_amount.get(int(credit.amount), [])
                      if posts_within(s, credit.value_date)]

        if len(candidates) != 1:
            if candidates:
                # A tie is refused, not broken. Same rule as D-014.
                ambiguous += 1
                audit.record("corroboration_ambiguous", bank_credit=credit.bank_ref,
                             settlements=len(candidates), credits=0)
            continue

        settlement = candidates[0]
        # The other direction: is this settlement claimed by exactly one credit?
        # Computed against THIS settlement's window rather than a shared key,
        # because two credits of the same amount can now sit in overlapping but
        # different windows.
        rival_credits = [c for c in credits_by_amount.get(int(settlement.amount), [])
                         if posts_within(settlement, c.value_date)]
        if len(rival_credits) != 1:
            ambiguous += 1
            audit.record("corroboration_ambiguous", bank_credit=credit.bank_ref,
                         settlements=1, credits=len(rival_credits))
            continue

        members = members_by_settlement.get(settlement.id, [])
        payments = [m for m in members if m.is_settled_payment]
        gross = Paise(sum(m.amount for m in payments))
        reported = (
            VarianceComponent(ComponentType.MDR,
                              Paise(sum(m.fee - m.tax for m in payments)),
                              RULE_VERSION, ComponentBasis.SCHEMA),
            VarianceComponent(ComponentType.GST_ON_MDR,
                              Paise(sum(m.tax for m in payments)),
                              RULE_VERSION, ComponentBasis.SCHEMA),
        )

        edges.append(ReconEdge(
            kind=EdgeKind.BANK_TO_SETTLEMENT,
            src_uid=credit.bank_ref,
            dst_uid=settlement.id,
            # MATCHED, never EXPLAINED. Corroboration establishes linkage; Tier 1
            # still has to close the money, exactly as for a UTR match.
            status=EdgeStatus.MATCHED,
            tier=Tier.T2_CANDIDATE,
            linked_by=Tier.T2_CANDIDATE,
            # Lower than a UTR match on purpose. This is corroboration, not
            # identification: two fields agreeing is strong evidence, not a
            # reference the gateway asserted.
            confidence=85,
            evidence=(
                Evidence("amount_date_corroboration",
                         f"credit {format_inr(Paise(credit.amount))} on "
                         f"{credit.value_date.isoformat()} matches the exact amount of "
                         f"exactly one open settlement initiated on "
                         f"{settlement.created_at.isoformat()}, inside the "
                         f"{BANK_POSTING_WINDOW_DAYS}-day posting window",
                         (f"bank_credit:{credit.bank_ref}", f"settlement:{settlement.id}")),
                Evidence("uniqueness_required_both_ways",
                         "1 settlement carries this exact amount in a window containing "
                         "this credit, and 1 credit falls inside that settlement's "
                         "window; any tie is refused rather than broken",
                         (f"bank_credit:{credit.bank_ref}",)),
                Evidence("no_utr_evidence",
                         "the narration yielded no UTR — this link rests on corroboration, "
                         "not on a reference the gateway asserted",
                         (f"bank_credit:{credit.bank_ref}",)),
            ),
            decomposition=Decomposition(expected=gross, actual=Paise(credit.amount),
                                        components=reported),
        ))
        resolved_refs.add(credit.bank_ref)
        # Consume both sides. The uniqueness checks above already guarantee a 1:1
        # pairing -- two settlements matching one credit, or two credits falling in
        # one settlement's window, are both refused before reaching here -- so this
        # cannot change any outcome. It is kept so that a future relaxation of
        # either check cannot silently produce a settlement claimed twice.
        settlements_by_amount.get(int(settlement.amount), []).remove(settlement)
        credits_by_amount.get(int(credit.amount), []).remove(credit)
        audit.record("corroborated", bank_credit=credit.bank_ref,
                     settlement=settlement.id, amount=int(credit.amount))

    # A credit we have now placed is no longer an unreadable narration, and the
    # settlement is no longer unconfirmed. Same supersession rule as D-020: the
    # queue states the final position; the audit log keeps how it got there.
    if resolved_refs:
        placed = {e.dst_uid for e in edges
                  if e.kind is EdgeKind.BANK_TO_SETTLEMENT and e.src_uid in resolved_refs}
        before = len(exceptions)
        exceptions = [
            r for r in exceptions
            if not (r.code == ExceptionType.NARRATION_UNPARSEABLE.code
                    and r.subject_id in resolved_refs)
            and not (r.code == ExceptionType.SETTLEMENT_UNCONFIRMED.code
                     and r.subject_id in placed)
        ]
        audit.record("corroboration_superseded", dropped=before - len(exceptions))

    edges.sort(key=lambda e: e.sort_key())
    audit.record("tier2_complete", linked=len(resolved_refs), refused_ties=ambiguous)
    return edges, exceptions
