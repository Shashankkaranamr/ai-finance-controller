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

### F-010 · 01 Sep 2026 · The rolling reserve was withheld before the fee that determines it

**What broke.** Starting Tier 1, the first thing it must do is identify which adjustment line is the
rolling reserve — and it may not do so by reading `description`, which is prose we wrote (D-017). The
only honest discriminator is arithmetic: is this debit equal to `round_half_up(settled credits x
500bps)`? Measured against the dev seed, it matched **0 of 22** reserve lines, off by 16 to 329 paise.

**Cause.** `build_world` called `_build_reserve` *before* `_inject_slab_and_gst_anomalies`. The
reserve was therefore computed on pre-anomaly credits, and the fee injection then changed those
credits underneath it. A reserve cannot precede the fee that determines it: in reality the gateway
charges its fee — correctly or not — and only then withholds a percentage of what it actually
credited.

**Why it mattered.** This is the failure mode that would have quietly forced the anti-pattern. With
exact arithmetic identification impossible, the tempting fixes are all bad: read `description` (fuzzy
string matching, §9's number one, and circular since we wrote the string), or accept a tolerance
(which turns an arithmetic proof into a score). The bug was in the generator, and the modelling was
simply wrong — but it presents as "Tier 1 needs to be more forgiving", which is exactly how a clean
design erodes.

**Recovery.** Moved the fee injection ahead of the reserve, which is both correct modelling and makes
the reserve exactly recoverable: **22 of 22** after the fix. No tolerance anywhere.

**Blast radius, measured rather than assumed.** Every Increment 1 accuracy and realism metric is
**unchanged** on both seeds — intrinsic clean rate, precision, recall, false-clear in remit, parse
rate, typing accuracy — because the fix moves reserve *amounts* and touches no unit count and no
anomaly assignment. The RNG streams are named per concern, so reordering two calls does not reshuffle
any draw. Only money figures moved: the dev residual went from Rs 3,96,133.81 to Rs 3,96,091.57, a
delta of **Rs 42.24**, confined to reserve, reserve release and instant fee. Noted in RUN_LOG against
the Increment 1 entry so a reviewer reproducing it is not surprised.

---

### F-011 · 01 Sep 2026 · A gate condition was recorded PASS before it was measured

**What broke.** Increment 3's gate condition 8 read "pytest green; float scan total; clean clone
inside 300 s", and I recorded **PASS** on the strength of 156 tests passing locally. Measuring the
clean clone afterwards found **nine failures**: `FileNotFoundError: data/generated/eval/bank.jsonl`.

**Cause.** The Tier 1 and Tier 3 test modules read the held-out seed straight out of
`data/generated/eval` in the working tree, instead of the session fixtures `conftest.py` already
provides. `data/` is gitignored, so it exists only for someone who has run the CLI — which I had.
The suite was therefore testing "did somebody remember to run `python -m recon eval` first".

**Why it mattered more than the bug.** The bug is ten minutes' work. The process failure is the
finding: a gate condition was written into RUN_LOG as passing on the basis of a *related* observation
(local tests are green) rather than the stated one (a clean clone is green). That is precisely the
error the gate ritual exists to prevent, and it happened while working unsupervised, which is when it
is least likely to be caught by anyone else.

**Recovery.** Both modules take the fixtures, which generate into `tmp_path`. Verified the way the
condition is actually worded: a fresh `git clone`, a fresh venv, `data/` deleted outright, and then
**156 passed**. Clean clone to working demo measured at **50.8 s** against the 300 s gate.

**Standing consequence.** A gate condition is measured the way it is written or it is not measured.
"Green locally" is not evidence about a clean clone, and no amount of it becomes evidence. The
Increment 3 entry in RUN_LOG carries a dated correction rather than a silent edit.

---

### F-012 · 01 Sep 2026 · Every chargeback fee was reported to an analyst as a broken reversal

**What broke.** `CHARGEBACK_UNLINKED` fired on any adjustment with a `dispute_id`, no `order_id` and
no credit. A dispute emits **two** lines matching that shape: the reversal, and a flat Rs 1,500
per-dispute fee. So every fee line was queued with the sentence *"The reversal is real; the reference
is missing."* That is simply false about a fee — it reverses nothing — and it was addressed to a human
who would go looking for a sale that does not exist.

**Scale.** 17 raised on dev against 5 real; 13 against 4 on eval. Roughly 70% of that alarm was noise.

**Why it survived.** No metric measured false alarms. Detection recall was 100%, false clear was 0,
typing accuracy was 100% — every published number looked perfect while a third of one alarm class was
wrong. See F-015.

**Recovery.** One clause: the reversal carries the `payment_id` of the capture it reverses; the fee
carries none. The discriminator was already in the schema and needed no rate card. The test asserts
the raised set **equals** the injected set rather than counting alarms, so it cannot pass by the false
alarm merely becoming rarer.

---

### F-013 · 01 Sep 2026 · The UTR we said was unrecoverable was in the row's own primary key

**What broke.** README, `ARCHITECTURE.md` Finding 3, D-025, the RUN_LOG live-run entry and the video's
closing beat all rested on: *"14 of 22 held-out credits have the UTR physically cut out of the
statement. No tier recovers those."* Every one of those rows had `bank_ref = "bc_" + utr` — the
complete UTR, one field away from the narration it was supposedly absent from. 22 of 24 leaked it.

**Why it mattered.** It is a false sentence in four shipped documents, and it is load-bearing:
`blocked_unverifiable` means what it means because of it, D-025's "same shape as REFUND_ORPHANED"
parallel inherits it, and the headline LLM denominator of 8 exists only because 14 were declared
unrecoverable. With `bank_ref` present, all 22 are recoverable.

**Recovery.** `bank_ref` is now a CRC of the UTR — deterministic and stable for invariant 2, not
derivable back, and closer to a real statement, where the bank's row id has nothing to do with the
sender's reference. The leak test asserts against every settlement UTR on both seeds rather than
checking the id format, so a future scheme that reintroduces it fails.

**It was load-bearing in the tests too.** The oracle adjudicator had been recovering the UTR by
slicing `bank_ref` — an oracle exploiting a tell rather than knowing the answer. With the tell gone it
returned an empty string, and the fence scored that a **hallucination** — while the prompt explicitly
tells the model an empty string is the correct answer when no UTR is present. Abstention is not
invention. Two bugs, one of them only visible because the other was fixed.

---

### F-014 · 01 Sep 2026 · We told treasury Rs 33 lakh never arrived. It had.

**What broke.** On the held-out seed no narration parses, so no credit is linked, so
`_flag_missing_bank_credits` reported **all 22 settlements** as `MISSING_BANK_CREDIT` — Rs 33.2 lakh.
Exactly one was genuinely missing. The other 21 credits were sitting in `bank.jsonl`, unread.

**Why it mattered more than the count.** `MISSING_BANK_CREDIT` carries the action *"raise with the
gateway quoting the UTR"*, and it is the top of a queue sorted by cash at risk. The exception the
video planned to open on was one of the false ones. A judge opening `bank.jsonl` during that beat
inverts the submission's entire honesty argument in one sentence.

**Why no number caught it.** The metric suite measured one error direction — false clear — with real
rigour, and the other not at all. Detection recall was 100% *because* the resolver flagged everything;
recall of 1.0 obtained by flagging everything is not a detection result.

**Recovery.** "The money never arrived" is only defensible once every credit has been read. With
credits unparsed, the honest claim is weaker and different: `SETTLEMENT_UNCONFIRMED`, informational,
with an action that says explicitly *do not chase the gateway on the strength of this record*.
Detection is unaffected — the settlement is still flagged, and the test asserts that directly.
`NARRATION_UNPARSEABLE` also stopped being a break: our parser failing is not the merchant's money
being wrong, and counting it as one double-counted a single event.

---

### F-015 · 01 Sep 2026 · Two columns already in memory did the LLM's job better than the LLM

**What broke.** Nothing crashed. The system reported 0% explanation on the held-out seed, attributed
the gap entirely to narration parsing, and credited an LLM with recovering 3–5 of 22 — while
`(amount, value_date)` resolved **20 of 24** credits to exactly one settlement, using two columns the
resolver had already loaded and chose not to read.

**Why it mattered.** It is the first question any competent reviewer asks — *"your credit equals the
settlement amount to the paise, on the settlement date; why do you need the narration at all?"* — and
it had no answer. Worse, the LLM's entire measured contribution was work a deterministic rule was
already capable of doing better.

**Recovery.** Built it: Tier 2 corroboration, exact on both fields, uniqueness required in both
directions, every tie refused as D-014 refuses a duplicated UTR. eval explanation 0.00% → 83.33%,
recall 99.40% → 99.97%, precision unmoved, zero model calls. The adjudicator is now asked **2**
questions instead of 22 and adds **zero** on top.

**The result is better than the one it replaces.** We went looking for the LLM's job, found a
deterministic rule that does it better on our own data, and published the comparison. What we cannot
claim is that this generalises: `derive_bank` copies the settlement's amount and date straight
through and a 4-day cycle gives one settlement per date, so a real statement — netting bank charges,
batching, settling daily — would not offer the same clean key. Stated in `ARCHITECTURE.md` §4.

**Standing consequence.** A resolver that declines to read a field it has already loaded needs a
reason recorded in the Decisions Log, not silence.

---

<!-- New entries below. Keep the date, what broke, why it mattered, and the recovery. -->


---

### F-016 · 02 Sep 2026 · Tier 1 quietly retired a gate Tier 0 applied, and the ledger posted on it

**What broke.** Tier 0 marks a bank edge explained only when two things hold: the decomposition
closes, **and** the credit ties out to the settlement's own reported total
(`tier0.py`, `explained = decomposition.is_fully_explained and ties_out`). Tier 1 recomputed that as
`explained = decomposition.is_fully_explained` — the first conjunct alone — and then **overwrote the
edge status**. A settlement whose reported total contradicted both its line items and the bank credit
was therefore marked fully EXPLAINED and **auto-posted to the ledger**.

Measured on the dev seed the moment data existed that could trigger it:

```
setl_4lT0URK4hJ3Ad0   report Rs 1,38,476.30   bank Rs 1,40,714.87   diff Rs 2,238.57   -> je posted
setl_egI36JZIezdPrf   report Rs 1,64,302.88   bank Rs 1,67,424.59   diff Rs 3,121.71   -> je posted
```

One run then asserted two contradictory things about the same two settlements: `decomposition
closure` reported them as not closing, while the headline counted them as explained and the journal
posted them. README's *"the ledger posts nothing it cannot fully explain"* was false as shipped.

**Cause, and why it was invisible for two increments.** The defect landed with Tier 1 at Increment 2
and could not be detected by any test, because **no generated data could make the tie-out fail**. The
settlement entity view reported a total computed from the same line items the resolver re-sums, and
the bank credit was copied from that total. Both sides of both identities came from one number.

That is D-003 — *every identity must have its two sides sourced independently, or it is decoration* —
reappearing one layer up, in the generator rather than in the resolver. `ARCHITECTURE.md` §4 had
already named it as an acknowledged simplification and called fixing it "the highest-value remaining
generator work". It was not cosmetic. It was hiding a live defect in the check that guards the ledger.

**How it was found.** Not by the test suite, which stayed green. By injecting the thing §4 said was
missing — a settlement entity whose reported `amount` was struck before one of its own line items
posted — and then *looking at the edge status* rather than at the headline. The headline did not move
at all on dev, which is what made it worth looking: closure had dropped to 20/22 and explanation had
not budged, and those two facts cannot both be right.

**Recovery.**
1. Tier 1 inherits the conjunct: `explained = closed and bank_tie_out_holds(actual, settlement.amount)`.
2. A closed residual that fails the tie-out raises **no new exception**. The event is already queued
   as `ROLLUP_MISMATCH` against the settlement, and the record Tier 1 would have raised reads
   "Rs 0.00 survives the full deduction decomposition", which is meaningless.
3. Supersession re-keyed. D-020 dropped Tier 0's intermediate `AMOUNT_VARIANCE_UNEXPLAINED` when the
   edge reached EXPLAINED. Closed-and-explained had been the same thing until now; once they came
   apart, Tier 0's record survived on exactly these edges, telling an analyst that a reserve or refund
   "needs the contracted rate card to name" when Tier 1 had already named every component. It is now
   keyed on what the record actually claims — whether the residual closed — not on the edge's status.

**Measured after.** dev explanation 20/24 -> **18/24**, coverage 20/22 -> **18/22**, journal entries
20 -> **18**; eval unchanged at 19/24. Statement foots on both. False clear in remit 0.00% on both.
**188 tests**, including two new parametrised regression guards that assert the *property* — nothing
posts while the report disagrees with the cash — rather than a count.

**A second rule found leaning on the same field, and left alone deliberately.** The instant-settlement
fee is identified as 25 bps of `settlement.amount + fee`, so on a `setlod_` cycle with a stale total
the fee line goes untyped and the residual stays OPEN. That is the correct degradation and it was not
"fixed": typing a component off a number the system has just flagged as untrustworthy would be a guess
wearing an identity's clothes. The settlement is queued once and posts nothing either way.

**Standing consequence.** A tier may add explanation. It may never silently retire a check a lower
tier already applied. And an identity that cannot fail is not a passing test — it is an untested
region with a green light over it.


---

### F-017 · 02 Sep 2026 · Tier 2 linked a credit to a settlement Tier 0 had just declared failed

**What broke.** On the held-out seed, Tier 2 corroborated bank credit `bc_2544693262d` against
settlement `setl_q7HIlAvG26Lo14` on an exact `(amount, value_date)` match, and Tier 1 marked it
explained. That settlement carries **`status: failed`** — and in the same run, Tier 0 had already read
that field and queued it as `SETTLEMENT_FAILED`, *"the gateway attempted the transfer and it did not
complete, so the money never left"*. One run, two tiers, opposite conclusions about one settlement.

Two invariants broke at once, both of which had held for the entire project:

| eval | before | during | after |
|---|---|---|---|
| **False clear, in remit** — must be zero | 0.00% (0/186) | **0.53% (1/187)** | **0.00% (0/187)** |
| **Linkage precision** | 100.00% | **99.97%** — bank grain **18/19** | **100.00%** — 18/18 |
| Exception detection recall | 100.00% | 99.47% (186/187) | 100.00% (187/187) |

Dev was clean throughout at 100.00% and 0/195. A defect visible on one seed and not the other is
exactly the shape F-009 exists to catch, and it is why both seeds are parameterised.

**Cause 1 — the generated world could not exist.** `_inject_bank_anomalies` had already created a
`DUPLICATE_UTR` credit copying that settlement's UTR, amount and date. `_inject_failed_settlements`
then failed the same settlement, which deletes its genuine credit. The statement was left holding a
**duplicate posting of a transfer that never happened**, and with the real partner gone the duplicate
became the unique `(amount, date)` match. The new injector filtered on `s.anomaly is None`, but the
duplicate-UTR anomaly attaches to the extra *credit*, not to the settlement it was copied from, so the
settlement still looked clean. My bug, introduced with C-2(b).

**Cause 2 — and this one is not about synthetic data at all.** Tier 2's candidate pool was every
settlement not already linked. It never consulted `status`. A real statement can easily carry an
unrelated credit that matches a failed settlement's amount and date; two fields agreeing is
corroboration, and there is nothing to corroborate once the gateway has said the transfer did not
complete. The fence Tier 0 built was simply not visible to the tier above it.

**Recovery.**
1. `_inject_failed_settlements` excludes any settlement whose UTR already sources an extra bank
   credit. Asserted over the generated data, not over the injector, so it survives reordering.
2. Tier 2 excludes non-`processed` settlements from its candidate pool entirely.

**Measured after.** eval false clear **0.00% (0/187)**, linkage precision **100.00%** at every grain,
detection recall **100.00%**, statement foots on both seeds, determinism byte-identical on both.
**192 tests**, including two new parametrised guards asserting the properties rather than counts.

**Standing consequence — and this is the second instance in two days.** F-016 was Tier 1 dropping a
gate Tier 0 applied. F-017 is Tier 2 linking against a unit Tier 0 excluded. Same shape both times:

> **A tier may add explanation. It may never widen the candidate set, relax a gate, or contradict a
> fact that a lower tier has already established from the sources.**

The graph model lets any tier overwrite an edge's status, and nothing carries forward what earlier
tiers concluded about a *unit*. Two instances is a pattern, not a coincidence, and the third will land
in whatever tier is built next. See RUN_LOG for the proposed general guard and its cost.

---

### F-018 · 02 Sep 2026 · A renamed column made us tell treasury that all the money was missing

**What broke.** Renaming one column in `bank.jsonl` — `narration` to `description`, the exact failure
BRIEF Sec 8 line 344 names — made the run publish **21 `MISSING_BANK_CREDIT` breaks** against a
statement it had never read. Each one carried the sentence:

> *"Every credit in the statement was read, so this is a genuine absence."*

Maximum confidence, maximum value at risk, on 100% of settlements, asserting a completeness check
that never ran. This was found by tracing the code while planning unrelated work, then reproduced;
it was not caught by a test, and no test would have caught it, because every fixture loads clean data.

**Measured, dev seed, one column renamed per view:**

| view renamed | rows quarantined | before the fix | after |
|---|---|---|---|
| `bank.jsonl` | 23 | `MISSING_BANK_CREDIT` **1 → 21** | 0; **21 `SETTLEMENT_UNCONFIRMED`** |
| `settlement_lines.jsonl` | 1732 | `ROLLUP_MISMATCH` **2 → 22** | 0 |
| `settlements.jsonl` | 22 | **`KeyError` — batch aborted** | completes, statement foots |
| `books.jsonl` | 1549 | `BOOK_AMOUNT_MISMATCH` **65 → 0**, silently | flagged as incomplete |

Two false-positive cascades, one silent false-negative, and a hard crash that violates Sec 8's
"quarantine bad rows rather than aborting" outright.

**Cause.** `extra="forbid"` is deliberate and correct: a renamed column fails loudly. But it fails
**every row of that view identically**, so the realistic shape is not one bad row — it is the whole
view gone. Quarantine then keeps the batch alive without telling the resolver that the view it is
reading is short of rows, and every claim made *from the absence of a row* silently loses its basis.

The near-miss is the instructive part. `_flag_missing_bank_credits` **already had this guard** — D-031
and F-014 built it, after we told treasury Rs 33 lakh had not arrived when it had. But it gates on
`unread`, the count of credits that are *present and unparseable*. When the whole view quarantines
there are **zero credits, so `unread == 0`**, and the guard waves through the strongest claim the
system can make on the emptiest possible evidence. The guard defended against an unreadable
statement and not against an unloadable one, and those are different failures with the same
consequence.

The crash had a separate cause: `lines_by_settlement()` is keyed off the LINE view's `settlement_id`,
so it can name a settlement the SETTLEMENT view never loaded. `_closure_by_settlement` indexed
`repo.settlements[sid]` blind.

**Recovery.**
1. `Repository.quarantined_by_file()` / `view_is_complete()` — the resolver can now ask whether a view
   loaded completely. Deliberately strict: one lost row is enough, because the resolver cannot know
   whether the row it needed is the row it lost.
2. New `SOURCE_VIEW_INCOMPLETE` exception, raised once per affected view, owned by `data-eng`. It
   *replaces* the absence-based claims it invalidates rather than sitting beside them. Amount at risk
   is **0**, which is the honest encoding: the money is in the rows that did not load, so stating a
   figure would repeat the error being fixed.
3. Every absence-based claim checks its view first — `MISSING_BANK_CREDIT` routes to
   `SETTLEMENT_UNCONFIRMED`, and `ROLLUP_MISMATCH`, `REFUND_ORPHANED` and `UNMATCHED_BANK_CREDIT` are
   withheld, each recorded in the audit log with the reason.
4. `_closure_by_settlement` skips settlement ids the settlement view never loaded.

**Measured after.** All four views degrade without a false claim and without aborting. **239 tests**
(28 new, parameterised over both seeds and all four views). `metrics.json` **byte-identical on both
seeds** before and after the change — on a clean run the guard is inert, which is what makes it a
guard rather than a behaviour change.

**Standing consequence.** This is the third instance in two days of the same shape as F-016 and F-017,
approached from a new direction. Those two were a tier contradicting a lower tier. This one is the
resolver contradicting the *ingest layer*, which had already recorded everything needed to prevent it:

> **A count is a diagnostic, not a control. If a fact would invalidate a published claim, it must
> gate that claim in code — printing it in the run summary is not a safeguard, it is a footnote.**

The quarantine count was on screen, twenty lines above the false breaks, on every single run.

**What this does not fix.** The batch now degrades honestly, but it still produces nothing useful from
a drifted view, and nothing here recovers the rows. Recovering them needs a mapping from unrecognised
column names to the schema, which no rule can supply for a name it has not seen. That is the argument
for the next increment, and it is the first time in this project that the LLM has had a defensible
job outside narration parsing.

---

### F-019 · 02–03 Sep 2026 · The live adjudicator never knew the second job existed, and a broad `except` disguised it

**What broke.** Two defects in the same method, stacked, both on the path to the first live
`map_schema` call. Neither was caught by 258 passing tests, and the second was created *while fixing
the first*.

**Bug 1 — no job dispatch.** `AnthropicAdjudicator.adjudicate()` ignored `request.job` entirely. It
read `payload["narration"]` unconditionally, sent the narration system prompt, and returned
`{utr, counterparty, reference}`. A `map_schema` request carries no `narration` key, so the call would
have gone to the API as an **empty user message** under the wrong prompt, come back with no `mapping`,
and been scored `blocked_bad_mapping` by the verifier.

That is the dangerous shape. It would not have crashed, or errored, or looked wrong. It would have
produced **a number that reads as a measurement of the model and is actually a measurement of our own
wiring** — and it would have gone into the RUN_LOG, the README and the video as the model failing the
fence.

**Bug 2 — a `NameError` disguised as an API failure.** Fixing bug 1 introduced a variable rename in
the dispatch and left the call site reading the old name:

```python
messages=[{"role": "user", "content": narration}],   # `narration` no longer exists
```

The deliberately broad `except Exception` caught the `NameError` and returned it as a clean, typed
`AdjudicationResult(ok=False, ...)`. **Every live call would have "declined"**, `calls_declined` would
have counted 4, and the run summary would have reported an adjudicator that was unavailable or
failing. The API would never have been reached at all.

**Cause.** `map_schema` was built against the `Adjudicator` protocol and proved with test doubles —
a truthful mapper, a hostile one, three structurally invalid ones. Every one of those satisfies the
protocol without going near `AnthropicAdjudicator`. **The protocol has two implementations that
matter and the suite only ever exercised the fake one.** The tests were a complete specification of
the *interface* and said nothing about whether the real client honoured it.

Bug 2 is the module's own documented hazard landing on the author. The comment justifying the 600-
character error budget reads *"a degrade path that hides why it degraded is only half a degrade
path"* — written after a truncated workspace-id error on 01 Sep. The same handler then hid a defect
in our own code behind the same door.

**Recovery.**
1. Dispatch on `request.job`. An unwired job (`rank_candidates`, `classify_residual`) declines **by
   name without billing a call**; an empty payload is refused as our bug rather than sent to earn a
   400 recorded against the model.
2. `parse_narration` deliberately untouched — the 01 Sep live run is published, and drift there would
   stop that RUN_LOG entry describing the code. A test now pins the exact bytes it sends.
3. Job-name constants moved to `llm/client.py`, the seam that owns the `job` field. Importing a
   resolver into the vendor client to learn a string inverts the layering.
4. `tests/test_adjudicator_dispatch.py` — 5 tests against a stub transport, no key, no network. These
   are what found bug 2, within a minute of being written.

**Measured after.** 263 tests. `metrics.json` byte-identical on a clean run. The live run went out on
03 Sep and the `map_schema` mapping was **accepted on the first attempt** — see RUN_LOG.

**Standing consequence.** Two rules, and the second is the one with teeth.

> **A protocol with more than one implementation needs a test per implementation. Test doubles prove
> the interface; they cannot prove that anything real honours it.**

> **A broad `except` that converts our own bugs into the vendor's failures makes a defect in our code
> indistinguishable from an API problem in the numbers we publish.** `calls_declined` conflated "the
> API failed" with "we called it wrong". The broad handler stays — Sec 8 requires the batch to
> complete — but everything it can catch that is *ours* must now be caught before it: the job is
> validated, and an empty payload never leaves the process.

This is the fourth instance in three days of the same underlying shape as F-016, F-017 and F-018: a
component behaving correctly in isolation while contradicting, or silently failing to honour, what
another component had already established. F-018's rule was *a count is a diagnostic, not a control*.
This one's is that **a counter is only evidence about the thing it names.**
