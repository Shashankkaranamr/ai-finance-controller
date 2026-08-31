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
| **Current increment** | 0 — Walking Skeleton **[CLOSED 25 Aug]** · next: Increment 1 |
| **Deadline** | 05 Sep 2026 — **confirmed with user** (not published on razorpay.com/buildathon) |
| **Today** | 25 Aug 2026 |
| **Elapsed / remaining** | 2 of 13 days elapsed · **11 days remain** |
| **Hard stop on engine work** | 03 Sep — Increment 6 needs 2 protected days (3 of the 4 deliverables) |
| **Public repo** | github.com/Shashankkaranamr — confirmed, create and push during Inc 0 |

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

## INCREMENT 0 — Walking Skeleton

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
