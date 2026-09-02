"""ONE live map_schema run. Same protocol as the 01 Sep parse_narration run.

PROTOCOL, and it is the point
----------------------------
One run. No re-rolls. No prompt edits after seeing the answer. Whatever comes back
is what gets reported, including if it is bad -- the 01 Sep narration run reported
`blocked_hallucination = 17` and then explained why the counter was wrong, rather
than re-running until the number looked better.

Reads ANTHROPIC_API_KEY and ANTHROPIC_WORKSPACE_ID from the environment. Neither
is printed, and neither is written to any artifact this produces.

    python scripts/live_map_schema.py --seed eval
    python scripts/live_map_schema.py --seed eval --stub    # harness check, no API

`--stub` runs the identical path against a truthful in-process mapper, so the
harness itself can be proven before a single billable call is made.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recon.llm.anthropic_client import AnthropicAdjudicator          # noqa: E402
from recon.llm.client import (JOB_MAP_SCHEMA, AdjudicationRequest,   # noqa: E402
                              AdjudicationResult)
from recon.resolve import pipeline                                   # noqa: E402

# One column per view, each REQUIRED by its model, so renaming it fails every row
# of that view and nothing else. Same drift the fence tests use.
DRIFT = {
    "settlement_lines.jsonl": ("entity_id", "entity_ref"),
    "bank.jsonl": ("narration", "description"),
}


class TruthfulStub:
    """Harness check only. Proposes the identity mapping plus the known rename."""

    available = True

    def __init__(self, renames):
        self.renames = renames
        self.seen = []

    def adjudicate(self, request):
        self.seen.append(request)
        if request.job != JOB_MAP_SCHEMA:
            return AdjudicationResult(ok=True, data={"utr": ""})
        mapping = {c: c for c in request.payload["observed_columns"]}
        mapping.update(self.renames)
        return AdjudicationResult(ok=True, data={"mapping": mapping},
                                  rationale="stub: identity + known rename")


class Recorder:
    """Wraps an adjudicator and records exactly what went out and came back."""

    def __init__(self, inner):
        self.inner = inner
        self.exchanges = []

    @property
    def available(self):
        return self.inner.available

    def adjudicate(self, request):
        started = time.perf_counter_ns()
        result = self.inner.adjudicate(request)
        self.exchanges.append({
            "job": request.job,
            "subject": request.subject_ref,
            "observed_columns": request.payload.get("observed_columns"),
            "ok": result.ok,
            "mapping": result.data.get("mapping") if result.ok else None,
            "rationale": result.rationale,
            "reason_unavailable": result.reason_unavailable,
            "elapsed_ms": (time.perf_counter_ns() - started) // 1_000_000,
        })
        return result


def drift(seed: str, view: str, work: Path) -> Path:
    src = ROOT / "data" / "generated" / seed
    if not (src / "ground_truth.json").exists():
        sys.exit(f"no generated data for '{seed}'. Run: python -m recon generate --seed {seed}")
    dst = work / f"drifted_{view.split('.')[0]}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    old, new = DRIFT[view]
    path = dst / view
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            row[new] = row.pop(old)
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="eval")
    ap.add_argument("--view", default="settlement_lines.jsonl", choices=sorted(DRIFT))
    ap.add_argument("--stub", action="store_true", help="harness check; no API call")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    work = Path(args.out) if args.out else ROOT / "out" / "_live_map_schema"
    work.mkdir(parents=True, exist_ok=True)
    data = drift(args.seed, args.view, work)
    old, new = DRIFT[args.view]

    if args.stub:
        inner = TruthfulStub({new: old})
        label = "STUB (no API call)"
    else:
        inner = AnthropicAdjudicator()
        if not inner.available:
            sys.exit(f"adjudicator unavailable: {inner.reason}")
        label = f"LIVE  model={inner.model}"

    adjudicator = Recorder(inner)
    print(f"=== map_schema · seed={args.seed} · view={args.view} "
          f"· renamed {old!r} -> {new!r} ===")
    print(f"    {label}")

    started = time.perf_counter_ns()
    result = pipeline.run(data, work / "run", adjudicator=adjudicator)
    wall_ms = (time.perf_counter_ns() - started) // 1_000_000

    print(f"\n--- what went out and came back ({len(adjudicator.exchanges)} exchange(s)) ---")
    for ex in adjudicator.exchanges:
        if ex["job"] != JOB_MAP_SCHEMA:
            continue
        print(f"  subject   : {ex['subject']}")
        print(f"  columns   : {ex['observed_columns']}")
        print(f"  ok        : {ex['ok']}   ({ex['elapsed_ms']} ms)")
        if ex["mapping"] is not None:
            changed = {k: v for k, v in ex["mapping"].items() if k != v}
            print(f"  mapping   : {len(ex['mapping'])} entries, "
                  f"{len(changed)} not identity -> {changed}")
        if ex["rationale"]:
            print(f"  rationale : {ex['rationale'][:300]}")
        if ex["reason_unavailable"]:
            print(f"  declined  : {ex['reason_unavailable'][:400]}")

    m = result.metrics
    print("\n--- outcome ---")
    print(f"  rows quarantined      {len(result.repo.quarantined)}")
    print(f"  blocked_bad_mapping   {result.llm.blocked_bad_mapping}")
    print(f"  calls_attempted       {result.llm.calls_attempted}")
    print(f"  calls_declined        {result.llm.calls_declined}")
    print(f"  explanation rate      {m.explanation_rate_bank.numerator}/"
          f"{m.explanation_rate_bank.denominator}")
    print(f"  false clear in remit  {m.false_clear_in_remit.numerator}/"
          f"{m.false_clear_in_remit.denominator}")
    print(f"  linkage precision     {m.linkage_precision.numerator}/"
          f"{m.linkage_precision.denominator}")
    print(f"  statement foots       {result.statement.foots}")
    print(f"  wall clock            {wall_ms} ms")

    # The rejection reason lives only in the audit log, and it is the number that
    # matters when a mapping is blocked: WHICH gate caught it.
    audit = (work / "run" / "audit.jsonl")
    if audit.exists():
        for line in audit.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("event") in {"blocked_bad_mapping", "map_schema_accepted",
                                      "map_schema_declined", "map_schema_skipped"}:
                print(f"  audit: {event.get('event')} "
                      f"gate={event.get('gate', '-')} "
                      f"rows={event.get('rows_recovered', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
