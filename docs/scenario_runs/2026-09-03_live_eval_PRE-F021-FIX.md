# 03 Sep 2026 — first live run of the ten scenarios (PRE F-021 fix)

**Provenance: transcribed from the committed RUN_LOG entry "RESULT — map_schema
scenario suite, live · 03 Sep 2026", not raw capture.** The raw
`out/_scenarios_eval/results.json` was overwritten by a later live pass before it
was copied anywhere tracked. Every number below appears in that RUN_LOG entry and
in commit `5ff1956`; nothing here is reconstructed from memory or re-derived.

Held-out seed, `claude-haiku-4-5`, one call per scenario, no re-rolls.

## Result

**Model accuracy: 8 of 10.** Gates: **all ten accepted**, including both wrong
mappings.

| # | shape | view | model | gate | run == clean | ms |
|---|---|---|---|---|---|---|
| S1 | single obvious | bank | correct | accepted | yes | 2428 |
| S2 | single obvious | lines | correct | accepted | yes | 3721 |
| S3 | single ambiguous | settlements | correct | accepted | yes | 1982 |
| S4 | single ambiguous | lines | correct | accepted | yes | 2375 |
| S5 | multiple (3) | bank | correct | accepted | yes | 1738 |
| S6 | multiple (3) | lines | correct | accepted | yes | 3596 |
| **S7** | misleading | lines | **WRONG** | **accepted** | **NO** | 2748 |
| S8 | misleading | books | correct | accepted | yes | 2002 |
| **S9** | misleading | settlements | **WRONG** | **accepted** | **NO** | 2039 |
| S10 | opaque, all 7 | books | correct | accepted | yes | 2174 |

## The 2×2

| | accepted | blocked |
|---|---|---|
| **correct** | 8 | 0 |
| **wrong** | **2** — S7, S9 | 0 |

The gates had **zero discriminating power**: every mapping the model got right was
accepted, and every mapping it got wrong was accepted too.

## The damage

| | explanation | false clear, in remit |
|---|---|---|
| clean baseline | 18/23 | 0/187 |
| **S7 repaired on a wrong mapping** | 0/23 | **4/187** |
| **S9 repaired on a wrong mapping** | 0/23 | 0/187 |

## The two mismappings

**S7** — the file carried `credit_amount` (holding true *debit* values) and
`debit_amount` (holding true *credit* values). The model returned the name match:

```
credit_amount -> credit    (truth: debit)
debit_amount  -> debit     (truth: credit)
```

Its rationale claimed evidence it did not have:

> *"…map to target fields 'credit' and 'debit' respectively, as evidenced by their
> numeric values (0 and 486933) representing transaction components…"*

One zero and one non-zero is consistent with **either** assignment.

**S9** — mapped `ref`→`id` correctly, then:

> *"…all other columns match their target field names directly."*

which puts `amount` and `fees` back on each other's values.
