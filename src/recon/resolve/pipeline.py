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
from ..domain.graph import ReconEdge
from ..domain.identities import RULE_VERSION
from ..domain.truth import GroundTruth
from ..ingest.load import Repository, load_all
from ..ledger import statement as ledger
from ..llm.client import Adjudicator, LLMStats, NullAdjudicator
from ..money import Paise
from ..report import exceptions as queue
from ..report import metrics as report_metrics
from . import tier0

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

    # Increment 0 is rules-only by design, so every run is already a degraded-mode
    # run. Proving the degraded path on day one beats proving it on demo day.
    llm = LLMStats(
        available=adjudicator.available,
        calls_attempted=0,
        calls_declined=getattr(adjudicator, "calls_declined", 0),
        degraded=not adjudicator.available,
        degraded_reason=getattr(adjudicator, "reason", "") if not adjudicator.available else "",
    )
    audit.record("adjudicator_status", **llm.to_json())

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
