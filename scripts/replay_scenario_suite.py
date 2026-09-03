"""REGRESSION, not a measurement. Replay the 03 Sep live mappings through the gates.

WHY REPLAY RATHER THAN RE-RUN LIVE
-----------------------------------
The question is whether the F-021 fix makes the fence discriminate. A fresh live
run answers a different question, because the model may sample differently and any
change would confound the gate fix with model variance. Replaying the EXACT
mappings the model returned on 03 Sep isolates the one thing that changed.

WHY THIS IS NOT EVIDENCE THAT THE FENCE IS NOW GOOD
----------------------------------------------------
The fix was written specifically to catch S7 and S9. Catching them is true by
construction, and a green result here says only "the fix does what it was built to
do". Whether the fence discriminates on shapes it was NOT built against is a
different question, which the declined fresh-10 suite (D-037) would have answered
and this cannot.

The proposal is reconstructed as `truth mapping, overridden by the entries the run
recorded as wrong` -- the results file stores the diff rather than the whole
mapping, and that reconstruction is exact.

    python scripts/replay_scenario_suite.py --seed eval
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recon.generate import drift                                     # noqa: E402
from recon.llm.client import (JOB_MAP_SCHEMA, AdjudicationResult,    # noqa: E402
                              NullAdjudicator)
from recon.resolve import pipeline                                   # noqa: E402


class Replay:
    """Returns one recorded mapping. Deterministic, offline, no key."""

    available = True

    def __init__(self, mapping):
        self.mapping = mapping

    def adjudicate(self, request):
        if request.job != JOB_MAP_SCHEMA:
            return AdjudicationResult(ok=True, data={"utr": ""})
        return AdjudicationResult(ok=True, data={"mapping": dict(self.mapping)},
                                  rationale="replayed from the 03 Sep live run")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="eval")
    args = ap.parse_args()

    src = ROOT / "data" / "generated" / args.seed
    recorded = ROOT / "out" / f"_scenarios_{args.seed}" / "results.json"
    if not recorded.exists():
        sys.exit(f"no recorded live run at {recorded}")
    rows = json.loads(recorded.read_text(encoding="utf-8"))

    work = ROOT / "out" / f"_replay_{args.seed}"
    work.mkdir(parents=True, exist_ok=True)
    baseline = pipeline.run(src, work / "_baseline", adjudicator=NullAdjudicator())
    clean = (baseline.metrics.explanation_rate_bank.numerator,
             baseline.metrics.false_clear_in_remit.numerator)

    print("REGRESSION -- replaying the 03 Sep live mappings against the fixed gates")
    print("(not a measurement: the fix was written to catch S7 and S9)\n")
    print(f"{'scenario':<24} {'model':<8} {'was':<10} {'now':<10} {'false clear':<12}")
    print("-" * 70)

    results = []
    for record in rows:
        scenario = drift.BY_NAME[record["name"]]
        truth = drift.truth_mapping(scenario, src)
        proposal = dict(truth)
        for column, pair in (record["wrong"] or {}).items():
            proposal[column] = pair[0]          # what the model actually said

        data = drift.apply(scenario, src, work / scenario.name)
        result = pipeline.run(data, work / f"out_{scenario.name}",
                              adjudicator=Replay(proposal))
        now = "accepted" if result.llm.blocked_bad_mapping == 0 else "blocked"
        fc = result.metrics.false_clear_in_remit
        print(f"{record['name']:<24} {'CORRECT' if record['correct'] else 'wrong':<8} "
              f"{record['outcome']:<10} {now:<10} {fc.numerator}/{fc.denominator}")
        results.append((record, now, result))

    print("\nTHE 2x2, AFTER")
    for label, pred in (
            ("correct + accepted", lambda r, n: r["correct"] and n == "accepted"),
            ("correct + BLOCKED (fence too strict)", lambda r, n: r["correct"] and n != "accepted"),
            ("wrong   + ACCEPTED (dangerous)", lambda r, n: not r["correct"] and n == "accepted"),
            ("wrong   + blocked (fence worked)", lambda r, n: not r["correct"] and n != "accepted")):
        hits = [r["name"] for r, n, _ in results if pred(r, n)]
        print(f"  {label:<40} {len(hits)}  {hits if hits else ''}")

    damaged = [r["name"] for r, n, res in results
               if n == "accepted" and not r["correct"]]
    print(f"\nclean baseline: explanation={clean[0]}, false_clear={clean[1]}")
    print(f"wrong mappings still reaching the repository: {damaged or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
