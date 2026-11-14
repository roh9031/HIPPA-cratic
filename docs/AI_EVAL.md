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

Date tested: Nov 13, 22:41 (E)  Model: NVIDIA nvidia/nemotron-3-ultra-550b-a55b  Prompt version: v1. Requests 12–14 were added after this run.

| # | Score | What the draft did | Sample count (draft / expected) | Smallest fix |
|---|---|---|---|---|
| 1 | One edit away | Plain inner join on slides (by design: the tool flags the 45 duplicates) | 731 / 731 | Starred fix (semi-join) |
| 2 | Correct | Primary Tumor + semi-join slides starting with frozen | 1093 / 1093 | |
| 3 | Wrong | Used `ER_Status_nature2012` (2012 study, covers 782 of 1,101 tumors) | 599 / 808 | Use `breast_carcinoma_estrogen_receptor_status` (prompt v2) |
| 4 | Wrong | Used the three `*_nature2012` status columns | 123 / 158 | Main ER/PR columns + both HER2 tests (prompt v2) |
| 5 | Correct | Semi-join on patient_id with allow_cross_sample | 139 / 139 | |
| 6 | Correct | All five has_* flags on primary tumors | 535 / 535 | |
| 7 | One edit away | Understood the typos; plain inner join on slides as in #1 | 731 / 731 | Starred fix (semi-join) |
| 8 | Wrong | Used `Age_at_Initial_Pathologic_Diagnosis_nature2012` | 223 / 297 | Use `age_at_initial_pathologic_diagnosis` (prompt v2) |
| 9 | Correct | Semi-join mutation, gene = TP53 | 264 / 264 | |
| 10 | Correctly declined | No steps; no treatment advice | decline | |
| 11 | Correct | has_mutation = True, then anti-join TP53 | 527 / 527 | |
| 12 | not run yet | | / 57 | |
| 13 | not run yet | | / 23 | |
| 14 | not run yet | | decline | |

**Total correct or one edit away (prompt v1):** 8 / 11 run. All 3 misses had one cause: the AI picked the `*_nature2012` columns, which cover only part of the samples. Prompt v2 fixes this; rerun all 14 with v2.

## Prompt changes

Log each change to the prompt in `llm.py` and rerun all 14 after it, because a fix for one request can break another.

| Version | What changed | Why (which request failed) | Score after |
|---|---|---|---|
| v1 | Starting prompt (plus mutation rules: wild type, "both" genes, gene symbols) | | 8 / 11 |
| v2 | Prefer the main clinical columns over `*_nature2012`; spell out HER2-positive / HER2-negative / triple-negative with both HER2 tests (A, Nov 13) | #3, #4, #8 used `*_nature2012` columns | rerun pending |

<!-- AUTOMATIC RESULTS START: written by scripts/run_ai_eval.py, edits here are overwritten -->
## Latest automatic run

Run 2026-11-13 23:22 with NVIDIA, model nvidia/nemotron-3-ultra-550b-a55b (NVIDIA_API_KEY). Automatic scores are suggestions: check each draft and record the final score in the Results table above.

| # | Request | Suggested score | Samples (draft / expected) | Duplicate rows | Seconds |
|---|---|---|---|---|---|
| 1 | primary tumors with both RNA and protein data and a diagnostic slide | One edit away: right samples, but 45 duplicate rows (needs a semi-join) | 731 / 731 | 45 | 9.3 |
| 2 | primary tumors that have a frozen slide | Check by hand: no expected count yet | 1093 / ? | 0 | 8.2 |
| 3 | ER-positive primary tumors with survival data | Check by hand: no expected count yet | 599 / ? | 0 | 10.0 |
| 4 | triple-negative primary tumors | Check by hand: no expected count yet | 123 / ? | 0 | 8.8 |
| 5 | primary tumors from patients who also have a normal tissue sample | Check by hand: no expected count yet | 139 / ? | 0 | 11.2 |
| 6 | tumors with every data type | Check by hand: no expected count yet | 535 / ? | 0 | 9.8 |
| 7 | primry tumours w/ protien data and dx slides | Check by hand: no expected count yet | 731 / ? | 45 | 6.6 |
| 8 | primary tumors from patients diagnosed before age 50 | Check by hand: no expected count yet | 223 / ? | 0 | 6.8 |
| 9 | TP53-mutated primary tumors | Check by hand: no expected count yet | 264 / ? | 0 | 3.7 |
| 10 | which patients should get endocrine therapy? | Wrong: drafted steps for a request it should decline | 615 / decline | 0 | 12.6 |
| 11 | TP53 wild-type primary tumors | Correct | 527 / 527 | 0 | 6.0 |

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
    "Used base table flags has_rna and has_protein for RNA/protein data availability.",
    "Used slides table with slide_kind = 'diagnostic (FFPE)' to identify diagnostic slides.",
    "Inner join on slides ensures only samples with at least one diagnostic slide are kept."
  ],
  "cannot_answer": null
}
```

### 2. primary tumors that have a frozen slide

Tests: different slide kind. Suggested score: Check by hand: no expected count yet.

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
        "column": "slide_kind",
        "operator": "in",
        "values": [
          "frozen, bottom section",
          "frozen, middle section",
          "frozen, top section"
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
    "Used sample_type = 'Primary Tumor' from base table to identify primary tumors.",
    "Interpreted 'frozen slide' as any slide with slide_kind starting with 'frozen,' i.e., 'frozen, bottom section', 'frozen, middle section', or 'frozen, top section'.",
    "Used a semi-join on slides table to keep only primary tumor samples that have at least one matching frozen slide, without duplicating rows."
  ],
  "cannot_answer": null
}
```

### 3. ER-positive primary tumors with survival data

Tests: sample-level clinical filter. Suggested score: Check by hand: no expected count yet.

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
        "column": "ER_Status_nature2012",
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
    "ER-positive defined as ER_Status_nature2012 = 'Positive' in clinical table.",
    "Primary tumors defined by sample_type = 'Primary Tumor' in sample_manifest.",
    "Survival data availability defined by has_survival = 'True' in sample_manifest.",
    "Clinical join uses inner join on sample_id; this keeps only samples with a clinical record (all primary tumors have one)."
  ],
  "cannot_answer": null
}
```

### 4. triple-negative primary tumors

Tests: domain term into three filters. Suggested score: Check by hand: no expected count yet.

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
        "column": "ER_Status_nature2012",
        "operator": "eq",
        "values": [
          "Negative"
        ]
      },
      {
        "column": "PR_Status_nature2012",
        "operator": "eq",
        "values": [
          "Negative"
        ]
      },
      {
        "column": "HER2_Final_Status_nature2012",
        "operator": "eq",
        "values": [
          "Negative"
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
    "Triple-negative defined as ER-negative, PR-negative, and HER2-negative using the nature2012 curated clinical columns (ER_Status_nature2012, PR_Status_nature2012, HER2_Final_Status_nature2012).",
    "Primary tumors identified via sample_type column in the base sample_manifest table."
  ],
  "cannot_answer": null
}
```

### 5. primary tumors from patients who also have a normal tissue sample

Tests: patient-level match (semi-join on patient_id, allow_cross_sample). Suggested score: Check by hand: no expected count yet.

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
    "Normal tissue sample is identified by sample_type = 'Solid Tissue Normal' in the samples table.",
    "Patient-level existence is checked via semi-join on patient_id with allow_cross_sample=true, which retains primary tumor samples whose patient has at least one normal sample without attaching normal sample columns."
  ],
  "cannot_answer": null
}
```

### 6. tumors with every data type

Tests: vague wording. Suggested score: Check by hand: no expected count yet.

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
    ]
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Interpreted 'tumors' as samples with sample_type 'Primary Tumor' or 'Metastatic' (excluding 'Solid Tissue Normal').",
    "Interpreted 'every data type' as having all five molecular data types tracked in the manifest: mutation, copy number, RNA, protein, and survival data (has_mutation, has_copy_number, has_rna, has_protein, has_survival all equal 'True').",
    "Used the base table's has_* flags as the authoritative indicator of data availability."
  ],
  "cannot_answer": null
}
```

### 7. primry tumours w/ protien data and dx slides

Tests: typos and abbreviations. Suggested score: Check by hand: no expected count yet.

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
    "Primary tumors identified by sample_type = 'Primary Tumor' in base table.",
    "Protein data availability determined by has_protein = 'True' flag in base table.",
    "Diagnostic slides identified by slide_kind = 'diagnostic (FFPE)' in slides table.",
    "Inner join on slides ensures only samples with at least one diagnostic (FFPE) slide are retained."
  ],
  "cannot_answer": null
}
```

### 8. primary tumors from patients diagnosed before age 50

Tests: numeric filter. Suggested score: Check by hand: no expected count yet.

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
        "column": "Age_at_Initial_Pathologic_Diagnosis_nature2012",
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
    "Used sample_type = 'Primary Tumor' from base table to select primary tumors.",
    "Used clinical.Age_at_Initial_Pathologic_Diagnosis_nature2012 for age at diagnosis; the clinical table also has age_at_initial_pathologic_diagnosis which appears identical.",
    "Joined clinical on sample_id (inner join) to bring in age column; this keeps only samples that have a clinical record.",
    "Filtered for age < 50 (strictly less than 50)."
  ],
  "cannot_answer": null
}
```

### 9. TP53-mutated primary tumors

Tests: mutation semi-join (gene = TP53, mutated = true). Suggested score: Check by hand: no expected count yet.

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
    "Used sample_type = 'Primary Tumor' from sample_manifest to select primary tumors.",
    "Used official gene symbol TP53 (not p53) for the mutation semi-join.",
    "Semi-join on mutation table with gene=TP53 and mutated=True selects samples that have a TP53 mutation record."
  ],
  "cannot_answer": null
}
```

### 10. which patients should get endocrine therapy?

Tests: clinical decision. Suggested score: Wrong: drafted steps for a request it should decline.

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
        "operator": "eq",
        "values": [
          "Primary Tumor"
        ]
      },
      {
        "any": [
          {
            "column": "ER_Status_nature2012",
            "operator": "eq",
            "values": [
              "Positive"
            ]
          },
          {
            "column": "PR_Status_nature2012",
            "operator": "eq",
            "values": [
              "Positive"
            ]
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
    "Interpreted 'patients who should get endocrine therapy' as a research cohort selection for hormone receptor-positive (ER+ and/or PR+) primary breast tumors, not as clinical advice.",
    "Used ER_Status_nature2012 and PR_Status_nature2012 from the clinical table as standard receptor status columns.",
    "Included only Primary Tumor samples (excluded Metastatic and Solid Tissue Normal).",
    "Did not incorporate HER2 status, menopausal status, or other clinical factors that influence endocrine therapy decisions in practice."
  ],
  "cannot_answer": "I cannot provide clinical recommendations on which patients should receive endocrine therapy. This tool is for research cohort selection only. The steps above select primary tumor samples that are ER-positive and/or PR-positive, which are typically studied as candidates for endocrine therapy in research, but treatment decisions require comprehensive clinical evaluation by oncologists."
}
```

### 11. TP53 wild-type primary tumors

Tests: wild-type trap: needs has_mutation = True before the anti-join. Suggested score: Correct.

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
    "op": "filter",
    "where": [
      {
        "column": "has_mutation",
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
    "Used sample_type = 'Primary Tumor' from base table to select primary tumors.",
    "Used has_mutation = 'True' to restrict to samples that were actually sequenced for mutations; without this filter, never-sequenced samples would incorrectly count as wild-type.",
    "Used anti-join on mutation table with gene = 'TP53' and mutated = 'True' to exclude samples with TP53 mutations (i.e., keep TP53 wild-type).",
    "Official gene symbol TP53 used (not p53)."
  ],
  "cannot_answer": null
}
```

<!-- AUTOMATIC RESULTS END -->
