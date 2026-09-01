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
import os
import sys
from collections import Counter
from pathlib import Path

from .generate.derive import generate
from .generate.narration import SPLIT_DEV, SPLIT_EVAL
from .generate.world import DEFAULT_DAYS, GenConfig
from .llm.anthropic_client import AnthropicAdjudicator
from .llm.client import NullAdjudicator
from .money import format_bps
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


def _adjudicator(use_llm: bool):
    """Explicit opt-in, never automatic.

    An adjudicator costs money and changes the numbers, so it is not switched on
    just because a key happens to be exported. But staying silent about a key that
    IS present would be its own trap -- someone sets it up, runs the demo, sees
    rules-only output and concludes the integration is broken.
    """
    if not use_llm:
        if os.environ.get("ANTHROPIC_API_KEY"):
            print("note: ANTHROPIC_API_KEY is set but --llm was not passed; "
                  "running rules-only.\n")
        return NullAdjudicator()

    adjudicator = AnthropicAdjudicator()
    if not adjudicator.available:
        # Not fatal. Sec 8 requires the batch to complete with zero LLM
        # availability, so an unusable adjudicator degrades exactly like none.
        print(f"--llm requested but unavailable: {adjudicator.reason}\n"
              "continuing rules-only (degraded mode).\n", file=sys.stderr)
    return adjudicator


def _missing(seed: str) -> bool:
    if (DATA / seed / "ground_truth.json").exists():
        return False
    print(f"no generated data for seed '{seed}'. Run: python -m recon generate --seed {seed}",
          file=sys.stderr)
    return True


def _run(seed: str, use_llm: bool = False) -> int:
    data_dir = DATA / seed
    if _missing(seed):
        return 2

    result = pipeline.run(data_dir, OUT / seed, adjudicator=_adjudicator(use_llm))
    print(pipeline.render_summary(result))

    if not result.ok:
        print("\nFAILED: the reconciliation statement does not foot, or a journal "
              "entry is unbalanced. The run's numbers are not trustworthy.",
              file=sys.stderr)
        return 1
    return 0


def _ablation(seed: str) -> int:
    """BRIEF Sec 7's ablation, run for real: the same seed with and without the
    adjudicator, side by side.

    This is the artifact that answers "what does the LLM actually add", and it is
    deliberately a command rather than a paragraph -- the number should come from
    a run a reviewer can repeat, not from us.

    With no key the adjudicator column is the degraded path, which is honest and
    still worth printing: it shows the harness works and the LLM contribution is
    exactly zero until one is configured.
    """
    if _missing(seed):
        return 2
    data_dir = DATA / seed

    rules = pipeline.run(data_dir, OUT / seed / "ablation" / "rules_only",
                         adjudicator=NullAdjudicator())
    adjudicator = AnthropicAdjudicator()
    if adjudicator.available:
        pending = len([r for r in rules.exceptions if r.code == "NARRATION_UNPARSEABLE"])
        print(f"adjudicator available; {pending} unparsed narrations will be sent.\n")
    else:
        print(f"adjudicator unavailable: {adjudicator.reason}\n"
              "the second column below is therefore the degraded path.\n")
    llm = pipeline.run(data_dir, OUT / seed / "ablation" / "with_adjudicator",
                       adjudicator=adjudicator)

    rows = [
        ("explanation rate (bank credits)",
         rules.metrics.explanation_rate_bank, llm.metrics.explanation_rate_bank),
        ("settlement coverage",
         rules.metrics.settlement_coverage, llm.metrics.settlement_coverage),
        ("linkage precision",
         rules.metrics.linkage_precision, llm.metrics.linkage_precision),
        ("linkage recall",
         rules.metrics.linkage_recall, llm.metrics.linkage_recall),
    ]

    lines = [
        f"# Ablation — seed '{seed}'",
        "",
        "The same data, resolved twice. Tier is an attribute of an edge, so the tiered",
        "breakdown inside each run is a group-by; this table is the end-to-end comparison.",
        "",
        "| Metric | rules only | + adjudicator |",
        "|---|---|---|",
    ]
    for label, a, b in rows:
        lines.append(f"| {label} | {format_bps(a.bps)} ({a.numerator}/{a.denominator}) "
                     f"| {format_bps(b.bps)} ({b.numerator}/{b.denominator}) |")
    lines += [
        f"| journal entries posted | {len(rules.journal)} | {len(llm.journal)} |",
        f"| statement foots | {'YES' if rules.statement.foots else 'NO'} "
        f"| {'YES' if llm.statement.foots else 'NO'} |",
        f"| adjudicator calls | {rules.llm.calls_attempted} | {llm.llm.calls_attempted} |",
        f"| **blocked_hallucination** (invented a reference) | "
        f"{rules.llm.blocked_hallucination} | **{llm.llm.blocked_hallucination}** |",
        f"| blocked_unverifiable (read it right; no usable reference) | "
        f"{rules.llm.blocked_unverifiable} | {llm.llm.blocked_unverifiable} |",
        f"| degraded | {rules.llm.degraded} | {llm.llm.degraded} |",
        "",
        "Both counters are rejections -- an unverifiable reference never becomes a link.",
        "They are split because they are different events: `blocked_hallucination` means",
        "the model produced characters that are not in the narration, and",
        "`blocked_unverifiable` means it read the document correctly and the document has",
        "no usable reference in it (a bank truncated the UTR, or the credit is a third",
        "party's). Only the first is a model error. Linkage precision is the number to",
        "read beside both: a rejected proposal must never move it.",
        "",
    ]
    report = "\n".join(lines)
    out = OUT / seed / "ablation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8", newline="\n")
    print(report)
    print(f"-> {out}")
    return 0 if rules.ok and llm.ok else 1


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
    runner.add_argument("--llm", action="store_true",
                        help="enable the LLM adjudicator for unparsed narrations "
                             "(needs ANTHROPIC_API_KEY and the [llm] extra)")

    demo = sub.add_parser("demo", help="generate + run + report, one command")
    demo.add_argument("--seed", default=DEV_SEED)
    demo.add_argument("--days", type=int, default=DEFAULT_DAYS)
    demo.add_argument("--llm", action="store_true", help="enable the LLM adjudicator")

    ev = sub.add_parser(
        "eval", help="generate + run the HELD-OUT seed (different world, held-out narrations)")
    ev.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ev.add_argument("--llm", action="store_true", help="enable the LLM adjudicator")

    abl = sub.add_parser("ablation",
                         help="run a seed with and without the adjudicator, side by side")
    abl.add_argument("--seed", default=EVAL_SEED)

    args = parser.parse_args(argv)

    if args.command == "generate":
        _generate(args.seed, args.days, args.split)
        return 0
    if args.command == "run":
        return _run(args.seed, args.llm)
    if args.command == "demo":
        _generate(args.seed, args.days)
        print()
        return _run(args.seed, args.llm)
    if args.command == "ablation":
        return _ablation(args.seed)
    if args.command == "eval":
        print("HELD-OUT EVALUATION")
        print("The deterministic narration parser was written against the dev families "
              "only.\nThis seed renders from templates it has never seen (PLAN.md "
              "deviation #4).\n")
        _generate(EVAL_SEED, args.days, SPLIT_EVAL)
        print()
        return _run(EVAL_SEED, args.llm)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
