"""Run the 10 pre-registered drift scenarios, once each. No re-rolls.

Scores TWO questions separately, because D-023 says they are different questions
and conflating them here would repeat that mistake:

  model_correct  -- the proposed mapping is EXACTLY the inverse of the rename
  gate_outcome   -- accepted, or blocked and by which gate

and reports the 2x2. The cell that matters is wrong-but-accepted: a mapping the
model got wrong and the fence let through.

For every ACCEPTED mapping it also re-checks the resulting run against the clean
baseline. A correct repair reproduces it exactly; a wrong one that got past the
gates will not, and the difference is the damage the fence failed to stop.

    python scripts/live_scenario_suite.py --seed eval --stub   # harness check
    python scripts/live_scenario_suite.py --seed eval          # the live run
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recon.generate import drift                                     # noqa: E402
from recon.llm.anthropic_client import AnthropicAdjudicator          # noqa: E402
from recon.llm.client import (JOB_MAP_SCHEMA, AdjudicationResult,    # noqa: E402
                              NullAdjudicator)
from recon.resolve import pipeline                                   # noqa: E402


class TruthfulStub:
    """Harness check only: answers every scenario correctly, from the registry."""

    available = True

    def __init__(self, truth):
        self.truth = truth

    def adjudicate(self, request):
        if request.job != JOB_MAP_SCHEMA:
            return AdjudicationResult(ok=True, data={"utr": ""})
        return AdjudicationResult(ok=True, data={"mapping": dict(self.truth)},
                                  rationale="stub: registry truth")


class Recorder:
    def __init__(self, inner):
        self.inner = inner
        self.mapping = None
        self.rationale = ""
        self.declined = ""
        self.elapsed_ms = 0

    @property
    def available(self):
        return self.inner.available

    def adjudicate(self, request):
        started = time.perf_counter_ns()
        result = self.inner.adjudicate(request)
        if request.job == JOB_MAP_SCHEMA:
            self.elapsed_ms = (time.perf_counter_ns() - started) // 1_000_000
            self.mapping = result.data.get("mapping") if result.ok else None
            self.rationale = result.rationale
            self.declined = result.reason_unavailable
        return result


def gate_from_audit(out_dir: Path) -> tuple[str, str]:
    """(outcome, gate) read from the run's own audit log."""
    path = out_dir.joinpath("audit.jsonl")
    if not path.exists():
        return ("no-audit", "-")
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        name = event.get("event")
        if name == "map_schema_accepted":
            return ("accepted", "-")
        if name == "blocked_bad_mapping":
            return ("blocked", event.get("gate", "?"))
        if name in ("map_schema_declined", "map_schema_skipped"):
            return (name.replace("map_schema_", ""), event.get("reason", "?")[:40])
    return ("no-call", "-")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="eval")
    ap.add_argument("--stub", action="store_true")
    args = ap.parse_args()

    src = ROOT / "data" / "generated" / args.seed
    if not src.joinpath("ground_truth.json").exists():
        sys.exit(f"no generated data for '{args.seed}'")
    work = ROOT / "out" / f"_scenarios_{args.seed}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    baseline = pipeline.run(src, work / "_baseline", adjudicator=NullAdjudicator())
    clean = (baseline.metrics.explanation_rate_bank.numerator,
             baseline.metrics.false_clear_in_remit.numerator,
             baseline.metrics.linkage_precision.bps)
    print(f"clean baseline ({args.seed}): explanation={clean[0]}"
          f"/{baseline.metrics.explanation_rate_bank.denominator}"
          f"  false_clear={clean[1]}  precision={clean[2]}bps\n")

    rows = []
    for scenario in drift.SCENARIOS:
        truth = drift.truth_mapping(scenario, src)
        data = drift.apply(scenario, src, work / scenario.name)
        inner = TruthfulStub(truth) if args.stub else AnthropicAdjudicator()
        if not inner.available:
            sys.exit(f"adjudicator unavailable: {inner.reason}")
        rec = Recorder(inner)

        out = work / f"out_{scenario.name}"
        result = pipeline.run(data, out, adjudicator=rec)
        outcome, gate = gate_from_audit(out)

        correct = rec.mapping == truth
        wrong_keys = ({k: (rec.mapping.get(k), v) for k, v in truth.items()
                       if rec.mapping.get(k) != v} if isinstance(rec.mapping, dict) else {})
        got = (result.metrics.explanation_rate_bank.numerator,
               result.metrics.false_clear_in_remit.numerator,
               result.metrics.linkage_precision.bps)
        rows.append({
            "name": scenario.name, "shape": scenario.shape, "view": scenario.view,
            "renames": len(scenario.renames), "correct": correct,
            "outcome": outcome, "gate": gate, "wrong": wrong_keys,
            "rationale": rec.rationale, "declined": rec.declined,
            "ms": rec.elapsed_ms, "matches_clean": got == clean,
            "metrics": got, "quarantined": len(result.repo.quarantined),
            "foots": result.statement.foots,
        })

    print(f"{'scenario':<24} {'shape':<22} {'model':<8} {'gate':<10} {'==clean':<8} ms")
    print("-" * 84)
    for r in rows:
        print(f"{r['name']:<24} {r['shape']:<22} "
              f"{'CORRECT' if r['correct'] else 'wrong':<8} "
              f"{r['outcome']:<10} {str(r['matches_clean']):<8} {r['ms']}")

    correct_n = sum(1 for r in rows if r["correct"])
    accepted = [r for r in rows if r["outcome"] == "accepted"]
    print(f"\nMODEL ACCURACY: {correct_n}/{len(rows)} mappings exactly correct")
    print("\nTHE 2x2")
    for label, pred in (("correct + accepted", lambda r: r["correct"] and r["outcome"] == "accepted"),
                        ("correct + BLOCKED (fence too strict)", lambda r: r["correct"] and r["outcome"] != "accepted"),
                        ("wrong   + ACCEPTED (dangerous)", lambda r: not r["correct"] and r["outcome"] == "accepted"),
                        ("wrong   + blocked (fence worked)", lambda r: not r["correct"] and r["outcome"] != "accepted")):
        hits = [r["name"] for r in rows if pred(r)]
        print(f"  {label:<40} {len(hits)}  {hits if hits else ''}")

    print("\nACCEPTED MAPPINGS -- did the run come back to the clean baseline?")
    for r in accepted:
        flag = "yes" if r["matches_clean"] else "NO -- DAMAGE"
        print(f"  {r['name']:<24} {flag:<14} {r['metrics']} vs clean {clean}")

    print("\nPER-SCENARIO DETAIL")
    for r in rows:
        print(f"\n  {r['name']} ({r['shape']}, {r['view']}, {r['renames']} rename(s))")
        print(f"    model correct : {r['correct']}")
        print(f"    gate          : {r['outcome']}  {r['gate']}")
        if r["wrong"]:
            for column, (got_v, want) in sorted(r["wrong"].items()):
                print(f"    MISMAPPED     : {column!r} -> {got_v!r}   (truth: {want!r})")
        if r["rationale"]:
            print(f"    rationale     : {r['rationale'][:260]}")
        if r["declined"]:
            print(f"    declined      : {r['declined'][:200]}")

    (work / "results.json").write_text(
        json.dumps(rows, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"\nwritten: {work / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
