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

---

## Trap: slides joined on patient_id (Nov 12)

**Answer keys: diagnostic 1,061 · frozen 1,093** · tests `diagnostic_slide_patient_join`, `frozen_slide_patient_join` · ✅ both pass

**1. Diagnostic slides: sample match vs patient match.** Only 1 tumor differs: `TCGA-E2-A15E-01` has no diagnostic
slide of its own, and its patient's only one belongs to the metastatic sample (`-06`).
```sql
WITH tum AS (SELECT sample_id, patient_id FROM samples WHERE sample_type='Primary Tumor')
SELECT
  count(*) FILTER (WHERE sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%'))  AS own_diag_slide,
  count(*) FILTER (WHERE patient_id IN (SELECT patient_id FROM slides WHERE slide_kind LIKE 'diagnostic%')) AS patient_has_diag_slide,
  count(*) FILTER (WHERE patient_id IN (SELECT patient_id FROM slides WHERE slide_kind LIKE 'diagnostic%')
               AND sample_id NOT IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%')) AS only_via_other_sample
FROM tum
```
own 1,061 · via patient 1,062 · only via another sample 1.

**2. Frozen slides: same sample set, but rows leak.** A patient-level inner join gives 1,978 rows for 1,093 tumors.
406 rows are another sample's slide (mostly the normal's), so slide columns such as the viewer link are wrong there.
```sql
SELECT count(*) AS joined_rows, count(DISTINCT t.sample_id) AS distinct_tumors,
       count(*) FILTER (WHERE s.sample_id <> t.sample_id) AS rows_from_other_sample
FROM samples t JOIN slides s USING (patient_id)
WHERE t.sample_type='Primary Tumor' AND s.slide_kind LIKE 'frozen%'
```

**3. Engine check** (Python: run the naive steps, then click the first fix of each problem until none are left):

| Naive version | Engine flags | Fix clicked | Result |
|---|---|---|---|
| diagnostic, semi-join on patient_id | cross_sample (1 sample) | Match on sample_id | 1,061 ✅ |
| frozen, inner join on patient_id | inflation (1,978 rows / 1,093) + cross_sample (406 rows) | semi-join | 1,093 ✅ |

**Findings:** the engine handles these correctly. The tests now protect that behavior.

---

## Trap: tumors whose patient has a matched normal sample with a slide (Nov 12)

**Answer key: 162** · test `tumor_with_normal_slide` · ❌ xfail, gap #2 (patient-level match always flagged). Raises gap #19.

**1. Two hops plus orphans.** 24 normal samples have slides but are missing from `sample_manifest.csv`.
```sql
WITH tum AS (SELECT sample_id, patient_id FROM samples WHERE sample_type='Primary Tumor')
SELECT
  count(*) FILTER (WHERE patient_id IN (SELECT patient_id FROM samples WHERE sample_type='Solid Tissue Normal'))   AS has_normal_in_manifest,
  count(*) FILTER (WHERE patient_id IN (SELECT s.patient_id FROM slides s JOIN samples m USING (sample_id)
                                          WHERE m.sample_type='Solid Tissue Normal'))                          AS A_normal_in_manifest_with_slide,
  count(*) FILTER (WHERE patient_id IN (SELECT patient_id FROM slides WHERE substr(sample_id, 14, 2) = '11'))  AS B_any_normal_slide_incl_orphans,
  count(*) FILTER (WHERE patient_id IN (SELECT patient_id FROM slides WHERE substr(sample_id, 14, 2) = '11'
                                          AND sample_id NOT IN (SELECT sample_id FROM samples))
                     AND patient_id NOT IN (SELECT patient_id FROM samples WHERE sample_type='Solid Tissue Normal')) AS only_via_orphans
FROM tum
```
| Normal in manifest | A: manifest normal with a slide | **B: any normal slide (incl. orphans)** | Only via orphans |
|---|---|---|---|
| 139 | 138 | **162** | 24 |

**Decision:** B. The request is about slides, and the slide manifest is the authority on slides. A slide with a `-11`
barcode proves the normal sample exists.

**2. Engine check.** A `patient_id` semi-join on slides with `sample_id contains -11` finds exactly the right 162,
but export is blocked by the cross-sample warning (gap #2).

**Findings:** gap #19. The sample manifest is missing 24 normal samples that have slides, so "has a matched normal" is
139 by the manifest or 163 counting slide evidence. The team should decide, and possibly ask the organizers.

## Trap: all five data layers, with and without a diagnostic slide (Nov 12)

**Answer keys: 535 and 531** · tests `all_five_layers`, `all_five_layers_diagnostic_slide` · ✅ both pass.
Why this one: `data/tcga-brca/README.md` in the challenge repo quotes "Primary tumors with all five data layers = 535",
so a judge is likely to start from it and add a join.

**1. All five layers.** Matches the README.
```sql
SELECT count(*) AS all_five FROM samples
WHERE sample_type='Primary Tumor' AND has_survival AND has_mutation AND has_copy_number AND has_rna AND has_protein
```
→ **535**

**2. Naive version with a diagnostic slide** (a plain JOIN, the way most people would write it):
```sql
SELECT count(*) AS rows_naive, count(DISTINCT s.sample_id) AS samples
FROM samples s JOIN slides d ON d.sample_id = s.sample_id AND d.slide_kind LIKE 'diagnostic%'
WHERE sample_type='Primary Tumor' AND has_survival AND has_mutation AND has_copy_number AND has_rna AND has_protein
```
| Rows (naive) | Samples (correct) |
|---|---|
| 572 | **531** |

41 extra rows from samples with 2+ diagnostic slides; 4 of the 535 have no diagnostic slide.

**3. One sample per patient?**
```sql
SELECT count(*) samples, count(DISTINCT patient_id) patients FROM samples
WHERE sample_type='Primary Tumor' AND has_survival AND has_mutation AND has_copy_number AND has_rna AND has_protein
```
→ 535 / 535. No patient has two such tumors, so "patients" and "samples" give the same answer here. Not a trap.

**4. Engine check.** Steps: primary tumor → five `has_* = True` conditions → slides semi-join on sample_id. Engine gives
535 and 531; the naive inner join is flagged as inflation (572 rows / 531 samples) and the semi-join fix is correct.
Verify with SQL agrees at every step.

**Findings:** none. The engine handles it.
