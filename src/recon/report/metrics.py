"""Metrics. Every numerator and denominator is stated here and in the README.

BRIEF Sec 7: "Ambiguous metrics are the single easiest way to lose a technical
panel. Publish the formulas."

TWO DELIBERATE CHOICES
----------------------
1. EXPLANATION RATE IS THE HEADLINE, not match rate. Exact UTR join clears the
   large majority on any realistic data -- finding the counterparty is easy.
   Explaining the amount to a zero residual with every component typed is the job.
   Match rate is reported alongside as the supporting number so nobody mistakes
   the easy one for the achievement.

2. THE HEADLINE GRAIN CARRIES TWO DENOMINATORS. "Bank credits fully explained /
   total bank credits" cannot see a settlement that never produced a bank credit
   at all -- the worst break in the set would be invisible in the headline. So
   settlement coverage is reported next to it, and both are named in full.

All rates are integer basis points (9873 == 98.73%). No float exists anywhere in
this package, which tests/test_no_floats.py asserts by AST scan.

Wall-clock throughput lives in run_summary.json, NOT here: metrics.json must be
byte-identical across runs (Increment 0 exit gate, item 6) and elapsed time never is.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.graph import (BUILT_TIER, ComponentType, EdgeKind, EdgeStatus,
                            ExceptionType, ReconEdge, Tier)
from ..domain.truth import GroundTruth
from ..generate.narration import parse_utr
from ..money import Paise, format_bps, format_inr, ratio_bps
from .exceptions import ExceptionRecord

ACCEPTED = (EdgeStatus.EXPLAINED, EdgeStatus.MATCHED)


@dataclass(frozen=True, slots=True)
class Rate:
    """A rate that always travels with the counts that produced it."""

    numerator: int
    denominator: int
    label: str

    @property
    def bps(self) -> int:
        return ratio_bps(self.numerator, self.denominator)

    def to_json(self) -> dict:
        return {"numerator": self.numerator, "denominator": self.denominator,
                "rate_bps": self.bps, "display": format_bps(self.bps), "label": self.label}

    def line(self) -> str:
        return (f"{self.label:<44} {format_bps(self.bps):>8}  "
                f"({self.numerator}/{self.denominator})")


@dataclass(slots=True)
class Metrics:
    explanation_rate_bank: Rate
    settlement_coverage: Rate
    match_rate_line_items: Rate
    money_weighted_coverage: Rate
    money_total: Paise
    money_explained: Paise
    linkage_precision: Rate
    linkage_recall: Rate
    exception_detection_recall: Rate
    false_clear_rate: Rate
    false_clear_in_remit: Rate
    false_clear_out_of_remit: Rate
    exception_typing_accuracy: Rate
    intrinsic_clean_rate: Rate
    narration_parse_rate: Rate
    decomposition_closure: Rate
    residual_total: Paise = Paise(0)
    residual_by_component: dict[str, int] = field(default_factory=dict)
    injected_by_class: dict[str, int] = field(default_factory=dict)
    explained_by_basis: dict[str, int] = field(default_factory=dict)
    ablation: dict[str, dict] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "headline": {
                "explanation_rate_bank": self.explanation_rate_bank.to_json(),
                "settlement_coverage": self.settlement_coverage.to_json(),
                "money_weighted_coverage": self.money_weighted_coverage.to_json(),
            },
            "supporting": {
                "match_rate_line_items": self.match_rate_line_items.to_json(),
                "money_total_paise": int(self.money_total),
                "money_explained_paise": int(self.money_explained),
            },
            "accuracy": {
                "linkage_precision": self.linkage_precision.to_json(),
                "linkage_recall": self.linkage_recall.to_json(),
                "exception_detection_recall": self.exception_detection_recall.to_json(),
                "false_clear_rate": self.false_clear_rate.to_json(),
                "false_clear_in_remit": self.false_clear_in_remit.to_json(),
                "false_clear_out_of_remit": self.false_clear_out_of_remit.to_json(),
                "exception_typing_accuracy": self.exception_typing_accuracy.to_json(),
            },
            # Properties of the DATA, computed from ground_truth.json with no
            # resolver involved. This is what the 85-92% realism target is checked
            # against -- the resolver's own score answers a different question.
            "data_realism": {
                "intrinsic_clean_rate": self.intrinsic_clean_rate.to_json(),
                "narration_parse_rate": self.narration_parse_rate.to_json(),
                "injected_by_class": dict(sorted(self.injected_by_class.items())),
            },
            # What Tier 0 could not explain, bucketed by the component that TRULY
            # accounts for it. The Increment 2 input: mechanical and typeable, or
            # scattered and ambiguous?
            # Can Tier 1 type the gross-to-net gap with NO linkage involved?
            # Separated out because on the held-out seed the narration parser finds
            # no UTR, so no bank edge exists and explanation rate is 0% for reasons
            # that have nothing to do with the arithmetic. Without this, Tier 1
            # would be unmeasurable on exactly the data that matters most.
            #
            # `explained_by_basis` is the circularity split: SCHEMA money is typed
            # from documented Sec 3.1 fields the gateway asserts and would read the
            # same from a real report; CONTRACT money is derived from a rate-card
            # constant we also generated with, so it is partly circular. Published
            # so the limit of the eval result is a number, not a caveat in prose.
            # BRIEF Sec 7's ablation. NOT a second run: tier is an attribute of an
            # EDGE (invariant 5), so "what would we have got with only tier <= N"
            # is a group-by over the edges we already have. That is the entire
            # reason tier was put on the edge rather than on the row.
            "ablation": dict(sorted(self.ablation.items())),
            "decomposition": {
                "closure": self.decomposition_closure.to_json(),
                "explained_by_basis": dict(sorted(self.explained_by_basis.items())),
            },
            "residual_distribution": {
                "residual_total_paise": int(self.residual_total),
                "by_component": dict(sorted(self.residual_by_component.items())),
                "built_tier": BUILT_TIER,
            },
            "counts": dict(sorted(self.counts.items())),
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"), indent=1),
            encoding="utf-8")

    def render(self) -> str:
        lines = [
            "HEADLINE",
            "  " + self.explanation_rate_bank.line(),
            "  " + self.settlement_coverage.line(),
            "  " + self.money_weighted_coverage.line(),
            f"  {'value reconciled':<44} {format_inr(self.money_explained):>18}"
            f" of {format_inr(self.money_total)}",
            "",
            "SUPPORTING",
            "  " + self.match_rate_line_items.line(),
            "",
            "ACCURACY vs ground truth",
            "  " + self.linkage_precision.line(),
            "  " + self.linkage_recall.line(),
            "  " + self.exception_detection_recall.line(),
            "  " + self.false_clear_rate.line(),
            "  " + self.false_clear_in_remit.line() + "   <-- the dangerous class",
            "  " + self.false_clear_out_of_remit.line()
            + f"   (needs tier > {BUILT_TIER})",
            "  " + self.exception_typing_accuracy.line(),
            "",
            "DATA REALISM (from ground truth, no resolver involved)",
            "  " + self.intrinsic_clean_rate.line(),
            "  " + self.narration_parse_rate.line(),
            "",
            "ABLATION -- headline grain, cumulative by tier (a group-by, not a re-run)",
        ]
        for name, row in sorted(self.ablation.items()):
            lines.append(
                f"  {name:<30} {format_bps(row['rate_bps']):>8}  "
                f"({row['explained']}/{row['bank_credits']})"
                + (f"   +{format_bps(row['delta_bps'])}" if row["delta_bps"] else ""))
        lines += [
            "",
            "TIER 1 DECOMPOSITION (no linkage, no ground truth)",
            "  " + self.decomposition_closure.line(),
        ]
        if self.explained_by_basis:
            total = max(1, sum(self.explained_by_basis.values()))
            for basis, amount in sorted(self.explained_by_basis.items()):
                label = ("typed from documented schema fields" if basis == "schema"
                         else "typed from contracted rate constants")
                lines.append(f"  {label:<44} {format_bps(ratio_bps(amount, total)):>8}"
                             f"  {format_inr(Paise(amount))}")
            lines.append("  " + "contract-derived money is partly circular: the eval seed "
                                "shares our rate card")

        if self.residual_by_component:
            lines += [
                "",
                f"RESIDUAL AT TIER {BUILT_TIER}, BY TRUE COMPONENT"
                f"        total {format_inr(self.residual_total)}",
            ]
            # Share of gross movement, not of the net residual: RESERVE_RELEASE is
            # negative, so shares against the net would sum well past 100% and
            # read as an error.
            denominator = max(1, sum(abs(v) for v in self.residual_by_component.values()))
            for kind, amount in sorted(self.residual_by_component.items(),
                                       key=lambda kv: (-abs(kv[1]), kv[0])):
                share = ratio_bps(abs(amount), denominator)
                lines.append(f"  {kind:<30} {format_inr(Paise(amount)):>18}"
                             f"  {format_bps(share):>8} of movement")
        return "\n".join(lines)


def compute(edges: list[ReconEdge], exceptions: list[ExceptionRecord],
            truth: GroundTruth, repo) -> Metrics:
    bank_edges = [e for e in edges if e.kind is EdgeKind.BANK_TO_SETTLEMENT]
    line_edges = [e for e in edges if e.kind is EdgeKind.SETTLEMENT_TO_LINE]

    explained_bank = [e for e in bank_edges if e.status is EdgeStatus.EXPLAINED]
    explained_settlement_ids = {e.dst_uid for e in explained_bank}

    # --- headline -------------------------------------------------------------
    explanation_rate_bank = Rate(
        len(explained_bank), len(repo.bank),
        "explanation rate (bank credits, residual==0)")

    settlement_coverage = Rate(
        len(explained_settlement_ids), len(repo.settlements),
        "settlement coverage (settlements fully explained)")

    # Money-weighted at the settlement grain, on GROSS, because gross is what the
    # receivable was raised at. Sec 7: 95% of records but 60% of value is a bad
    # result, and count-only metrics hide it.
    members_by_settlement = repo.lines_by_settlement()
    money_total = 0
    money_explained = 0
    for settlement_id, members in members_by_settlement.items():
        gross = sum(m.amount for m in members)
        money_total += gross
        if settlement_id in explained_settlement_ids:
            money_explained += gross

    money_weighted_coverage = Rate(
        money_explained, money_total, "money-weighted coverage (gross value)")

    match_rate_line_items = Rate(
        len([e for e in line_edges if e.status is EdgeStatus.EXPLAINED]),
        len(repo.lines), "match rate (line items -> settlement)")

    # --- accuracy vs ground truth --------------------------------------------
    truth_edges = truth.edge_keys()
    predicted = {(e.kind.value, e.src_uid, e.dst_uid) for e in edges if e.status in ACCEPTED}
    correct = predicted & truth_edges

    linkage_precision = Rate(len(correct), len(predicted),
                             "linkage precision (of what we matched)")
    linkage_recall = Rate(len(correct), len(truth_edges),
                          "linkage recall (of true links)")

    # Exception detection: did we flag the units truth says are broken?
    truth_breaks = {u.uid: u for u in truth.anomalous_units(breaks_only=True)}
    flagged_subjects = {r.subject_id for r in exceptions}
    caught = {uid for uid in truth_breaks if uid in flagged_subjects}
    missed = set(truth_breaks) - caught

    exception_detection_recall = Rate(
        len(caught), len(truth_breaks), "exception detection recall (injected breaks caught)")

    # FALSE-CLEAR: an injected break we did not flag is one we passed as fine.
    # The most dangerous error class in reconciliation: a missed match costs an
    # analyst ten minutes, a false clear means money leaves the reconciliation
    # and nobody looks again.
    #
    # SPLIT BY REMIT, because the raw number conflates two different things. A
    # break the built resolver was supposed to catch and did not is the dangerous
    # class and must be zero. A break whose detection needs a tier that does not
    # exist yet was never looked at -- reporting that as a silent pass would be
    # self-flagellation, and worse, it would hide the real defects among it.
    by_code = {e.code: e for e in ExceptionType}
    missed_in_remit = {uid for uid in missed
                       if by_code[truth_breaks[uid].anomaly].in_remit_of(BUILT_TIER)}
    missed_out_of_remit = missed - missed_in_remit
    in_remit_breaks = {uid for uid, unit in truth_breaks.items()
                       if by_code[unit.anomaly].in_remit_of(BUILT_TIER)}

    false_clear_rate = Rate(len(missed), len(truth_breaks),
                            "FALSE-CLEAR rate, all breaks")
    false_clear_in_remit = Rate(
        len(missed_in_remit), len(in_remit_breaks),
        f"FALSE-CLEAR within tier<={BUILT_TIER} remit")
    false_clear_out_of_remit = Rate(
        len(missed_out_of_remit), len(truth_breaks) - len(in_remit_breaks),
        "not attempted (no resolver built yet)")

    # --- properties of the DATA, not of the resolver --------------------------
    # Answers "is the synthetic data too clean?" (BRIEF Sec 5: 85-92% cleanly
    # resolvable). Computed from ground truth alone: the resolver's explanation
    # rate answers a different question and must not be confused with this one.
    clean_units = sum(1 for u in truth.units if u.anomaly is None)
    intrinsic_clean_rate = Rate(clean_units, len(truth.units),
                                "intrinsic clean rate (units with no injected anomaly)")
    injected_by_class: dict[str, int] = {}
    for unit in truth.units:
        if unit.anomaly is not None:
            injected_by_class[unit.anomaly] = injected_by_class.get(unit.anomaly, 0) + 1

    # How often the DETERMINISTIC parser found a UTR at all. Reported per run, and
    # a run is one narration split, so dev vs eval is a direct comparison. This is
    # the number the Increment 3 LLM ablation has to beat -- published now, before
    # any LLM exists, so it cannot be chosen after the fact.
    parsed = sum(1 for credit in repo.bank.values()
                 if parse_utr(credit.narration) is not None)
    narration_parse_rate = Rate(parsed, len(repo.bank),
                                "narration parse rate (UTR extracted by regex)")

    # Tier 1's arithmetic, isolated from linkage. Imported here rather than at
    # module scope to keep the report layer from depending on a resolver at import
    # time -- the dependency is real but it is a measurement, not a pipeline step.
    from ..resolve.tier1 import closure_report

    closed, total_settlements, explained_by_basis = closure_report(repo)

    # The Sec 7 ablation, cumulative. An edge carries the tier that produced its
    # CURRENT status, so "explained with only tier <= N" is a filter, and the
    # table falls out by construction rather than being reconstructed later.
    ablation: dict[str, dict] = {}
    previous_bps = 0
    # Span every tier actually represented, not just BUILT_TIER: an adjudicator
    # may be configured at runtime even though the remit ceiling has not moved.
    highest = max([BUILT_TIER] + [max(e.tier.value, e.established_by.value)
                                  for e in bank_edges] or [BUILT_TIER])
    for tier in sorted(Tier, key=lambda x: x.value):
        if tier.value > highest:
            break
        # An edge counts at tier N only if BOTH its linkage and its explanation
        # are within N -- an LLM-linked, Tier-1-explained edge is not something
        # Tier 1 alone could have produced.
        explained_at = len([e for e in bank_edges
                            if e.status is EdgeStatus.EXPLAINED
                            and max(e.tier.value, e.established_by.value) <= tier.value])
        rate = ratio_bps(explained_at, len(repo.bank))
        ablation[f"T{tier.value}_{tier.name.split('_', 1)[1].lower()}"] = {
            "explained": explained_at,
            "bank_credits": len(repo.bank),
            "rate_bps": rate,
            "delta_bps": rate - previous_bps,
        }
        previous_bps = rate
    decomposition_closure = Rate(
        closed, total_settlements,
        "decomposition closure (gross->net gap fully typed)")

    # --- what the built tier could not explain, by its TRUE cause -------------
    # Tier 0 types MDR and GST from reported values, so its residual on a
    # settlement is exactly the sum of every OTHER true component. Bucketing it
    # that way says how much of the gap an arithmetic Tier 1 could reach, and how
    # much would still be scattered -- which is the Increment 2 fork.
    tier0_typed = {ComponentType.MDR.value, ComponentType.GST_ON_MDR.value}
    residual_by_component: dict[str, int] = {}
    residual_total = 0
    for edge in bank_edges:
        if edge.status is EdgeStatus.EXPLAINED or edge.decomposition is None:
            continue
        residual_total += int(edge.decomposition.residual)
        for component in truth.components.get(edge.dst_uid, ()):
            if component.kind in tier0_typed:
                continue
            residual_by_component[component.kind] = (
                residual_by_component.get(component.kind, 0) + component.amount)

    # Typing: of the breaks we caught, did we give them the right code?
    by_subject: dict[str, str] = {}
    for record in exceptions:
        by_subject.setdefault(record.subject_id, record.code)
    typed_right = sum(1 for uid in caught if by_subject.get(uid) == truth_breaks[uid].anomaly)
    exception_typing_accuracy = Rate(typed_right, len(caught),
                                     "exception typing accuracy (correct code)")

    counts = {
        "edges_total": len(edges),
        "edges_explained": len([e for e in edges if e.status is EdgeStatus.EXPLAINED]),
        "edges_matched_not_explained": len([e for e in edges
                                            if e.status is EdgeStatus.MATCHED]),
        "exceptions_total": len(exceptions),
        "exceptions_breaks": len([r for r in exceptions if r.is_break]),
        "exceptions_informational": len([r for r in exceptions if not r.is_break]),
        "quarantined_rows": len(repo.quarantined),
        "records_ingested": repo.total_records,
        "bank_credits": len(repo.bank),
        "settlements": len(repo.settlements),
        "line_items": len(repo.lines),
        "book_entries": len(repo.books),
    }

    return Metrics(
        explanation_rate_bank=explanation_rate_bank,
        settlement_coverage=settlement_coverage,
        match_rate_line_items=match_rate_line_items,
        money_weighted_coverage=money_weighted_coverage,
        money_total=Paise(money_total),
        money_explained=Paise(money_explained),
        linkage_precision=linkage_precision,
        linkage_recall=linkage_recall,
        exception_detection_recall=exception_detection_recall,
        false_clear_rate=false_clear_rate,
        false_clear_in_remit=false_clear_in_remit,
        false_clear_out_of_remit=false_clear_out_of_remit,
        exception_typing_accuracy=exception_typing_accuracy,
        intrinsic_clean_rate=intrinsic_clean_rate,
        narration_parse_rate=narration_parse_rate,
        decomposition_closure=decomposition_closure,
        explained_by_basis=explained_by_basis,
        ablation=ablation,
        residual_total=Paise(residual_total),
        residual_by_component=residual_by_component,
        injected_by_class=injected_by_class,
        counts=counts,
    )
