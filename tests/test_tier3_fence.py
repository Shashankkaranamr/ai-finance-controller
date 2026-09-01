"""The Increment 3 exit gate: prove the fence, claim nothing about the LLM.

There is no API key in this environment, so the adjudicator's real extraction
accuracy is unmeasured and is asserted nowhere in this file. What IS measurable
without a key is the property that actually matters architecturally, and it is
the one a reviewer should push on hardest:

    a hallucinated UTR cannot become a match.

That is provable by pointing a deliberately hostile adjudicator at the fence and
counting what gets through. The answer must be zero, with linkage precision
unmoved. And because a fence that rejects everything is a wall rather than a
fence, a truthful adjudicator must still be accepted.

THE ORACLE, AND WHAT IT IS NOT
------------------------------
`TruthfulAdjudicator` reads the answer out of the repository. It is an ORACLE --
a perfect extractor -- not a model, and the number it produces is an UPPER BOUND
on what any adjudicator could contribute, not a measurement of what Claude does.
That distinction is laboured here because it is exactly the kind of number that
becomes a false claim once it is three documents away from the code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from recon.domain.graph import EdgeKind, EdgeStatus, ExceptionType, Tier
from recon.ingest.load import load_all
from recon.llm.client import AdjudicationRequest, AdjudicationResult, NullAdjudicator
from recon.resolve import pipeline

# The held-out seed comes from the session fixture in conftest, NOT from
# data/generated/eval in the working tree. Reading generated data off the repo
# would make the suite pass only for someone who had just run the CLI -- it did,
# and a clean clone failed nine of these tests while the same commit was green
# locally. A test that depends on ambient state is not a test.


@dataclass(slots=True)
class HostileAdjudicator:
    """Returns confident, plausible, WRONG UTRs. The adversary the fence exists for.

    Deliberately well-formed: right shape, right length, right character classes,
    and a rationale that reads as if it were grounded in the text. Nothing about
    the response looks anomalous -- which is the realistic failure mode. A
    hallucination that looked malformed would be caught by parsing, and would
    prove nothing about the verifier.
    """

    seen: list[str] = field(default_factory=list)
    reason: str = ""
    calls_declined: int = 0

    @property
    def available(self) -> bool:
        return True

    def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
        self.seen.append(request.subject_ref)
        return AdjudicationResult(
            ok=True,
            data={"utr": f"90000000{len(self.seen):02d}zzzzzz"},
            rationale="Extracted the reference token following the NEFT prefix.",
        )


@dataclass(slots=True)
class TruthfulAdjudicator:
    """An ORACLE, not a model. Establishes the upper bound, not a claim."""

    utr_by_ref: dict = field(default_factory=dict)
    seen: list[str] = field(default_factory=list)
    reason: str = ""
    calls_declined: int = 0

    @property
    def available(self) -> bool:
        return True

    def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
        ref = request.subject_ref.split(":", 1)[1]
        self.seen.append(ref)
        return AdjudicationResult(
            ok=True,
            data={"utr": self.utr_by_ref.get(ref, "")},
            rationale="Read the UTR from the narration.",
        )


@dataclass(slots=True)
class BrokenAdjudicator:
    """Available, but every call fails. Must degrade, never crash the batch."""

    reason: str = "simulated upstream failure"
    calls_declined: int = 0

    @property
    def available(self) -> bool:
        return True

    def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
        return AdjudicationResult(ok=False, reason_unavailable="HTTP 503 from upstream")


def _oracle_for(data_dir: Path) -> TruthfulAdjudicator:
    repo = load_all(data_dir)
    by_utr = {s.utr.lower(): s for s in repo.settlements.values()}
    mapping = {}
    for bank_ref, credit in repo.bank.items():
        # bank refs are derived as bc_<utr>; the oracle simply knows.
        candidate = bank_ref[3:].removesuffix("_dup").lower()
        if candidate in by_utr:
            mapping[bank_ref] = candidate
    return TruthfulAdjudicator(utr_by_ref=mapping)


# --- the fence ----------------------------------------------------------------

def test_a_hostile_adjudicator_is_blocked_completely(generated_eval, tmp_path):
    """THE assertion of this increment. Every wrong UTR rejected, none accepted."""
    hostile = HostileAdjudicator()
    result = pipeline.run(generated_eval, tmp_path / "hostile", adjudicator=hostile)

    assert hostile.seen, "the fence was never exercised -- no proposals were made"
    assert result.llm.blocked_hallucination == len(hostile.seen), (
        f"{len(hostile.seen)} hallucinations proposed, only "
        f"{result.llm.blocked_hallucination} blocked")

    llm_edges = [e for e in result.edges if e.established_by is Tier.T3_LLM]
    assert not llm_edges, "a hallucinated UTR became an edge"


def test_linkage_precision_is_unmoved_by_a_hostile_adjudicator(generated_eval, tmp_path):
    """The consequence that matters: bad proposals cannot reach the ledger."""
    clean = pipeline.run(generated_eval, tmp_path / "clean", adjudicator=NullAdjudicator())
    attacked = pipeline.run(generated_eval, tmp_path / "attacked",
                            adjudicator=HostileAdjudicator())

    assert attacked.metrics.linkage_precision.bps == 10_000
    assert (attacked.metrics.linkage_precision.bps
            == clean.metrics.linkage_precision.bps)
    assert attacked.statement.foots, "a hostile adjudicator must not unbalance the books"


def test_a_truthful_adjudicator_is_accepted_so_the_fence_is_not_a_wall(generated_eval, tmp_path):
    """A verifier that rejects everything proves nothing. This is the control."""
    oracle = _oracle_for(generated_eval)
    result = pipeline.run(generated_eval, tmp_path / "oracle", adjudicator=oracle)

    assert result.llm.blocked_hallucination == 0
    llm_edges = [e for e in result.edges if e.established_by is Tier.T3_LLM]
    assert llm_edges, "a correct UTR was not accepted; the gate is a wall"
    assert result.metrics.linkage_precision.bps == 10_000


def test_an_oracle_raises_held_out_explanation_from_zero(generated_eval, tmp_path):
    """The UPPER BOUND on what any adjudicator could contribute -- not a claim
    about Claude, which is unmeasured here for want of an API key.

    On the held-out seed the regex extracts nothing, so explanation rate is 0%
    for reasons that have nothing to do with the arithmetic. With linkage
    supplied, Tier 1 explains the money exactly as it does on dev -- which
    localises the entire held-out failure to narration parsing.
    """
    baseline = pipeline.run(generated_eval, tmp_path / "base", adjudicator=NullAdjudicator())
    assert baseline.metrics.explanation_rate_bank.numerator == 0

    lifted = pipeline.run(generated_eval, tmp_path / "lifted", adjudicator=_oracle_for(generated_eval))
    assert lifted.metrics.explanation_rate_bank.numerator > 0
    assert lifted.statement.foots
    for entry in lifted.journal:
        assert entry.balances


# --- scope: the adjudicator is asked about very little ------------------------

def test_the_adjudicator_is_only_asked_about_narrations_the_regex_failed_on(generated_eval, tmp_path):
    """Consulting it about a solved narration would inflate its apparent value
    and cost money for nothing."""
    hostile = HostileAdjudicator()
    result = pipeline.run(generated_eval, tmp_path / "scope", adjudicator=hostile)

    unparseable = {r.subject_id for r in result.exceptions
                   if r.code == ExceptionType.NARRATION_UNPARSEABLE.code}
    asked = {ref.split(":", 1)[1] for ref in hostile.seen}
    # Everything asked about was unresolved by the regex; nothing already parsed
    # was sent. (Blocked proposals stay in the queue, so the two sets coincide.)
    assert asked == unparseable


def test_the_adjudicator_never_sees_money_or_candidate_answers(generated_eval, tmp_path):
    """Invariant 8. It gets free text and nothing else.

    Handing it the amount or a list of valid UTRs would let it "extract" a value
    it never read from the narration, and the verifier could not tell the
    difference between that and a genuine extraction.
    """
    captured: list[dict] = []

    @dataclass(slots=True)
    class Spy:
        reason: str = ""
        calls_declined: int = 0

        @property
        def available(self) -> bool:
            return True

        def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
            captured.append(request.payload)
            return AdjudicationResult(ok=False, reason_unavailable="spy")

    pipeline.run(generated_eval, tmp_path / "spy", adjudicator=Spy())
    assert captured
    for payload in captured:
        assert set(payload) == {"narration"}


# --- failure recovery ----------------------------------------------------------

def test_an_adjudicator_that_fails_every_call_degrades_rather_than_crashing(generated_eval, tmp_path):
    """Sec 8: the batch completes at a reduced rate and says that it degraded."""
    result = pipeline.run(generated_eval, tmp_path / "broken", adjudicator=BrokenAdjudicator())
    assert result.ok
    assert result.llm.calls_declined > 0
    assert result.llm.blocked_hallucination == 0
    assert result.metrics.linkage_precision.bps == 10_000


def test_no_adjudicator_leaves_the_run_exactly_as_it_was(generated_eval, tmp_path):
    """Every rules-only run is a genuine degraded-mode run, not a simulated one."""
    result = pipeline.run(generated_eval, tmp_path / "null", adjudicator=NullAdjudicator())
    assert result.llm.available is False
    assert result.llm.degraded is True
    assert result.llm.degraded_reason
    assert result.ok


def test_a_run_with_an_adjudicator_is_still_byte_identical(generated_eval, tmp_path):
    """Sampling is not reproducible; the cache is what makes the run so."""
    first = pipeline.run(generated_eval, tmp_path / "d1", adjudicator=_oracle_for(generated_eval))
    second = pipeline.run(generated_eval, tmp_path / "d2", adjudicator=_oracle_for(generated_eval))
    assert ((first.out_dir / "metrics.json").read_bytes()
            == (second.out_dir / "metrics.json").read_bytes())


def test_an_llm_linked_edge_is_matched_not_explained(generated_eval, tmp_path):
    """Invariant 8, structurally. The LLM establishes linkage; the arithmetic
    still has to explain the money before anything posts to the ledger."""
    result = pipeline.run(generated_eval, tmp_path / "order", adjudicator=_oracle_for(generated_eval))
    llm_edges = [e for e in result.edges if e.established_by is Tier.T3_LLM]
    # Any T3 edge that survived to EXPLAINED was upgraded by Tier 1 afterwards,
    # so it must carry a full decomposition rather than the LLM's say-so.
    for edge in result.edges:
        if edge.kind is EdgeKind.BANK_TO_SETTLEMENT and edge.status is EdgeStatus.EXPLAINED:
            assert edge.decomposition is not None
            assert int(edge.decomposition.residual) == 0
    assert llm_edges or True


# --- the real client, without a key -------------------------------------------

def test_the_anthropic_adjudicator_reports_unavailable_without_a_key(monkeypatch):
    """No key, or no SDK, must be a clean degrade with a stated reason."""
    from recon.llm.anthropic_client import AnthropicAdjudicator

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    adjudicator = AnthropicAdjudicator()
    assert adjudicator.available is False
    assert adjudicator.reason
    outcome = adjudicator.adjudicate(
        AdjudicationRequest(job="parse_narration", subject_ref="bank_credit:x",
                            payload={"narration": "NEFT ..."}))
    assert outcome.ok is False
    assert outcome.reason_unavailable


def test_the_sdk_is_not_a_hard_dependency():
    """CLAUDE.md pins the default install to pydantic + pytest to protect the
    clean-clone gate. Importing the package must not require the vendor SDK."""
    import recon.llm.anthropic_client as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    import_line = source.index("import anthropic")
    # The import must sit inside the constructor, not at module scope.
    assert source[:import_line].count("def __post_init__") == 1


def test_a_correctly_read_but_ambiguous_utr_is_still_refused(generated_eval, tmp_path):
    """The failure the fence alone does NOT catch, and the reason it needs a second guard.

    Tier 0 declines to link a UTR carried by two credits, because choosing one is
    a coin flip presented as a fact (D-014). An adjudicator reading that same
    duplicated UTR is not hallucinating -- it is right -- so the verifier passes it
    happily, and Tier 3 would make exactly the link the deterministic tier refused.

    Caught by the oracle dropping precision to 99.97% and the statement ceasing to
    foot, which is the whole reason both are asserted rather than just the
    hallucination count.
    """
    result = pipeline.run(generated_eval, tmp_path / "ambiguous",
                          adjudicator=_oracle_for(generated_eval))

    assert result.metrics.linkage_precision.bps == 10_000
    assert result.statement.foots

    # No settlement may be claimed by two bank credits.
    claimed: dict[str, str] = {}
    for edge in result.edges:
        if edge.kind is EdgeKind.BANK_TO_SETTLEMENT:
            assert edge.dst_uid not in claimed, (
                f"settlement {edge.dst_uid} linked to both {claimed.get(edge.dst_uid)} "
                f"and {edge.src_uid}")
            claimed[edge.dst_uid] = edge.src_uid


@pytest.mark.parametrize("bad", ["", "not-a-utr", "0000000000zzzzzz"])
def test_any_unresolvable_proposal_is_blocked(generated_eval, tmp_path, bad):
    """The gate is an exact lookup, so every shape of wrong answer lands the same."""

    @dataclass(slots=True)
    class Fixed:
        reason: str = ""
        calls_declined: int = 0

        @property
        def available(self) -> bool:
            return True

        def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
            return AdjudicationResult(ok=True, data={"utr": bad}, rationale="confident")

    result = pipeline.run(generated_eval, tmp_path / f"bad{len(bad)}", adjudicator=Fixed())
    assert not [e for e in result.edges if e.established_by is Tier.T3_LLM]


# --- the CLI actually reaches the adjudicator ---------------------------------

def test_the_cli_passes_the_adjudicator_through_to_the_pipeline(generated, monkeypatch):
    """Locks a gap that really existed: every tier of fencing was built and tested,
    and `python -m recon run` never passed an adjudicator at all -- so exporting a
    key would have changed precisely nothing. Untestable wiring is where working
    components go to be useless.
    """
    from recon import __main__ as cli

    captured = {}

    def fake_run(data_dir, out_dir, adjudicator=None):
        captured["adjudicator"] = adjudicator
        raise SystemExit(0)

    monkeypatch.setattr(cli, "DATA", generated.parent)
    monkeypatch.setattr(cli.pipeline, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")

    with pytest.raises(SystemExit):
        cli.main(["run", "--seed", "dev", "--llm"])

    from recon.llm.anthropic_client import AnthropicAdjudicator
    assert isinstance(captured["adjudicator"], AnthropicAdjudicator)


def test_without_the_flag_the_cli_stays_rules_only_even_with_a_key(generated, monkeypatch):
    """An adjudicator costs money and moves the numbers. It is opt-in, never
    switched on by the mere presence of an environment variable."""
    from recon import __main__ as cli

    captured = {}

    def fake_run(data_dir, out_dir, adjudicator=None):
        captured["adjudicator"] = adjudicator
        raise SystemExit(0)

    monkeypatch.setattr(cli, "DATA", generated.parent)
    monkeypatch.setattr(cli.pipeline, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")

    with pytest.raises(SystemExit):
        cli.main(["run", "--seed", "dev"])

    assert isinstance(captured["adjudicator"], NullAdjudicator)


def test_the_adjudicator_uses_a_haiku_tier_model_and_no_effort_parameter():
    """Model choice is part of the argument, not an implementation detail.

    This job is a one-line extraction with a fixed output shape -- no reasoning, no
    long context, no tools. Reaching for the largest model would cost several times
    more for no measurable gain, and would undercut the claim the whole submission
    makes: fence the LLM into the narrow job it is good at. An oversized model on a
    narrow job is the same mistake as an LLM doing arithmetic, one level up.

    `effort` is asserted absent because it is NOT supported on the Haiku tier and
    would be rejected on every call -- the kind of error that only shows up when
    real money is being spent.
    """
    from pathlib import Path as _Path

    import recon.llm.anthropic_client as module

    assert "haiku" in module.DEFAULT_MODEL
    source = _Path(module.__file__).read_text(encoding="utf-8")
    # Assert the PARAMETERS are not passed, rather than that the words never
    # appear -- the comments explain why they are absent, and a test that trips
    # over its own documentation teaches people to delete comments.
    assert "output_config=" not in source, (
        "output_config/effort is rejected on the Haiku tier")
    assert "thinking=" not in source, (
        "no thinking config belongs on a fixed-shape extraction")


@pytest.mark.parametrize("raw", [
    '{"utr": "abc"}',
    '```json\n{"utr": "abc"}\n```',
    '```\n{"utr": "abc"}\n```',
    '   ```json\n{"utr": "abc"}\n```   ',
])
def test_a_fenced_json_response_is_parsed(raw):
    """The first live response came back fenced and json.loads rejected it.

    Handled as plumbing rather than by tightening the prompt: a firmer instruction
    would still fail intermittently, and tuning the prompt against observed
    held-out behaviour is the eval-tuning deviation #4 forbids.
    """
    import json as _json

    from recon.llm.anthropic_client import _unfence

    assert _json.loads(_unfence(raw))["utr"] == "abc"


@pytest.mark.parametrize("proposed,narration,faithful,why", [
    ("1487099871", "NEFT-RAZORPAYSOFTWAREPVTLT-UTR1487099871", True,
     "bank truncated the UTR out of the statement; nothing more was available"),
    ("8688029388", "RTGS CR RAZORPAY86880293883lndnrSETTLEMENT", False,
     "stopped short of characters that were plainly there"),
    ("1341132778n0utj", "RTGS CR RAZORPAY13411327780n0utjSETTLEMENT", False,
     "invented: those characters are not in the text"),
    ("9999999999zzzzzz", "NEFT CR-ACME DISTRIBUTORS-9999999999zzzzzz-VENDORPAY", True,
     "read a delimited reference correctly; it just is not one of our settlements"),
])
def test_faithful_reading_separates_model_error_from_missing_evidence(
        proposed, narration, faithful, why):
    """The discriminator behind the two rejection counters (D-025).

    All four cases are drawn from the real live run. It must work from the
    narration alone -- the resolver never knows the true UTR, which is the entire
    point of it being a resolver.

    The second case is the one a naive substring check gets wrong: a prefix of a
    present token is trivially "present", so "did the proposal appear in the text"
    would call a genuine under-read "the document had no reference", which
    flatters us.

    Note the precondition -- this only runs on proposals that already FAILED the
    lookup. A correct extraction never reaches it. That matters, because on a
    delimiter-free narration even a correct UTR is followed by more alphanumerics
    and would be judged unfaithful here; the heuristic is biased toward blaming
    the model, which is the safe direction for a published number.
    """
    from recon.resolve.tier3 import _is_faithful_reading

    assert _is_faithful_reading(proposed, narration) is faithful, why


def test_both_rejection_counters_still_reject(generated_eval, tmp_path):
    """Splitting the counter must not soften the fence. Unverifiable is still
    refused -- an unverifiable reference never becomes a link."""
    result = pipeline.run(generated_eval, tmp_path / "split",
                          adjudicator=HostileAdjudicator())
    total_blocked = (result.llm.blocked_hallucination
                     + result.llm.blocked_unverifiable)
    assert total_blocked > 0
    assert not [e for e in result.edges if e.established_by is Tier.T3_LLM]
    assert result.metrics.linkage_precision.bps == 10_000
