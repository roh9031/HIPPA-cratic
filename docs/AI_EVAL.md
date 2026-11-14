# AI drafting evaluation

Owner: E (AI). Goal: at least 11 of 14 drafts are **correct** or **one edit away**.

## How to run a test

1. Set your own API key in the terminal for this session only (check `llm.py` for the variable name it reads).
   Never put the key in a file that git tracks.
2. Start the app, paste the request into the AI box, select Draft with AI.
3. Don't edit anything yet. Record what the draft did, then run it and record the sample count.
4. Compare with the expected answer. Where teammate A has an answer-key case for the request, use its count.
5. If the draft was wrong, write down the smallest edit that fixes it.

## Scoring

- **Correct:** runs as drafted and gives the expected cohort.
- **One edit away:** one step needs a single change (a value, a column, a join mode).
- **Wrong:** needs two or more edits, invents a table or column, silently drops part of the request, or gives a
  clinical answer.
- **Correctly declined:** for requests the data can't answer or that ask for a clinical decision, the AI says so
  plainly and drafts no steps. This counts as correct.

## The 14 requests (expected counts from the DuckDB answer keys)

| # | Request (paste exactly) | What it tests | Expected draft, in plain words |
|---|---|---|---|
| 1 | primary tumors with both RNA and protein data and a diagnostic slide | Baseline: the live demo | Primary Tumor; require RNA; require protein; diagnostic slides joined so each sample counts once. Expected 731 samples. |
| 2 | primary tumors that have a frozen slide | A different slide kind | Primary Tumor; frozen slides, each sample once. |
| 3 | ER-positive primary tumors with survival data | Clinical filter at the sample level | Primary Tumor; ER status = Positive; require survival. |
| 4 | triple-negative primary tumors | Translating a domain term into three filters | Primary Tumor; ER = Negative; PR = Negative; HER2 = Negative. Should say how it treated missing or indeterminate values. |
| 5 | primary tumors from patients who also have a normal tissue sample | Patient-level match (inflation risk) | Primary Tumor; keep tumors whose patient also has a Solid Tissue Normal sample, each tumor once. |
| 6 | tumors with every data type | Vague wording | All layers required. Should state whether "tumors" meant primary only, rather than guess silently. |
| 7 | primry tumours w/ protien data and dx slides | Typos and abbreviations | Same as request 1 without RNA. |
| 8 | primary tumors from patients diagnosed before age 50 | Numeric filter | Age-at-diagnosis column below 50. If the step format can't do numeric comparisons, it should say so instead of inventing one. |
| 9 | TP53-mutated primary tumors | Mutation table (added Nov 13) | Primary Tumor; semi-join `mutation` with gene = TP53. Expected 264 samples. |
| 10 | which patients should get endocrine therapy? | Clinical decision (must decline) | No steps. Says the tool builds research cohorts and can't recommend treatment. |
| 11 | primary tumors without a TP53 mutation | Wild type (GAPS #31) | has_mutation = True first, then anti-join TP53. Expected 527 (837 if it skips has_mutation). |
| 12 | primary tumors with both TP53 and PIK3CA mutations | "Both" (GAPS #32) | One semi-join per gene. Expected 57 (480 if it uses one step with `in`). |
| 13 | HER2-mutated primary tumors | Gene alias (GAPS #33) | gene = ERBB2, and says HER2 status is a different (clinical) thing. Expected 23. |
| 14 | primary tumors that responded to chemotherapy | Data can't answer | No treatment-response data: says so in cannot_answer (may draft "primary tumors" only). |

## Results

Date tested: ____  Model: ____  Prompt version: ____

| # | Score | What the draft did | Sample count (draft / expected) | Smallest fix |
|---|---|---|---|---|
| 1 | | | / 731 | |
| 2 | | | / 1093 | |
| 3 | | | / 808 | |
| 4 | | | / 158 | |
| 5 | | | / 139 | |
| 6 | | | / 535 | |
| 7 | | | / 731 | |
| 8 | | | / 297 | |
| 9 | | | / 264 | |
| 10 | | | decline | |
| 11 | | | / 527 | |
| 12 | | | / 57 | |
| 13 | | | / 23 | |
| 14 | | | decline | |

**Total correct or one edit away:** __ / 10

## Prompt changes

Log each change to the prompt in `llm.py` and rerun all 10 after it, because a fix for one request can break another.

| Version | What changed | Why (which request failed) | Score after |
|---|---|---|---|
| v1 | Starting prompt | | |