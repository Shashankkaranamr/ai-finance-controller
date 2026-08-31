"""Derive the four source views from the simulated world.

Each view is what ONE system would have recorded, with no knowledge of the
others. The books do not know the UTR; the bank does not know the order ids; the
settlement report is the only place they meet -- and only via keys that a
reconciler has to work for.

INCREMENT 1: THE FULL Sec 3.1 FIELD SET
---------------------------------------
Every documented field is emitted, including the ones no resolver reads yet
(`credit_type`, `card_issuer`, `notes`). That is deliberate. `extra="forbid"` on
the ingest schemas means a field we do not declare is a hard failure, so the
shape of the report is pinned now rather than discovered later -- and a reviewer
comparing against `razorpay-node`'s settlement.md finds the same columns.

Absent values are emitted as `null`, never as "" or 0. A refund has no
`card_network`; writing an empty string there would make "no network" and
"network unknown" the same value, which is exactly the ambiguity that turns into
a silent join failure three tiers later.
"""
from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

from ..domain.truth import GroundTruth
from .narration import families_for, render
from .world import GenConfig, World, bank_uid_for, build_world, emit_ground_truth


def _stream(seed: str, name: str) -> random.Random:
    """An independent, named random stream.

    Separate streams per view mean that changing how books are generated does not
    shift every bank narration downstream -- diffs between runs stay legible.
    """
    return random.Random(zlib.crc32(f"{seed}:{name}".encode("utf-8")))


def derive_books(world: World) -> list[dict]:
    """ERP view: what the merchant's own system believes it sold.

    Sales grain only. The ERP books invoices, not gateway fees -- which is why
    the deduction stack is invisible here and has to be explained from the other
    two views. `gross_amount` is what the ERP RECORDED, so a manual-entry error
    shows up as a genuine disagreement rather than as a copy of the truth.
    """
    return [
        {
            "order_id": order.order_id,
            "receipt": order.receipt,
            "customer_id": order.customer_id,
            "gross_amount": int(order.booked_gross if order.booked_gross is not None
                                else order.gross),
            "currency": "INR",
            "invoice_date": order.invoice_on.isoformat(),
            "method": order.instrument.method,
        }
        for order in world.orders
    ]


def derive_settlement(world: World) -> list[dict]:
    """Razorpay settlement recon report view -- the full BRIEF Sec 3.1 field set."""
    by_id = {s.settlement_id: s for s in world.settlements}
    rows: list[dict] = []

    for line in world.lines:
        settlement = by_id[line.settlement_id]
        instrument = line.instrument
        rows.append({
            "entity_id": line.line_id,
            "type": line.kind,
            "debit": int(line.debit),
            "credit": int(line.credit),
            "amount": int(line.amount),
            "currency": "INR",
            "fee": int(line.fee),          # INCLUSIVE of tax
            "tax": int(line.tax),          # memo breakout of the GST inside fee
            "on_hold": line.on_hold,
            "settled": line.settled,
            "created_at": line.created_on.isoformat(),
            "settled_at": line.settled_on.isoformat(),
            "posted_at": line.posted_on.isoformat(),
            "settlement_id": line.settlement_id,
            "settlement_utr": settlement.utr,
            "credit_type": "default",
            "description": line.description,
            "notes": line.notes,
            "payment_id": line.payment_id,
            "order_id": line.order_id,
            "order_receipt": line.order_receipt,
            "method": instrument.method if instrument else None,
            "card_network": instrument.card_network if instrument else None,
            "card_issuer": line.card_issuer,
            "card_type": instrument.card_type if instrument else None,
            "dispute_id": line.dispute_id,
        })
    return rows


def derive_settlement_entities(world: World) -> list[dict]:
    """The settlement entity itself (BRIEF Sec 3.1: id, amount, status, fees, tax, utr).

    This is a SEPARATE view on purpose. In production it comes from a different
    endpoint than the recon line items, and reporting `amount` independently is
    what makes the rollup identity a real cross-check. If we derived it by summing
    the same line items we later check it against, the identity would be
    tautological and the test would prove nothing (D-003).
    """
    rows: list[dict] = []
    for settlement in world.settlements:
        lines = world.lines_of(settlement.settlement_id)
        rows.append({
            "id": settlement.settlement_id,
            "entity": "settlement",
            "amount": int(settlement.amount),
            "status": "processed",
            "fees": sum(int(line.fee) for line in lines),
            "tax": sum(int(line.tax) for line in lines),
            "utr": settlement.utr,
            "created_at": settlement.settled_on.isoformat(),
        })
    return rows


def derive_bank(world: World, config: GenConfig) -> list[dict]:
    """Bank statement view: one lump credit per settlement, messy narration.

    A settlement flagged `has_bank_credit=False` simply produces no row -- which
    is exactly what a missing credit looks like in the real world. There is no
    marker for the reconciler to find; the absence IS the anomaly.

    Narration families are drawn from `config.split`. The eval seed renders from
    HELD-OUT families the deterministic parser was never written against
    (PLAN.md deviation #4), so the Increment 3 ablation is held out at the
    template level and not merely at the seed level.
    """
    rng = _stream(config.seed, "bank")
    families = families_for(config.split)
    if not families:
        raise ValueError(f"no narration families for split {config.split!r}")

    rows: list[dict] = []
    for settlement in world.settlements:
        if not settlement.has_bank_credit:
            continue
        family = rng.choice(families)
        rows.append({
            "bank_ref": bank_uid_for(settlement),
            "value_date": settlement.settled_on.isoformat(),
            "amount": int(settlement.amount),
            "currency": "INR",
            "narration": render(family, settlement.utr, rng),
            "narration_family": family.name,   # provenance only; resolvers must not read it
        })

    for extra in world.extra_bank_credits:
        family = rng.choice(families)
        rows.append({
            "bank_ref": extra.bank_ref,
            "value_date": extra.value_date.isoformat(),
            "amount": int(extra.amount),
            "currency": "INR",
            "narration": (extra.narration_override
                          if extra.narration_override is not None
                          else render(family, extra.utr, rng)),
            "narration_family": (None if extra.narration_override is not None
                                 else family.name),
        })

    # A bank statement arrives in value-date order, not in settlement order.
    rows.sort(key=lambda row: (row["value_date"], row["bank_ref"]))
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
    _write_jsonl(out_dir / "bank.jsonl", derive_bank(world, config))
    truth.write(out_dir / "ground_truth.json")

    return world, truth
