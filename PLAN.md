# PLAN.md — AI Finance Controller (Razorpay Buildathon, Track 04)

> **This document is APPEND-ONLY at gates.** Do not rewrite history. At each gate:
> add measured results to `RUN_LOG.md`, append an entry to the **Decisions Log** at the
> bottom of this file, re-rank the cut list *in place* with a dated note, and append the
> next increment's plan below the current one. Superseded plans stay, marked `[CLOSED]`.
> The value of this file is the trail, not the tidiness.

---

## Status

| | |
|---|---|
| **Current increment** | 3 — Fenced adjudicator **[CLOSED 01 Sep]** · next: Increment 6 (protected) |
| **Deadline** | 05 Sep 2026 — **confirmed with user** (not published on razorpay.com/buildathon) |
| **Today** | 31 Aug 2026 |
| **Elapsed / remaining** | 9 of 13 days elapsed (69%) · **4 days remain** · engine work stops 03 Sep · scope cut at the Inc 1 gate |
| **Hard stop on engine work** | 03 Sep — Increment 6 needs 2 protected days (3 of the 4 deliverables) |
| **Public repo** | github.com/Shashankkaranamr/ai-finance-controller — live |

---

## Product thesis (one paragraph, for the README and the video)

Finding the counterparty is easy; **explaining the amount is the job**. A controller tying a
Razorpay settlement to a bank credit is not asking "which credit is this" — the UTR answers that.
They are asking "why is this credit short of gross sales by this much", and the answer is MDR, GST
on MDR, rolling reserve, refund offsets and chargebacks tangled together across a T+2 cycle. So the
headline metric of this system is **explanation rate** — bank credits whose residual is zero with
every component typed — not match rate. Match rate is reported alongside as the easy supporting
number, precisely so nobody mistakes it for the achievement.

---

## Assumptions on the brief's §12 open decisions

Stated and proceeding per §13.4 ("assume, don't block"). Each names the gate at which it is revisited.

| # | Decision | Position | Revisit at |
|---|---|---|---|
| 1 | Merchant persona | **Direct merchant. TDS 194-O is OUT of the deduction stack.** 194-O is monthly-grain, seller-level, reconciled to Form 26AS — a second sub-recon at a different grain from per-settlement. It buys one exception code for disproportionate generator work. Scoping it out *and defending why* beats modelling it badly. Stack for now: MDR, GST on MDR, rolling reserve, refund offsets, chargeback reversal, chargeback fee. | Inc 2 gate, only if residuals are too thin |
| 2 | Multi-gateway | **Single gateway (Razorpay only).** `MULTI_GATEWAY_COLLISION` deferred — but held as the cheapest **lever** to manufacture genuine Tier-2 ambiguity if Inc 2 shows residuals are mechanical. A reserve, not dead scope. | Inc 2 gate |
| 3 | Live test-mode API | **Synthetic only.** But a `SettlementSource` protocol is defined in Inc 0 so a read-only `RazorpayAPISource` is a ~1h add later. An interface costs nothing; an unbacked claim costs credibility. | Inc 6, if time |
| 4 | Agent vs pipeline | **It is a pipeline, and we say so.** §9 names "agent as marketing" an anti-pattern, and the AI-judgment axis rewards *not* forcing tech. Called "a deterministic pipeline with a fenced LLM adjudicator" in code, README and video; the track's wording is addressed head-on in one sentence rather than dressed up. | Never — a posture, not a scope call |
| 5 | Forward cash forecast | **Cut now.** Top of the cut list. | After Inc 4 gate |
| 6 | UI budget | **≤15% of total time, and zero in Inc 0.** Output is stdout + written artifacts. Streamlit at Inc 6, for the video only. | Inc 4 gate |

---

## INCREMENT 0 — Walking Skeleton  **[CLOSED 25 Aug 2026]**

**Goal:** Prove the reconciliation grain model, the ground-truth schema and the metric denominators
by running one command end to end on clean synthetic data into real artifacts — including a
reconciliation statement that foots to zero and one typed exception.

Increment 0's job is not features. It is to lock the three things that are expensive to change
later — the **grain**, the **ground-truth schema**, and the **metric denominators** — and to prove
them by running all the way to an artifact.

**Exit gate.** On a clean clone, with no network and no API key, `python -m recon demo` finishes in
under 5 minutes and:

1. prints per-grain numbers: bank-credit **explanation rate**, line-item match rate, money-weighted coverage;
2. prints precision / recall / **false-clear rate** against `ground_truth.json`;
3. writes `out/dev/{metrics.json, recon_statement.md, exceptions.jsonl, journal_entries.jsonl, audit.jsonl}`;
4. the reconciliation statement **foots to zero** — asserted, non-zero exit if not;
5. exactly one seeded `MISSING_BANK_CREDIT` is in the queue, typed, with its evidence chain;
6. two consecutive runs on the same seed produce **byte-identical** `metrics.json`;
7. `pytest` green — including the §3.2 arithmetic identities as property tests and a no-floats-in-the-money-path check.

**Expected learning** (what this changes downstream):

- Whether the grain model survives real records, or whether a grain is missing/wrong. Prime suspect:
  `REFUND_TO_PAYMENT` across settlement cycles.
- What the ground-truth schema must carry to make **false-clear** computable at all. Learned by
  actually computing it; Inc 1's generator is then locked to that field set.
- Whether the footing identity holds on clean data. If it cannot be made to foot here, the entity
  model is wrong and Inc 1 changes shape. *A failure here is the most valuable thing Inc 0 could find.*
- Real wall-clock and install time against the `<5 min` clean-clone gate.

**Tasks** — ordered most-uncertain-first per §13.4:

- [x] 1. **Grain + edge model** — `src/recon/domain/graph.py`. *Reviewed and signed off before implementation.*
- [x] 2. **Ground-truth schema** — `src/recon/domain/truth.py`. Designed backwards from "what does false-clear need?"
- [x] 3. **Metric definitions, before any number prints** — `src/recon/report/metrics.py` + formulas in README
- [x] 4. **Money type** — `src/recon/money.py`. `Paise` int newtype. No floats in the money path, ever
- [x] 5. **§3.2 identities as pure functions + property tests** — `src/recon/domain/identities.py`
- [x] 6. **Minimal generator** — `src/recon/generate/{world,derive,narration}.py` → `data/generated/dev/`
- [x] 7. **Ingest + quarantine** — `src/recon/ingest/load.py` (Pydantic; bad rows quarantined, not fatal)
- [x] 8. **Tier 0 resolver** — `src/recon/resolve/tier0.py`
- [x] 9. **Pipeline + LLM seam (null impl)** — `src/recon/resolve/pipeline.py`, `src/recon/llm/client.py`
- [x] 10. **Audit log** — `src/recon/audit/log.py`. Append-only JSONL; run reconstructible from the log alone
- [x] 11. **Recon statement + minimal JE** — `src/recon/ledger/statement.py`. Footing mandatory; JE is cuttable
- [x] 12. **One exception type** — `MISSING_BANK_CREDIT`, seeded once, typed, with evidence
- [x] 13. **Determinism test** — same seed produces byte-identical `metrics.json`
- [x] 14. **Entrypoint + repo hygiene** — `python -m recon {generate,run,demo,eval}`, Makefile forwarder, git init
- [x] 15. **Docs seeded** — `README.md` (formulas), `RUN_LOG.md`, `FAILURE_LOG.md` (written *during*, real dates)

**Deliberately NOT in Increment 0:** Tier 1 decomposition · Tier 2 · any LLM call · MDR slab tables ·
rolling reserve · chargebacks · held-out eval seed · anomaly injection beyond the one type ·
ablation table · any UI.

**Dependencies:** `pydantic`, `pytest`. Nothing else. SQLite (stdlib) over DuckDB — zero install
protects the clean-clone gate; revisit if analytical SQL gets painful. No pandas/polars until a
profile says otherwise; 2,000 rows is nothing for pure Python, and install weight is a real cost
against a 5-minute gate.

**Time:** Inc 0 target 1 day. 11 days remain. Engine work stops 03 Sep.

**Next (tentative, one line):** Faithful generator — full §3.1 schema, anomaly injection, dev + held-out seeds.

---

## INCREMENT 1 — Faithful generator  **[CLOSED 31 Aug 2026]**

**Goal:** Replace Increment 0's clean, payments-only world with data a controller would recognise —
the full §3.1 schema, the whole Indian deduction stack, refunds and disputes crossing cycles, and
anomalies injected at realistic rates across two seeds, one of them held out. Increment 1 adds
**no new resolver capability**. Its deliverable is data, plus the measurement that decides what
Increment 2 has to be.

Increment 0 locked the three expensive things — the grain, the ground-truth schema, the metric
denominators. Increment 1 loads them.

### The measurement this increment exists to produce

§13.1 makes the Inc 2 pivot depend on the residual distribution. That distribution is a property of
the *data*, and it cannot be read off a generator that does not exist yet. So the gate is not "the
generator runs". It is: **here is the unexplained money, bucketed by its true component type, and
here is therefore how much of the gap an arithmetic Tier 1 could possibly reach.**

**Tier 0's explanation rate will fall hard. That is the finding, not a regression.** Tier 0 reads the
`fee` and `tax` the source reports and checks §3.2's identities. It knows nothing about rolling
reserve, chargeback reversals or refund offsets. The moment those enter the world,
`gross − cash − MDR − GST` stops landing on zero for most settlements. Recording that fall *is* the
justification for building Tier 1. Reading it as a regression and "fixing" Tier 0 would be doing
Increment 2's work inside Increment 1, against the one rule this repo most wants kept.

**So the "is the data too clean?" question is answered from ground truth, not from the resolver.**
CLAUDE.md targets 85–92% cleanly resolvable. Tier 0's post-Inc-1 score measures Tier 0's ignorance of
a deduction stack, not the data's difficulty — the two numbers answer different questions and only one
of them is the open question. Inc 1 therefore adds an intrinsic **clean rate**: units carrying no
injected anomaly, over all units, computed from `ground_truth.json` alone with no resolver involved.
That is the number checked against 85–92%. Tier 0's explanation rate is recorded beside it.

### Scope

**The world (`generate/world.py`).** One merchant, net settlement, single gateway — mixed method
profile (UPI-heavy, with enough card volume to carry disputes and a reserve). Cut-list rank 7,
"second/third merchant scenario", **stays deferred**: a second merchant doubles the generator surface
without producing a single new *break shape*, and the difficulty the brief wants from a card-heavy
merchant can live inside one merchant's method mix. FX stays cut — it needs a second currency
threaded through the money type for one exception code.

**The deduction stack (§3.3), all of it except TDS 194-O** (out by persona, Assumption 1):
MDR by slab · GST on MDR · rolling reserve withheld · reserve release matched back to its originating
cycle · refund offset · chargeback reversal · chargeback fee.

**Line types.** All four of `payment | refund | transfer | adjustment`, each non-trivial. ID prefixes
mirrored exactly: `pay_ rfnd_ trf_ adj_ order_ setl_ setlod_ setlodp_`.

**Timing (§3.4).** T+2 on a batched cycle; refunds and chargebacks that debit a later cycle than the
payment they reverse; a month-end straddle where books and bank correctly disagree; `on_hold` lines
captured but never settled; instant `setlod_*` settlements interleaved with the scheduled cycle.

**Rates (`domain/rates.py`, new).** The flat 200 bps of Inc 0 becomes a real slab table keyed by
`method` × `card_network` × `card_type`, in integer basis points. `RULE_VERSION` bumps. Only at this
point does `MDR_SLAB_MISMATCH` mean anything, which is why Inc 0 did not pretend to have it.

**Anomaly injection (`generate/anomalies.py`, new).** Controlled, declared rates, every one tagged in
ground truth at injection time. Never labelled after the fact.

**Two seeds.** `dev` and a held-out `eval`. The eval seed generates from **eval-only** narration
families (deviation #4), so the Inc 3 ablation is held out at the template level and not merely at
the seed level. `parse_utr` hit rate is reported per split — that gap is the LLM's justification, or
its refutation.

**The `eval` subcommand** ships here, closing D-007.

### Exit gate

1. **Scale:** 1,000–2,000 settlement line items, 60–90 days, 15–25 settlement cycles, on each seed.
2. **Schema:** every §3.1 field emitted; all four `type` values present and non-trivial; ID prefixes exact.
3. **Stack:** MDR (slab), GST, reserve withheld, reserve release, refund offset, chargeback reversal
   and chargeback fee all present in the world *and* carried in `ground_truth.json` as typed components.
4. **Intrinsic clean rate lands in 85–92% on both seeds**, computed from ground truth alone.
   Outside that band, the generator is wrong and gets fixed before Increment 2 starts.
5. **One declared expected-to-fail class, and it does fail:** `REFUND_ORPHANED` where the original
   payment predates the extract window. Chosen because it is *structurally* unknowable rather than
   merely hard — no tier, including an LLM, can link a refund to a payment that is not in the data.
   Named in the README as a blind spot.
6. **Held-out split is real:** eval seed renders from eval-only families; `parse_utr` hit rate
   reported separately for dev and eval.
7. **Residual distribution published:** Tier 0's unexplained money bucketed by *true* component type
   from ground truth. This is the Increment 2 input and the reason the gate exists.
8. **False-clear rate still 0.00%** on both seeds. Non-negotiable — it is on the never-cut list.
   > **AMENDED 31 Aug 2026, during the increment.** As written this condition was unmeetable by
   > construction, and the original text is left above so the error is visible. `MDR_SLAB_MISMATCH`
   > requires the contracted rate card to detect — that is the definition of Tier 1 — so holding
   > Tier 0 to a 0% false-clear rate against it would have forced Increment 2's work into
   > Increment 1. The condition now reads: **false clear WITHIN THE BUILT TIER'S REMIT must be
   > 0.00% on both seeds**, with out-of-remit breaks reported separately and every one of them
   > naming a class declared unreachable at this tier *before* the run. See F-005 and D-009.
9. **Determinism per seed:** two runs, byte-identical `metrics.json`, on `dev` and on `eval`.
10. **Statement still foots to zero on both seeds**; journal entries still balance. The stack is new
    money moving through the entity model, and this is what proves the model absorbed it.
11. `pytest` green. Float-free scan still total. New identities property-tested.
12. Clean-clone demo still inside the 300 s gate at ~3× the record count.

### Expected learning

- **The residual distribution** — mechanical and typeable, or scattered and ambiguous? This is the
  Inc 2 fork, and both branches are good submissions.
- **Whether `REFUND_TO_PAYMENT` survives contact with cross-cycle refunds.** Declared on hypothesis in
  Inc 0, unexercised, and named in CLAUDE.md as the part of the grain model most likely to be wrong.
  Inc 1 is where it either holds or breaks.
- **Whether the footing identity survives the deduction stack.** It footed trivially on clean data.
  Reserve is a receivable and not cash, which is precisely the shape that breaks a naive statement.
- **How far the dev-only parser actually falls on eval narrations.** A small gap weakens the LLM case
  and should be reported as such.

### Deliberately NOT in Increment 1

Tier 1 decomposition · Tier 2 · any LLM call · TDS 194-O · FX · multi-gateway · second merchant
scenario · any UI · ablation table · `ARCHITECTURE.md`.

### Open uncertainties (Increment 1)

| # | Uncertainty | Why uncertain | How Inc 1 resolves it |
|---|---|---|---|
| 1 | Does `REFUND_TO_PAYMENT` hold across cycles? | Declared on hypothesis in Inc 0 and never exercised | Generate cross-cycle refunds and see whether a binary edge expresses them |
| 2 | Can the statement still foot with a rolling reserve? | Reserve is a receivable, not cash — a naive statement double-counts or drops it | Assert footing on both seeds; a failure here is the most valuable finding available |
| 3 | Is 85–92% reachable by construction? | Injection rates compose in ways that are hard to predict — anomalies overlap on the same unit | Measure intrinsic clean rate from ground truth and tune rates against it, not against expectations |
| 4 | How large is the dev/eval narration gap? | We wrote both sides; the gap could be trivial | Report `parse_utr` hit rate per split as a first-class number |

### Answers, 31 Aug 2026

1. **`REFUND_TO_PAYMENT` holds.** Exercised for the first time against 60+ cross-cycle refunds per
   seed; the binary edge expresses them without strain, and "the refund settles in a later cycle
   than its payment" is carried as evidence on the edge rather than needing a new grain. The grain
   model's most suspect declaration survived contact. **Uncertainty closed.**
2. **The statement still foots with a rolling reserve**, on both seeds, first try. The reserve is
   two adjustment lines — a debit when withheld and a credit when released — so it moves through the
   entity model as line items rather than as a special case. No rework needed.
3. **85–92% was reachable, but only after measuring.** The first tuning landed at 91.97% (dev),
   sitting on the top edge of the band. Rates were raised and re-measured to 89.12% / 89.46%. This
   is exactly why the target is checked against ground truth and not against the resolver.
4. **The narration gap is enormous, and that is a caveat as much as a result.** 100.00% (24/24) on
   dev, 8.33% (2/24) on eval — and the two eval hits are injected stray credits carrying their own
   narration, so the true figure on held-out settlement narrations is **0 of 22**. Both held-out
   families defeat the regex structurally (one truncates the UTR, one removes the delimiters). The
   honest reading is "this parser handles 0 of 2 unseen shapes", NOT "an LLM adds 100 points". With
   only two held-out families the number is a direction, not a magnitude, and the Increment 3
   ablation must say so.

---

## INCREMENT 2 — Tier 1 arithmetic variance decomposition  **[CLOSED 01 Sep 2026]**

**Goal:** Close the residual. Type every remaining component of the gross-to-cash gap from the
report's own fields and the contracted rate card, so a settlement reaches `EXPLAINED` with
`residual == 0` and the ledger can post it. Detect fees charged off-contract. Measure the result on
both seeds, and measure honestly how much of that result is circular.

**The pivot is decided: (A) ACCEPT.** Tier 1 closes the loop; the LLM is confined to narration
parsing, where a real measured gap already exists. Multi-gateway is **fully cut, not deferred**
(D-016). Three engine days remain (01-03 Sep), and manufacturing ambiguity to give the LLM a job is close enough
to the §9 "agent as marketing" anti-pattern that a panel would read the ablation as staged.

### What Tier 1 does, and where the line is

Tier 0 reads the fee and tax the report *states* and checks §3.2's identities over them. Tier 1 is
the first tier with a second, independent opinion: the contracted rate card in `domain/rates.py`.

Two jobs, and they are different:

**(a) Close the residual.** Type the components Tier 0 cannot: refund offset, transfer out,
chargeback reversal, chargeback fee, rolling reserve, reserve release, instant settlement fee.

**(b) Detect off-contract fees.** Compare reported fee against the slab for that
`method` x `card_network` x `card_type`. Note this does **not** move the residual: Tier 0's MDR
component is built from the fee actually charged, so an overcharge produces a decomposition that is
wrong but internally consistent. `MDR_SLAB_MISMATCH` is recoverable money, not unexplained money.
It is the 83/80 out-of-remit misses from Increment 1, and it is what moves them in-remit.

`BUILT_TIER` goes 0 -> 1 **in the same commit that lands the resolver**, never ahead of it.

### The circularity condition — the reason this gate is not just "explanation rate went up"

The eval seed is a different world drawn from the **same rule constants**: reserve 500 bps, GST
1800 bps, chargeback fee Rs 1,500, the same MDR slabs. So a high explanation rate on eval shows the
rules apply correctly to unseen *instances*. It does **not** show the rules were discovered rather
than assumed, and it says nothing about a merchant on a different contract. This is D-015's
circularity resurfacing one tier up, and it must not be reported as generalization.

It is measurable rather than merely confessable, because the derived report **does not carry a
`component` field** — Tier 1 has to infer what an adjustment is. How it infers is exactly the axis
that matters, so every typed component is partitioned three ways and the split is published:

| Class | Typed from | Circular? |
|---|---|---|
| **Schema-derived** | documented §3.1 fields: `type == refund`, `type == transfer`, `dispute_id` present | **No.** The gateway asserts it; we would read the same field from a real report |
| **Contract-derived** | a rate-card constant a real controller also holds: per-dispute fee, reserve rate, instant fee rate | **Partly.** The constant is contractual, not invented — but we generated with it too |
| **Narrative-derived** | free text we wrote (`description`, `notes`) | **Yes, fully.** Also §9 fuzzy matching. **Banned** — see below |

**`description` and `notes` are off limits to the resolver.** "Rolling reserve withheld" is a string
we authored; typing an adjustment off it would be circular AND the fuzzy string matching §9 names as
the number one thing that sinks the submission. Reserve is identified arithmetically — an adjustment
debit equal to `round_half_up(settled credits x 500bps)` — and `notes` may appear in *evidence* but
never in the decision. Enforced by a test, not a convention.

Expected shape from Increment 1's residual: refunds + transfers + chargebacks are schema-derived
(~54% of movement), reserve + release + instant fee are contract-derived (~45%). **Publishing that
split, with the caveat attached, is gate condition 5.** If it lands very differently, that is itself
the finding.

### Exit gate

Numbers on **both seeds**, dev and eval, every one of them.

1. **Explanation rate (bank credits) AND settlement coverage**, together, never one alone (D-005).
   Measured, not targeted — if Tier 1 leaves a residual, that is the result.
2. **Every `EXPLAINED` edge has `residual == 0` with every component typed.** Any settlement Tier 1
   cannot close carries `AMOUNT_VARIANCE_UNEXPLAINED` with the amount stated.
3. `BUILT_TIER == 1`, and **false-clear in remit == 0.00%** — now with a larger denominator, since
   `MDR_SLAB_MISMATCH`, `RESERVE_WITHHELD` and `RESERVE_RELEASE_UNMATCHED` become in-remit.
4. **`MDR_SLAB_MISMATCH` detection recall**, against the 83 dev / 80 eval injected at Inc 1.
5. **The circularity partition, published**: explained money split schema-derived vs
   contract-derived, with an explicit written statement of what the eval number does and does not
   prove. Flagged either way, per the standing instruction.
6. **The ablation table falls out**: explanation rate at Tier 0 alone vs Tier 0+1, both seeds. Tier
   is an edge attribute, so this is a group-by, not a second run (invariant 5).
7. **Journal entries now post.** Every one balances; the statement still foots to zero on both
   seeds. This is the Increment 4 tail arriving on its own once settlements are explainable.
8. Determinism per seed: byte-identical `metrics.json`, holding across regeneration.
9. `pytest` green; the float scan still total over the whole package.
10. Clean clone still inside the 300 s gate.

### Deliberately NOT in Increment 2

Any LLM call · Tier 2 subset-sum · multi-gateway (CUT) · second merchant (CUT) · FX (CUT) · UI ·
`ARCHITECTURE.md`. The verifier gate and `blocked_hallucination` stay with the LLM increment, where
they have something to verify.

### Open uncertainties (Increment 2)

| # | Uncertainty | Why uncertain | How Inc 2 resolves it |
|---|---|---|---|
| 1 | Can reserve be identified without reading our own prose? | The §3.1 schema has no field saying "this debit is a reserve"; the only honest discriminator is arithmetic | Type it by `round_half_up(credits x 500bps)` and measure how often that is unambiguous |
| 2 | Can a reserve release be tied to its originating cycle arithmetically? | `notes` carries the answer, and `notes` is banned | Match on amount + hold period against prior cycles; unmatched becomes `RESERVE_RELEASE_UNMATCHED` |
| 3 | Does anything remain unexplained after Tier 1? | Inc 1 says no, but by construction | Measure. A non-zero residual is the more interesting outcome |
| 4 | Does the chargeback fee/reversal split survive without `description`? | Both carry `dispute_id`; only the contracted fee amount separates them | Split on the rate-card constant and count misclassifications |

---

## INCREMENT 3 — The fenced adjudicator  **[CLOSED 01 Sep 2026]**

**Goal:** Give the LLM exactly one job — extracting a UTR from a narration no deterministic parser
was written for — and fence it so it cannot corrupt the ledger. Then **measure the fence**, which is
the part that can be measured tonight.

**There is no API key in this environment.** That is the fact that shapes this increment, and the
conservative response is to build everything that is testable without one and claim nothing that is
not. So: the adjudicator, the cache, the verifier gate, the `blocked_hallucination` counter, degraded
mode and the ablation harness all land and are tested. **The LLM's actual extraction accuracy is not
measured and is not claimed anywhere.** It needs a key, and that is flagged as a task for review
rather than quietly estimated.

That is not a hole in the submission. The architectural claim — *the LLM selects and explains, the
arithmetic engine verifies, and a hallucination cannot survive* — is the claim worth defending, and
it is provable without a key by pointing a deliberately **hostile** adjudicator at the fence and
counting what gets through. Zero is the only acceptable answer.

### Where the LLM is allowed to act, and where it is not

Invariant 8: the LLM never computes money. It gets one job, `parse_narration`, and only on bank
credits where the regex found nothing. Its output is a *candidate string*, immediately re-verified by
exact lookup against known settlement UTRs. A proposal that does not resolve is REJECTED and counted.

It is never asked to choose between candidate settlements, never to explain a residual, never to
touch an amount. Tier 1 closed 100% of the gaps it was given (D-018), so there is no arithmetic left
for an LLM to help with — and inventing a job for it would be the §9 anti-pattern D-016 already ruled
out.

### Dependency rule, unchanged

The `anthropic` SDK is an **optional extra** (`pip install -e ".[llm]"`), imported lazily inside the
adjudicator. CLAUDE.md pins the default install to `pydantic` + `pytest` to protect the clean-clone
gate, and that stands: with no SDK and no key the adjudicator reports unavailable with a reason, and
the run degrades exactly as it does today.

### Exit gate

Every condition below is measurable with **no API key**.

1. **Tier 3 is asked only where Tier 0 failed.** Adjudicator calls == narrations the regex could not
   parse. It must never be consulted about a narration already resolved deterministically.
2. **The fence holds under attack.** A hostile adjudicator returning plausible-but-wrong UTRs gets
   **100% blocked**; `blocked_hallucination` equals the number of proposals made.
3. **Linkage precision stays 100.00%** with that hostile adjudicator wired in. This is the real claim:
   a hallucination cannot become a match.
4. **A truthful adjudicator is accepted**, proving the gate is a verifier and not a blanket refusal —
   a fence that rejects everything is not a fence, it is a wall.
5. **Degraded mode unchanged:** no adjudicator, run completes, reports degraded, exit 0.
6. **Determinism:** repeated runs byte-identical with an adjudicator wired in; the cache is what
   guarantees it, since sampling never can.
7. **Ablation extends to T3**, cumulative, still a group-by.
8. `pytest` green; float scan still total; clean clone still inside 300 s with the default extras.
9. **Explicitly NOT claimed:** any figure for the LLM's real-world extraction accuracy. Requires a
   key; flagged for review.

### Deliberately NOT in Increment 3

Any claim about LLM accuracy · Tier 2 (CUT) · multi-gateway (CUT) · a second merchant (CUT) · UI.

---

## Deviations from the brief, and why

The brief called itself a hypothesis and asked to be argued with. Five positions, load-bearing enough
to record here rather than only in the video.

1. **There are three grains, not one pipeline.** §4 reads as stages over "records", but Tier 0 alone
   spans bank↔settlement (1:1), settlement↔line (1:N) and line↔book (1:1). Blurring them makes the
   match-rate denominator indefensible — §7 warns that ambiguous metrics are the easiest way to lose a
   technical panel. Modelled instead as a **graph of typed edges**; tiers are edge-resolution
   strategies, not pipeline stages. §7's "two granularities" then falls out by construction.
2. **Tier 0 will look deceptively good, and "match rate" is the wrong headline.** Exact UTR join
   clears ~95%+ on any realistic data. Publishing that invites exactly the "one cherry-picked match
   proves nothing" objection. Headline is **explanation rate**. Set now, before any number prints, so
   the framing is not retrofitted later.
3. **Tier 2 as specified is the §9 anti-pattern wearing a hat.** "Blocking on amount plus/minus
   tolerance, score on proximity and token overlap" is fuzzy matching, which §9 names the number one
   thing that sinks the submission. The structurally correct tool for N-to-1 — *which line items
   compose this credit* — is **bounded subset-sum over a date-windowed candidate set**: deterministic,
   exact, and it produces an arithmetic proof rather than a score. Similarity scoring gets confined to
   the narrow orphan-credit case. Leading hypothesis to test at the Inc 2 gate; not built in Inc 0.
4. **The narration/LLM ablation is circular unless the generator is designed against it now.** §3.5 is
   right that messy narration is the legitimate LLM surface — but *we write the narrations*. A regex
   authored against the same templates that generate the eval data wins trivially, and the ablation
   then proves something about our generator, not about reality. A panel will spot it. Mitigation,
   decided now because it constrains the Inc 1 generator: a **narration template registry split into
   `dev_only` and `eval_only` families**, with a standing rule that deterministic parsers are written
   only against `dev` families. Held out at the *template* level, not just the seed level.
5. **The footing assertion belongs in Inc 0, not Inc 4.** `opening receivable + gross sales −
   settlements received − explained variance − exceptions = closing receivable` is not a feature, it is
   a **constraint on the entity model**. Finding at Inc 4 that our entities cannot produce a balancing
   statement is a late, expensive rework. A walking skeleton runs end to end through *every* layer, and
   §1.3 is explicit that the loop must terminate in an artifact — a skeleton stopping at a printed
   match rate has not walked to the end of the loop. On clean data it is nearly trivial to make foot,
   which is exactly why it costs almost nothing now.

**Sequence changes to §13.3** — three pull-forwards into Inc 0, everything else unchanged:
the **footing assertion** (from Inc 4); the **LLM client seam and cache interface as a null
implementation** (from Inc 3/5 — no LLM call exists in Inc 0, the *seam* does, so degraded mode
becomes an implementation later instead of a refactor); and the **determinism contract** (from §8 —
cheapest to establish when there is almost no code, and Inc 3's caching claim depends on it).

**Flagged, not changed:** Inc 3 is probably two increments (Tier 2, then Tier 3-if-justified).
Decide at the Inc 2 gate.

---

## Increments 1–6 — intent only

Per §13.1, planning past Inc 2 is guessing: the residual distribution after Tier 1 decides whether
Tier 2 finishes the job (and the LLM has no defensible place) or the residuals scatter into genuine
ambiguity (and Tier 3 is the centrepiece). Both are good submissions. They are different submissions.
**One line each. Do not expand until the gate.**

1. Faithful generator: real §3.1 schema, anomaly injection at realistic rates, dev + held-out seeds.
2. Tier 1 arithmetic variance decomposition, and measure the residual distribution. **The pivot.**
3. Whatever Inc 2's residuals actually demand — subset-sum, scoring, LLM adjudication, or a defensible subset.
4. Ledger and loop closure: full journal entries, cash position, prioritised exception queue.
5. Failure recovery: verifier gate, `blocked_hallucination` counter, degraded mode, backoff, idempotency.
6. Artifacts: video, README with formulas, architecture doc, failure log. **Protected — 2 days.**

---

## Cut list — cheapest to cut first

Re-ranked *in place* at every gate, with a dated note. Never rewritten.

| Rank | Item | Status | Note |
|---|---|---|---|
| 1 | Forward cash forecast (§2 stretch) | **CUT** 25 Aug | Revisit only after Inc 4 gate |
| 2 | Live Razorpay test-mode adapter | Interface only | `SettlementSource` protocol in Inc 0; impl deferred to Inc 6 |
| 3 | Streamlit UI beyond one screen | Deferred | The video needs one screen, not an app |
| 4 | Multi-gateway collision class | **Held as a lever** | Not dead — cheapest way to manufacture real Tier-2 ambiguity if Inc 2 residuals are mechanical |
| 5 | TDS 194-O | Out by persona choice | Defend the decision, not the mechanics |
| 6 | Inc 0's minimal journal entry | Cuttable within Inc 0 | Keep the footing assertion regardless |
| 7 | Second / third merchant scenario | Deferred | Inc 1 decides |
| — | **Never cut** | — | Held-out seed · false-clear metric · degraded mode · Increment 6 |

**Re-ranked 31 Aug 2026 at the Increment 1 gate. Scope is now cut, not deferred.**

The ritual's step 4 forces this: **8 of 13 days are gone (62%)** and Increments 0–2 were budgeted at
half the calendar. Engine work stops 03 Sep, which leaves **three engine days** for everything after
this gate. Cutting at the gate, on measured evidence, is the whole point of the ritual — cutting at
the end is panic.

| Rank | Item | Status | Note (31 Aug) |
|---|---|---|---|
| 1 | Forward cash forecast | **CUT** | Unchanged since 25 Aug |
| 2 | Second / third merchant scenario | **CUT — decided** | Was "Inc 1 decides". One merchant with a mixed instrument profile carries the difficulty; a second doubles generator surface for zero new break shapes (D-011) |
| 3 | FX / international settlement | **CUT — decided** | A second currency threaded through the money type buys one exception code (D-011) |
| 4 | Tier 2 subset-sum | **CUT 01 Sep** | Followed multi-gateway. With no manufactured ambiguity there is nothing for a search to search, and Inc 1 measured zero scatter (D-016) |
| 5 | Increment 4 and 5 as separate increments | **MERGED into Inc 2's tail** | Most of both already exists: statement foots, journal entries balance, exception queue is typed and prioritised, degraded mode runs on every run, audit log and determinism are in place. What remains is the verifier gate and `blocked_hallucination`, which belong with the LLM |
| 6 | Live Razorpay test-mode adapter | Interface only | `SettlementSource` exists; impl only if Inc 6 has slack |
| 7 | Streamlit UI beyond one screen | Deferred | The video needs one screen |
| 8 | Multi-gateway collision class | **CUT 01 Sep — decided, not deferred** | The lever is closed. Building difficulty in order to justify the LLM is the §9 anti-pattern; the honest line is that arithmetic closes this loop and the LLM earns its place only in narration parsing (D-016) |
| 9 | TDS 194-O | Out by persona | Defend the decision, not the mechanics |
| 10 | Third seed on a different rate card | **DECLINED 01 Sep** | Would upgrade D-019's claim from "across worlds" to "across contracts"; 1–2 h because the rate card would have to become injectable. Fixes nothing broken. Revisit only if Inc 6 finishes early (D-024) |
| — | **Never cut** | — | Held-out seed · false-clear metric · degraded mode · Increment 6 |

---

## Open uncertainties (Increment 0)

| # | Uncertainty | Why uncertain | How Inc 0 resolves it |
|---|---|---|---|
| 1 | Is the grain decomposition right? | `REFUND_TO_PAYMENT` is declared on hypothesis; cross-cycle refunds may not fit a binary-edge model | Run real records through and see what does not fit |
| 2 | Does the ground-truth schema support false-clear? | False-clear needs truth about *explanation*, not just linkage — deeper than §5's sketch | Compute the metric for real; the schema is whatever that requires |
| 3 | Does the footing identity hold on clean data? | Untested against an entity model that did not exist until now | Assert it; failure here is the most valuable finding available |
| 4 | Are the fee/tax identities as read? | §3.2's transfer example (fee 296, tax 46, debit 100296) implies tax is *inside* fee; must survive rounding at scale | Property tests over generated ranges |
| 5 | Clean-clone install + run under 5 min on Windows | No `uv`, no `make`, OneDrive I/O on the repo path | Time it on a fresh venv; record in `RUN_LOG.md` |

---

## Decisions Log

Append one entry per decision at each gate. **Never edit an existing entry** — supersede it with a new
one that references it. Fixed shape:

```
### D-NNN · <Gate> · <YYYY-MM-DD> · <one-line decision>
**Decision:**           what we are doing
**Why:**                the evidence or argument, not the preference
**What it rules out:**  the option now closed, and what would reopen it
**Supersedes:**         D-NNN, or "—"
```

<!-- Entries below. Newest last. -->

### D-001 · Increment 0 · 2026-08-25 · Reconciliation is a graph of typed edges, not a pipeline over rows
**Decision:** Model four grains as typed binary edges (`EDGE_SPECS`), with tier, confidence, evidence
and decomposition carried on the edge. The 1:N settlement→line grain is a *set* of binary edges; the
rollup identity is checked over the set, not stored on any edge.
**Why:** BRIEF §4 reads as stages over "records", but Tier 0 alone spans three different joins at three
different cardinalities. Blurring them makes the match-rate denominator indefensible, which §7 names as
the easiest way to lose a technical panel. Reviewed with the user before any dependent code existed.
**What it rules out:** A single edge holding a member list (rejected: forces every consumer to branch on
cardinality). Reopens only if Tier 2 becomes subset-sum, at the Inc 2 gate.
**Supersedes:** —

### D-002 · Increment 0 · 2026-08-25 · An exception's subject is a unit OR an edge
**Decision:** `ExceptionRecord.subject_kind` ∈ {`unit`, `edge`}.
**Why:** The edge model cannot express "this settlement has no bank credit at all" — an unmatched unit
is the *absence* of an edge, and absence carries no evidence. Discovered by building it, which is what
Increment 0 was for. Note this is the most common break shape in real reconciliation, so a pure edge
model would have been wrong in the field, not merely inconvenient here.
**What it rules out:** Fabricating dangling edges with an empty counterpart to keep the model uniform.
**Supersedes:** partially amends D-001

### D-003 · Increment 0 · 2026-08-25 · Every identity must have its two sides sourced independently
**Decision:** Emit the settlement entity as its own view (`settlements.jsonl`) carrying its own
`amount`, rather than summing the line items it is checked against.
**Why:** The rollup identity was tautological in the first cut — a green test over a circular
definition. Real deployments get the settlement entity from a different endpoint than the recon lines.
Generalised immediately to the reconciliation statement, whose terms are drawn from four sources.
**What it rules out:** Any future "identity" test whose two sides share a derivation. This now governs
Increment 1.
**Supersedes:** —

### D-004 · Increment 0 · 2026-08-25 · One canonical GST rounding rule; the brief's example is treated as a mismatch
**Decision:** `mdr_base = round_half_up(amount × 2%)`, `tax = round_half_up(mdr_base × 18%)`,
`fee = mdr_base + tax`. The brief's own transfer example (`fee=296, tax=46`) violates this by one paise
and is treated as `GST_ON_MDR_MISMATCH`.
**Why:** No base yields 46 at 18% while summing to 296, so the reference example is internally
inconsistent. Bending the rule to fit it would make our own generator violate the identity we test.
In production this mismatch is precisely what a controller wants flagged.
**What it rules out:** Deriving the rule from the documented example. Locked by
`test_brief_transfer_example_violates_its_own_gst_rule`. Reopens only against real merchant data.
**Supersedes:** —

### D-005 · Increment 0 · 2026-08-25 · The headline carries two denominators, permanently
**Decision:** Report explanation rate (bank credits) *and* settlement coverage side by side, always.
**Why:** Measured at this gate: explanation rate reads 100.00% (5/5) while settlement coverage reads
83.33% (5/6). The worst break in the dataset — a settlement that never reached the bank — is invisible
in the bank-credit denominator, because a settlement with no credit contributes nothing to it.
Publishing the first number alone would be technically true and materially dishonest.
**What it rules out:** A single-number headline, in the README or the video.
**Supersedes:** —

### D-006 · Increment 0 · 2026-08-25 · Float-free is enforced as a property, with a split rule
**Decision:** Float literals and references to `float` are banned in every module, no exceptions. The
true-division rule is skipped for four named path-joining modules, recorded as an exclusion list.
**Why:** `pathlib` overloads `/`, so the naive scan fired on correct code. A guard that fires on
correct code gets disabled, and a disabled guard is worse than none. An exclusion list keeps new
modules strict by default and makes each addition visible in review.
**What it rules out:** Heuristically sniffing whether a `/` operand "looks like a path" (brittle; would
fail silently on `DATA / seed`).
**Supersedes:** —

### D-007 · Increment 0 · 2026-08-25 · `eval` subcommand deferred to Increment 1
**Decision:** The CLI ships `generate`, `run`, `demo`. No `eval` subcommand yet, and nothing in the
repo claims one.
**Why:** `eval` only means something once a held-out seed exists, which is Increment 1's work. A stub
that runs the dev seed under an "eval" name would be worse than its absence.
**What it rules out:** Reporting any number as "held-out" before Increment 1. The `SettlementSource`
protocol *was* built (`ingest/source.py`) as promised, since that seam constrains later design.
**Supersedes:** —

### D-008 · Increment 0 (post-gate) · 2026-08-31 · The working copy lives at `C:\dev\ai-finance-controller`, off OneDrive
**Decision:** Move the repo out of the OneDrive-synced path to `C:\dev\ai-finance-controller`. Open
Uncertainty #5 above still names "OneDrive I/O on the repo path" as a risk to the clean-clone gate;
that line stands as written (this log is append-only) and is retired here.
**Why:** `out/<seed>/` and `data/generated/<seed>/` are rewritten on every run, so a synced path puts a
background uploader on exactly the files the determinism contract (invariant 2) covers, and adds
unmeasured I/O to the one gate condition that is a wall-clock number. Verified after the move: tree
byte-identical, `pytest` 91 green, and two `recon run --seed dev` invocations both produce
`metrics.json` sha256 `83f6c531…` — the same hash recorded at the Increment 0 gate *before* the move.
Determinism therefore holds across the move, not merely at the new path.
**What it rules out:** Attributing any later flaky write, timing outlier, or non-reproducible artifact
to OneDrive — that explanation is now closed and the cause would have to be found in our code. Also
removes sync latency from the clean-clone number, re-measured in `RUN_LOG.md` against a fresh venv.
Reopens only if the repo is moved back under a synced path, which nothing requires.
**Supersedes:** — (retires the OneDrive risk in Open Uncertainty #5; does not amend it)

### D-009 · Increment 1 · 2026-08-31 · False clear is split by the built tier's remit
**Decision:** `ExceptionType` gains `detectable_at` (lowest tier that can flag the class) and
`resolvable` (can any tier ever close it). `BUILT_TIER` is one declared constant. The metric splits
into `false_clear_in_remit` — which must be zero — and `false_clear_out_of_remit`.
**Why:** Measured at this gate: 83 of 192 dev breaks went unflagged, and every single one is
`MDR_SLAB_MISMATCH`, which needs the rate card and is therefore Tier 1 work. A single false-clear
number would have read 43.23% and forced one of two bad moves: build Tier 1 inside Increment 1, or
stop generating anomalies Tier 0 cannot see. Neither is acceptable, and quietly relaxing the gate
condition is worse than both. See F-005.
**What it rules out:** Reporting one undifferentiated false-clear number. Also rules out
`detectable_at` being an aspiration: `test_tier0_covers_its_declared_remit` fails if a class marked
tier 0 is never raised in `tier0.py`, so the split cannot become a way to relabel real misses.
**Supersedes:** — (amends Increment 1 gate condition 8, in place and dated)

### D-010 · Increment 1 · 2026-08-31 · Increment 1 completes Tier 0's remit; it does not add a tier
**Decision:** Increment 1 built no Tier 1, Tier 2 or LLM. It did extend `tier0.py` to cover the
classes that are definitionally Tier 0 on data that finally contains them — the `REFUND_TO_PAYMENT`
exact-key join, duplicate detection on a 1:1 grain, flag and date reads, and the per-line GST
identity.
**Why:** "No new resolver capability" means no new tier, not a frozen Tier 0. Increment 0 raised one
exception class because the generator produced one shape. Leaving an exact-key join unimplemented
would have made the gate numbers measure absent plumbing rather than the Tier 0/Tier 1 boundary, and
uncertainty #1 — does `REFUND_TO_PAYMENT` survive cross-cycle refunds? — cannot be answered without
running the join.
**What it rules out:** Reading "no new capability" as licence to leave Tier 0 half-built and then
attribute the resulting misses to a missing Tier 1.
**Supersedes:** —

### D-011 · Increment 1 · 2026-08-31 · One merchant, one currency. Second scenario and FX are CUT
**Decision:** A single merchant with a mixed instrument profile (46% UPI, ~40% card across five
network/type slabs, netbanking, wallet). Cut-list rank 7, "second/third merchant scenario — Inc 1
decides", is resolved as **cut**. FX is cut with it.
**Why:** A second merchant doubles the generator surface and produces no new *break shape* — the
card-heavy difficulty the brief wants (disputes, reserve) fits inside one merchant's method mix, and
it does. FX needs a second currency threaded through `Paise` and every identity, to buy one
exception code. With 62% of the calendar gone, neither earns its place.
**What it rules out:** `FX_VARIANCE` and `MULTI_GATEWAY_COLLISION` as *generated* classes, and
therefore as declared members of the taxonomy. Multi-gateway is explicitly retained as the Inc 2
ambiguity lever (D-015), which is the one thing that would reopen this.
**Supersedes:** —

### D-012 · Increment 1 · 2026-08-31 · The rolling reserve is held 45 days, not the documented 90–180
**Decision:** `RESERVE_HOLD_DAYS = 45` against a 90-day extract, stated in `domain/rates.py`.
**Why:** With a 90-day window and a 90-day hold, not one release originating inside the window ever
lands inside it. The only interesting property of a reserve — that a release must be matched back to
the cycle it came from — would go completely unexercised, and `RESERVE_RELEASE_UNMATCHED` would be
untestable. 45 days puts both legs of the identity inside one extract. The mechanism is what is
being modelled; the calendar constant is not what makes it credible.
**What it rules out:** Presenting the hold period as realistic. It is documented as a deliberate
deviation at the constant itself, so nobody reads it as a research result.
**Supersedes:** —

### D-013 · Increment 1 · 2026-08-31 · Two Sec 6 codes stay undeclared because the data cannot produce them
**Decision:** `CHARGEBACK_FEE_UNBOOKED` and `PARTIAL_SETTLEMENT` are removed from `ExceptionType`
with the reason recorded inline, joining `TDS_194O_VARIANCE`, `FX_VARIANCE` and
`MULTI_GATEWAY_COLLISION` as declared-absent.
**Why:** Our ERP view is sales-grain — it books invoices, not gateway expenses — so an unbooked fee
has nowhere to be missing *from*. A batch split across cycles is a subset-sum target and belongs
with Tier 2 rather than ahead of it. A taxonomy entry with no data behind it is a claim we cannot
back, and §6 says to refine the list rather than adopt it.
**What it rules out:** Quoting "17 of the brief's 20 exception types" as coverage. The honest number
is the ones that fire, and the reasons the others do not are in the enum.
**Supersedes:** —

### D-014 · Increment 1 · 2026-08-31 · On an ambiguous UTR, Tier 0 links nothing
**Decision:** When one UTR appears on two bank credits, Tier 0 raises `DUPLICATE_UTR` on both and
creates **no** `BANK_TO_SETTLEMENT` edge for either. The settlement still counts as reached, so it
does not also surface as a missing bank credit.
**Why:** Linking one of two identical candidates is a coin flip presented as a fact. The cost is one
recall point (measured: linkage recall 99.97% on dev, and the single miss is exactly this); the
alternative cost is a precision error, and in reconciliation a confident wrong link is far more
expensive than a gap — an analyst who trusts a link stops looking.
**What it rules out:** Tie-breaking by value date, amount or row order. Any of those would produce a
100% recall number that means less than the 99.97% one.
**Supersedes:** —
**Reaffirmed 01 Sep 2026** when D-023 extended the same refusal to Tier 3. The two must move
together: if tie-breaking is ever allowed here, Tier 3 has to tie-break identically or the tiers
disagree about the same data.

### D-015 · Increment 1 · 2026-08-31 · The residual is 100% mechanical BY CONSTRUCTION, and Inc 2 must decide what that means
**Decision:** Record the measured residual distribution — every paise of Tier 0's Rs 3,96,133.81
residual falls into a typed component (reserve 32%, refund offset 25%, transfers 20%, reserve
release −13%, chargebacks 9%, fees 3%) with **zero** scatter — and record explicitly that this is a
property of how the generator was built, not a discovery about reconciliation.
**Why:** §13.1 makes the Inc 2 pivot depend on whether residuals are mechanical or scatter into
ambiguity. Increment 1 answers "mechanical", but it answers it tautologically: the world was
simulated from typed components, so of course they type. Presenting that as an empirical finding
would be the circularity the brief warns about in a different costume. The honest statement is that
**Increment 1 produced no genuine Tier-2 ambiguity**, and that this was not an accident of tuning.
**What it rules out:** Concluding at this gate that Tier 2 is unnecessary. That conclusion needs
either a deliberate decision to accept a Tier-1-closes-it submission (in which case the LLM's only
defensible place is narration extraction, and the measured 100% → 0-of-22 parse gap is the argument
for it), or the multi-gateway lever pulled to manufacture real ambiguity. Decide at the Inc 2 gate,
on the post-Tier-1 residual.
**Supersedes:** —

### D-016 · Increment 2 · 2026-09-01 · The pivot is ACCEPT. Multi-gateway is fully CUT, not deferred
**Decision:** Tier 1 arithmetic closes the residual and the submission says so. The LLM is confined
to narration parsing. `MULTI_GATEWAY_COLLISION` is **cut outright** — removed from the lever
position it held on the cut list since 25 Aug, not deferred to a later gate.
**Why:** Two reasons, and the second is the stronger. Scheduling: three engine days remain (01-03 Sep), and a
second gateway means generator work, Tier 0 and Tier 1 extension, *and* Tier 2 subset-sum on top --
it does not fit. Substance: the only purpose of building it would be to manufacture ambiguity so the
LLM has something to adjudicate, and §9 names "agent as marketing" an anti-pattern explicitly. An
ablation over difficulty we invented to justify a component is staged, and a panel reads it that way.
The honest submission is that deterministic arithmetic closes this loop, and the LLM earns its place
exactly where deterministic parsing does not generalise — a claim we already have a measured number
for (100.00% dev vs 0 of 22 held-out settlement narrations).
**What it rules out:** `MULTI_GATEWAY_COLLISION` as a declared exception type, Tier 2 subset-sum, and
any "the LLM resolves ambiguous matches" claim. The ablation table will show the LLM adding nothing
to the arithmetic and everything to extraction. That is the result, not a disappointment, and it is
reported as such.
**Supersedes:** amends the cut list's rank-8 "held as the lever" entry, which is now closed.

### D-017 · Increment 2 · 2026-09-01 · The resolver may not read `description` or `notes`
**Decision:** Tier 1 types adjustments from documented §3.1 fields (`type`, `dispute_id`) and from
contracted rate-card constants, never from the free-text `description` or `notes`. Enforced by test.
**Why:** Those strings are ours. "Rolling reserve withheld" types an adjustment perfectly and proves
nothing except that we can read our own generator, which is D-015's circularity in its purest form.
It is also the fuzzy string matching §9 names as the single thing most likely to sink the
submission. Banning it forces reserve to be identified arithmetically, which is a real derivation a
controller could run against a real report.
**What it rules out:** Any keyword or regex classification of adjustment lines. `notes` may appear in
an exception's *evidence* for a human to read; it may never enter a resolver's decision.
**Supersedes:** —

### D-018 · Increment 2 · 2026-09-01 · Tier 1 is measured by decomposition closure, not explanation rate
**Decision:** Add `closure_report`, which asks whether the gross-to-net gap can be typed using the
settlement report alone — no bank statement, no narration, no ground truth — and publish it per seed
alongside the headline.
**Why:** Explanation rate on the held-out seed is 0%, and not for any arithmetic reason: the parser
finds no UTR, no bank edge is created, and Tier 1 never runs. A metric that linkage can mask cannot
answer whether the decomposition generalises, which was this gate's whole question. Closure compares
two independently derived views (line items vs the settlement entity's own `amount`, D-003), so it is
a real cross-check rather than a restatement. Measured: **100% on both seeds.**
**What it rules out:** Reporting the eval explanation rate of 0% as evidence about Tier 1. It is
evidence about narration parsing, and the two must not be conflated in the README or the video.
**Supersedes:** —
**Made autonomously overnight; open for review.**
**Reviewed and APPROVED by the user, 01 Sep 2026.**

### D-019 · Increment 2 · 2026-09-01 · "Generalises across worlds, not across contracts"
**Decision:** The claim we will defend about Tier 1 is exactly that sentence, backed by the published
schema/contract split: ~49% of explained money is typed from documented Sec 3.1 fields the gateway
asserts (`type`, `dispute_id`) and is not circular; ~51% is derived from rate-card constants we also
generated with and is circular in D-015's sense.
**Why:** The eval seed is a different world drawn from the *same* rate card, so 100% closure there
demonstrates the rules apply to unseen instances — not that they would hold for a merchant on a
different contract. Stating the stronger claim would be overclaiming, and a panel checking the
generator would find it in minutes.
**What it rules out:** Any "validated on held-out data" phrasing that does not carry the split. The
remaining circularity would be genuinely broken by a third seed generated with a DIFFERENT rate card,
where Tier 1 should report mismatches rather than closures — logged as the top candidate on the cut
list rather than built tonight, because it is new scope at 69% of the calendar.
**Supersedes:** —
**Made autonomously overnight; open for review.**
**Reviewed and APPROVED by the user, 01 Sep 2026.** Wording kept; the third seed is declined — see D-024.

### D-020 · Increment 2 · 2026-09-01 · An exception describes the final state of the graph
**Decision:** The pipeline drops exceptions whose subject edge ended `EXPLAINED`, recording each
supersession in the audit log.
**Why:** Tier 0 raises `AMOUNT_VARIANCE_UNEXPLAINED` on every edge it cannot close, and Tier 1 then
closed 20 of them on dev. Without this the queue showed an analyst 20 phantom breaks the system had
already explained — inflating the exception count, which Sec 6 names as the thing that understates
the agent. The audit log keeps the intermediate view reconstructible.
**What it rules out:** Tiers appending to a shared queue as if it were a log. The queue is a
statement about now; the audit log is the history.
**Supersedes:** —
**Made autonomously overnight; open for review.**
**Reviewed and APPROVED by the user, 01 Sep 2026.**

### D-021 · Increment 3 · 2026-09-01 · Tier 3 supplies linkage only, and runs before Tier 1
**Decision:** The adjudicator creates `MATCHED` edges tagged `linked_by=T3_LLM`, and Tier 1 then
explains the money. Edges carry `linked_by` separately from `tier`; an edge counts at tier N in the
ablation only if both its linkage and its explanation are within N.
**Why:** Invariant 8 — the LLM never computes money. Running Tier 3 after Tier 1 would leave
LLM-linked credits permanently unexplained; letting it set `EXPLAINED` would violate the invariant
outright. And with only one tier per edge, Tier 1's upgrade erased the adjudicator's contribution
from both the graph and the ablation, making the LLM look useless by construction.
**What it rules out:** Reading `tier` alone as "which tier made this possible". Also rules out any
future tier setting `EXPLAINED` without the arithmetic engine agreeing.
**Supersedes:** —
**Made autonomously overnight; open for review.**
**Reviewed and APPROVED by the user, 01 Sep 2026.**

### D-022 · Increment 3 · 2026-09-01 · With no API key, the fence is measured and accuracy is not claimed
**Decision:** Build and test the adjudicator, cache, verifier gate, `blocked_hallucination`, degraded
mode and the ablation harness. Claim **no** figure for the model's real extraction accuracy anywhere
in the repo. The `anthropic` SDK is an optional `[llm]` extra, lazily imported.
**Why:** There is no key in this environment. The architectural claim — a hallucination cannot become
a match — is provable without one, by attacking the fence and counting what gets through. An accuracy
number is not, and estimating it would be exactly the kind of unearned figure this project's logs
exist to prevent. The oracle result is published as an explicit **upper bound**, labelled in the test
docstring, the RUN_LOG table and here, because it is the number most likely to become a false claim
once it travels.
**What it rules out:** Any "the LLM recovers N% of held-out narrations" statement in the README or
video until a key produces one. Also rules out making the SDK a hard dependency, which would break
the clean-clone gate CLAUDE.md protects.
**Supersedes:** —
**Made autonomously overnight; open for review.**
**Reviewed and APPROVED by the user, 01 Sep 2026.** The no-number clause is expected to be superseded by a
new entry once an API key produces a measured figure — superseded, never edited.
The optional-extra decision stands permanently regardless.

### D-023 · Increment 3 · 2026-09-01 · Tier 3 inherits Tier 0's refusal to link an ambiguous UTR
**Decision:** Tier 3 skips credits already flagged `DUPLICATE_UTR`, and rejects any proposal
resolving to a settlement that already has a bank credit. Logged as a rejection, not a hallucination.
**Why:** The verifier gate blocks *wrong* answers. It does not block a *correct* answer to an
ambiguous question: an adjudicator reading a duplicated UTR is right, the lookup succeeds, and Tier 3
would make precisely the link Tier 0 declines to make on a coin flip (D-014). Measured cost of not
having this: linkage precision 99.97% and a statement that no longer foots.
**What it rules out:** Treating "the verifier passed it" as sufficient. Counted separately from
`blocked_hallucination` because conflating them would overstate the hallucination rate and hide a
distinct failure mode — the model was correct and the DATA was ambiguous.
**Supersedes:** —
**Made autonomously overnight; open for review.**
**Reviewed and APPROVED by the user, 01 Sep 2026.**

### D-024 · Increment 3 (post-gate) · 2026-09-01 · The different-rate-card seed is declined, not deferred
**Decision:** Do **not** build a third seed generated with a different rate card. D-019's claim —
"Tier 1 generalises across worlds, not across contracts" — stands as the claim we defend, with the
~49/51 schema/contract split published beside it.
**Why:** The user's call, and the reasoning is worth recording verbatim because this is exactly the
kind of thing that gets re-litigated at 2am on the last day: *two engine days is too tight to spend
on strengthening a claim that is already honest and defensible as written — the weaker claim is a
good result, not a compromise.* The estimated cost was 1–2 hours, because the rate card is
module-level constants and would have to become injectable; the benefit was upgrading a defensible
claim to a slightly stronger one, not fixing anything wrong.
**What it rules out:** Any "validated across contracts" phrasing, permanently, unless the seed is
actually built. Reopens only if Increment 6 finishes with real time to spare, and the default is no.
**Supersedes:** — (closes the open option flagged in D-019)

### D-025 · Increment 3 · 2026-09-01 · Two rejection counters, because they are two events
**Decision:** `blocked_hallucination` (the model produced characters not faithfully read from the
narration — invented, or under-read when more were available) and `blocked_unverifiable` (it read the
document correctly and the document contains no usable reference). Both are still rejected; only the
accounting differs. Discriminated by `_is_faithful_reading`, from the narration alone.
**Why:** The first live run reported 17 hallucinations. Fourteen of them were the model returning
exactly the text that was present — the `neft_truncated` family cuts the narration at 40 characters
and only 10 of the 16 UTR characters survive. That is `REFUND_ORPHANED`'s shape, evidence outside the
extract, and calling it a hallucination overstated model error roughly fivefold. The same distinction
Tier 0 already draws for a duplicated UTR (D-014, D-023), one level along.
**What it rules out:** Publishing a single rejection count. Also rules out the naive discriminator
"did the proposal appear in the narration" — a prefix of a present token is trivially present, so
that version scored a genuine under-read as unverifiable, which flatters us. The heuristic is
deliberately biased toward blaming the model instead.
**Supersedes:** — **Approved by the user, 01 Sep 2026.**

### D-026 · Increment 3 · 2026-09-01 · Determinism holds for the deterministic core, not the LLM layer
**Decision:** State invariant 2's boundary explicitly: same seed ⇒ byte-identical `metrics.json` for
the shipped rules-only path and for any deterministic adjudicator, both covered by tests. With a live
LLM it does not hold, because the response cache is per-run. Do **not** build cross-run cache
persistence now. Report the LLM figure as a **range over runs**, never a single number.
**Why:** Measured, not predicted: two identical live runs returned 5/22 and 3/22. The stable part is
the 14 structurally-unrecoverable narrations; all variance sits in the 8 where the UTR is present.
Persisting the cache would restore reproducibility and costs perhaps 30–45 minutes, but the demo and
every gate run the deterministic core, Increment 6 is protected, and two engine days remain. A stated
boundary is worth more than a hidden one.
**What it rules out:** Quoting 62% (or any single figure) for LLM accuracy — the range is 38–62% over
two runs. Also rules out claiming byte-identical runs with `--llm` enabled.
**Supersedes:** the no-number clause of **D-022**, which required an API key to resolve and now has
measured figures. D-022's other half — that the SDK stays an optional extra — stands unchanged.
**Approved in principle by the user (split + supersession); the range framing is new and open for
review.**
