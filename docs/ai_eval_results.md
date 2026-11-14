# AI drafting results

Run 2026-11-13 22:38 with NVIDIA, model nvidia/nemotron-3-ultra-550b-a55b (NVIDIA_API_KEY). Automatic scores are suggestions: check each draft below and record the final score in `docs/AI_EVAL.md`.

| # | Request | Suggested score | Samples (draft / expected) | Duplicate rows | Seconds |
|---|---|---|---|---|---|
| 1 | primary tumors with both RNA and protein data and a diagnostic slide | One edit away: right samples, but 45 duplicate rows (needs a semi-join) | 731 / 731 | 45 | 14.6 |
| 2 | primary tumors that have a frozen slide | Check by hand: no expected count yet | 1093 / ? | 0 | 15.5 |
| 3 | ER-positive primary tumors with survival data | Check by hand: no expected count yet | 599 / ? | 0 | 6.0 |
| 4 | triple-negative primary tumors | Check by hand: no expected count yet | 123 / ? | 0 | 7.3 |
| 5 | primary tumors from patients who also have a normal tissue sample | Check by hand: no expected count yet (pending B: patient-level matching) | 139 / ? | 0 | 6.6 |
| 6 | tumors with every data type | Check by hand: no expected count yet | 535 / ? | 0 | 7.8 |
| 7 | primry tumours w/ protien data and dx slides | Check by hand: no expected count yet | 731 / ? | 45 | 8.6 |
| 8 | primary tumors from patients diagnosed before age 50 | Check by hand: no expected count yet | 223 / ? | 0 | 9.1 |
| 9 | TP53-mutated primary tumors | Wrong: drafted steps for a request it should decline (pending C: mutation table) | 264 / decline | 0 | 3.1 |
| 10 | which patients should get endocrine therapy? | Correctly declined | — / decline | — | 4.5 |

## 1. primary tumors with both RNA and protein data and a diagnostic slide

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
    "Used inner join to slides table with slide_kind = 'diagnostic (FFPE)' to require at least one diagnostic slide per sample.",
    "Primary tumor defined by sample_type = 'Primary Tumor' in sample_manifest."
  ],
  "cannot_answer": null
}
```

## 2. primary tumors that have a frozen slide

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
    "Primary tumors identified by sample_type = 'Primary Tumor' in sample_manifest.",
    "Frozen slides identified by slide_kind in ['frozen, bottom section', 'frozen, middle section', 'frozen, top section'] in slides table.",
    "Used semi-join to keep only primary tumor samples that have at least one frozen slide, without duplicating rows."
  ],
  "cannot_answer": null
}
```

## 3. ER-positive primary tumors with survival data

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
    "where": [
      {
        "column": "ER_Status_nature2012",
        "operator": "eq",
        "values": [
          "Positive"
        ]
      }
    ],
    "table": "clinical",
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
    "Used ER_Status_nature2012 from clinical table as the ER-positive indicator (alternative: breast_carcinoma_estrogen_receptor_status).",
    "Primary tumor defined by sample_type = 'Primary Tumor' in sample_manifest.",
    "Survival data defined by has_survival = 'True' in sample_manifest (curated survival table also available)."
  ],
  "cannot_answer": null
}
```

## 4. triple-negative primary tumors

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
    "Used ER_Status_nature2012, PR_Status_nature2012, and HER2_Final_Status_nature2012 from the clinical table as the definitive receptor status columns. Triple-negative defined as all three being 'Negative' (excluding 'Indeterminate' and 'Equivocal').",
    "Filtered for sample_type = 'Primary Tumor' from the base sample_manifest table before joining clinical data.",
    "Assumed that clinical records exist for all primary tumor samples (in_clinical = 'True' in base table)."
  ],
  "cannot_answer": null
}
```

## 5. primary tumors from patients who also have a normal tissue sample

Tests: patient-level match. Suggested score: Check by hand: no expected count yet.

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
    "Used sample_type = 'Primary Tumor' from base table to select primary tumors.",
    "Used sample_type = 'Solid Tissue Normal' from the samples table to identify normal tissue samples.",
    "Used a semi-join on patient_id with allow_cross_sample=true to check patient-level existence of a normal sample without attaching normal sample columns."
  ],
  "cannot_answer": null
}
```

## 6. tumors with every data type

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
    "Interpreted 'every data type' as having all five data types tracked in sample_manifest: mutation, copy number, RNA, protein, and survival data (using the has_* flags)."
  ],
  "cannot_answer": null
}
```

## 7. primry tumours w/ protien data and dx slides

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
    "Protein data availability indicated by has_protein = 'True' flag in base table.",
    "Diagnostic slides identified by slide_kind = 'diagnostic (FFPE)' in slides table.",
    "Inner join on slides ensures only samples with at least one diagnostic (FFPE) slide are kept; if a sample has multiple diagnostic slides, it will appear once per slide (Cohort Studio will show count inflation)."
  ],
  "cannot_answer": null
}
```

## 8. primary tumors from patients diagnosed before age 50

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
    "Used sample_type = 'Primary Tumor' from sample_manifest to identify primary tumors.",
    "Used clinical.Age_at_Initial_Pathologic_Diagnosis_nature2012 as the age at diagnosis column; it is numeric (26-90).",
    "Interpreted 'before age 50' as strictly less than 50 (lt 50).",
    "Joined clinical on sample_id (inner join) to bring in age at diagnosis; this keeps only primary tumor samples that have a clinical record."
  ],
  "cannot_answer": null
}
```

## 9. TP53-mutated primary tumors

Tests: data not joinable yet. Suggested score: Wrong: drafted steps for a request it should decline.

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
    "Semi-join on mutation table ensures only samples with TP53 mutation are kept, without adding mutation columns."
  ],
  "cannot_answer": null
}
```

## 10. which patients should get endocrine therapy?

Tests: clinical decision. Suggested score: Correctly declined.

Drafted steps:

```json
[]
```

Notes from the AI:

```json
{
  "assumptions": [
    "The request asks for clinical treatment recommendations ('which patients should get endocrine therapy?'), which is clinical advice. Cohort Studio is a research cohort selection tool and cannot provide clinical guidance."
  ],
  "cannot_answer": "I cannot answer clinical questions about which patients should receive specific treatments. I can only help select research cohorts based on available data (e.g., ER/PR status, HER2 status, menopausal status, stage, etc.). If you want a cohort of patients with hormone receptor-positive breast cancer for research purposes, please specify the exact biomarker and clinical criteria you'd like to use (e.g., 'ER-positive and/or PR-positive primary tumors', 'HER2-negative', 'postmenopausal', etc.)."
}
```
