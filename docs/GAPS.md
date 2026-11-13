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
| 2 | ✅ Fixed Nov 12 | **Patient-level requests** ("tumors whose patient also has a matched normal sample") can't be expressed, and any `patient_id` match is flagged as a problem even when intended | Explicit `allow_cross_sample: true` opts into intentional patient-level existence matching; ordinary patient joins remain flagged | Use the explicit opt-in for patient-level requests; keep `sample_id` joins for attaching records | B |
| 3 | 🔴 High | **Only clinical, survival and slides can be joined.** "TP53-mutated", "high ESR1 expression" and so on can't be answered | Mutation / RNA / protein / copy-number files exist in `raw/` but aren't in `data.TABLES` | Add at least gene-level mutation. Until then the AI must say `cannot_answer` | C |
| 4 | 🔴 High | **AI drafting has never been run** with a real key | — | Run 10 requests, log them in `docs/ai_eval.md`, fix the prompt | E |
| 5 | ✅ Fixed Nov 12 | **Non-coders must edit JSON** | — | Dropdown step builder (`cohort_studio/builder.py`): op → table → column → value, add/move/remove steps and conditions. The JSON box is still there as “Advanced” and round-trips both ways | D |
| 6 | ✅ Resolved Nov 12 (organizers answered) | **Redacted survival records are included silently.** 6 samples (5 primary tumors) have `Redaction = Redacted` but full OS values | e.g. `TCGA-A7-A0DC-01`, OS.time 906 | Organizers: **keep them** (the manifest marks them as having survival data) **and flag them**. Done: the info note says they're kept, the "exclude" fix is labelled "only if your question requires it", test `survival_keeps_redacted` | B |
| 7 | 🔴 High (confirmed on triple-negative: 21 unknown-HER2 tumors kept by "not positive") | **Odd coded values count as real values.** `ne Negative` keeps `Indeterminate` and `[Discrepancy]` (14 such codes in clinical). They aren't blank, so no warning appears | "ER not Negative" = 810 samples vs. ER Positive only | Treat `[...]` codes as missing and warn. AI prompt should prefer positive matches (`eq Positive`) | B + E |
| 8 | 🟠 Medium | **Ambiguous wording.** Does "tumors" include the 7 Metastatic samples? Does "patients" mean one sample each? | — | AI must list these as assumptions; test in E's AI eval | E |
| 9 | 🟡 Low | **Collapse to patient keeps whichever row comes first** in the file, with no rule like "prefer the primary tumor" | Works today only because the manifest lists tumors first | Sort by sample type (tumor first) before collapsing | B |
| 10 | 🟡 Low | **Booleans spelled differently** (`has_rna = yes` or `1`) return 0 samples | Empty warning appears, but the fix isn't obvious | Normalise yes/1/true | B |
| 11 | 🟡 Low | **Anti-join on `patient_id`** isn't checked for cross-sample effects | Same result as sample_id in this data (8 = 8), so harmless today | Add the same check as semi | B |
| 12 | 🟡 Low | **Silent drops on inner joins** (4 primary tumors have no survival row). Visible in the funnel but not explained | 1,101 → 1,097 | "Explain each exclusion in plain words" (a stretch goal in the brief) | D |
| 13 | 🟡 Low | `rebuild_cohort.py` needs this repo installed to run | — | Document it in README, or inline the engine | E |
| 14 | ✅ Fixed Nov 11 | **Windows encoding.** `app.py` reads examples without `encoding="utf-8"`, so a `≥` or `—` in an example JSON would crash on Windows | Hit this while editing docs | Add `encoding="utf-8"` (one line) | B |
| 15 | ✅ Fixed Nov 12 | `requirements.txt` said `streamlit>=1.37`, but the app uses `width="stretch"` and the builder uses `st.menu_button`, horizontal containers and `accept_new_options` | — | Minimum raised to `streamlit>=1.67` (the version the builder was written and tested against). Confirm in the clean-clone test | D |
| 16 | ✅ Fixed Nov 12 | **No OR conditions.** A step's conditions were AND-only, so "HER2-positive (IHC **or** ISH)" and similar requests could not be built | Engine supports `{"any": [condition, condition]}` OR groups, including descriptions and missing-value checks; HER2 and triple-negative answer keys pass | Use `any` groups in `where`; nested `all` groups support ORs of AND conditions | B (+ D, E; SQL: A ✅) |
| 17 | 🟠 Medium | **Same concept, several columns.** HER2 status lives in 3 columns that disagree (114 / 164 / 197 positive tumors). Also PAM50 (Luminal A: 421 vs 231), vital status vs OS (152 vs 151), gender (1 tumor) | `docs/TRAPS.md` #3 | The AI must name the column it picked as an assumption. Consider a column note in the UI | E |
| 18 | ✅ Fixed Nov 12 | **No warnings for conditions inside a join.** Missing-value notes only ran for `filter` steps, so conditions in a join's `where` could drop samples silently | Join conditions now inspect missing values in the right-hand table before filtering and report affected sample examples. | Reuse the shared missing-value warning helper for join `where` conditions | B |
| 19 | 🟠 Medium | **Normal samples missing from the manifest.** 24 normal samples (50 slides) appear in `slide_manifest.csv` but not in `sample_manifest.csv`. "Tumors with a matched normal" is 139 by the manifest, 163 counting slide evidence | `docs/TRAP_LOG.md`, matched-normal-with-slide trap | Decide as a team (ask organizers?). If slides count, B's patient-level matching (#2) must look at slides too | A + B |
| 19 | ✅ Resolved Nov 12 (organizers answered) | **Normal samples missing from the manifest.** 24 normal samples (50 slides) appear in `slide_manifest.csv` but not in `sample_manifest.csv`. "Tumors with a matched normal" is 139 by the manifest, 163 counting slide evidence | `docs/TRAP_LOG.md`, matched-normal-with-slide trap | Organizers: **leave them out** (not in the sample manifest) **and point out the mismatch**. Done: they can't enter any cohort (the base is the manifest), the Data notes panel and the sample trace both explain them, and the matched-normal-with-slide answer key is now **138** (was 162) | A + B |
| 20 | 🟠 Medium (judges notice) | **No check that a filter changed the cohort's makeup.** Another team's checkpoint shows: "requiring protein data removes 355 tumors and shifts the mix of submitting sites (TVD 0.14)". We show counts only | Discord, Checkpoint 1 posts | After each step, compare the distribution of the submitting site (barcode chars 6-7, e.g. `TCGA-`**`A7`**`-...`) and other categories before vs after. Total variation distance = ½·Σ\|p−q\|. Info note above a threshold (e.g. 0.1), plus a plain-words line: "this step removed N tumors, mostly from sites X, Y". Also covers the brief's stretch goal "explain each exclusion" | unclaimed |
| 21 | ✅ Fixed Nov 12 (UI side) | **No "recommended" fix.** Every problem offered several fixes and the user couldn't tell which was best. On the survival trap, "collapse" leaves the cross-sample problem and "semi-join" only works by luck; "join on sample_id" is the real fix | `examples/trap_patient_level_survival.json` | `cohort_studio/advice.py` picks one fix per step by **what it changes**, not its label. The UI shows that box first, stars the fix, says why, and puts a caveat on the near-misses. If the engine ever sets `fix["recommended"]`, that wins and these rules are skipped. Tests: `tests/test_advice.py` | D (engine side still open for B) |

## Standing out: what judges can check themselves

The other Cohort Studio team has counts, an inflation fix, a site-mix check (TVD) and a rebuild script. These
items go further. They're aimed at the judging bar: *a judge can use it without narration, sees one result they
can verify, and one limitation they can inspect* ("this data can't answer, and here's why" is a valid result).

| # | Priority | Item | Why it matters | Plan | Owner |
|---|---|---|---|---|---|
| 22 | ✅ Built Nov 12 | **"Verify with SQL" button** | A judge can check the count without trusting our engine: "one verifiable result" | The steps are translated into one DuckDB query (a CTE per step, `cohort_studio/sqlcheck.py`) and run on the raw files. The app shows engine vs SQL per step, and the SQL to copy or download (`cohort.sql`, runs with `python scripts/sql.py -f cohort.sql`). Agrees on all 30 step lists in `tests/test_verify.py` | A |
| 23 | ✅ Built Nov 12 | **"Why isn't sample X in my cohort?"** | Judges like checking one specific case. Covers the brief's stretch goal "explain each exclusion" | Text box in section 3 (and `run_cohort.py --why ID`). Traces the sample through the per-step SQL, names the step that removed it, and shows the values or records involved. Also explains samples missing from the manifest (#19) | A |
| 24 | ✅ Built Nov 12 | **"Data notes" panel** (limitations to inspect) | Shows we understand the data, not just the joins | List the quirks we found, with numbers: 24 normal samples missing from the manifest (#19), 6 redacted survival rows (#6), 3 HER2 columns that disagree (#17), age stored as text, coded values like `[Discrepancy]` (#7). Facts are in `TRAP_LOG.md`. **Built:** expander in section 4, computed live with DuckDB (`sqlcheck.data_notes()`): orphan normals, redacted rows, vital status vs OS, PAM50, gender. C can add more notes (HER2 columns, coded values) | A (+ C) |
| 25 | 🟠 Medium | **"Can't answer, and here's why"** | The rules call this a valid winning result | When a request needs data we don't have (treatment response; mutations until #3), say so clearly instead of building something close. `llm.py` already returns `cannot_answer`: make it prominent and test it | E |
| 26 | ✅ Built Nov 12 | **Compare two versions of a cohort** (a stretch goal in the brief) | Makes a fix visible: which samples changed and why | Section 4 keeps every distinct step list run in this session (`cohort_studio/versions.py`, session only, nothing written to disk) and compares the current cohort with any earlier one: rows/samples/patients deltas, a plain sentence, the sample IDs that moved and `cohort_diff.csv`. On the demo fix it says “exactly the same 731 samples, 45 duplicate rows gone”, which is the point a count alone can't make. Tests: `tests/test_versions.py` | D |
| 27 | 🟡 Low | **Makeup shift beyond site** | Beats the other team's single TVD number | Do #20 for site, PAM50 subtype, ER status and age band | unclaimed |
| 28 | ✅ Done Nov 12 | **"All five layers" variants** | The data README quotes 535 primary tumors with all five layers; a judge may add "with a diagnostic slide" | Engine already gives 535, and with a diagnostic slide 572 rows / 531 samples, flagged as inflation. Both are answer-key Cases and pass | A |
| 29 | ✅ Fixed Nov 12 | **Number filters on columns with blanks returned 0.** `objective = 40` matched nothing, because pandas stores the column as float (`40.0`) | Found by Verify with SQL while testing the 40x trap (SQL: 920, engine: 0) | `eq` / `in` / `ne` / `not_in` match numbers by value too, in the engine and the SQL translator. Test `test_numbers_match_by_value` | A |
| 30 | 🔴 High (found Nov 12) | **The dropdown builder drops OR groups and `allow_cross_sample`.** The engine supports them, but loading such steps into the app (JSON box, examples, AI draft) and letting the builder rewrite them removes them, so the cohort silently changes | HER2-positive via OR: app shows **1,101** instead of 197; triple-negative **220** instead of 158; tumor with normal slide is blocked from export (flag dropped). Verify with SQL still says Match because it checks the rewritten steps. Engine, CLI and tests are correct | `builder.py` must keep `{"any"/"all": [...]}` items and `allow_cross_sample` when it round-trips steps (at minimum: pass them through unchanged and show them read-only, e.g. "OR group (edit in JSON)"). Add an AppTest that loads `her2_positive` and expects 197 | D |

**Organizer rule (Discord, Nov 12):** `sample_manifest.csv` is the official list of samples and of what data each one has. The slide manifest only describes slides; don't use it to decide which samples exist.

## How each gap gets closed

Every fix by B or C should come with a `Case` in `tests/test_answer_key.py`: the correct answer as DuckDB SQL plus the
steps a user would build. A gap is closed when that test passes **and** the naive version is flagged.

**Done Nov 11:** #1 (left joins now offer only the collapse fix), #6 (info warning plus an "exclude redacted"
fix; it doesn't block export because we don't yet know what the checker expects), #14 (all file reads use UTF-8).
Each has a test.

**Done Nov 12:** #5 (dropdown step builder; the JSON view is now “Advanced”, and `tests/test_app.py` runs the real app with `AppTest`), and the exported `rebuild_cohort.py` is now tested (it reproduces the app's CSV exactly, `tests/test_rebuild.py`). The demo splits RNA (1,097) and protein (742) into separate steps so the funnel shows where tumors are lost.
#22 "Verify with SQL" is in the app (section 4), with `tests/test_verify.py`. #23 "Why isn't sample X" is in section 3. Both also run from the command line (`--verify`, `--why`). #29 fixed. Trap backlog #5–#12 done (all pass).
#21 the recommended fix is starred, explained and shown first (`cohort_studio/advice.py`, `tests/test_advice.py`). #26 compares the current cohort with any earlier version from the session (`cohort_studio/versions.py`, `tests/test_versions.py`).

**Next, before the Friday feature freeze:** 16 and 2 (engine: 4 trap tests are waiting on them) → 18 → 3 (data) · 4 (AI eval) · 21 (recommended fix) · the rest only if time allows.
