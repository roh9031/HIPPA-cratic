# Trap backlog (Teammate A: trap hunter)

Goal: think like a judge. For each request below, write the **correct** cohort as DuckDB SQL, then add it as a
`Case` in `tests/test_answer_key.py`. If the engine disagrees with your SQL, you've found a bug: log it in
[GAPS.md](GAPS.md) and give the Case a `gap="#N"` so it's tracked as an expected failure until B or C fix it.

## Workflow

```bash
.venv\Scripts\activate                          # every new terminal (Mac: source .venv/bin/activate)
python scripts/sql.py                           # SQL console: type queries ending in ;  (.tables, .cols clinical her2)
python scripts/sql.py --cols clinical receptor  # find column names
pytest -q -rxX tests/test_answer_key.py         # run the answer-key tests (x = known gap, X = gap fixed!)
```

Tables in the console: `samples` (one row per sample, the cohort base), `slides` (several per sample),
`survival` (per sample; quote dotted names, e.g. `"OS.time"`), `clinical` (per sample, 194 text columns).

**Rules for a good answer key**
- Return exactly one column, `sample_id`, one row per sample (use `IN (...)` / `EXISTS`, not a `JOIN` that can duplicate).
- Decide the ambiguous bits deliberately (what counts as "tumor"? which HER2 column?) and write the decision in `notes`.
- After checking the count by hand, pin it with `expected_n`.

## Done

| Trap | Answer | Status |
|---|---|---|
| Demo: primary tumors, RNA + protein, diagnostic slide | 731 | ✅ passes |
| Same, fixed with collapse | 731 | ✅ |
| Primary tumors with a frozen slide | 1,093 | ✅ |
| ER+ primary tumors with OS data (naive: survival on patient_id) | 807 | ✅ |
| 5+ years follow-up | 253 | ✅ |
| RNA but no diagnostic slide | 38 | ✅ |
| All primary tumors, left-joined to slides + collapse | 1,101 | ✅ |
| OS data excluding redacted records | — | ✅ |
| **Primary tumors whose patient also has a matched normal** (worked example) | 139 | ❌ xfail, gap #2 |
| **HER2-positive primary tumors** (IHC or ISH positive) | 197 | ❌ xfail, gap #16 (no OR). Also #17: 3 columns disagree |

## To do (rough priority)

| # | Request a judge might give | Why it's tricky | Hints |
|---|---|---|---|
| 1 | Tumors **with a matched normal that has a slide** | Two hops: tumor → patient → normal sample → slides | 24 normal samples have slides but are **missing from `samples`** (50 slides). Does your answer depend on that? |
| 2 | Primary tumors joined to slides **on patient_id** | Those 24 "orphan" normal samples' slides attach to their patient's tumor | Check the engine flags it as cross-sample, and that the fix gives your answer |
| 4 | **Triple-negative** primary tumors (ER−, PR−, HER2−) | Three filters; missing/Indeterminate/Equivocal values | Gap #7: `ne Positive` keeps Indeterminate, `eq Negative` doesn't |
| 5 | Primary tumors from **patients diagnosed over 50** | Age is stored as text in clinical; 5 are missing | `TRY_CAST(age_at_initial_pathologic_diagnosis AS INT) > 50` |
| 6 | **Female** patients with a diagnostic slide | 12 male primary tumors; 4 missing gender | `gender = 'FEMALE'`. Missing gender: in or out? |
| 7 | Tumors with **only 20x** slides / any **40x** slide | Per-slide attribute → inflation + "only" = anti logic | `slides.objective` (2,583 at 40x, 521 at 20x, 7 missing) |
| 8 | **Luminal A** tumors with survival and protein data | PAM50 missing for 291 samples | `PAM50Call_RNAseq` |
| 9 | **All tumors** (primary + metastatic) with a slide | Does "tumors" include the 7 Metastatic samples? | Note the decision |
| 10 | **One sample per patient**, patients with OS data | Collapse to patient: which sample is kept? | Gap #9. Do any patients have 2 tumor samples? |
| 11 | Patients who **died** with a diagnostic slide | `OS = 1` in survival vs `vital_status` in clinical: do they agree? | Compare the two first |
| 12 | Primary tumors **with no survival record** | Anti-join; 4 primary tumors | Make sure redacted rows count as "having" a record (or not, and say so) |
