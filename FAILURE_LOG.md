# FAILURE_LOG.md — what broke, and how it was recovered

Written **during** development with real dates, not reconstructed afterwards. The git commit
history corroborates the timestamps. This is a required deliverable (brief §1.2, item 4) and
it cannot be faked convincingly at the end.

Entries are append-only, newest last.

---

### F-001 · 25 Aug 2026 · The reference example in the brief contradicts its own GST rule

**What broke.** While encoding the §3.2 arithmetic identities, the documented transfer example
would not satisfy the documented GST rule. `fee = 296`, `tax = 46` implies `mdr_base = 250`, and
`250 × 18% = 45`, not 46. Working backwards is no better: `46 / 0.18 ≈ 255.6`, which does not sum
to 296 with a tax of 46. The example is internally inconsistent by one paise.

**Why it mattered.** Encoding the rule to match the example would have made the generator produce
data that violates the identity we test, so `GST_ON_MDR_MISMATCH` would have been firing on our own
bug rather than on a finding. Encoding the rule "correctly" without noticing would have left a
silent disagreement with the source document.

**Recovery.** Pinned one canonical rule — `mdr_base = round_half_up(amount × 2%)`,
`tax = round_half_up(mdr_base × 18%)`, `fee = mdr_base + tax` — made the generator satisfy it
exactly, and treated deviation as the `GST_ON_MDR_MISMATCH` exception, which was already in the §6
taxonomy. Locked the finding into a test named
`test_brief_transfer_example_violates_its_own_gst_rule` so nobody later "fixes" the rule to match
the example and silently changes what the exception means.

**Standing consequence.** In production this mismatch is exactly what a controller wants flagged,
so the discrepancy became a feature of the exception taxonomy rather than a footnote.

---

### F-002 · 25 Aug 2026 · The rollup identity was almost a tautology

**What broke.** The first cut of the generator derived `settlement.amount` by summing the credits
of the line items belonging to that settlement. Tier 0 then "verified" the rollup identity
`settlement.amount == Σcredit − Σdebit` against those same line items. The test would have passed
unconditionally and proved nothing — a green check over a circular definition.

**How it was caught.** Noticed while designing the ingest schemas, when the settlement entity had
no independent source to be validated against. The absence of a `settlements.jsonl` view was the tell.

**Recovery.** Emitted the settlement entity as its own derived view (`derive_settlement_entities`),
the way a real deployment receives it — a different API endpoint from the recon line items, carrying
its own `amount`, `fees`, `tax` and `utr`. The identity now compares two independently reported
numbers, which is what makes it a check.

**Standing consequence, and it generalises.** Every identity in this system must have its two sides
sourced independently or it is decoration. Applied immediately to the reconciliation statement,
whose five terms are drawn from four different sources on purpose. This rule now governs Increment 1.

---

### F-003 · 25 Aug 2026 · The no-floats guard failed on `pathlib`

**What broke.** `tests/test_no_floats.py` asserts by AST scan that no float exists anywhere in the
package. It failed on four modules with `true division '/' (use '//')` — but every one of those hits
was `Path / "filename"`. `pathlib` overloads `/` for path joining, and it parses as `ast.Div`.

**Why it mattered.** A guard that fires on correct code gets disabled, and a disabled guard is worse
than none: the claim "no float anywhere in the pipeline" would still have been in the README while
nothing enforced it.

**Recovery.** Split the rule instead of weakening it. Float literals and any reference to `float`
remain banned in **every** module with no exceptions. The true-division rule is skipped for four
named path-joining modules, recorded as an explicit **exclusion list** rather than an allowlist — so
a new module is strict by default and adding one to the list is a visible decision in review.

**Considered and rejected.** Heuristically sniffing whether a `/` operand "looks like a path"
(string literal, name ending in `_dir`). Brittle, and it would have failed silently on `DATA / seed`.

---

### F-004 · 25 Aug 2026 · Near miss: a test asserted the wrong Indian digit grouping

**What broke.** `test_indian_digit_grouping` expected `Rs 12,34,56,789.00` for 1,234,567,890 paise.
The correct lakh/crore grouping is `Rs 1,23,45,678.90`. The implementation was right; the test was
wrong, and it failed on first run.

**Why it is logged.** It is the failure mode that matters most in this project in miniature — a
plausible-looking number that a reviewer would not check by hand. Western thousands-grouping makes a
finance reader misread the magnitude by an order of magnitude, which in a reconciliation report is
not cosmetic.

**Recovery.** Fixed the expectation, kept the exhaustive grouping cases (0, sub-rupee, lakh, crore,
negative) in the test.

---

### F-005 · 31 Aug 2026 · Increment 1's own gate condition was unmeetable by construction

**What broke.** Gate condition 8, written at the start of the increment, said the false-clear rate
must "still be 0.00% on both seeds. Non-negotiable." It was written by analogy to Increment 0, where
the data carried one anomaly and Tier 0 caught it. Once the generator produced the real deduction
stack, the condition became impossible to satisfy without either building Tier 1 inside Increment 1
or refusing to generate anomalies Tier 0 cannot see. Both are wrong.

**Why it mattered.** This is the trap the whole increment was designed to avoid, and it was sitting
in the increment's own plan. `MDR_SLAB_MISMATCH` needs the contracted rate card to detect — that is
the definition of Tier 1 work. Holding Tier 0 to a 0% false-clear rate against it would have forced
exactly the scope creep CLAUDE.md's central rule forbids. The alternative failure is worse: quietly
relaxing the condition at the gate, which is how a project stops measuring the thing that matters.

**Recovery.** The metric was wrong, not the data. "We did not flag it" was bundling two different
failures: a break the built resolver was accountable for and silently passed, and a break whose
detection needs a tier that does not exist yet. Added `detectable_at` to `ExceptionType` and split
the metric into `false_clear_in_remit` (must be zero, and is: 0/109 dev, 0/104 eval) and
`false_clear_out_of_remit` (83 and 80, every one of them `MDR_SLAB_MISMATCH`). Gate condition 8 was
amended in place with a dated note rather than rewritten, since PLAN.md is append-only.

**Standing consequence.** `BUILT_TIER` is now a single declared constant, and
`test_tier0_covers_its_declared_remit` fails if a class marked detectable at tier 0 is never raised
in `tier0.py`. Without that test the split would be self-serving — a way to relabel real misses as
"not attempted".

---

### F-006 · 31 Aug 2026 · The instant-settlement fee moved money with no line item behind it

**What broke.** The on-demand settlement fee was modelled by subtracting it from
`settlement.amount` directly. That silently broke the Sec 3.2 rollup identity on every `setlod_*`
cycle: the report's own line items no longer summed to the report's own total. Match rate read
**73.42%**.

**How it was caught.** Tier 0 reported `ROLLUP_MISMATCH` on exactly those settlements — correctly.
The resolver was right and the generator was wrong, which is the only comfortable way round.

**Why it mattered.** Had it gone unnoticed, the Increment 1 gate would have recorded a 26% rollup
failure rate as a property of realistic data. It is not a property of anything except our own bug,
and the residual distribution — the number Increment 2 pivots on — would have been contaminated.

**Recovery.** Emitted the fee as a real `adjustment` line with `debit = fee`, so it is a row like
every other deduction. Standing rule now in the `_close_settlements` docstring: **if money moves, a
row says so.** `test_the_rollup_identity_holds_over_every_settlement` covers both seeds.

---

### F-007 · 31 Aug 2026 · The GST checker crashed on exactly the data it exists to catch

**What broke.** `python -m recon run` died with
`ValueError: apply_rate_bps expects a non-negative amount, got -2`. The GST anomaly injector had
nudged `tax` above `fee` on a zero-MDR UPI line, making the MDR base negative, and
`gst_on_mdr_holds` propagated that into `apply_rate_bps`.

**Why it mattered.** Two separate defects wearing one traceback. The injector was producing an
impossible shape — `fee` is inclusive of `tax`, so `tax > fee` cannot happen — but far worse, the
identity checker **crashed on malformed input instead of reporting it**. A checker that dies on the
data it is meant to flag is one that gets wrapped in a try/except and ignored, and then the claim
"we verify the GST breakout" is false while still being in the README.

**Recovery.** Both ends. `gst_on_mdr_holds` is now total: a negative MDR base returns `False`,
because it is the strongest possible form of that mismatch, not an error. The injector keeps the
skew inside `0 < tax <= fee` and skips lines with no GST breakout to skew.

**Standing consequence.** Identity functions are checkers, so they must be defined over every input
a source file can contain, including nonsense. Robustness is not a nice-to-have in a function whose
entire job is to survive contact with bad data.

---

### F-008 · 31 Aug 2026 · "Cannot detect" and "cannot resolve" were the same field

**What broke.** The first cut of the tier annotation used one field with `None` meaning
"structurally unresolvable", and marked `REFUND_ORPHANED` that way. Then the run reported it as
**caught, 9 out of 9** — Tier 0 detects an orphan refund trivially, because the `payment_id` points
at nothing.

**Why it mattered.** The declared blind spot was described as something we cannot see. We can see it
perfectly; what we can never do is *link* it, because the original capture is outside the extract.
Getting this backwards would have made the README's honesty about a blind spot factually wrong, in
the direction of understating the system — and a panel that noticed would reasonably ask what else
was described loosely.

**Recovery.** Split into two fields: `detectable_at` (the tier that can flag it) and `resolvable`
(whether any tier could ever close it). `REFUND_ORPHANED` is `(0, False)` — always found, never
fixable. `test_exactly_one_exception_class_is_unresolvable` pins the list at one, so a growing
collection of "we can never fix this" cannot quietly become an excuse.

---

### F-009 · 31 Aug 2026 · Near miss: a gate condition that held on dev and not on eval

**What broke.** Instant settlements were selected per cycle at a 9% rate. Over 22 cycles the dev
seed drew two and the **eval seed drew zero**, so `INSTANT_SETTLEMENT_FEE` was absent from the
deduction stack on one seed and present on the other.

**How it was caught.** Only because the gate test was parameterised over both seeds from the start.
Run on dev alone it passes, and the incompleteness ships.

**Why it is logged.** A rate applied to a small population is not a guarantee, and a gate condition
verified on one seed is not verified. The failure mode here is silent and seed-dependent — the worst
kind, because it comes back on a different seed weeks later looking like a new bug.

**Recovery.** Instant settlements became a **count** chosen by `rng.sample`, matching how the other
whole-run events (missing bank credit, duplicate UTR, orphan refunds) were already modelled. Every
Increment 1 gate test is parameterised over both seeds.

---

<!-- New entries below. Keep the date, what broke, why it mattered, and the recovery. -->
