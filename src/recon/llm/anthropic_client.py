"""A real adjudicator, behind the seam. Optional, lazily imported, never required.

WHY THIS IS AN OPTIONAL EXTRA
-----------------------------
CLAUDE.md pins the default install to `pydantic` + `pytest` to protect the
clean-clone gate, and that is not negotiable for a vendor SDK that most reviewers
will never exercise. So `anthropic` lives in the `[llm]` extra and is imported
INSIDE the constructor. With the SDK absent, or the key absent, this class
reports `available = False` with a reason and the pipeline degrades exactly as it
does with no adjudicator at all -- which is the path every run takes today.

WHAT HAS AND HAS NOT BEEN SENT
------------------------------
`parse_narration` HAS been exercised live: 22 held-out narrations on 01 Sep 2026,
`claude-haiku-4-5`, one call each (RUN_LOG, "Increment 3 -- LIVE adjudicator
run"). That run is what produced `_unfence` and the 600-character error budget
below. This docstring previously said the request shape had never been sent; that
was true when it was written and stopped being true the next day.

`map_schema` HAS now been sent: one call on 03 Sep 2026, same model, and the
mapping was accepted on the first attempt (RUN_LOG, "LIVE map_schema run"). That
is one mapping on one view -- a smoke test that came back correct, not an accuracy
measurement, and it is worded that way everywhere it appears.

Either way it is
survivable by construction: every proposal this class returns is re-verified by
exact lookup in `resolve/tier3.py`, so a malformed response, a wrong UTR or a
total failure all land in the same place -- rejected, counted, and the run
continues on the deterministic path.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .client import (JOB_MAP_SCHEMA, JOB_PARSE_NARRATION, AdjudicationRequest,
                     AdjudicationResult)

# Haiku tier, deliberately. This job is a short extraction from one line of free
# text with a fixed output shape -- no reasoning, no long context, no tool use.
# Reaching for the largest model would cost ~5x for no measurable gain on a task
# like this, and it would undercut the argument the whole submission makes: fence
# the LLM into the narrow job it is actually good at. Using an oversized model for
# a narrow job is the same mistake as using an LLM for arithmetic, one level up.
#
# Overridable by env so a model-id correction is a one-line change rather than a
# code edit -- the id below is written from the current model reference, and the
# first live call is what confirms it (a wrong id raises NotFoundError, which the
# broad handler below turns into a clean degrade rather than a crash).
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024

# An identity-linked API key is scoped to a workspace and the API rejects a call
# that does not name one: 400 `anthropic-workspace-id is required`. It is not a
# secret, but it is read from the environment like the key so that neither ever
# has to be written into a command line or a config file in the repo.
WORKSPACE_HEADER = "anthropic-workspace-id"


def _unfence(text: str) -> str:
    """Strip a markdown code fence if the model wrapped its JSON in one.

    It does, routinely. The first live response came back as a fenced block
    and json.loads rejected it at character zero.

    Handled here rather than by tightening the prompt, and the distinction
    matters: a firmer instruction would still fail intermittently, and tuning
    the prompt against observed HELD-OUT behaviour is precisely the eval-tuning
    that deviation #4 forbids. Stripping a fence is plumbing, and plumbing is
    allowed to know what the world is like.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    if "\n" in text:
        text = text.split("\n", 1)[1]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    return text.strip()


SYSTEM_PROMPT = """\
You extract payment references from Indian bank statement narrations.

A settlement UTR is a 10-digit number followed by 6 alphanumeric characters, but \
narrations truncate it, split it, uppercase it, or run it together with \
surrounding words with no delimiter. Return what is actually present in the text.

Reply with a single JSON object and nothing else:
{"utr": "<the utr exactly as you read it, or empty string>",
 "counterparty": "<payer name if present, else empty string>",
 "reference": "<any other reference token, else empty string>",
 "rationale": "<one short sentence on where in the text you found it>"}

Do not guess a UTR that is not in the text. An empty string is a correct answer \
when the narration does not contain one -- a wrong UTR is worse than none, \
because it will be checked against real settlements and a mismatch is recorded \
as a hallucination."""


# A SECOND JOB, AND WHAT THIS PROMPT DELIBERATELY DOES NOT SAY
# -------------------------------------------------------------
# It states the OUTPUT CONTRACT -- one-to-one, cover every observed column, invent
# no field names -- because a model that does not know the required shape cannot
# answer at all, exactly as the narration prompt states its JSON shape.
#
# It says nothing about what makes a mapping VERIFY. The containment checks in
# `resolve/schema_repair.py` (tax <= fee, fee <= amount, ...) are never mentioned,
# and neither are the identities or the rate card. A model told the test can write
# to the test, and the whole value of the gate is that it is an independent
# opinion about the answer.
MAP_SCHEMA_SYSTEM_PROMPT = """You map the columns of a financial data file onto a fixed target schema.

You are given the column names actually present in the file, the field names the schema declares, and one sample row. Column names may have been renamed, abbreviated, or reordered by whoever produced the file. Use the sample row's VALUES to decide what each column really holds.

Reply with a single JSON object and nothing else:
{"mapping": {"<observed column>": "<target field>", ...},
 "rationale": "<one short sentence on what the values told you>"}

Rules, all strict:
- Map EVERY observed column exactly once. Do not omit one.
- Every target field you name must be one of the target fields given to you. Do not invent a field name.
- No two observed columns may map to the same target field.
- If you cannot work out a column with confidence, still return your best one-to-one mapping; a mapping that is wrong is rejected safely, but a malformed one tells us nothing."""


@dataclass(slots=True)
class AnthropicAdjudicator:
    """Adjudicator backed by the Anthropic Messages API.

    Programs against the `Adjudicator` protocol like every other implementation,
    so no call site knows a vendor SDK exists.
    """

    api_key: str | None = None
    model: str = field(default_factory=lambda: os.environ.get("RECON_LLM_MODEL",
                                                              DEFAULT_MODEL))
    reason: str = ""
    calls_declined: int = 0
    _client: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            self.reason = ("no ANTHROPIC_API_KEY in the environment; "
                           "running rules-only")
            return
        try:
            import anthropic
        except ImportError:
            self.reason = ("the anthropic SDK is not installed; "
                           "install the optional extra: pip install -e '.[llm]'")
            return
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
        headers = {WORKSPACE_HEADER: workspace} if workspace else None
        self._client = anthropic.Anthropic(api_key=key, default_headers=headers)

    @property
    def available(self) -> bool:
        return self._client is not None

    def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
        """One call, one subject. Never raises -- callers must degrade, not crash."""
        if self._client is None:
            self.calls_declined += 1
            return AdjudicationResult(ok=False, reason_unavailable=self.reason)

        # DISPATCH ON THE JOB, and refuse an unwired one loudly.
        #
        # This used to read `payload["narration"]` unconditionally. A map_schema
        # request carries no such key, so it would have sent an EMPTY user message
        # under the narration prompt and returned no `mapping` -- which
        # schema_repair would score as blocked_bad_mapping. That number would have
        # measured this method, not the model, and it would have looked exactly
        # like a real result.
        if request.job == JOB_PARSE_NARRATION:
            system = SYSTEM_PROMPT
            content = str(request.payload.get("narration", ""))
        elif request.job == JOB_MAP_SCHEMA:
            system = MAP_SCHEMA_SYSTEM_PROMPT
            content = json.dumps(request.payload, sort_keys=True, indent=1)
        else:
            self.calls_declined += 1
            return AdjudicationResult(
                ok=False,
                reason_unavailable=f"job {request.job!r} is declared but not wired "
                                   "into this adjudicator; no call was made")
        if not content.strip():
            # The API rejects an empty message, and a 400 here would be recorded as
            # a model failure. An empty subject is our bug, so say so.
            self.calls_declined += 1
            return AdjudicationResult(
                ok=False,
                reason_unavailable=f"empty payload for job {request.job!r}; no call was made")

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                # No `output_config.effort` and no `thinking`. Both are deliberate:
                # the effort parameter is not supported on the Haiku tier and would
                # be rejected outright, and this task wants no thinking at all --
                # it is a one-line extraction with a fixed output shape.
                messages=[{"role": "user", "content": content}],
            )
            text = "".join(block.text for block in response.content
                           if getattr(block, "type", None) == "text")
            payload = json.loads(_unfence(text))
        except Exception as exc:
            # Deliberately broad. A vendor exception, a network failure and a
            # malformed response are the same event to this pipeline: no usable
            # answer, degrade. Narrowing it would only add ways to crash a batch
            # that Sec 8 requires to complete.
            self.calls_declined += 1
            # 600, not 200. The first live error this ever saw was
            # "anthropic-workspace-id is required ... send" -- truncated exactly
            # where it started explaining the fix. A degrade path that hides why it
            # degraded is only half a degrade path.
            return AdjudicationResult(
                ok=False,
                reason_unavailable=f"{type(exc).__name__}: {exc}"[:600])

        if not isinstance(payload, dict):
            self.calls_declined += 1
            return AdjudicationResult(ok=False,
                                      reason_unavailable="response was not a JSON object")

        if request.job == JOB_MAP_SCHEMA:
            # Pass the mapping through UNVALIDATED beyond "it is a dict of strings".
            # Every structural check belongs to the verifier in schema_repair, and
            # duplicating it here would mean a rejection could come from two places
            # and the counter could not say which.
            mapping = payload.get("mapping")
            if not isinstance(mapping, dict):
                self.calls_declined += 1
                return AdjudicationResult(
                    ok=False, reason_unavailable="response carried no `mapping` object")
            return AdjudicationResult(
                ok=True,
                data={"mapping": {str(k): str(v) for k, v in mapping.items()}},
                rationale=str(payload.get("rationale", "")),
            )

        return AdjudicationResult(
            ok=True,
            data={"utr": str(payload.get("utr", "")),
                  "counterparty": str(payload.get("counterparty", "")),
                  "reference": str(payload.get("reference", ""))},
            rationale=str(payload.get("rationale", "")),
        )
