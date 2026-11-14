# Synthetic example for "Use your own data"

**Made-up data for demos and tests. Not real patients.** Generated with a fixed random seed.

- `samples.csv`: the sample list. One row per sample: 60 patients, each with a biopsy and some with a blood sample.
  Columns: sample_id, patient_id, sample_type (Biopsy / Blood), site, age, has_imaging.
- `labs.csv`: CRP lab results, **several per sample** (joining it inner repeats samples: inflation).
- `visits.csv`: one row per **patient** (smoker, bmi), no sample column.

Try: **blood samples with a lab result**, joining `labs` on `sample_id` with "Add its columns": samples with several
CRP results repeat (inflation). Then **biopsies with a lab result**, joining `labs` on `patient_id`: biopsies are kept
only because the same patient's *blood* sample had a lab result (a wrong-sample link). Cohort Studio flags both.
