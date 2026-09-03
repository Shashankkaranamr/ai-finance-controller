# map_schema scenario runs — preserved records

`out/` is gitignored, so a live run's raw output survives only until the next run
overwrites it. That happened once: a later live pass overwrote the 03 Sep
before-state, and the before/after comparison that the write-ups depend on had to
be recovered from the committed RUN_LOG entry. These files exist so it cannot
happen again.

| file | what it is | provenance |
|---|---|---|
| `2026-09-03_live_eval_PRE-F021-FIX.md` | the **first** live run of the ten scenarios. Two wrong mappings **accepted** | **transcribed from the committed RUN_LOG entry**, not raw capture — the raw file was overwritten |
| `2026-09-03_live_eval_POST-F021-FIX.json` | a **second** live run, after gate 3 was fixed. Same two mappings wrong, both now **blocked** | raw output of `scripts/live_scenario_suite.py` |

## Why both matter

The pair is the evidence for the F-021 fix, and each half says something the other
cannot:

- **Before** — the model got 8/10 and the gates accepted all ten, including both
  wrong mappings. In-remit false clear went to 4/187 on S7. That is the finding.
- **After** — the model again got 8/10, failing **the same two scenarios**, and
  the gates now block exactly those two. That the failures reproduce across two
  independent live samples means the model's failure mode is **stable**, not
  sampling noise, which is a stronger claim than either run alone supports.

Neither is evidence that the fence generalises. The fix was written against S7 and
S9, so catching them is true by construction (D-037).
