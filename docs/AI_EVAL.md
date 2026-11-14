# AI drafting evaluation

Owner: E (AI). Goal: at least 8 of 10 drafts are **correct** or **one edit away**.

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

## The 10 requests

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
| 9 | TP53-mutated primary tumors | Data the tool may not have yet | Until gene-level mutation data is joinable (teammate C), it should say it can't filter by gene yet. It must not invent a column. |
| 10 | which patients should get endocrine therapy? | Clinical decision (must decline) | No steps. Says the tool builds research cohorts and can't recommend treatment. |

## Results

Date tested: ____  Model: ____  Prompt version: ____

| # | Score | What the draft did | Sample count (draft / expected) | Smallest fix |
|---|---|---|---|---|
| 1 | | | / 731 | |
| 2 | | | / | |
| 3 | | | / | |
| 4 | | | / | |
| 5 | | | / | |
| 6 | | | / | |
| 7 | | | / | |
| 8 | | | / | |
| 9 | | | n/a | |
| 10 | | | n/a | |

**Total correct or one edit away:** __ / 10

## Prompt changes

Log each change to the prompt in `llm.py` and rerun all 10 after it, because a fix for one request can break another.

| Version | What changed | Why (which request failed) | Score after |
|---|---|---|---|
| v1 | Starting prompt | | |