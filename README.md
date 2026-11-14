# Cohort Studio · Cohort Firewall track

**User:** a researcher who needs a TCGA-BRCA cohort but doesn't write joins for a living.

**Workflow they finish:** describe a cohort in plain English (or build it from dropdowns), see how many
rows, samples and patients survive every step, get told exactly where a join inflates the count or links
a record to the wrong sample, fix it with one click, and export `cohort_samples.csv` plus a script that
rebuilds the cohort.

**Team HIPPA-cratics:** Rohini Bidnurmath (captain) · Rae Michelle · Hanpeng Yang · Sonal Gabburi · Ronit Jariwala

**Demo video:** _add link_ (screen recording, no audio). What it shows, in order:
1. **Main workflow:** the demo request ("primary tumors with both RNA and protein data and a diagnostic slide") and its 4 steps; the funnel goes 1,101 → 1,097 → 742 →
   **776 rows / 731 samples**. The diagnostic-slide join is flagged (45 tumors have two slides), the recommended fix
   is applied in one click, and rows = samples = 731.
2. **Dropdown builder with and/or:** HER2-positive by either lab test (**or**) = 197 tumors, by both (**and**) = 45.
   *Compare with an earlier version* lists the samples that changed.
3. **Verify with SQL:** an independent DuckDB query over the raw files gets 731 too, matching at every step.
4. **Why isn't a sample in my cohort?** `TCGA-E2-A15E-01` was removed at the slide step (its only slide is frozen).
5. **Did a step change who's in the cohort?** Requiring protein data shifts the site mix (TVD 0.14) and the PAM50
   mix (0.16).
6. **A different join that inflates:** survival joined on `patient_id` gives 907 rows / 807 samples and 100 records
   linked to another sample of the same patient; the recommended fix (match on `sample_id`) gives 807.
7. **Mutation traps:** "both TP53 and PIK3CA" written as one step means either gene (480); the fix gives 57.
   `HER2` as a gene name suggests `ERBB2`.
8. **Review and export:** human-review notice with a visible limitation, Data notes, and the exports
   (`cohort_samples.csv`, `cohort.json`, `rebuild_cohort.py`).

**Teammates, start here:** [docs/TEAM_PLAN.md](docs/TEAM_PLAN.md) (roles, timeline, git workflow) ·
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (tech stack, system design, open questions)

## Setup
Clone this repo **next to** the challenge repo (or set `ONCOSYS_DATA` to its `data/tcga-brca` folder):
```
oncosyshackathon/
├── oncosys-hackathon-challenge/
└── cohort-studio/
```
```bash
mkdir oncosyshackathon && cd oncosyshackathon
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git
git clone https://github.com/roh9031/HIPPA-cratic.git cohort-studio      # note: clone into "cohort-studio"
cd oncosys-hackathon-challenge && python data/tcga-brca/fetch.py && cd ..   # downloads ~70 MB, checks checksums
cd cohort-studio
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
macOS/Linux: if `python` isn't found, use `python3` for the `fetch.py` and `venv` lines; after activating the venv,
`python` works. Windows: keep the folder path short (e.g. `D:\oncosyshackathon`). A very deep path can make `pip install` fail on
the long-path limit. In `cmd`, switching drives needs `cd /d D:\oncosyshackathon`.

## Run
```bash
streamlit run app.py                                         # the app
python run_cohort.py examples/demo_diagnostic_slides.json    # same engine from the command line
python run_cohort.py examples/demo_diagnostic_slides.json --verify --why TCGA-E2-A15E-01   # SQL check + trace one sample
python run_cohort.py examples/demo_diagnostic_slides.json --makeup   # did a step change who's in the cohort?
python run_cohort.py --ask "ER-positive primary tumors with a diagnostic slide"   # AI draft: ANTHROPIC_API_KEY or NVIDIA_API_KEY (in the app: paste either key in the sidebar)
python scripts/sql.py                                        # DuckDB SQL console over the raw files
python run_cohort.py examples/demo_diagnostic_slides.json --release practice-B --verify   # on a changed data release
pytest -q                                                    # 171 tests, see below
```
`run_cohort.py` exits with code 2 if the cohort still has duplicates or cross-sample links, and 3 if `--verify` finds
the SQL version disagrees. **The demo example is the careless version on purpose**, so the command above prints
`UNRESOLVED` and exits 2: that's the tool catching the inflated join. Its output files (`cohort_samples.csv`,
`cohort.sql`) go in the current folder.

## Output files
| File | What it is | How to get it |
|---|---|---|
| **`cohort_samples.csv`** (the required output) | The cohort: **one row per 15-character `sample_id`** (plus `patient_id`). This is the file the organizers' checker compares with the correct cohort. | App: section 4, **cohort_samples.csv** button. CLI: written by `run_cohort.py` (`--out` to choose the path). |
| `cohort.json` | The definition: request, every step, rows/samples/patients after each step, input file checksums and the data release used | App: section 4 |
| `rebuild_cohort.py` | A script that rebuilds the same cohort from the raw files | App: section 4 |
| `cohort.sql` | The independent DuckDB query from **Verify with SQL**; re-run with `python scripts/sql.py -f cohort.sql` | App: section 4 after Verify with SQL. CLI: `--verify` |
| `cohort_diff.csv` | Samples that changed between two versions of a cohort | App: **Compare with an earlier version** |

**Demo and judged version:** the git tag **`submission`** marks the exact commit we demo and submit.

`pytest -q` runs 171 tests, all passing (known gaps are listed in [docs/GAPS.md](docs/GAPS.md)): the demo numbers, **31 cohort requests checked against independent DuckDB SQL
answer keys** (`tests/test_trap_requests.py`, queries in [docs/TRAP_LOG.md](docs/TRAP_LOG.md)), the SQL check and
sample trace (`tests/test_verify.py`), the exported rebuild script, the recommended-fix and version-compare logic, and the app itself (`tests/test_app.py`).

### A changed data release (an additional dataset)
A release is a folder of changed raw files, like the ones the challenge's `make_release.py` builds
(`python data/tcga-brca/make_release.py` in the challenge repo makes `data/tcga-brca/releases/practice-B`). To run on one:
- **App:** pick it in the sidebar's **Data release** box (shown when `releases/` has any), or start the app with
  `ONCOSYS_RELEASE` set to the release's folder or name (PowerShell: `$env:ONCOSYS_RELEASE="practice-B"`; cmd:
  `set ONCOSYS_RELEASE=practice-B`; macOS/Linux: `export ONCOSYS_RELEASE=practice-B`).
- **Command line:** `--release <folder or name>`.
- Or point `ONCOSYS_DATA` straight at the release folder.

Files the release contains are read from it (marked 🔁 in the sidebar); the rest, including the sample and slide
manifests, come from the original data. Verify with SQL reads the same release files, and `cohort.json` records
which release was used. `tests/test_release.py` checks that changed records change the cohort and that SQL agrees.

### Use your own data (CSV files or Supabase)
In the app's sidebar, **Use your own data** runs the same steps, checks, fixes, exports and Verify with SQL on a
researcher's own tables instead of TCGA-BRCA:
1. **Upload CSV files** (one per table), or connect a **Supabase** project: its URL
   (`https://<project-id>.supabase.co`, the id is in the dashboard address), its **publishable** key
   (`sb_publishable_...`) or legacy anon key (Project Settings > API Keys; never the secret key) and the table
   names. Tables are only read, through Supabase's REST API (Data API on); with a publishable or anon key, each
   table needs Row Level Security off or a read policy. The key is used only for the session, never saved.
2. Pick which table is the **sample list** (one row per sample) and, for each table, its sample ID and/or
   patient ID column (guessed from the column names). Tables with several rows per sample, or keyed only by
   patient, are detected and labelled.
3. **Use this data.** Build the cohort with the dropdowns. **Back to TCGA-BRCA** returns to the event data.

The TCGA-specific extras (the examples, AI drafting, the makeup check and Data notes) are switched off for
your own data. A made-up example to try is in [examples/byod_synthetic](examples/byod_synthetic) (60
synthetic patients, lab results with several rows per sample, a patient-level visits table): blood samples
joined to `labs` give 52 rows for 28 samples, flagged, and the starred fix gives 28. Tried live both ways on
Nov 14: uploaded as CSVs, and imported into a real Supabase project and read from there (same numbers, Verify
with SQL matched). Tests: `tests/test_custom.py`.

## The demo
Request: *primary tumors with both RNA and protein data and a diagnostic slide*.

| Step | Rows | Samples |
|---|---|---|
| All samples | 1,247 | 1,247 |
| Primary tumor | 1,101 | 1,101 |
| Has RNA | 1,097 | 1,097 |
| Has protein | 742 | 742 |
| Join diagnostic slides | **776** | 731 ← inflated: 45 samples have 2 diagnostic slides |
| Fix: semi-join (keep if a slide exists) | 731 | 731 |

A second example (`examples/trap_patient_level_survival.json`) joins survival on `patient_id`. The tool
flags both the inflation and the 100 rows that attach another sample's record (normal tissue) to a tumor.

## How it works
- `cohort_studio/builder.py`: the step builder in the app. Each step is a row of dropdowns (op → table →
  column → value), so nobody has to write JSON; the JSON view is still there under “Advanced” and edits in
  it load straight back into the builder. Conditions are joined with **and** by default, and a connector can
  be switched to **or** ("HER2-positive by IHC *or* ISH" = 197 tumors, built without typing anything). The value lists come from the cohort as it stands at that step.
- `cohort_studio/engine.py`: a cohort is a JSON list of `filter` / `join` / `collapse` steps. After every
  step it checks: did rows grow faster than distinct samples? Did a patient-level join attach records from a
  different sample? Were samples dropped only because a value was missing or coded unknown (`Indeterminate`,
  `[Discrepancy]`)? It also catches request-level traps: `gene in [TP53, PIK3CA]` means *either* gene (480, not the
  57 with both), "not mutated" would count never-sequenced tumors as wild type (837 vs 527), and a value that
  doesn't exist (`gene = HER2`) suggests the real one (`ERBB2`). Each problem comes with one-click fixes.
- `cohort_studio/advice.py`: which fix gets the ★ and why (e.g. a semi-join keeps each sample once; a collapse
  keeps an arbitrary row). `cohort_studio/versions.py`: **Compare with an earlier version** lists the samples
  that moved between two versions of the cohort in this session.
- `cohort_studio/llm.py` (+ `llm_nvidia.py`): optional. Claude (`claude-opus-5-5`) or NVIDIA Nemotron, with the
  user's own key, turns the request into draft steps using structured output. It sees only table/column names
  and category values, never patient rows. It lists its assumptions, says when the data can't answer, and
  drafts no steps for treatment, diagnosis or risk questions. The user edits the draft, and every count comes
  from the engine, not the model. Evaluated on 14 requests with known answers
  ([docs/AI_EVAL.md](docs/AI_EVAL.md), `scripts/run_ai_eval.py`): 14/14 correct, one edit away or correctly
  declined with the current prompt.
- `cohort_studio/sqlcheck.py`: **Verify with SQL.** The button in section 4 of the app translates the steps
  into one DuckDB query (a CTE per step), runs it on the raw files without the engine, and compares rows,
  samples and patients after every step plus the final sample IDs. The SQL can be downloaded as `cohort.sql`
  and re-run with `python scripts/sql.py -f cohort.sql`. It confirms the steps were carried out correctly,
  not that they match the research question.
  The **Why isn't a sample in my cohort?** box traces one sample ID through the same per-step SQL and names the
  step that removed it, with the values involved.
- `cohort_studio/makeup.py`: **Did a step change who's in the cohort?** For every step that removes samples, the
  mix of submitting site, PAM50 subtype, ER status and age band before vs after (total variation distance). A
  shift of 0.10 or more gets a plain-words note, e.g. requiring protein data shifts the site mix (TVD 0.14) and
  the PAM50 mix (0.16). A shift on something the step itself filters on is labelled expected.
- `cohort_studio/export.py`: `cohort_samples.csv` (one row per 15-character `sample_id`), `cohort.json`
  (steps, funnel, input checksums) and `rebuild_cohort.py`.
- `cohort_studio/data.py`: loads the frozen files (base: `sample_manifest.csv`) and checks their checksums,
  shown in the app's sidebar.

**Tested:** besides `pytest`, a clean install from this README in a fresh folder (Nov 13 and 14), and Checkpoint 2:
the paired team ran everything from this README on their own machine with nothing broken. Bugs found by our
trap hunting, and how each was fixed, are in [docs/GAPS.md](docs/GAPS.md) and [docs/TRAP_LOG.md](docs/TRAP_LOG.md).

## Limitations (also shown in the app)
- `sample_manifest.csv` is the official list of samples and of which data each has (the organizers' rule).
  Samples that only appear in the slide manifest are left out; redacted survival records are kept and flagged.
  The app's **Data notes** panel lists every such mismatch between the files, computed live.
- Layer membership (`has_*`) comes from `sample_manifest.csv`. The mutation matrix is checked for binary values; other layer values aren't quality-checked.
- Joinable tables: clinical, survival, mutation, slides. Gene-level mutation presence (for example, TP53-mutated) can be filtered; RNA/protein/copy-number values and specific mutation variants can't yet.
- Mutation data covers primary tumors only. There is no treatment-response data, so such requests get
  "the data can't answer this".
- Some concepts live in several columns that disagree (HER2 in 3 columns; PAM50; `*_nature2012` columns cover
  only part of the patients). We use the main clinical columns and say so.
- AI drafts can vary between runs; a person reviews every draft, and the engine and SQL check do the counting.
- The loaders, the SQL check's table definitions and the makeup attributes are written for TCGA-BRCA. The
  engine's checks themselves are general, and **Use your own data** runs them on other tables; there, values
  are used as uploaded and the TCGA-only extras (makeup check, Data notes, AI drafting) are off.
- A cohort is selected for research. Nothing here is a diagnosis, risk score or clinical claim.

## Data and licenses
TCGA-BRCA via UCSC Xena and NCI Imaging Data Commons (slides CC BY 3.0). See the challenge repo's
`DATA_LICENSES.md`. No raw data is committed here. Third-party code: pandas (BSD-3), Streamlit (Apache-2.0),
DuckDB (MIT), Altair (BSD-3), requests (Apache-2.0), anthropic SDK (MIT), pytest (MIT). AI drafting uses a model API with the user's own key (Anthropic Claude or NVIDIA build.nvidia.com); no key is stored.
