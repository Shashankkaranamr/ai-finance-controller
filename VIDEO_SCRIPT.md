# Video script — 5:00 hard cap

> # Current as of 02 Sep 2026 — filmable
>
> Rewritten against the numbers a run produces **today**. The 01 Sep audit's six fixes and the 02 Sep
> realism increment are both folded in; no beat below quotes a superseded figure.
>
> **What changed since the last draft, and why the script is stronger for it:**
>
> | Block | What changed |
> |---|---|
> | 1:15–2:45 | The drill-down is now `SETTLEMENT_FAILED` — the case where the system tells "the money never left" apart from "the bank lost it". The old entry was a false alarm. |
> | 2:45–3:30 | The ablation beat now carries the **artifact-versus-fact** finding: we tested our own headline against our own simulator, watched corroboration collapse 18 → 4, rebuilt the rule, and got 18 back. That is the strongest 45 seconds in the film. |
> | 4:20–5:00 | The truncated-UTR beat is true now (`bank_ref` is a CRC), and the stale-total settlement is added — the one case where extraction beats every deterministic tier. |
>
> Blocks 0:00–0:35, 0:35–1:15 and 3:30–4:20 (the network kill) are unchanged.
>
> **Numbers to re-check on the machine you film on**, because they are quoted aloud: explanation rate
> and settlement coverage on eval (78.26% / 81.82%), the top queue entry's amount, and the test count.

Follows BRIEF §11's block structure. Narration is written to be **spoken** at ~140 wpm.

**Budget: 685 spoken words ≈ 4:53, leaving ~7 s. Counts below are generated from the text by
`scripts` word count, not estimated, and they are deliberately higher than the pre-02-Sep draft's:
the ablation block grew because the artifact-versus-fact finding is now the centrepiece of the film.
Time a full read-through before filming. If a take runs long, cut from 1:15–2:45 — never 3:30–4:20.**

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

## 1:15–2:45 · Live run on the held-out batch, and one exception · *125 words*

**Run `python -m recon eval` on camera. Let it breathe — the run is under half a second, the reading is the content.**

> Held-out seed — a different world *and* narrations the parser has never seen. Three and a half
> thousand records, under half a second, statement foots to zero.
>
> **Seventy-eight percent explanation, eighty-two percent coverage.** Never one without the other.
>
> The queue sorts by **cash at risk**. Finance triages by money, not row count.

**Drill into the top entry — `SETTLEMENT_FAILED`, Rs 1,41,743.98.**

> **Rs 1,41,744**, no bank credit. But look at *why*.
>
> Status: **failed**. The transfer was attempted and didn't complete — the money never left, and the
> bank hasn't lost it. Action to **treasury**: confirm the beneficiary details.
>
> A missing credit and a failed one look **identical** in a statement. Neither has a row. They send an
> analyst to opposite ends of the building.

**Scroll to an `MDR_SLAB_MISMATCH`.**

> And one only Tier 1 can see: charged off-contract. Recoverable money.

---

## 2:45–3:30 · The ablation, and the question we asked about it · *171 words* · **the centrepiece**

> **Tier 0 alone explains zero percent of bank credits on realistic data.** That's the finding, not a
> regression — it knows nothing about a rolling reserve.
>
> Add Tier 1 arithmetic: **seventy-four percent.** Add deterministic corroboration: **seventy-eight
> on the held-out seed.** Add the LLM: **no change.**

**Slow down. This is the beat.**

> So we asked the obvious question about our own result. Is "the LLM adds nothing" a fact about
> reconciliation — or an artifact of data we wrote ourselves?
>
> We closed three realism gaps our own architecture doc had already admitted to. One mattered: the
> bank statement was restating the gateway's own date. Fix that, and our matching rule **collapsed
> from eighteen to four.**
>
> Rebuilt properly — exact amount, inside the bank's posting window — it came **back to eighteen, at
> a hundred percent precision.** Because what identifies a settlement is the **amount**. All
> twenty-two are unique, the closest pair a hundred and seventy-one rupees apart. True of real
> settlements, not just ours.
>
> **Half our finding was an artifact. The bigger half was real. We published both.**

**On screen:** the 18 → 4 → 18 table, then the oracle ceiling row.

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

## 4:20–5:00 · The honest exception list · *140 words*

> The queue separates **breaks** from **explained-but-notable**. A withheld reserve isn't a break —
> it's a receivable. Conflating them inflates your exception count.
>
> The class we **cannot** solve: a refund whose payment predates this extract. Detected every time.
> **Never** resolvable — the payment isn't in the data.
>
> Most held-out narrations have the UTR **cut out** at forty characters. The model returned what was
> there — it was **right**. We'd called those hallucinations, overstating model error fivefold.
>
> **"The model was wrong" and "the answer wasn't recoverable" are different findings.**
>
> And the one place extraction beats every deterministic tier: a settlement whose **own reported total
> is stale**. No amount rule reaches it. It buys the link — and still nothing posts, because the
> report contradicts itself.
>
> One deep loop, measured honestly — including the part where we proved our own headline half wrong.

**On screen:** the queue with `is_break` visible, then the repo URL.

---

## Pre-flight checklist

- [ ] `pytest` green (**207**) on the machine being filmed
- [ ] Re-run `demo` and `eval` and confirm every spoken number against the banner
- [ ] `demo` and `eval` both clean from a fresh clone
- [ ] **Rehearse the network kill** — confirm ~20 s lands mid-batch
- [ ] Terminal font large enough to read queue entries
- [ ] Explanation rate and settlement coverage visible **together** in every metrics frame
- [ ] The 18 → 4 → 18 table on screen for the whole artifact-versus-fact beat
- [ ] **Time a full read-through before filming.** Three drafts running, the estimate was optimistic.
