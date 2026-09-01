"""Tier 3 -- LLM adjudication, fenced.

THE ONE JOB
-----------
Extract a UTR from a bank narration whose shape no deterministic parser was
written for. That is the whole remit. BRIEF Sec 3.5 identifies it as the one
genuinely fuzzy surface in this problem, and Increment 2 turned that into a
number: the regex scores 100% on the narration families it was written against
and **0 of 22** on held-out ones.

The LLM is never asked to choose between candidate settlements, never to explain
a residual, never to touch an amount. Tier 1 closes 100% of the gaps it is given,
so there is no arithmetic left for an LLM to help with -- and inventing a job for
it would be exactly the "agent as marketing" anti-pattern (D-016).

THE FENCE, WHICH IS THE POINT
-----------------------------
Invariant 8: the LLM never computes money; it selects and explains, and every
proposal is re-verified by the arithmetic engine before acceptance.

Here that verification is total, because the thing being proposed is a lookup
key. A UTR either resolves to a known settlement or it does not -- there is no
"close enough". So:

    proposal -> exact lookup against known settlement UTRs
             -> resolves?  accept, tier=T3, and Tier 1 still has to explain the money
             -> does not?  REJECT, increment blocked_hallucination, stay unresolved

A hallucinated UTR cannot become a match. It cannot become a *partial* match
either, which is the more subtle failure: there is no scoring step for a
confident wrong answer to win. `tests/test_tier3_fence.py` proves this by pointing
a deliberately hostile adjudicator at the fence and asserting 100% blocked with
linkage precision unmoved at 100.00%.

A fence that rejects everything is a wall, not a fence, so the same tests assert
a truthful adjudicator IS accepted.

DETERMINISM
-----------
Sampling is not reproducible, so the response cache -- keyed by a hash of the
request -- is what makes a run with an adjudicator byte-identical to itself. The
cache is consulted before the adjudicator, always.
"""
from __future__ import annotations

from ..audit.log import AuditLog
from ..domain.graph import (ComponentBasis, ComponentType, Decomposition, EdgeKind,
                            EdgeStatus, Evidence, ExceptionType, ReconEdge, Tier,
                            VarianceComponent)
from ..domain.rates import RULE_VERSION
from ..ingest.load import Repository
from ..llm.client import AdjudicationRequest, Adjudicator, LLMStats, ResponseCache
from ..money import Paise
from ..report.exceptions import ExceptionRecord

JOB_PARSE_NARRATION = "parse_narration"


def _is_faithful_reading(proposed: str, narration: str) -> bool:
    """Did the model read the document, or fill in characters that were not there?

    This is the discriminator behind the two rejection counters (D-025), and it
    has to work from the narration alone -- the resolver never knows the true UTR,
    which is the whole point of it being a resolver.

    Two ways a proposal can be unfaithful, and the second one is easy to miss:

      1. The characters are simply not in the narration. Invented.
      2. The characters ARE in the narration, but the model stopped short of more
         characters that were plainly available -- it returned a prefix of a longer
         run. That is still the model getting it wrong with the evidence in front
         of it, and counting it as "the document had no reference" would flatter us.

    So a reading is faithful only if the proposal appears AND runs to the end of
    its alphanumeric run. That distinguishes "the bank truncated the UTR out of the
    statement" (nothing more was available) from "the model under-read a UTR that
    was fully present".

    PRECONDITION: only ever called on a proposal that ALREADY failed the exact
    lookup. A correct extraction never reaches here -- it resolved and was
    accepted -- which matters, because on a delimiter-free narration
    (`...RAZORPAY<utr>SETTLEMENT`) even a perfectly correct UTR is followed by
    more alphanumerics, and this function would call it unfaithful.

    It is a heuristic, and it is deliberately biased AGAINST us: on that same
    delimiter-free family it will tend to call a genuinely-unavailable reference a
    model error rather than the reverse. A rejection counter that errs toward
    blaming the model is the safe direction for a number we intend to publish.
    """
    low = narration.lower()
    at = low.find(proposed)
    if at < 0:
        return False                       # invented
    after = at + len(proposed)
    if after < len(low) and low[after].isalnum():
        return False                       # stopped short of available characters
    return True


def resolve(repo: Repository, edges: list[ReconEdge],
            exceptions: list[ExceptionRecord], adjudicator: Adjudicator,
            cache: ResponseCache, stats: LLMStats,
            audit: AuditLog) -> tuple[list[ReconEdge], list[ExceptionRecord]]:
    """Ask the adjudicator about narrations Tier 0 could not parse, and verify.

    Returns updated edges and exceptions. Called only when the adjudicator is
    available; with none configured the run is unchanged, which is what makes
    every rules-only run a genuine degraded-mode run rather than a simulated one.
    """
    if not adjudicator.available:
        return edges, exceptions

    settlement_by_utr = repo.settlement_by_utr()
    # ONLY the credits Tier 0 could not parse. Consulting the adjudicator about a
    # narration the regex already resolved would inflate the apparent LLM
    # contribution and cost money for nothing -- so the candidate set is exactly
    # the NARRATION_UNPARSEABLE queue, and a test pins that.
    unparseable = [r for r in exceptions if r.code == ExceptionType.NARRATION_UNPARSEABLE.code]

    # Tier 0 refuses to link a UTR carried by two credits, because choosing one is
    # a coin flip presented as a fact (D-014). Tier 3 must honour the same refusal:
    # an adjudicator that reads a duplicated UTR correctly would otherwise make
    # exactly the link the deterministic tier declined to make, and the fence would
    # not catch it -- the proposal is not a hallucination, it is right.
    ambiguous = {r.subject_id for r in exceptions
                 if r.code == ExceptionType.DUPLICATE_UTR.code}
    # Settlements already reached deterministically. A second credit claiming one
    # is a duplicate posting, not a discovery.
    already_linked = {e.dst_uid for e in edges if e.kind is EdgeKind.BANK_TO_SETTLEMENT}

    accepted: list[str] = []
    resolved_refs: set[str] = set()

    for record in sorted(unparseable, key=lambda r: r.subject_id):
        bank_ref = record.subject_id
        credit = repo.bank.get(bank_ref)
        if credit is None or bank_ref in ambiguous:
            continue

        request = AdjudicationRequest(
            job=JOB_PARSE_NARRATION,
            subject_ref=f"bank_credit:{bank_ref}",
            # Deliberately narrow. The adjudicator sees the free text and nothing
            # else -- not the amount, not the candidate settlements, not the date.
            # Handing it a list of valid UTRs would let it "extract" one it never
            # actually read, and the verifier could not tell the difference.
            payload={"narration": credit.narration},
        )

        key = request.cache_key()
        result = cache.get(key)
        if result is None:
            stats.calls_attempted += 1
            result = adjudicator.adjudicate(request)
            cache.put(key, result)
        else:
            stats.cache_hits += 1

        if not result.ok:
            stats.calls_declined += 1
            audit.record("adjudication_declined", bank_credit=bank_ref,
                         reason=result.reason_unavailable[:120])
            continue

        proposed = str(result.data.get("utr", "")).strip().lower()

        # THE VERIFIER GATE. An exact lookup, with no tolerance and no scoring.
        settlement = settlement_by_utr.get(proposed) if proposed else None
        if settlement is None:
            # WHY the proposal failed matters, and one counter conflated two very
            # different events (D-025). The discriminator is whether the proposed
            # string is actually IN the narration:
            #
            #   present  -> the model read the document correctly and the document
            #               has no usable reference (a bank truncated it, or the
            #               credit is a third party's). Not a model error.
            #   absent   -> the model produced characters that are not there. That
            #               is a hallucination, and it is what the fence is for.
            #
            # Both are rejected either way: an unverifiable reference must never
            # become a link. Only the accounting differs.
            faithful = bool(proposed) and _is_faithful_reading(proposed, credit.narration)
            if not faithful:
                stats.blocked_hallucination += 1
                event = "blocked_hallucination"
            else:
                stats.blocked_unverifiable += 1
                event = "blocked_unverifiable"
            audit.record(event, bank_credit=bank_ref,
                         proposed=proposed[:64],
                         narration=credit.narration[:120],
                         rationale=result.rationale[:160])
            continue

        if settlement.id in already_linked:
            # Correct extraction, wrong conclusion: this settlement already has a
            # credit. Counted separately from a hallucination because it is a
            # different failure -- the model read the text right and the DATA is
            # ambiguous. Linking anyway would silently double-count the cash.
            audit.record("adjudication_rejected_duplicate", bank_credit=bank_ref,
                         settlement=settlement.id, utr=proposed)
            continue
        already_linked.add(settlement.id)

        accepted.append(bank_ref)
        resolved_refs.add(bank_ref)
        members = repo.lines_by_settlement().get(settlement.id, [])
        payments = [m for m in members if m.is_settled_payment]
        gross = Paise(sum(m.amount for m in payments))

        # Seed the decomposition with exactly what Tier 0 would have built from the
        # reported fee and tax, had the regex found this UTR. Tier 3 only supplied
        # the linkage -- the money side of this edge must arrive at Tier 1 in the
        # same state as any deterministically matched one, or Tier 1 adds its
        # components to an incomplete base and the residual never closes.
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
            src_uid=bank_ref,
            dst_uid=settlement.id,
            # MATCHED, not EXPLAINED. The LLM established a linkage; the money is
            # still Tier 1's problem, and this edge does not become explained
            # until the arithmetic closes. That ordering is invariant 8.
            status=EdgeStatus.MATCHED,
            tier=Tier.T3_LLM,
            linked_by=Tier.T3_LLM,
            confidence=80,
            evidence=(
                Evidence("llm_extracted_utr",
                         f"adjudicator proposed utr {proposed} from an unparsed narration",
                         (f"bank_credit:{bank_ref}",)),
                Evidence("verifier_gate",
                         f"utr {proposed} resolved by exact lookup to {settlement.id}; "
                         "a proposal that did not resolve would have been rejected",
                         (f"bank_credit:{bank_ref}", f"settlement:{settlement.id}")),
                Evidence("llm_rationale", result.rationale[:300] or "(none given)",
                         (f"bank_credit:{bank_ref}",)),
            ),
            decomposition=Decomposition(expected=gross, actual=Paise(credit.amount),
                                        components=reported),
        ))
        audit.record("adjudication_accepted", bank_credit=bank_ref,
                     settlement=settlement.id, utr=proposed)

    # A credit the adjudicator resolved is no longer unparseable. Same supersession
    # rule as D-020: the queue states the final position, and the audit log keeps
    # the history of how it got there.
    if resolved_refs:
        exceptions = [r for r in exceptions
                      if not (r.code == ExceptionType.NARRATION_UNPARSEABLE.code
                              and r.subject_id in resolved_refs)]

    edges.sort(key=lambda e: e.sort_key())
    audit.record("tier3_complete", proposals=stats.calls_attempted,
                 accepted=len(accepted),
                 blocked_hallucination=stats.blocked_hallucination,
                 blocked_unverifiable=stats.blocked_unverifiable)
    return edges, exceptions
