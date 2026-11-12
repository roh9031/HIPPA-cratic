# Edge cases and gaps

Everything here was **tested against the real data** on Nov 11, not guessed. Update the status column as things get fixed.
Priority = how likely it is to cost us points when judges give a new request.

## Already handled ✅

| Edge case | How | Tested |
|---|---|---|
| Slide join inflates rows (several slides per sample) | Inflation warning + semi-join / collapse fixes | ✅ |
| Join on `patient_id` attaches another sample's record (e.g. normal tissue → tumor) | Cross-sample warning + "join on sample_id" fix | ✅ |
| Joining the same table twice | Each join flagged separately | probe only |
| Typo in a column name | Error with "similar columns" hint, no crash | ✅ |
| Value case and whitespace (`positive` vs `Positive `) | Matching ignores case and trims | ✅ |
| Samples dropped because a value is blank | Info note with examples | probe only |
| Filter matches nothing | "Empty" warning | probe only |
| Patients with several samples in the final cohort | Info note + "collapse to patient" fix | probe only |
| Exporting while problems remain | Blocked unless the user ticks a box; CSV de-duplicated anyway | ✅ |
| Wrong or edited data files | Sidebar checksum check (✅ / ⚠️ CHANGED) | manual |

## Gaps found

| # | Priority | Gap | Evidence | Plan | Owner ([TEAM_PLAN](TEAM_PLAN.md)) |
|---|---|---|---|---|---|
| 1 | ✅ Fixed Nov 11 | **Wrong fix offered for a `left` join.** The "semi-join" fix silently drops samples that have no match, which changes the cohort. | Primary tumors left-joined to slides: 1,101 samples → semi fix gives **1,098** | For `left` joins offer only "collapse to one row per sample". Offer semi only for `inner` | B |
| 2 | 🔴 High | **Patient-level requests** ("tumors whose patient also has a matched normal sample") can't be expressed, and any `patient_id` match is flagged as a problem even when intended | No way to join the sample manifest to itself; the semi-join on patient_id is blocked from export | Add a `samples` joinable table; don't flag cross-sample links when matching another sample of the same patient is the point | B |
| 3 | 🔴 High | **Only clinical, survival and slides can be joined.** "TP53-mutated", "high ESR1 expression" and so on can't be answered | Mutation / RNA / protein / copy-number files exist in `raw/` but aren't in `data.TABLES` | Add at least gene-level mutation. Until then the AI must say `cannot_answer` | C |
| 4 | 🔴 High | **AI drafting has never been run** with a real key | — | Run 10 requests, log them in `docs/ai_eval.md`, fix the prompt | E |
| 5 | 🔴 High | **Non-coders must edit JSON** | — | Dropdown step builder | D |
| 6 | ✅ Warned Nov 11 (still ask organizers) | **Redacted survival records are included silently.** 6 samples (5 primary tumors) have `Redaction = Redacted` but full OS values | e.g. `TCGA-A7-A0DC-01`, OS.time 906 | Info warning when redacted rows survive, plus an "exclude redacted" fix. Ask organizers what the checker expects | B |
| 7 | 🔴 High (confirmed on triple-negative: 21 unknown-HER2 tumors kept by "not positive") | **Odd coded values count as real values.** `ne Negative` keeps `Indeterminate` and `[Discrepancy]` (14 such codes in clinical). They aren't blank, so no warning appears | "ER not Negative" = 810 samples vs. ER Positive only | Treat `[...]` codes as missing and warn. AI prompt should prefer positive matches (`eq Positive`) | B + E |
| 8 | 🟠 Medium | **Ambiguous wording.** Does "tumors" include the 7 Metastatic samples? Does "patients" mean one sample each? | — | AI must list these as assumptions; test in E's AI eval | E |
| 9 | 🟡 Low | **Collapse to patient keeps whichever row comes first** in the file, with no rule like "prefer the primary tumor" | Works today only because the manifest lists tumors first | Sort by sample type (tumor first) before collapsing | B |
| 10 | 🟡 Low | **Booleans spelled differently** (`has_rna = yes` or `1`) return 0 samples | Empty warning appears, but the fix isn't obvious | Normalise yes/1/true | B |
| 11 | 🟡 Low | **Anti-join on `patient_id`** isn't checked for cross-sample effects | Same result as sample_id in this data (8 = 8), so harmless today | Add the same check as semi | B |
| 12 | 🟡 Low | **Silent drops on inner joins** (4 primary tumors have no survival row). Visible in the funnel but not explained | 1,101 → 1,097 | "Explain each exclusion in plain words" (a stretch goal in the brief) | D |
| 13 | 🟡 Low | `rebuild_cohort.py` needs this repo installed to run | — | Document it in README, or inline the engine | E |
| 14 | ✅ Fixed Nov 11 | **Windows encoding.** `app.py` reads examples without `encoding="utf-8"`, so a `≥` or `—` in an example JSON would crash on Windows | Hit this while editing docs | Add `encoding="utf-8"` (one line) | B |
| 15 | 🟡 Low | `requirements.txt` says `streamlit>=1.37`, but the app uses `width="stretch"`, which older versions don't support. 1.67 works | — | Raise the minimum version after the clean-clone test | E |
| 16 | 🔴 High | **No OR conditions.** A step's conditions are AND-only, so "HER2-positive (IHC **or** ISH)", "ER- or PR-positive" and similar requests can't be built | HER2+ answer key = 197; best engine attempt (IHC only) = 164, missing 33. Test `her2_positive` (xfail) | Allow `"any": [...]` groups inside `where` (OR), in the engine, the AI schema and D's builder | B (+ D, E) |
| 17 | 🟠 Medium | **Same concept, several columns.** HER2 status lives in 3 columns that disagree (114 / 164 / 197 positive tumors) | `docs/TRAPS.md` #3 | The AI must name the column it picked as an assumption. Consider a column note in the UI | E |
| 18 | 🔴 High | **No warnings for conditions inside a join.** Missing-value notes only run for `filter` steps. Conditions in a join's `where` (what the semi-join fix and the AI produce) drop samples silently | Triple-negative, ISH `ne Positive` inside a join: 18 samples, 0 warnings. Same conditions as a filter step: 4 notes (e.g. 681 dropped for blank ISH). `engine.py:243` | Run the same missing-value check on the right table's `where` in `_join` | B |
| 19 | 🟠 Medium | **Normal samples missing from the manifest.** 24 normal samples (50 slides) appear in `slide_manifest.csv` but not in `sample_manifest.csv`. "Tumors with a matched normal" is 139 by the manifest, 163 counting slide evidence | `docs/TRAP_LOG.md`, matched-normal-with-slide trap | Decide as a team (ask organizers?). If slides count, B's patient-level matching (#2) must look at slides too | A + B |
| 20 | 🟠 Medium (judges notice) | **No check that a filter changed the cohort's makeup.** Another team's checkpoint shows: "requiring protein data removes 355 tumors and shifts the mix of submitting sites (TVD 0.14)". We show counts only | Discord, Checkpoint 1 posts | After each step, compare the distribution of the submitting site (barcode chars 6-7, e.g. `TCGA-`**`A7`**`-...`) and other categories before vs after. Total variation distance = ½·Σ\|p−q\|. Info note above a threshold (e.g. 0.1), plus a plain-words line: "this step removed N tumors, mostly from sites X, Y". Also covers the brief's stretch goal "explain each exclusion" | unclaimed |
| 21 | 🟠 Medium | **No "recommended" fix.** Every problem offers several fixes, and the user can't tell which is best. On the survival trap, "collapse" leaves the cross-sample problem and "semi-join" only works by luck; "join on sample_id" is the real fix | `examples/trap_patient_level_survival.json` | Engine marks one fix `recommended` (cross-sample → join on sample_id; inner-join inflation → semi-join; left-join inflation → collapse). UI shows it first with a ⭐ and a one-line why | B + D |

## Standing out: what judges can check themselves

The other Cohort Studio team has counts, an inflation fix, a site-mix check (TVD) and a rebuild script. These
items go further. They're aimed at the judging bar: *a judge can use it without narration, sees one result they
can verify, and one limitation they can inspect* ("this data can't answer, and here's why" is a valid result).

| # | Priority | Item | Why it matters | Plan | Owner |
|---|---|---|---|---|---|
| 22 | ✅ Built Nov 12 | **"Verify with SQL" button** | A judge can check the count without trusting our engine: "one verifiable result" | The steps are translated into one DuckDB query (a CTE per step, `cohort_studio/sqlcheck.py`) and run on the raw files. The app shows engine vs SQL per step, and the SQL to copy or download (`cohort.sql`, runs with `python scripts/sql.py -f cohort.sql`). Agrees on all 30 step lists in `tests/test_verify.py` | A |
| 23 | 🟠 Medium | **"Why isn't sample X in my cohort?"** | Judges like checking one specific case. Covers the brief's stretch goal "explain each exclusion" | Text box: sample ID → the step that dropped it and why (e.g. "`TCGA-E2-A15E-01` was removed at step 4: its only diagnostic slide belongs to the patient's metastatic sample") | E |
| 24 | 🟠 Medium | **"Data notes" panel** (limitations to inspect) | Shows we understand the data, not just the joins | List the quirks we found, with numbers: 24 normal samples missing from the manifest (#19), 6 redacted survival rows (#6), 3 HER2 columns that disagree (#17), age stored as text, coded values like `[Discrepancy]` (#7). Facts are in `TRAP_LOG.md` | C |
| 25 | 🟠 Medium | **"Can't answer, and here's why"** | The rules call this a valid winning result | When a request needs data we don't have (treatment response; mutations until #3), say so clearly instead of building something close. `llm.py` already returns `cannot_answer`: make it prominent and test it | E |
| 26 | 🟡 Low | **Compare two versions of a cohort** (a stretch goal in the brief) | Makes a fix visible: which samples changed and why | Careless vs fixed side by side, with the sample IDs that differ | D |
| 27 | 🟡 Low | **Makeup shift beyond site** | Beats the other team's single TVD number | Do #20 for site, PAM50 subtype, ER status and age band | unclaimed |
| 28 | ✅ Done Nov 12 | **"All five layers" variants** | The data README quotes 535 primary tumors with all five layers; a judge may add "with a diagnostic slide" | Engine already gives 535, and with a diagnostic slide 572 rows / 531 samples, flagged as inflation. Both are answer-key Cases and pass | A |

## How each gap gets closed

Every fix by B or C should come with a `Case` in `tests/test_answer_key.py`: the correct answer as DuckDB SQL plus the
steps a user would build. A gap is closed when that test passes **and** the naive version is flagged.

**Done Nov 11:** #1 (left joins now offer only the collapse fix), #6 (info warning plus an "exclude redacted"
fix; it doesn't block export because we don't yet know what the checker expects), #14 (all file reads use UTF-8).
Each has a test.

**Done Nov 12:** the exported `rebuild_cohort.py` is now tested (it reproduces the app's CSV exactly, `tests/test_rebuild.py`). The demo splits RNA (1,097) and protein (742) into separate steps so the funnel shows where tumors are lost.
#22 "Verify with SQL" is in the app (section 4), with `tests/test_verify.py`.

**Next, before the Friday feature freeze:** 2 → 3 (engine) · 4, 5 (in parallel, other roles) · the rest only if time allows.
