# AI Finance Controller — three-way settlement reconciliation

**Razorpay Buildathon, Track 04.** Status: **Increments 0–3 complete** — walking skeleton, faithful
generator, Tier 1 arithmetic decomposition, and the LLM fenced into narration parsing.
This is an incremental build: [PLAN.md](PLAN.md) records every decision and what each one ruled out.

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
python -m recon eval                                # the HELD-OUT seed
python -m recon ablation --seed eval                # with and without the adjudicator, side by side
pytest                                              # 168 tests
```

No network access and no API key are required: the default path is rules-only and fully
deterministic. Clean clone to working demo, measured on Windows with no `uv` and no `make`:
**~50 s** against a 300 s budget. `make demo` forwards to the same entrypoint.

The LLM is **opt-in** (`--llm`, plus `pip install -e ".[llm]"` and `ANTHROPIC_API_KEY`). It is never
enabled by the mere presence of a key, because it costs money and moves the numbers.

---

## Architecture: a pipeline with a fenced LLM, and we say so

The track asks for an "agent". What closes this loop reliably is a **deterministic pipeline with the
LLM fenced into one job it cannot corrupt**. Calling a for-loop an agent is the anti-pattern; the
ablation table is the argument, and it is published below either way.

Reconciliation is modelled as a **graph of typed edges**, not as stages over rows. An edge asserts
*"these two units are the same money, and here is the typed arithmetic explaining why the amounts
differ."* Tier is an attribute of an **edge**, which makes the ablation a group-by rather than a
second run.

Four grains, each with its own denominator (`src/recon/domain/graph.py`, `EDGE_SPECS`):

| Edge | Cardinality | Key | Bears variance |
|---|---|---|---|
| `BANK_TO_SETTLEMENT` | 1:1 | `settlement_utr` in narration | yes — gross vs cash |
| `SETTLEMENT_TO_LINE` | 1:N | `settlement_id` | no — membership; rollup checked over the set |
| `LINE_TO_BOOK` | 1:1 | `order_id` | yes — ERP vs gateway |
| `REFUND_TO_PAYMENT` | 1:1 | `payment_id` | no — crosses cycles; **exercised and holds** |

### The tiers, and what each is accountable for

| Tier | Does | Status |
|---|---|---|
| **0** | Exact-key joins; §3.2 identities over the values the report *states*; flags, dates, cardinality | built |
| **1** | Types the whole deduction stack against a contracted rate card; detects off-contract fees | built |
| **2** | Subset-sum over candidates | **CUT** — see below |
| **3** | LLM extracts a UTR from a narration no parser was written for | built, fenced |

Tier 2 is cut deliberately (PLAN.md, D-016). Increment 1 measured the residual as 100%
typed-component-shaped with zero scatter, so there was nothing for a search to search — and building
difficulty *in order to* give the LLM something to adjudicate is the §9 "agent as marketing"
anti-pattern. The honest line is that arithmetic closes this loop, and the LLM earns its place only
where deterministic parsing does not generalise.

---

## Metrics — the formulas, in full

Ambiguous metrics are the easiest way to lose a technical panel, so every numerator and denominator is
named. All rates are **integer basis points** (9873 = 98.73%); `metrics.json` contains no floats.

### Headline — always two denominators, never one number

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

**Why explanation rate, not match rate.** Exact UTR join clears essentially everything — finding the
counterparty is easy. Explaining the amount to a zero residual is the job.

**Why two denominators.** "Bank credits explained ÷ total bank credits" *cannot see a settlement that
never produced a credit at all* — the worst break in the set would be invisible. Measured at
Increment 0: explanation rate read 100.00% while settlement coverage read 83.33%. Both true. Only one
of them honest on its own.

### Accuracy, against ground truth emitted by the simulator

```
linkage precision          = correct edges  / edges we accepted      <- lead with this
linkage recall             = correct edges  / true edges
exception detection recall = injected breaks caught / injected breaks
false-clear rate           = injected breaks NOT flagged / injected breaks
  ...in remit              = missed breaks detectable at the built tier / those breaks
  ...out of remit          = missed breaks needing a higher tier      / those breaks
exception typing accuracy  = correctly coded / breaks caught
intrinsic clean rate       = units with no injected anomaly / all units   <- a property of the DATA
decomposition closure      = settlements whose gross-to-net gap is fully typed, WITHOUT linkage
narration parse rate       = credits whose UTR the regex extracted / all credits
blocked_hallucination      = LLM proposals rejected because the model invented the reference
blocked_unverifiable       = LLM proposals rejected because the document has no usable reference
```

**False-clear is split by remit, and that matters more than the raw number.** "We did not flag it"
bundles two different failures: a break the built resolver was accountable for and silently passed,
and a break whose detection needs a tier that does not exist. Only the first is a false clear —
nothing was cleared in the second case, nothing looked. Every exception class declares the lowest tier
that can detect it, `BUILT_TIER` declares how far this build goes, and a test fails if a class claimed
detectable at tier 0 is never raised in `tier0.py`. Without that test the split would just be a way to
relabel real misses.

**The in-remit number must never regress. It is 0.00% on both seeds.**

Ground truth is emitted by the world simulator *before* the source views are derived from it. Labelling
views after the fact would encode the matcher's own assumptions, and the evaluation would then measure
agreement with ourselves.

---

## Measured

88 days · 22 settlement cycles · ~1,750 line items · all four §3.1 line types · the full §3.3
deduction stack. `dev` is the seed we tune on; `eval` is held out — a different world **and**
narration templates the parser has never seen.

| | dev | eval (held out) |
|---|---|---|
| **Explanation rate · settlement coverage** | **83.33%** (20/24) · **90.91%** (20/22) | 0.00% · 0.00% — *see below* |
| **Decomposition closure** *(no linkage, no ground truth)* | **100.00%** (22/22) | **100.00%** (22/22) |
| **Linkage precision** | **100.00%** (3,388/3,388) | **100.00%** (3,488/3,488) |
| Linkage recall | 99.97% | 99.40% |
| Exception detection recall | 100.00% (192/192) | 100.00% (184/184) |
| **False-clear, in remit** | **0.00%** (0/192) | **0.00%** (0/184) |
| Exception typing accuracy | 100.00% | 99.46% |
| Intrinsic clean rate *(from ground truth)* | 89.12% | 89.46% |
| Narration parse rate *(regex)* | 100.00% (24/24) | **8.33%** (2/24) |
| Journal entries, all balanced | 20 | 0 |
| Reconciliation statement | **foots to zero** | **foots to zero** |
| Throughput | 3,327 records in ~240 ms | 3,435 in ~240 ms |

### The ablation — what each tier is actually worth

| Tier | dev | eval |
|---|---|---|
| Tier 0 alone | **0.00%** (0/24) | 0.00% |
| + Tier 1 | **83.33%** (20/24) | 0.00% |
| + Tier 3 (LLM) | — *(no unparsed narrations to work on)* | **12.50–20.83%** |

**Tier 0 alone explains nothing on realistic data.** It finds the counterparty and proves the report
is internally consistent — worth having — but on a merchant with a rolling reserve it cannot explain a
single rupee of the gross-to-cash gap. The brief's thesis, that explaining the amount is the job, is a
measured number here rather than a claim.

The four dev credits that remain unexplained are not decomposition failures: they are two credits with
no settlement behind them and a duplicate-UTR pair the resolver **deliberately declines to link**.
Every settlement Tier 1 could reach, it closed.

### Eval explanation is 0%, and it is not an arithmetic failure

On the held-out seed the regex extracts nothing, so no bank edge is created and Tier 1 never runs.
That is why **decomposition closure** exists as a separate measurement: it asks whether the
gross-to-net gap can be typed using the settlement report alone — no bank statement, no narration, no
ground truth. It is **100% on both seeds**. The held-out failure is localised entirely to narration
parsing.

### What Tier 1's 100% does and does not prove

Explained money splits **~49% schema-derived** (read from documented §3.1 fields the *gateway*
asserts — `type`, `dispute_id` — which would read identically from a real report) and **~51%
contract-derived** (from rate-card constants we also generated with).

So the claim is exactly: **Tier 1 generalises across worlds, not across contracts.** The eval seed is
a different world drawn from the *same* rate card, so 100% closure shows the rules apply to unseen
**instances**, not that they hold for a merchant on a different **contract**. Anything stronger would
be overclaiming, and the split is published so the sentence can be checked.

---

## The LLM: one job, fenced, and measured against itself

The regex scores **100% on dev and 0 of 22 on held-out settlement narrations**. That gap — not the
arithmetic — is the only place an LLM earns a role here. So it gets exactly one job: extract a UTR
from a narration no parser was written for. It never chooses between settlements, never explains a
residual, never touches an amount.

Every proposal is re-verified by **exact lookup**. A UTR either resolves to a known settlement or it
does not; there is no "close enough" and no scoring step a confident wrong answer can win.

### We ran it three times, and the answer changed

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| Correct and verified | 5 / 22 | 3 / 22 | 4 / 22 |
| `blocked_hallucination` | 3 | 5 | 4 |
| `blocked_unverifiable` | **14** | **14** | **14** |
| **Linkage precision** | **100.00%** | **100.00%** | **100.00%** |
| Statement foots | YES | YES | YES |

Same 22 narrations, same prompt, same model (`claude-haiku-4-5`). We got 5, published it, re-ran to
make the artifacts match, got 3, ran a third and got 4.

**We report the range: 3–5 of 22 overall, 38–62% on recoverable data.** Quoting 62% alone would be
quoting the better sample.

And underneath a model swinging 24 points, **linkage precision was 100.00% in all three runs.** The
fence never moved. The LLM is *allowed* to be unreliable, because nothing it proposes reaches the
ledger without a verification it cannot talk its way past.

### Two rejection counters, because they are two different events

The first live run reported 17 "hallucinations". Fourteen of them were the model being **right**: the
`neft_truncated` family cuts the narration at 40 characters, and only 10 of the 16 UTR characters
survive in the source at all. The model returned exactly what was there.

```
narration : NEFT-RAZORPAYSOFTWAREPVTLT-UTR1487099871
true utr  : 14870998713daxoq
proposed  : 1487099871          <- exactly what the document contains
```

Rejecting it was still correct — an unverifiable reference must never become a link — but calling it a
hallucination overstated model error roughly fivefold. **"The model was wrong" and "the answer was not
recoverable" are different findings**, and the system now separates them. It is the same judgment
Tier 0 already applies to a duplicated UTR, one level sharper.

### Determinism, and where it stops

Same seed ⇒ byte-identical `metrics.json`, for the shipped rules-only path and for any deterministic
adjudicator. Both are covered by tests. **With a live LLM it does not hold** — the response cache is
per-run, so a re-run re-asks and may get a different answer, as the table above shows. Stated rather
than left for a reviewer to discover.

---

## What this system cannot do

**`REFUND_ORPHANED`** — a refund whose original payment was captured before the extract window opens.
Always **detected** (the `payment_id` points at nothing, and we say so with evidence); **never
resolvable** by any tier, LLM included, because the payment is not in the data. Nine per seed. A test
pins the unresolvable list at exactly one class — a growing collection of "we can never fix this" is
how a blind spot becomes an excuse.

**Truncated narrations** are the same shape arriving from the other direction: 14 of 22 held-out
credits have the UTR physically cut out of the statement. No tier recovers those, and the system says
so instead of guessing.

**Also deliberately absent:** Tier 2 · multi-gateway · a second merchant scenario · FX · TDS 194-O
(out by merchant persona). Each is a dated decision in [PLAN.md](PLAN.md) with what it ruled out.

---

## Design decisions worth defending

**All money is integer paise, and the whole package is float-free.** Not a style rule — a property.
`tests/test_no_floats.py` asserts it by AST scan over every module. Only possible because rates are
carried as basis points and timing uses `perf_counter_ns`.

**`fee` is inclusive of `tax`.** `credit = amount − fee`; `mdr_base = fee − tax`;
`tax = round_half_up(mdr_base × 18%)`. Adding tax on top of fee double-counts it — the single most
common way to get this schema wrong.

> **A discrepancy in the reference example.** The brief's transfer example (`fee=296, tax=46`) does not
> satisfy its own GST rule: `296 − 46 = 250`, and `250 × 18% = 45`, not 46. No base yields 46 at 18%
> and still sums to 296. Rather than quietly bending the rule to fit, we pin one canonical rule,
> generate data that satisfies it exactly, and treat deviation as `GST_ON_MDR_MISMATCH` — already in
> the taxonomy. See `test_brief_transfer_example_violates_its_own_gst_rule`.

**The resolver may not read prose we wrote.** `description` and `notes` are free text from our own
generator, so typing an adjustment off "Rolling reserve withheld" would be circular *and* would be the
fuzzy string matching §9 names as most likely to sink a submission. A rolling reserve is identified
arithmetically — the adjustment debit exactly equal to 500 bps of settled credits, no tolerance. A
test redacts every description and asserts the decomposition does not move.

**The footing identity is a cross-source check, not a tautology.** `gross_sales` from the books,
`settlements_received` from the bank, `explained_variance` from the resolver, `exceptions` from the
queue. A one-paise error in the MDR arithmetic breaks it.

**A rolling reserve posts to a receivable, not an expense.** Withholding debits the asset and releasing
credits it, to the same account, so the reserve ledger nets itself out over the hold period instead of
quietly becoming a cost the merchant never recovers on paper.

**Narration templates are split `dev` / `eval`.** We write the narrations, so a parser authored against
the same templates that generate the eval data wins trivially. Held out at the *template* level, not
just the seed level. The prompt gets the same discipline: it was written blind and has **not** been
tuned against held-out results.

**The ledger posts nothing it cannot fully explain.** Auto-posting is gated on a zero residual with
every component typed. An accounting system that posts a half-understood entry is worse than one that
posts none and raises an exception.

---

## Repo map

```
src/recon/
  domain/graph.py        the grain model -- units, typed edges, tiers, exceptions
  domain/rates.py        the contracted rate card: MDR slabs, reserve, dispute fees
  domain/identities.py   the Sec 3.2 arithmetic, as pure functions
  domain/truth.py        ground truth, designed backwards from false-clear
  generate/              world simulator -> derived views + ground truth
  ingest/                Pydantic validation at the boundary, quarantine
  resolve/tier0.py       exact-key joins + identity checking
  resolve/tier1.py       variance decomposition against the rate card
  resolve/tier3.py       the fenced adjudicator + the verifier gate
  llm/                   the seam: protocol, cache, null and Anthropic adjudicators
  ledger/statement.py    footing statement + balanced journal entries
  report/                metrics harness and the exception queue
  audit/log.py           append-only decision log
```

[PLAN.md](PLAN.md) — every decision and what it ruled out ·
[RUN_LOG.md](RUN_LOG.md) — measured results per gate ·
[FAILURE_LOG.md](FAILURE_LOG.md) — eleven real incidents, dated as they happened ·
[STUDY_PLAN.md](STUDY_PLAN.md)
