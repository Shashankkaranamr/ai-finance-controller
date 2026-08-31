# AI Finance Controller — three-way settlement reconciliation

**Razorpay Buildathon, Track 04.** Status: **Increment 1 (faithful generator) complete.**
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
python -m recon demo                                # generate + reconcile + report (dev seed)
python -m recon eval                                # the HELD-OUT seed (see below)
pytest                                              # 124 tests
```

`make demo` forwards to the same entrypoint for reviewers who have GNU make. No network access and no
API key are required — the build is rules-only so far, by design. Clean clone to working demo,
measured on Windows with no `uv` and no `make`: **27 s**.

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
  ...in remit              = missed breaks detectable at the built tier / those breaks
  ...out of remit          = missed breaks needing a higher tier      / those breaks
exception typing accuracy  = correctly coded / breaks caught
intrinsic clean rate       = units with no injected anomaly / all units   <- a property of the DATA
narration parse rate       = credits whose UTR the regex extracted / all credits
```

**False-clear is tracked separately and prominently.** A missed match costs an analyst ten minutes; a
false clear means money silently leaves the reconciliation and nobody looks again.

**And it is split by remit, which matters more than the headline number.** "We did not flag it"
bundles two different failures: a break the built resolver was accountable for and silently passed,
and a break whose detection needs a tier that does not exist yet. Only the first is a false clear in
any meaningful sense — nothing was cleared in the second case, nothing looked. Every exception class
declares the lowest tier that can detect it, `BUILT_TIER` declares how far this build actually goes,
and a test fails if a class claimed detectable at tier 0 is never raised in `tier0.py`. Without that
test the split would just be a way to relabel real misses.

**The in-remit number is the one that must never regress. It is 0.00% on both seeds.**

Ground truth is emitted by the world simulator *before* the source views are derived from it
(`src/recon/domain/truth.py`). Labelling views after the fact would encode the matcher's own
assumptions, and the evaluation would then measure agreement with ourselves.

---

## Measured — Increment 1, both seeds

88 days · 22 settlement cycles · ~1,750 line items · all four Sec 3.1 types · the full deduction
stack. `dev` is the seed we tune on; `eval` is held out — a different world **and** narration
templates the parser has never seen.

| | dev | eval (held out) |
|---|---|---|
| Line items / records | 1,732 / 3,327 | 1,789 / 3,435 |
| **Intrinsic clean rate** (from ground truth) | **89.12%** (2,965/3,327) | **89.46%** (3,073/3,435) |
| Linkage precision | **100.00%** (3,388/3,388) | **100.00%** (3,488/3,488) |
| Linkage recall | 99.97% (3,388/3,389) | 99.40% (3,488/3,509) |
| Exception detection recall | 56.77% (109/192) | 56.52% (104/184) |
| **False-clear, in remit** | **0.00%** (0/109) | **0.00%** (0/104) |
| False-clear, out of remit | 100.00% (83/83) | 100.00% (80/80) |
| Exception typing accuracy | 100.00% (109/109) | 99.04% (103/104) |
| Narration parse rate | **100.00%** (24/24) | **8.33%** (2/24) |
| Explanation rate (bank credits) | 0.00% (0/24) | 0.00% (0/24) |
| Reconciliation statement | **foots to zero** | **foots to zero** |
| Throughput | 3,327 records in 91 ms | 3,435 in 91 ms |

**Explanation rate is 0%, and that is the finding, not a regression.** Tier 0 reads the fee and tax
the report states. It knows nothing about a rolling reserve, a refund offset or a chargeback
reversal, so `gross − cash − MDR − GST` stops landing on zero the moment those exist. Increment 0's
100% was a fact about clean data. This 0% is the measured argument for building Tier 1, and it is
reported rather than engineered away.

**The intrinsic clean rate is the number that answers "is the synthetic data too clean?"** — 89%, from
ground truth, with no resolver involved. Substituting the resolver's own score there would be
answering a different question.

### Where the unexplained money actually is

Tier 0 leaves **Rs 3,96,133.81** unexplained on the dev seed. Bucketed by the component that truly
accounts for it:

| Component | Amount | Share of movement |
|---|---|---|
| Rolling reserve | Rs 1,74,079.22 | 32.3% |
| Refund offset | Rs 1,36,202.84 | 25.3% |
| Transfer out | Rs 1,09,580.02 | 20.4% |
| Reserve release | −Rs 71,224.02 | 13.2% |
| Chargeback reversal | Rs 28,646.46 | 5.3% |
| Chargeback fee | Rs 18,000.00 | 3.3% |
| Instant settlement fee | Rs 849.29 | 0.2% |

**Zero scatter — and we are explicit that this is by construction.** The world is simulated *from*
typed components, so of course every residual types. This says an arithmetic Tier 1 can reach all of
it; it does **not** establish that real residuals behave this way, and presenting it as an empirical
discovery would be circular. What it does establish concretely is that Increment 1 produced no
genuine Tier-2 ambiguity, which is a decision Increment 2 has to make deliberately rather than
inherit. (PLAN.md, D-015.)

### The held-out seed, and what it costs us

The deterministic narration parser was written against `dev` templates only, and the split is held
out at the **template** level, not just the seed level — a held-out seed rendered from the same
templates would only prove the RNG differs.

Parse rate: **100.00% on dev, 8.33% on eval.** The two eval hits are injected stray credits carrying
their own narration, so on held-out *settlement* narrations the parser scores **0 of 22**.

The honest reading is "this regex handles 0 of 2 unseen shapes", **not** "an LLM adds 100 points".
Both held-out families defeat it structurally — one truncates the UTR, the other removes the
delimiters — and with only two families that number is a direction, not a magnitude. The Increment 3
ablation will say so.

### What this system cannot do, and never will

`REFUND_ORPHANED` — a refund whose original payment was captured before the extract window opens.

It is **always detected**: the `payment_id` points at nothing and we say so, with evidence. It is
**never resolvable**, by any tier, an LLM included, because the payment is not in the data. There is
nothing to link it to. Nine per seed, and the exception queue names them.

This is the one class flagged unresolvable, and a test pins that list at exactly one — a growing
collection of "we can never fix this" is how a blind spot turns into an excuse.

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

**Every run so far is already a degraded-mode run.** No adjudicator is configured, so the
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
