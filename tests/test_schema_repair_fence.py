"""The schema-repair fence: a proposed column mapping must be PROVEN, not trusted.

This is the second job the LLM is allowed to do, and the first one outside
narration parsing. It exists because F-018 established that a renamed column
costs the whole view and no rule can recover it -- you cannot write a regex for a
column name you have not seen.

The fence is the point, exactly as in `test_tier3_fence.py`: a hostile mapper
must be blocked completely, and a truthful one must be ACCEPTED, because a gate
that rejects everything is a wall and proves nothing.

What makes this verifier stronger than Tier 3's exact lookup is gate 3. A mapping
that swaps two fields OF THE SAME TYPE re-validates through Pydantic perfectly --
type checking cannot see it -- and is arithmetically nonsense. Only the
containment gate catches it, and it catches it on every row at once.

Every case works on a COPY in tmp_path; nothing reads the working tree
(invariant 13, F-011), and every case runs on both seeds (invariant 12).
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from recon.generate import drift
from recon.ingest.load import BANK_VIEW, LINES_VIEW, load_all
from recon.llm.client import AdjudicationRequest, AdjudicationResult, NullAdjudicator
from recon.resolve import pipeline
from recon.resolve.schema_repair import JOB_MAP_SCHEMA

SEEDS = ("dev", "eval")


def _drift(src: Path, dst: Path, view: str, old: str, new: str) -> Path:
    shutil.copytree(src, dst)
    path = dst / view
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            row[new] = row.pop(old)
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return dst


def _seed_dir(request, seed: str) -> Path:
    return request.getfixturevalue("generated" if seed == "dev" else "generated_eval")


# --- adjudicators -------------------------------------------------------------

@dataclass
class Mapper:
    """Proposes `observed -> target` as identity, with `overrides` applied.

    Built from the request payload rather than from ground truth, so it can only
    ever name columns the file actually has -- which keeps every rejection below
    attributable to the MAPPING and not to a malformed proposal.
    """

    overrides: dict[str, str] = field(default_factory=dict)
    seen: list[AdjudicationRequest] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return True

    def adjudicate(self, request: AdjudicationRequest) -> AdjudicationResult:
        self.seen.append(request)
        if request.job != JOB_MAP_SCHEMA:
            return AdjudicationResult(ok=True, data={"utr": ""})
        mapping = {c: c for c in request.payload["observed_columns"]}
        mapping.update(self.overrides)
        return AdjudicationResult(ok=True, data={"mapping": mapping},
                                  rationale="proposed by test double")


def _truthful_lines() -> Mapper:
    return Mapper(overrides={"entity_ref": "entity_id"})


def _fee_tax_swapped() -> Mapper:
    """Plausible, type-correct, and arithmetically nonsense.

    `fee` and `tax` are both `int >= 0`, so Pydantic accepts the swap without a
    murmur. Only containment can tell: `fee` is INCLUSIVE of tax, so tax > fee is
    not a wrong rate, it is a column that is no longer what it claims to be.
    """
    return Mapper(overrides={"entity_ref": "entity_id", "fee": "tax", "tax": "fee"})


# --- the fence ----------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_a_truthful_mapping_is_accepted_so_the_fence_is_not_a_wall(request, tmp_path, seed):
    """The control. A verifier that rejects everything proves nothing."""
    data = _drift(_seed_dir(request, seed), tmp_path / f"t_{seed}",
                  LINES_VIEW, "entity_id", "entity_ref")
    mapper = _truthful_lines()
    result = pipeline.run(data, tmp_path / f"out_t_{seed}", adjudicator=mapper)

    assert mapper.seen, "the fence was never exercised -- no mapping was proposed"
    assert result.llm.blocked_bad_mapping == 0
    assert not result.repo.quarantined, "a correct mapping did not recover the view"
    assert result.repo.lines, "rows were accepted but never installed"
    assert not [r for r in result.exceptions if r.code == "SOURCE_VIEW_INCOMPLETE"]
    assert result.statement.foots


@pytest.mark.parametrize("seed", SEEDS)
def test_a_type_correct_but_nonsense_mapping_is_blocked(request, tmp_path, seed):
    """THE assertion of this increment.

    Swapping fee and tax passes every structural check and every type check. If
    the identity gate were absent this mapping would be accepted, the rows would
    install, and the run would report reconciled money computed from a scrambled
    fee column -- a silent corruption, which is worse than the quarantine it
    replaced.
    """
    data = _drift(_seed_dir(request, seed), tmp_path / f"h_{seed}",
                  LINES_VIEW, "entity_id", "entity_ref")
    mapper = _fee_tax_swapped()
    result = pipeline.run(data, tmp_path / f"out_h_{seed}", adjudicator=mapper)

    assert result.llm.blocked_bad_mapping == 1
    assert result.repo.quarantined, "a rejected mapping must leave the rows quarantined"
    assert not result.repo.lines, "rejected rows must not reach the repository"
    assert [r for r in result.exceptions if r.code == "SOURCE_VIEW_INCOMPLETE"], (
        "a blocked repair must still be reported as an incomplete view")
    assert result.statement.foots


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("overrides,gate", [
    ({"entity_ref": "not_a_real_field"}, "structural:invented_fields"),
    ({"entity_ref": "settlement_id"}, "structural:not_injective"),
    ({}, "structural:required_fields_unmapped"),
])
def test_structurally_impossible_mappings_are_blocked(request, tmp_path, seed,
                                                      overrides, gate):
    """Gate 1 is the analogue of `_is_faithful_reading`: the model may not invent
    a field name any more than it may invent a UTR. The no-override case is the
    model simply failing to notice the renamed column."""
    slug = gate.replace(":", "_")
    data = _drift(_seed_dir(request, seed), tmp_path / f"s_{seed}_{slug}",
                  LINES_VIEW, "entity_id", "entity_ref")
    result = pipeline.run(data, tmp_path / f"out_s_{seed}_{slug}",
                          adjudicator=Mapper(overrides=overrides))

    assert result.llm.blocked_bad_mapping == 1
    assert result.repo.quarantined
    assert not result.repo.lines


def _duplicate_one_narration(data: Path, column: str) -> Path:
    """Make two credits share a narration, as they do at realistic volume.

    The 88-day seeds carry 23 credits and 22 distinct narrations on both dev and
    eval. The 24-day test fixture carries 7 and 7. Gate 4 turns on exactly that
    difference, so a test of gate 4 has to supply it rather than hope for it.
    """
    path = data / BANK_VIEW
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[1][column] = rows[0][column]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return data


@pytest.mark.parametrize("seed", SEEDS)
def test_a_mapping_that_collapses_the_primary_key_is_blocked(request, tmp_path, seed):
    """Gate 4. `bank_ref` and `narration` are both unconstrained strings, so a swap
    re-validates cleanly and satisfies every containment -- the bank view has none.
    What catches it is that a primary key must be UNIQUE, and narrations repeat."""
    data = _drift(_seed_dir(request, seed), tmp_path / f"u_{seed}",
                  BANK_VIEW, "narration", "description")
    _duplicate_one_narration(data, "description")   # already renamed by _drift
    result = pipeline.run(data, tmp_path / f"out_u_{seed}",
                          adjudicator=Mapper(overrides={"description": "bank_ref",
                                                        "bank_ref": "narration"}))

    assert result.llm.blocked_bad_mapping == 1
    assert not result.repo.bank
    # And the F-018 guard still holds behind it: no false missing-money claim.
    assert not [r for r in result.exceptions if r.code == "MISSING_BANK_CREDIT"]


@pytest.mark.parametrize("seed", SEEDS)
def test_the_limit_of_gate_4_is_asserted_rather_than_assumed(request, tmp_path, seed):
    """THE HOLE, PINNED SO IT CANNOT QUIETLY STOP BEING BELIEVED.

    Gate 4 is data-dependent. Where every narration is distinct -- which the small
    fixture is, and a real statement can be -- swapping two unconstrained string
    columns collapses no key, breaks no containment, and **passes**.

    There is no exact fix: nothing in the schema constrains the shape of a
    `bank_ref`, and inventing a format rule would encode our generator's `bc_<crc>`
    convention, which no real bank shares. This test exists so the limit is a
    measured property of the system rather than a sentence in a docstring.
    """
    data = _drift(_seed_dir(request, seed), tmp_path / f"lim_{seed}",
                  BANK_VIEW, "narration", "description")
    rows = [json.loads(line) for line in
            (data / BANK_VIEW).read_text(encoding="utf-8").splitlines() if line.strip()]
    narrations = [r["description"] for r in rows]
    assert len(set(narrations)) == len(narrations), (
        "this fixture is supposed to have all-distinct narrations")

    result = pipeline.run(data, tmp_path / f"out_lim_{seed}",
                          adjudicator=Mapper(overrides={"description": "bank_ref",
                                                        "bank_ref": "narration"}))

    assert result.llm.blocked_bad_mapping == 0, (
        "if this now BLOCKS, gate 4 got stronger -- good; update the docstring and "
        "this test rather than leaving the limit documented as still present")
    assert result.repo.bank, "the swapped mapping was accepted, which is the limit"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_adjudicator_is_never_shown_the_arithmetic(request, tmp_path, seed):
    """A model told what would make an answer verify can write to the test.

    It sees the column names, the target field names, and ONE row. Not the
    identities, not the rate card, not ground truth.
    """
    data = _drift(_seed_dir(request, seed), tmp_path / f"p_{seed}",
                  LINES_VIEW, "entity_id", "entity_ref")
    mapper = _truthful_lines()
    pipeline.run(data, tmp_path / f"out_p_{seed}", adjudicator=mapper)

    proposals = [r for r in mapper.seen if r.job == JOB_MAP_SCHEMA]
    assert proposals, "no mapping was requested"
    for request_seen in proposals:
        assert set(request_seen.payload) == {"observed_columns", "target_fields",
                                             "sample_row"}


@pytest.mark.parametrize("seed", SEEDS)
def test_repair_never_runs_on_a_clean_view(request, tmp_path, seed):
    """It must cost nothing when nothing is wrong. No quarantine, no call."""
    mapper = Mapper()
    pipeline.run(_seed_dir(request, seed), tmp_path / f"c_{seed}", adjudicator=mapper)

    assert not [r for r in mapper.seen if r.job == JOB_MAP_SCHEMA]


@pytest.mark.parametrize("seed", SEEDS)
def test_rules_only_leaves_a_drifted_view_quarantined_and_honest(request, tmp_path, seed):
    """Degraded mode (Sec 8): with no adjudicator the batch still completes, the
    view stays quarantined, and the run claims nothing it cannot support. This is
    the rules-only half of the ablation."""
    data = _drift(_seed_dir(request, seed), tmp_path / f"n_{seed}",
                  BANK_VIEW, "narration", "description")
    result = pipeline.run(data, tmp_path / f"out_n_{seed}", adjudicator=NullAdjudicator())

    assert result.llm.degraded
    assert result.llm.blocked_bad_mapping == 0
    assert result.repo.quarantined
    assert not [r for r in result.exceptions if r.code == "MISSING_BANK_CREDIT"]
    assert [r for r in result.exceptions if r.code == "SOURCE_VIEW_INCOMPLETE"]
    assert result.statement.foots


# --- the two containments added by F-021's fix -------------------------------
#
# Both of these swaps were ACCEPTED by the live model on 03 Sep and accepted by the
# fence behind it. They are the regression, and they use the pre-registered
# scenario registry rather than a hand-rolled drift so the shapes cannot drift
# apart from the ones that were actually measured.

@pytest.mark.parametrize("seed", SEEDS)
def test_a_credit_debit_inversion_is_blocked_by_the_asymmetric_sign_rule(
        request, tmp_path, seed):
    """F-021, S7. The symmetric rule `not (credit > 0 and debit > 0)` is preserved
    BY the swap -- a payment goes from credit>0/debit=0 to credit=0/debit>0 and
    still has exactly one non-zero side. Only asking WHICH side, via `type`,
    separates them."""
    scenario = drift.BY_NAME["S7_lines_credit_debit"]
    data = drift.apply(scenario, _seed_dir(request, seed), tmp_path / f"s7_{seed}")
    result = pipeline.run(data, tmp_path / f"out_s7_{seed}",
                          adjudicator=Mapper(overrides={"credit_amount": "credit",
                                                        "debit_amount": "debit"}))

    assert result.llm.blocked_bad_mapping == 1
    assert not result.repo.lines, "an inverted ledger reached the repository"

    # A blocked repair must leave the run EXACTLY where no adjudicator would have.
    # Asserting false_clear == 0 here would be wrong: with the view still
    # quarantined it is legitimately high, because nothing was read. What must not
    # happen is the accepted-wrong outcome, where the view loads INVERTED and four
    # real breaks are reported clean.
    rules_only = pipeline.run(data, tmp_path / f"out_s7_null_{seed}",
                              adjudicator=NullAdjudicator())
    assert (result.metrics.false_clear_in_remit.numerator
            == rules_only.metrics.false_clear_in_remit.numerator)
    assert (result.metrics.explanation_rate_bank.numerator
            == rules_only.metrics.explanation_rate_bank.numerator)


@pytest.mark.parametrize("seed", SEEDS)
def test_an_amount_fees_inversion_is_blocked_by_the_line_item_second_opinion(
        request, tmp_path, seed):
    """F-021, S9 -- predicted in writing before the run and still not caught.

    `tax <= fees` passes comfortably once a lakh-sized value sits in `fees`. The
    second opinion has to come from the other view: `fees` must equal the summed
    line-item fees, and those two sides are independently sourced (D-003).
    """
    scenario = drift.BY_NAME["S9_settlements_swap"]
    data = drift.apply(scenario, _seed_dir(request, seed), tmp_path / f"s9_{seed}")
    result = pipeline.run(data, tmp_path / f"out_s9_{seed}",
                          adjudicator=Mapper(overrides={"ref": "id"}))

    assert result.llm.blocked_bad_mapping == 1
    assert not result.repo.settlements


@pytest.mark.parametrize("seed", SEEDS)
def test_the_correct_mapping_for_both_is_still_accepted(request, tmp_path, seed):
    """The control, and the one that matters most after tightening a gate: a
    stricter fence that also rejects right answers is a wall."""
    for name in ("S7_lines_credit_debit", "S9_settlements_swap"):
        scenario = drift.BY_NAME[name]
        src = _seed_dir(request, seed)
        data = drift.apply(scenario, src, tmp_path / f"ok_{name}_{seed}")
        truth = drift.truth_mapping(scenario, src)
        result = pipeline.run(data, tmp_path / f"out_ok_{name}_{seed}",
                              adjudicator=Mapper(overrides=truth))

        assert result.llm.blocked_bad_mapping == 0, f"{name}: correct mapping rejected"
        assert not result.repo.quarantined, f"{name}: correct mapping did not recover"


# --- gate 5: referential integrity (F-022) -----------------------------------
#
# Gates 1-4 are all assertions about ROWS. This is the first about the EDGES
# between them, and the swap below passes every one of the other four.

@pytest.mark.parametrize("seed", SEEDS)
def test_a_foreign_key_swap_is_blocked_by_referential_integrity(request, tmp_path, seed):
    """F-022. `order_id` and `payment_id` are both `str | None`, so exchanging them
    re-validates (gate 2), touches no money column (gate 3), leaves `entity_id`
    unique (gate 4) and names only real fields (gate 1).

    Unblocked, this took detection recall to 58.29% on eval and put 78 real breaks
    through as clean, while blocked_bad_mapping stayed 0, the statement footed,
    degraded stayed false and linkage precision read 100.00%.
    """
    scenario = drift.BY_NAME["R1_lines_fk_swap"]
    data = drift.apply(scenario, _seed_dir(request, seed), tmp_path / f"fk_{seed}")
    result = pipeline.run(data, tmp_path / f"out_fk_{seed}",
                          adjudicator=Mapper(overrides={"payment_ref": "payment_id",
                                                        "order_ref": "order_id"}))

    assert result.llm.blocked_bad_mapping == 1
    assert not result.repo.lines, "a view with inverted foreign keys was installed"

    # As with F-021: a blocked repair must land exactly where no adjudicator would.
    # False clear is legitimately high with the view still quarantined -- what must
    # not happen is the view loading with its keys crossed.
    rules_only = pipeline.run(data, tmp_path / f"out_fk_null_{seed}",
                              adjudicator=NullAdjudicator())
    assert (result.metrics.false_clear_in_remit.numerator
            == rules_only.metrics.false_clear_in_remit.numerator)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_correct_fk_mapping_is_still_accepted_and_restores_the_run(
        request, tmp_path, seed):
    """The control for gate 5. A gate that blocks everything is a wall.

    Stronger than "accepted": the repaired run must return detection recall to
    100% and in-remit false clear to zero, which is the property gate 5 exists to
    protect and the one the swap destroyed.
    """
    scenario = drift.BY_NAME["R1_lines_fk_swap"]
    src = _seed_dir(request, seed)
    data = drift.apply(scenario, src, tmp_path / f"fkok_{seed}")
    result = pipeline.run(data, tmp_path / f"out_fkok_{seed}",
                          adjudicator=Mapper(overrides=drift.truth_mapping(scenario, src)))

    assert result.llm.blocked_bad_mapping == 0, "gate 5 rejected a correct mapping"
    assert not result.repo.quarantined
    assert result.metrics.false_clear_in_remit.numerator == 0
    assert (result.metrics.exception_detection_recall.numerator
            == result.metrics.exception_detection_recall.denominator)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_clean_data_rates_gate_5_assumes_are_still_true(request, tmp_path, seed):
    """The threshold is only safe because of what clean data measures.

    `order_id -> books` and `settlement_id -> settlements` are 100% on both seeds,
    so a 90% floor carries ten points of margin. If a generator change ever drops
    them, this fails loudly instead of the gate quietly becoming unreachable.
    """
    repo = load_all(_seed_dir(request, seed))
    payments = [r for r in repo.lines.values()
                if r.type == "payment" and r.order_id is not None]
    assert payments
    assert all(r.order_id in repo.books for r in payments), (
        "order_id -> books is no longer 100% on clean data; re-derive the floor")
    assert all(r.settlement_id in repo.settlements for r in repo.lines.values())


@pytest.mark.parametrize("seed", SEEDS)
def test_gate_5_deliberately_does_not_police_payment_id(request, tmp_path, seed):
    """THE LIMIT, ASSERTED SO IT CANNOT BE BELIEVED AWAY.

    `refund.payment_id -> payments` measures 89.53% on dev and 90.43% on eval,
    because REFUND_ORPHANED is the declared blind spot -- nine per seed, injected
    on purpose. At a 90% floor dev's own CLEAN data would be rejected, so gating it
    would reject a correct mapping because the source contains the anomaly the
    system exists to find. That is the mistake the GST rate made in gate 3.
    """
    repo = load_all(_seed_dir(request, seed))
    refunds = [r for r in repo.lines.values() if r.type == "refund" and r.payment_id]
    index = repo.payments_by_payment_id()
    resolved = sum(1 for r in refunds if r.payment_id in index)
    assert resolved < len(refunds), (
        "payment_id now resolves for every refund; the blind spot is gone and this "
        "exclusion should be revisited")
    assert resolved * 10_000 // len(refunds) < 10_000
