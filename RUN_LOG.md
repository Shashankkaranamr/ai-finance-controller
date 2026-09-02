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

---

## Increment 3 — The fenced adjudicator · gate reached 01 Sep 2026

> ## OVERNIGHT SUMMARY — read this first
>
> **Worked autonomously 01 Sep.** Increment 2 (Tier 1) and Increment 3 (fenced adjudicator) both
> closed. **156 tests green, 10 commits, all pushed, working tree clean.** Verified on a fresh clone
> with `data/` deleted, not just locally — see F-011 for why that distinction cost me a wrong entry.
>
> **The one thing to look at first:** the table under *The fence, measured* below — specifically the
> `hostile` row. 22 plausible-but-wrong UTRs proposed, **22 blocked, 0 edges created, linkage
> precision unmoved at 100.00%**. That is the architectural claim of this whole submission, and it
> is now a measured number rather than an assertion.
>
> **Decisions I made without you, all reversible, all in the Decisions Log:**
> - **D-018** — measure Tier 1 by *decomposition closure* rather than explanation rate, because on
>   the held-out seed no bank edge exists and explanation rate is 0% for reasons unrelated to the
>   arithmetic. Conservative: it adds a measurement, removes none.
> - **D-019** — the claim we defend is *"Tier 1 generalises across worlds, not across contracts"*,
>   backed by a published ~49/51 schema/contract split. I chose the weaker, defensible claim over
>   the stronger one the numbers superficially support.
> - **D-020** — exceptions describe the graph's final state; superseded ones are dropped from the
>   queue and kept in the audit log. Fixed 20 phantom breaks.
> - **D-021** — Tier 3 runs *before* Tier 1 and supplies linkage only; edges carry `linked_by`
>   separately from `tier`.
> - **D-022** — with no API key, the fence is measured and the model's accuracy is claimed
>   **nowhere**. The oracle number below is an upper bound, labelled as such.
> - **D-023** — Tier 3 honours Tier 0's ambiguity refusal (D-014). Found by precision dropping to
>   99.97%.
>
> **A mistake I made and corrected, worth your attention more than the features:** I recorded gate
> condition 8 as PASS because 156 tests passed *locally*, then measured it as written and found
> **nine failures on a clean clone** — the new tests read the held-out seed out of the working tree,
> and `data/` is gitignored. Fixed and re-verified properly. The correction sits under the original
> row rather than replacing it, and the process failure is logged as **F-011**, because marking a
> condition passed on a *related* observation instead of the stated one is exactly what the gate
> ritual exists to stop — and unsupervised is when nobody else catches it.
>
> **Flagged for your sign-off, deliberately not done:** `README.md` still carries Increment 1's
> numbers and now understates the system considerably (it says explanation rate 0%; it is 83.33% on
> dev). Updating it changes the project's public framing, which you asked me not to push without
> review. It is the first thing to approve.
>
> **Not done, needs you:** the LLM's real extraction accuracy. There is no `ANTHROPIC_API_KEY` in
> this environment, so it is unmeasured and unclaimed. With a key, `python -m recon eval` plus the
> adjudicator wired in would produce the real number in one run.

### The fence, measured (held-out seed, 22 unparseable narrations)

| Adjudicator | Explanation | Coverage | Precision | Calls | **Blocked** | T3 edges | Foots | JEs |
|---|---|---|---|---|---|---|---|---|
| **null** (shipped default) | 0/24 | 0/22 | 100.00% | 0 | 0 | 0 | YES | 0 |
| **hostile** (plausible wrong UTRs) | 0/24 | 0/22 | **100.00%** | 22 | **22** | **0** | YES | 0 |
| **broken** (every call 503s) | 0/24 | 0/22 | 100.00% | 22 | 0 | 0 | YES | 0 |
| **oracle** (perfect extractor — *upper bound, not a claim*) | 21/24 | 21/22 | 100.00% | 22 | 0 | 21 | YES | 21 |

### Exit gate

| # | Condition | Result |
|---|---|---|
| 1 | Adjudicator asked only where the regex failed | PASS — asked set == `NARRATION_UNPARSEABLE` set, pinned by test |
| 2 | **Hostile adjudicator 100% blocked** | **PASS — 22/22, zero edges created** |
| 3 | **Linkage precision unmoved under attack** | **PASS — 100.00%, and the statement still foots** |
| 4 | A truthful adjudicator IS accepted (not a wall) | PASS — 21 accepted, 1 refused on ambiguity |
| 5 | Degraded mode: no adjudicator, run completes | PASS — unchanged, exit 0 |
| 6 | Determinism with an adjudicator wired in | PASS — byte-identical; both seeds byte-identical on the default path |
| 7 | Ablation extends to T3, still a group-by | PASS — eval: T0 0%, T1 0%, T3 87.50% |
| 8 | `pytest` green; float scan total; clean clone in gate | PASS — **156 tests** |
| 9 | No claim about real LLM accuracy | PASS — asserted nowhere; see D-022 |

> **Correction, 01 Sep 2026 (same day).** Condition 8 above was first recorded PASS on the
> strength of 156 tests passing *locally*. Measuring it as written then found **nine failures
> on a clean clone** — the Tier 1 and Tier 3 modules read the held-out seed out of the working
> tree instead of the conftest fixtures, and `data/` is gitignored. Fixed, and re-verified the
> way the condition is worded: fresh clone, fresh venv, `data/` deleted, **156 passed**; clean
> clone to working demo **50.8 s** against a 300 s gate. The original row is left as written.
> The process failure is the point and is logged as **F-011**: a gate condition is measured the
> way it is written, or it is not measured.

### What this taught us

**1. The verifier was necessary and not sufficient, and that is the most useful thing here.**
The gate blocks hallucinations perfectly. It did **not** block an adjudicator that read a
*duplicated* UTR correctly — because that is not a hallucination, it is right, and the lookup
succeeds. Tier 3 therefore made exactly the link Tier 0 refuses to make on ambiguity (D-014).

It surfaced as linkage precision dropping to **99.97%** and the statement ceasing to foot — which is
precisely why both are asserted rather than only the hallucination count. A fence tested solely
against wrong answers would have shipped this. The lesson generalises: *"the model was correct" and
"the action was safe" are different questions, and only the second one matters at the gate.*

**2. One tier per edge was not enough once an LLM could create edges.**
`tier` means "the tier that produced the current status", and Tier 1 upgrades an LLM-linked edge
immediately after Tier 3 links it — so the adjudicator's entire contribution vanished from the graph
and from the ablation. Edges now carry `linked_by` as well, and an edge counts at tier N only if
**both** its linkage and its explanation are within N.

**3. The eval failure is now localised to exactly one component.**
With linkage supplied by an oracle, the held-out seed goes from 0/24 to **21/24 explained, 21/22
coverage, statement footing, 21 balanced journal entries** — the same behaviour as dev. So the whole
held-out gap is narration parsing, and nothing else. That is the sharpest possible case for where an
LLM belongs, and it was measured rather than argued.

**4. Degraded mode is not a feature we added; it is the path we ship.**
Every run in this repo to date has run with no adjudicator. The `broken` row above — 22 calls, all
failing — completes, reports, foots, and keeps precision at 100.00%.

### Time

**9 of 13 days elapsed.** Engine work stops **03 Sep**: two days left. Increments 4 and 5 were merged
into Increment 2's tail at the Inc 1 gate and are substantially delivered (statement foots, journal
entries post and balance, typed and prioritised queue, degraded mode, audit log, determinism,
`blocked_hallucination`).

### Next

**Increment 6 is the remaining work, and it is protected.** Video, README, architecture doc, failure
log — 3 of the 4 things Razorpay actually receives. The README rewrite is the first task and needs
sign-off because it changes public framing.

---

## Increment 3 — LIVE adjudicator run · 01 Sep 2026

**The first real LLM calls this project has made.** 22 held-out narrations, `claude-haiku-4-5`,
one call each, ~47 s wall clock. Reported exactly as returned.

### The ablation, measured

| Metric | rules only | + adjudicator |
|---|---|---|
| Explanation rate (bank credits) | 0.00% (0/24) | **20.83% (5/24)** |
| Settlement coverage | 0.00% (0/22) | 22.73% (5/22) |
| **Linkage precision** | 100.00% (3,488/3,488) | **100.00% (3,493/3,493)** |
| Linkage recall | 99.40% | 99.54% |
| Journal entries posted | 0 | 5 |
| Statement foots | YES | YES |
| Adjudicator calls | 0 | 22 |
| `blocked_hallucination` | 0 | 17 |

**Precision did not move.** 17 rejected proposals, and not one reached the ledger. The
hostile-adjudicator test predicted this; the adversary here was the real model.

### The finding that matters more than the headline

`blocked_hallucination = 17` **overstates hallucination by roughly five times**, and the counter is
what is wrong, not the model. Checked mechanically rather than by eye:

| Of the 22 held-out narrations | Count |
|---|---|
| Correct and verified | **5** |
| **Full UTR provably ABSENT from the narration** | **14** |
| Genuine extraction errors | **3** |

The `neft_truncated` family truncates at 40 characters. The prefix
`NEFT-RAZORPAYSOFTWAREPVTLT-UTR` is 30 of them, so only **10 of the 16 UTR characters survive** in the
source at all. In **all 14** cases the model returned exactly the substring that was present:

```
narration : NEFT-RAZORPAYSOFTWAREPVTLT-UTR1487099871
true utr  : 14870998713daxoq
proposed  : 1487099871          <- exactly what the text contains
```

That is not a hallucination. It is the same shape as `REFUND_ORPHANED`: the evidence is not in the
extract, and no tier — LLM included — can recover it. **Rejecting it was still correct**, because an
unverifiable reference must never become a link. Counting it as a hallucination is the error.

By family:

| Family | correct / blocked | note |
|---|---|---|
| `neft_truncated` | 0 / 14 | UTR truncated out of the source; unrecoverable by anyone |
| `rtgs_no_delimiter` | 5 / 3 | UTR present; the model mis-split a delimiter-free run |

**Accuracy where the UTR was actually present: 5 of 8 (62%).** That is the honest number for what the
model can do on this task, and it is very different from the 5-of-22 the headline implies.

This is D-023 again, one level along: *"the model was correct" and "the action was safe" are
different questions.* We drew that distinction for a duplicated UTR and failed to draw it for an
absent one. Splitting the counter changes a video-facing number, so it is **proposed, not done** —
see the open question below.

### The three plumbing fixes this run forced

1. **Workspace header.** An identity-linked API key is workspace-scoped; without
   `anthropic-workspace-id` every call 400s. Read from `ANTHROPIC_WORKSPACE_ID`, sent via
   `default_headers` (the SDK client has no workspace parameter — checked the constructor).
2. **Markdown fence stripping.** The model wraps its JSON in ` ```json ` fences and `json.loads`
   rejected it at character zero. Handled as plumbing, deliberately **not** by tightening the prompt:
   a firmer instruction would still fail intermittently, and tuning the prompt against observed
   held-out behaviour is the eval-tuning deviation #4 forbids.
3. **Error truncation widened, 200 → 600 chars.** The very first live error read
   `anthropic-workspace-id is required ... send` — cut off exactly where it began explaining the fix.
   A degrade path that hides why it degraded is only half a degrade path.

### What was deliberately NOT done

**The prompt was not touched, and will not be on the strength of this run.** It was written blind,
before any held-out narration was seen, exactly as the regex was written against `dev` families only.
Improving it against results from the eval seed would make the ablation measure our tuning rather
than the model. If it is worth improving, that happens against `dev` narrations, as a separate dated
decision, and is then re-measured here.

### Addendum, 01 Sep 2026 — the counter split, and a second run that changed the answer

`blocked_hallucination` was split into two counters (D-025). Then the live run was repeated so the
artifacts would match the claim, and **the second run returned a different answer**.

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| Correct and verified | **5 / 22** | **3 / 22** | **4 / 22** |
| `blocked_hallucination` (invented, or under-read available characters) | 3 | 5 | 4 |
| `blocked_unverifiable` (read it right; document has no usable reference) | **14** | **14** | **14** |
| Explanation rate | 20.83% | 12.50% | 16.67% |
| **Linkage precision** | **100.00%** | **100.00%** | **100.00%** |
| Statement foots | YES | YES | YES |

**On recoverable data (the 8 narrations where the UTR is actually present): 5/8, 3/8, 4/8 — 62%,
38%, 50%.** Mean 50%, spread ±12 points. Three samples is still three samples, and it is quoted as a
range for that reason.

*(Run 1's split is the recorded proposals replayed through the new discriminator, since the code at
the time had only one counter. Run 2 is the code computing it live.)*

**The 14 are stable; all the variance is in the other 8.** That is the useful shape of this result.
The `neft_truncated` family is 0/14 in all three runs because the UTR is physically absent from the
narration — no amount of sampling changes that. The `rtgs_no_delimiter` family, where the UTR *is*
present, went 5, then 3, then 4 out of 8.

**So the honest headline is a range, not a number: 3–5 of 22 overall, 38–62% on recoverable data,
across three runs.** Quoting 62% alone would be quoting the better sample, which is exactly the
cherry-picking §7 warns about.

### This breaks determinism, and the invariant needs its boundary stated

Invariant 2 says same seed ⇒ byte-identical `metrics.json`. That holds for the **shipped default**
(rules-only) and for any deterministic adjudicator — both are covered by tests. It does **not** hold
with a live LLM: the response cache is per-run, so a second run re-asks and can get different
answers. Measured here, not theorised.

The fix, if we want it, is to persist the cache across runs keyed by the narration hash. Not built —
see D-026 — because the deterministic core is what the demo runs and what the gates measure, and
Increment 6 is protected. What matters is that the boundary is stated rather than discovered by a
reviewer.

### What did NOT vary

Precision, all three runs: **100.00%**. Statement foots, all three. Journal entries posted only for
verified links. Every wrong proposal rejected, three times over, with the model's own accuracy
swinging 38–62% underneath it. **The fence is the part that does not move**, and that is the claim
worth making — not the extraction rate.

### Open question for review

~~Should `blocked_hallucination` split?~~ **Approved and done, 01 Sep 2026 — see D-025 and the
addendum above.**

### FLAGGED FOR THE INCREMENT 6 VIDEO SCRIPT — LEAD WITH THIS

> ## "Quoting 62% alone would be quoting the better sample."
>
> **This is the moment the video opens on.** We ran the held-out evaluation, got **5 of 22**. We
> re-ran it to make the artifacts match, and got **3 of 22**. Then a third run: **4 of 22**. Same
> data, same prompt, same model.
>
> **We reported the range.** Not the first number, not the best number — 38–62% on recoverable
> data, across three runs. The temptation to quote 62% and move on is exactly the failure §7 warns
> about, and resisting it is the point.
>
> And underneath a model swinging by 24 points, **linkage precision was 100.00% in all three runs.**
> The fence never moved. That is the system working: the LLM is allowed to be unreliable, because
> nothing it proposes reaches the ledger without an exact-lookup verification it cannot talk its way
> past.

Supporting beats, in order:

1. **The system distinguished "the model was wrong" (3–5) from "the answer was not recoverable"
   (14).** The `neft_truncated` narrations have the UTR physically cut out of them at 40 characters —
   nobody can recover it, and the model was *right* to return only what was there. Rejecting it was
   still correct; calling it a hallucination was our error, and we fixed the counter (D-025). Same
   judgment Tier 0 already applies to a duplicated UTR (D-014, D-023), sharpened one level.
2. **The LLM is never consulted on the dev seed at all** — the regex parses 100% of it, so zero calls
   are made. It is asked only where determinism fails, which is the argument for where an LLM belongs.
3. **Smallest model that does the job** (`claude-haiku-4-5`), one narrow job, every output verified.
   An oversized model on a narrow job is the same mistake as an LLM doing arithmetic, one level up.
4. Closing frame: *we gave the LLM the one job it is suited for, on the smallest model that does it,
   and then measured it against an adversary, against a held-out set, and against itself.*

---

## Adversarial audit — six fixes · 01 Sep 2026

An external adversarial read of the shipped submission — docs against the actual rows in
`data/generated/**` and `out/**`, not against the summary tables. It found **three load-bearing false
or unmeasured claims in shipped documents**. Not polish: two of them were sentences in the README, the
architecture doc and the video script that the repo's own data files contradicted.

CLAUDE.md says not to reopen a closed increment "unless it's a real problem". These qualified, so
Increments 1–3 were reopened on 01 Sep. Every number below is re-measured; nothing above this line
was edited.

### What was wrong, and what it is now

| | before | after |
|---|---|---|
| **eval — settlements reported MISSING that had arrived** | **21 of 22** | **0** |
| eval — exception queue precision | 73.60% | **92.89%** (183/197) |
| dev — exception queue precision | 89.35% | **94.61%** (193/204) |
| dev — `CHARGEBACK_UNLINKED` raised / real | 17 / 5 | **5 / 5** |
| eval — `CHARGEBACK_UNLINKED` raised / real | 13 / 4 | **4 / 4** |
| **eval — explanation rate** | **0.00%** | **83.33%** (20/24) |
| eval — settlement coverage | 0.00% | **90.91%** (20/22) |
| eval — linkage recall | 99.40% | **99.97%** |
| **bank refs leaking the settlement UTR** | **22 of 24** | **0 of 24** |
| queue precision measured at all | **never** | published per seed, per code |
| linkage precision per grain | not published | published — bank grain **20/20** |
| LLM calls needed on eval | 22 | **2** |
| **LLM contribution over the deterministic tiers** | claimed 3–5 of 22 | **zero** |

Unmoved, and checked rather than assumed: **false clear in remit 0/192 dev, 0/184 eval**; detection
recall 100.00% on both; linkage precision 100.00%; decomposition closure 100.00% on both; statement
foots on both; determinism byte-identical across two runs and a regeneration on both seeds.

### The three real problems

**RP-1 — the queue told treasury that Rs 33 lakh never arrived. It had.** On the held-out seed no
narration parses, so no credit is linked, so all 22 settlements were reported `MISSING_BANK_CREDIT`.
Exactly one was real; the other 21 credits were sitting in `bank.jsonl`. And **no published metric
could see it**, because the suite measured false clear with real rigour and never measured false
alarms at all. Fixed by FIX-2 (measure it) and FIX-3 (stop asserting it).

**RP-2 — a two-field exact join reproduced the whole result, with no model.** `(amount, value_date)`
resolves 20 of 24 held-out credits to exactly one settlement. The resolver was ignoring two columns
it had already loaded, reporting 0% explanation, and crediting an LLM with 3–5 of 22. Fixed by FIX-4.

**RP-3 — "the UTR is physically cut out of the statement" was false as shipped.** Every bank row's
own primary key was `bc_<utr>` — the full UTR, one field from the narration it was supposedly absent
from. 22 of 24 leaked it. Three shipped sentences, the `blocked_unverifiable` counter and the LLM
headline's denominator of 8 all rested on it. Fixed by FIX-5.

### The ablation, re-measured — this is the headline change

| Cumulative | dev | eval (held out) |
|---|---|---|
| T0 · narration only | 0.00% (0/24) | 0.00% (0/24) |
| + T1 · arithmetic | **83.33%** (20/24) | 0.00% (0/24) |
| + T2 · (amount, date) corroboration | 83.33% | **83.33%** (20/24) |
| + T3 · LLM | 83.33% | **83.33% — adds nothing** |

Live, post-fix, with a real key: the adjudicator is now asked **2 questions instead of 22**, because
corroboration placed the other 20 first. It returned 0 hallucinations, 2 unverifiable, and moved the
explanation rate by **zero**.

**That is a better submission than the one it replaces.** We went looking for the LLM's job, found a
deterministic rule that does it better on our own data, published the comparison, and cut the model
back to the residue nothing else could place — where it also added nothing. The previous story
credited a model for work two columns were already doing.

### What this does not prove

Corroboration works this well partly because the generator is clean: `derive_bank` copies the
settlement's amount and date straight through, and a 4-day cycle gives one settlement per date. A
real statement nets bank charges out of the credit, batches across dates, and settles daily. Said in
`ARCHITECTURE.md` §4 and in the Tier 2 module docstring rather than left to be found.

### Also fixed, surfaced by the work rather than by the audit

An **empty** answer from the adjudicator was being counted as a hallucination — while the prompt
explicitly tells the model an empty string is correct when no UTR is present. Abstention is not
invention; counting it as such punishes the behaviour we asked for and inflates a number we publish
about the model. Found when a *perfect oracle* scored a hallucination after FIX-5 removed the tell it
had been exploiting.

### Still open, deliberately

`DUPLICATE_PAYMENT` is now the largest remaining false-alarm source (10 dev, 14 eval): Tier 0 flags
**both** lines of a duplicated pair because it cannot tell which is the copy, and truth marks one.
That is a defensible design choice, documented in `tier0.py`, and it is now *visible* rather than
invisible — which is what FIX-2 was for. Collapsing the pair into a single record naming both lines
would drop false alarms to near zero and is the obvious next candidate.

FIX-10 (a third seed on a different rate card) remains declined per D-024, and nothing in the audit
weakened that reasoning.


---

## Realism increment — C-4(i): the identities that could not fail · 02 Sep 2026

**Why this increment exists.** A principal-level review asked whether "the LLM adds nothing" is a
fact about reconciliation or an artifact of the generator, and scoped the answer to the realism gaps
**already acknowledged** in `ARCHITECTURE.md` §4. No new sources of ambiguity, and no change whose
justification is "this would give the LLM something to do". §4 nominated one item itself as the
highest-value remaining generator work, and this is it.

**One measurement taken first, because it reframes the question.** The oracle adjudicator — a perfect
extractor built from ground truth — is the **upper bound on any model**, and it needs no API key
(there is none in this environment). Before any change:

| oracle headroom, credits a perfect extractor adds over the deterministic tiers | dev | eval |
|---|---|---|
| before this increment | **0 of 24** | **1 of 24** |

So the published "+T3 LLM adds nothing" was measured against a live model that returned nothing
usable; the stronger available statement was that **the ceiling was one credit and the model captured
none of it**. That one credit exists only because of an injected `DUPLICATE_UTR`, which Tier 2 refuses
as a tie.

### The change

`settlements.jsonl` is a separate endpoint from the recon line items (D-003), so the two are read at
different instants. An extract taken while a line is still posting carries a total struck **before**
that line. Two settlements per seed now report such a total. Only the derived entity view goes stale:
the line items and the bank credit follow the money that actually moved, because a reporting lag does
not change what the bank paid.

This is the ordinary cause of a real rollup break, and it is the sentence Tier 0's hypothesis text has
been offering since Increment 0 — *"Either a line item is missing from the report or the total is
stale"* — with no data able to trigger it.

### It found a live defect within minutes. See F-016.

Tier 1 was silently dropping the bank tie-out conjunct that Tier 0 applies, and **posting journal
entries for settlements whose own report contradicted the bank**. Two on dev, at Rs 2,238.57 and
Rs 3,121.71. The suite stayed green throughout; the tell was that `decomposition closure` fell to
20/22 while the headline did not move at all, and those two facts cannot both be right.

The defect had been live since Increment 2 and was **undetectable by construction** — no generated
data could make the tie-out fail. An identity that cannot fail is not a passing test.

### Measured, after the injection and the F-016 fix

| | dev | eval (held out) |
|---|---|---|
| Explanation rate · settlement coverage | 83.33% (20/24) · 90.91% (20/22) -> **75.00% (18/24) · 81.82% (18/22)** | 83.33% (20/24) · 90.91% (20/22) -> **79.17% (19/24) · 86.36% (19/22)** |
| Decomposition closure | 100.00% (22/22) -> **90.91% (20/22)** | 100.00% (22/22) -> **90.91% (20/22)** |
| Journal entries, all balanced | 20 -> **18** | 20 -> **19** |
| Statement foots | **YES** | **YES** |
| Exception detection recall | 100.00% (194/194) | 100.00% (186/186) |
| **False clear, in remit** | **0.00% (0/194)** | **0.00% (0/186)** |
| Linkage precision | 100.00% (3,388/3,388) | 100.00% (3,507/3,507) |
| Exception queue precision | 94.61% -> **94.66% (195/206)** | 92.89% -> **92.96% (185/199)** |
| Determinism, two runs | byte-identical | byte-identical |
| Tests | **188 passed** | — |

Every headline number moved **down**, and that is the increment working. The system was previously
claiming to have explained two settlements per seed that it had not.

### The two link paths fail differently, and that is a result

The same anomaly produces two completely different failures depending on which tier established the
link:

- **UTR path (dev).** The settlement is linked, the residual closes, and the tie-out is the only thing
  standing between it and the ledger. Before F-016 nothing was standing there at all.
- **Corroboration path (eval).** Tier 2 keys on `(amount, value_date)` where `amount` is the
  **reported** total. A stale total means the key no longer matches its own credit, so the settlement
  is **never linked** — silently. Tier 0 at least raises `ROLLUP_MISMATCH`; Tier 2 just finds nothing.

Tier 2's key is built from a field that can be wrong, and when it is wrong the tier fails quietly.
That is worth saying out loud next to the claim that corroboration reproduced the whole result.

### Prediction 1, as registered before the work

> "Decomposition closure drops below 100% by exactly the number injected, ROLLUP_MISMATCH fires for
> the first time on real data, LLM contribution unchanged at zero."

All three held. The prediction was **incomplete rather than wrong**: it said nothing about the
headline, and the headline not moving on dev was the defect. Recorded because a prediction that is
right about everything it mentions and silent about the thing that breaks is not a success.

### What this did to the LLM's ceiling — measured, both directions

| oracle headroom (explanation) | dev | eval |
|---|---|---|
| before | 0 of 24 | 1 of 24 |
| after | **0 of 24** | **0 of 24** |

The ceiling went **down**, not up: the one credit a perfect extractor could previously add is still
linkable, but is no longer explainable, because the tie-out now correctly withholds it.

**At the linkage grain the ceiling went up, and this is the first time in this project that an
extractor can do something no deterministic tier can:**

| eval, linkage recall | rules only | + perfect extractor |
|---|---|---|
| before this increment | 99.97% (3,508/3,509) | 99.97% |
| after | 99.94% (3,507/3,509) | **100.00% (3,509/3,509)** |

The stale totals cost Tier 2 exactly two links, and only extraction recovers them — because the UTR
is the one reference that does not depend on any amount being right. **That is the real-world argument
for the UTR, arriving as a measurement rather than as an assertion.**

It does **not** move the headline: those two links convert to zero additional explained settlements,
because the report still contradicts itself and nothing posts. Both halves get published together —
an extractor buys linkage here, and linkage is not the job.

Whether a real model captures those two links is **unmeasured**: no `ANTHROPIC_API_KEY` in this
environment. The oracle is an upper bound and is labelled as one, exactly as at Increment 3 (D-022).


---

## Realism increment — C-2(b): failed settlements · 02 Sep 2026

**The gap, as named in `ARCHITECTURE.md` §4:** *"all `status: processed`, no failed or reversed
settlements"*. `derive_settlement_entities` hard-coded `"processed"` on every row. The field was
loaded, printed inside Tier 0's evidence, and **never decided on** — so the one fact a real settlement
report gives you about why a credit is absent was being thrown away.

**Why it matters, in one sentence.** A failed settlement and a missing credit are *identical* in the
bank statement — neither has a row — and they are opposite findings. One says the gateway told us the
transfer did not complete, and the analyst chases beneficiary details. The other says the money left
and never landed, and the analyst chases the bank. Reporting the first as the second is F-014 one step
along: asserting more than the evidence supports.

One settlement per seed now carries `status: failed` and no credit, drawn from the **last quarter** of
the window so that "not yet re-settled" is the honest reading. Modelling the re-issue would put the
same underlying sales under two settlement ids — a real shape, but a much larger change than the gap
named, and outside the boundary this increment was given.

`SETTLEMENT_FAILED` is declared (D-013's rule: a code is declared only once the generator can produce
it), is a **break** — money that should be in the bank is not — and is **resolvable**, because unlike
`REFUND_ORPHANED` the evidence is in the extract. Tier 0 checks `status` *before* either weaker claim,
since `MISSING_BANK_CREDIT` and `SETTLEMENT_UNCONFIRMED` are both inferences from absence and this is
a fact the report states. Its queue entry routes to treasury with a different action.

### It broke two invariants on the held-out seed. See F-017.

Tier 2 corroborated a credit against a settlement whose status was `failed` — the same settlement
Tier 0 had just queued as `SETTLEMENT_FAILED` in that run. False clear in remit went to **0.53%
(1/187)** and linkage precision to **99.97%**, both for the first time in the project's history. Dev
stayed clean, so it was visible on one seed only (F-009's shape).

Two causes, and only one of them was about synthetic data:
- the injectors composed into a world that cannot exist — a duplicate posting of a transfer that never
  happened (my bug, fixed);
- **Tier 2's candidate pool never consulted `status`** — a real defect that a real statement would
  expose just as readily (fixed).

### Measured, after the fixes

| | dev | eval (held out) |
|---|---|---|
| Explanation rate · settlement coverage | 18/24 · 18/22 -> **17/23 (73.91%) · 17/22 (77.27%)** | 19/24 · 19/22 -> **18/23 (78.26%) · 18/22 (81.82%)** |
| Money-weighted coverage | **77.06%** | **82.16%** |
| Exception detection recall | **100.00% (195/195)** | **100.00% (187/187)** |
| **False clear, in remit** | **0.00% (0/195)** | **0.00% (0/187)** |
| **Linkage precision** (bank grain) | **100.00%** (19/19) | **100.00%** (18/18) |
| Exception typing accuracy | **100.00%** | 98.93% (185/187) |
| Exception queue precision | 94.66% -> **94.69% (196/207)** | 92.96% -> **93.00% (186/200)** |
| `MISSING_BANK_CREDIT` raised / real | 1 / 1 | 0 / 0 |
| `SETTLEMENT_FAILED` raised / real | **1 / 1** | **1 / 1** |
| Journal entries, all balanced | 17 | 18 |
| Statement foots | **YES** | **YES** |
| Determinism, two runs | byte-identical | byte-identical |
| Tests | **192 passed** | — |

The bank-credit denominator drops 24 -> 23 on both seeds: a failed settlement produces no credit, so
there is one fewer row in the statement. The headline falls accordingly, and correctly.

### Prediction 2, as registered before the work

> "Failed settlements produce settlements with no credit that are correctly *not* breaks. Queue
> precision improves; LLM unaffected."

**Two parts wrong, one right, and the wrong parts were the useful ones.**

1. **"correctly *not* breaks" was wrong, and I changed the design rather than the prediction.**
   A failed settlement *is* a break: money that should be in the bank is not, and someone must act.
   What differs from `MISSING_BANK_CREDIT` is the evidence and the action, not the severity. Declaring
   it informational would have understated a real cash shortfall to make a number look tidy.
2. **It said nothing about interactions, and the interaction was the whole event.** A new anomaly
   class composed with an existing one to produce an impossible world, which then exposed a live gap
   in Tier 2's candidate rule. Prediction 2 reasoned about the new class in isolation; anomalies do
   not arrive in isolation.
3. Queue precision did improve on both seeds, and the LLM contribution was unaffected. That part held.

### The LLM's ceiling, re-measured

| oracle headroom (explanation) | dev | eval |
|---|---|---|
| before this increment | 0 of 24 | 0 of 24 |
| after | **0 of 23** | **0 of 23** |

Unchanged at zero. At the **linkage** grain the oracle still recovers what the deterministic tiers
cannot: eval bank-grain edges go **18 -> 20** with a perfect extractor, because a stale total breaks
Tier 2's key and only the UTR is independent of every amount being right. Those two links still
convert to **zero** additional explained settlements, and both halves are published together.

Still unmeasured with a real model: no `ANTHROPIC_API_KEY` in this environment (D-022).

---

## Realism increment — C-2(a): the bank value date · 02 Sep 2026

**The gap.** BRIEF §3.4 lists `created_at ≠ settled_at ≠ bank value date` as one of the two structural
difficulties of this domain. `derive_bank` wrote `settled_on` straight into `value_date`. The bank
statement was restating the gateway's own date, which is a property no statement has.

A credit now posts on the settlement date or the next business day, and never on a weekend. Measured
drift between `settlement.created_at` and `bank.value_date`, in calendar days:

| drift | dev | eval |
|---|---|---|
| 0 days | 9 | 4 |
| 1 day | 8 | 8 |
| 2 days | 1 | 4 |
| 3 days | 1 | 2 |

Weekend value dates: **0**. Dates carrying more than one credit: **2 on dev, 1 on eval** — so "no
same-day multiples", the other half of the C-2 caveat, is closed as a side effect of the same
mechanism rather than by forcing it.

### Guard (D) was built first, and deliberately

The tier-prefix differential (ARCHITECTURE §3b) was in place **before** this change was written,
because C-2(a) is exactly the kind of edit that produced F-016 and F-017: new linking logic in a tier
that sits above another tier's conclusions. It was validated by re-introducing F-017 rather than by
reasoning about it — with both fixes reverted and the seeds regenerated it fails with
`eval: tier 2 silenced 1 real break(s) that tier 1 had flagged: ['bc_1582830180d']`.

**It did not fire during C-2(a) development.** Reported because a guard that never fires is worth
exactly as much as its validation, and no more.

### The collapse, measured before it was repaired

This is the number the whole increment exists to produce. With the value dates made realistic and
Tier 2 **unchanged**:

| | dev | eval (held out) |
|---|---|---|
| Explanation rate | 17/23 (unchanged) | **18/23 → 4/23** |
| Settlement coverage | 17/22 (unchanged) | **18/22 → 4/22** |

Tier 2's exact `(amount, value_date)` join lost **14 of 18 links** on the held-out seed. Dev is
untouched because dev links by UTR at Tier 0 — the narration parses there. So the audit's headline
finding of 01 Sep, that a two-field exact join reproduced the entire result, **rested entirely on
`derive_bank` copying one field**. That is an artifact, and it is now measured as one.

### The repair, and what it reveals (D-033)

Tier 2 now requires the amount to match **to the paise** and the value date to fall inside
`[created_at, +BANK_POSTING_WINDOW_DAYS]`, uniqueness still required both ways, every tie still
refused. A window on a date is a statement about settlement mechanics; a tolerance on money would be a
score, and there is still none — a test shifts every credit by one paise and asserts Tier 2 drops to
zero links.

| eval, held out | before C-2(a) | date drift, T2 unchanged | + windowed rule |
|---|---|---|---|
| Explanation rate | 18/23 | **4/23** | **18/23** |
| Linkage precision | 100.00% | 100.00% | **100.00%** (18/18 bank grain) |

**Full recovery — and the recovery is the finding.** What carries corroboration is the *amount*, not
the date: 22 of 22 settlement amounts are distinct on both seeds, the two closest **Rs 171.98** apart.
A mixed merchant's daily net settlement is an effectively random paise value, so that uniqueness is a
real property of settlement flows rather than an artifact of the simulator — which is also why C-1 was
withdrawn rather than closed (D-034).

### Measured, both seeds, after C-2(a)

| | dev | eval (held out) |
|---|---|---|
| Explanation rate · settlement coverage | **73.91% (17/23) · 77.27% (17/22)** | **78.26% (18/23) · 81.82% (18/22)** |
| Linkage precision (bank grain) | **100.00%** (19/19) | **100.00%** (18/18) |
| Exception detection recall | **100.00%** (195/195) | **100.00%** (187/187) |
| **False clear, in remit** | **0.00%** (0/195) | **0.00%** (0/187) |
| Exception queue precision | 94.69% (196/207) | 93.00% (186/200) |
| Journal entries, all balanced | 17 | 18 |
| Statement foots | **YES** | **YES** |
| Determinism, incl. regeneration | byte-identical | byte-identical |
| Tests | **207 passed** | — |

`metrics.json` hashes to the same value it did before C-2(a) on both seeds. The underlying data
changed materially — every credit's value date moved — and the measured outcome did not. The windowed
rule reaches the same 17 and 18 settlements by a different route.

### Prediction 3, as registered before any of this work

> "Tier 2's shipped rule collapses to ~0; under the windowed rule it recovers to ~20, because amount
> alone is decisive (22/22 distinct, Rs 172 minimum gap). **LLM contribution stays at zero.**"

**Right on all three counts**, including the mechanism. The collapse was to 4 rather than 0 — four
credits happened to post same-day and still matched exactly — and the recovery was to 18 rather than
~20 because C-4(i) and C-2(b) had already removed two settlements from the reachable set for
unrelated and correct reasons.

### The LLM's ceiling after every closed gap

| oracle headroom (explanation) | dev | eval |
|---|---|---|
| start of increment | 0 of 24 | 1 of 24 |
| after C-4(i) | 0 of 24 | 0 of 24 |
| after C-2(b) | 0 of 23 | 0 of 23 |
| **after C-2(a)** | **0 of 23** | **0 of 23** |

A **perfect** extractor — the upper bound on any model, measurable with no API key — adds **zero
explained credits** on either seed, at every stage of this increment. It never rose above one.

At the **linkage** grain it is not zero: the oracle takes the held-out bank grain from **18 to 20**,
recovering the two settlements whose stale totals put them beyond any amount-based rule. Those two
links convert to **zero** additional explained settlements, because the report still contradicts
itself and nothing posts. Both halves are published together, because the first without the second
would overstate what extraction buys.

---

## Review response — items 1, 3, 4 · 02 Sep 2026

An external senior review (acting as a Razorpay technical evaluator) scored the repo **81/100** and
named one clear gap: the adjudicator has never been validated against the live API in its corrected,
post-C-2(a) form. Four items were assigned; this entry records the three that do not need a key.

### 1 — Pushed

11 commits to `origin/main`. Remote HEAD `bc46d91` verified against `git ls-remote`, not against the
cached tracking ref.

### 2 — BLOCKED, not done, and nothing stale was edited

`python -m recon ablation --seed eval` reports **`adjudicator unavailable: no ANTHROPIC_API_KEY in the
environment`**, so its second column is the degraded path: **0 adjudicator calls, `degraded: True`**.
That is not a model result and is not published as one. The stale 5/3/4-of-22 citations are left in
place with their existing "superseded run" labels, because replacing measured figures with
degraded-path zeros would be worse than leaving them.

*(`--llm` is not a flag on `ablation`. That subcommand exists to compare with and without the
adjudicator, so it always attempts one; the flag applies to `run`, `demo` and `eval`. README corrected.)*

**A correction to the review's framing, worth stating before the key is spent.** The review said the
denominator should be 23 rather than 24. That is right for *bank credits* and wrong for the
adjudicator, whose denominator moved for a different reason:

| | at the 5/3/4-of-22 run | today |
|---|---|---|
| Credits the adjudicator is asked about | 22 | **3** |
| Why | no narration parsed, so every credit went to Tier 3 | Tier 2 places 18 first; only the residue is asked |
| Oracle ceiling, explanation | 1 of 24 | **0 of 23** |
| Oracle ceiling, linkage | — | **2 edges** (the stale-total settlements) |

So the live run produces a number out of **3**, and a *perfect* extractor scores zero additional
explained credits on them. The question worth buying an API call for is therefore not "what does the
LLM add" — the oracle already answers that — but **"does a real model reach the ceiling the oracle
sets", i.e. does it recover the two stale-total links.**

### 3 — The pair artifact in queue precision (D-035)

DUPLICATE_PAYMENT is raised on **both** lines of a pair because at detection time nothing
distinguishes the copy from the original, and an analyst needs both rows to decide which to reverse.
Truth labels one, so the other scores as a false alarm. Measured, not assumed:

| | dev | eval |
|---|---|---|
| DUPLICATE_PAYMENT raised | 20 | 28 |
| …truth-labelled (scored real) | 10 | 14 |
| …scored as false alarms | 10 | 14 |
| **…of those, the other half of a genuine pair** | **10 of 10** | **14 of 14** |
| **…spurious, with no duplicate behind them** | **0** | **0** |

**We kept the conservative headline and published the split**, rather than rescoring. Collapsing pairs
would move dev to 99.49% and eval to **100.00%** — a change whose only effect is to improve our own
number, adopted after seeing that it does, which is the F-005 failure. It is also strictly less
sensitive: under it, flagging the *wrong* half of a pair would still score as a correct detection.
Both figures are now in `metrics.json` and in the run output, stricter one first. Full reasoning and
the rejected option in **D-035**.

The claim "every such alarm is a genuine pair half" is now a **test**, not a sentence, so it fails
loudly if real queue noise ever arrives wearing the artifact's clothes.

### 4 — README restructured

The measured table now opens the file, above all prose: headline rates, the ablation, throughput,
determinism and test count inside the first screen. Three reading notes sit under it — why the numbers
went *down* on 02 Sep, what queue precision absorbs, and why the headline is never a single number.

### Measured after items 3 and 4

| | dev | eval (held out) |
|---|---|---|
| Explanation rate · coverage | 73.91% (17/23) · 77.27% (17/22) | 78.26% (18/23) · 81.82% (18/22) |
| Exception queue precision | **94.69%** (196/207) | **93.00%** (186/200) |
| …pairs collapsed *(secondary)* | 99.49% (196/197) | 100.00% (186/186) |
| False clear, in remit | **0.00%** (0/195) | **0.00%** (0/187) |
| Linkage precision | 100.00% | 100.00% |
| Statement foots | YES | YES |
| Determinism, incl. regeneration | byte-identical | byte-identical |
| Tests | **211 passed** | — |

No metric moved as a result of items 3 or 4. Two were added; none was changed.

---

## PRE-REGISTERED PREDICTION — second-gateway credits on eval · 02 Sep 2026

**Written before any code was touched.** The hypothesis under test: *does the LLM's ceiling rise if
the held-out seed contains same-day, amount-proximate credits from a second gateway?* This is a
timeboxed experiment, not a feature commitment, and the prediction is recorded first so the result
cannot drift toward the interesting answer.

### The prediction: NO. The ceiling does not rise. I expect it to stay at 1.

Not a hedge — this follows from the code rather than from intuition, so it is sharply falsifiable.

**The mechanism, traced through `tier2.resolve` rather than assumed.** Tier 2 requires the amount to
match **to the paise**, then filters by the posting window, then requires uniqueness both ways:

- For a **second-gateway credit** of amount B: `candidates` are settlements whose amount is *exactly*
  B. An amount-*proximate* credit (B ≈ A, B ≠ A) matches nothing, so it is skipped without even
  counting as ambiguous. It cannot produce a wrong link.
- For a **gateway-1 settlement** of amount A: `rival_credits` are credits of amount *exactly* A inside
  its window. A proximate credit is not a rival, so it cannot break an existing link either.

**Exactness is immune to proximity.** Same-day, near-miss credits therefore change nothing about
which settlements Tier 2 places, which means the LLM is handed no work it could not already have had.

The only way the ceiling rises is an **exact-to-the-paise** amount collision inside a settlement's
posting window, which would refuse that settlement's link as a tie and leave the UTR as the only route
to it. By chance that is essentially impossible: 22 of 22 settlement amounts are distinct on this seed
and the two closest are **Rs 171.98** apart, on values around Rs 1.5 lakh. To get a collision I would
have to set a second-gateway amount equal to a gateway-1 settlement's amount **deliberately** — and
that is manufacturing the ambiguity, not modelling a merchant. I will not do it, and if the result
comes back showing a risen ceiling, the first thing to check is whether the generator accidentally
did.

### What I predict DOES change

| | prediction |
|---|---|
| Oracle ceiling (recoverable credits a perfect extractor adds) | **unchanged at 1** |
| Live model accepted links | **0**, and any acceptance is a defect to investigate, not a win |
| Adjudicator calls | **rises** from 3 to roughly 3 + the number injected, since held-out narrations do not parse |
| `blocked_unverifiable` | rises by about the same amount — every second-gateway UTR is real and resolves to no settlement of ours |
| Explanation rate | **falls**, mechanically: the denominator grows, the numerator does not. ~18/23 becomes ~18/29 if six are injected |
| `UNMATCHED_BANK_CREDIT` raised | rises by the number injected; all real, so detection recall holds |
| False clear, in remit | **stays 0.00%** |
| Linkage precision | **stays 100.00%** |

The explanation-rate fall is the honest arithmetic of a real merchant account: a controller must
account for every credit that lands, including the ones another aggregator sent. It will look like a
regression and it is not one.

### Two costs I want on the record before starting, not after

**1. This makes `eval` structurally different from `dev`, not just a different draw.** Until now both
seeds came from one generator with one config, which is what makes eval a clean held-out sample. A
knob set only on eval means any dev/eval difference is confounded by the knob. For a timeboxed
experiment that is acceptable if stated; it would not be acceptable as a permanent asymmetry, and if
this ships the same shape has to reach dev too.

**2. D-016 cut multi-gateway with reasoning that has not gone away.** It was cut because *building
difficulty in order to give the LLM a job* is the Sec 9 anti-pattern. What makes this experiment
legitimate is that the prediction is registered first and says the ceiling will NOT move — so the
finding is publishable either way. But if the ceiling does rise, the honest sentence is **"it rises
because we added the difficulty that raises it"**, and that must appear next to the number rather than
be left for a reviewer to work out.

### Confidence

High on the Tier 2 reasoning, because it is read off the two uniqueness checks rather than inferred.
Lower on the exact call counts, which depend on how many credits I inject and which narration families
they draw. The falsifiable core is the first row of the table: **oracle ceiling stays at 1.**

### Estimate for the smallest version: ~2h 15m

Under the 3-hour ceiling, so proceeding. Second-gateway credits reuse `ExtraBankCredit`, which already
carries a bank_ref, value date, amount, UTR, narration override and a truth anomaly — most of the
structure exists.

| | |
|---|---|
| Config knob (default 0, so dev is untouched) + injector | 45 min |
| Truth and derive wiring — largely free via `ExtraBankCredit` | 15 min |
| Tests: dates collide, amounts never collide exactly, dev unchanged, determinism | 45 min |
| Full invariant suite, determinism, false clear, both seeds | 20 min |
| RUN_LOG result entry | 30 min |

---

## RESULT — second-gateway credits on eval · 02 Sep 2026

Measured against the pre-registration recorded earlier the same day, which was written before any
code was touched. Every number below is from a run on this machine, not inferred.

Method: `python -m recon eval` with the knob at 6 (29 bank rows), against a knob-off generation of
the same seed into a scratch directory (23 bank rows). The two runs differ **only** by
`second_gateway_credit_count`. The ceiling is the oracle's explanation-rate numerator minus the
rules-only numerator, using the same `_oracle_for` helper `tests/test_tier3_fence.py` uses.

### The falsifiable core: CONFIRMED. The ceiling did not rise.

| | knob off | knob on |
|---|---|---|
| rules-only explanation rate | 18/23 | 18/29 |
| with a perfect extractor (oracle) | 18/23 | 18/29 |
| **ceiling — what the oracle adds** | **0** | **0** |

The mechanism held exactly as reasoned off `tier2.resolve`: Tier 2 keys on `int(amount)` into a dict
built at `tier2.py:120-125`, so an amount-proximate credit hits no key, produces no link, and is not
a rival to any settlement's real credit. **Exactness is immune to proximity**, and same-day
near-miss credits handed the LLM no work it could not already have had.

One correction to the prediction's own baseline: it said the ceiling would "stay at 1". The measured
ceiling was **0 before the change and 0 after**. The hypothesis (does not rise) is confirmed; the
figure quoted for the starting point was wrong.

### Scorecard against the predicted table

| row | predicted | measured | |
|---|---|---|---|
| Oracle ceiling | unchanged | 0 → 0 | **confirmed** |
| Live model accepted links | 0 | 0 (no key; oracle/hostile only) | confirmed, unmeasurable in the real sense |
| Adjudicator calls | 3 → ~3+injected | **3 → 9** | **confirmed exactly** |
| `blocked_unverifiable` | rises by about the same | **1 → 7** | **confirmed** |
| Explanation rate | falls, ~18/23 → ~18/29 | **18/23 → 18/29** (78.26% → 62.07%) | **confirmed exactly** |
| `UNMATCHED_BANK_CREDIT` raised | +6 | **0. Stayed at 2** | **FALSIFIED** |
| False clear, in remit | 0.00% | 0.00% | confirmed |
| Linkage precision | 100.00% | 100.00% (3506/3506) | confirmed |

### The falsified row is the most interesting result here

The prediction assumed a second-gateway credit would be *typed* `UNMATCHED_BANK_CREDIT`. It is not.
All six are raised as `NARRATION_UNPARSEABLE`, `is_break=False`.

The cause is an ordering fact in `tier0._resolve_bank_credits`: the `utr is None` branch
(`tier0.py:401`) fires **before** the settlement lookup (`tier0.py:435`) that raises
`UNMATCHED_BANK_CREDIT`. Second-gateway credits render from held-out narration families, so no UTR is
extracted, and they never reach the branch the prediction expected. The prediction reasoned about
what these credits *are* and ignored the order in which the resolver *discovers* things.

**The resolver is not wrong.** Truth types the credit by its cause — another aggregator's money.
The resolver types it by its observable state — the narration will not parse. Both are correct
descriptions of the same row, and `exception_typing_accuracy` cannot hold both:

| | knob off | knob on |
|---|---|---|
| exception typing accuracy | 98.93% (185/187) | **95.85% (185/193)** |
| exception detection recall | 100.00% (187/187) | **100.00% (193/193)** |

Detection recall is unmoved because `flagged_subjects` keys on `subject_id` regardless of code — every
credit was found. Only the label differs. This was not predicted in either direction and is recorded
as an unforced finding.

### Costs, paid as recorded

Both costs registered in advance were incurred and neither was discovered late. `eval` is now
structurally different from `dev` rather than a different draw of the same generator, so any dev/eval
difference is confounded while the knob is set. D-016's reasoning is untouched.

**The honest sentence, which the pre-registration required in advance: the ceiling did not rise, so
there is no interesting answer to report.** The experiment was run to falsify a claim about the LLM's
value and it failed to falsify it. Manufacturing an exact-to-the-paise collision would raise the
ceiling, and that is precisely the Sec 9 anti-pattern the pre-registration committed not to build.

### Two defects found in the experiment's own code, recorded not fixed

**1. The collision guard is weaker than its docstring.** `_inject_second_gateway` builds its
exclusion set from **true** settlement amounts (`world.py:935`), but Tier 2 indexes on the amount the
settlement entity **reports** (`derive.py:123-125`), and `_inject_stale_totals` runs *after*
`_inject_second_gateway` (`world.py:366-369`). A draw landing on a stale reported total would create
the exact-value collision the guard exists to prevent, and Tier 2 would link it. Not observed on this
seed; the docstring's "never colliding with ANY of our settlement amounts" claims more than the code
delivers.

**2. `_is_faithful_reading` will mis-attribute a real model on this data.** Not measured — the oracle
returns an empty proposal for a ref it has no true edge for, and an empty answer is correctly not a
hallucination (`tier3.py:182-188`), which is why all six landed in `blocked_unverifiable`. But a real
model that *correctly* reads the UTR out of `RTGS CR PAYSWIFT<utr>SETTLEMENT` is followed by more
alphanumerics, so `tier3.py:94-96` would score it `blocked_hallucination`. The bias is documented at
`tier3.py:85-88` and is deliberately the safe direction, but with these narrations present the
published hallucination count would overstate model error. Flagged for the day a key exists.

### Disposition

The implementation is **stashed, not discarded** — the result is now recorded, so the prediction is
closed either way. Nothing about the knob ships: it stays at `0` by default, `dev` is provably
untouched (23 rows, zero `PAYSWIFT`), and the entire test suite constructs `GenConfig` without
`anomalies=`, so no gate condition depends on it.

Elapsed: under the 2h 15m estimate, because the generator work was already done when the result
was measured.
