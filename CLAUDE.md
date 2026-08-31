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

**Increment 0 — CLOSED 25 Aug 2026.** All 7 gate conditions passed.
**Increment 1 — CLOSED 31 Aug 2026.** All 12 gate conditions passed. **124 tests green.**
Next: **Increment 2 — Tier 1 arithmetic variance decomposition. The pivot.**

**Read `RUN_LOG.md`'s Increment 1 section before planning Increment 2.** The pivot depends on it, and
D-015 is the entry that decides the shape of the submission.

### What exists

Tier 0 resolver, complete for its declared remit (exact-key joins incl. `REFUND_TO_PAYMENT`,
cardinality violations, flag/date reads, per-line GST identity) · faithful world simulator: full
Sec 3.1 schema, all four line types, the whole Sec 3.3 deduction stack except TDS 194-O · contracted
MDR slab table (`domain/rates.py`) · dev + **held-out eval seed** with template-level narration split
· `eval` subcommand (D-007 closed) · ingest with Pydantic validation and quarantine · metrics with
false-clear **split by tier remit**, intrinsic clean rate and residual distribution · reconciliation
statement that foots · balanced journal entries · typed exception queue with evidence · append-only
audit log · LLM seam as a null implementation · determinism contract, verified on both seeds.

### What deliberately does NOT exist yet

Tier 1 decomposition · Tier 2 · any LLM call · ablation table · any UI · `ARCHITECTURE.md`
(Increment 6). **CUT, not pending:** second merchant scenario · FX · TDS 194-O (D-011).

`REFUND_TO_PAYMENT` was the part of the grain model most likely to be wrong. Increment 1 exercised it
against 60+ cross-cycle refunds per seed and **it holds** — the binary edge expresses them without
strain. That uncertainty is closed.

---

## Commands

```bash
./.venv/Scripts/python.exe -m recon demo     # generate + reconcile + report (dev seed)
./.venv/Scripts/python.exe -m recon eval     # the HELD-OUT seed: different world AND narrations
./.venv/Scripts/python.exe -m recon generate --seed dev --days 88
./.venv/Scripts/python.exe -m recon run --seed dev
./.venv/Scripts/python.exe -m pytest         # 124 tests; use bare pytest, NOT -q (addopts already has it)
```

The venv is at `.venv/`. `make` and `uv` are **not installed** on this machine — `python -m recon`
is the real entrypoint and the Makefile is only a forwarder for reviewers. Windows, Python 3.13.

Clean clone → working demo measured at **27 s** against a 300 s gate, at ~4x Increment 0's data
(57 s was the Inc 0 figure, on the old OneDrive path — see D-008). Protect that: dependencies are
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
  resolve/tier0.py       exact-key join + identity checking
  resolve/pipeline.py    the run: load -> resolve -> measure -> close loop -> artifacts
  llm/client.py          Adjudicator protocol, cache, NullAdjudicator
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

## Open question for Increment 2

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
