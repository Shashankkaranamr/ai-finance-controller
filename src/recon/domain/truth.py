"""Ground truth -- designed backwards from "what does false-clear need?".

FALSE-CLEAR is the dangerous error class in reconciliation (BRIEF Sec 7): an
anomaly the system wrongly marked resolved. A missed match costs an analyst ten
minutes; a false clear means real money silently leaves the reconciliation and
nobody looks again.

To compute it we need truth about EXPLANATION, not just about linkage:

  * per unit  -- was an anomaly injected here, which one, and is it a break?
  * per edge  -- what SHOULD have linked to what
  * per settlement -- the true typed decomposition, so a residual that happens to
                      land on zero via compensating errors is still catchable

That third item is the reason this file exists separately from the generator.
Truth is emitted by the world simulator (generate/world.py) and never derived
from the source views, because labelling views after the fact would encode the
matcher's own assumptions and the eval would then measure agreement with itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TruthComponent:
    kind: str      # ComponentType.value
    amount: int    # paise

    def to_json(self) -> dict:
        return {"kind": self.kind, "amount": self.amount}


@dataclass(frozen=True, slots=True)
class TruthEdge:
    kind: str      # EdgeKind.value
    src_uid: str
    dst_uid: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.kind, self.src_uid, self.dst_uid)

    def to_json(self) -> dict:
        return {"kind": self.kind, "src_uid": self.src_uid, "dst_uid": self.dst_uid}


@dataclass(frozen=True, slots=True)
class TruthUnit:
    kind: str              # UnitKind.value
    uid: str
    amount: int            # paise
    anomaly: str | None    # ExceptionType.code, or None for a clean unit
    is_break: bool         # False for explained-but-notable (Sec 6)

    def to_json(self) -> dict:
        return {"kind": self.kind, "uid": self.uid, "amount": self.amount,
                "anomaly": self.anomaly, "is_break": self.is_break}


@dataclass(frozen=True, slots=True)
class GroundTruth:
    seed: str
    units: tuple[TruthUnit, ...]
    edges: tuple[TruthEdge, ...]
    # True decomposition keyed by settlement uid. Lets us catch a residual that
    # nets to zero through compensating errors -- which would otherwise look
    # like a clean explanation.
    components: dict[str, tuple[TruthComponent, ...]]

    # -- lookups the metrics harness needs ------------------------------------

    def unit(self, uid: str) -> TruthUnit | None:
        return next((u for u in self.units if u.uid == uid), None)

    def units_by_uid(self) -> dict[str, TruthUnit]:
        """Build once in the metrics harness rather than scanning per lookup."""
        return {u.uid: u for u in self.units}

    def anomalous_units(self, breaks_only: bool = True) -> tuple[TruthUnit, ...]:
        return tuple(u for u in self.units
                     if u.anomaly is not None and (u.is_break or not breaks_only))

    def edge_keys(self) -> set[tuple[str, str, str]]:
        return {e.key for e in self.edges}

    # -- serialization ---------------------------------------------------------

    def to_json(self) -> dict:
        """Fully sorted: ground_truth.json must be byte-identical across runs."""
        return {
            "seed": self.seed,
            "units": [u.to_json() for u in sorted(self.units, key=lambda u: (u.kind, u.uid))],
            "edges": [e.to_json() for e in sorted(self.edges, key=lambda e: e.key)],
            "components": {
                uid: [c.to_json() for c in sorted(comps, key=lambda c: c.kind)]
                for uid, comps in sorted(self.components.items())
            },
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"), indent=1),
            encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "GroundTruth":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            seed=raw["seed"],
            units=tuple(TruthUnit(**u) for u in raw["units"]),
            edges=tuple(TruthEdge(**e) for e in raw["edges"]),
            components={uid: tuple(TruthComponent(**c) for c in comps)
                        for uid, comps in raw["components"].items()},
        )
