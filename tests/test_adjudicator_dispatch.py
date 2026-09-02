"""The live adjudicator must serve the job it is handed, or refuse it by name.

WHY THIS FILE EXISTS
--------------------
`map_schema` was built against the `Adjudicator` protocol and proved with test
doubles, and the one REAL implementation was never taught the job. It read
`payload["narration"]` unconditionally, so a map_schema request -- which has no
such key -- would have gone to the API as an empty user message under the
narration prompt, come back with no `mapping`, and been scored
`blocked_bad_mapping` by the verifier.

That is the dangerous shape: a number that looks like a measurement of the model
and is actually a measurement of our own wiring. Nothing in the suite could see
it, because every other test supplies its own adjudicator.

These tests use a stub transport. They make no network call and need no key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from recon.llm.anthropic_client import (MAP_SCHEMA_SYSTEM_PROMPT, SYSTEM_PROMPT,
                                        AnthropicAdjudicator)
from recon.llm.client import (JOB_MAP_SCHEMA, JOB_PARSE_NARRATION,
                              AdjudicationRequest)


@dataclass
class _Block:
    text: str
    type: str = "text"


@dataclass
class _Response:
    content: list


@dataclass
class _Messages:
    reply: str
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(content=[_Block(text=self.reply)])


@dataclass
class _Client:
    messages: _Messages


def _wired(reply: str) -> tuple[AnthropicAdjudicator, _Messages]:
    """An adjudicator with the vendor client replaced by a stub."""
    messages = _Messages(reply=reply)
    adjudicator = AnthropicAdjudicator(api_key="stub-not-a-real-key")
    adjudicator._client = _Client(messages=messages)
    return adjudicator, messages


def test_an_unwired_job_declines_without_calling_the_api():
    """`rank_candidates` is declared in the seam and deliberately unbuilt. Sending
    it anyway would bill a call and return an answer to a question we never asked."""
    adjudicator, messages = _wired("{}")
    result = adjudicator.adjudicate(AdjudicationRequest(
        job="rank_candidates", subject_ref="x", payload={"candidates": []}))

    assert not result.ok
    assert "not wired" in result.reason_unavailable
    assert not messages.calls, "an unwired job must not reach the API"


def test_an_empty_subject_is_refused_as_our_bug_not_the_models():
    """The API rejects an empty message, and that 400 would be recorded against
    the model. An empty payload is ours, so it never leaves the process."""
    adjudicator, messages = _wired("{}")
    result = adjudicator.adjudicate(AdjudicationRequest(
        job=JOB_PARSE_NARRATION, subject_ref="x", payload={"narration": "   "}))

    assert not result.ok
    assert "empty payload" in result.reason_unavailable
    assert not messages.calls


def test_map_schema_sends_its_own_prompt_and_the_whole_payload():
    adjudicator, messages = _wired(
        '{"mapping": {"entity_ref": "entity_id"}, "rationale": "values look like ids"}')
    payload = {"observed_columns": ["entity_ref"], "target_fields": ["entity_id"],
               "sample_row": {"entity_ref": "abc"}}
    result = adjudicator.adjudicate(AdjudicationRequest(
        job=JOB_MAP_SCHEMA, subject_ref="source_view:x", payload=payload))

    assert len(messages.calls) == 1
    sent = messages.calls[0]
    assert sent["system"] == MAP_SCHEMA_SYSTEM_PROMPT
    body = json.loads(sent["messages"][0]["content"])
    assert body == payload, "the model must see the columns, the targets and the sample"
    assert result.ok
    assert result.data["mapping"] == {"entity_ref": "entity_id"}


def test_map_schema_without_a_mapping_is_not_a_usable_answer():
    """A reply that parses as JSON but carries no mapping is a failed call, not an
    empty mapping -- the difference decides which counter moves."""
    adjudicator, _ = _wired('{"rationale": "I could not tell"}')
    result = adjudicator.adjudicate(AdjudicationRequest(
        job=JOB_MAP_SCHEMA, subject_ref="source_view:x",
        payload={"observed_columns": ["a"], "target_fields": ["b"], "sample_row": {}}))

    assert not result.ok
    assert "mapping" in result.reason_unavailable


def test_parse_narration_is_unchanged_so_the_01_sep_numbers_stay_comparable():
    """The live run of 01 Sep is published. If this path drifts, that entry stops
    describing the code and the ablation stops being reproducible."""
    adjudicator, messages = _wired(
        '{"utr": "1487099871", "counterparty": "", "reference": "", "rationale": "prefix"}')
    result = adjudicator.adjudicate(AdjudicationRequest(
        job=JOB_PARSE_NARRATION, subject_ref="bank_credit:x",
        payload={"narration": "NEFT-RAZORPAYSOFTWAREPVTLT-UTR1487099871"}))

    sent = messages.calls[0]
    assert sent["system"] == SYSTEM_PROMPT
    assert sent["messages"][0]["content"] == "NEFT-RAZORPAYSOFTWAREPVTLT-UTR1487099871", (
        "the narration is sent raw, with nothing added around it")
    assert result.data["utr"] == "1487099871"
    assert "mapping" not in result.data
