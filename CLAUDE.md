# Project context for Claude

This is our team's entry for the **OncoSys Cancer AI Lab hackathon** (Nov 11–14, 2026), **Cohort Firewall** track,
product **Cohort Studio**, team **HIPPA-cratics**: A Rohini Bidnurmath (captain, trap hunter / SQL),
B Rae Michelle (engine), C Hanpeng Yang (data), D Sonal Gabburi (UI), E Ronit Jariwala (AI). The challenge pack (data, briefs, rules) is the sibling repo
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
- `cohort_studio/data.py`: loads `sample_manifest.csv` (base), `clinical`, `survival`, `mutation` (gene-level presence, one row per
  mutated sample-gene; 791 sequenced samples = `has_mutation`), `slides` from
  `$ONCOSYS_DATA` or `../oncosys-hackathon-challenge/data/tcga-brca`. Gotcha: clinical.tsv's own `patient_id`
  is a 4-char suffix, so it's renamed `patient_suffix` and the real 12-char barcode is used.
  Releases: `ONCOSYS_RELEASE` (folder or name under `<data>/releases/`), `run_cohort.py --release`, the sidebar
  box, or ONCOSYS_DATA pointed at a release folder. `data.file_path()` picks the release's copy of a file if it
  has one, else the original; sqlcheck reads the same paths. `tests/test_release.py`.
- `cohort_studio/custom.py`: **Use your own data** (sidebar). CSV uploads or Supabase (REST, user's URL + key)
  -> `build()` writes a folder (sample_manifest.csv + one CSV per table, keys renamed sample_id/patient_id,
  marker file `data.CUSTOM_MARK`) -> `activate()` swaps `data.TABLES` in place and sets ONCOSYS_DATA.
  `data._load` and `sqlcheck.connect` have a plain-CSV path for it; makeup, Data notes, AI and examples are off.
  Synthetic example: `examples/byod_synthetic/`. Tests: `tests/test_custom.py`.
- `cohort_studio/engine.py`: steps are JSON (`filter` / `join` with how inner|left|semi|anti / `collapse`).
  `run()` returns the final df plus per-step results with warnings (inflation, cross_sample, missing_values, any_vs_all, value_not_found, unsequenced_mutation,
  empty, multi_sample_patients, redacted) and fixes (each fix is a replacement step list). `eq`/`in`/`ne`/`not_in`
  match numbers by value too (a float column reads 40 as 40.0). `Indeterminate` and `[...]` codes count as
  missing (GAPS #7); the SQL check mirrors this in `_cond_sql`. "Not mutated" needs `has_mutation = True`
  first (GAPS #31: TP53 wild type 527, not 837; the engine warns and offers that fix).
  Also warns `any_vs_all` (`gene in [A, B]` = A or B; "both" = one step each, #32) and
  `value_not_found` (HER2 → ERBB2, typos; #33).
- `cohort_studio/llm.py`: optional AI drafting (E). Claude (`claude-opus-5-5`, key in the sidebar or
  ANTHROPIC_API_KEY) by default; NVIDIA (`llm_nvidia.py`, NVIDIA_API_KEY) if no Claude key (the team uses NVIDIA;
  Groq was dropped: its free-tier rate limits failed). Sees only schema, never rows. Eval: `scripts/run_ai_eval.py`,
  `docs/AI_EVAL.md` (14 requests; prompt v3 scored 14/14 on NVIDIA Nemotron Ultra, Nov 14).
- `cohort_studio/advice.py`: which fix the UI stars (GAPS #21), with a reason and caveats on the others.
- `cohort_studio/versions.py`: session-only cohort versions and the diff between two of them (GAPS #26).
- `cohort_studio/export.py`: cohort_samples.csv, cohort.json, rebuild_cohort.py.
- `cohort_studio/builder.py`: the dropdown step builder in the UI (widgets keyed by a per-step id; JSON view
  under “Advanced” round-trips). Only produces the step JSON above.
- `cohort_studio/sqlcheck.py`: DuckDB views over the raw files (`connect()`), the steps→SQL translator behind
  the app's **Verify with SQL** (`verify()`), and **Why isn't sample X** (`trace()`). `scripts/sql.py`: SQL console.
- `cohort_studio/makeup.py`: after each step, TVD of site / PAM50 / ER / age-band mix before vs after (note at
  ≥ 0.10; a shift on a filtered attribute is "expected"). Demo protein step: site 0.14, PAM50 0.16.
- `app.py`: Streamlit UI. `run_cohort.py`: CLI (`--verify`, `--why ID`, `--makeup`; exit 2 = unresolved problems, 3 = SQL
  disagrees). `tests/`: pytest; `test_trap_requests.py` holds 31 trap cases with SQL answer keys.

## Known-good numbers (demo)
Primary tumor 1,101 → has RNA 1,097 → has protein 742 → join diagnostic slides = 776 rows / 731 samples (inflated)
→ semi-join fix = 731. Survival joined on patient_id: 100 extra rows plus 100 cross-sample links.
All five data layers = 535; plus a diagnostic slide = 531 (572 rows if inner-joined). More in `docs/TRAP_LOG.md`.

## Rules to respect
- Organizer data rule (Nov 12): `sample_manifest.csv` is the official sample list. Samples only in the slide
  manifest (24 normals) stay out; redacted survival rows (6) stay in and are flagged. Point out mismatches.
- No API keys in the repo, no raw TCGA files committed, and no clinical claims (diagnosis/risk/treatment).
- The app must show a human-review notice and one visible limitation.
- Code freeze: Sat Nov 14, 2:15 PM ET. A finished workflow beats an ambitious broken one.

## Open TODOs
- OR groups (`{"any"/"all": [...]}`) and patient-level matching (`allow_cross_sample`) work in the engine,
  the builder (and/or switch per condition; nested groups read-only) and the SQL check; all 31 trap cases pass. Next gaps in docs/GAPS.md
- More joinable tables (mutation/protein values); add the demo video link to the README
- Run `pytest -q` and the app after every change
