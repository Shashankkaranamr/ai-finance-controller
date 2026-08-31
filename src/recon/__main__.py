"""CLI.  python -m recon {generate,run,demo,eval}

`demo` is the one-command entrypoint promised in the README: generate, run, print.
The Makefile forwards to it so reviewers on mac/Linux get `make demo`; the real
entrypoint is this module, which works everywhere without GNU make installed.

`eval` closes D-007. It was deliberately absent in Increment 0 because a held-out
set did not exist yet, and a stub running the dev seed under an "eval" name would
have been worse than its absence. It exists now because the held-out seed does:
a different world AND a different set of narration templates, so the number it
reports is not one we tuned against.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .generate.derive import generate
from .generate.narration import SPLIT_DEV, SPLIT_EVAL
from .generate.world import DEFAULT_DAYS, GenConfig
from .resolve import pipeline

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "generated"
OUT = ROOT / "out"

DEV_SEED = "dev"
EVAL_SEED = "eval"


def _split_for(seed: str, explicit: str | None) -> str:
    """The eval seed renders from held-out templates unless told otherwise.

    Tying the split to the seed name by default makes the held-out property hard
    to lose by accident: someone regenerating `eval` without thinking about
    narration still gets the held-out families. `--split` remains available so the
    coupling is a default rather than a hidden rule.
    """
    if explicit is not None:
        return explicit
    return SPLIT_EVAL if seed == EVAL_SEED else SPLIT_DEV


def _generate(seed: str, days: int, split: str | None = None) -> Path:
    out_dir = DATA / seed
    config = GenConfig(seed=seed, n_days=days, split=_split_for(seed, split))
    world, truth = generate(config, out_dir)

    by_kind = Counter(line.kind for line in world.lines)
    print(f"generated seed '{seed}' [narration split: {config.split}]")
    print(f"  {len(world.orders)} orders, {len(world.lines)} line items "
          f"({', '.join(f'{k}={v}' for k, v in sorted(by_kind.items()))}), "
          f"{len(world.settlements)} settlements over {config.n_days} days")

    injected = Counter(u.anomaly for u in truth.units if u.anomaly)
    clean = sum(1 for u in truth.units if u.anomaly is None)
    print(f"  intrinsic clean rate: {clean}/{len(truth.units)} units carry no "
          f"injected anomaly")
    for code, count in sorted(injected.items()):
        print(f"    injected {code:<26} x{count}")
    print(f"  -> {out_dir}")
    return out_dir


def _run(seed: str) -> int:
    data_dir = DATA / seed
    if not (data_dir / "ground_truth.json").exists():
        print(f"no generated data for seed '{seed}'. Run: python -m recon generate --seed {seed}",
              file=sys.stderr)
        return 2

    result = pipeline.run(data_dir, OUT / seed)
    print(pipeline.render_summary(result))

    if not result.ok:
        print("\nFAILED: the reconciliation statement does not foot, or a journal "
              "entry is unbalanced. The run's numbers are not trustworthy.",
              file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="recon", description="AI Finance Controller -- settlement reconciliation")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="build synthetic source views + ground truth")
    gen.add_argument("--seed", default=DEV_SEED)
    gen.add_argument("--days", type=int, default=DEFAULT_DAYS)
    gen.add_argument("--split", choices=(SPLIT_DEV, SPLIT_EVAL), default=None,
                     help="narration template family; defaults to eval for the eval seed")

    runner = sub.add_parser("run", help="reconcile an already-generated seed")
    runner.add_argument("--seed", default=DEV_SEED)

    demo = sub.add_parser("demo", help="generate + run + report, one command")
    demo.add_argument("--seed", default=DEV_SEED)
    demo.add_argument("--days", type=int, default=DEFAULT_DAYS)

    ev = sub.add_parser(
        "eval", help="generate + run the HELD-OUT seed (different world, held-out narrations)")
    ev.add_argument("--days", type=int, default=DEFAULT_DAYS)

    args = parser.parse_args(argv)

    if args.command == "generate":
        _generate(args.seed, args.days, args.split)
        return 0
    if args.command == "run":
        return _run(args.seed)
    if args.command == "demo":
        _generate(args.seed, args.days)
        print()
        return _run(args.seed)
    if args.command == "eval":
        print("HELD-OUT EVALUATION")
        print("The deterministic narration parser was written against the dev families "
              "only.\nThis seed renders from templates it has never seen (PLAN.md "
              "deviation #4).\n")
        _generate(EVAL_SEED, args.days, SPLIT_EVAL)
        print()
        return _run(EVAL_SEED)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
