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

**Increment 0 — CLOSED 25 Aug 2026.** All 7 gate conditions passed. 91 tests green.
Next: **Increment 1 — faithful generator.**

### What exists

Tier 0 resolver (exact-key join + identity checking) · world simulator with truth-first generation ·
ingest with Pydantic validation and quarantine · metrics harness with false-clear · reconciliation
statement that foots · balanced journal entries · typed exception queue with evidence · append-only
audit log · LLM seam as a null implementation · determinism contract.

### What deliberately does NOT exist yet

Tier 1 decomposition · Tier 2 · any LLM call · MDR slab table · rolling reserve · chargebacks ·
refunds/transfers/adjustments · held-out eval seed · anomaly injection beyond `MISSING_BANK_CREDIT` ·
ablation table · any UI · `eval` subcommand (D-007) · `ARCHITECTURE.md` (Increment 6).

`REFUND_TO_PAYMENT` is declared in `EDGE_SPECS` **on hypothesis** and is unexercised. It is the part
of the grain model most likely to be wrong.

---

## Commands

```bash
./.venv/Scripts/python.exe -m recon demo     # generate + reconcile + report
./.venv/Scripts/python.exe -m recon generate --seed dev --cycles 6
./.venv/Scripts/python.exe -m recon run --seed dev
./.venv/Scripts/python.exe -m pytest         # 91 tests; use bare pytest, NOT -q (addopts already has it)
```

The venv is at `.venv/`. `make` and `uv` are **not installed** on this machine — `python -m recon`
is the real entrypoint and the Makefile is only a forwarder for reviewers. Windows, Python 3.13.

Clean clone → working demo measured at **57 s** against a 300 s gate. Protect that: dependencies are
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

## Open question for Increment 1

Does Tier 0's explanation rate fall to something realistic once the data is genuinely messy? **If it
stays above ~95%, the data is too clean and must be fixed before Tier 1 is worth building.** Target
85–92% cleanly resolvable, and include at least one anomaly class the agent is *expected* to fail on.
