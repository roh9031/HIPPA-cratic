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

You need Python 3.10 or newer and git. Clone this repo **next to** the challenge repo, in a short path
(not inside another git repository), or set `ONCOSYS_DATA` to the challenge repo's `data/tcga-brca` folder:
```
oncosyshackathon/
├── oncosys-hackathon-challenge/
└── cohort-studio/
```

### macOS / Linux
```bash
mkdir ~/oncosyshackathon && cd ~/oncosyshackathon
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git
git clone https://github.com/roh9031/HIPPA-cratic.git cohort-studio      # note: clone into "cohort-studio"
cd cohort-studio
python3 -m venv .venv
source .venv/bin/activate        # the prompt now starts with (.venv); from here on, `python` and `pip` work
pip install -r requirements.txt
cd ../oncosys-hackathon-challenge && python data/tcga-brca/fetch.py && cd ../cohort-studio   # ~70 MB, checks checksums
```

### Windows
Keep the folder path short (e.g. `C:\oncosyshackathon`). A very deep path can make `pip install` fail on the
long-path limit. In `cmd`, switching drives needs `cd /d`.
```bat
mkdir C:\oncosyshackathon && cd /d C:\oncosyshackathon
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git
git clone https://github.com/roh9031/HIPPA-cratic.git cohort-studio
cd cohort-studio
py -m venv .venv
.venv\Scripts\activate           :: PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..\oncosys-hackathon-challenge && python data\tcga-brca\fetch.py && cd ..\cohort-studio
```

### Check it worked
```bash
pytest -q                 # all tests pass, including the demo numbers
streamlit run app.py      # the sidebar shows ✅ for all four data files
```
Open a new terminal later? Activate the environment again first (`source .venv/bin/activate` on macOS/Linux,
`.venv\Scripts\activate` on Windows).

### If something goes wrong
- **`python: command not found` (macOS):** the environment isn't active. Run `source .venv/bin/activate` from
  the `cohort-studio` folder, or use `python3`.
- **`CERTIFICATE_VERIFY_FAILED` when fetching (macOS, Python from python.org):** run
  `open "/Applications/Python 3.14/Install Certificates.command"` once (change `3.14` to your version; check
  with `python3 --version`), then run `fetch.py` again.
- **Sidebar shows ❌, or `FileNotFoundError: ... sample_manifest.csv`:** the data isn't downloaded yet. Run the
  `fetch.py` line again and watch for errors, or set `ONCOSYS_DATA` to the folder that holds
  `sample_manifest.csv`.
- **Sidebar shows ⚠️ CHANGED:** a file doesn't match the event's frozen checksum. Run `fetch.py` again; don't use
  that file for judged results.

## Run
With the environment active, from the `cohort-studio` folder:
```bash
streamlit run app.py                                         # the app
python run_cohort.py examples/demo_diagnostic_slides.json    # same engine from the command line
python run_cohort.py examples/demo_diagnostic_slides.json --verify --why TCGA-E2-A15E-01   # SQL check + trace one sample
python run_cohort.py --ask "ER-positive primary tumors with a diagnostic slide"   # AI draft, needs ANTHROPIC_API_KEY
python scripts/run_ai_eval.py                                # AI drafting test on 10 requests, needs ANTHROPIC_API_KEY
pytest -q                                                    # checks the demo numbers
```
The AI features use your own Anthropic key, set for the current terminal only. Never put it in a file:
```bash
export ANTHROPIC_API_KEY="your-key"          # macOS/Linux
set ANTHROPIC_API_KEY=your-key               # Windows cmd
$env:ANTHROPIC_API_KEY="your-key"            # Windows PowerShell
```
`run_cohort.py` exits with code 2 if the cohort still has duplicates or cross-sample links, and 3 if `--verify` finds
the SQL version disagrees. **The demo example is the careless version on purpose**, so the command above prints
`UNRESOLVED` and exits 2: that's the tool catching the inflated join. Its output files (`cohort_samples.csv`,
`cohort.sql`) go in the current folder.

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