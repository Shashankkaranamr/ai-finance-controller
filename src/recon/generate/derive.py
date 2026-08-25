"""Derive the three source views from the simulated world.

Each view is what ONE system would have recorded, with no knowledge of the
others. The books do not know the UTR; the bank does not know the order ids; the
settlement report is the only place they meet -- and only via keys that a
reconciler has to work for.
"""
from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

from ..domain.truth import GroundTruth
from .narration import SPLIT_DEV, families_for, render
from .world import GenConfig, Payment, World, bank_uid_for, build_world, emit_ground_truth


def _stream(seed: str, name: str) -> random.Random:
    """An independent, named random stream.

    Separate streams per view mean that changing how books are generated does not
    shift every bank narration downstream -- diffs between runs stay legible.
    """
    return random.Random(zlib.crc32(f"{seed}:{name}".encode("utf-8")))


def derive_books(world: World) -> list[dict]:
    """ERP view: what the merchant's own system believes it sold."""
    return [
        {
            "order_id": o.order_id,
            "receipt": o.receipt,
            "customer_id": o.customer_id,
            "gross_amount": int(o.gross),
            "currency": "INR",
            "invoice_date": o.created_on.isoformat(),
            "method": o.method,
        }
        for o in world.orders
    ]


def derive_settlement(world: World) -> list[dict]:
    """Razorpay settlement recon report view (BRIEF Sec 3.1 field names).

    Increment 0 emits the payment-line subset of the schema. The full field set,
    plus refund/transfer/adjustment types, lands in Increment 1.
    """
    by_id = {s.settlement_id: s for s in world.settlements}
    rows: list[dict] = []
    for p in world.payments:
        settlement = by_id[p.settlement_id]
        rows.append({
            "entity_id": p.line_id,
            "type": "payment",
            "debit": 0,
            "credit": int(p.credit),          # amount - fee
            "amount": int(p.amount),
            "currency": "INR",
            "fee": int(p.fee),                # INCLUSIVE of tax
            "tax": int(p.tax),                # memo breakout of GST inside fee
            "on_hold": False,
            "settled": True,
            "created_at": p.captured_on.isoformat(),
            "settled_at": p.settled_on.isoformat(),
            "settlement_id": p.settlement_id,
            "settlement_utr": settlement.utr,
            "payment_id": p.payment_id,
            "order_id": p.order_id,
            "method": p.method,
        })
    return rows


def derive_settlement_entities(world: World) -> list[dict]:
    """The settlement entity itself (BRIEF Sec 3.1: id, amount, status, fees, tax, utr).

    This is a SEPARATE view on purpose. In production it comes from a different
    endpoint than the recon line items, and reporting `amount` independently is
    what makes the rollup identity a real cross-check. If we derived it by summing
    the same line items we later check it against, the identity would be
    tautological and the test would prove nothing.
    """
    members: dict[str, list[Payment]] = {}
    for p in world.payments:
        members.setdefault(p.settlement_id, []).append(p)

    return [
        {
            "id": s.settlement_id,
            "entity": "settlement",
            "amount": int(s.amount),
            "status": "processed",
            "fees": sum(int(p.fee) for p in members.get(s.settlement_id, [])),
            "tax": sum(int(p.tax) for p in members.get(s.settlement_id, [])),
            "utr": s.utr,
            "created_at": s.settled_on.isoformat(),
        }
        for s in world.settlements
    ]


def derive_bank(world: World) -> list[dict]:
    """Bank statement view: one lump credit per settlement, messy narration.

    A settlement flagged `has_bank_credit=False` simply produces no row -- which
    is exactly what a missing credit looks like in the real world. There is no
    marker for the reconciler to find; the absence IS the anomaly.
    """
    rng = _stream(world.config.seed, "bank")
    dev_families = families_for(SPLIT_DEV)
    rows: list[dict] = []

    for settlement in world.settlements:
        if not settlement.has_bank_credit:
            continue
        family = rng.choice(dev_families)
        rows.append({
            "bank_ref": bank_uid_for(settlement),
            "value_date": settlement.settled_on.isoformat(),
            "amount": int(settlement.amount),
            "currency": "INR",
            "narration": render(family, settlement.utr, rng),
            "narration_family": family.name,   # provenance only; resolvers must not read this
        })
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def generate(config: GenConfig, out_dir: Path) -> tuple[World, GroundTruth]:
    """Build the world, derive the views, emit ground truth. Fully deterministic."""
    world = build_world(config)
    truth = emit_ground_truth(world)

    _write_jsonl(out_dir / "books.jsonl", derive_books(world))
    _write_jsonl(out_dir / "settlement_lines.jsonl", derive_settlement(world))
    _write_jsonl(out_dir / "settlements.jsonl", derive_settlement_entities(world))
    _write_jsonl(out_dir / "bank.jsonl", derive_bank(world))
    truth.write(out_dir / "ground_truth.json")

    return world, truth
