"""The LLM seam. In Increment 0 no LLM call exists -- but the seam does.

WHY THIS FILE EXISTS BEFORE THERE IS ANY LLM (PLAN.md, sequence changes)
-----------------------------------------------------------------------
BRIEF Sec 8 requires degraded mode: the batch completes with zero LLM
availability, at a reduced match rate, and reports that it degraded. That
requires a fallback path at every call site. If Tiers 2-3 are built first and
the seam is retrofitted afterwards, degraded mode becomes a refactor of the
resolver instead of an implementation behind an interface.

So the protocol, the cache and the degraded flag land now, at roughly thirty
lines, and `NullAdjudicator` is the Increment 0 implementation: it is permanently
unavailable, which means every Increment 0 run is *already* a degraded-mode run.
The demo proves the degraded path on day one rather than on the day of the video.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AdjudicationRequest:
    """Everything the adjudicator may see. Deliberately narrow.

    The LLM never computes money (BRIEF Sec 4, Tier 3): it selects among
    candidates and explains. Amounts are passed for context, and whatever comes
    back is re-verified by the Tier 1 arithmetic engine before acceptance.
    """

    job: str                 # "parse_narration" | "rank_candidates" | "classify_residual" | "draft_note"
    subject_ref: str
    payload: dict

    def cache_key(self) -> str:
        blob = json.dumps({"job": self.job, "subject": self.subject_ref,
                           "payload": self.payload},
                          sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class AdjudicationResult:
    ok: bool
    data: dict = field(default_factory=dict)
    rationale: str = ""
    reason_unavailable: str = ""


class Adjudicator(Protocol):
    """Every call site programs against this, never against a vendor SDK."""

    @property
    def available(self) -> bool: ...

    def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult: ...


@dataclass(slots=True)
class ResponseCache:
    """Keyed by input hash so runs are reproducible (BRIEF Sec 8).

    temperature 0 alone does not give run-to-run identity; the cache does.
    """

    entries: dict[str, AdjudicationResult] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, key: str) -> AdjudicationResult | None:
        result = self.entries.get(key)
        if result is None:
            self.misses += 1
        else:
            self.hits += 1
        return result

    def put(self, key: str, result: AdjudicationResult) -> None:
        self.entries[key] = result


@dataclass(slots=True)
class NullAdjudicator:
    """Increment 0's implementation: permanently unavailable, never raises.

    Callers must degrade rather than crash, so the null object returns a typed
    "unavailable" result instead of throwing. Every call is counted, which is how
    the run summary can honestly say how much work wanted an LLM and did not get one.
    """

    calls_declined: int = 0
    reason: str = "no adjudicator configured (Increment 0 is rules-only by design)"

    @property
    def available(self) -> bool:
        return False

    def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
        self.calls_declined += 1
        return AdjudicationResult(ok=False, reason_unavailable=self.reason)


@dataclass(slots=True)
class LLMStats:
    """Surfaced in the run summary. `blocked_hallucination` stays at 0 until
    Increment 3 gives it something to block -- it is reported from the start so
    the number has a history rather than appearing on demo day."""

    available: bool = False
    calls_attempted: int = 0
    calls_declined: int = 0
    cache_hits: int = 0
    # Two counters, because they are two different events and one number was
    # actively misleading. See D-025.
    #
    #   blocked_hallucination -- the model returned characters that are NOT in the
    #       narration. It invented a reference. This is the number the fence exists
    #       for, and the one worth quoting.
    #   blocked_unverifiable  -- the model returned text that IS in the narration,
    #       and that text resolves to no known settlement. The extraction was
    #       correct; the document does not contain a usable reference. Rejecting is
    #       still right, but it is not a model error and must not be counted as one.
    blocked_hallucination: int = 0
    blocked_unverifiable: int = 0
    #   blocked_bad_mapping   -- a proposed column mapping failed one of schema
    #       repair's four gates. A third counter for the same reason there are
    #       two above (D-025): it is a different event with a different meaning.
    #       A hallucinated UTR is a model reading a document wrong; a rejected
    #       mapping is a model reasoning about a SCHEMA wrong, and the two say
    #       different things about where a model can be trusted.
    blocked_bad_mapping: int = 0
    degraded: bool = True
    degraded_reason: str = ""

    def to_json(self) -> dict:
        return {
            "available": self.available,
            "calls_attempted": self.calls_attempted,
            "calls_declined": self.calls_declined,
            "cache_hits": self.cache_hits,
            "blocked_hallucination": self.blocked_hallucination,
            "blocked_unverifiable": self.blocked_unverifiable,
            "blocked_bad_mapping": self.blocked_bad_mapping,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
        }
