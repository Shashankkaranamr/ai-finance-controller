# RUN_LOG.md — measured results at each gate

Append-only. Numbers as measured, plus anything surprising. Re-planning happens against
this file, not against expectations.

---

## Increment 0 — Walking Skeleton · gate reached 25 Aug 2026

**Seed:** `dev` · 6 cycles · 213 orders · 213 line items · 6 settlements · 5 bank credits
· 437 records total. One injected anomaly (`MISSING_BANK_CREDIT`, cycle 3).

### Exit gate

| # | Condition | Result |
|---|---|---|
| 1 | Per-grain numbers print | PASS |
| 2 | Precision / recall / false-clear print | PASS |
| 3 | Five artifacts written | PASS (+ `run_summary.json`) |
| 4 | Statement foots to zero, non-zero exit if not | **PASS** |
| 5 | One typed `MISSING_BANK_CREDIT` with evidence chain | PASS |
| 6 | Two runs byte-identical `metrics.json` | PASS (sha256 `83f6c531…`, twice) |
| 7 | `pytest` green incl. identities + no-floats | PASS — **91 tests** |

### Numbers

| Metric | Value | Numerator / denominator |
|---|---|---|
| Explanation rate (bank credits) | 100.00% | 5 / 5 |
| Settlement coverage | 83.33% | 5 / 6 |
| Money-weighted coverage | 85.61% | Rs 4,43,546.72 / Rs 5,18,101.78 |
| Match rate (line items) | 100.00% | 213 / 213 |
| Linkage precision | 100.00% | 431 / 431 |
| Linkage recall | 100.00% | 431 / 431 |
| Exception detection recall | 100.00% | 1 / 1 |
| **False-clear rate** | **0.00%** | 0 / 1 |
| Exception typing accuracy | 100.00% | 1 / 1 |
| Throughput | 437 records in 105 ms | ~4,160 rec/s |
| Quarantined rows | 0 | — |
| **Clean clone -> working demo** | **57 s** | gate: < 300 s |

Clean-clone gate measured for real, not estimated: `git clone` + fresh venv +
`pip install -e ".[dev]"` + `python -m recon demo` = **57 s** (56 s of it is pip;
the demo itself is 1 s). Verified on Windows with no `uv` and no `make`, and with
no network access needed after install. The decision to hold dependencies at
pydantic + pytest is what buys this margin.

**Re-measured 31 Aug 2026 — fresh venv, at `C:\dev`, off OneDrive: 27 s.** The 57 s above stands
as the Increment 0 gate number and is not restated. This is the number a reviewer on this
machine hits today, measured phase by phase against the same `< 300 s` gate:

| Phase | Warm pip cache | Cold pip cache (`--no-cache-dir`) |
|---|---|---|
| `git clone` (local path) | 0.2 s | 0.2 s |
| `py -3.13 -m venv .venv` | 6.9 s | 6.9 s |
| `pip install -e ".[dev]"` | 18.6 s | 20.7 s |
| `python -m recon demo` | 0.8 s | 0.8 s |
| **Total** | **26.6 s** | **28.6 s** |

`git clone` from GitHub rather than from the local path measured separately at **2.7 s**, so the
end-to-end number for a reviewer starting from the public remote is **≈31 s**. Gate: < 300 s.

Three things this measurement establishes, beyond the headline:

**Determinism now holds across a clone boundary.** The fresh clone's `metrics.json` hashes to
sha256 `83f6c531…` — the same value recorded at the Increment 0 gate, from a different directory
and a freshly created venv. Invariant 2 was previously verified
only as two runs in one tree; it is now verified across the move *and* across a clean clone.

**The pip cache is not what changed.** Cold and warm differ by 2.1 s, so the drop from 56 s of pip
to ~19 s is not cache warmth. It is consistent with removing OneDrive's sync overhead from the many
small file writes a venv plus editable install performs (D-008), but this is an *observation, not a
proven cause*: the OneDrive path no longer exists, so the A/B cannot be run, and Windows filesystem
cache warmth is an uncontrolled confounder. Recorded at that strength deliberately.

**`eol=lf` behaves on Windows.** The fresh clone checks out `PLAN.md`, `graph.py` and
`.gitattributes` LF-only, and `python -m recon demo` still exits 0 against them. The line-ending
change costs nothing at run time.

Statement: gross Rs 5,18,101.78 − cash Rs 4,33,079.04 − variance Rs 10,467.68 −
exceptions Rs 74,555.06 = **Rs 0.00**. Journal: 5 entries, all balanced.

### What this taught us

**1. The predicted headline trap is real, and now has numbers behind it.**
Explanation rate on bank credits is **100.00% (5/5)** while settlement coverage is
**83.33% (5/6)**. The single worst break in the dataset — an entire settlement that never
reached the bank — is *completely invisible* in the bank-credit denominator, because a
settlement with no credit contributes nothing to it. Publishing the first number alone
would have been technically true and materially dishonest. Both are now reported side by
side, permanently. This was PLAN.md deviation #2, argued on reasoning; it is now measured.

**2. The edge model cannot express an unmatched unit — a real limitation, not a bug.**
Exceptions were designed to attach to edges. But "this settlement has no bank credit at
all" is the *absence* of an edge, and absence is not something you can hang evidence on.
Resolution: an exception's subject is a unit **or** an edge (`report/exceptions.py`,
`SUBJECT_UNIT` / `SUBJECT_EDGE`). This is the first place the skeleton pushed back on the
approved design. Worth noting that the most common break in real reconciliation is exactly
this shape, so a pure edge model would have been wrong in the field, not just here.

**3. The rollup identity was nearly tautological, and had to be rescued at design time.**
Deriving `settlement.amount` by summing the same line items it is later checked against
would have made the test prove nothing. Fixed by emitting the settlement entity as its own
view (`settlements.jsonl`), the way a real deployment gets it — a different endpoint from
the recon line items. **Generalises to Inc 1:** every identity we test must have its two
sides sourced independently, or it is decoration.

**4. The footing assertion cost about twenty minutes and validated the entity model.**
Pulled forward from Inc 4 (deviation #5). It footed on the first run, which is the boring
outcome — but it is now a standing cross-source check that will fail loudly the moment
Inc 1's deductions are modelled wrong.

**5. Degraded mode is already demonstrable.** Increment 0 has no adjudicator, so every run
exercises the rules-only path. The failure-recovery demo does not need to be built later;
it needs an LLM path added *next to* it.

**6. Throughput is a non-issue at this scale.** 437 records in ~105 ms with pure Python and
no dataframe library. The decision to defer pandas/polars holds — 2,000 records will land
around half a second. Revisit only if Tier 2 introduces combinatorial search.

### Time

2 of 13 days elapsed. **11 days remain** to 05 Sep (confirmed). Increment 0 came in at
roughly half a day against a one-day budget. No scope cut needed at this gate.

### Cut list — unchanged at this gate

No re-ranking. Forward cash forecast stays cut; multi-gateway stays held as a lever for
the Inc 2 pivot.

### Next

Increment 1 — faithful generator: full §3.1 schema, refunds/transfers/adjustments, MDR
slab table, rolling reserve, chargebacks, anomaly injection at realistic rates (85–92%
cleanly resolvable), dev + **held-out eval seed**, eval-split narration families switched on.

Open question to answer there: does Tier 0's explanation rate fall to something realistic
once the data is messy? If it stays above ~95%, the data is too clean and must be fixed
before Tier 1 is worth building.

---

## Increment 1 — Faithful generator · gate reached 31 Aug 2026

**Two seeds.** `dev` (tuned on) and `eval` (held out: a different world *and* narration templates the
parser has never seen). 88 days · 22 settlement cycles · all four Sec 3.1 line types · the full
Sec 3.3 deduction stack except TDS 194-O.

| | dev | eval |
|---|---|---|
| Orders / line items / records | 1,549 / 1,732 / 3,327 | 1,600 / 1,789 / 3,435 |
| Line types | payment, refund, transfer, adjustment | same |

### At a glance

Five of the fifteen metrics below, for a reviewer deciding whether to read further. **The `Numbers`
table is the record for this gate**; nothing here is measured independently of it, and if the two ever
disagree, that table is right and this block is stale.

| | dev | eval (held out) |
|---|---|---|
| Explanation rate · settlement coverage | 0.00% (0/24) · 0.00% (0/22) | 0.00% (0/24) · 0.00% (0/22) |
| Intrinsic clean rate — *the realism target* | 89.12% (2,965/3,327) | 89.46% (3,073/3,435) |
| **False-clear, in remit — must be zero** | **0.00% (0/109)** | **0.00% (0/104)** |
| Linkage precision | 100.00% (3,388/3,388) | 100.00% (3,488/3,488) |
| Narration parse rate | 100.00% (24/24) | 8.33% (2/24) |

Three things a skim will otherwise get backwards:

- **0% explanation is the expected result of this increment, not a regression.** Tier 0 reads the fee
  and tax the report states and knows nothing about a rolling reserve, so `gross − cash − MDR − GST`
  cannot land on zero once one exists. Increment 0's 100% was a fact about clean data. Both headline
  denominators are shown together because neither is honest alone (D-005), and here both are zero.
- **The number that must never regress is false-clear IN REMIT, not the raw 43%.** Out-of-remit
  breaks — 83 on dev, 80 on eval — are every one of them `MDR_SLAB_MISMATCH`, which needs the
  contracted rate card and is Tier 1 by definition. Nothing was cleared there; nothing looked (D-009).
- **The parse rate overstates the parser.** Both eval hits are injected stray credits carrying their
  own narration. On held-out *settlement* narrations it is **0 of 22**, and with only two held-out
  families that gap is a direction, not a magnitude.

The residual distribution below is 100% typed **by construction** — see D-015 before drawing the
obvious conclusion from it.

### Exit gate

| # | Condition | Result |
|---|---|---|
| 1 | 1,000–2,000 lines, 60–90 days, 15–25 cycles, both seeds | PASS — 1,732 / 1,789 lines, 88 days, 22 cycles |
| 2 | Full Sec 3.1 field set, all four types, exact ID prefixes | PASS — 26 fields pinned by test |
| 3 | Whole deduction stack in world *and* ground truth | PASS — 9 component types, both seeds |
| 4 | **Intrinsic clean rate in 85–92%** | **PASS — 89.12% dev, 89.46% eval** |
| 5 | One declared expected-to-fail class, and it fails | PASS — `REFUND_ORPHANED`, 9 per seed |
| 6 | Held-out split real; parse rate reported per split | PASS — 100.00% dev vs 8.33% eval |
| 7 | Residual distribution published by true component | PASS — dev; see below |
| 8 | **False clear — AMENDED, see PLAN.md** | **PASS — in-remit 0.00% (0/109 dev, 0/104 eval)** |
| 9 | Determinism per seed, byte-identical `metrics.json` | PASS — holds across regeneration too |
| 10 | Statement foots on both seeds; journal entries balance | PASS — foots on both; **0 entries**, see below |
| 11 | `pytest` green, float scan still total | PASS — **124 tests** |
| 12 | Clean clone inside 300 s at the new scale | PASS — **27 s** at ~4x the Inc 0 record count |

### Numbers

| Metric | dev | eval (held out) |
|---|---|---|
| Explanation rate (bank credits) | 0.00% (0/24) | 0.00% (0/24) |
| Settlement coverage | 0.00% (0/22) | 0.00% (0/22) |
| Match rate (line items) | 100.00% (1,732/1,732) | 100.00% (1,789/1,789) |
| Linkage precision | **100.00%** (3,388/3,388) | **100.00%** (3,488/3,488) |
| Linkage recall | 99.97% (3,388/3,389) | 99.40% (3,488/3,509) |
| Exception detection recall | 56.77% (109/192) | 56.52% (104/184) |
| False-clear, all breaks | 43.23% (83/192) | 43.48% (80/184) |
| **False-clear, in remit** | **0.00% (0/109)** | **0.00% (0/104)** |
| False-clear, out of remit | 100.00% (83/83) | 100.00% (80/80) |
| Exception typing accuracy | 100.00% (109/109) | 99.04% (103/104) |
| Intrinsic clean rate | 89.12% (2,965/3,327) | 89.46% (3,073/3,435) |
| Narration parse rate | 100.00% (24/24) | 8.33% (2/24) |
| Exceptions queued (breaks / informational) | 153 / 148 | 170 / 157 |
| Throughput | 3,327 records in 91 ms | 3,435 in 91 ms |
| Statement | foots to zero | foots to zero |

Residual at Tier 0, dev, by the component that truly accounts for it — **Rs 3,96,133.81** total:
rolling reserve Rs 1,74,079.22 (32.3%) · refund offset Rs 1,36,202.84 (25.3%) · transfer out
Rs 1,09,580.02 (20.4%) · reserve release −Rs 71,224.02 (13.2%) · chargeback reversal Rs 28,646.46
(5.3%) · chargeback fee Rs 18,000.00 (3.3%) · instant settlement fee Rs 849.29 (0.2%). **Zero
scatter.**


> **Addendum, 01 Sep 2026 — re-measured after F-010.** Building Tier 1 exposed a generator bug: the
> rolling reserve was withheld before the fee injection that changes the credits it is a percentage
> of, so it was not exactly recoverable from the report (0 of 22 dev reserve lines; 22 of 22 after
> the fix). Every accuracy and realism figure in the tables above is **unchanged on both seeds** —
> the fix moves reserve amounts and touches no unit count or anomaly assignment. Only money figures
> moved: the dev residual total below is Rs 3,96,091.57 on current code rather than Rs 3,96,133.81,
> a delta of **Rs 42.24** confined to rolling reserve (Rs 1,74,014.75), reserve release
> (−Rs 71,201.81) and instant settlement fee (Rs 849.31). The figures as first measured are left
> above; this note is the reconciliation for anyone reproducing from HEAD.

### What this taught us

**1. Explanation rate went 100% -> 0%, and that is the increment's main result.**
Tier 0 reads the fee and tax the report states. It knows nothing about a rolling reserve, so
`gross − cash − MDR − GST` stops landing on zero the moment one exists. Increment 0's 100% was a fact
about clean data, not about the resolver. This 0% is the measured argument for Tier 1. The temptation
to "fix" it inside Increment 1 was the exact scope creep CLAUDE.md's central rule exists to prevent.

**2. The gate condition on false clear was wrong, and the metric was what needed fixing.**
Condition 8 demanded 0.00% false clear. `MDR_SLAB_MISMATCH` needs the contracted rate card to detect
— Tier 1 by definition — so the condition was unmeetable without building Tier 1 here. Splitting the
metric by remit resolved it honestly: **in-remit 0.00% on both seeds**, out-of-remit 83 and 80, every
one of them `MDR_SLAB_MISMATCH`. The alternative — quietly relaxing the condition at the gate — is
how a project stops measuring the thing that matters. (F-005, D-009)

**3. The residual is 100% mechanical, BY CONSTRUCTION, and that is a caveat as much as a result.**
Every paise falls into a typed component. But the world is simulated *from* those components, so of
course they type. §13.1 poses the Inc 2 pivot as "do residuals scatter into ambiguity?" — and the
honest answer is that **Increment 1 produced no genuine Tier-2 ambiguity**, not that reconciliation
has none. This is the single most important thing to carry into the Inc 2 gate: the pivot must be
*decided*, not read off a number our own generator predetermined. (D-015)

**4. `REFUND_TO_PAYMENT` survived, and the blind spot got sharper.**
The grain declared on hypothesis in Inc 0 and named in CLAUDE.md as most likely wrong now carries 60+
cross-cycle refunds per seed without strain. Separately: the first cut of the tier annotation called
`REFUND_ORPHANED` undetectable. It is detected perfectly — the `payment_id` points at nothing — and it
is *unresolvable*. Detection and resolution are different questions, and conflating them understated
the system in the README's own honesty section. (F-008)

**5. Two generator bugs were caught by the resolver being right.**
The instant-settlement fee moved money with no line item behind it, breaking the rollup on every
`setlod_*` cycle; Tier 0 reported `ROLLUP_MISMATCH` correctly and match rate read 73.42%. And the GST
identity checker *crashed* on malformed data it exists to catch, which would have left "we verify the
GST breakout" true in the README and false in the code. Standing rule from the first: **if money
moves, a row says so.** (F-006, F-007)

**6. The ledger posts nothing, and that is correct.**
Auto-posting is gated on EXPLAINED, so zero settlements explained means zero journal entries. An
accounting system that posts a half-understood entry is worse than one that posts none and raises an
exception. The test asserting this says in its docstring that it must change to a non-zero count when
Tier 1 lands — never to a relaxed assertion.

**7. A rate is not a guarantee on a small population.**
Instant settlements at 9% over 22 cycles drew two on dev and **zero** on eval, leaving the deduction
stack complete on one seed and not the other. Caught only because the gate test was parameterised
over both seeds. Now a count, like every other whole-run event. (F-009)

**8. Throughput is still a non-issue.** 3,300+ records in 91 ms in pure Python, ~4x Inc 0's data at
the same wall clock. Clean clone 27 s against a 300 s gate. The decision to hold dependencies at
pydantic + pytest keeps paying.

### Time

**8 of 13 days elapsed (62%).** 5 days remain to 05 Sep; engine work stops **03 Sep**, so **three
engine days** remain for everything after this gate. Increments 0–2 were budgeted at half the
calendar and have now exceeded it.

**Scope was therefore cut at this gate, per ritual step 4** — not deferred again. Second merchant
scenario and FX: CUT. Increments 4 and 5: merged into Increment 2's tail, because most of both
already exists. Tier 2: conditional and now doubtful. See the re-ranked cut list in PLAN.md, dated
31 Aug.

### Next

**Increment 2 — Tier 1 arithmetic variance decomposition. The pivot.** Plan it against these
results, not against expectations, and answer D-015 explicitly at its gate: if Tier 1 closes the
residual to zero, is the submission "deterministic arithmetic closes it, and the LLM's only
defensible place is narration extraction" — for which the measured 100% -> 0-of-22 parse gap is the
argument — or is the multi-gateway lever pulled to manufacture genuine ambiguity? Both are good
submissions. They are different submissions.

---

## Increment 2 — Tier 1 arithmetic variance decomposition · gate reached 01 Sep 2026

**Built autonomously overnight** under the standing protocol. Every decision taken without review is
in the Decisions Log marked as such and is open to be overridden.

### At a glance

| | dev | eval (held out) |
|---|---|---|
| **Explanation rate · settlement coverage** | **83.33% (20/24) · 90.91% (20/22)** | 0.00% (0/24) · 0.00% (0/22) |
| **Decomposition closure** *(no linkage, no truth)* | **100.00% (22/22)** | **100.00% (22/22)** |
| Circularity split — schema · contract | 49.70% · 50.30% | 49.41% · 50.59% |
| **False-clear, in remit** | **0.00% (0/192)** | **0.00% (0/184)** |
| Exception detection recall | 100.00% (192/192) | 100.00% (184/184) |
| Linkage precision | 100.00% (3,388/3,388) | 100.00% (3,488/3,488) |
| Exception typing accuracy | 100.00% (192/192) | 99.46% (183/184) |
| Journal entries (all balanced) | 20 | 0 |
| Statement | **foots to zero** | **foots to zero** |

### Exit gate

| # | Condition | Result |
|---|---|---|
| 1 | Explanation rate AND settlement coverage, both seeds | PASS (measured, not targeted) — see above |
| 2 | Every EXPLAINED edge has residual == 0, all components typed | PASS — 20 dev edges, zero remaining `AMOUNT_VARIANCE_UNEXPLAINED` |
| 3 | `BUILT_TIER == 1`; **false-clear in remit 0.00%** | **PASS — 0/192 dev, 0/184 eval** |
| 4 | `MDR_SLAB_MISMATCH` detection recall | PASS — 83/83 dev, 80/80 eval (was 0 at Inc 1) |
| 5 | **Circularity partition published** | **PASS — ~49% schema / ~51% contract, both seeds** |
| 6 | Ablation table falls out by construction | PASS — T0 0.00%, T0+T1 83.33%, delta +83.33% |
| 7 | Journal entries post; statement foots, both seeds | PASS — 20 entries dev, all balanced; foots on both |
| 8 | Determinism per seed, incl. regeneration | PASS — byte-identical on dev and eval |
| 9 | `pytest` green; float scan still total | PASS — **138 tests** |
| 10 | Clean clone inside 300 s | PASS — **65 s** (see note on variance) |

### What this taught us

**1. The ablation is not "Tier 1 helped". It is the whole system.**
T0 alone explains **0.00%** of bank credits on realistic data; T0+T1 explains **83.33%**. Tier 0
finds the counterparty and proves the report is internally consistent, and that is worth having —
but on a merchant with a reserve it cannot explain a single rupee of the gross-to-cash gap. The
brief's thesis, that explaining the amount is the job, is now a measured number rather than a claim.

**2. The four unexplained credits are not decomposition failures.**
They are the two `UNMATCHED_BANK_CREDIT`s (no settlement behind them) and the `DUPLICATE_UTR` pair
that Tier 0 deliberately declines to link (D-014). **Every settlement Tier 1 could reach, it closed.**
Explanation rate is bounded by linkage here, not by arithmetic — which is exactly what the next
increment has to attack.

**3. THE CIRCULARITY ANSWER, which was the point of this gate.**
Explanation rate on eval is 0%, so the headline cannot answer whether Tier 1 generalises: the
narration parser finds no UTR, no bank edge is created, and **Tier 1 never runs at all**. A measure
that linkage can mask is not a measure of the arithmetic. So `closure_report` compares
`sum(settled payment amounts)` against the settlement's *own reported* `amount`, using no bank
statement and no ground truth — two independently derived views (D-003), so a real cross-check.

Result: **100% closure on both seeds.** Tier 1's rules hold on a world they were not tuned against.

And the honest limit, as a number rather than a caveat: **~49% of explained money is schema-derived**
— typed from `type` and `dispute_id`, fields the *gateway* asserts, which would read identically from
a real Razorpay report. That half is not circular. **~51% is contract-derived** — reserve 500 bps,
per-dispute fee Rs 1,500, instant fee 25 bps — constants we also generated with. That half *is*
circular in D-015's sense: it shows the rules apply to unseen **instances**, not that they would hold
for a merchant on a different **contract**.

**The defensible one-line claim is therefore: Tier 1 generalises across worlds, not across contracts.**
Anything stronger would be overclaiming, and the split is published so a reviewer can check the
arithmetic of that sentence themselves.

**4. Holding "no tolerance" found a real bug rather than costing us one.**
The reserve is identified as the adjustment debit *exactly* equal to `round_half_up(credits x
500bps)`. That matched **0 of 22** at first. The tempting fixes were both anti-patterns — read
`description` (fuzzy matching, and circular since we wrote the string) or accept a tolerance (an
arithmetic proof downgraded to a score). The generator was wrong: it withheld the reserve *before*
the fee injection that changes the credits it is a percentage of. 22 of 22 after the fix (F-010).

**5. The exception queue was showing 20 phantom breaks.**
Tier 0 raises `AMOUNT_VARIANCE_UNEXPLAINED` on every edge it cannot close; Tier 1 then closed them,
and the queue still carried Tier 0's view. An exception is a statement about the **final** state of
the graph. Supersession is now applied in the pipeline and recorded in the audit log, so the
intermediate view stays reconstructible without being shown to an analyst as a break.

**6. The false-clear denominator grew, and the number held at zero.**
At Inc 1, 83 dev breaks were out-of-remit — nothing had been built that could see them. At Tier 1
**every declared class is in remit**, so the in-remit denominator is now the whole break population
(192 dev, 184 eval) and it is still 0.00%. That is a materially stronger statement than Increment 1
could make: there is no longer anywhere for a miss to hide.

**7. Clean-clone time is noisy and the gate has room.**
65 s tonight against 27 s measured on 31 Aug, same commit shape — venv 19.3 s vs 6.9 s and pip 43 s
vs 18.6 s. Machine load, not the code: record count is unchanged and the demo itself is 2.4 s. The
gate is 300 s, so the margin absorbs it, but the honest figure to quote is a range rather than the
best run.

### Time

**9 of 13 days elapsed (69%).** Engine work stops **03 Sep** — two engine days left after tonight.

### Next

**Increment 3 — the LLM confined to narration parsing.** The measured case for it is now unusually
sharp: Tier 1 closes 100% of the gaps it is given, and the *only* thing standing between the
held-out seed and the same 83% explanation rate is that the deterministic parser scores **0 of 22**
on settlement narrations it has never seen. The LLM has exactly one job, it is the job it is best
at, and the ablation number for "without it" is already published.
