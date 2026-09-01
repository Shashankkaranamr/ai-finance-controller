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
pytest                                              # 184 tests
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
| **2** | Corroborates an unmatched credit on exact `(amount, value_date)` | built |
| **3** | LLM extracts a UTR from a narration no parser was written for | built, fenced |

**Tier 2 is not subset-sum, and subset-sum stays cut** (D-016, D-027). Searching manufactured
ambiguity *in order to* give the LLM something to adjudicate is the §9 "agent as marketing"
anti-pattern. What Tier 2 does instead is exact: a credit links only when `(amount, value_date)`
resolves to one settlement **and** that settlement is claimed by one credit. No tolerance, no
scoring, every tie refused. It exists because an audit showed those two columns were already in
memory and being ignored — see the ablation below.

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
exception queue precision  = raised breaks that are real / raised breaks    <- the OTHER direction
linkage precision by grain = per edge kind, because the aggregate is insensitive
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
| **Explanation rate · settlement coverage** | **83.33%** (20/24) · **90.91%** (20/22) | **83.33%** (20/24) · **90.91%** (20/22) |
| **Decomposition closure** *(no linkage, no ground truth)* | **100.00%** (22/22) | **100.00%** (22/22) |
| **Linkage precision** | **100.00%** | **100.00%** (3,508/3,508) |
| …at the bank grain *(the one an adjudicator can reach)* | **20/20** | **20/20** |
| Linkage recall | 99.97% | 99.97% |
| Exception detection recall | 100.00% (192/192) | 100.00% (184/184) |
| **False-clear, in remit** | **0.00%** (0/192) | **0.00%** (0/184) |
| **Exception queue precision** *(raised breaks that are real)* | **94.61%** (193/204) | **92.89%** (183/197) |
| Exception typing accuracy | 100.00% | 98.91% |
| Intrinsic clean rate *(from ground truth)* | 89.12% | 89.46% |
| Narration parse rate *(regex)* | 100.00% (24/24) | **8.33%** (2/24) |
| Journal entries, all balanced | 20 | 20 |
| Reconciliation statement | **foots to zero** | **foots to zero** |

**Queue precision is published because its absence hid a real defect.** The suite measured false
clear — what we missed — with genuine rigour, and never measured what we *raised* that was not real.
Under that blind spot the held-out queue reported 22 settlements as missing when 21 of those credits
were in the bank file. Both directions are now published, per seed and per code (D-030, F-014).

### The ablation — what each tier is actually worth

| Cumulative | dev | eval (held out) |
|---|---|---|
| T0 · narration join | **0.00%** (0/24) | 0.00% (0/24) |
| + T1 · arithmetic | **83.33%** (20/24) | 0.00% (0/24) |
| + T2 · (amount, date) corroboration | 83.33% | **83.33%** (20/24) |
| + T3 · LLM | 83.33% | **83.33% — adds nothing** |

**Tier 0 alone explains nothing on realistic data.** It finds the counterparty and proves the report
is internally consistent — worth having — but on a merchant with a rolling reserve it cannot explain a
single rupee of the gross-to-cash gap. The brief's thesis, that explaining the amount is the job, is a
measured number here rather than a claim.

The four unexplained credits on each seed are not decomposition failures: two credits with no
settlement behind them, and a duplicate-UTR pair the resolver **deliberately declines to link**. Every
settlement the tiers could reach, they closed.

**The bottom row is the important one.** On the held-out seed, deterministic corroboration does all
of it and the LLM adds zero — see below.

### The held-out seed used to report 0%, and that was our bug

The regex extracts nothing there, so Tier 0 created no bank edge and the whole eval result was 0%.
An adversarial audit showed why that was not a data problem: `(amount, value_date)` resolves 20 of 24
held-out credits to exactly one settlement, using two columns the resolver had already loaded and
declined to read. Tier 2 now reads them, and eval matches dev.

**Decomposition closure** remains published as a separate measurement — it asks whether the
gross-to-net gap can be typed from the settlement report alone, with no linkage at all — and it is
**100% on both seeds**. It is what let us tell an arithmetic failure from a linkage failure while the
linkage was broken.

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

### What it adds over the deterministic tiers: nothing

Measured live, post-audit. Tier 2 places 20 of the 22 credits first, so the adjudicator is asked
**2 questions instead of 22** — and the explanation rate does not move.

| | rules only | + adjudicator |
|---|---|---|
| Explanation rate | 83.33% (20/24) | **83.33% (20/24)** |
| Linkage precision | 100.00% | 100.00% |
| Adjudicator calls | 0 | **2** |
| `blocked_hallucination` | 0 | 0 |
| Journal entries | 20 | 20 |

**This is a better result than the one it replaces, not a worse one.** We went looking for the LLM's
job, found a deterministic rule that does it better on our own data, published the comparison, and cut
the model back to the residue nothing else could place — where it also added nothing.

Before Tier 2 existed, three live runs on all 22 narrations returned 5, then 3, then 4 correct — and
we reported the range rather than the best sample. That run is preserved in
[RUN_LOG.md](RUN_LOG.md); its denominator was inflated by the same defect Tier 2 fixed, so the figure
to quote today is the one above: **zero contribution over the deterministic tiers on this data.**

Through all of it, at the grain an adjudicator can actually reach, **linkage precision stayed
100.00%** — including under a hostile adjudicator returning 22 plausible wrong UTRs, all blocked.

### Two rejection counters, because they are two different events

The first live run reported 17 "hallucinations". Fourteen were the model being **right** about a
narration that genuinely truncates the UTR at 40 characters — it returned exactly what was there.

```
narration : NEFT-RAZORPAYSOFTWAREPVTLT-UTR1487099871
true utr  : 14870998713daxoq
proposed  : 1487099871          <- exactly what the narration contains
```

Rejecting it was still correct — an unverifiable reference must never become a link — but calling it a
hallucination overstated model error roughly fivefold. **"The model was wrong" and "the answer was not
recoverable" are different findings**, and the system separates them (D-025).

> **Correction, 01 Sep.** We also claimed those UTRs were unrecoverable *by any tier*. That was false
> as shipped: every bank row carried the full UTR in its own primary key, `bc_<utr>`, one field from
> the narration it was supposedly absent from. `bank_ref` is now a CRC, so the sentence is true — and
> a third source of recovery, `(amount, value_date)`, turned out to place 20 of the 22 anyway.
> (D-029, F-013.)

An **empty** answer is also not a hallucination: the prompt tells the model an empty string is correct
when no UTR is present, so abstention counts as unverifiable. Found when a *perfect oracle* scored a
hallucination.

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
