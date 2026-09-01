# Video script — 5:00 hard cap

Follows BRIEF §11's block structure. Narration is written to be **spoken** at ~140 wpm.

**Budget: ~610 spoken words.** The first draft ran 952 (≈6:48) and was cut 36% — the live run, the
network kill and the pauses need the time more than the prose does. Per-block word budgets are in each
heading; if a take runs long, cut from 1:15–2:45, never from 3:30–4:20.

**Two rules while filming.** Never show a single-number headline — explanation rate and settlement
coverage always appear together (D-005). Never quote 62% without the range.

---

## 0:00–0:35 · The problem, in money terms · *~80 words*

> A controller closing a settlement cycle isn't asking *"which bank credit is this?"* The UTR answers
> that in seconds.
>
> They're asking: **why is this credit short of gross sales, and by exactly what?**
>
> That's never one number. It's MDR, GST on the MDR, a rolling reserve withheld as a receivable,
> refund offsets, chargeback reversals and their separate fees — tangled across a T+2 boundary, with
> many line items rolling into **one lump bank credit**.
>
> Which is why row-to-row matching isn't just inaccurate here. It's **ill-posed**. There's no row on
> the bank side to match against.

**On screen:** three sources side by side; one bank credit fanning out to ~70 line items.

---

## 0:35–1:15 · Architecture: tiers, and why the LLM is fenced · *~90 words*

> So it's a graph of typed edges, not a pipeline over rows. Three cardinalities, each with its own
> denominator — merging them is how you get an indefensible match rate.
>
> **Tier 0** joins on exact keys and checks the identities using the numbers the report *states*.
> **Tier 1** is the first tier with a second, independent opinion — a contracted rate card — so it can
> type a rolling reserve and tell you the gateway overcharged you.
>
> **Tier 3 is the LLM, and it has one job:** read a UTR out of a narration no parser was written for.
> It never picks between settlements, never explains a residual, never touches an amount.
>
> This is a deterministic pipeline with a fenced adjudicator, and we say so.

**On screen:** the tier table; highlight the Tier 0 / Tier 1 boundary.

---

## 1:15–2:45 · Live run on the held-out batch, and one exception · *~145 words*

**Run `python -m recon eval` on camera. Let it breathe — the run is ~1 s, the reading is the content.**

> Held-out seed: a different world *and* narration templates the parser has never seen. Three and a
> half thousand records, a quarter of a second, statement foots to zero.
>
> The queue is sorted by **cash at risk** — finance triages by money, not row count.

**Drill into the top entry.**

> Top of the queue: **Rs 1,63,318**. A settlement processed on 13 June, and **no bank credit anywhere
> carrying that UTR**.
>
> The evidence isn't a score — it's two checkable facts: the settlement's own status and UTR, and
> *"no narration among 24 bank credits yielded this UTR."* The action is deliberately careful:
> **confirm it isn't still in transit** before calling it missing.
>
> And notice what it's attached to. There's no edge — the credit doesn't exist. An unmatched unit is
> the **absence** of an edge, and absence carries no evidence. That's the most common break shape in
> real reconciliation.

**Scroll to an `MDR_SLAB_MISMATCH`.**

> One only Tier 1 can see: charged **Rs 165.84** where the contracted slab gives **Rs 110.55**. The
> report is internally consistent — it just disagrees with the contract.

---

## 2:45–3:30 · The ablation · *~115 words*

> **Tier 0 alone explains zero percent of bank credits on realistic data.** That's the finding, not a
> regression — it knows nothing about a rolling reserve.
>
> Add Tier 1: **83% explanation rate, 91% settlement coverage.**
>
> On the held-out seed the regex extracts **nothing**. So we measured the arithmetic without linkage:
> **100% on both seeds.** The held-out failure is *entirely* narration parsing — which is exactly where
> we pointed the LLM.

**Slow down. This is the beat.**

> We ran the held-out evaluation. Got **five of twenty-two**. Re-ran it to make the artifacts match —
> got **three**. Third run: **four**.
>
> **We're reporting the range. Three to five. Thirty-eight to sixty-two percent on recoverable data.**
>
> **Quoting sixty-two alone would be quoting the better sample.**
>
> And underneath a model swinging twenty-four points, **precision was one hundred percent in all three
> runs.** The fence never moved.

**On screen:** the three-run table, precision row highlighted. Hold through the pull-quote.

---

## 3:30–4:20 · Failure recovery: kill it mid-run · *~85 words*

**Runbook — rehearse once before filming.**

```bash
export ANTHROPIC_API_KEY=$(cat ~/.anthropic_key)
export ANTHROPIC_WORKSPACE_ID=$(cat ~/.anthropic_workspace)
python -m recon eval --llm          # 22 calls, ~2 s each, ~45 s total
```

Around call 8–10 (~20 s in), **disable the network adapter on camera.** Don't stop the process.

> I'm taking the network away mid-run.
>
> *[kill it — let the silence run]*
>
> It doesn't crash and it doesn't hang. The remaining calls fail, each one counted, and the batch
> **completes**. Statement still foots. Precision still one hundred percent. And it reports
> **degraded**, with the reason attached.
>
> This has been the default path since day one — there was no adjudicator for the first three
> increments, so every run was already a degraded run. Recovery wasn't bolted on at the end. The LLM
> was the thing added later.

**On screen:** the MODE block — `degraded: True`, `calls_declined`, statement still footing.

---

## 4:20–5:00 · The honest exception list · *~95 words*

> The queue separates **breaks** from **explained-but-notable**. A withheld rolling reserve isn't a
> break — it's a receivable. Conflating them inflates your exception count and understates the system.
>
> Now the class we **cannot** solve. A refund whose original payment predates this extract. We detect
> it every time; we can **never** resolve it, because the payment isn't in the data. Not with a better
> model.
>
> The same shape appeared in the live run from the other direction: fourteen of those twenty-two
> narrations have the UTR **physically cut out** at forty characters. The model returned what was
> there — it was **right**. We'd been counting those as hallucinations, which overstated model error
> fivefold. So we split the counter.
>
> **"The model was wrong" and "the answer wasn't recoverable" are different findings.**
>
> One deep loop, measured honestly — including the parts that didn't work.

**On screen:** the queue with `is_break` visible, then the repo URL.

---

## Pre-flight checklist

- [ ] `pytest` green (168) on the machine being filmed
- [ ] `demo` and `eval` both clean from a fresh clone
- [ ] **Rehearse the network kill** — confirm ~20 s lands mid-batch
- [ ] Terminal font large enough to read queue entries
- [ ] Explanation rate and settlement coverage visible **together** in every metrics frame
- [ ] Three-run table on screen for the whole pull-quote beat
- [ ] Time a full read-through before filming — the first draft was 36% over
