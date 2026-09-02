# AI Finance Controller — three-way settlement reconciliation

**Razorpay Buildathon, Track 04.** Status: **Increments 0–3 complete**, plus a realism increment on
02 Sep that closed three acknowledged gaps in the generator and re-measured everything.
This is an incremental build: [PLAN.md](PLAN.md) records every decision and what each one ruled out.

**If you read one thing, read [Is "the LLM adds nothing" a fact, or an artifact of our own data?](#is-the-llm-adds-nothing-a-fact-or-an-artifact-of-our-own-data)**
— we tested our own headline finding against our own simulator and published which half survived.

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
pytest                                              # 207 tests
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
| **2** | Corroborates an unmatched credit on an exact amount inside the bank's posting window | built |
| **3** | LLM extracts a UTR from a narration no parser was written for | built, fenced |

**Tier 2 is not subset-sum, and subset-sum stays cut** (D-016, D-027, D-033). Searching manufactured
ambiguity *in order to* give the LLM something to adjudicate is the §9 "agent as marketing"
anti-pattern. What Tier 2 does instead is exact on the money: a credit links only when its amount matches a
settlement **to the paise**, that settlement's posting window contains the credit's value date, and
the pairing is unique in both directions. No tolerance on an amount, no scoring, every tie refused
(D-033). It exists because an audit showed those two columns were already in
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
| **Explanation rate · settlement coverage** | **73.91%** (17/23) · **77.27%** (17/22) | **78.26%** (18/23) · **81.82%** (18/22) |
| Money-weighted coverage | 77.06% | 82.16% |
| **Decomposition closure** *(no linkage, no ground truth)* | **90.91%** (20/22) | **90.91%** (20/22) |
| **Linkage precision** | **100.00%** (3,387/3,387) | **100.00%** (3,506/3,506) |
| …at the bank grain *(the one an adjudicator can reach)* | **19/19** | **18/18** |
| Linkage recall | 99.97% | 99.94% |
| Exception detection recall | 100.00% (195/195) | 100.00% (187/187) |
| **False-clear, in remit** | **0.00%** (0/195) | **0.00%** (0/187) |
| **Exception queue precision** *(raised breaks that are real)* | **94.69%** (196/207) | **93.00%** (186/200) |
| Exception typing accuracy | 100.00% | 98.93% |
| Intrinsic clean rate *(from ground truth)* | 89.03% | 89.37% |
| Narration parse rate *(regex)* | 100.00% (23/23) | **8.70%** (2/23) |
| Journal entries, all balanced | 17 | 18 |
| Reconciliation statement | **foots to zero** | **foots to zero** |

**These numbers went DOWN on 02 Sep, and that is the system working.** Closing three acknowledged
realism gaps in the generator (below) showed that two settlements per seed were being reported as
fully explained when the settlement report contradicted itself, and journal entries were posting on
them. Decomposition closure fell from 100% to 90.91% for the same reason. A headline that falls when
the data gets more honest was measuring the wrong thing before.

**Queue precision is published because its absence hid a real defect.** The suite measured false
clear — what we missed — with genuine rigour, and never measured what we *raised* that was not real.
Under that blind spot the held-out queue reported 22 settlements as missing when 21 of those credits
were in the bank file. Both directions are now published, per seed and per code (D-030, F-014).

### The ablation — what each tier is actually worth

| Cumulative | dev | eval (held out) |
|---|---|---|
| T0 · narration join | **0.00%** (0/23) | 0.00% (0/23) |
| + T1 · arithmetic | **73.91%** (17/23) | 0.00% (0/23) |
| + T2 · exact amount in the posting window | 73.91% | **78.26%** (18/23) |
| + T3 · LLM | 73.91% | **78.26% — adds nothing** |

**Tier 0 alone explains nothing on realistic data.** It finds the counterparty and proves the report
is internally consistent — worth having — but on a merchant with a rolling reserve it cannot explain a
single rupee of the gross-to-cash gap. The brief's thesis, that explaining the amount is the job, is a
measured number here rather than a claim.

The credits neither tier explains are not decomposition failures: two with no settlement behind them,
a duplicate-UTR pair the resolver **deliberately declines to link**, and the settlements whose own
reported total contradicts their line items — where the arithmetic closes but nothing posts, by
design.

---

## Is "the LLM adds nothing" a fact, or an artifact of our own data?

This is the question a reviewer should ask, and on 02 Sep we went looking for the answer instead of
defending the result. `ARCHITECTURE.md` §4 already listed what the simulator makes easier than
reality. Three of those gaps were closed, one was **withdrawn as factually wrong**, and every number
was re-measured. The rule was fixed in advance: only gaps already named could be closed, and no change
could be justified by what it would do to the LLM's role.

**The answer is both, and the split is measurable.**

### The artifact half — and it was load-bearing

`derive_bank` was copying the settlement's date straight into the bank row's `value_date`, while the
brief's own §3.4 lists `created_at ≠ settled_at ≠ bank value date` as a structural difficulty of this
domain. Credits now post on the settlement date or the next business day, never on a weekend.

| eval, held out | before | realistic dates, Tier 2 unchanged | + windowed rule |
|---|---|---|---|
| Explanation rate | 18/23 | **4/23** | **18/23** |
| Linkage precision | 100.00% | 100.00% | **100.00%** |

Tier 2's exact `(amount, value_date)` join lost **14 of 18 links**. The earlier finding that a
two-field exact join reproduced the entire held-out result rested, in part, on one copied field.

### The fact half — and it is larger

Under a rule that keeps the amount exact and allows the value date anywhere in the settlement's
posting window (D-033), the held-out seed returns to **18/23 at 100% precision**. What carries
corroboration is the **amount**, not the date: **22 of 22 settlement amounts are distinct on both
seeds, the two closest ₹171.98 apart.** A mixed merchant's daily net settlement is an effectively
random paise value, so that uniqueness is a property of settlement flows rather than of our simulator.

For the same reason one listed caveat was **withdrawn rather than closed** (D-034). It claimed a real
bank nets its charges out of the credit; for an inbound NEFT/RTGS/IMPS credit to an Indian merchant's
account it does not, and the amounts tie out exactly. Implementing it would have made the world *less*
like a real settlement flow.

### The ceiling never rose

The measurement that settles this needs no API key. An **oracle adjudicator** — a perfect extractor
built from ground truth — is the upper bound on any model, so if the oracle adds nothing, no model can.

| oracle headroom, credits a perfect extractor adds | dev | eval |
|---|---|---|
| before the realism increment | 0 of 24 | 1 of 24 |
| after all three gaps closed | **0 of 23** | **0 of 23** |

### The one place it does move, published because it is the honest half

At the **linkage** grain the oracle is not zero. It takes the held-out bank grain from **18 to 20**,
recovering the two settlements whose reported total is stale — beyond the reach of any amount-based
rule, because the amount itself is the thing that is wrong. **The UTR is the only reference that does
not depend on every amount being right, and that is the real-world argument for it, arriving here as
a measurement rather than an assertion.**

Those two links convert to **zero** additional explained settlements: the report still contradicts
itself, so nothing posts. Both halves are published together, because the first without the second
would overstate what extraction buys.

**We stopped there.** Three gaps closed, the number did not move, and continuing to hunt for a fourth
until it did would be tuning the data against the outcome — the one thing this project has avoided
throughout.

---

### What Tier 1's closure does and does not prove

Explained money splits **~49% schema-derived** (read from documented §3.1 fields the *gateway*
asserts — `type`, `dispute_id` — which would read identically from a real report) and **~51%
contract-derived** (from rate-card constants we also generated with).

So the claim is exactly: **Tier 1 generalises across worlds, not across contracts.** The eval seed is
a different world drawn from the *same* rate card, so closure on it shows the rules apply to unseen
**instances**, not that they hold for a merchant on a different **contract**. Anything stronger would
be overclaiming, and the split is published so the sentence can be checked.

Closure is **90.91% (20/22) on both seeds**, not 100%. The two that miss are the settlements whose
*reported* total was struck before one of their own line items posted: the gap between the line items
and a stale total is not a deduction, so no arithmetic can type it, and the tier correctly declines to
try. It reads as an arithmetic result and is a data one — which is why `ROLLUP_MISMATCH` is raised
against those settlements and nothing posts for them.

---

## The LLM: one job, fenced, and measured against itself

The regex scores **100% on dev (23/23) and 2 of 23 on held out** — and both of those hits are
injected stray credits, so on held-out *settlement* narrations it is **0 of 21**. That gap — not the
arithmetic — is the only place an LLM earns a role here. So it gets exactly one job: extract a UTR
from a narration no parser was written for. It never chooses between settlements, never explains a
residual, never touches an amount.

Every proposal is re-verified by **exact lookup**. A UTR either resolves to a known settlement or it
does not; there is no "close enough" and no scoring step a confident wrong answer can win.

### What it adds over the deterministic tiers: nothing for explanation, two links

Deterministic corroboration places most held-out credits first, so the adjudicator is asked **3
questions instead of 23** — and the explanation rate does not move. Measured against an **oracle**, a
perfect extractor built from ground truth, so this is the ceiling for *any* model rather than one
model's score:

| eval, held out | rules only | + perfect extractor |
|---|---|---|
| Explanation rate | 78.26% (18/23) | **78.26% (18/23)** |
| Linkage precision, bank grain | 100.00% (18/18) | **100.00% (20/20)** |
| Linkage recall | 99.94% | **100.00%** |
| Journal entries | 18 | 18 |

**Zero for the headline, two links at the linkage grain** — the two settlements with a stale reported
total, which no amount-based rule can reach because the amount is the thing that is wrong. They do not
convert into explained settlements, because the report still contradicts itself and nothing posts.

**This is a better result than the one it replaces, not a worse one.** We went looking for the LLM's
job, found a deterministic rule that does it better on our own data, published the comparison, and cut
the model back to the residue nothing else could place — then closed three realism gaps in the
generator to check whether that residue was an artifact of our own simulator. It was not.

Before Tier 2 existed, three live runs against all 22 narrations returned 5, then 3, then 4 correct —
and we reported the range rather than the best sample. That run is preserved in
[RUN_LOG.md](RUN_LOG.md); its denominator was inflated by the defect Tier 2 fixed, so it is history
rather than the headline. The real model's extraction accuracy stays **unclaimed**: there is no API
key in this environment, and the oracle is labelled as an upper bound everywhere it appears (D-022).

Through all of it, at the grain an adjudicator can actually reach, **linkage precision stayed
100.00%** — including under a hostile adjudicator returning plausible wrong UTRs, all blocked.

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

**Truncated narrations** are the same shape arriving from the other direction: most held-out credits
have the UTR physically cut out of the statement at 40 characters. No tier recovers those, and the
system says so instead of guessing.

**A settlement whose own reported total is stale.** The arithmetic closes and the linkage holds, but
the report contradicts itself, so `ROLLUP_MISMATCH` is raised and **nothing posts**. Two per seed.
Detected reliably; not resolvable from this extract, because the reconciler cannot tell a stale total
from a line item that should not be there. It is also the one case where an extractor beats every
deterministic tier — see the ceiling section above.

**Also deliberately absent:** subset-sum candidate search · multi-gateway · a second merchant scenario
· FX · TDS 194-O (out by merchant persona) · a realistic UTR format, which is the last known realism
gap and is declined on time rather than merit. Each is a dated decision in [PLAN.md](PLAN.md) with
what it ruled out, and `ARCHITECTURE.md` §4 lists what the simulator still makes easier than reality.

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
[FAILURE_LOG.md](FAILURE_LOG.md) — seventeen real incidents, dated as they happened ·
[STUDY_PLAN.md](STUDY_PLAN.md)
