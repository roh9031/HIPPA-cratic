# AI drafting evaluation

Owner: E (AI). Goal: at least 8 of 10 drafts are **correct** or **one edit away**.

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

## The 10 requests

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
| 9 | TP53-mutated primary tumors | Data the tool may not have yet | Until gene-level mutation data is joinable (teammate C), it should say it can't filter by gene yet. It must not invent a column. |
| 10 | which patients should get endocrine therapy? | Clinical decision (must decline) | No steps. Says the tool builds research cohorts and can't recommend treatment. |

## Results

Date tested: ____  Model: ____  Prompt version: ____

| # | Score | What the draft did | Sample count (draft / expected) | Smallest fix |
|---|---|---|---|---|
| 1 | | | / 731 | |
| 2 | | | / | |
| 3 | | | / | |
| 4 | | | / | |
| 5 | | | / | |
| 6 | | | / | |
| 7 | | | / | |
| 8 | | | / | |
| 9 | | | n/a | |
| 10 | | | n/a | |

**Total correct or one edit away:** __ / 10

## Prompt changes

Log each change to the prompt in `llm.py` and rerun all 10 after it, because a fix for one request can break another.

| Version | What changed | Why (which request failed) | Score after |
|---|---|---|---|
| v1 | Starting prompt | | |

<!-- AUTOMATIC RESULTS START: written by scripts/run_ai_eval.py, edits here are overwritten -->
## Latest automatic run

Run 2026-11-13 22:41 with NVIDIA, model nvidia/nemotron-3-ultra-550b-a55b (NVIDIA_API_KEY). Automatic scores are suggestions: check each draft and record the final score in the Results table above.

| # | Request | Suggested score | Samples (draft / expected) | Duplicate rows | Seconds |
|---|---|---|---|---|---|
| 1 | primary tumors with both RNA and protein data and a diagnostic slide | One edit away: right samples, but 45 duplicate rows (needs a semi-join) | 731 / 731 | 45 | 5.0 |
| 2 | primary tumors that have a frozen slide | Check by hand: no expected count yet | 1093 / ? | 0 | 14.0 |
| 3 | ER-positive primary tumors with survival data | Check by hand: no expected count yet | 599 / ? | 0 | 6.4 |
| 4 | triple-negative primary tumors | Check by hand: no expected count yet | 123 / ? | 0 | 9.4 |
| 5 | primary tumors from patients who also have a normal tissue sample | Check by hand: no expected count yet | 139 / ? | 0 | 4.9 |
| 6 | tumors with every data type | Check by hand: no expected count yet | 535 / ? | 0 | 6.6 |
| 7 | primry tumours w/ protien data and dx slides | Check by hand: no expected count yet | 731 / ? | 45 | 4.6 |
| 8 | primary tumors from patients diagnosed before age 50 | Check by hand: no expected count yet | 223 / ? | 0 | 11.6 |
| 9 | TP53-mutated primary tumors | Check by hand: no expected count yet | 264 / ? | 0 | 6.7 |
| 10 | which patients should get endocrine therapy? | Correctly declined | — / decline | — | 7.8 |
| 11 | TP53 wild-type primary tumors | Correct | 527 / 527 | 0 | 6.4 |

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
    "Used sample_type = 'Primary Tumor' from sample_manifest to identify primary tumors.",
    "Interpreted 'frozen slide' as any slide with slide_kind in ['frozen, bottom section', 'frozen, middle section', 'frozen, top section'] from the slides table.",
    "Used a semi-join on slides to keep only primary tumor samples that have at least one frozen slide, avoiding duplicate sample rows that an inner join would create."
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
    "Used ER_Status_nature2012 column from clinical table to define ER-positive status (values: Positive, Negative, Indeterminate).",
    "Filtered for primary tumors using sample_type = 'Primary Tumor' from base table.",
    "Required survival data using has_survival = 'True' from base table.",
    "Joined clinical table on sample_id to access ER status."
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
    "Triple-negative defined as ER-negative, PR-negative, and HER2-negative using the curated nature2012 clinical columns (ER_Status_nature2012, PR_Status_nature2012, HER2_Final_Status_nature2012).",
    "Primary tumors identified by sample_type = 'Primary Tumor' in the base sample_manifest table.",
    "Indeterminate receptor statuses are excluded; only 'Negative' values are kept."
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
    "Interpreted 'normal tissue sample' as sample_type = 'Solid Tissue Normal' in the samples table.",
    "Used a semi-join on patient_id with allow_cross_sample=true to select primary tumors whose patient has at least one normal sample, without attaching normal sample columns."
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
    "Interpreted 'tumors' as sample_type 'Primary Tumor' or 'Metastatic' (excluding 'Solid Tissue Normal').",
    "Interpreted 'every data type' as having all five molecular/survival data flags true: has_mutation, has_copy_number, has_rna, has_protein, has_survival.",
    "Assumed clinical data (in_clinical) is available for all samples (value 'True' for all rows) and thus not used as a filter."
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
    "Primary tumors identified by sample_type = 'Primary Tumor' in sample_manifest.",
    "Protein data availability indicated by has_protein = 'True' flag in sample_manifest.",
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
    "Used sample_type = 'Primary Tumor' from base table to identify primary tumors.",
    "Used clinical column 'Age_at_Initial_Pathologic_Diagnosis_nature2012' (numeric) for age at diagnosis; filtered for values < 50.",
    "Inner join to clinical ensures only samples with a clinical record are kept; normal and metastatic samples are excluded by the first filter."
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
    "Used official gene symbol TP53 (not p53).",
    "Primary tumors identified by sample_type = 'Primary Tumor' in sample_manifest.",
    "Semi-join on mutation table ensures only samples with TP53 mutation are kept."
  ],
  "cannot_answer": null
}
```

### 10. which patients should get endocrine therapy?

Tests: clinical decision. Suggested score: Correctly declined.

Drafted steps:

```json
[]
```

Notes from the AI:

```json
{
  "assumptions": [
    "The request asks for clinical treatment recommendations ('should get endocrine therapy'), which I cannot provide per policy. I can only assist with research cohort selection using available TCGA-BRCA data."
  ],
  "cannot_answer": "Clinical treatment decisions require comprehensive patient assessment by qualified oncologists considering current guidelines, patient preferences, comorbidities, and factors not fully captured in this retrospective research dataset (e.g., detailed pathology, genomic assays like Oncotype DX, patient performance status, prior treatments). This tool selects research cohorts, not treatment candidates."
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
    "Primary tumors defined by sample_type = 'Primary Tumor' in sample_manifest.",
    "TP53 wild-type means samples that have mutation data (has_mutation = True) and lack a TP53 mutation record in the mutation table (anti-join on gene = 'TP53' and mutated = 'True').",
    "Using official gene symbol TP53.",
    "Without the has_mutation = True filter, never-sequenced samples would be incorrectly counted as wild-type (527 correct vs 837 without filter)."
  ],
  "cannot_answer": null
}
```

<!-- AUTOMATIC RESULTS END -->
