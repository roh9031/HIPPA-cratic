# Trap log

Every query used to build an answer key, in order, with what it showed. Rerun any of them with
`python scripts/sql.py "<query>"` (activate `.venv` first). Newest trap at the bottom.

---

## Trap: HER2-positive primary tumors (Nov 12)

**Answer key: 197** · test `her2_positive` · ❌ xfail, gap #16 (no OR conditions)

**1. Find the HER2 columns.** 16 columns; 3 hold a status: `HER2_Final_Status_nature2012`,
`lab_proc_her2_neu_immunohistochemistry_receptor_status` (IHC), `lab_procedure_her2_neu_in_situ_hybrid_outcome_type` (ISH).
```bash
python scripts/sql.py --cols clinical her2
```

**2. Values of each, primary tumors only.** nature2012 is blank for 325. IHC has 179 Equivocal. ISH is blank for 681.
```sql
SELECT 'final_nature2012' AS col, HER2_Final_Status_nature2012 AS value, count(*) AS n FROM clinical WHERE sample_type='Primary Tumor' GROUP BY ALL
UNION ALL
SELECT 'ihc', lab_proc_her2_neu_immunohistochemistry_receptor_status, count(*) FROM clinical WHERE sample_type='Primary Tumor' GROUP BY ALL
UNION ALL
SELECT 'ish', lab_procedure_her2_neu_in_situ_hybrid_outcome_type, count(*) FROM clinical WHERE sample_type='Primary Tumor' GROUP BY ALL
ORDER BY col, n DESC
```

**3. Count each definition.** nature2012 = 114 · IHC only = 164 · **IHC or ISH = 197** (chosen: standard rule).
```sql
WITH t AS (SELECT * FROM clinical WHERE sample_type='Primary Tumor')
SELECT
  count(*) FILTER (WHERE HER2_Final_Status_nature2012='Positive')                          AS A_nature2012,
  count(*) FILTER (WHERE lab_proc_her2_neu_immunohistochemistry_receptor_status='Positive') AS B_ihc_only,
  count(*) FILTER (WHERE lab_proc_her2_neu_immunohistochemistry_receptor_status='Positive'
                      OR lab_procedure_her2_neu_in_situ_hybrid_outcome_type='Positive')     AS C_ihc_or_ish,
  count(*) FILTER (WHERE lab_proc_her2_neu_immunohistochemistry_receptor_status='Positive'
                     AND lab_procedure_her2_neu_in_situ_hybrid_outcome_type='Negative')     AS ihc_pos_but_ish_neg
FROM t
```

**4. Engine check.** Conditions are AND-only (`engine.py` `_apply_where`), so the OR can't be built. The best
attempt (IHC only) gives 164: it misses 33 ISH-only positives and wrongly includes none.

**Findings:** gap #16 (no OR), gap #17 (3 columns disagree, so the AI must name its choice).

---

## Trap: triple-negative primary tumors (Nov 12)

**Answer key: 158** · test `triple_negative` · ❌ xfail, gap #16 (no OR). Also exposed gap #18.

**1. ER and PR values.** Both have Positive / Negative / Indeterminate / blank. "Negative" means exactly `'Negative'`.
```sql
SELECT 'ER' AS receptor, breast_carcinoma_estrogen_receptor_status AS value, count(*) AS n FROM clinical WHERE sample_type='Primary Tumor' GROUP BY ALL
UNION ALL
SELECT 'PR', breast_carcinoma_progesterone_receptor_status, count(*) FROM clinical WHERE sample_type='Primary Tumor' GROUP BY ALL
ORDER BY receptor, n DESC
```
ER: Positive 808, Negative 238, blank 53, Indeterminate 2 · PR: Positive 699, Negative 344, blank 54, Indeterminate 4.

**2. Count each HER2-negative definition among the 220 ER-/PR- tumors.**
```sql
WITH t AS (
  SELECT sample_id,
         breast_carcinoma_estrogen_receptor_status    AS er,
         breast_carcinoma_progesterone_receptor_status AS pr,
         lab_proc_her2_neu_immunohistochemistry_receptor_status AS ihc,
         lab_procedure_her2_neu_in_situ_hybrid_outcome_type     AS ish,
         HER2_Final_Status_nature2012                           AS her2_final
  FROM clinical WHERE sample_type = 'Primary Tumor'),
er_pr_neg AS (SELECT * FROM t WHERE er = 'Negative' AND pr = 'Negative')
SELECT
  count(*)                                                                         AS er_pr_negative,
  count(*) FILTER (WHERE (ihc = 'Negative' AND coalesce(ish, '') <> 'Positive')
                      OR (coalesce(ihc, '') <> 'Positive' AND ish = 'Negative'))   AS A_strict_rule,
  count(*) FILTER (WHERE ihc = 'Negative')                                         AS B_ihc_negative_only,
  count(*) FILTER (WHERE NOT (coalesce(ihc,'') = 'Positive' OR coalesce(ish,'') = 'Positive')) AS C_not_positive,
  count(*) FILTER (WHERE her2_final = 'Negative')                                  AS D_nature2012
FROM er_pr_neg
```
| ER-/PR- | **A strict rule** | B IHC-negative only | C "not HER2-positive" | D nature2012 |
|---|---|---|---|---|
| 220 | **158** | 116 | 179 | 123 |

**3. Where does C's extra 21 come from?** Tumors with unknown HER2: 17 with no test, 3 Equivocal and 1 Indeterminate
with no ISH. "Not positive" quietly treats unknown as negative (gap #7).
```sql
SELECT lab_proc_her2_neu_immunohistochemistry_receptor_status AS ihc,
       lab_procedure_her2_neu_in_situ_hybrid_outcome_type     AS ish,
       count(*) AS n,
       CASE WHEN (ihc = 'Negative' AND coalesce(ish,'') <> 'Positive')
              OR (coalesce(ihc,'') <> 'Positive' AND ish = 'Negative') THEN 'HER2-negative (A)'
            WHEN ihc = 'Positive' OR ish = 'Positive'                     THEN 'HER2-positive'
            ELSE 'UNKNOWN: dropped by A, kept by C' END AS verdict
FROM clinical
WHERE sample_type = 'Primary Tumor'
  AND breast_carcinoma_estrogen_receptor_status = 'Negative'
  AND breast_carcinoma_progesterone_receptor_status = 'Negative'
GROUP BY ALL ORDER BY verdict, n DESC
```

**4. What the engine does with the obvious attempts** (all as conditions inside a `clinical` semi-join):

| Attempt | Engine | Missed | Wrongly included | Warnings |
|---|---|---|---|---|
| ER, PR, IHC all `eq Negative` | 116 | 44 | 2 | none |
| ER, PR `eq Negative`, IHC `ne Positive` | 150 | 16 | 8 | none |
| ER, PR, IHC `eq Negative`, ISH `ne Positive` | 18 | 140 | 0 | none |

**5. Why no warnings?** The same conditions as a separate `filter` step produce 4 missing-value notes. Inside a
join they produce none: `engine.py:243` applies join conditions without running any checks → **gap #18**.

**Findings:** gap #16 again (OR needed for the HER2 rule), gap #7 confirmed on a real request (21 unknowns),
new gap #18 (no missing-value warnings for join conditions).
