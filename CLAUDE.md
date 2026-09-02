# CLAUDE.md — working agreement for this repo

Razorpay Buildathon, **Track 04 — AI Finance Controller**. Three-way settlement reconciliation
(books ↔ Razorpay settlement report ↔ bank statement) with typed variance decomposition, an
auto-posting ledger, and an honest exception queue.

**Deadline: 05 Sep 2026, confirmed with the user.** Engine work stops **03 Sep** — Increment 6
(video, README, architecture doc, failure log) needs two protected days and is 3 of the 4 things
Razorpay actually receives.

---

## Read these before doing anything

In this order. Do not start work from this file alone.

| File | Why |
|---|---|
| `RAZORPAY_BUILDATHON_BRIEF.md` | Standing context. Sections 3–7 are load-bearing domain detail, not background. |
| `PLAN.md` | Current increment, assumptions, cut list, and the **Decisions Log** — every call already made, with what it rules out. |
| `RUN_LOG.md` | Measured results per gate. Re-planning happens against this, never against expectations. |
| `FAILURE_LOG.md` | Real dated incidents. A required deliverable. |
| `STUDY_PLAN.md` | The user's own domain prep. Not for you, but tells you what they'll be asked to defend. |

---

## The rule most likely to be broken

**Plan ONE increment at a time, to its gate, then stop and re-plan against measured results.**

Brief §13.1 is explicit about why: the residual distribution after Tier 1 decides whether Tier 2
finishes the job (and the LLM has no defensible place) or the residuals scatter into genuine
ambiguity (and Tier 3 adjudication is the centrepiece). Both are good submissions. They are
*different* submissions. Committing early means either building an LLM layer the ablation then
proves unnecessary — a direct AI-judgment failure — or under-building the layer that carries the
result.

**Do not plan past Increment 2.** Later increments stay as one-line intents. No task breakdown, no
estimates. If you feel the urge to plan the whole build, re-read §13.1.

---

## Current state

**Increments 0–3 — CLOSED 25 Aug – 01 Sep 2026.** · **Audit response — 01 Sep.** ·
**Realism + review response — 02 Sep.** · **Schema repair — 02 Sep.**
**258 tests green.** Next: **Increment 6 — artifacts. Protected.**

Increments 2 and 3 were built **autonomously overnight**; D-018 through D-023 were taken without
review and remain marked open for override in the Decisions Log.

### The headline numbers

| | dev | eval (held out) |
|---|---|---|
| Explanation rate · coverage | 73.91% (17/23) · 77.27% (17/22) | 78.26% (18/23) · 81.82% (18/22) |
| Linkage precision | 100.00% (3,387/3,387) | 100.00% (3,506/3,506) |
| False-clear, in remit | 0.00% (0/195) | 0.00% (0/187) |
| Decomposition closure (no linkage, no truth) | 90.91% (20/22) | 90.91% (20/22) |
| Narration parse rate (regex) | 100.00% (23/23) | 8.70% (2/23) |
| Ablation | T0 0.00% -> T1 73.91% | T0/T1 0.00% -> T2 78.26%; T3 adds nothing |

**These went DOWN on 02 Sep and that is the system working** — closing three generator realism gaps
revealed two settlements per seed posting against a self-contradicting report (F-016, F-017).

**Hostile adjudicator: every proposal blocked, 0 edges, linkage precision unmoved at 100.00%.**
**Hostile schema mapper: blocked at the containment gate, rows stay quarantined.**

### What exists

Tier 0 (exact-key joins, cardinality, flags, GST identity, **source-completeness gating**) ·
**Tier 1** (full deduction stack typed against `domain/rates.py`, off-contract fee detection) ·
**Tier 2** (exact-amount corroboration inside the posting window, every tie refused — D-027, D-033) ·
**Tier 3** (LLM fenced to narration parsing, verifier gate, two rejection counters, cache) ·
**schema repair** (LLM proposes a column mapping, four exact gates, `blocked_bad_mapping` — D-036) ·
faithful generator, dev + held-out eval · statement foots, journal entries post and balance · typed
prioritised queue · audit log · determinism on both seeds · degraded mode on every run ·
`README.md`, `ARCHITECTURE.md`, `VIDEO_SCRIPT.md`, architecture diagram.

### What does NOT exist

Subset-sum search (**CUT**, D-016/D-027) · multi-gateway (**CUT** D-016; experiment run and closed
02 Sep, below) · second merchant (**CUT**) · FX (**CUT**) · TDS 194-O (out by persona) · any UI ·
`draft_note` and rate-card extraction (designed, verifiers identified, deferred — D-036).

**No API key in this environment**, so the LLM's real accuracy — extraction *and* mapping — is
**unmeasured and claimed nowhere** (D-022, D-036). Every published LLM number comes from test doubles
(oracle, hostile, structurally invalid) and measures **the fence**, never the model.

### The second-gateway experiment — closed 02 Sep, code stashed

Pre-registered, run, closed. The falsifiable core held: **the oracle ceiling did not rise, 0 → 0** —
Tier 2 keys on exact `int(amount)`, so an amount-proximate credit hits no key and proximity is
irrelevant. One row falsified: `UNMATCHED_BANK_CREDIT` stayed at 2 rather than rising by 6, because
the `utr is None` branch fires *before* the settlement lookup and held-out narrations never parse. The
implementation is **stashed, not discarded** (`git stash list`); the knob ships nowhere and no test
depends on it. Full result in RUN_LOG.

### NEEDS SIGN-OFF BEFORE IT SHIPS

`README.md` and `ARCHITECTURE.md` were brought current with Part 0/1/2 on 02 Sep — schema repair,
F-018, D-036, and the second-gateway result. **Not yet reviewed by the user.** These are the public
framing and two of the four things Razorpay actually receives, so treat the wording as provisional
until it is signed off.

---

## Commands

```bash
./.venv/Scripts/python.exe -m recon demo     # generate + reconcile + report (dev seed)
./.venv/Scripts/python.exe -m recon eval     # the HELD-OUT seed: different world AND narrations
./.venv/Scripts/python.exe -m recon generate --seed dev --days 88
./.venv/Scripts/python.exe -m recon run --seed dev
./.venv/Scripts/python.exe -m pytest         # 258 tests; use bare pytest, NOT -q (addopts already has it)
```

The venv is at `.venv/`. `make` and `uv` are **not installed** on this machine — `python -m recon`
is the real entrypoint and the Makefile is only a forwarder for reviewers. Windows, Python 3.13.

Clean clone → working demo measured at **27–65 s** against a 300 s gate (the spread is machine
load, not code; 57 s was the Inc 0 figure on the old OneDrive path — see D-008). Protect that: dependencies are
`pydantic` + `pytest` and nothing else. No pandas/polars until a profile says otherwise.

---

## Invariants — do not violate without a Decisions Log entry

1. **All money is integer paise.** The *entire package* is float-free, enforced by AST scan in
   `tests/test_no_floats.py`. Rates are integer basis points; timing uses `perf_counter_ns`. This is
   a property, not a style rule — keep it total.
2. **Determinism.** Same seed ⇒ byte-identical `metrics.json`. Never seed from `hash()` (salted per
   process); use `zlib.crc32`. Sort before serializing. Wall-clock lives in `run_summary.json`, never
   in `metrics.json`.
3. **Truth-first generation.** Simulate the world, emit ground truth, *then* derive the views. Never
   label views after the fact — that encodes the matcher's assumptions and the eval measures
   agreement with itself.
4. **Narration templates stay split `dev` / `eval`.** Deterministic parsers are written **only**
   against `dev` families. Held out at the *template* level, not just the seed level. Violating this
   makes the Increment 3 ablation meaningless and a panel will spot it.
5. **Tier is an attribute of an edge, never of a row.** That is what makes the ablation table fall
   out by construction.
6. **The headline is explanation rate AND settlement coverage, together, always.** Never publish a
   single-number headline. See the trap below.
7. **Every identity must have its two sides sourced independently**, or it is decoration (D-003).
8. **The LLM never computes money.** It selects and explains. Every LLM-proposed match is re-verified
   by the arithmetic engine before acceptance; rejections increment `blocked_hallucination`.
9. **`is_break` separates real breaks from explained-but-notable.** Conflating them inflates the
   exception count and understates the agent (§6).
10. **False clear is split by remit, and the in-remit number must be zero.** `ExceptionType` carries
    `detectable_at` (lowest tier that can flag it) and `resolvable` (can any tier ever close it).
    `BUILT_TIER` in `domain/graph.py` says how far the resolver actually goes — **bump it in the same
    commit that lands a tier, never ahead of one.** `test_tier0_covers_its_declared_remit` fails if a
    class marked tier 0 is never raised in `tier0.py` (D-009).
11. **If money moves, a row says so.** Every deduction is a line item, never a silent adjustment to a
    total. Violating this breaks the rollup identity and the resolver correctly blames the data for
    our bug (F-006).
12. **A gate condition verified on one seed is not verified.** Parameterise over `dev` and `eval`
    (F-009).
13. **A gate condition is measured the way it is written, or it is not measured.** "Tests green
    locally" is not evidence about a clean clone, and no amount of it becomes evidence. Tests must
    never read `data/generated/` from the working tree — use the conftest fixtures (F-011).
14. **The verifier gate is necessary, not sufficient.** It blocks a wrong answer; it does not block a
    *correct* answer to an ambiguous question. "The model was correct" and "the action was safe" are
    different questions and only the second one matters at the gate (D-023).
15. **An absence is only evidence when the view that would have carried the row loaded completely.**
    Every claim reasoning from a row NOT being there checks `repo.view_is_complete()` first; a view
    short of rows raises `SOURCE_VIEW_INCOMPLETE` and the absence-based claims it invalidates are
    withheld, not published beside it. A renamed column once produced 21 `MISSING_BANK_CREDIT` breaks
    asserting "every credit in the statement was read" (F-018).
16. **A count is a diagnostic, not a control.** If a fact would invalidate a published claim, it must
    gate that claim in code. The quarantine count was printed in the run summary, twenty lines above
    the false breaks, on every single run (F-018).

---

## Traps specific to this codebase

**Do not "fix" the GST rule to match the brief's example.** The brief's transfer example
(`fee=296, tax=46`) violates its own stated rule: `296 − 46 = 250`, and `250 × 18% = 45`, not 46. No
base yields 46 at 18% while summing to 296. We pin a canonical rule and treat deviation as
`GST_ON_MDR_MISMATCH`. `test_brief_transfer_example_violates_its_own_gst_rule` exists precisely to
stop someone reverting this. (D-004, F-001)

**The rollup identity is easy to make tautological.** `settlement.amount` comes from its own view
(`settlements.jsonl`), not from summing the line items it is checked against. If you add a new
identity, ask where each side comes from. (D-003, F-002)

**The headline trap is measured, not theoretical.** At the Inc 0 gate, explanation rate read
**100.00% (5/5)** while settlement coverage read **83.33% (5/6)** — a settlement that never reached
the bank contributes nothing to the bank-credit denominator, so the worst break in the set was
invisible in the first number. (D-005)

**A 0% explanation rate at Tier 0 is the expected result, not a regression.** Tier 0 reads the fee
and tax the report states and knows nothing about a rolling reserve, so `gross − cash − MDR − GST`
cannot land on zero. Increment 0's 100% was a fact about clean data. Do not "fix" this outside
Increment 2 — it is the measured argument for Tier 1.

**The residual distribution is 100% typed BY CONSTRUCTION. Do not quote it as a discovery.** The
world is simulated from typed components, so of course every residual types. It means an arithmetic
Tier 1 can reach all of it; it does *not* mean real residuals behave this way, and it means
Increment 1 produced **no genuine Tier-2 ambiguity**. The Inc 2 pivot must be decided, not read off
this number. (D-015)

**Detection and resolution are different questions.** `REFUND_ORPHANED` is detected perfectly at
Tier 0 and is unresolvable at every tier. Saying "we cannot see it" understates the system and is
simply false. (F-008)

**Exceptions attach to a unit OR an edge.** An unmatched unit is the *absence* of an edge, and
absence carries no evidence. This is the most common break shape in real reconciliation. (D-002)

**`pathlib` overloads `/`,** which parses as `ast.Div`. The float scan bans division in all modules
except four named path-joining ones, tracked as an *exclusion list* so new modules stay strict by
default. Do not weaken the rule; add to the list deliberately. (D-006, F-003)

---

## The gate ritual

At the end of every increment, in order:

1. Run the gate conditions and record **measured** numbers in `RUN_LOG.md` — plus anything surprising.
2. Append Decisions Log entries to `PLAN.md` (`Gate · Date · Decision · Why · What it rules out`).
3. Re-rank the cut list **in place**, with a dated note.
4. Time check: elapsed vs remaining against 05 Sep. If Inc 0–2 have eaten more than half the
   calendar, cut scope *at the gate*, not at the end.
5. **Stop.** Re-plan the next increment against the results. Do not roll straight on.

### Docs discipline

- `PLAN.md` is **append-only at gates**. Mark superseded sections `[CLOSED]`; never rewrite history.
- `FAILURE_LOG.md` is written **during** development with real dates. It cannot be reconstructed
  convincingly at the end, and the git history corroborates the timestamps.
- Never edit an existing Decisions Log entry — supersede it with a new one that references it.

---

## Commit conventions

**Do not add `Co-Authored-By`, `Claude-Session`, or any AI-attribution trailer to commits.** The user
asked for these removed and the history was rewritten to strip them. Commits are authored by
`shashankkaranam <shashankkaranamr@gmail.com>` alone. Adding them back would undo an explicit request.

Otherwise: subject line in the imperative, then a body explaining *why* — the reasoning, trade-offs,
and what was rejected. The commit history is part of the build-quality story a reviewer reads.

Remote: `https://github.com/Shashankkaranamr/ai-finance-controller` (public).

---

## Repo map

```
src/recon/
  domain/graph.py        THE grain model -- units, typed edges, tiers, exceptions. Start here.
  domain/identities.py   Sec 3.2 arithmetic as pure functions. Read the docstring.
  domain/truth.py        ground truth, designed backwards from false-clear
  generate/world.py      world simulator (truth) -- GenConfig controls scale and anomalies
  generate/derive.py     the four derived views
  generate/narration.py  template registry with the dev/eval split + the UTR parser
  ingest/schemas.py      Pydantic, extra="forbid" so a renamed column fails loudly
  ingest/load.py         Repository + quarantine
  ingest/source.py       SettlementSource protocol (a real API client plugs in here)
  resolve/tier0.py       exact-key join + identity checking + source-completeness gating
  resolve/tier2.py       exact-amount corroboration inside the posting window (D-027)
  resolve/tier3.py       the fenced adjudicator: parse_narration + the verifier gate
  resolve/schema_repair.py  map_schema: proposes a column mapping, four exact gates (D-036)
  resolve/pipeline.py    the run: load -> resolve -> measure -> close loop -> artifacts
  llm/client.py          Adjudicator protocol, cache, NullAdjudicator, LLMStats counters
  ledger/statement.py    footing statement + balanced journal entries
  report/metrics.py      every numerator and denominator, stated
  report/exceptions.py   the queue: type, evidence, hypothesis, action, owner
  audit/log.py           append-only JSONL; run_id is the idempotency key
```

Artifacts land in `out/<seed>/`; generated data in `data/generated/<seed>/`. Both gitignored — the
demo regenerates them, which is what keeps the clean-clone path fast.

---

## Anti-patterns that sink this submission (brief §9)

Fuzzy string matching as the centrepiece · floats for money · the LLM computing totals · exactly 50
records · synthetic data so clean it yields 99% · a chatbot over a CSV · metrics without a held-out
set · a demo that only walks the happy path · four shallow features instead of one deep loop ·
calling a pipeline an agent.

On that last one: **this is a pipeline with a fenced LLM adjudicator, and we say so.** The track asks
for an "agent"; the AI-judgment axis rewards not forcing the tech. Address it head-on in one sentence
rather than dressing up a for-loop.

---

## Open question for Increment 2 — [CLOSED 01–02 Sep 2026]

Kept for the reasoning, not as live guidance. **Both branches below were eventually answered by
measurement:** Tier 1 closed the residual, so the first branch is the shipped submission (D-016);
the multi-gateway lever was later pulled anyway, as a *pre-registered experiment* rather than a
feature, and the result was that it changes nothing — the oracle ceiling did not move. The
implementation is stashed and the reasoning is in RUN_LOG's 02 Sep entries.

The thing this section got wrong is worth keeping: it framed the LLM's place as a binary between
"narration extraction" and "manufactured Tier-2 ambiguity". The third option it never considered —
**the ingest boundary**, where a renamed column costs a whole view and no rule can recover it — is
where the second fenced job actually landed (D-036).

**Does Tier 1 close the residual to zero — and if it does, what is the submission?**

Increment 1 measured Tier 0's residual as 100% typed-component-shaped with zero scatter, so an
arithmetic Tier 1 should reach all of it. That is the good outcome, and it creates the harder
question, which §13.1 says is the whole reason for planning incrementally:

- **If Tier 1 closes it:** the honest submission is "deterministic arithmetic closes the loop, and
  the LLM's only defensible place is narration extraction" — for which the measured parse gap
  (100.00% on dev, **0 of 22** on held-out settlement narrations) is the argument. The ablation then
  shows the LLM adding nothing to the arithmetic and everything to extraction, which is a *result*,
  not a disappointment.
- **Or pull the multi-gateway lever** (cut list rank 8, held for exactly this) to manufacture genuine
  Tier-2 ambiguity, and build the adjudicator the track's AI-judgment axis rewards.

Both are good submissions. They are different submissions. **Three engine days remain (stop 03 Sep),
so this choice is also a scheduling decision — make it at the Increment 2 gate, explicitly, and
record it.**
