# ARCHITECTURE

Written so a technical reviewer can **check the design decisions independently** rather than take
them on trust. Every claim below points at a file, a test, or a number you can reproduce.

It supports the video; it does not replace it. [README.md](README.md) has the measured results in
full, [PLAN.md](PLAN.md) has every decision with what it ruled out, [RUN_LOG.md](RUN_LOG.md) has the
numbers as they were measured at each gate.

```bash
git clone <repo> && cd ai-finance-controller
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]"          # pydantic + pytest, nothing else
python -m recon demo             # dev seed, ~50 s from a cold clone
python -m recon eval             # the held-out seed
python -m recon ablation --seed eval
pytest                           # 168 tests
```

No network, no API key, no `make`, no `uv`. The LLM is opt-in (`--llm`).

---

## The whole system in one picture

![Three sources fanning into the reconciliation edge graph, with tiers T0-T4 overlaid](docs/architecture.svg)

Three sources on the left, the typed edge graph in the middle, the tiers on the right. The two things
to take from it before reading further:

**The fan.** Roughly seventy line items converge on one settlement, which ties to one lump bank
credit. That is why row-to-row matching here is not merely inaccurate but **ill-posed** — there is no
row on the bank side to match a line item against.

**The colours are tiers, and they sit on edges rather than on rows.** The headline edge is linked by
Tier 0, or by Tier 3 when the narration defeats the parser, and then explained by Tier 1. Sections 2
and 3 are that sentence in detail.

*(Vector, so it scales cleanly for the video's opening frame. Presentation is set with attributes
rather than a stylesheet, because markdown sanitisers strip `<style>` and it would render as black
boxes.)*

---

## 1. The grain model — why not a pipeline over rows

**The claim:** reconciliation here is a graph of typed edges between units drawn from three sources,
not stages over a flat row stream.

**Why a row-pipeline was rejected.** The bank does not have rows to match against. One lump credit
corresponds to *many* settlement line items, so "match row to row" is not merely inaccurate — it is
**ill-posed**. And Tier 0 alone spans three different joins at three different cardinalities:

| Edge | Cardinality | Natural key | Bears variance? |
|---|---|---|---|
| `BANK_TO_SETTLEMENT` | **1:1** | `settlement_utr`, buried in free text | yes — gross vs cash |
| `SETTLEMENT_TO_LINE` | **1:N** | `settlement_id` | no — membership only |
| `LINE_TO_BOOK` | **1:1** | `order_id` | yes — ERP vs gateway |
| `REFUND_TO_PAYMENT` | 1:1 | `payment_id`, may cross cycles | no |

Blurring those into one "match rate" makes the denominator indefensible, which §7 names as the
easiest way to lose a technical panel. Each grain carries its own denominator instead.

**Two consequences worth checking:**

*The rollup identity is a property of the edge SET, not of any edge.* `settlement.amount = Σcredit −
Σdebit` is checked over all members at once (`resolve/tier0.py`), which is why `SETTLEMENT_TO_LINE`
is marked `bears_variance=False` — a line either belongs or it does not.

*An exception's subject is a unit **or** an edge* (D-002). "This settlement has no bank credit at all"
is the **absence** of an edge, and absence carries no evidence to hang on one. This is the most common
break shape in real reconciliation, so a pure edge model would have been wrong in the field, not just
inconvenient here.

**Verify:**
- `src/recon/domain/graph.py` → `EDGE_SPECS` — the denominators are machine-readable, not buried in
  report code.
- `test_every_edge_kind_declares_its_grain` — every kind must declare a natural key.
- `test_membership_edge_may_be_explained_without_one` — membership edges carry no decomposition.

---

## 2. The tier system — and the ablation as evidence

**Tier is an attribute of an edge, never of a row.** That single choice is what makes the §7 ablation
a `group by` over edges we already have, rather than a second run with features switched off. A table
produced by re-running can drift from the run it describes; this one cannot.

| Tier | Accountable for | Boundary |
|---|---|---|
| **0** | Exact-key joins; §3.2 identities over values the report *states*; flags, dates, cardinality | Reads reported `fee`/`tax`. Cannot say you were overcharged. |
| **1** | Types the whole §3.3 deduction stack against a contracted rate card; detects off-contract fees | First tier with a *second, independent opinion* (`domain/rates.py`). |
| **2** | Subset-sum over candidates | **CUT** (D-016) |
| **3** | Extracts a UTR from a narration no parser was written for | Proposes linkage only. Never touches money. |

### The ablation

| Cumulative | dev | eval (held out) |
|---|---|---|
| Tier 0 alone | **0.00%** (0/24) | 0.00% |
| + Tier 1 | **83.33%** (20/24) | 0.00% |
| + Tier 3 | — *(nothing unparsed to work on)* | **12.50–20.83%** |

**Tier 0 alone explains nothing on realistic data.** It finds the counterparty and proves the report
is internally consistent — genuinely useful — but on a merchant with a rolling reserve it explains not
one rupee of the gross-to-cash gap. Increment 0's 100% was a fact about clean data, not about the
resolver.

Two subtleties a reviewer should push on:

**An edge counts at tier N only if *both* its linkage and its explanation are within N.** Tier 3 can
propose a link that Tier 1 then explains; crediting that to Tier 1 would make the LLM look useless by
construction. Edges carry `linked_by` separately from `tier` (D-021).

**`MDR_SLAB_MISMATCH` does not move the residual.** Tier 0 builds its MDR component from the fee
*actually charged*, so an overcharge is internally consistent and still sums to zero. It is
recoverable money, not unexplained money — the one case where a fully explained settlement legitimately
still carries a break.

### How the false-clear metric is kept honest

Every exception class declares `detectable_at`, the lowest tier that can flag it; `BUILT_TIER`
declares how far this build actually goes. False clear splits into **in-remit** (a break the built
resolver was accountable for and silently passed — **must be zero**, and is: 0/192 dev, 0/184 eval)
and **out-of-remit** (needs a tier that does not exist; nothing was cleared, nothing looked).

Without a guard this split would be a way to relabel real misses, so:

**Verify:**
- `test_each_tier_covers_the_remit_it_declares` — a class marked `detectable_at == N` must actually be
  raised by tier N's module. Not "somewhere in the resolver" — that specific tier.
- `test_built_tier_matches_the_tiers_actually_wired_in` — `BUILT_TIER` cannot run ahead of the code.
- `test_no_false_clears_within_the_built_tier_remit`
- `metrics.json` → `ablation`, computed as a filter over edges.

---

## 3. The fence — what the LLM may and may not do

**May:** propose a UTR extracted from one bank narration.
**May not:** choose between candidate settlements, explain a residual, touch an amount, or see
anything except the free text. It is not given the credit amount, the date, or a list of valid UTRs —
handing it valid UTRs would let it "extract" one it never read, and the verifier could not tell the
difference.

Every proposal is re-verified by **exact lookup**. A UTR either resolves to a known settlement or it
does not: no tolerance, no scoring, nothing for a confident wrong answer to win. An accepted edge is
`MATCHED`, not `EXPLAINED` — Tier 1 still has to explain the money before anything posts.

### Finding 1 — the fence holds under attack

A deliberately hostile adjudicator returns well-formed, plausible, **wrong** UTRs with grounded-sounding
rationales.

**22 proposed, 22 blocked, 0 edges created, linkage precision unmoved at 100.00%, statement still
foots.** A fence that rejects everything is a wall, so the control matters too: a truthful adjudicator
*is* accepted.

`test_a_hostile_adjudicator_is_blocked_completely` ·
`test_linkage_precision_is_unmoved_by_a_hostile_adjudicator` ·
`test_a_truthful_adjudicator_is_accepted_so_the_fence_is_not_a_wall`

### Finding 2 — the verifier is necessary and *not sufficient* (D-023)

The gate blocks wrong answers. It does **not** block a *correct* answer to an ambiguous question.

Tier 0 refuses to link a UTR carried by two credits, because picking one is a coin flip presented as a
fact (D-014). An adjudicator reading that same duplicated UTR is not hallucinating — it is right — so
the lookup succeeds and Tier 3 would make exactly the link Tier 0 declined.

Measured cost of not having the second guard: **linkage precision 99.97% and a statement that no
longer foots.** It surfaced only because both are asserted, not just the block count.

**"The model was correct" and "the action was safe" are different questions, and only the second one
matters at the gate.**

`test_a_correctly_read_but_ambiguous_utr_is_still_refused`

### Finding 3 — three live runs disagreed, and we published the range

Same 22 held-out narrations, same prompt, same model (`claude-haiku-4-5`):

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| Correct and verified | 5/22 | 3/22 | 4/22 |
| `blocked_hallucination` | 3 | 5 | 4 |
| `blocked_unverifiable` | **14** | **14** | **14** |
| **Linkage precision** | **100.00%** | **100.00%** | **100.00%** |

**We report 3–5 of 22 — 38–62% on recoverable data. Quoting 62% alone would be quoting the better
sample.**

The 14 are identical every run because those narrations have the UTR *physically cut out* at 40
characters; the model returns exactly what is there and is **right**. Calling that a hallucination
overstated model error roughly fivefold, so the counter was split (D-025) — same judgment as Finding 2,
one level along. The discriminator works from the narration alone and is deliberately biased toward
blaming the model.

**Underneath a model swinging 24 points, precision did not move once.** The LLM is *allowed* to be
unreliable. That is the design.

### Where determinism stops

Same seed ⇒ byte-identical `metrics.json` for the shipped rules-only path and any deterministic
adjudicator (both tested). **Not** with a live LLM — the response cache is per-run (D-026). Stated
here rather than left for a reviewer to find.

---

## 4. Honest absences

Not oversights. Each is a dated decision recording what it ruled out.

| Absent | Why | Decision |
|---|---|---|
| **Tier 2 (subset-sum)** | Increment 1 measured the residual as 100% typed with **zero scatter** — nothing for a search to search. Building difficulty *to justify* the LLM is the §9 anti-pattern. | D-016 |
| **Multi-gateway collision** | Held as the ambiguity "lever" from 25 Aug, then cut outright rather than manufacture difficulty. | D-016 |
| **Second merchant scenario** | Doubles generator surface, produces no new *break shape*; a card-heavy merchant's difficulty fits inside one merchant's method mix. | D-011 |
| **FX / international** | A second currency threaded through the money type, to buy one exception code. | D-011 |
| **TDS 194-O** | Out by merchant persona — monthly-grain, seller-level, reconciled to Form 26AS. A second sub-recon at a different grain. | Assumption 1 |
| **Third rate-card seed** | Would upgrade "generalises across worlds" to "across contracts". 1–2 h, fixes nothing broken. | D-024 |
| **Cross-run LLM cache** | Would make `--llm` runs reproducible. The demo and every gate run the deterministic core. | D-026 |

The taxonomy is disciplined the same way: `CHARGEBACK_FEE_UNBOOKED` and `PARTIAL_SETTLEMENT` were
**removed** from `ExceptionType` because the generator cannot honestly produce them (D-013). A
taxonomy entry with no data behind it is a claim we cannot back.

---

## 5. What we would build next

Ranked by value, with honest cost. This is the difference between *ran out of scope* and *ran out of
time*: everything below is designed for and unblocked, not aspirational.

**1. A third seed on a different rate card — 1–2 h.** The one measurement that would materially
strengthen the strongest claim. Tier 1 currently proves it generalises across *worlds* drawn from the
same rate card; a seed with different constants would prove it across *contracts*, or reveal that
Tier 1 silently closes when it should be reporting mismatches. The rate card is module-level constants
today and would need to become injectable. (D-024 — declined on time, not on merit.)

**2. Persist the adjudicator cache across runs — 30–45 min.** Restores byte-identical runs with
`--llm` enabled, keyed by narration hash. Would collapse the 3–5 range into a reproducible figure.
(D-026.)

**3. A prompt tuned against `dev` narrations — 1 h.** The current prompt was written **blind** and has
never been tuned, deliberately: tuning against held-out results would make the ablation measure our
tuning rather than the model. The disciplined version tunes on `dev` only, then re-measures on `eval`
once.

**4. `RazorpayAPISource` — ~1 h.** The `SettlementSource` protocol (`ingest/source.py`) was built in
Increment 0 precisely so a read-only live adapter is an implementation rather than a refactor. The
seam exists and is unused.

**5. Tier 2, if and only if data demands it.** Not "next" so much as *conditional*: it needs a
residual distribution with genuine scatter, which our generator does not produce and which we declined
to manufacture. On real merchant data, this is the first thing to re-measure.

**What we would not do:** add features to broaden the surface. The submission's argument is one deep
loop measured honestly, and four shallow features is the §9 anti-pattern that would weaken it.
