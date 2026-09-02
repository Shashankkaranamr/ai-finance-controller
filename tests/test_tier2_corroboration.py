"""Tier 2: deterministic corroboration on (amount, value_date) — FIX-4 / D-027.

The audit's sharpest finding: on the held-out seed a two-field exact join
reproduces the entire dev result with no model at all, while the shipped system
reported 0% and credited an LLM with 3-5 of 22. These tests pin the behaviour
that makes the corroboration defensible rather than lucky.
"""
from __future__ import annotations

import pytest

from recon.domain.graph import EdgeKind, EdgeStatus, Tier
from recon.domain.rates import BANK_POSTING_WINDOW_DAYS
from recon.domain.truth import GroundTruth
from recon.ingest.load import load_all
from recon.resolve import pipeline


def test_corroboration_carries_the_held_out_seed_without_any_model(generated_eval, tmp_path):
    """The result that forced this tier to exist."""
    result = pipeline.run(generated_eval, tmp_path / "corr")

    corroborated = [e for e in result.edges if e.established_by is Tier.T2_CANDIDATE]
    assert corroborated, "no credit was corroborated on a seed where no narration parses"
    assert result.metrics.explanation_rate_bank.numerator > 0
    assert result.llm.calls_attempted == 0, "no model was involved"


def test_every_corroborated_link_is_correct(generated_eval, tmp_path):
    """Precision is the whole licence for doing this at all.

    Checked against ground truth edge by edge, not via the aggregate — an
    aggregate at 3,508 edges would not notice twenty wrong ones.
    """
    result = pipeline.run(generated_eval, tmp_path / "prec")
    truth = GroundTruth.read(generated_eval / "ground_truth.json")
    true_edges = {(e.kind, e.src_uid, e.dst_uid) for e in truth.edges}

    corroborated = [e for e in result.edges if e.established_by is Tier.T2_CANDIDATE]
    wrong = [e for e in corroborated
             if ("bank_to_settlement", e.src_uid, e.dst_uid) not in true_edges]
    assert not wrong, f"{len(wrong)} corroborated links are not real"
    assert result.metrics.linkage_precision.bps == 10_000


def test_a_tie_is_refused_rather_than_broken(generated_eval, tmp_path):
    """Same rule as D-014. Two settlements sharing an (amount, date) must yield
    no link at all, not a coin flip presented as a fact.

    Constructed by duplicating a settlement's key so the tie is guaranteed,
    rather than hoping the fixture happens to contain one.
    """
    repo = load_all(generated_eval)
    victim = sorted(repo.settlements)[0]
    twin = sorted(repo.settlements)[1]
    target = repo.settlements[victim]

    # Force a collision: make another settlement identical on both key fields.
    # Pydantic model, so model_copy rather than dataclasses.replace.
    repo.settlements[twin] = repo.settlements[twin].model_copy(
        update={"amount": target.amount, "created_at": target.created_at})

    from recon.audit.log import AuditLog
    from recon.resolve import tier0, tier2

    audit = AuditLog(run_id="tie", rule_version="test")
    edges, exceptions = tier0.resolve(repo, audit)
    edges, exceptions = tier2.resolve(repo, edges, exceptions, audit)

    linked = {e.dst_uid for e in edges
              if e.kind is EdgeKind.BANK_TO_SETTLEMENT
              and e.established_by is Tier.T2_CANDIDATE}
    assert victim not in linked and twin not in linked, (
        "a tied (amount, date) was broken instead of refused")


def test_corroboration_never_overwrites_a_narration_match(generated, tmp_path):
    """On dev every narration parses, so Tier 2 must find nothing to do.

    A tier that re-links already-linked credits would inflate its own apparent
    contribution and could displace a stronger identification with a weaker one.
    """
    result = pipeline.run(generated, tmp_path / "dev")
    corroborated = [e for e in result.edges if e.established_by is Tier.T2_CANDIDATE]
    assert not corroborated, "Tier 2 acted on a seed where Tier 0 had already linked"


def test_a_corroborated_edge_is_matched_not_explained(generated_eval, tmp_path):
    """Linkage is not explanation. Tier 1 still has to close the money."""
    result = pipeline.run(generated_eval, tmp_path / "matched")
    for edge in result.edges:
        if edge.established_by is Tier.T2_CANDIDATE and edge.status is EdgeStatus.EXPLAINED:
            assert edge.decomposition is not None
            assert int(edge.decomposition.residual) == 0
            assert edge.tier is Tier.T1_ARITHMETIC, (
                "an explained edge must have been closed by the arithmetic tier")


def test_corroboration_supersedes_the_alarms_it_answers(generated_eval, tmp_path):
    """A credit we have now placed is not an unreadable narration, and its
    settlement is not unconfirmed. Leaving both would double-count one event."""
    result = pipeline.run(generated_eval, tmp_path / "supersede")

    placed = {e.src_uid for e in result.edges if e.established_by is Tier.T2_CANDIDATE}
    settled = {e.dst_uid for e in result.edges if e.established_by is Tier.T2_CANDIDATE}
    codes = {(r.code, r.subject_id) for r in result.exceptions}

    for ref in placed:
        assert ("NARRATION_UNPARSEABLE", ref) not in codes
    for sid in settled:
        assert ("SETTLEMENT_UNCONFIRMED", sid) not in codes


# --- F-017: a tier may not link against what a lower tier excluded ------------

@pytest.mark.parametrize("seed", ("dev", "eval"))
def test_corroboration_never_links_a_settlement_that_never_paid_out(
        seed, generated, generated_eval, tmp_path_factory):
    """THE regression guard for F-017.

    Tier 0 reads `status` and reports a non-`processed` settlement as
    SETTLEMENT_FAILED -- the money never left. Tier 2 corroborated a credit
    against exactly such a settlement anyway and marked it explained, so one run
    asserted two contradictory things about the same settlement.

    The property, not the count: no credit may link to a settlement the report
    says did not pay out, whatever the amounts happen to be.
    """
    data_dir = generated if seed == "dev" else generated_eval
    repo = load_all(data_dir)
    result = pipeline.run(data_dir, tmp_path_factory.mktemp("f017") / seed)

    for edge in result.edges:
        if edge.kind is not EdgeKind.BANK_TO_SETTLEMENT:
            continue
        status = repo.settlements[edge.dst_uid].status
        assert status == "processed", (
            f"{edge.src_uid} was linked to {edge.dst_uid}, whose status is "
            f"'{status}' -- a settlement that never paid out is not a link target")


@pytest.mark.parametrize("seed", ("dev", "eval"))
def test_a_failed_settlement_is_never_also_double_posted(
        seed, generated, generated_eval):
    """The world has to be one that could exist.

    A duplicate posting exists BECAUSE the original landed, so a settlement whose
    transfer failed cannot also have been double-posted. Injecting both onto one
    settlement left the statement holding a duplicate of a transfer that never
    happened -- and with its genuine partner deleted, that duplicate became the
    unique (amount, date) match and got linked (F-017).

    Asserted over the generated data rather than over the injector, so it holds
    however the injection order is later rearranged.
    """
    data_dir = generated if seed == "dev" else generated_eval
    repo = load_all(data_dir)
    truth = GroundTruth.read(data_dir / "ground_truth.json")

    failed = {s.utr for s in repo.settlements.values() if s.status != "processed"}
    duplicated = {u.uid for u in truth.units if u.anomaly == "DUPLICATE_UTR"}
    for ref in duplicated:
        credit = repo.bank[ref]
        overlap = [utr for utr in failed if utr.lower() in credit.narration.lower()]
        assert not overlap, (
            f"credit {ref} duplicates a transfer for a settlement whose status is "
            "failed; that world cannot exist")


# --- C-2(a): the window replaces the exact date, and stays a window ----------

@pytest.mark.parametrize("seed", ("dev", "eval"))
def test_corroboration_never_matches_a_credit_that_predates_its_settlement(
        seed, generated, generated_eval, tmp_path_factory):
    """The window is asymmetric, and that asymmetry is load-bearing.

    A credit may post on the settlement date or after it, never before: money
    cannot arrive before the transfer that sent it was initiated. A symmetric
    +/- window would be a tolerance chosen for convenience rather than a statement
    about settlement mechanics, and it would double the candidate set for nothing.
    """
    data_dir = generated if seed == "dev" else generated_eval
    repo = load_all(data_dir)
    result = pipeline.run(data_dir, tmp_path_factory.mktemp("window") / seed)

    for edge in result.edges:
        if edge.established_by is not Tier.T2_CANDIDATE:
            continue
        credit = repo.bank[edge.src_uid]
        settlement = repo.settlements[edge.dst_uid]
        drift = (credit.value_date - settlement.created_at).days
        assert drift >= 0, (
            f"{edge.src_uid} was linked to {edge.dst_uid} but posted {-drift} days "
            "BEFORE that settlement was initiated")
        assert drift <= BANK_POSTING_WINDOW_DAYS, (
            f"{edge.src_uid} was linked {drift} days after {edge.dst_uid}, outside "
            f"the {BANK_POSTING_WINDOW_DAYS}-day posting window")


def test_corroboration_still_requires_the_amount_to_match_to_the_paise(
        generated_eval, tmp_path):
    """The window relaxed the DATE. It must not have relaxed the money.

    D-027 refuses a tolerance on an amount, because an arithmetic proof downgraded
    to a score is the anti-pattern BRIEF Sec 9 names. Shifting every credit by one
    paise must therefore take Tier 2 to zero links, not to approximate ones.
    """
    repo = load_all(generated_eval)
    for ref, credit in list(repo.bank.items()):
        repo.bank[ref] = credit.model_copy(update={"amount": credit.amount - 1})

    from recon.audit.log import AuditLog
    from recon.resolve import tier0, tier2

    audit = AuditLog(run_id="paise", rule_version="test")
    edges, exceptions = tier0.resolve(repo, audit)
    before = len([e for e in edges if e.established_by is Tier.T2_CANDIDATE])
    edges, exceptions = tier2.resolve(repo, edges, exceptions, audit)
    after = [e for e in edges if e.established_by is Tier.T2_CANDIDATE]

    assert before == 0
    assert not after, (
        f"{len(after)} credits corroborated while every amount was one paise short; "
        "the money comparison has acquired a tolerance")
