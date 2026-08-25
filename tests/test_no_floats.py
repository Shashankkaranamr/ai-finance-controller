"""Assert, by AST scan, that no float exists anywhere in the package.

BRIEF Sec 9 lists floats for money as an instant build-quality tell. A comment
saying "use ints" is a style rule; this is a checkable property, which is the
difference between claiming discipline and having it.

The scan covers the WHOLE `recon` package, not a hand-picked "money path". That
is only possible because rates are carried as integer basis points and timing
uses perf_counter_ns -- both deliberate choices made to keep this test total.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "recon"
MODULES = sorted(SRC.rglob("*.py"))

# pathlib overloads `/` for path joining, which parses as ast.Div. These modules
# build paths, so the division rule is not applied to them. The float-literal and
# `float` rules still are, everywhere, with no exceptions.
#
# The list is an EXCLUSION rather than an allowlist on purpose: a new module is
# strict by default, and adding one here is a visible decision in review.
PATH_JOINING_MODULES = {"__main__.py", "pipeline.py", "derive.py", "load.py"}


def test_the_scan_actually_finds_files():
    """A green test over an empty file list proves nothing."""
    assert len(MODULES) >= 15, f"expected the package to be scanned, found {len(MODULES)}"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_module_contains_no_float(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offences: list[str] = []

    for node in ast.walk(tree):
        # A float literal anywhere.
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offences.append(f"line {node.lineno}: float literal {node.value!r}")

        # True division always produces a float in Python 3, even on two ints.
        if path.name not in PATH_JOINING_MODULES:
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                offences.append(f"line {node.lineno}: true division '/' (use '//')")
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Div):
                offences.append(f"line {node.lineno}: augmented true division '/='")

        # Any call to float(), or an annotation of type float.
        if isinstance(node, ast.Name) and node.id == "float":
            offences.append(f"line {node.lineno}: reference to 'float'")

    assert not offences, (
        f"{path.relative_to(SRC.parent.parent)} is not float-free:\n  "
        + "\n  ".join(offences))
