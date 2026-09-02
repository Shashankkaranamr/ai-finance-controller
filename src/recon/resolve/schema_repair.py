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
the proposal is a mapping, and it must survive four gates, all exact:

  1. STRUCTURAL -- every target is a real field on the model and every source is a
     column actually present in the file; the mapping is injective and covers
     every required field. This is the analogue of `_is_faithful_reading`: the
     model may not invent a field name any more than it may invent a UTR.
  2. TOTAL RE-VALIDATION -- EVERY quarantined row of that view must re-validate
     through the same Pydantic model, `extra="forbid"` still enforced. Not most.
     One row short and the mapping is rejected, because a mapping that works for
     some rows is a mapping we do not understand.
  3. CONTAINMENT -- the structural facts a column must satisfy to still BE that
     column (tax <= fee, fee <= amount, ...). This catches the dangerous case gate
     2 cannot: two fields of the SAME TYPE swapped, which re-validates perfectly
     and is arithmetically nonsense. See `_identity_holds` for why this is
     containment and deliberately NOT the GST rate.
  4. UTILITY -- the repaired view must actually serve the join it exists for. A
     bank statement whose narration has been swapped with its row id validates
     fine and yields not one readable reference.

Gate 3's strength VARIES BY VIEW, and claiming otherwise would overstate the
fence:

  settlement_lines   strongest: four independent containments, and a fee/tax swap
                     breaks them on every fee-bearing row at once.
  settlements        fee/tax containment only -- `amount` is signed here, because
                     a heavy-refund cycle settles negative.
  bank               no money identity at all: a credit is one number. Gate 4
                     carries this view instead.
  books              none. Gates 1 and 2 only, stated rather than papered over.

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
from ..generate.narration import parse_utr
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


def _identity_holds(view: str, rows: list) -> bool:
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

    Returns True when the view carries no such invariant -- an ABSENT check, not a
    pass we did not earn. The caller records which gate ran.
    """
    if view == LINES_VIEW:
        return all(r.tax <= r.fee and r.fee <= r.amount and r.amount > 0
                   and not (r.credit > 0 and r.debit > 0)
                   for r in rows)
    if view == SETTLEMENTS_VIEW:
        # `amount` is signed here -- a heavy-refund cycle settles negative -- so
        # only the fee/tax containment is available, and it is enough.
        return all(r.tax <= r.fees for r in rows)
    return True


def _is_useful(view: str, rows: list, repo: Repository) -> bool:
    """Gate 4. Only the bank view has a non-trivial answer, and it is the one
    that needs one: `bank_ref` and `narration` are both strings, so swapping them
    re-validates cleanly, satisfies every identity (there is none), and leaves a
    statement from which no reference can be read."""
    if view != BANK_VIEW:
        return True
    if not repo.settlements:
        # Nothing to resolve against. Withhold judgement rather than reject a
        # mapping for a reason that is not about the mapping.
        return True
    known = set(repo.settlement_by_utr())
    return any((parse_utr(r.narration) or "") in known for r in rows)


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
    if not _identity_holds(view, repaired):
        return "identity:sec_3_2_violated"

    # --- gate 4: utility ------------------------------------------------------
    if not _is_useful(view, repaired, repo):
        return "utility:view_serves_no_join"
    return None


def _render(mapping) -> str:
    if isinstance(mapping, dict):
        return json.dumps(mapping, sort_keys=True, separators=(",", ":"))[:200]
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
