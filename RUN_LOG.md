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
