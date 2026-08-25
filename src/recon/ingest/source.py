"""Where settlement data comes from.

PLAN.md assumption #3: the evaluation runs on synthetic data, which the track
explicitly permits. But an interface costs nothing and an unbacked claim costs
credibility, so the seam that a real Razorpay client would plug into is defined
here rather than described in a README.

`FileSource` is the only implementation in Increment 0. A read-only
`RazorpayAPISource` against test mode is roughly an hour's work behind this
protocol if Increment 6 has the time; if it does not, nothing in the repo claims
otherwise.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .load import Repository, load_all


@runtime_checkable
class SettlementSource(Protocol):
    """Anything that can supply the four views the reconciler needs."""

    @property
    def name(self) -> str: ...

    def fetch(self) -> Repository: ...


class FileSource:
    """The generated (or exported) JSONL views on disk."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    @property
    def name(self) -> str:
        return f"file:{self._data_dir.name}"

    def fetch(self) -> Repository:
        return load_all(self._data_dir)
