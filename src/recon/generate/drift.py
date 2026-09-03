"""Schema-drift scenarios: a registry of ways a source extract changes its shape.

WHY THIS LIVES IN `generate/` AND NOT IN A TEST
-----------------------------------------------
Drift is not a property of the world. The merchant's money does not change when a
bank renames a column -- the *extract* does. So this sits beside `derive`, which
is the layer that turns the simulated world into the four views a reconciler
actually receives, and not in `world.py`, which owns truth.

It is a registry in the same shape as `narration.TemplateFamily` for the same
reason: the alternative is drift shapes scattered across test bodies, where
nothing can enumerate them, no two agree on the rename, and the count of "how many
shapes do we handle" is unanswerable.

WHAT A SCENARIO IS, AND THE ONE THING IT MUST DO
------------------------------------------------
A scenario renames columns in exactly one view. To be worth anything it must make
that view FAIL validation, because `map_schema` only ever sees quarantined rows.

That rules out a shape it is tempting to include and which does not work: a pure
SWAP of two same-typed columns. `extra="forbid"` catches a name it does not
recognise; it cannot catch a name it recognises holding the wrong value. A swap
validates cleanly, never quarantines, and flows straight through to Tier 0. See
S9, which forces quarantine with a third rename so the swap can still be tested,
and F-020, which records the blind spot itself.

TRUTH IS DERIVED, NEVER WRITTEN TWICE
--------------------------------------
`truth_mapping` is computed by inverting the renames against the columns actually
present in the file. Hand-writing the expected answer next to the rename would let
the two drift apart, and the scoring would then measure the transcription.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..ingest.load import BANK_VIEW, BOOKS_VIEW, LINES_VIEW, SETTLEMENTS_VIEW

# Shape labels, used for grouping in the result table rather than for behaviour.
SINGLE_OBVIOUS = "single obvious"
SINGLE_AMBIGUOUS = "single ambiguous"
MULTIPLE = "multiple at once"
MISLEADING = "misleading name"
OPAQUE = "opaque, no name signal"


@dataclass(frozen=True, slots=True)
class DriftScenario:
    """One named way a view's column names can differ from the schema.

    `renames` is (field as the schema declares it -> name as the file carries it).
    That direction is deliberate: it reads as "what happened to the file", and the
    mapping the model must produce is its inverse, which `truth_mapping` derives.
    """

    name: str
    view: str
    shape: str
    renames: tuple[tuple[str, str], ...]
    note: str = ""

    @property
    def applied(self) -> dict[str, str]:
        return dict(self.renames)


# The suite is pre-registered in RUN_LOG (03 Sep 2026) with a prediction per
# scenario. Do not add, remove or adjust one after a run without saying so there:
# a scenario tuned to a result is a scenario that measures the tuning.
SCENARIOS: tuple[DriftScenario, ...] = (
    DriftScenario(
        "S1_bank_narration", BANK_VIEW, SINGLE_OBVIOUS,
        (("narration", "description"),),
        "the only free-text field in the view; a floor, not a test"),
    DriftScenario(
        "S2_lines_entity_id", LINES_VIEW, SINGLE_OBVIOUS,
        (("entity_id", "entity_ref"),),
        "the 03 Sep n=1 case, kept so the sample includes it"),
    DriftScenario(
        "S3_settlements_fees", SETTLEMENTS_VIEW, SINGLE_AMBIGUOUS,
        (("fees", "charges"),),
        "`tax` is also charge-shaped; only magnitude separates them"),
    DriftScenario(
        "S4_lines_created_at", LINES_VIEW, SINGLE_AMBIGUOUS,
        (("created_at", "date"),),
        "three date fields exist; a generic name forces value ordering"),
    DriftScenario(
        "S5_bank_three", BANK_VIEW, MULTIPLE,
        (("narration", "remarks"), ("value_date", "txn_date"), ("bank_ref", "ref_no")),
        "half the view at once, each plausible in isolation"),
    DriftScenario(
        "S6_lines_money_three", LINES_VIEW, MULTIPLE,
        (("fee", "commission"), ("tax", "gst"), ("amount", "gross")),
        "three money fields with real-world-plausible aliases"),
    DriftScenario(
        "S7_lines_credit_debit", LINES_VIEW, MISLEADING,
        (("credit", "debit_amount"), ("debit", "credit_amount")),
        "the new name asserts the opposite field; one side is always 0"),
    DriftScenario(
        "S8_books_gross", BOOKS_VIEW, MISLEADING,
        (("gross_amount", "net_amount"),),
        "name says net, values are gross -- but only one money field exists"),
    DriftScenario(
        # AMENDED before running: `id`->`ref` forces the quarantine that makes the
        # swap testable at all. See the RUN_LOG addendum, 03 Sep.
        "S9_settlements_swap", SETTLEMENTS_VIEW, MISLEADING,
        (("id", "ref"), ("amount", "fees"), ("fees", "amount")),
        "both new names are real fields holding each other's values"),
    DriftScenario(
        "S10_books_opaque", BOOKS_VIEW, OPAQUE,
        (("currency", "c1"), ("customer_id", "c2"), ("gross_amount", "c3"),
         ("invoice_date", "c4"), ("method", "c5"), ("order_id", "c6"),
         ("receipt", "c7")),
        "no name signal at all; three of the seven are unconstrained strings"),
)

# Scenarios added AFTER the 03 Sep pre-registration, kept in a separate tuple so
# the measured suite stays exactly the ten it was registered at. The published
# "8/10" is a fact about SCENARIOS and must not quietly become 8/11 because a
# regression fixture was appended to the same list.
REGRESSION_SCENARIOS: tuple[DriftScenario, ...] = (
    DriftScenario(
        # F-022. Both fields are `str | None`, so this re-validates, touches no
        # money column, leaves entity_id unique, and names only real fields --
        # every one of gates 1-4 passes. It is the reason gate 5 exists.
        "R1_lines_fk_swap", LINES_VIEW, MISLEADING,
        (("order_id", "payment_ref"), ("payment_id", "order_ref")),
        "a foreign-key swap: every row-level signal reads clean, 78 breaks vanish"),
)

BY_NAME = {scenario.name: scenario
           for scenario in SCENARIOS + REGRESSION_SCENARIOS}


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def truth_mapping(scenario: DriftScenario, src_dir: Path) -> dict[str, str]:
    """The mapping a perfect answer would return: observed column -> target field.

    Derived from the file, not written by hand, so it cannot disagree with what
    `apply` actually did.
    """
    # joinpath, not `/`: pathlib overloads the operator into ast.Div and the float
    # scan bans it outside four named modules (D-006, F-003).
    columns: set[str] = set()
    for row in _rows(src_dir.joinpath(scenario.view)):
        columns.update(row)

    # For every column the SOURCE has: what the drifted file calls it, and what the
    # schema calls it. One entry per column, so the mapping is total by
    # construction and a renamed field cannot silently go missing.
    applied = scenario.applied
    return {applied.get(original, original): original for original in columns}


def observed_columns(scenario: DriftScenario, src_dir: Path) -> list[str]:
    """What the drifted file will present, in the order the payload sorts them."""
    columns: set[str] = set()
    for row in _rows(src_dir.joinpath(scenario.view)):
        columns.update(row)
    applied = scenario.applied
    return sorted(applied.get(column, column) for column in columns)


def apply(scenario: DriftScenario, src_dir: Path, dst_dir: Path) -> Path:
    """Copy `src_dir` and rewrite one view's column names. Returns `dst_dir`.

    Never mutates the source. The generated seed stays exactly what every other
    gate measures against; a scenario is a view of it, not a change to it.
    """
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)

    path = dst_dir.joinpath(scenario.view)
    applied = scenario.applied
    rows = _rows(path)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            renamed = {applied.get(key, key): value for key, value in row.items()}
            handle.write(json.dumps(renamed, sort_keys=True,
                                    separators=(",", ":")) + "\n")
    return dst_dir
