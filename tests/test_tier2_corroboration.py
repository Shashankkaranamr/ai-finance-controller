"""Tier 2: deterministic corroboration on (amount, value_date) — FIX-4 / D-027.

The audit's sharpest finding: on the held-out seed a two-field exact join
reproduces the entire dev result with no model at all, while the shipped system
reported 0% and credited an LLM with 3-5 of 22. These tests pin the behaviour
that makes the corroboration defensible rather than lucky.
"""
from __future__ import annotations

from recon.domain.graph import EdgeKind, EdgeStatus, Tier
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
