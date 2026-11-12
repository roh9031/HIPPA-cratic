# Team plan: Cohort Studio

**Code freeze: Saturday, Nov 14, 2:15 PM ET.** A finished workflow beats an ambitious broken one.

## Where we are (Wed, Nov 11)

The core product already works end to end. It's our own code, not provided by the organizers. The challenge
repo gives only the data, the briefs, the rules and a starter notebook.

| Part | Status |
|---|---|
| Engine (`engine.py`): steps, per-step counts, inflation and cross-sample checks, one-click fixes | ✅ works, tested |
| Data loading (`data.py`) with checksum check | ✅ works |
| Export (`export.py`): `cohort_samples.csv`, `cohort.json`, `rebuild_cohort.py` | ✅ works |
| Streamlit UI (`app.py`) | ✅ works, but users edit **raw JSON** |
| CLI (`run_cohort.py`), exit code 2 on unresolved problems | ✅ works |
| AI drafting (`llm.py`) | ⚠️ never tested with a real key |
| Tests | ⚠️ 13 tests: the 2 examples plus 6 DuckDB answer-key cases. Needs more traps |
| README | ⚠️ missing team names, demo video and third-party licenses |

Demo numbers: Primary tumor 1,101 → RNA + protein 742 → join diagnostic slides **776 rows / 731 samples**
(inflated) → semi-join fix **731**.

## What judges do

They give us **a new cohort request that inflates through a join we haven't seen**, run it live, and export
`cohort_samples.csv`. A checker compares that file with the correct cohort. **That's the score that
matters most**, so roles 1 and 2 below are the priority.

## Roles (proposed: swap names in)

| # | Role | Owner | Owns | Done when |
|---|---|---|---|---|
| 1 | **Trap hunter / tests** | _name_ | Invent 8–10 requests judges might give (clinical joins, left joins, patient-level joins, normal vs tumor, frozen vs diagnostic slides). Work out the correct sample list for each **by hand in pandas**. Add each as a `Case` in **`tests/test_answer_key.py`** (correct answer as DuckDB SQL plus the engine steps; template inside) and an example in `examples/`. | Each trap is caught, and the exported CSV matches the hand-made answer |
| 2 | **Engine** | _name_ | Fix what role 1 breaks. Add more joinable tables (mutation, protein). | All of role 1's tests pass. First known gap: patient-level "matched normal" requests (ARCHITECTURE.md, open question 6) |
| 3 | **UI** | _name_ | Dropdown step builder (op → table → column → value). Keep JSON as an "advanced" view. | A non-coder builds the demo cohort without touching JSON |
| 4 | **AI drafting** | _name_ | Test "Draft with AI" on 10 requests with a personal key, log results in `docs/ai_eval.md`, improve the prompt | ≥ 8/10 drafts correct or one edit away |
| 5 | **Submission lead** | _name_ | README (names, licenses, video link), clean-clone test, Gitleaks scan, both checkpoints, demo script and video, final merge | Every box in `SUBMISSION_CHECKLIST.md` ticked |

Roles 1 and 2 should pair closely. Role 3 only *produces* step JSON (format in [ARCHITECTURE.md](ARCHITECTURE.md)),
so roles 2 and 3 won't collide.

## Timeline

| When | Milestone |
|---|---|
| **Wed night** | Everyone: clone both repos, run `fetch.py`, `pip install -r requirements.txt`, `pytest -q`, `streamlit run app.py`. Report setup problems to role 5. Agree on roles. |
| **Thu** | **Checkpoint 1:** post the demo funnel screenshot in Discord. Role 1 has ≥ 4 new traps written up. Role 3 has a rough builder. |
| **Fri** | **Checkpoint 2:** paired team clones our repo fresh and runs it from the README alone. We do the same for them. **Feature freeze Friday night.** |
| **Sat AM** | Bug fixes only. Record demo video. Final merge by role 5. **2:15 PM ET freeze.** |

## How we work in git

- One branch per person or feature (`git checkout -b ui-builder`). Merge to `main` in small, frequent PRs.
- Run **`pytest -q` and `streamlit run app.py` before every merge.**
- **Never commit** API keys, `.env`, or raw TCGA files (data stays in the challenge repo).
- Don't change the step JSON format without telling roles 2, 3 and 4. All three depend on it.

## Rules checklist (from the challenge repo)

- App shows a **human-review notice** and **one visible limitation** (already in section 4 of the UI).
- **No clinical claims**: no diagnosis, treatment advice or risk scores.
- AI runs only with a **user-supplied key**, says when the data can't answer, and never sees patient rows.
- Judged results use the **frozen data** (the sidebar shows ✅ / ⚠️ CHANGED).
