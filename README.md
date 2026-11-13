# Cohort Studio · Cohort Firewall track

**User:** a researcher who needs a TCGA-BRCA cohort but doesn't write joins for a living.

**Workflow they finish:** describe a cohort in plain English (or build it from dropdowns), see how many
rows, samples and patients survive every step, get told exactly where a join inflates the count or links
a record to the wrong sample, fix it with one click, and export `cohort_samples.csv` plus a script that
rebuilds the cohort.

**Team:** _add names_ · **Demo video:** _add link_

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
Windows: keep the folder path short (e.g. `D:\oncosyshackathon`). A very deep path can make `pip install` fail on
the long-path limit. In `cmd`, switching drives needs `cd /d D:\oncosyshackathon`.

## Run
```bash
streamlit run app.py                                         # the app
python run_cohort.py examples/demo_diagnostic_slides.json    # same engine from the command line
python run_cohort.py examples/demo_diagnostic_slides.json --verify --why TCGA-E2-A15E-01   # SQL check + trace one sample
python run_cohort.py examples/demo_diagnostic_slides.json --makeup   # did a step change who's in the cohort?
python run_cohort.py --ask "ER-positive primary tumors with a diagnostic slide"   # AI draft, needs ANTHROPIC_API_KEY
python scripts/sql.py                                        # DuckDB SQL console over the raw files
pytest -q                                                    # 134 tests, see below
```
`run_cohort.py` exits with code 2 if the cohort still has duplicates or cross-sample links, and 3 if `--verify` finds
the SQL version disagrees. **The demo example is the careless version on purpose**, so the command above prints
`UNRESOLVED` and exits 2: that's the tool catching the inflated join. Its output files (`cohort_samples.csv`,
`cohort.sql`) go in the current folder.

`pytest -q` runs 134 tests, all passing (known gaps are listed in [docs/GAPS.md](docs/GAPS.md)): the demo numbers, **25 cohort requests checked against independent DuckDB SQL
answer keys** (`tests/test_answer_key.py`, queries in [docs/TRAP_LOG.md](docs/TRAP_LOG.md)), the SQL check and
sample trace (`tests/test_verify.py`), the exported rebuild script, the recommended-fix and version-compare logic, and the app itself (`tests/test_app.py`).

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
  different sample? Were samples dropped only because a value was missing? Each problem comes with fixes.
- `cohort_studio/llm.py`: optional. Claude (`claude-opus-5-5`, user-supplied key) turns the request into
  draft steps using structured output. It sees only table/column names and category values, never patient
  rows. It lists its assumptions and says when the data can't answer. The user edits the draft, and every
  count comes from the engine, not the model.
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

## Limitations (also shown in the app)
- `sample_manifest.csv` is the official list of samples and of which data each has (the organizers' rule).
  Samples that only appear in the slide manifest are left out; redacted survival records are kept and flagged.
  The app's **Data notes** panel lists every such mismatch between the files, computed live.
- Layer membership (`has_*`) comes from `sample_manifest.csv`. The mutation matrix is checked for binary values; other layer values aren't quality-checked.
- Joinable tables: clinical, survival, mutation, slides. Gene-level mutation presence (for example, TP53-mutated) can be filtered; RNA/protein/copy-number values and specific mutation variants can't yet.
- A cohort is selected for research. Nothing here is a diagnosis, risk score or clinical claim.

## Data and licenses
TCGA-BRCA via UCSC Xena and NCI Imaging Data Commons (slides CC BY 3.0). See the challenge repo's
`DATA_LICENSES.md`. No raw data is committed here. Third-party code: pandas (BSD-3), Streamlit (Apache-2.0),
DuckDB (MIT), anthropic SDK (MIT), pytest (MIT).
