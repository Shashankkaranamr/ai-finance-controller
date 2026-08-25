"""CLI.  python -m recon {generate,run,demo}

`demo` is the one-command entrypoint promised in the README: generate, run, print.
The Makefile forwards to it so reviewers on mac/Linux get `make demo`; the real
entrypoint is this module, which works everywhere without GNU make installed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .generate.derive import generate
from .generate.world import GenConfig
from .resolve import pipeline

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "generated"
OUT = ROOT / "out"


def _generate(seed: str, cycles: int) -> Path:
    out_dir = DATA / seed
    config = GenConfig(seed=seed, n_cycles=cycles)
    world, truth = generate(config, out_dir)
    print(f"generated seed '{seed}': {len(world.orders)} orders, "
          f"{len(world.payments)} line items, {len(world.settlements)} settlements "
          f"-> {out_dir}")
    injected = [u for u in truth.units if u.anomaly]
    for unit in injected:
        print(f"  injected anomaly: {unit.anomaly} on {unit.kind} {unit.uid}")
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
    parser = argparse.ArgumentParser(prog="recon",
                                     description="AI Finance Controller -- settlement reconciliation")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="build synthetic source views + ground truth")
    gen.add_argument("--seed", default="dev")
    gen.add_argument("--cycles", type=int, default=6)

    runner = sub.add_parser("run", help="reconcile an already-generated seed")
    runner.add_argument("--seed", default="dev")

    demo = sub.add_parser("demo", help="generate + run + report, one command")
    demo.add_argument("--seed", default="dev")
    demo.add_argument("--cycles", type=int, default=6)

    args = parser.parse_args(argv)

    if args.command == "generate":
        _generate(args.seed, args.cycles)
        return 0
    if args.command == "run":
        return _run(args.seed)
    if args.command == "demo":
        _generate(args.seed, args.cycles)
        print()
        return _run(args.seed)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
