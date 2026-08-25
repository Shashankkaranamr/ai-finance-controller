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

<!-- New entries below. Keep the date, what broke, why it mattered, and the recovery. -->
