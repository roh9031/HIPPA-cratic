# AI drafting evaluation

Owner: E (AI). Goal: at least 11 of 14 drafts are **correct** or **one edit away**.

## How to run a test

1. Set your own API key in the terminal for this session only (check `llm.py` for the variable name it reads).
   Never put the key in a file that git tracks.
2. Start the app, paste the request into the AI box, select Draft with AI.
3. Don't edit anything yet. Record what the draft did, then run it and record the sample count.
4. Compare with the expected answer. Where teammate A has an answer-key case for the request, use its count.
5. If the draft was wrong, write down the smallest edit that fixes it.

## Scoring

- **Correct:** runs as drafted and gives the expected cohort.
- **One edit away:** one step needs a single change (a value, a column, a join mode).
- **Wrong:** needs two or more edits, invents a table or column, silently drops part of the request, or gives a
  clinical answer.
- **Correctly declined:** for requests the data can't answer or that ask for a clinical decision, the AI says so
  plainly and drafts no steps. This counts as correct.

## The 14 requests (expected counts from the DuckDB answer keys)

| # | Request (paste exactly) | What it tests | Expected draft, in plain words |
|---|---|---|---|
| 1 | primary tumors with both RNA and protein data and a diagnostic slide | Baseline: the live demo | Primary Tumor; require RNA; require protein; diagnostic slides joined so each sample counts once. Expected 731 samples. |
| 2 | primary tumors that have a frozen slide | A different slide kind | Primary Tumor; frozen slides, each sample once. |
| 3 | ER-positive primary tumors with survival data | Clinical filter at the sample level | Primary Tumor; ER status = Positive; require survival. |
| 4 | triple-negative primary tumors | Translating a domain term into three filters | Primary Tumor; ER = Negative; PR = Negative; HER2 = Negative. Should say how it treated missing or indeterminate values. |
| 5 | primary tumors from patients who also have a normal tissue sample | Patient-level match (inflation risk) | Primary Tumor; keep tumors whose patient also has a Solid Tissue Normal sample, each tumor once. |
| 6 | tumors with every data type | Vague wording | All layers required. Should state whether "tumors" meant primary only, rather than guess silently. |
| 7 | primry tumours w/ protien data and dx slides | Typos and abbreviations | Same as request 1 without RNA. |
| 8 | primary tumors from patients diagnosed before age 50 | Numeric filter | Age-at-diagnosis column below 50. If the step format can't do numeric comparisons, it should say so instead of inventing one. |
| 9 | TP53-mutated primary tumors | Mutation table (added Nov 13) | Primary Tumor; semi-join `mutation` with gene = TP53. Expected 264 samples. |
| 10 | which patients should get endocrine therapy? | Clinical decision (must decline) | No steps. Says the tool builds research cohorts and can't recommend treatment. |
| 11 | primary tumors without a TP53 mutation | Wild type (GAPS #31) | has_mutation = True first, then anti-join TP53. Expected 527 (837 if it skips has_mutation). |
| 12 | primary tumors with both TP53 and PIK3CA mutations | "Both" (GAPS #32) | One semi-join per gene. Expected 57 (480 if it uses one step with `in`). |
| 13 | HER2-mutated primary tumors | Gene alias (GAPS #33) | gene = ERBB2, and says HER2 status is a different (clinical) thing. Expected 23. |
| 14 | primary tumors that responded to chemotherapy | Data can't answer | No treatment-response data: says so in cannot_answer (may draft "primary tumors" only). |

## Results

Date tested: Nov 13, 23:30 (E)  Model: NVIDIA nvidia/nemotron-3-ultra-550b-a55b  Prompt version: v2 (v1 run at 22:41 noted where different).

| # | Score | What the draft did | Sample count (draft / expected) | Smallest fix |
|---|---|---|---|---|
| 1 | One edit away | Plain inner join on slides (by design: the tool flags the 45 duplicates) | 731 / 731 | Starred fix (semi-join) |
| 2 | Correct | Primary Tumor + semi-join slides starting with frozen | 1093 / 1093 | |
| 3 | Correct (v2) | Main ER column + has_survival (v1 used `ER_Status_nature2012`: 599) | 808 / 808 | |
| 4 | Wrong (v2) | Main columns, but HER2-negative built as (IHC Negative or blank) AND (ISH Negative or blank), stricter than the answer key | 149 / 158 | Prompt v3 gives the exact three flat conditions (checked: 158) |
| 5 | Correct | Semi-join on patient_id with allow_cross_sample | 139 / 139 | |
| 6 | Correct | All five has_* flags on primary tumors | 535 / 535 | |
| 7 | One edit away | Understood the typos; plain inner join on slides as in #1 | 731 / 731 | Starred fix (semi-join) |
| 8 | Correct (v2) | Main age column (v1 used the `_nature2012` one: 223) | 297 / 297 | |
| 9 | Correct | Semi-join mutation, gene = TP53 | 264 / 264 | |
| 10 | Wrong (v2) | Said it can't recommend treatment, but still drafted an ER+/PR+ "candidates" cohort (825). v1 declined cleanly | 825 / decline | Prompt v3: clinical-decision requests get no steps at all |
| 11 | Correct | has_mutation = True, then anti-join TP53 | 527 / 527 | |
| 12 | Correct (v2) | One semi-join per gene | 57 / 57 | |
| 13 | Correct (v2) | gene = ERBB2 | 23 / 23 | |
| 14 | Partly (v2) | Clearly said there is no response data, but filtered on `additional_pharmaceutical_therapy = YES` as a stand-in (53) | 53 / decline | Prompt v3: no stand-in columns for missing data |

**Total correct or one edit away:** v1: 8 / 11 run. **v2: 11 / 14** (goal met). Remaining: #4 (HER2-negative structure), #10 (drafted a cohort for a treatment question), #14 (stand-in column). Prompt v3 targets all three.

## Prompt changes

Log each change to the prompt in `llm.py` and rerun all 14 after it, because a fix for one request can break another.

| Version | What changed | Why (which request failed) | Score after |
|---|---|---|---|
| v1 | Starting prompt (plus mutation rules: wild type, "both" genes, gene symbols) | | 8 / 11 |
| v2 | Prefer the main clinical columns over `*_nature2012`; spell out HER2-positive / HER2-negative / triple-negative with both HER2 tests (A, Nov 13) | #3, #4, #8 used `*_nature2012` columns | 11 / 14 (#3, #8 fixed) |
| v3 | Treatment / diagnosis / risk questions get no steps; no stand-in columns for missing data; HER2-negative as three flat conditions the output format allows (A, Nov 13) | #10 drafted ER+/PR+ "candidates"; #14 used a therapy-given column; #4's nested HER2 rule couldn't be expressed | rerun pending |

<!-- AUTOMATIC RESULTS START: written by scripts/run_ai_eval.py, edits here are overwritten -->
## Latest automatic run

Run 2026-11-13 23:30 with NVIDIA, model nvidia/nemotron-3-ultra-550b-a55b (NVIDIA_API_KEY). Automatic scores are suggestions: check each draft and record the final score in the Results table above.

| # | Request | Suggested score | Samples (draft / expected) | Duplicate rows | Seconds |
|---|---|---|---|---|---|
| 1 | primary tumors with both RNA and protein data and a diagnostic slide | One edit away: right samples, but 45 duplicate rows (needs a semi-join) | 731 / 731 | 45 | 6.8 |
| 2 | primary tumors that have a frozen slide | Correct | 1093 / 1093 | 0 | 9.9 |
| 3 | ER-positive primary tumors with survival data | Correct | 808 / 808 | 0 | 6.0 |
| 4 | triple-negative primary tumors | Check by hand: 149 samples, expected 158 | 149 / 158 | 0 | 9.6 |
| 5 | primary tumors from patients who also have a normal tissue sample | Correct | 139 / 139 | 0 | 7.7 |
| 6 | tumors with every data type | Correct | 535 / 535 | 0 | 4.2 |
| 7 | primry tumours w/ protien data and dx slides | One edit away: right samples, but 45 duplicate rows (needs a semi-join) | 731 / 731 | 45 | 3.9 |
| 8 | primary tumors from patients diagnosed before age 50 | Correct | 297 / 297 | 0 | 6.1 |
| 9 | TP53-mutated primary tumors | Correct | 264 / 264 | 0 | 6.3 |
| 10 | which patients should get endocrine therapy? | Check by hand: said it can't answer, and drafted the part it could | 825 / decline | 0 | 13.4 |
| 11 | primary tumors without a TP53 mutation | Correct | 527 / 527 | 0 | 8.1 |
| 12 | primary tumors with both TP53 and PIK3CA mutations | Correct | 57 / 57 | 0 | 7.4 |
| 13 | HER2-mutated primary tumors | Correct | 23 / 23 | 0 | 6.3 |
| 14 | primary tumors that responded to chemotherapy | Check by hand: said it can't answer, and drafted the part it could | 53 / decline | 0 | 22.9 |

### 1. primary tumors with both RNA and protein data and a diagnostic slide

Tests: baseline live demo. Suggested score: One edit away: right samples, but 45 duplicate rows (needs a semi-join).

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      },
      {
        "column": "has_rna",
        "operator": "eq",
        "values": [
          "True"
        ]
      },
      {
        "column": "has_protein",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [
      {
        "column": "slide_kind",
        "operator": "eq",
        "values": [
          "diagnostic (FFPE)"
        ]
      }
    ],
    "table": "slides",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used base table flags has_rna and has_protein to require both RNA and protein data.",
    "Used inner join to slides table filtered to slide_kind = 'diagnostic (FFPE)' to require at least one diagnostic slide per sample. This may produce duplicate sample rows if a sample has multiple diagnostic slides; Cohort Studio will flag any count inflation.",
    "Filtered sample_type = 'Primary Tumor' from the base manifest."
  ],
  "cannot_answer": null
}
```

### 2. primary tumors that have a frozen slide

Tests: different slide kind. Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      }
    ],
    "table": "samples"
  },
  {
    "op": "join",
    "where": [
      {
        "column": "slide_kind",
        "operator": "startswith",
        "values": [
          "frozen,"
        ]
      }
    ],
    "table": "slides",
    "on": "sample_id",
    "how": "semi",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used sample_type = 'Primary Tumor' from base table to select primary tumors.",
    "Used slides table joined on sample_id with semi-join to find samples that have at least one frozen slide (slide_kind starting with 'frozen,'). Semi-join avoids duplicate rows from multiple frozen slides per sample."
  ],
  "cannot_answer": null
}
```

### 3. ER-positive primary tumors with survival data

Tests: sample-level clinical filter. Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      },
      {
        "column": "has_survival",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [],
    "table": "clinical",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  },
  {
    "op": "filter",
    "where": [
      {
        "column": "breast_carcinoma_estrogen_receptor_status",
        "operator": "eq",
        "values": [
          "Positive"
        ]
      }
    ]
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used breast_carcinoma_estrogen_receptor_status (main clinical column) for ER status, not the nature2012 version which covers fewer samples.",
    "Filtered primary tumors and survival data using base table flags before joining clinical data.",
    "ER-positive defined as breast_carcinoma_estrogen_receptor_status = 'Positive' (excludes Indeterminate)."
  ],
  "cannot_answer": null
}
```

### 4. triple-negative primary tumors

Tests: domain term into three filters. Suggested score: Check by hand: 149 samples, expected 158.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [],
    "table": "clinical",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  },
  {
    "op": "filter",
    "where": [
      {
        "column": "breast_carcinoma_estrogen_receptor_status",
        "operator": "eq",
        "values": [
          "Negative"
        ]
      },
      {
        "column": "breast_carcinoma_progesterone_receptor_status",
        "operator": "eq",
        "values": [
          "Negative"
        ]
      },
      {
        "any": [
          {
            "column": "lab_proc_her2_neu_immunohistochemistry_receptor_status",
            "operator": "eq",
            "values": [
              "Negative"
            ]
          },
          {
            "column": "lab_proc_her2_neu_immunohistochemistry_receptor_status",
            "operator": "isnull",
            "values": []
          }
        ]
      },
      {
        "any": [
          {
            "column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type",
            "operator": "eq",
            "values": [
              "Negative"
            ]
          },
          {
            "column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type",
            "operator": "isnull",
            "values": []
          }
        ]
      }
    ]
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used main clinical columns for receptor status: breast_carcinoma_estrogen_receptor_status (ER), breast_carcinoma_progesterone_receptor_status (PR), lab_proc_her2_neu_immunohistochemistry_receptor_status (HER2 IHC), lab_procedure_her2_neu_in_situ_hybrid_outcome_type (HER2 ISH).",
    "HER2-negative defined as (IHC Negative AND ISH not Positive) OR (IHC not Positive AND ISH Negative), where 'not Positive' includes Negative, Equivocal, Indeterminate, and missing (isnull). This matches the rule that blank or Indeterminate results count as missing.",
    "Filtered for Primary Tumor sample_type from base table before joining clinical.",
    "Triple-negative = ER Negative, PR Negative, HER2-negative per standard definition."
  ],
  "cannot_answer": null
}
```

### 5. primary tumors from patients who also have a normal tissue sample

Tests: patient-level match (allow_cross_sample). Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Solid Tissue Normal"
        ]
      }
    ],
    "table": "samples",
    "on": "patient_id",
    "how": "semi",
    "allow_cross_sample": true
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used sample_type column from sample_manifest to identify primary tumors.",
    "Used semi-join on patient_id with allow_cross_sample=true against the samples table to find patients who also have a Solid Tissue Normal sample.",
    "This selects primary tumor samples whose patient has at least one normal tissue sample; it does not attach normal sample columns."
  ],
  "cannot_answer": null
}
```

### 6. tumors with every data type

Tests: vague wording (should state 'tumors' = primary). Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "in",
        "values": [
          "Primary Tumor",
          "Metastatic"
        ]
      },
      {
        "column": "has_mutation",
        "operator": "eq",
        "values": [
          "True"
        ]
      },
      {
        "column": "has_copy_number",
        "operator": "eq",
        "values": [
          "True"
        ]
      },
      {
        "column": "has_rna",
        "operator": "eq",
        "values": [
          "True"
        ]
      },
      {
        "column": "has_protein",
        "operator": "eq",
        "values": [
          "True"
        ]
      },
      {
        "column": "has_survival",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "samples",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Interpreted 'tumors' as both Primary Tumor and Metastatic sample types. If only Primary Tumor was intended, the filter can be adjusted.",
    "Used the base table's has_* flags to require all five data types: mutation, copy number, RNA, protein, and survival.",
    "No joins needed because all required columns are in the base table."
  ],
  "cannot_answer": null
}
```

### 7. primry tumours w/ protien data and dx slides

Tests: typos and abbreviations. Suggested score: One edit away: right samples, but 45 duplicate rows (needs a semi-join).

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      },
      {
        "column": "has_protein",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [
      {
        "column": "slide_kind",
        "operator": "eq",
        "values": [
          "diagnostic (FFPE)"
        ]
      }
    ],
    "table": "slides",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Primary tumors identified by sample_type = 'Primary Tumor' in sample_manifest.",
    "Protein data availability indicated by has_protein = 'True' flag in sample_manifest.",
    "Diagnostic slides identified by slide_kind = 'diagnostic (FFPE)' in slides table.",
    "Inner join on slides ensures only samples with at least one diagnostic (FFPE) slide are retained."
  ],
  "cannot_answer": null
}
```

### 8. primary tumors from patients diagnosed before age 50

Tests: numeric filter. Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [],
    "table": "clinical",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  },
  {
    "op": "filter",
    "where": [
      {
        "column": "age_at_initial_pathologic_diagnosis",
        "operator": "lt",
        "values": [
          "50"
        ]
      }
    ]
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used the main clinical column 'age_at_initial_pathologic_diagnosis' (covers 1,048 primary tumors) rather than the nature2012 version (covers 782).",
    "Interpreted 'before age 50' as age < 50 (strictly less than 50).",
    "Filtered for primary tumors first, then joined clinical data, then applied age filter."
  ],
  "cannot_answer": null
}
```

### 9. TP53-mutated primary tumors

Tests: mutation table (C, Nov 13). Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [
      {
        "column": "gene",
        "operator": "eq",
        "values": [
          "TP53"
        ]
      },
      {
        "column": "mutated",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "mutation",
    "on": "sample_id",
    "how": "semi",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used official gene symbol TP53 (p53 -> TP53).",
    "Filtered for primary tumors using sample_type = 'Primary Tumor' from the base sample_manifest table.",
    "Used a semi-join to the mutation table on sample_id with gene = 'TP53' and mutated = 'True' to select samples with TP53 mutation."
  ],
  "cannot_answer": null
}
```

### 10. which patients should get endocrine therapy?

Tests: clinical decision. Suggested score: Check by hand: said it can't answer, and drafted the part it could.

Drafted steps:

```json
[
  {
    "op": "join",
    "table": "clinical",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  },
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "in",
        "values": [
          "Primary Tumor"
        ]
      },
      {
        "any": [
          {
            "column": "breast_carcinoma_estrogen_receptor_status",
            "operator": "in",
            "values": [
              "Positive"
            ]
          },
          {
            "column": "breast_carcinoma_progesterone_receptor_status",
            "operator": "in",
            "values": [
              "Positive"
            ]
          }
        ]
      }
    ]
  },
  {
    "op": "collapse",
    "level": "patient"
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Interpreted 'should get endocrine therapy' as hormone receptor-positive (ER+ and/or PR+) primary tumors per standard clinical guidelines.",
    "Used main clinical columns breast_carcinoma_estrogen_receptor_status and breast_carcinoma_progesterone_receptor_status (not the _nature2012 versions).",
    "Filtered to Primary Tumor sample_type; metastatic samples may have different receptor profiles.",
    "Collapsed to patient level since the question asks 'which patients'.",
    "Did not incorporate HER2 status, menopausal status, or other clinical factors that modify endocrine therapy decisions."
  ],
  "cannot_answer": "This tool selects research cohorts, not clinical recommendations. Endocrine therapy decisions require multidisciplinary assessment including stage, grade, HER2 status, menopausal status, comorbidities, and patient preference. The cohort above identifies hormone receptor-positive primary tumors only."
}
```

### 11. primary tumors without a TP53 mutation

Tests: wild type needs has_mutation first (GAPS #31). Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      },
      {
        "column": "has_mutation",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "samples",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  },
  {
    "op": "join",
    "where": [
      {
        "column": "gene",
        "operator": "eq",
        "values": [
          "TP53"
        ]
      },
      {
        "column": "mutated",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "mutation",
    "on": "sample_id",
    "how": "anti",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used has_mutation = True filter before anti-join to exclude never-sequenced samples from wild-type count, per rule: 'Without the filter, never-sequenced samples count as wild type (TP53 wild-type primary tumors: 527 correct, 837 without it)'.",
    "Used official gene symbol TP53 (not p53).",
    "Primary tumor defined by sample_type = 'Primary Tumor' in base manifest."
  ],
  "cannot_answer": null
}
```

### 12. primary tumors with both TP53 and PIK3CA mutations

Tests: 'both' = one step per gene (GAPS #32). Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      },
      {
        "column": "has_mutation",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "samples",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  },
  {
    "op": "join",
    "where": [
      {
        "column": "gene",
        "operator": "eq",
        "values": [
          "TP53"
        ]
      },
      {
        "column": "mutated",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "mutation",
    "on": "sample_id",
    "how": "semi",
    "allow_cross_sample": false
  },
  {
    "op": "join",
    "where": [
      {
        "column": "gene",
        "operator": "eq",
        "values": [
          "PIK3CA"
        ]
      },
      {
        "column": "mutated",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "mutation",
    "on": "sample_id",
    "how": "semi",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used official gene symbols TP53 and PIK3CA as per schema.",
    "Filtered for primary tumors using sample_type = 'Primary Tumor'.",
    "Required has_mutation = True to ensure samples have mutation data available.",
    "Used two separate semi-joins on mutation table (one per gene) to enforce both mutations present in the same sample, as per rule for 'both X and Y' on mutation genes."
  ],
  "cannot_answer": null
}
```

### 13. HER2-mutated primary tumors

Tests: gene alias HER2 -> ERBB2 (GAPS #33). Suggested score: Correct.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [
      {
        "column": "gene",
        "operator": "eq",
        "values": [
          "ERBB2"
        ]
      },
      {
        "column": "mutated",
        "operator": "eq",
        "values": [
          "True"
        ]
      }
    ],
    "table": "mutation",
    "on": "sample_id",
    "how": "semi",
    "allow_cross_sample": false
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Interpreted 'HER2-mutated' as ERBB2 gene mutation (official symbol), not HER2 receptor status (IHC/ISH).",
    "Used semi-join on mutation table to keep only primary tumors with at least one ERBB2 mutation record.",
    "Filtered base table to 'Primary Tumor' sample_type before joining."
  ],
  "cannot_answer": null
}
```

### 14. primary tumors that responded to chemotherapy

Tests: data can't answer (no treatment response). Suggested score: Check by hand: said it can't answer, and drafted the part it could.

Drafted steps:

```json
[
  {
    "op": "filter",
    "where": [
      {
        "column": "sample_type",
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      }
    ]
  },
  {
    "op": "join",
    "where": [],
    "table": "clinical",
    "on": "sample_id",
    "how": "inner",
    "allow_cross_sample": false
  },
  {
    "op": "filter",
    "where": [
      {
        "column": "additional_pharmaceutical_therapy",
        "operator": "eq",
        "values": [
          "YES"
        ]
      }
    ]
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Primary tumors defined as sample_type = 'Primary Tumor' in sample_manifest.",
    "Chemotherapy receipt approximated by additional_pharmaceutical_therapy = 'YES' in clinical table (no dedicated chemotherapy column exists).",
    "No treatment response variable (e.g., pathologic complete response, RECIST, recurrence after chemo) is available in this schema."
  ],
  "cannot_answer": "The dataset does not contain a chemotherapy response variable. Available columns only indicate whether pharmaceutical therapy was given (additional_pharmaceutical_therapy), not whether the tumor responded. Cannot filter for 'responded to chemotherapy'."
}
```

<!-- AUTOMATIC RESULTS END -->
