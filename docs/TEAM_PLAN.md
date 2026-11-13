# Team plan: Cohort Studio

**Code freeze: Saturday, Nov 14, 2:15 PM ET.** A finished workflow beats an ambitious broken one.

## Where we are (Thu, Nov 12, evening)

The core product already works end to end. It's our own code (scaffolded with Claude Code), not provided by
the organizers. The challenge repo gives only the data, the briefs, the rules and a starter notebook.

| Part | Status |
|---|---|
| Engine (`engine.py`): steps, per-step counts, inflation and cross-sample checks, one-click fixes | ✅ works, tested |
| Data loading (`data.py`) with checksum check | ✅ works |
| Export (`export.py`): `cohort_samples.csv`, `cohort.json`, `rebuild_cohort.py` | ✅ works |
| Streamlit UI (`app.py` + `builder.py`): dropdown step builder, JSON kept as an advanced view | ✅ works, tested |
| CLI (`run_cohort.py`), exit code 2 on unresolved problems, `--verify` / `--why` | ✅ works |
| **Verify with SQL** + **Why isn't sample X** (`sqlcheck.py`, DuckDB) | ✅ works, tested |
| AI drafting (`llm.py`) | ⚠️ never tested with a real key |
| Tests | ✅ 129 tests, all passing: 26 trap cases with DuckDB answer keys (all pass since B's OR and patient-level fixes, Nov 12), `AppTest` UI tests, SQL check, rebuild, recommended-fix and version-compare tests. Known gaps: [GAPS.md](GAPS.md) |
| Clean install from README | ✅ tested Nov 12 (fresh clone of both repos, new venv). Rerun after the last merge on Friday |
| README | ⚠️ missing team names and demo video link |

Demo numbers: Primary tumor 1,101 → RNA 1,097 → protein 742 → join diagnostic slides **776 rows / 731 samples**
(inflated) → semi-join fix **731**.

## What judges do

They give us **a new cohort request that inflates through a join we haven't seen**, run it live, and export
`cohort_samples.csv`. A checker compares that file with the correct cohort. **That's the score that
matters most**, so finding and fixing traps (roles 1, 2 and 2b) is the priority.

## Roles (proposed: confirm on Thursday)

Everyone writes code. The submission paperwork is split up as small side tasks instead of being one person's job.

| Teammate | Role | Main coding job | Side task | Done when |
|---|---|---|---|---|
| **A** (proposed: roh9031) | **1 · Trap hunter** | Invent requests judges might give. Write the correct answer as **DuckDB SQL** and add each as a `Case` in `tests/test_answer_key.py` (template inside) plus an example in `examples/`. Hand failures to B and C. | Review and merge PRs into `main` (repo owner) | 10+ traps, each passing or logged in GAPS.md. ✅ 25 traps (Nov 12) |
| **B** | **2 · Engine** | Fix what A finds. First job: patient-level matching (GAPS.md #2). | ~~Ask organizers about redacted records~~ answered Nov 12: keep and flag (GAPS.md #6) | A's tests pass |
| **C** | **2b · Data** | Add mutation data as a joinable table so "TP53-mutated" requests work (GAPS.md #3), then protein/RNA if time allows | List third-party code and licenses in README | Gene-level mutation requests work with a test |
| **D** | **3 · UI** | Dropdown step builder (op → table → column → value). Keep JSON as an "advanced" view. | Record the demo video | A non-coder builds the demo cohort without touching JSON. ✅ builder merged Nov 12 (demo video still to do) |
| **E** | **4 · AI** | Test "Draft with AI" on 10 requests with a personal key, log results in `docs/ai_eval.md`, improve the prompt in `llm.py` | README setup steps + run the Friday clean-install check | ≥ 8/10 drafts correct or one edit away |

**Who talks to whom:** A ↔ B and C (A finds bugs, they fix them). D and E only *produce* step JSON (format in
[ARCHITECTURE.md](ARCHITECTURE.md)), so they won't collide with the engine work.

## Timeline

| When | Milestone |
|---|---|
| **Wed night** | Everyone: clone both repos, run `fetch.py`, `pip install -r requirements.txt`, `pytest -q`, `streamlit run app.py`. Post setup problems in the team chat. |
| **Thu** | Confirm roles. **Checkpoint 1:** post the demo funnel screenshot in Discord. Work starts: A writes the first traps, B starts patient-level matching, D has a rough builder. |
| **Fri** | **Checkpoint 2:** paired team clones our repo fresh and runs it from the README alone. We do the same for them. **Feature freeze Friday night.** |
| **Sat AM** | Bug fixes only. D records the demo video. A does the final merge. **2:15 PM ET freeze.** |

## How we work in git

- One branch per person or feature (`git checkout -b ui-builder`). Open a PR to `main` and A merges it.
- Run **`pytest -q` and `streamlit run app.py` before opening a PR.**
- **Never commit** API keys, `.env`, or raw TCGA files (data stays in the challenge repo).
- Don't change the step JSON format without telling B, D and E. All three depend on it.

## Rules checklist (from the challenge repo)

- App shows a **human-review notice** and **one visible limitation** (already in section 4 of the UI).
- **No clinical claims**: no diagnosis, treatment advice or risk scores.
- AI runs only with a **user-supplied key**, says when the data can't answer, and never sees patient rows.
- Judged results use the **frozen data** (the sidebar shows ✅ / ⚠️ CHANGED).
