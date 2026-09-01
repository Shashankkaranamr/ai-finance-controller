# Video script — 5:00 hard cap

Follows BRIEF §11's block structure. Narration is written to be **spoken** at ~140 wpm.

**Budget: 620 spoken words ≈ 4:25, leaving ~35 s for the live run, the network kill and pauses.**

Budget arithmetic: 4:25 spoken, plus ~15 s of silence for the network kill and ~10 s watching the
run land — about 4:50 against a 5:00 cap.

Getting here took four drafts, and the reason is worth one line: draft 1 ran 952 words (6:48), draft 2
*claimed* 610 and measured 745, draft 3 measured 719, draft 4 hit 4:58 with two seconds of headroom —
which is not under the cap in any real sense. Every per-block count below is **generated from the
text**, not estimated. If a take runs long, cut from 1:15–2:45; never from 3:30–4:20.

**Two rules while filming.** Never show a single-number headline — explanation rate and settlement
coverage always appear together (D-005). Never quote 62% without the range.

---

## 0:00–0:35 · The problem, in money terms · *69 words*

> A controller closing a settlement cycle isn't asking *"which bank credit is this?"* The UTR answers
> that in seconds.
>
> They're asking: **why is this credit short of gross sales, and by exactly what?**
>
> Never one number — MDR, GST, rolling reserve, refund offsets, chargebacks, tangled across a T+2
> boundary, with many line items rolling into **one lump bank credit**.
>
> Which is why row-to-row matching here isn't inaccurate. It's **ill-posed**.

**On screen:** `docs/architecture.svg`, full frame. Hold on the left two thirds — the three
source boxes and the fan of ~70 line items converging on one settlement, then one bank credit.
The red callout lands exactly on the word *ill-posed*. Do not show the tier panel yet; it is the
next block's visual.

---

## 0:35–1:15 · Architecture: tiers, and why the LLM is fenced · *92 words*

> So it's a graph of typed edges — three cardinalities, each with its own denominator. Merging them is
> how you get an indefensible match rate.
>
> **Tier 0** checks identities using the numbers the report *states*. **Tier 1** is the first tier with
> a second, independent opinion — a contracted rate card — so it types a rolling reserve, and catches
> the gateway overcharging you.
>
> **Tier 3 is the LLM, with one job:** read a UTR out of a narration no parser was written for. Never
> picks between settlements, never touches an amount.

**On screen:** same diagram, now pan right to the tier panel and the strip along the bottom —
*T0 links it · T3 links it when the narration defeats the parser · T1 explains the money*.

---

## 1:15–2:45 · Live run on the held-out batch, and one exception · *136 words*

**Run `python -m recon eval` on camera. Let it breathe — the run is ~1 s, the reading is the content.**

> Held-out seed — a different world *and* narrations the parser has never seen. Three and a half
> thousand records, a quarter of a second, statement foots to zero.
>
> The queue sorts by **cash at risk**. Finance triages by money, not row count.

**Drill into the top entry.**

> **Rs 1,63,318**. Processed 13 June, **no bank credit carrying that UTR**.
>
> The evidence isn't a score — two checkable facts: the settlement's status and UTR, and *"no narration
> among 24 bank credits yielded this UTR."* The action is careful on purpose: **confirm it isn't still
> in transit** before calling it missing.
>
> And notice what it attaches to. There's no edge — the credit doesn't exist. An unmatched unit is the
> **absence** of an edge, and absence carries no evidence.

**Scroll to an `MDR_SLAB_MISMATCH`.**

> One only Tier 1 can see: charged **Rs 165.84** where the contract gives **Rs 110.55**.

---

## 2:45–3:30 · The ablation · *127 words*

> **Tier 0 alone explains zero percent of bank credits on realistic data.** That's the finding, not a
> regression — it knows nothing about a rolling reserve.
>
> Add Tier 1: **83% explanation rate, 91% settlement coverage.**
>
> On the held-out seed the regex extracts **nothing** — so we measured the arithmetic without linkage:
> **100% on both seeds.** The held-out failure is *entirely* narration parsing.

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

## 3:30–4:20 · Failure recovery: kill it mid-run · *81 words — do not cut*

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

## 4:20–5:00 · The honest exception list · *115 words*

> The queue separates **breaks** from **explained-but-notable**. A withheld reserve isn't a break —
> it's a receivable. Conflating them inflates your exception count.
>
> The class we **cannot** solve: a refund whose original payment predates this extract. Detected every
> time. **Never** resolvable — the payment isn't in the data.
>
> The live run showed the same shape from the other side. Fourteen of those twenty-two narrations have
> the UTR **physically cut out** at forty characters. The model returned what was there — it was
> **right**. We'd counted those as hallucinations, overstating model error fivefold.
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
- [ ] **Time a full read-through before filming.** Three drafts running, the estimate was optimistic.
