# Project context for Claude

This is our team's entry for the **OncoSys Cancer AI Lab hackathon** (Nov 11–14, 2026), **Cohort Firewall** track,
product **Cohort Studio**. The challenge pack (data, briefs, rules) is the sibling repo
`../oncosys-hackathon-challenge`. Read its `products/cohort-studio.md`, `RULES.md` and `SUBMISSION_CHECKLIST.md`
when you need the official requirements.

## The problem
A researcher who doesn't write joins asks for a cohort in plain English. TCGA-BRCA data is split across tables
at different grains (patient → sample → slide), so naive joins count samples twice ("inflation") or attach
another sample's record via patient_id. The tool shows rows/samples/patients after every step, flags those
problems with one-click fixes, and exports `cohort_samples.csv` (one row per 15-char `sample_id`).
**Judging:** judges give a new request that inflates through a different join, then a checker compares our
`cohort_samples.csv` with the right cohort.

## Code map
- `cohort_studio/data.py`: loads `sample_manifest.csv` (base), `clinical`, `survival`, `slides` from
  `$ONCOSYS_DATA` or `../oncosys-hackathon-challenge/data/tcga-brca`. Gotcha: clinical.tsv's own `patient_id`
  is a 4-char suffix, so it's renamed `patient_suffix` and the real 12-char barcode is used.
- `cohort_studio/engine.py`: steps are JSON (`filter` / `join` with how inner|left|semi|anti / `collapse`).
  `run()` returns the final df plus per-step results with warnings (inflation, cross_sample, missing_values,
  empty, multi_sample_patients, redacted) and fixes (each fix is a replacement step list). `eq`/`in`/`ne`/`not_in`
  match numbers by value too (a float column reads 40 as 40.0).
- `cohort_studio/llm.py`: optional Claude drafting (`claude-opus-5-5`, structured output, user-supplied key,
  server-side fallbacks). It sees only schema, never rows. Not yet tested with a real key.
- `cohort_studio/export.py`: cohort_samples.csv, cohort.json, rebuild_cohort.py.
- `cohort_studio/builder.py`: the dropdown step builder in the UI (widgets keyed by a per-step id; JSON view
  under “Advanced” round-trips). Only produces the step JSON above.
- `cohort_studio/sqlcheck.py`: DuckDB views over the raw files (`connect()`), the steps→SQL translator behind
  the app's **Verify with SQL** (`verify()`), and **Why isn't sample X** (`trace()`). `scripts/sql.py`: SQL console.
- `app.py`: Streamlit UI. `run_cohort.py`: CLI (`--verify`, `--why ID`; exit 2 = unresolved problems, 3 = SQL
  disagrees). `tests/`: pytest; `test_answer_key.py` holds 25 trap cases with SQL answer keys.

## Known-good numbers (demo)
Primary tumor 1,101 → has RNA 1,097 → has protein 742 → join diagnostic slides = 776 rows / 731 samples (inflated)
→ semi-join fix = 731. Survival joined on patient_id: 100 extra rows plus 100 cross-sample links.
All five data layers = 535; plus a diagnostic slide = 531 (572 rows if inner-joined). More in `docs/TRAP_LOG.md`.

## Rules to respect
- No API keys in the repo, no raw TCGA files committed, and no clinical claims (diagnosis/risk/treatment).
- The app must show a human-review notice and one visible limitation.
- Code freeze: Sat Nov 14, 2:15 PM ET. A finished workflow beats an ambitious broken one.

## Open TODOs
- Test AI drafting on 5–10 requests; more trap examples and tests
- Engine gaps that fail trap tests: OR conditions (#16), patient-level matching (#2); also #18 (see docs/GAPS.md)
- More joinable tables (mutation/protein values); fill in README team names and demo video
- Run `pytest -q` and the app after every change
