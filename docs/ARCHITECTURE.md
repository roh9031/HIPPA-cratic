# Architecture: Cohort Studio

This describes the system **as it is now**. The last section lists decisions the team should talk through.
Edit this file when we decide.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3 | The whole team can read it, and it's what the data starter uses |
| Data processing | **pandas** | The tables are small (~1.2k samples, a few thousand slides), so everything fits in memory |
| UI | **Streamlit** | A web UI in pure Python with no frontend build. The brief suggests it |
| AI (optional) | **Anthropic Claude** (`claude-opus-5-5`), structured JSON output | Turns plain English into steps. Uses a key the user supplies, never stored |
| Tests | **pytest** | Pins the demo numbers and trap behavior |
| Data | Frozen TCGA-BRCA release from the challenge repo | Required by the rules. Checked against `sources.csv` checksums |

There's no database and no backend server. Streamlit runs the Python directly. The brief also suggests
DuckDB, but pandas is enough at this data size (see open questions).

## System design

```
 plain-English request
        │
        ▼
 ┌──────────────┐  schema only     ┌──────────────┐
 │  llm.py      │ ───────────────▶ │  Claude API  │   (optional, user's key)
 │  draft steps │ ◀─────────────── │              │
 └──────┬───────┘  steps JSON +    └──────────────┘
        │          assumptions
        ▼
 ┌──────────────────────────┐
 │  Step list (JSON)        │ ◀── user edits it (JSON box today, dropdowns soon)
 └──────┬───────────────────┘ ◀── "Apply fix" buttons replace it
        ▼
 ┌──────────────────────────┐     ┌──────────────────────────┐
 │  engine.run(steps)       │ ◀── │  data.py                 │
 │  per step: rows /        │     │  sample_manifest (base)  │
 │  samples / patients      │     │  clinical, survival,     │
 │  + warnings + fixes      │     │  slides  (+ checksums)   │
 └──────┬───────────────────┘     └──────────────────────────┘
        ▼
 ┌──────────────────────────┐
 │  app.py (UI) / CLI       │  funnel table, chart, problem boxes, fix buttons
 └──────┬───────────────────┘
        ▼
 ┌──────────────────────────┐
 │  export.py               │  cohort_samples.csv · cohort.json · rebuild_cohort.py
 └──────────────────────────┘
```

**The core idea:** the AI only *proposes* steps. Every number comes from the engine, which is ordinary,
testable code. The model never sees patient rows.

### Modules

| File | Responsibility |
|---|---|
| `cohort_studio/data.py` | Finds the data folder (`$ONCOSYS_DATA` or `../oncosys-hackathon-challenge/data/tcga-brca`), loads and caches tables, normalises keys to `sample_id` / `patient_id`, verifies checksums. Registry of joinable tables: `TABLES`. |
| `cohort_studio/engine.py` | Validates and runs steps. After each step: counts, inflation check, cross-sample check, missing-value note, empty-result check. At the end: multi-sample-patient note. `unresolved_problems()` gates export. |
| `cohort_studio/llm.py` | Builds a schema description (column names plus short category values), calls Claude with a strict JSON schema, returns `steps`, `assumptions` and `cannot_answer`. |
| `cohort_studio/export.py` | One row per unique 15-char `sample_id`. Definition JSON with funnel and file hashes. A rebuild script. |
| `app.py` | Streamlit page: 1 describe → 2 edit → 3 funnel and warnings → 4 review and export. |
| `run_cohort.py` | Same engine from the command line. Exit code 2 if problems remain. |

### The data's grains (the root cause of every trap)

```
patient (12-char barcode, TCGA-XX-XXXX)
  └── sample (15-char, TCGA-XX-XXXX-01)   ← cohort grain; 01 = primary tumor, 11 = normal
        └── slide (several per sample; diagnostic FFPE or frozen)
```

- Joining a **finer** table (slides) onto samples → **inflation** (a sample repeats).
- Joining on **patient_id** → **cross-sample links** (a tumor sample gets its normal sample's record).
- Gotcha: `clinical.tsv`'s own `patient_id` is a 4-char suffix. `data.py` renames it to `patient_suffix`.

### Step format (the contract between UI, AI and engine)

```json
[
  {"op": "filter", "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]},
  {"op": "join", "table": "slides", "on": "sample_id", "how": "semi",
   "where": [{"column": "slide_kind", "operator": "startswith", "values": ["diagnostic"]}]},
  {"op": "collapse", "level": "sample"}
]
```

- `op`: `filter` | `join` | `collapse`
- `how`: `inner` | `left` | `semi` (keep if a match exists, never duplicates) | `anti` (drop if a match exists)
- `on`: `sample_id` | `patient_id`
- `operator`: `in`, `not_in`, `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `notnull`, `isnull`, `startswith`, `contains`
  (text matching ignores case)

**Changing this format affects the UI builder, the AI schema and the engine. Agree on any change first.**

## Open questions for the team

1. **pandas or DuckDB?** pandas works now and the data is small. DuckDB would let us show SQL to users. Proposal: stay on pandas.
2. **Dropdowns or a node canvas?** The brief allows either. Dropdowns are much less risky in 3 days. Proposal: dropdowns.
3. **Which tables to add?** Mutation and protein values would let judges ask "with a TP53 mutation". Each new table needs a grain and a key in `data.TABLES`.
4. **Inner join default:** should the UI suggest `semi` by default when a user picks a slide-grain table?
5. **Standalone rebuild script?** `rebuild_cohort.py` currently needs this repo installed. Is that acceptable for "a workflow someone else can rerun"?
6. **Deploy?** Run locally for judging, or also host it (e.g. Streamlit Community Cloud) as a backup?
