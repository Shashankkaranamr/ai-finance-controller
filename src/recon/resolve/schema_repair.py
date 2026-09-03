"""Schema repair -- the LLM's second job, and the only one outside narration.

WHY THIS IS A DEFENSIBLE PLACE FOR A MODEL, WHEN TIER 2 WAS NOT
---------------------------------------------------------------
D-016 cut every proposed LLM job because arithmetic already closed the loop, and
inventing work for a model is the Sec 9 anti-pattern. That reasoning was about
the MIDDLE of the system -- matching and computing -- and it has not changed.
Nothing here touches either.

This is the boundary. `extra="forbid"` means a renamed column fails every row of
a view identically (F-018), and no rule can recover it: you cannot write a regex
for a column name you have not seen. The realistic alternatives are an engineer
shipping a mapping every time a bank changes a header, or the system proposing
one and PROVING it. There is no deterministic third option, and that is what
makes this different from every job D-016 declined.

THE FENCE, WHICH IS STRONGER HERE THAN IN TIER 3
-------------------------------------------------
Tier 3 verifies a proposed UTR by exact lookup: it resolves or it does not. Here
the proposal is a mapping, and it must survive five gates, all exact:

  1. STRUCTURAL -- every target is a real field on the model and every source is a
     column actually present in the file; the mapping is injective and covers
     every required field. This is the analogue of `_is_faithful_reading`: the
     model may not invent a field name any more than it may invent a UTR.
  2. TOTAL RE-VALIDATION -- EVERY quarantined row of that view must re-validate
     through the same Pydantic model, `extra="forbid"` still enforced. Not most.
     One row short and the mapping is rejected, because a mapping that works for
     some rows is a mapping we do not understand.
  3. CONTAINMENT -- the structural facts a column must satisfy to still BE that
     column (tax <= fee, fee <= amount, the side of the ledger its `type` moves,
     ...). This catches the dangerous case gate 2 cannot: two fields of the SAME
     TYPE swapped, which re-validates perfectly and is arithmetically nonsense.
     See `_identity_holds` for why this is containment and deliberately NOT the
     GST rate, and why the sign rule had to become asymmetric (F-021).
  4. IDENTITY -- the column mapped to the view's primary key must actually be
     unique. Catches a `bank_ref`/`narration` swap when a narration repeats, which
     it does on realistic volumes. DATA-DEPENDENT, not exact -- see `_is_useful`.
  5. REFERENTIAL -- every foreign key must still land on a real row, at the rate
     clean data does. Gates 1-4 are all about ROWS; this is the first one about
     the EDGES between them, and an `order_id`/`payment_id` swap passes all four
     of them while 78 real breaks vanish. See `_foreign_keys_resolve`.

Gate 3's strength VARIES BY VIEW, and claiming otherwise would overstate the
fence:

  settlement_lines   strongest: four independent containments, and a fee/tax swap
                     breaks them on every fee-bearing row at once.
  settlements        two: fee/tax containment, plus `fees` against the summed
                     line-item fees -- an independently sourced second opinion,
                     because `amount` is signed and cannot be bounded in-row.
  bank               no money identity at all: a credit is one number. Gate 4
                     carries this view instead.
  books              none. Gates 1, 2 and 4 only, stated rather than papered over.

Gate 4 applies to ALL FOUR views, which it did not before 03 Sep -- it asked the
bank view alone whether a UTR resolved, and that made it a test of our regex
rather than of the mapping. See `_is_useful`.

WHAT IS NEVER SENT
------------------
The payload is the observed column names, ONE sample row, and the target field
names. Not the identities, not the arithmetic, not ground truth. The model is
told what the columns are called; it is never told what would make an answer
verify, because a model that knows the test can write to the test.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..audit.log import AuditLog
from ..ingest.load import (BANK_VIEW, BOOKS_VIEW, LINES_VIEW, SETTLEMENTS_VIEW,
                           QuarantinedRow, Repository)
from ..ingest.schemas import (BankCreditRow, BookEntryRow, SettlementLineRow,
                              SettlementRow)
from ..llm.client import (JOB_MAP_SCHEMA, AdjudicationRequest, Adjudicator,
                         LLMStats, ResponseCache)

# Re-exported from the seam so existing importers keep working.
__all__ = ["repair", "JOB_MAP_SCHEMA"]

MODEL_FOR_VIEW = {
    BOOKS_VIEW: BookEntryRow,
    LINES_VIEW: SettlementLineRow,
    SETTLEMENTS_VIEW: SettlementRow,
    BANK_VIEW: BankCreditRow,
}


def _required_fields(model) -> set[str]:
    return {name for name, spec in model.model_fields.items() if spec.is_required()}


# Which side of the ledger each line type moves. `None` means both are legitimate
# and nothing can be asserted -- an adjustment withholds a reserve as a debit and
# releases it as a credit, so a rule here would reject correct data.
SIDE_FOR_TYPE: dict[str, str | None] = {
    "payment": "credit",
    "refund": "debit",
    "transfer": "debit",
    "adjustment": None,
}


def _moves_the_right_way(row) -> bool:
    """A line of this `type` may not move money in the other direction.

    Zero on both sides is allowed and is not a swap tell: an on-hold payment is
    captured and never settled, so it moves nothing (48 dev / 58 eval rows).
    """
    side = SIDE_FOR_TYPE.get(row.type)
    if side is None:
        return True
    return row.debit == 0 if side == "credit" else row.credit == 0


# Gate 5's floor, in integer basis points -- 9000 == 90.00%. A rate, not a count,
# because the denominator moves with the extract; integer bps because this package
# is float-free by property, not by style (invariant 1).
FK_RESOLUTION_FLOOR_BPS = 9000


def _foreign_keys_resolve(view: str, rows: list, repo: Repository) -> str | None:
    """Gate 5: a foreign key must still land on a real row. Returns the broken one.

    WHY GATES 1-4 CANNOT SEE THIS, AND WHY IT IS F-018 ONE LAYER DOWN
    ------------------------------------------------------------------
    `order_id` and `payment_id` are both `str | None`, so exchanging them
    re-validates perfectly (gate 2), touches no money column (gate 3), leaves
    `entity_id` unique (gate 4), and names only real fields (gate 1). Every gate
    passes. Measured on the swap a live model actually proposed:

        eval   detection recall 187/187 -> 109/187 (58.29%)   false clear 0 -> 78/187
        dev    detection recall 195/195 -> 116/195 (59.49%)   false clear 0 -> 79/195

    while `blocked_bad_mapping` stayed 0, the statement footed, `degraded` stayed
    false and linkage precision read 100.00%. **Every safety signal we publish read
    clean while 78 real breaks disappeared**, because precision only asks whether
    the links we made were right -- not whether the links we should have made were
    ever attempted.

    F-018 said an absence is only evidence when the VIEW loaded completely. This is
    the same sentence one level down: a foreign key can resolve to the wrong row
    while every row-level completeness signal reads clean. Rows are not enough;
    the edges between them have to be checked too.

    THE THRESHOLD, AND WHY IT IS NOT 100%
    --------------------------------------
    Same pattern as `settlements.fees` against summed line-item fees (D-003): the
    second opinion comes from the OTHER VIEW, independently sourced. Measured clean
    rates, both seeds:

        payment.order_id   -> books         100.00% / 100.00%
        line.settlement_id -> settlements   100.00% / 100.00%
        refund.payment_id  -> payments       89.53% /  90.43%   <- EXCLUDED

    **`payment_id` is deliberately not gated.** Its clean rate is intrinsically
    below 100% because `REFUND_ORPHANED` is the declared blind spot -- nine per
    seed, injected on purpose -- and at a 90% floor dev's own clean data (89.53%)
    would be REJECTED. Gating it would reject a correct mapping because the source
    contains the anomaly the system exists to find, which is exactly the mistake
    the GST rate made in gate 3. The floor sits at 90% for the two keys that
    measure 100% clean, so it carries ten points of margin and still catches a
    swap, which drives resolution to essentially zero.

    WHAT THIS GATE DOES NOT CATCH, STATED RATHER THAN IMPLIED AWAY
    ---------------------------------------------------------------
    * A swap between two columns that BOTH resolve -- `order_id` against
      `order_receipt`, say, if receipts were also book keys. Nothing here compares
      a key to the *right* target, only to *a* target.
    * Any drift on `payment_id`, for the reason above.
    * Anything at all when the referenced view is itself missing: the check is
      skipped, because a check that cannot run has not passed (F-018's rule).
    """
    if view != LINES_VIEW:
        return None

    if repo.books:
        payments = [r for r in rows if r.type == "payment" and r.order_id is not None]
        if payments:
            hits = sum(1 for r in payments if r.order_id in repo.books)
            if hits * 10_000 // len(payments) < FK_RESOLUTION_FLOOR_BPS:
                return f"order_id->books {hits}/{len(payments)}"

    if repo.settlements:
        hits = sum(1 for r in rows if r.settlement_id in repo.settlements)
        if rows and hits * 10_000 // len(rows) < FK_RESOLUTION_FLOOR_BPS:
            return f"settlement_id->settlements {hits}/{len(rows)}"
    return None


def _identity_holds(view: str, rows: list, repo: Repository) -> bool:
    """Gate 3: CONTAINMENT, deliberately not the GST rate.

    THE DISTINCTION THIS GATE TURNS ON, WHICH COST A REWRITE TO SEE
    ---------------------------------------------------------------
    The obvious check is `gst_on_mdr_holds` -- tax is 18% of the MDR base. It is
    the wrong one, and measuring said so immediately: it fails on 17 of 890
    fee-bearing dev rows and 13 of 885 on eval, because GST_ON_MDR_MISMATCH is a
    real anomaly the generator injects on purpose. Gating on it rejects a CORRECT
    mapping because the source data contains a defect the system exists to find,
    which is the worst possible direction to be wrong in: it would make the repair
    fail precisely on the merchants who need it.

    So the gate asks a different question -- not "was the right rate charged",
    which is Tier 1's job and may legitimately be no, but "is this column still
    the thing it claims to be". These are structural facts about the schema that
    hold no matter what the gateway got wrong:

        fee <= amount     a fee is charged ON the amount
        tax <= fee        `fee` is INCLUSIVE of tax (schemas.py says so)
        amount > 0        every line moves something
        not (credit > 0 and debit > 0)    a line moves money one way

    Measured across both seeds: every one holds on 100% of rows, while a single
    fee/tax swap breaks containment on ALL 890 (dev) and 885 (eval) fee-bearing
    rows at once. Exact, total, and blind to whether the money itself was right.

    WHY THE SIGN RULE IS ASYMMETRIC, AND WHY THE SYMMETRIC ONE WAS NOT ENOUGH
    -------------------------------------------------------------------------
    `not (credit > 0 and debit > 0)` is true and useless against the swap it looks
    like it should catch. A payment has credit > 0, debit = 0; exchange the two
    columns and it has credit = 0, debit > 0 -- still exactly one non-zero side.
    **The invariant is preserved by the very swap it exists to catch**, and a
    live model's credit/debit inversion was accepted because of it (F-021).

    The fix is to ask WHICH side, not how many. `type` already says, and the gate
    never consulted it. Measured over both seeds:

        payment    credit 1511/1556, both-zero 48/58, debit NEVER
        refund     debit 86/94, always
        transfer   debit 29/29, always
        adjustment debit 48/42 AND credit 10/10  -- both are legitimate

    So three of the four types pin a direction and `adjustment` pins none -- a
    reserve is withheld as a debit and released as a credit, and constraining it
    would reject correct data. Stated rather than smoothed over: this gate covers
    the types that carry a direction, which on this data is ~96% of rows, and a
    swap confined entirely to adjustment lines would pass.

    Returns True when the view carries no such invariant -- an ABSENT check, not a
    pass we did not earn. The caller records which gate ran.
    """
    if view == LINES_VIEW:
        return all(r.tax <= r.fee and r.fee <= r.amount and r.amount > 0
                   and not (r.credit > 0 and r.debit > 0)
                   and _moves_the_right_way(r)
                   for r in rows)
    if view == SETTLEMENTS_VIEW:
        # `amount` is signed here -- a heavy-refund cycle settles negative -- so it
        # cannot be bounded from inside the row. That left ONE containment,
        # `tax <= fees`, and a lakh-sized value dropped into `fees` satisfies it
        # comfortably: exactly how a live amount/fees inversion was accepted
        # (F-021, S9, predicted in writing and still not caught).
        #
        # The second opinion comes from the OTHER VIEW. `fees` must equal the sum
        # of the line items' fees, and those two sides are independently sourced
        # (D-003) -- settlements.jsonl reports the total, settlement_lines.jsonl
        # carries the parts. Measured: 22/22 exact on both seeds, and an inverted
        # `fees` misses by three orders of magnitude.
        if not all(r.tax <= r.fees for r in rows):
            return False
        return _fees_agree_with_line_items(rows, repo)
    return True


def _fees_agree_with_line_items(rows: list, repo: Repository) -> bool:
    """`settlements.fees` against the sum of that settlement's line-item fees.

    Skipped for any settlement whose lines are not present. That is not
    leniency -- it is the same rule as everywhere else here: a check that cannot
    be run has not passed, and asserting on rows we do not have would be the
    absence-as-evidence error F-018 was about. When the line view itself is the
    one being repaired, this contributes nothing and `tax <= fees` stands alone.
    """
    by_settlement = repo.lines_by_settlement()
    if not by_settlement:
        return True
    for row in rows:
        members = by_settlement.get(row.id)
        if not members:
            continue
        if row.fees != sum(int(m.fee) for m in members):
            return False
    return True


# Every view has exactly one column that IDENTIFIES its rows -- the field the
# repository keys its dict on. If a mapping sends the wrong column there, the view
# stops being addressable and rows silently overwrite each other.
IDENTITY_FIELD = {
    BOOKS_VIEW: "order_id",
    LINES_VIEW: "entity_id",
    SETTLEMENTS_VIEW: "id",
    BANK_VIEW: "bank_ref",
}


def _is_useful(view: str, rows: list) -> bool:
    """Gate 4: the column mapped to the identity field must actually identify.

    WHAT THIS ASKED BEFORE, AND WHY IT WAS WRONG
    ---------------------------------------------
    It used to require that some repaired bank narration parse to a UTR resolving
    to a known settlement. That is not a property of the MAPPING -- it is a
    property of whether our regex can read this seed's narration families, which
    is the exact gap Tier 3 exists for. Measured: dev parses 23 of 23 and 21
    resolve, so the gate waved everything through; **eval parses 2 of 23 and 0
    resolve, so it blocked every bank mapping however correct it was.**

    Strictest on the held-out seed, for a reason that has nothing to do with the
    answer. Found by the stub harness on 03 Sep before any live call, which is the
    only reason it did not become 2 of 10 published scenarios scored as fence
    rejections of a right answer.

    A primary key must be unique. That is a real invariant, it is checkable
    exactly, and it applies to all four views rather than one -- so it is a
    straight improvement on what it replaces.

    WHAT IT DOES NOT DO, STATED RATHER THAN ASSUMED
    ------------------------------------------------
    It is DATA-DEPENDENT, not exact, and the difference matters. It catches a
    `bank_ref`/`narration` swap only when some narration REPEATS, because that is
    what collapses the key. Measured:

        dev  88d: 23 credits, 22 distinct narrations -> swap CAUGHT
        eval 88d: 23 credits, 22 distinct narrations -> swap CAUGHT
        dev  24d:  7 credits,  7 distinct narrations -> swap MISSED
        eval 24d:  7 credits,  7 distinct narrations -> swap MISSED

    On a statement where every narration happens to be unique, a swap of two
    unconstrained string columns passes every gate this module has. That is a real
    hole and there is no exact fix available: nothing in the schema constrains the
    SHAPE of a `bank_ref`, and inventing a format rule would encode our generator's
    `bc_<crc>` convention, which no real bank shares -- fitting the fence to our own
    synthetic data, which is the Sec 9 anti-pattern one level down.

    So the honest statement of this view's fence is: gates 1 and 2, plus a
    uniqueness check that is decisive on realistic volumes and silent on tiny ones.
    `tests/test_schema_repair_fence.py` asserts BOTH halves, so the limit cannot
    quietly stop being believed.
    """
    field = IDENTITY_FIELD.get(view)
    if field is None:
        return True
    values = [getattr(row, field) for row in rows]
    return len(set(values)) == len(values)


def _reread(data_dir: Path, view: str, bad: list[QuarantinedRow]) -> list[dict] | None:
    """Re-read the quarantined rows from the source file, by line number.

    NOT from `QuarantinedRow.raw`, which is truncated to 200 characters because it
    is a diagnostic excerpt destined for the audit log -- not data. A settlement
    line is several times that, so repairing from it would have silently worked
    for the bank view and been impossible for the two largest ones. Reading the
    file back is the only way to get the row intact.

    Returns None if anything is not a JSON object, which means the problem is not
    schema drift and a column mapping cannot fix it.
    """
    wanted = {row.line_no for row in bad}
    rows: list[dict] = []
    # `joinpath`, not `/`: pathlib overloads the operator and it parses as
    # ast.Div, which the float scan bans (D-006, F-003). One call does not
    # justify adding this module to that exclusion list -- new modules stay
    # strict by default, which is the whole point of the list being a list.
    with data_dir.joinpath(view).open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if line_no not in wanted:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return None
            if not isinstance(parsed, dict):
                return None
            rows.append(parsed)
    return rows


def repair(data_dir: Path, repo: Repository, adjudicator: Adjudicator,
           cache: ResponseCache, stats: LLMStats, audit: AuditLog) -> Repository:
    """Ask the adjudicator to map unrecognised columns, and verify before using.

    Runs BEFORE Tier 0, because Tier 0's completeness gate reads the quarantine
    (F-018). A repaired row is then indistinguishable from one that loaded
    normally, which is the point: every tier downstream behaves exactly as it
    would have on clean input, and nothing else in the pipeline knows this ran.
    """
    if not adjudicator.available or not repo.quarantined:
        return repo

    by_file: dict[str, list[QuarantinedRow]] = {}
    for row in repo.quarantined:
        by_file.setdefault(row.source_file, []).append(row)

    for view in sorted(by_file):
        model = MODEL_FOR_VIEW.get(view)
        if model is None:
            continue

        samples = _reread(data_dir, view, by_file[view])
        if not samples:
            audit.record("map_schema_skipped", source_file=view,
                         reason="rows are not parseable JSON objects")
            continue

        observed = sorted({key for row in samples for key in row})
        request = AdjudicationRequest(
            job=JOB_MAP_SCHEMA,
            subject_ref=f"source_view:{view}",
            payload={"observed_columns": observed,
                     "target_fields": sorted(model.model_fields),
                     "sample_row": samples[0]},
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
            audit.record("map_schema_declined", source_file=view,
                         reason=result.reason_unavailable[:120])
            continue

        mapping = result.data.get("mapping")
        failed_gate = _verify(view, model, mapping, samples, observed, repo)
        if failed_gate is not None:
            stats.blocked_bad_mapping += 1
            audit.record("blocked_bad_mapping", source_file=view, gate=failed_gate,
                         mapping=_render(mapping), rationale=result.rationale[:160])
            continue

        repaired = [model.model_validate({mapping[k]: v for k, v in row.items()})
                    for row in samples]
        _install(repo, view, repaired)
        repo.quarantined = [q for q in repo.quarantined if q.source_file != view]
        audit.record("map_schema_accepted", source_file=view,
                     rows_recovered=len(repaired), mapping=_render(mapping),
                     rationale=result.rationale[:160])

    return repo


def _verify(view, model, mapping, samples, observed, repo) -> str | None:
    """Run the four gates in order. Returns the gate that failed, or None.

    Named rather than boolean: `blocked_bad_mapping` is a number we intend to
    publish, and a rejection that cannot say WHICH gate caught it is a number
    nobody can act on.
    """
    # --- gate 1: structural ---------------------------------------------------
    if not isinstance(mapping, dict) or not mapping:
        return "structural:not_a_mapping"
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        return "structural:non_string_entry"
    if set(mapping) != set(observed):
        return "structural:does_not_cover_observed_columns"
    if len(set(mapping.values())) != len(mapping):
        return "structural:not_injective"
    invented = set(mapping.values()) - set(model.model_fields)
    if invented:
        return f"structural:invented_fields:{','.join(sorted(invented))}"
    if not _required_fields(model) <= set(mapping.values()):
        return "structural:required_fields_unmapped"

    # --- gate 2: total re-validation ------------------------------------------
    repaired = []
    for row in samples:
        try:
            repaired.append(model.model_validate({mapping[k]: v for k, v in row.items()}))
        except Exception:
            return "revalidation:row_rejected"

    # --- gate 3: identity -----------------------------------------------------
    if not _identity_holds(view, repaired, repo):
        return "identity:sec_3_2_violated"

    # --- gate 4: utility ------------------------------------------------------
    if not _is_useful(view, repaired):
        return "utility:view_serves_no_join"

    # --- gate 5: referential integrity ----------------------------------------
    broken = _foreign_keys_resolve(view, repaired, repo)
    if broken is not None:
        return f"referential:{broken}"
    return None


def _render(mapping) -> str:
    """The mapping as it goes into the audit log. A well-formed one is NOT truncated.

    It used to cut every mapping at 200 characters, which is about eight of the
    twenty-six entries a `settlement_lines` mapping carries. That made the audit
    record unreplayable: `map_schema_accepted` named the view and the row count,
    and then showed a prefix of the decision it was recording. Reconstructing what
    the model actually proposed meant re-running it and hoping for the same sample.

    An append-only decision log exists so a decision can be re-derived from it
    alone (INVARIANT: `audit/log.py`, run_id as the idempotency key). A record that
    holds part of the decision does not meet that bar, and the field it truncates
    is the only part a replay needs.

    A NON-dict is still bounded, and the asymmetry is deliberate. A dict has
    already passed `json.loads` and gate 1, so its size is set by the schema --
    bounded by construction. Anything else is a malformed model response of
    unknown length arriving on the error path, and the log should not be the place
    that discovers there is no limit to it.
    """
    if isinstance(mapping, dict):
        return json.dumps(mapping, sort_keys=True, separators=(",", ":"))
    return str(mapping)[:200]


def _install(repo: Repository, view: str, rows: list) -> None:
    if view == BOOKS_VIEW:
        for row in rows:
            repo.books[row.order_id] = row
    elif view == LINES_VIEW:
        for row in rows:
            repo.lines[row.entity_id] = row
    elif view == SETTLEMENTS_VIEW:
        for row in rows:
            repo.settlements[row.id] = row
    elif view == BANK_VIEW:
        for row in rows:
            repo.bank[row.bank_ref] = row
