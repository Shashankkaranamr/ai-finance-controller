# STUDY_PLAN.md — what you need to know, and when

This is for **you**, not for the build. Every item names the decision or gate it unblocks. If an item
does not unblock something, it is not here.

Do not read this end to end. Read **Section 0 today** (~45 min), then come back to each section the
day before the gate it serves. Front-loading the rest is wasted effort — half of it will be answered
by our own output, and the residual distribution at the Increment 2 gate may delete a whole section.

### Depth tags

| Tag | Means |
|---|---|
| **[C] conceptual** | You need to explain it in a sentence and know why it matters. Reading it once is enough. |
| **[D] derive from memory** | You must be able to reproduce it on a whiteboard, with numbers, under questioning. These are the ones a panel probes. |

### Honesty about depth

Where surface familiarity is genuinely enough, it says so. Where a shallow answer would visibly fail,
it says that too — those are marked **⚠ shallow answer fails here**.

---

## Section 0 — Before Increment 0 (today, ~45 min)

Unblocks: reviewing the grain model, the money type, and the Increment 0 exit gate.

- [ ] **The three reconciliation grains, and what your denominator is** — [D]
  Bank credit ↔ settlement (1:1, key `settlement_utr`), settlement ↔ its line items (1:N, key
  `settlement_id`), line item ↔ book entry (1:1, key `order_id`). A fourth, `refund → parent payment`
  via `payment_id`, is declared on hypothesis.
  *Unblocks:* every metric we publish. **⚠ shallow answer fails here** — "match rate" without a stated
  numerator and denominator is the single easiest way to lose a technical panel (brief §7). When asked
  "what is your match rate", the correct reflex is "at which grain?"
  *Read our own code:* `src/recon/domain/graph.py` — `EDGE_SPECS` states each grain and its natural key.

- [ ] **Explanation rate vs match rate — why the headline is the former** — [D]
  Finding the counterparty is easy (exact UTR join clears ~95%+). Explaining the amount to a zero
  residual with every component typed is the job. *Unblocks:* the framing of every number in the README
  and the video. This is our central deviation from the brief, so you must be able to defend it cold.

- [ ] **Integer paise, and why a float is disqualifying** — [C]
  All money is `int` paise. A float in a reconciliation engine accumulates representation error and
  makes "residual == 0" unachievable and untestable. *Unblocks:* the money type review. Brief §9 lists
  it as an instant build-quality tell; one sentence is enough.

- [ ] **The settlement rollup identity** — [D]
  `settlement.amount = Σ(credit) − Σ(debit)` over all line items sharing that `settlement_id`.
  *Unblocks:* the Increment 0 property tests. Be able to write it without prompting.

- [ ] **The bank tie-out** — [D]
  The bank credit whose narration contains `settlement_utr` should equal `settlement.amount`.
  On a net-settlement merchant, deductions are already inside `settlement.amount` — so a *correct*
  tie-out is exact, not approximate. *Unblocks:* Tier 0, and knowing what a real break looks like.

- [ ] **Fee is INCLUSIVE of tax** — [D] **⚠ shallow answer fails here**
  This is the "did you actually read the schema" question. From the brief's §3.2:
  ```
  payment line:   credit = amount − fee        e.g. 100000 − 2900 = 97100
  refund line:    debit  = amount
  transfer line:  debit  = amount + fee        e.g. 100000 + 296  = 100296
  mdr_base = fee − tax          tax ≈ round(mdr_base × 0.18)
  ```
  `tax` is a *memo breakout* of the GST component already inside `fee` — it exists so the merchant can
  claim Input Tax Credit. Adding `tax` to `fee` double-counts (100342 instead of 100296) and is the
  most common way to get this wrong.
  *Unblocks:* the generator's fee arithmetic and the §3.2 property tests.
  **Note the discrepancy we found** — see the flagged item at the end of this section.

- [ ] **What "closes the loop" means** — [C]
  The run must end in an artifact a controller uses — journal entries, a reconciliation statement that
  foots, an exception queue with owners — not a report a human then redoes. *Unblocks:* why the footing
  assertion was pulled forward from Increment 4 into Increment 0.

### ⚠ Flagged: the brief's own transfer example does not satisfy its own GST rule

`fee = 296`, `tax = 46` ⟹ `mdr_base = 250`, and `250 × 0.18 = 45`, not 46. One paise off. There is no
base that yields exactly 46 at 18% and sums to 296 (`46 / 0.18 ≈ 255.6`, but `296 − 46 = 250`).

So either real data rounds on a pre-rounded base, or the documented example is illustrative rather
than exact. Either way it matters to us: **we pick one canonical rounding rule, make the generator
satisfy it exactly, and treat deviation as the `GST_ON_MDR_MISMATCH` exception** — which is already in
the brief's §6 taxonomy. That is not a workaround, it is the correct modelling: in production this
mismatch is a real thing you would want flagged.

*Worth saying in the panel.* "The reference example in the docs is a paise off its own stated GST rule,
so we defined the rule explicitly, tested it, and made the deviation an exception class" is a strong
answer. Log it in `FAILURE_LOG.md` when the property test first fires.

### Questions you should be able to answer after Section 0

1. What is your match rate? *(Correct reflex: "at which grain?" then give the number and its denominator.)*
2. Why is explanation rate your headline instead of match rate?
3. In a settlement line item, is `fee` inclusive or exclusive of `tax`? Show me with the numbers.
4. Why does `tax` exist as a separate field at all?
5. Why integer paise?

---

## Section 1 — Before Increment 1 (the faithful generator)

Unblocks: generator design, anomaly rates, and the held-out methodology.

- [ ] **The full §3.1 recon line-item schema and its four `type` values** — [C] for the 25-field list,
  [D] for the four types and the identity each obeys.
  `payment` | `refund` | `transfer` | `adjustment`. ID prefixes to mirror: `pay_`, `rfnd_`, `trf_`,
  `adj_`, `order_`, `setl_`, `setlod_`, `setlodp_`. *Unblocks:* the generator's record shape. You do not
  need to recite all 25 fields — you do need to know which four types exist and what each does to the
  ledger.

- [ ] **Net vs gross settlement** — [D]
  Indian gateways default to **net**: fees, tax and adjustments are deducted *before* the credit lands.
  Under gross settlement the full amount lands and fees are debited separately. *Unblocks:* the whole
  deduction model. **⚠ shallow answer fails here** — "is your settlement net or gross, and what changes
  if it is the other one?" is a natural panel question and the answer determines whether a shortfall in
  the bank credit is expected or a break.

- [ ] **Rolling reserve is a receivable, not lost money** — [D]
  Typically 5–10% of daily settlement withheld 90–180 days as a chargeback buffer. It is an **asset**
  (a receivable from the gateway), it belongs on its own ledger, and releases must be tied back to the
  cycle they came from. *Unblocks:* the reserve component type and the cash-position split. Modelled as
  an `adjustment` line item so the rollup identity and the bank tie-out both stay exact.

- [ ] **Chargeback reversal vs chargeback fee are two separate lines** — [D]
  The reversal is the disputed amount coming back out; the fee is a separate per-dispute charge
  (roughly ₹500–₹2,000). Conflating them is a domain tell. *Unblocks:* two distinct exception codes,
  `CHARGEBACK_UNLINKED` and `CHARGEBACK_FEE_UNBOOKED`.

- [ ] **MDR varies by method, network and card type** — [C]
  UPI / netbanking / debit / credit / Amex / international all differ. You need to know *that* it
  slabs, not the current rate card. *Unblocks:* the slab table's shape and `MDR_SLAB_MISMATCH`.
  Surface familiarity is genuinely enough here.

- [ ] **TDS 194-O — enough to defend scoping it out** — [C]
  E-commerce operator TDS on gross sales, 0.1% since 1 Oct 2024 (was 1%), reconciled against Form 26AS,
  applies only in marketplace/aggregator models. *Unblocks:* the persona decision. You are defending
  **the decision, not the mechanics**: it is monthly-grain and seller-level, a second sub-recon at a
  different grain from per-settlement, so it buys one exception code for disproportionate work. Knowing
  *why you cut it* is the answer; knowing the 26AS filing flow is not required.

- [ ] **T+2 timing: `created_at` ≠ `settled_at` ≠ bank value date** — [D]
  A payment captured 31 Mar settles 2 Apr. Books and bank disagree at period close **correctly**. The
  agent must recognise in-transit rather than flag a break. Refunds and chargebacks cross cycles: a
  refund against a payment settled in cycle N can debit cycle N+3. *Unblocks:* `PERIOD_CUTOFF_TIMING`
  and `REFUND_CROSS_CYCLE`, both marked `is_break = False`. **⚠ shallow answer fails here** — treating
  a timing difference as a break is the classic junior error, and being able to name it is a large part
  of the credibility of this project.

- [ ] **Truth-first generation, and why labelling after the fact is invalid** — [D]
  Simulate the ground-truth world, then *derive* the three source views from it, injecting corruption
  at controlled rates. Never generate three files and try to label them afterwards — the labels would
  encode your matcher's assumptions, so the eval would measure agreement with yourself.
  *Unblocks:* the generator architecture. *Read our own output once it exists:*
  `data/generated/dev/ground_truth.json`.

- [ ] **The template-holdout trap** — [D] **⚠ shallow answer fails here**
  We write the bank narrations. If a regex is authored against the same templates that generate the
  eval data, the regex wins trivially and the ablation "proves" the LLM is useless — a fact about our
  generator, not about reality. Mitigation: narration templates split into `dev_only` and `eval_only`
  families, and deterministic parsers are written only against `dev`. Held out at the **template**
  level, not just the seed level. *Unblocks:* whether the Increment 3 ablation means anything at all.
  Expect a sharp panel to ask some version of *"you tested your parser on data you built for it —
  why should I believe the ablation?"*

- [ ] **Realistic anomaly rates** — [C]
  85–92% cleanly resolvable. Data that is 50% broken is a puzzle, not a recon dataset; data that is 99%
  clean means the exception path is untested and nobody believes the number. Include at least one class
  the agent is *expected to fail on*, and say so. *Unblocks:* injection rates.

### Questions you should be able to answer after Section 1

1. Is your settlement net or gross? What would change if it were the other?
2. Where does the rolling reserve sit on the balance sheet, and why is it not an expense?
3. A refund appears in cycle N+3 for a payment settled in cycle N. Is that a break?
4. Why is TDS 194-O not in your deduction stack?
5. You generated the messy narrations *and* the parser that reads them. Why should I trust the ablation?
6. What is the difference between a chargeback reversal and a chargeback fee?

---

## Section 2 — Before the Increment 2 pivot (the decision point of the project)

Unblocks: **the biggest call in the build** — whether Tiers 2 and 3 exist, and in what form.

- [ ] **Why N-to-1 is structurally hard** — [D] **⚠ shallow answer fails here**
  Many settlement line items roll into one lump bank credit. Row-to-row matching is not merely
  inaccurate, it is *ill-posed*: there is no row on the bank side to match a line item to. This is the
  single thing that separates this build from a fuzzy-join submission, so it must be crisp.
  *Unblocks:* the framing of the whole architecture, and the first 35 seconds of the video.

- [ ] **Subset-sum vs similarity scoring** — [D]
  When `settlement_id` linkage is missing or the UTR is truncated, the honest question is *which
  subset of line items composes this credit* — a bounded subset-sum over a date-windowed candidate set.
  Deterministic, exact, and it yields an arithmetic **proof** rather than a score. Similarity scoring
  belongs only in the narrow orphan-credit case where no exact key survives. *Unblocks:* the Tier 2
  design decision at this gate. Be ready to explain why you did *not* reach for fuzzy matching.

- [ ] **Reading a residual distribution** — [C], but you must be able to narrate the decision
  After Tier 1, do the survivors cluster into a few mechanical patterns (⟹ Tier 2 finishes the job and
  the LLM has no defensible place) or scatter into genuinely ambiguous cases (⟹ Tier 3 adjudication is
  the centrepiece)? *Unblocks:* the existence and scope of Tiers 2 and 3. **Both answers are good
  submissions — they are different submissions.** *Learn this from our own output:* the residual
  histogram produced at the Increment 2 gate, recorded in `RUN_LOG.md`. Do not study this abstractly.

- [ ] **Precision, recall, and false-clear in a recon context** — [D] **⚠ shallow answer fails here**
  - *Precision:* of what we auto-matched, how much was correct. **Lead with this.**
  - *Recall:* of the true matches, how many we found.
  - *False-clear:* anomalies we wrongly marked resolved. **The dangerous class.** A missed match costs
    an analyst ten minutes; a false clear means real money silently walks out of the reconciliation and
    nobody ever looks at it again. Tracked and reported separately and prominently.
  *Unblocks:* the ground-truth schema and how we report. If you say "accuracy" without splitting these,
  a finance-literate panel will stop listening.

- [ ] **Money-weighted vs count-weighted coverage** — [D]
  Value coverage: rupees auto-reconciled ÷ rupees total. 95% of *records* but 60% of *value* is a bad
  result, and count-only metrics hide it — the exceptions are usually the large ones. Finance cares
  about the money, not the row count. *Unblocks:* the metrics module. One line, but it lands hard in a
  panel because it shows you think like a controller rather than an ML engineer.

- [ ] **Exception typing accuracy, as a confusion matrix** — [C]
  A mistyped exception sends the analyst down the wrong path, so it costs more than it sounds. That is
  the entire justification for reporting the matrix. *Unblocks:* the exception-typing metric.

### Questions you should be able to answer after Section 2

1. Why can you not just match rows to rows?
2. What is your false-clear rate, and why do you report it separately from precision?
3. You reconciled 95% of records — what fraction of the *value*?
4. Your ablation shows the LLM adding little. Why is it still in the build? *(Or: why did you cut it?)*
5. What does your residual distribution look like, and what did it make you change?

---

## Section 3 — Before Increments 4–5 (ledger and failure recovery)

Unblocks: the journal entries, the footing statement, and the degraded-mode demo.

- [ ] **The settlement journal entry, and which side each deduction lands** — [D]
  ```
  Dr Bank                    (cash actually received)
  Dr MDR Expense             (fee − tax)
  Dr GST Input Credit        (tax — reclaimable, hence its own line)
  Dr Rolling Reserve (asset) (withheld, still owed to us)
    Cr Trade Receivable      (what the customer owed)
  ```
  *Unblocks:* the ledger module. **⚠ shallow answer fails here** — if you cannot say why the reserve is
  a debit to an asset rather than an expense, the "finance controller" framing collapses.

- [ ] **Why GST on MDR must be a separate line** — [D]
  It is reclaimable as Input Tax Credit. Buried inside MDR expense, the merchant loses the claim. This
  is the business reason the `tax` field exists in the schema at all — it ties directly back to
  Section 0. *Unblocks:* the chart of accounts.

- [ ] **The footing identity** — [D]
  `opening receivable + gross sales − settlements received − explained variance − exceptions = closing receivable`
  If it does not foot to zero, the run failed. Asserted, not reported. *Unblocks:* the Increment 0 and
  Increment 4 exit gates both.

- [ ] **Cash position: settled / in-transit / reserve-held** — [C]
  Three buckets with expected release dates. This is the "and the cash position" half of the track
  prompt. *Unblocks:* the cash-position artifact.

- [ ] **Degraded mode, circuit breaker, idempotency, `blocked_hallucination`** — [C], but you must be
  able to *demo* it.
  The batch completes with zero LLM availability, at a reduced match rate, and says so in the run
  summary. Every LLM-proposed match is re-verified by the Tier 1 arithmetic engine before acceptance;
  rejections increment a counter we publish. Re-running a batch must not double-post journal entries.
  *Unblocks:* the strongest 50 seconds of the video — killing the API on camera. Brief §11 is right
  that this moment is worth more than any feature built in the same hour.

### Questions you should be able to answer after Section 3

1. Show me the journal entry for one settlement. Why is the reserve a debit?
2. What happens to your batch if the Claude API is down for the whole run?
3. What is `blocked_hallucination` counting, and what has it caught?
4. I run your pipeline twice on the same file. What happens to the ledger?

---

## Section 4 — Before the panel

Unblocks: the video and the interview. Nothing here is new material — it is rehearsal.

- [ ] **The problem in money terms, in one sentence** — [D]
  Not "reconciliation is hard". Something closer to: a controller spends N hours a cycle tying
  settlements to bank credits, and the gap is never one number — it is MDR, GST, reserve and disputes
  tangled together across a T+2 boundary.

- [ ] **The ablation narrative, including where the LLM lost** — [D]
  If the LLM row does not beat the row above it, **say so and cut it**. That is a stronger result than
  a marginal gain, and the AI-judgment axis explicitly rewards not forcing the tech. Rehearse saying
  "we removed it from that path" without apology.

- [ ] **The blind spot you shipped on purpose** — [D]
  Name the exception class the system cannot solve and why. Honesty about a known limitation reads as
  senior; a claimed 100% reads as fake.

- [ ] **Agent vs pipeline** — [D]
  The track says "build an agent". This is a pipeline with a fenced LLM adjudicator, and we say so in
  one sentence rather than dressing up a for-loop. Have the sentence ready — it will be asked, and
  flinching is worse than the answer.

- [ ] **The honest limits of synthetic data** — [D]
  What our numbers do and do not establish, and what would have to be true on real merchant data.
  Volunteer this before you are asked.

### Questions you should be able to answer after Section 4

1. What would break first if you pointed this at real Razorpay data tomorrow?
2. Which of your numbers would you least trust, and why?
3. You call it an agent — does it plan, or is it a pipeline?
4. What did you cut, and what would you build next with another week?
