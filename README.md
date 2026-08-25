# AI Finance Controller — three-way settlement reconciliation

**Razorpay Buildathon, Track 04.** Status: **Increment 0 (walking skeleton) complete.**
This is an incremental build — see [PLAN.md](PLAN.md) for what is deliberately not built yet.

---

## The problem, in money terms

A controller closing a cycle is not asking *"which bank credit is this?"* — the UTR answers that in
seconds. They are asking *"why is this credit short of gross sales, and by exactly what?"* The answer
is never one number: it is MDR, GST on MDR, rolling reserve, refund offsets and chargebacks, tangled
together across a T+2 boundary, with many settlement line items rolling into one lump bank credit.

That N-to-1 structure is why row-to-row matching is not merely inaccurate but **ill-posed** — there is
no row on the bank side to match a line item against.

## What this does

Reconciles three sources that never agree by construction:

| Source | Grain | Key |
|---|---|---|
| **Books / ERP** | one row per order | `order_id` |
| **Razorpay settlement recon report** | many line items per settlement | `settlement_id` |
| **Bank statement** | one lump credit per settlement | UTR, buried in free-text narration |

…and closes the loop into artifacts a controller would actually use: a reconciliation statement that
**foots to zero**, balanced journal entries, a typed exception queue with evidence and owners, and an
append-only audit trail.

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[dev]"
python -m recon demo                                # generate + reconcile + report
pytest                                              # 91 tests
```

`make demo` forwards to the same entrypoint for reviewers who have GNU make. No network access and no
API key are required — Increment 0 is rules-only by design.

---

## Architecture: a pipeline with a fenced LLM, and we say so

The track asks for an "agent". What closes this loop reliably is a **deterministic pipeline with the
LLM fenced into adjudication jobs it cannot corrupt**. Calling a for-loop an agent is the anti-pattern;
the ablation table is the argument, and it will be published either way.

Reconciliation is modelled as a **graph of typed edges**, not as stages over rows. An edge asserts
*"these two units are the same money, and here is the typed arithmetic explaining why the amounts
differ."* Tier is an attribute of an **edge**, which is what makes the ablation table fall out by
construction instead of being reconstructed at the end.

Four grains, each with its own denominator (`src/recon/domain/graph.py`, `EDGE_SPECS`):

| Edge | Cardinality | Key | Bears variance |
|---|---|---|---|
| `BANK_TO_SETTLEMENT` | 1:1 | `settlement_utr` in narration | yes — gross vs cash |
| `SETTLEMENT_TO_LINE` | 1:N | `settlement_id` | no — membership; rollup checked over the set |
| `LINE_TO_BOOK` | 1:1 | `order_id` | yes — ERP vs gateway |
| `REFUND_TO_PAYMENT` | 1:1 | `payment_id` | no — *declared on hypothesis, unexercised in Inc 0* |

**Tiers.** Tier 0 (built) joins on exact keys and checks the §3.2 identities using the fee and tax the
source *reports*. Tier 1 (next) computes what the fee *should* have been from a contracted slab table
— that distinction is what makes `MDR_SLAB_MISMATCH` meaningful. Tiers 2–3 are deliberately unplanned
until the residual distribution after Tier 1 is measured.

---

## Metrics — the formulas, in full

Ambiguous metrics are the easiest way to lose a technical panel, so every numerator and denominator is
named. All rates are **integer basis points** (9873 = 98.73%); `metrics.json` contains no floats and is
byte-identical across runs.

### Headline

```
explanation rate (bank)   = bank credits whose residual == 0 with every component typed
                            ------------------------------------------------------------
                            total bank credits

settlement coverage       = settlements with a fully explained bank credit
                            ------------------------------------------------
                            total settlements

money-weighted coverage   = gross value of fully explained settlements
                            --------------------------------------------
                            total gross value
```

**Why the headline is explanation rate, not match rate.** Exact UTR join clears essentially everything
— finding the counterparty is easy. Explaining the amount to a zero residual is the job. Match rate is
published alongside as the supporting number so the easy one is never mistaken for the achievement.

**Why two denominators.** "Bank credits explained ÷ total bank credits" *cannot see a settlement that
never produced a credit at all* — the worst break in the set would be invisible. Increment 0 shows this
concretely: explanation rate reads **100.00% (5/5)** while settlement coverage reads **83.33% (5/6)**.
Both are true. Only one of them is honest on its own.

### Accuracy, against a ground truth emitted by the simulator

```
linkage precision          = correct edges  / edges we accepted      <- lead with this
linkage recall             = correct edges  / true edges
exception detection recall = injected breaks caught / injected breaks
false-clear rate           = injected breaks NOT flagged / injected breaks
exception typing accuracy  = correctly coded / breaks caught
```

**False-clear is tracked separately and prominently.** A missed match costs an analyst ten minutes; a
false clear means money silently leaves the reconciliation and nobody looks again.

Ground truth is emitted by the world simulator *before* the source views are derived from it
(`src/recon/domain/truth.py`). Labelling views after the fact would encode the matcher's own
assumptions, and the evaluation would then measure agreement with ourselves.

---

## Measured — Increment 0, dev seed

437 records · 213 orders · 6 settlement cycles · one injected anomaly.

| | |
|---|---|
| Explanation rate (bank credits) | **100.00%** (5/5) |
| Settlement coverage | **83.33%** (5/6) |
| Money-weighted coverage | **85.61%** (Rs 4,43,546.72 of Rs 5,18,101.78) |
| Linkage precision / recall | 100.00% (431/431) / 100.00% |
| Exception detection recall | 100.00% (1/1) |
| **False-clear rate** | **0.00%** (0/1) |
| Reconciliation statement | **foots to zero** |
| Journal entries | 5, all balanced |
| Throughput | 437 records in 105 ms (~4,100 rec/s) |

These numbers are from clean data with a single injected anomaly. They establish that the harness
works; they are **not** a claim about accuracy on realistic data. That claim needs Increment 1's
anomaly injection and a held-out seed, and it will be reported there.

---

## Design decisions worth defending

**All money is integer paise, and the whole package is float-free.** Not a style rule — a property.
`tests/test_no_floats.py` asserts it by AST scan over every module. That is only possible because rates
are carried as basis points and timing uses `perf_counter_ns`.

**`fee` is inclusive of `tax`.** `credit = amount − fee`; `mdr_base = fee − tax`;
`tax = round_half_up(mdr_base × 18%)`. Adding tax on top of fee double-counts it — the single most
common way to get this schema wrong.

> **A discrepancy in the reference example.** The brief's transfer example (`fee=296, tax=46`) does not
> satisfy its own GST rule: `296 − 46 = 250`, and `250 × 18% = 45`, not 46. No base yields 46 at 18%
> and still sums to 296. Rather than quietly bending the rule to fit, we pin one canonical rule,
> generate data that satisfies it exactly, and treat deviation as `GST_ON_MDR_MISMATCH` — already in
> the taxonomy. In production that mismatch is precisely what a controller wants flagged.
> See `test_brief_transfer_example_violates_its_own_gst_rule`.

**The footing identity is a cross-source check, not a tautology.** `gross_sales` comes from the books,
`settlements_received` from the bank, `explained_variance` from the resolver, `exceptions` from the
queue. A one-paise error in the MDR arithmetic breaks it.

**Narration templates are split `dev` / `eval`.** We write the narrations, so a parser authored against
the same templates that generate the eval data wins trivially and the ablation would prove something
about our generator rather than about reality. Held out at the *template* level, not just the seed
level (`src/recon/generate/narration.py`).

**Every Increment 0 run is already a degraded-mode run.** No adjudicator is configured, so the
rules-only path that failure recovery depends on is exercised from day one rather than first proven on
demo day.

---

## Repo map

```
src/recon/
  domain/graph.py        the grain model -- units, typed edges, tiers, exceptions
  domain/identities.py   the Sec 3.2 arithmetic, as pure functions
  domain/truth.py        ground truth, designed backwards from false-clear
  generate/              world simulator -> derived views + ground truth
  ingest/                Pydantic validation at the boundary, quarantine
  resolve/tier0.py       exact-key join + identity checking
  llm/client.py          the seam: protocol, cache, null adjudicator
  ledger/statement.py    footing statement + balanced journal entries
  report/                metrics harness and the exception queue
  audit/log.py           append-only decision log
```

[PLAN.md](PLAN.md) · [STUDY_PLAN.md](STUDY_PLAN.md) · [RUN_LOG.md](RUN_LOG.md) · [FAILURE_LOG.md](FAILURE_LOG.md)
