# AI drafting results

Run 2026-11-13 20:51 with NVIDIA, model nvidia/nemotron-3-ultra-550b-a55b (NVIDIA_API_KEY). Automatic scores are suggestions: check each draft below and record the final score in `docs/ai_eval.md`.

| # | Request | Suggested score | Samples (draft / expected) | Duplicate rows | Seconds |
|---|---|---|---|---|---|
| 1 | primary tumors with both RNA and protein data and a diagnostic slide | One edit away: right samples, but 45 duplicate rows (needs a semi-join) | 731 / 731 | 45 | 8.6 |

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
    "how": "inner"
  }
]
```

Notes from the AI:

```json
{
  "assumptions": [
    "Used sample_manifest.sample_type = 'Primary Tumor' to select primary tumors.",
    "Used has_rna = 'True' and has_protein = 'True' flags in sample_manifest for RNA and protein data availability.",
    "Interpreted 'a diagnostic slide' as at least one slide with slide_kind = 'diagnostic (FFPE)' in the slides table, using an inner join to ensure existence."
  ],
  "cannot_answer": null
}
```
