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
| **Diagnostic slides, naive patient_id join** | 1,061 | ✅ passes (engine flags it, fix is correct) |
| **Frozen slides, naive patient_id inner join** | 1,093 | ✅ passes (inflation + 406 cross-sample rows flagged) |
| **Tumors with a matched normal that has a slide** | 162 | ❌ xfail, gap #2. Raised #19 (24 normals missing from manifest) |
| **All five data layers** (number quoted in the data README) | 535 | ✅ passes |
| **All five layers + a diagnostic slide** (naive inner join: 572 rows / 531 samples) | 531 | ✅ passes (inflation flagged, semi fix correct) |
| **Over 50** (age is text; > vs ≥) | 766 | ✅ (≥ 50 = 800) |
| **Female** | 1,085 | ✅ (2 gender columns disagree on 1 tumor) |
| **Died** (survival `OS = 1`) | 151 | ✅ (`vital_status` says 152: 1 tumor disagrees) |
| **Luminal A** (`PAM50Call_RNAseq = LumA`) | 421 | ✅ (other column says 231) |
| **40x diagnostic slide** | 920 | ✅ after fix: **the engine returned 0**, caught by Verify with SQL |
| **Only 20x diagnostic slides** (anti-join) | 134 | ✅ |
| **No survival record** (anti-join) | 4 | ✅ |
| **All tumor samples** (incl. 7 metastatic) | 1,108 | ✅ (`contains tumor` gives 1,101: wording trap, gap #8) |
| **One tumor per patient, prefer primary** | 1,101 | ✅ but only because the manifest lists primaries first (gap #9) |
| **Triple-negative primary tumors** | 158 | ❌ xfail, gap #16. Also found #18 (no warnings in joins), confirmed #7 |

Every query behind these answers is in [TRAP_LOG.md](TRAP_LOG.md).

## To do

The first backlog (#5–#12) is done: see the table above and `TRAP_LOG.md`. Ideas for the next batch:

| Request a judge might give | Why it might be tricky |
|---|---|
| Tumors with a **frozen slide but no diagnostic slide** | Two slide conditions; semi + anti |
| **Stage III or IV** tumors | `pathologic_stage` has sub-stages (IIIA, IIIB, ...) and `[Discrepancy]` codes (gap #7) |
| **Lymph-node positive** | Several node columns; coded values |
| Patients with **OS data but no DFI data** | Survival columns blank vs 0 |
| **ER-positive OR PR-positive** | Needs OR (gap #16) |
