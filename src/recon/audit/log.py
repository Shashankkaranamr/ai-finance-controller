"""Append-only decision log. The run must be reconstructible from this alone.

BRIEF Sec 4.1: "every match, the tier, the inputs, the rule or prompt version,
timestamp. Reproducible from the log alone." Razorpay's own general bar reads
"every money action explainable, bounded and gated. Show the audit trail."

DETERMINISM AND TIMESTAMPS
--------------------------
An audit trail without a wall-clock time is not an audit trail; byte-identical
output with one is impossible. So the boundary is explicit: the FIRST line
carries the real `started_at`, and every entry after it carries a monotonic
`seq` instead. The determinism test therefore asserts that everything after line
one is byte-identical between runs, which is a stronger and more honest claim
than dropping timestamps entirely.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def run_id_for(source_files: list[Path], rule_version: str) -> str:
    """Idempotency key: content of the inputs plus the rules applied to them.

    BRIEF Sec 8 requires that re-ingesting the same file must not double-post
    journal entries. Keying on content rather than filename or run time means a
    re-run of identical inputs is recognisable as the same run.
    """
    digest = hashlib.sha256()
    for path in sorted(source_files, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    digest.update(rule_version.encode("utf-8"))
    return digest.hexdigest()[:16]


@dataclass(slots=True)
class AuditLog:
    run_id: str
    rule_version: str
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    entries: list[dict] = field(default_factory=list)

    def record(self, event: str, **fields) -> None:
        self.entries.append({"seq": len(self.entries) + 1, "event": event, **fields})

    def record_edge(self, event: str, edge, **fields) -> None:
        self.record(event, edge=edge.ref, kind=edge.kind.value, status=edge.status.value,
                    tier=edge.tier.name, confidence=edge.confidence, **fields)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "event": "run_started",
            "run_id": self.run_id,
            "rule_version": self.rule_version,
            "started_at": self.started_at,   # the only non-deterministic field
        }
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n")
            for entry in self.entries:
                handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
