# Cohort Studio · Cohort Firewall track

**User:** a researcher who needs a TCGA-BRCA cohort but doesn't write joins for a living.

**Workflow they finish:** describe a cohort in plain English (or edit the steps directly), see how many
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
├── oncosys-hackathon-challenge/   # git clone https://github.com/disleveK/oncosys-hackathon-challenge.git
└── cohort-studio/                 # this repo
```
```bash
cd oncosys-hackathon-challenge && python data/tcga-brca/fetch.py && cd ..
cd cohort-studio
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
streamlit run app.py                                         # the app
python run_cohort.py examples/demo_diagnostic_slides.json    # same engine from the command line
python run_cohort.py --ask "ER-positive primary tumors with a diagnostic slide"   # AI draft, needs ANTHROPIC_API_KEY
pytest -q                                                    # checks the demo numbers
```
`run_cohort.py` exits with code 2 if the cohort still has duplicates or cross-sample links.

## The demo
Request: *primary tumors with both RNA and protein data and a diagnostic slide*.

| Step | Rows | Samples |
|---|---|---|
| All samples | 1,247 | 1,247 |
| Primary tumor | 1,101 | 1,101 |
| Has RNA and protein | 742 | 742 |
| Join diagnostic slides | **776** | 731 ← inflated: 45 samples have 2 diagnostic slides |
| Fix: semi-join (keep if a slide exists) | 731 | 731 |

A second example (`examples/trap_patient_level_survival.json`) joins survival on `patient_id`. The tool
flags both the inflation and the 100 rows that attach another sample's record (normal tissue) to a tumor.

## How it works
- `cohort_studio/engine.py`: a cohort is a JSON list of `filter` / `join` / `collapse` steps. After every
  step it checks: did rows grow faster than distinct samples? Did a patient-level join attach records from a
  different sample? Were samples dropped only because a value was missing? Each problem comes with fixes.
- `cohort_studio/llm.py`: optional. Claude (`claude-opus-5-5`, user-supplied key) turns the request into
  draft steps using structured output. It sees only table/column names and category values, never patient
  rows. It lists its assumptions and says when the data can't answer. The user edits the draft, and every
  count comes from the engine, not the model.
- `cohort_studio/export.py`: `cohort_samples.csv` (one row per 15-character `sample_id`), `cohort.json`
  (steps, funnel, input checksums) and `rebuild_cohort.py`.

## Limitations (also shown in the app)
- Layer membership (`has_*`) comes from `sample_manifest.csv`. Values inside each layer aren't quality-checked.
- Joinable tables: clinical, survival, slides. Mutation/RNA/protein values can't be filtered on yet.
- A cohort is selected for research. Nothing here is a diagnosis, risk score or clinical claim.

## Data and licenses
TCGA-BRCA via UCSC Xena and NCI Imaging Data Commons (slides CC BY 3.0). See the challenge repo's
`DATA_LICENSES.md`. No raw data is committed here. Third-party code: pandas (BSD-3), Streamlit (Apache-2.0),
anthropic SDK (MIT), pytest (MIT).
