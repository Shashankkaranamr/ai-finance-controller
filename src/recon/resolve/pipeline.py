"""The run. Load -> resolve -> measure -> close the loop -> write artifacts.

This is a PIPELINE with a fenced LLM adjudicator, and we say so (BRIEF Sec 9
names "agent as marketing" an anti-pattern). Razorpay's track asks for an agent;
what closes this loop reliably is deterministic arithmetic with the LLM confined
to four adjudication jobs it cannot corrupt. The ablation table is the argument.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..audit.log import AuditLog, run_id_for
from ..domain.graph import EdgeKind, EdgeStatus, ReconEdge
from ..domain.identities import RULE_VERSION
from ..domain.truth import GroundTruth
from ..ingest.load import Repository, load_all
from ..ledger import statement as ledger
from ..llm.client import Adjudicator, LLMStats, NullAdjudicator, ResponseCache
from ..money import Paise
from ..report import exceptions as queue
from ..report import metrics as report_metrics
from . import tier0, tier1, tier2, tier3

SOURCE_FILES = ("books.jsonl", "settlement_lines.jsonl", "settlements.jsonl", "bank.jsonl")


@dataclass(slots=True)
class RunResult:
    run_id: str
    repo: Repository
    edges: list[ReconEdge]
    exceptions: list[queue.ExceptionRecord]
    metrics: report_metrics.Metrics
    statement: ledger.ReconStatement
    journal: list[ledger.JournalEntry]
    llm: LLMStats
    elapsed_ms: int
    out_dir: Path

    @property
    def ok(self) -> bool:
        return self.statement.foots and all(e.balances for e in self.journal)


def run(data_dir: Path, out_dir: Path,
        adjudicator: Adjudicator | None = None) -> RunResult:
    # perf_counter_ns, not perf_counter: integer nanoseconds keep this module
    # float-free, which is what lets tests/test_no_floats.py assert the property
    # over the WHOLE package rather than over a hand-picked "money path".
    started_ns = time.perf_counter_ns()

    adjudicator = adjudicator or NullAdjudicator()
    run_id = run_id_for([data_dir / name for name in SOURCE_FILES], RULE_VERSION)
    audit = AuditLog(run_id=run_id, rule_version=RULE_VERSION)

    repo = load_all(data_dir)
    audit.record("ingest_complete", records=repo.total_records,
                 quarantined=len(repo.quarantined))
    for bad in repo.quarantined:
        audit.record("row_quarantined", **bad.to_json())

    edges, exception_records = tier0.resolve(repo, audit)

    # Built before Tier 3 so the counters it increments are the ones reported.
    # With no adjudicator configured this stays a degraded run and Tier 3 is a
    # no-op -- which is why every run so far has already exercised that path.
    llm = LLMStats(
        available=adjudicator.available,
        degraded=not adjudicator.available,
        degraded_reason=getattr(adjudicator, "reason", "") if not adjudicator.available else "",
    )

    # Tier 1 takes Tier 0's MATCHED bank edges and types what remains against the
    # contracted rate card. It returns new edges rather than mutating: the audit
    # log carries the transition, so the graph never holds two versions of a truth.
    # Tier 2 BEFORE Tier 3: the LLM is only ever asked about credits that
    # deterministic evidence could not place. Asking it about a credit two exact
    # fields already identify would inflate its measured contribution and cost
    # money for nothing (D-027).
    edges, exception_records = tier2.resolve(repo, edges, exception_records, audit)

    # Tier 3 BEFORE Tier 1, because they do different jobs in a fixed order: the
    # adjudicator can only establish a LINKAGE, and the money on any edge it
    # creates still has to be explained by the arithmetic afterwards. Running it
    # after Tier 1 would leave LLM-linked credits permanently unexplained, and
    # letting it run instead of Tier 1 would be invariant 8 violated outright.
    cache = ResponseCache()
    edges, exception_records = tier3.resolve(
        repo, edges, exception_records, adjudicator, cache, llm, audit)

    edges, tier1_exceptions = tier1.resolve(repo, edges, audit)
    exception_records.extend(tier1_exceptions)

    # An exception is a statement about the FINAL state of the graph, not about
    # what some tier believed on the way there. Tier 0 raises
    # AMOUNT_VARIANCE_UNEXPLAINED on every edge it cannot close; Tier 1 then closes
    # most of them, and without this the queue would show an analyst 20 phantom
    # breaks that the system had in fact already explained. Supersession is
    # recorded in the audit log so the intermediate view is still reconstructible.
    linked_settlements = {e.dst_uid for e in edges if e.kind is EdgeKind.BANK_TO_SETTLEMENT}
    still_missing = [r for r in exception_records
                     if r.code == "MISSING_BANK_CREDIT" and r.subject_id in linked_settlements]
    for record in still_missing:
        audit.record("exception_superseded", code=record.code,
                     subject=record.subject_id, by_tier=3)
    exception_records = [r for r in exception_records if r not in still_missing]

    explained_refs = {e.ref for e in edges if e.status is EdgeStatus.EXPLAINED}
    superseded = [r for r in exception_records
                  if r.subject_kind == queue.SUBJECT_EDGE and r.subject_id in explained_refs]
    for record in superseded:
        audit.record("exception_superseded", code=record.code,
                     subject=record.subject_id, by_tier=1)
    exception_records = [r for r in exception_records if r not in superseded]


    truth = GroundTruth.read(data_dir / "ground_truth.json")
    metrics = report_metrics.compute(edges, exception_records, truth, repo)

    statement = ledger.build(edges, repo, opening_receivable=Paise(0))
    journal = ledger.journal_entries(edges, repo)
    audit.record("statement_built", foots=statement.foots,
                 difference=int(statement.difference),
                 journal_entries=len(journal),
                 all_balanced=all(e.balances for e in journal))

    elapsed_ms = (time.perf_counter_ns() - started_ns) // 1_000_000

    _write_artifacts(out_dir, metrics, statement, exception_records, journal, audit,
                     run_id, elapsed_ms, repo, llm)

    return RunResult(run_id=run_id, repo=repo, edges=edges, exceptions=exception_records,
                     metrics=metrics, statement=statement, journal=journal, llm=llm,
                     elapsed_ms=elapsed_ms, out_dir=out_dir)


def _write_artifacts(out_dir, metrics, statement, exception_records, journal, audit,
                     run_id, elapsed_ms, repo, llm) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics.write(out_dir / "metrics.json")
    (out_dir / "recon_statement.md").write_text(statement.render(), encoding="utf-8")
    queue.write_queue(out_dir / "exceptions.jsonl", exception_records)
    ledger.write_journal(out_dir / "journal_entries.jsonl", journal)
    audit.write(out_dir / "audit.jsonl")

    # Deliberately separate from metrics.json: elapsed time is never byte-identical,
    # and metrics.json must be (Increment 0 exit gate, item 6).
    records = repo.total_records
    summary = {
        "run_id": run_id,
        "elapsed_ms": elapsed_ms,
        "records_ingested": records,
        "records_per_second": (records * 1000 // elapsed_ms) if elapsed_ms else 0,
        "statement_foots": statement.foots,
        "llm": llm.to_json(),
    }
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":"), indent=1),
        encoding="utf-8")


def render_summary(result: RunResult) -> str:
    lines = [
        "=" * 74,
        f"RUN {result.run_id}   (idempotency key: content of inputs + rule version)",
        "=" * 74,
        "",
        result.metrics.render(),
        "",
        "LOOP CLOSURE",
        f"  {'reconciliation statement foots':<44} "
        f"{'YES' if result.statement.foots else 'NO':>8}",
        f"  {'journal entries, all balanced':<44} "
        f"{str(all(e.balances for e in result.journal)):>8}  "
        f"({len(result.journal)} entries)",
        f"  {'exceptions queued (breaks / informational)':<44} "
        f"{result.metrics.counts['exceptions_breaks']:>4} /"
        f"{result.metrics.counts['exceptions_informational']:>3}",
        "",
        "MODE",
        f"  {'LLM adjudicator available':<44} {str(result.llm.available):>8}",
        f"  {'degraded':<44} {str(result.llm.degraded):>8}"
        + (f"  ({result.llm.degraded_reason})" if result.llm.degraded else ""),
        "",
        "THROUGHPUT",
        f"  {'records ingested':<44} {result.repo.total_records:>8}",
        f"  {'wall clock':<44} {result.elapsed_ms:>6} ms",
        f"  {'quarantined rows':<44} {len(result.repo.quarantined):>8}",
        "",
        f"artifacts -> {result.out_dir}",
    ]
    return "\n".join(lines)
