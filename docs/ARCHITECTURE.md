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
| Independent check | **DuckDB** | The app's **Verify with SQL** button translates the steps into one SQL query and runs it on the raw files without the engine (`sqlcheck.py`), so a judge can check the count themselves |
| Tests | **pytest** + **DuckDB** | pytest pins the demo numbers and trap behavior. DuckDB is the **independent answer key**: each test case writes the correct cohort as plain SQL on the raw files and checks that the engine's export matches it exactly (`tests/test_answer_key.py`) |
| Data | Frozen TCGA-BRCA release from the challenge repo | Required by the rules. Checked against `sources.csv` checksums |

There's no database and no separate backend. `streamlit run app.py` starts a local web server that runs the
Python directly, and the frozen CSV/TSV files are read into memory. The brief suggests DuckDB. We use it where it
adds the most, as a second, independent implementation that checks the engine's answers, the same way the
judges' checker does.

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
 │  Step list (JSON)        │ ◀── user edits it with dropdowns (builder.py; JSON view for power users)
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
        │      ┌──────────────────────────┐
        ├────▶ │  sqlcheck.py (DuckDB)    │  same steps as SQL: Verify (engine = SQL?)
        │      │                          │  and trace one sample (why was it removed?)
        │      └──────────────────────────┘
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
| `cohort_studio/data.py` | Finds the data folder (`$ONCOSYS_DATA` or `../oncosys-hackathon-challenge/data/tcga-brca`), loads and caches tables, normalises keys to `sample_id` / `patient_id`, verifies checksums. Registry of joinable tables: `TABLES`. **Changed releases** (the challenge's `make_release.py` format): `ONCOSYS_RELEASE`, the sidebar picker or `--release`; `file_path()` reads a file from the release if it has one, else from the original data. |
| `cohort_studio/custom.py` | **Use your own data**: CSV uploads or a Supabase project (REST API, the user's URL and key, session only). The user picks the sample list and ID columns; `build()` writes a data folder with keys renamed to `sample_id` / `patient_id`, `activate()` swaps `data.TABLES`. The engine, fixes, builder, exports and Verify with SQL run unchanged; TCGA-only extras (makeup, Data notes, AI, examples) are off. |
| `cohort_studio/engine.py` | Validates and runs steps. After each step: counts, inflation check, cross-sample check, missing-value note, empty-result check. At the end: multi-sample-patient note. `unresolved_problems()` gates export. |
| `cohort_studio/llm.py` (+ `llm_nvidia.py`) | Builds a schema description (column names plus short category values), calls Claude or NVIDIA Nemotron (user's key; an `nvapi-` key is routed to NVIDIA) with a strict JSON schema, returns `steps`, `assumptions` and `cannot_answer`. Evaluated in `docs/AI_EVAL.md` (14/14). |
| `cohort_studio/advice.py` | Ranks the fixes a warning offers: which one the UI stars, why, and what's wrong with the others. Judges a fix by what it changes, not its label, and defers to the engine if a fix is marked `recommended`. |
| `cohort_studio/versions.py` | Remembers each distinct cohort built in a session (in session state only) and diffs two of them: counts, the samples that moved, and a one-sentence summary. |
| `cohort_studio/export.py` | One row per unique 15-char `sample_id`. Definition JSON with funnel and file hashes. A rebuild script. |
| `cohort_studio/builder.py` | The dropdown step builder: renders the step list as widgets, keyed by a per-step id so moving or deleting a step keeps everyone's values, and keeps the “Advanced: JSON” box in sync both ways. Conditions are rows joined by an `and`/`or` connector: a run of `or` rows is one `{"any": [...]}` group, so OR requests are built with dropdowns (a nested group still loads, shown read-only, and is edited in the JSON). Column and value choices for a step come from the cohort *as of that step* (it runs the engine on the steps before it). Only produces the step format below. |
| `cohort_studio/sqlcheck.py` | DuckDB views over the raw files. Translates a step list into one SQL query (a CTE per step) for **Verify with SQL**, and traces one sample through it for **Why isn't sample X in my cohort?**. Doesn't use the engine's code, so it's an independent check. |
| `cohort_studio/makeup.py` | Did a step change who's in the cohort? Per step, total variation distance of the site, PAM50 subtype, ER status and age-band mix before vs after (sample lists from the same per-step DuckDB SQL, attributes from the raw files). Note at ≥ 0.10, skipped below 30 samples, "expected" when the step filters on that attribute. |
| `app.py` | Streamlit page: 1 describe → 2 build → 3 funnel, warnings, sample trace → 4 review, Verify with SQL, export. |
| `run_cohort.py` | Same engine from the command line. `--verify`, `--why ID`, `--makeup` and `--release`. Exit code 2 if problems remain, 3 if the SQL check disagrees. |
| `scripts/sql.py` | DuckDB SQL console for writing answer keys (`-f file.sql` runs a file). |

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
- `allow_cross_sample`: optional boolean for intentional patient-level existence checks. It is valid only
  with `on: "patient_id"` and `how: "semi"` or `"anti"`. It suppresses the cross-sample warning because
  the step selects the current samples based on another sample from the same patient; it does not attach
  the other sample's columns. Row-producing patient joins remain unsafe and are still warned.
- `where`: conditions are ANDed by default. An item such as `{"any": [condition, condition]}`
  creates an OR group; nested `all` groups support OR expressions containing multiple AND conditions.
  The builder draws a flat `any` group as a run of `or` rows and writes it back in the same shape
  (`builder._flatten` / `_regroup`); anything nested is passed through untouched.
- `operator`: `in`, `not_in`, `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `notnull`, `isnull`, `startswith`, `contains`
  (text matching ignores case)

The optional `allow_cross_sample` field is the explicit opt-in for patient-level existence matching. Without
it, patient-level joins retain the safety warning for possible cross-sample links. Changes to this contract
affect the UI builder, the AI schema and the engine.

## Open questions for the team

1. **pandas or DuckDB in the engine?** Current choice: the engine stays on pandas (the data is small and the row-level checks are one-liners), and DuckDB is the test answer key. Done Nov 12: the "Verify with SQL" panel shows the equivalent SQL and runs it.
2. ~~**Dropdowns or a node canvas?**~~ Decided: dropdowns (`builder.py`, Nov 12). A node canvas was judged too risky for the time left.
3. **Which tables to add?** Mutation and protein values would let judges ask "with a TP53 mutation". Each new table needs a grain and a key in `data.TABLES`.
4. **Inner join default:** a *new* join step starts at `semi`, and picking a finer-grained table with `inner`/`left` shows a caption saying the join will repeat samples. Should the UI go further and switch `how` automatically? (It doesn't, so the user's choice is never changed behind their back.)
5. **Standalone rebuild script?** `rebuild_cohort.py` currently needs this repo installed. Is that acceptable for "a workflow someone else can rerun"?
6. **Patient-level requests** like "tumors whose patient also has a matched normal sample": use a semi-join
   with `allow_cross_sample: true` for intentional existence matching. Row-producing patient joins remain
   flagged because they can attach another sample's record.
7. **Deploy?** Run locally for judging, or also host it (e.g. Streamlit Community Cloud) as a backup?
