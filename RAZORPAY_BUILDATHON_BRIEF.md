# AI Finance Controller — Planning Brief for Claude Code

**Purpose of this document:** standing context for the whole project. Read fully before producing any plan.
Do not start writing code from this document. Produce a plan first.

**Planning mode: incremental.** Do not produce a full 13-day plan. Plan one increment at a time, to the exit gate, then stop and re-plan against measured results. See §13 for the protocol — it overrides any instinct to plan the whole build up front.

**Date compiled:** 23 August 2026
**Submission deadline:** 05 September 2026 (verify on the official application form — aggregator-sourced)
**Track:** 04 — AI Finance Controller
**Official page:** https://razorpay.com/buildathon/

---

## 1. What Razorpay actually asked for

Verbatim from the track:

> **Run the books and the cash position.**
> Build an agent that closes one finance-ops loop across a 50+ record batch of synthetic data, reporting its match rate and the exceptions it could not resolve.
>
> **Why now:** The 2026 builder consensus: verification capacity, not generation speed, is the bottleneck. Reconciliation, settlement and forecasting are still done by hand.
>
> **Example directions:** Multi-source reconciliation · Settlement Q&A agent · Forward cash forecaster · Tax-line matcher
>
> **The bar:** Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing.

Program framing from the same page:

> No resume screening. No long application. Four steps: pick a track, build something real, show your work (a public repo, a 5 minute pitch video, the architecture), and if it has signal we call you in.

### 1.1 Judging rubric

Four parameters (reported by hiring-aggregator coverage of the program, not printed on the track page — treat as strong signal, not gospel):

| Axis | What it means | What it demands of us |
|---|---|---|
| **Problem taste** | Did you pick a real-world problem with financial/operational significance? | Solve the loop finance teams actually do by hand, not a toy join |
| **Build quality** | Code structure, repo organisation, execution stability, architectural robustness | Clean modules, typed schemas, tests, one-command repro |
| **AI judgment** | Was AI applied appropriately, vs forcing unnecessary tech stacks? | LLM confined to where it beats rules; prove it with an ablation |
| **Failure recovery** | How did you identify runtime failures and engineer graceful fallbacks? | Instrumented degradation, verifier that blocks bad LLM output, real incident log |

### 1.2 Deliverables

1. Public GitHub repo
2. 5-minute pitch video
3. Architecture (diagram + written)
4. A statement of what broke during development and how you recovered

### 1.3 Reading between the lines

| Their phrase | Hard requirement it implies |
|---|---|
| "closes one finance-ops **loop**" | Must end in an action/artifact — journal entries, an exception queue with owners, a posted reconciliation statement. Not a report that a human then re-does. |
| "**one** loop" | Depth over breadth. Do NOT build recon + forecast + Q&A + tax as four shallow features. |
| "50+ record batch" | 50 is the floor, not the target. Ship 1,000–2,000 to make throughput a real claim. |
| "reporting its **match rate**" | Requires a precise, published definition of numerator and denominator. |
| "the exceptions **it could not resolve**" | Requires a typed exception taxonomy, not a dump of unmatched rows. |
| "**measured** accuracy" | Requires ground-truth labels and a held-out set. |
| "**honest** exception list" | Report precision, not just recall. Show what you got wrong. Show the failure modes. |
| "One cherry-picked match proves nothing" | An eval harness is the deliverable, as much as the agent is. |
| "verification capacity is the bottleneck" | The product thesis is: the agent's job is to *verify*, and to be verifiable itself. Confidence, evidence and audit trail on every decision. |

---

## 2. Recommended scope

**Build: three-way settlement reconciliation with typed variance decomposition and an auto-posting ledger.**

Reconcile three sources that never agree by construction:

- **Source A — Books/ERP:** orders and invoices. Gross amounts, GST, customer, `order_id`, `receipt`.
- **Source B — Razorpay settlement recon report:** transaction-level line items (payments, refunds, transfers, adjustments) grouped under `settlement_id` / `settlement_utr`.
- **Source C — Bank statement:** one lump credit per settlement, free-text narration, value date.

**Why this scope wins:**
- It is the loop that is genuinely still manual.
- The N-to-1 structure (many settlement line items → one bank credit) makes naive row-to-row matching impossible, which separates this from every other submission.
- Every deduction is arithmetically checkable, so ground truth is objective and accuracy is *measurable* rather than vibes.
- It naturally produces both halves of "run the books **and the cash position**": journal entries (books) + settled/unsettled/reserve-held position (cash).

**Stretch, only if core is airtight:** a forward cash view derived from the same ledger (expected settlement dates for captured-but-unsettled payments, reserve release schedule). This gestures at "Forward cash forecaster" without splitting focus. Cut it without hesitation if time is short.

---

## 3. Domain model — get this right, it is the credibility layer

### 3.1 Razorpay settlement recon line item (real schema)

From `razorpay/razorpay-node` `documents/settlement.md`, the settlement recon response items carry:

```
entity_id, type, debit, credit, amount, currency, fee, tax,
on_hold, settled, created_at, settled_at, settlement_id, posted_at,
credit_type, description, notes, payment_id, settlement_utr,
order_id, order_receipt, method, card_network, card_issuer,
card_type, dispute_id
```

`type` ∈ `payment` | `refund` | `transfer` | `adjustment`. The settlement entity itself is:

```
id (setl_*), entity, amount, status, fees, tax, utr, created_at
```

ID prefixes to mirror exactly: `pay_`, `rfnd_`, `trf_`, `adj_`, `order_`, `setl_`, `setlod_`, `setlodp_`.

### 3.2 Arithmetic identities the engine must enforce

Derived from the documented examples — encode these as invariants and as tests:

```
# Payment line (credit to merchant)
credit = amount - fee                  # 100000 - 2900 = 97100  ✓
debit  = 0

# Refund line (debit from merchant)
debit  = amount
credit = 0

# Transfer line
debit  = amount + fee                  # 100000 + 296 = 100296  ✓

# CRITICAL: fee is INCLUSIVE of tax.
# In the transfer example fee=296, tax=46, debit=100296 (not 100342).
# `tax` is a memo breakout of the GST component of MDR, needed for ITC.
# MDR base = fee - tax ; tax should equal round(MDR_base * 0.18)

# Settlement rollup
settlement.amount = Σ(credit) - Σ(debit)  over all line items of that settlement_id

# Bank tie-out
bank_credit(where narration contains settlement_utr).amount == settlement.amount
```

**All money is integer paise. Never use floats anywhere in the pipeline.** Use `int` or `Decimal`; a float somewhere in a recon engine is an instant build-quality tell.

### 3.3 The Indian deduction stack

Every rupee of gap between gross sales and bank credit must land in a typed bucket:

| Component | Mechanics |
|---|---|
| **MDR** | Method/network-dependent slab (UPI, netbanking, debit, credit, Amex, international). Varies by `method` + `card_network` + `card_type`. |
| **GST on MDR** | 18% on the MDR base. Merchant claims Input Tax Credit only if it is a separate line item — hence `tax` exists in the schema. |
| **TDS 194-O** | E-commerce operator TDS on gross sales. 0.1% from 1 Oct 2024 (was 1%). Reconciled against Form 26AS / TRACES. Only applies in marketplace/aggregator models — decide whether your merchant persona is in scope and document the decision. |
| **Rolling reserve** | Typically 5–10% of daily settlements withheld 90–180 days as a chargeback buffer. **It is a receivable from the gateway, not settled cash** — must be reconciled on its own ledger, and released reserves must be matched back to the cycle they came from. |
| **Chargeback debit** | Reversal of the disputed amount. |
| **Chargeback fee** | A *separate* line item from the reversal, typically ₹500–₹2,000 per dispute. |
| **Refund offset** | Reduces the settlement total with no separate bank debit — a classic source of "the bank credit is short and nobody knows why". |

**Net vs gross settlement:** Indian gateways default to *net* settlement — fees, TDS and adjustments are deducted before the credit lands. Model net. If you also model a gross-settlement merchant, that is a second scenario, not the default.

### 3.4 Timing — the second structural difficulty

- T+2 (or T+1/T+3 by merchant) settlement cycle: `created_at` ≠ `settled_at` ≠ bank value date.
- Month-end cutoff: a payment captured 31 Mar settles 2 Apr. Books and bank disagree at period close *correctly*. The agent must recognise in-transit rather than flag it as a break.
- Refunds and chargebacks cross cycles: a refund for a payment settled in cycle N appears as a debit in cycle N+3.
- Instant/on-demand settlements (`setlod_*`) interleave with the scheduled cycle and carry their own fee.

### 3.5 Bank narration — the one genuinely fuzzy surface

Narrations are unstructured, bank-specific, truncated, and inconsistently delimited. Examples of the shape to generate:

```
NEFT CR-RAZORPAY SOFTWARE PVT LTD-1568176960vxp0rj-RZPXFER
IMPS/P2A/512841003847/RAZORPAYSOF/SETTLEMENT
UPI-RAZORPAY-SETL-1568176960VXP0RJ-PAYMENT FROM PHONE
NEFT-RAZORPAYSOFTWAREPVTLT-UTR1568176960VX (truncated at 40 chars)
```

**This — not the arithmetic — is the legitimate place for an LLM.** Extraction of `{utr, counterparty, reference, type}` from noisy free text is exactly what LLMs beat regex at, and the extracted UTR is then verified by an exact lookup, so a hallucination cannot survive.

---

## 4. Architecture — tiered resolution

Design the resolver as explicit tiers. Every record carries the tier that resolved it, so you can produce the ablation table.

```
Tier 0  DETERMINISTIC JOIN
        Exact keys: settlement_utr ↔ bank narration UTR,
        settlement_id ↔ line items, order_id ↔ book invoice,
        payment_id ↔ refund parent.
        Expect this to clear the large majority. If it doesn't,
        your synthetic data is unrealistically messy.

Tier 1  ARITHMETIC VARIANCE DECOMPOSITION            (rules, no LLM)
        gap = expected_gross - actual_bank_credit
        Subtract, in order: MDR (from contracted slab table),
        GST on MDR, TDS, reserve withheld, refund offsets,
        chargeback reversals + fees.
        Residual == 0  → RESOLVED, fully explained
        Residual != 0  → carry to Tier 2 with the residual as evidence

Tier 2  CANDIDATE GENERATION + SCORING               (deterministic/statistical)
        Blocking on amount ± tolerance and date window to keep the
        candidate set small. Score on amount proximity, date proximity,
        counterparty similarity, reference-token overlap.
        Single high-confidence candidate → provisional match.
        Ambiguous or empty → Tier 3.

Tier 3  LLM ADJUDICATION                             (structured output only)
        Four jobs, and only these four:
          a) Parse messy bank narration → structured fields
          b) Rank an ambiguous candidate set and give a written rationale
          c) Classify an unexplained residual into an exception type
          d) Draft the analyst-facing note for the exception queue
        Constraints:
          - Tool-use / JSON-schema constrained output. No free text parsing.
          - temperature 0, response cached by input hash → reproducible runs
          - The LLM never computes money. It selects and explains.
          - EVERY LLM-proposed match is re-verified by the Tier 1 arithmetic
            engine before acceptance. Rejections increment a
            `blocked_hallucination` counter — surface this metric, it is
            one of the strongest things you can show a panel.

Tier 4  HUMAN QUEUE
        Emits: exception type, confidence, the evidence chain,
        the agent's best hypothesis, suggested action, owner.
        This is the "honest exception list".
```

### 4.1 Closing the loop — the output artifacts

The run must end in artifacts a controller would actually use:

1. **Proposed journal entries**, double-entry and balanced:
   `Dr Bank · Dr MDR Expense · Dr GST Input Credit · Dr TDS Receivable · Dr Rolling Reserve (asset) · Cr Trade Receivable`
2. **Reconciliation statement** that ties:
   `opening receivable + gross sales − settlements received − explained variance − exceptions = closing receivable`
   If this doesn't foot to zero, the run failed. Assert it.
3. **Exception queue** — typed, prioritised by ₹ value at risk, with evidence.
4. **Cash position** — settled / in-transit / reserve-held, with expected release dates.
5. **Audit trail** — append-only decision log: every match, the tier, the inputs, the rule or prompt version, timestamp. Reproducible from the log alone.

---

## 5. Synthetic data — generate from truth, then corrupt

**Architecture:** simulate the ground-truth world first, then *derive* the three source views from it, injecting realistic corruption at controlled rates. Never generate three files and try to label them afterwards.

```
world_generator.py
  → truth.jsonl          # every order, payment, refund, dispute, settlement
                          # with the true linkage graph
  → derive_books()       # ERP view (may lag, may have manual entry errors)
  → derive_settlement()  # Razorpay recon report view
  → derive_bank()        # bank statement view (lump credits, messy narration)
  → inject_anomalies()   # controlled rates, each tagged in ground_truth
  → ground_truth.json    # linkage + injected anomaly type per record
```

**Scale:** 1,000–2,000 line items across ~60–90 days and 15–25 settlement cycles. 50 is their floor; clearing it by 20–40× is a throughput claim.

**Two seeds minimum.** A `dev` seed you tune on and a **held-out `eval` seed the system never saw**. Report headline numbers on the held-out set. Say so explicitly in the README — this alone answers "one cherry-picked match proves nothing".

**Realism requirements:**
- Anomaly rates should mirror reality: ~85–92% should be cleanly resolvable. If your data is 50% broken it isn't a recon dataset, it's a puzzle.
- Include at least one anomaly class the agent is *expected to fail on*, and say so. Honesty about a known blind spot reads as senior. Pretending 100% reads as fake.
- Vary merchant scenarios: one clean high-volume UPI merchant, one card-heavy merchant with disputes and a rolling reserve, one with international/FX if you want the difficulty.

---

## 6. Exception taxonomy

Every unresolved record gets exactly one type. Draft list — refine, don't just adopt:

| Code | Description |
|---|---|
| `MISSING_BANK_CREDIT` | Settlement processed, no matching bank credit (in-transit vs genuinely missing — distinguish) |
| `UNMATCHED_BANK_CREDIT` | Credit in bank with no corresponding settlement |
| `AMOUNT_VARIANCE_UNEXPLAINED` | Residual survives full deduction decomposition |
| `MDR_SLAB_MISMATCH` | Actual fee ≠ contracted rate for that method/network/card type |
| `GST_ON_MDR_MISMATCH` | `tax` ≠ 18% of MDR base |
| `TDS_194O_VARIANCE` | Deducted TDS ≠ expected on gross |
| `RESERVE_WITHHELD` | Explained by rolling reserve — informational, not a break |
| `RESERVE_RELEASE_UNMATCHED` | Release cannot be tied to the originating cycle |
| `REFUND_ORPHANED` | Refund with no locatable original payment |
| `REFUND_CROSS_CYCLE` | Refund debits a later cycle than its payment — timing, not a break |
| `CHARGEBACK_UNLINKED` | `dispute_id` present, no corresponding book entry |
| `CHARGEBACK_FEE_UNBOOKED` | Per-dispute fee not recognised in books |
| `DUPLICATE_UTR` | Same UTR on two credits |
| `DUPLICATE_PAYMENT` | Same order paid twice |
| `PARTIAL_SETTLEMENT` | Batch split across cycles |
| `ON_HOLD_NOT_SETTLED` | `on_hold=true`, captured but never settled |
| `PERIOD_CUTOFF_TIMING` | Correct, but straddles the close — must not be counted as a break |
| `NARRATION_UNPARSEABLE` | Extraction failed even at Tier 3 |
| `FX_VARIANCE` | International settlement rate difference |
| `MULTI_GATEWAY_COLLISION` | Two aggregators credit the same day, similar amounts |

Note which of these are **breaks** vs **explained-but-notable**. Conflating them inflates your exception count and understates the agent.

---

## 7. Metrics — define these precisely in the README

Ambiguous metrics are the single easiest way to lose a technical panel. Publish the formulas.

**Match rate — state numerator and denominator, at two granularities:**
- Line-item level: auto-resolved line items ÷ total line items
- Bank-credit level: bank credits fully explained ÷ total bank credits

**Accuracy (the honest half):**
- **Precision:** of auto-matched records, % correct against ground truth. *Lead with this.*
- **Recall:** of true matches, % found
- **Exception detection recall:** of injected anomalies, % caught
- **Exception typing accuracy:** confusion matrix over exception types — a mistyped exception sends the analyst down the wrong path, so this matters more than it sounds
- **False-clear rate:** anomalies wrongly marked resolved. The most dangerous error class in recon. Track it separately and prominently.

**Money-weighted, not just count-weighted:**
- ₹ auto-reconciled ÷ ₹ total. Finance cares about value coverage. 95% of records but 60% of value is a bad result and count-only metrics hide it.

**Throughput & cost:**
- Records/second, wall-clock for the full batch
- LLM calls per 1,000 records, tokens, ₹ cost per 1,000 records
- % of records that ever touched an LLM (should be small — that's the point)

**The ablation table — build the plan around producing this:**

| Configuration | Match rate | Precision | False-clear | ₹/1k records |
|---|---|---|---|---|
| Tier 0 only (exact join) | | | | |
| Tier 0+1 (+ arithmetic) | | | | |
| Tier 0+1+2 (+ scoring) | | | | |
| Full (+ LLM adjudication) | | | | |

This is the artifact that proves AI judgment. If the LLM row doesn't improve on the row above it, **cut the LLM from that path and say so in the video.** That is a stronger result than a marginal gain, and panels reward it.

---

## 8. Failure recovery — instrument it, log it as you go

Keep `FAILURE_LOG.md` in the repo and write to it *during* development, with real timestamps. Reconstructing it the night before is obvious.

**Failure modes to engineer against explicitly:**

| Failure | Fallback |
|---|---|
| LLM returns malformed / schema-invalid JSON | Validate → one repair retry → fall back to Tier 2 result → route to exception. Never crash the batch. |
| LLM proposes an arithmetically impossible match | Verifier rejects, increments `blocked_hallucination`, record goes to queue |
| LLM output non-deterministic across runs | temperature 0 + response cache keyed by input hash; assert run-to-run identity in a test |
| API timeout / 429 / outage | Exponential backoff with jitter, circuit breaker, then **degraded mode: complete the entire batch rules-only** and report the degradation in the run summary |
| Source file malformed / encoding broken / column renamed | Schema validation at ingest with a clear typed error; quarantine bad rows rather than aborting |
| Duplicate ingestion of the same file | Idempotency key on the run; re-running must not double-post journal entries |
| Cost blowout | Hard token budget per run; on breach, degrade to rules and flag |

**Degraded mode is the headline.** "The batch completes with zero LLM availability, at reduced match rate, and tells you it degraded" is exactly the answer the Failure Recovery axis is looking for.

---

## 9. Anti-patterns — these will sink the submission

- ❌ **Fuzzy string matching as the centrepiece.** It is what everyone else will build.
- ❌ **Floats for money.** Integer paise only.
- ❌ **LLM performing arithmetic or computing totals.** Instant AI-judgment failure.
- ❌ **Exactly 50 records.** Their floor, not a target.
- ❌ **Synthetic data that's too clean**, producing a 99% match rate. Nobody believes it and it means the exception path is untested.
- ❌ **A chatbot wrapper over a CSV.** "Settlement Q&A agent" is listed as a direction, but a bare RAG-over-spreadsheet is the weakest reading of it. Q&A should sit *on top of* a reconciled ledger, not replace one.
- ❌ **Metrics without a held-out set.** Directly violates the stated bar.
- ❌ **A demo that only walks the happy path.** Show a failure being caught, typed and queued.
- ❌ **Four shallow features.** They said *one* loop.
- ❌ **"Agent" as marketing.** If it's a pipeline, call it a pipeline and be proud of it. If it genuinely plans, calls tools and reacts to results, show the trace. Don't dress up a for-loop.

---

## 10. Suggested stack and repo shape

Adjust to the builder's actual fluency — a stack they can debug under time pressure beats a fashionable one.

- **Python 3.12**, `uv` for deps
- **Pydantic** for every source schema and every LLM structured output
- **DuckDB** or SQLite for the ledger and the audit log — SQL makes the recon queries legible to a finance-literate reviewer, which matters in the panel
- **Polars/Pandas** for the batch transforms
- **pytest** with the arithmetic identities from §3.2 as property tests
- **structlog** → JSONL audit trail
- **Claude API** with tool-use for constrained outputs
- **Streamlit** or FastAPI + a light frontend. The UI is for the video; keep it thin. Exception queue + metrics dashboard + one drill-down into an evidence chain is enough.

```
/
├── README.md                    # problem, architecture, metrics + formulas, how to run
├── ARCHITECTURE.md              # diagram + tier walkthrough
├── FAILURE_LOG.md               # real incidents, dated
├── Makefile                     # make demo → full run in < 5 min, one command
├── data/
│   ├── generator/               # world sim + view derivation + anomaly injection
│   └── generated/               # dev seed + held-out eval seed + ground_truth
├── src/
│   ├── ingest/                  # schema validation, quarantine
│   ├── domain/                  # money types, entities, invariants
│   ├── resolve/                 # tier0..tier4
│   ├── verify/                  # arithmetic verifier — the hallucination gate
│   ├── ledger/                  # journal entries, recon statement, cash position
│   └── report/                  # metrics harness, exception queue
├── eval/
│   ├── run_eval.py              # held-out evaluation
│   └── ablation.py              # produces the §7 table
└── tests/
```

`make demo` must run end-to-end on a clean clone in under five minutes. Reviewers will not debug your setup.

---

## 11. Video structure (5 minutes, hard cap)

| Time | Content |
|---|---|
| 0:00–0:35 | The problem, in money terms. A controller spends N hours a cycle tying settlements to bank credits and books, and the gap is not one number — it's MDR, GST, TDS, reserve and disputes tangled together. |
| 0:35–1:15 | Architecture: the tiers, and *why* arithmetic is deterministic and the LLM is fenced. |
| 1:15–2:45 | Live run on the held-out batch. Show throughput, the metrics, and then **drill into one exception** — the evidence chain, the confidence, the suggested action. |
| 2:45–3:30 | The ablation table. Where the LLM earned its place, and where it didn't. |
| 3:30–4:20 | Failure recovery: kill the API mid-run on camera, show degraded mode complete the batch and self-report. |
| 4:20–5:00 | The honest exception list — including the class you know it can't solve, and why. |

The kill-the-API moment is worth more than any feature you could add in the same hour.

---

## 12. Open decisions — resolve before or during planning

1. **Merchant persona:** direct merchant (no 194-O) or marketplace/aggregator (194-O applies)? This decides whether TDS is in the deduction stack at all.
2. **Multi-gateway?** Adding a second aggregator creates the same-day-collision exception class and strengthens "multi-source", but roughly doubles generator work.
3. **Live Razorpay test-mode API, or purely synthetic?** The track says synthetic data, so synthetic is fully compliant. A thin adapter that *could* read the real settlements API — demonstrated against test mode even if the eval runs on synthetic — is a cheap credibility win. Decide whether it's worth the time.
4. **Agent or pipeline?** Be honest either way and design the trace accordingly.
5. **Forward cash forecast:** in scope as a stretch, or cut now to protect the core?
6. **UI depth:** how much of the 13 days goes to the interface vs the engine? Recommendation: no more than 15%.

---

## 13. Planning protocol — incremental, gate-driven

### 13.1 Why this project must be planned incrementally

A full up-front plan for this build would be guesswork, for a concrete reason:

**The shape of the residual set after Tier 1 determines the entire back half of the project.** Until the arithmetic decomposition has actually run against real generated data, nobody knows how many records survive it, what they look like, or whether they cluster into a few mechanical patterns (in which case Tier 2 scoring finishes the job and the LLM has no defensible place) or scatter into genuinely ambiguous cases (in which case Tier 3 adjudication is the centrepiece).

Both outcomes are good submissions. They are *different* submissions. Committing to one on day 1 means either building an LLM layer that the ablation table then proves was unnecessary — a direct AI-judgment failure — or under-building the layer that turns out to carry the result.

The same applies downstream: the exception taxonomy in §6 is a hypothesis, not a spec. Which codes are real, which collapse into each other, and which never fire is an empirical question answered by running the generator.

So: **measure, then plan the next increment.**

### 13.2 The protocol

For each increment:

1. **Plan only the current increment**, in detail sufficient to execute. Later increments stay as one-line statements of intent — no task breakdown, no estimates.
2. **State the exit gate as a measurable condition**, not "done". A number printed, a test passing, a file produced.
3. **State what this increment is expected to teach us** that changes the next one. If an increment teaches nothing, question whether it should be an increment.
4. Execute to the gate.
5. **Write measured results to `RUN_LOG.md`** — the actual numbers, plus anything surprising.
6. **Re-plan the next increment against those results.** Explicitly revisit: the cut list, the remaining time, and whether the increment sequence below still makes sense.

Do not batch steps 1 and 6 across increments. Stop at each gate and come back.

### 13.3 Increment sequence (a starting hypothesis — revise at each gate)

| # | Increment | Exit gate | What it should teach |
|---|---|---|---|
| **0** | Walking skeleton: minimal generator (one merchant, clean data), Tier 0 exact join, metrics harness, one exception type, `make demo` | An end-to-end match-rate number prints on a clean clone | Whether the data model and the tier boundaries hold up once real records flow through |
| **1** | Faithful generator: real Razorpay schema (§3.1), arithmetic invariants as property tests (§3.2), ground-truth emission, anomaly injection, dev + held-out seeds | Property tests green; `ground_truth.json` emitted; Tier 0 match rate measured on both seeds | The realistic Tier 0 ceiling. If it's already ~95%, the data is too clean — fix before proceeding |
| **2** | Tier 1 arithmetic variance decomposition (§4) | Residual distribution measured and characterised: how many records survive, and what they look like | **The pivot point of the project.** Decides the scope, and possibly the existence, of Tiers 2 and 3 |
| **3** | Whatever increment 2's residuals actually demand — Tier 2 scoring, Tier 3 LLM adjudication, or both | First ablation rows produced (§7) | Whether the LLM earns its place. Accept either answer |
| **4** | Ledger + loop closure: journal entries, recon statement that foots to zero, cash position, exception queue | Recon statement balances; queue emits typed exceptions with evidence | Whether "closes the loop" is actually satisfied, or only reported on |
| **5** | Failure recovery: verifier gate, degraded mode, backoff, idempotency (§8) | Full batch completes with the LLM API forcibly unavailable | Whether degraded mode is demoable on camera |
| **6** | Artifacts: video, README with metric formulas, architecture doc, failure log | All four required deliverables exist | — |

Increment 6 is **not** compressible and is 3 of the 4 things Razorpay actually receives. Protect it.

### 13.4 Standing rules across all increments

- **The eval harness is built in increment 0**, not bolted on later. Every subsequent increment reports its numbers through it.
- **`FAILURE_LOG.md` is written continuously**, from increment 0 onward, with real dates. It is a required deliverable and cannot be reconstructed convincingly at the end.
- **Maintain a live cut list**, re-ranked at every gate rather than written once. Cheapest-to-cut first; the stretch forecast in §2 is always at the top.
- **Front-load uncertainty.** Within any increment, do the part you're least sure about first.
- **Assume, don't block.** State assumptions about §12's open decisions and proceed; flag them for the human at the gate.
- **Time check at every gate.** Report elapsed vs remaining against the 05 Sep deadline. If increments 0–2 have consumed more than half the calendar, cut scope at that gate rather than at the end.

### 13.5 Output format for each planning pass

```
INCREMENT N — <name>
Goal:                one sentence
Exit gate:           measurable condition
Expected learning:   what this changes downstream
Tasks:               detailed, only for this increment
Assumptions:         re-stated, especially §12 items
Cut list:            current ranking, cheapest first
Time:                elapsed / remaining vs 05 Sep
Next (tentative):    one line only — do not expand
```

### 13.6 For this first pass

Produce **increment 0 only**, in the §13.5 format. Include a one-line statement of intent for increments 1–6 for orientation, and nothing more.
