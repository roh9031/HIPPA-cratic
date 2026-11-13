"""Answer-key tests: our engine vs. an independent DuckDB SQL query.

This mirrors how judging works: the organizers' checker compares our cohort_samples.csv with a correct
cohort. For every case below we write the *correct* cohort as plain SQL, run straight on the raw files
(no engine code involved), and check that the engine's exported sample set is identical.

To add a trap: add a Case with
  - request: the plain-English ask
  - sql:     a query returning one column, sample_id, that is the right answer
             (try it first: python scripts/sql.py)
  - steps:   the engine steps a careful user ends up with (after applying fixes)
  - naive:   (optional) the steps a careless user would write first. The engine must flag them.
  - gap:     (optional) if the engine can't do this yet, the GAPS.md item, e.g. "#2". The test is then
             recorded as an expected failure (xfail) instead of breaking the suite. When someone fixes the
             engine, pytest reports XPASS and fails, so the gap gets removed and the test becomes a normal one.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("duckdb")

from cohort_studio import data
from cohort_studio.engine import run, unresolved_problems
from cohort_studio.export import cohort_samples
from cohort_studio.sqlcheck import connect


@pytest.fixture(scope="module")
def db():
    con = connect()
    yield con
    con.close()


PRIMARY = {"op": "filter", "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]}
RNA_PROTEIN = {"op": "filter", "where": [{"column": "has_rna", "operator": "eq", "values": ["True"]},
                                         {"column": "has_protein", "operator": "eq", "values": ["True"]}]}
DIAG = [{"column": "slide_kind", "operator": "startswith", "values": ["diagnostic"]}]
FROZEN = [{"column": "slide_kind", "operator": "startswith", "values": ["frozen"]}]
def _semi(table, where):
    return {"op": "join", "table": table, "on": "sample_id", "how": "semi", "where": where}


FIVE_LAYERS = {"op": "filter", "where": [{"column": c, "operator": "eq", "values": ["True"]} for c in
                                         ("has_survival", "has_mutation", "has_copy_number", "has_rna", "has_protein")]}
ER_POS = {"op": "filter", "where": [{"column": "breast_carcinoma_estrogen_receptor_status",
                                     "operator": "eq", "values": ["Positive"]}]}


@dataclass
class Case:
    name: str
    request: str
    sql: str
    steps: list
    naive: list | None = None
    expected_n: int | None = None   # pin the count once we've checked it by hand
    notes: str = ""
    gap: str | None = None          # GAPS.md item the engine still fails on -> test is xfail


CASES = [
    Case(
        "demo_diagnostic_slides",
        "Primary tumors with both RNA and protein data and a diagnostic slide",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor' AND has_rna AND has_protein
             AND sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%')""",
        steps=[PRIMARY, RNA_PROTEIN, {"op": "join", "table": "slides", "on": "sample_id", "how": "semi", "where": DIAG}],
        naive=[PRIMARY, RNA_PROTEIN, {"op": "join", "table": "slides", "on": "sample_id", "how": "inner", "where": DIAG}],
        expected_n=731,
    ),
    Case(
        "demo_fixed_by_collapse",
        "Same as the demo, but keep slide columns and collapse to one row per sample",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor' AND has_rna AND has_protein
             AND sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%')""",
        steps=[PRIMARY, RNA_PROTEIN, {"op": "join", "table": "slides", "on": "sample_id", "how": "inner", "where": DIAG},
               {"op": "collapse", "level": "sample"}],
        expected_n=731,
    ),
    Case(
        "frozen_slides",
        "Primary tumors that have a frozen-section slide",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'frozen%')""",
        steps=[PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "semi", "where": FROZEN}],
        naive=[PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "inner", "where": FROZEN}],
    ),
    Case(
        "er_positive_with_survival",
        "ER-positive primary tumors with overall survival data",
        """SELECT s.sample_id FROM samples s
           JOIN clinical c ON c.sample_id = s.sample_id
           WHERE s.sample_type = 'Primary Tumor'
             AND lower(c.breast_carcinoma_estrogen_receptor_status) = 'positive'
             AND s.sample_id IN (SELECT sample_id FROM survival WHERE "OS.time" IS NOT NULL)""",
        steps=[PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "inner"}, ER_POS,
               {"op": "join", "table": "survival", "on": "sample_id", "how": "inner",
                "where": [{"column": "OS.time", "operator": "notnull"}]}],
        # the shipped trap example: survival joined on patient_id
        naive=[PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "inner"}, ER_POS,
               {"op": "join", "table": "survival", "on": "patient_id", "how": "inner",
                "where": [{"column": "OS.time", "operator": "notnull"}]}],
    ),
    Case(
        "five_year_followup",
        "Primary tumors followed up for at least 5 years (OS.time >= 1825 days)",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM survival WHERE "OS.time" >= 1825)""",
        steps=[PRIMARY, {"op": "join", "table": "survival", "on": "sample_id", "how": "semi",
                         "where": [{"column": "OS.time", "operator": "ge", "values": ["1825"]}]}],
    ),
    Case(
        "left_join_slides_collapsed",
        "All primary tumors, with slide details where a slide exists",
        "SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor'",
        steps=[PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "left"},
               {"op": "collapse", "level": "sample"}],
        naive=[PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "left"}],
        expected_n=1101,
        notes="GAPS.md #1: the semi-join fix would wrongly give 1,098 here.",
    ),
    Case(
        "survival_excluding_redacted",
        "Primary tumors with overall survival data, excluding redacted records",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM survival
                               WHERE "OS.time" IS NOT NULL AND Redaction IS NULL)""",
        steps=[PRIMARY, {"op": "join", "table": "survival", "on": "sample_id", "how": "semi",
                         "where": [{"column": "OS.time", "operator": "notnull"},
                                   {"column": "Redaction", "operator": "isnull"}]}],
        notes="Only when the user explicitly asks to exclude them. By default they stay in (next case). GAPS.md #6.",
    ),
    Case(
        "survival_keeps_redacted",
        "Primary tumors with overall survival data",
        # Organizer rule (Discord, Nov 12): the sample manifest marks the 5 redacted primary tumors as having survival
        # data, so they stay in the cohort. The tool flags them (info note) for a person to look at.
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM survival WHERE "OS.time" IS NOT NULL)""",
        steps=[PRIMARY, _semi("survival", [{"column": "OS.time", "operator": "notnull"}])],
        notes="Includes the 5 redacted primary tumors. GAPS.md #6.",
    ),
    Case(
        "no_diagnostic_slide",
        "Primary tumors with RNA data but no diagnostic slide",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor' AND has_rna
             AND sample_id NOT IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%')""",
        steps=[PRIMARY, {"op": "filter", "where": [{"column": "has_rna", "operator": "eq", "values": ["True"]}]},
               {"op": "join", "table": "slides", "on": "sample_id", "how": "anti", "where": DIAG}],
    ),
    Case(
        "diagnostic_slide_patient_join",
        "Primary tumors with a diagnostic slide (naive: matched on patient_id)",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%')""",
        steps=[PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "semi", "where": DIAG}],
        # Matching on patient_id wrongly keeps TCGA-E2-A15E-01: its only diagnostic slide is from the
        # patient's metastatic sample (-06). Engine flags it; the fix gives the answer.
        naive=[PRIMARY, {"op": "join", "table": "slides", "on": "patient_id", "how": "semi", "where": DIAG}],
        expected_n=1061,
    ),
    Case(
        "frozen_slide_patient_join",
        "Primary tumors with frozen-section slide details (naive: inner join on patient_id)",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'frozen%')""",
        steps=[PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "semi", "where": FROZEN}],
        # Naive version: 1,978 rows for 1,093 tumors, 406 of them another sample's slide (mostly the normal's).
        # Same sample set, but every slide-level column on those rows is wrong. Engine flags both problems.
        naive=[PRIMARY, {"op": "join", "table": "slides", "on": "patient_id", "how": "inner", "where": FROZEN}],
        expected_n=1093,
    ),
    # ---------------------------------------------------------------- traps that still fail (xfail)
    Case(
        "tumor_with_normal_slide",
        "Primary tumors whose patient has a matched normal sample with a slide",
        # Organizer rule (Discord, Nov 12): sample_manifest.csv is the official list of samples; the slide manifest
        # only describes slides. So the normal sample must be in the manifest AND have a slide = 138. The 24 normal
        # samples that only appear in slide_manifest.csv are left out (counting them gave 162). See gap #19.
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND patient_id IN (SELECT n.patient_id FROM samples n
                                WHERE n.sample_type = 'Solid Tissue Normal'
                                  AND n.sample_id IN (SELECT sample_id FROM slides))""",
        # The steps use the manifest's slides_for_sample; the key checks slide_manifest.csv instead (both 138),
        # so the answer key stays independent of the column the engine relies on.
        steps=[PRIMARY, {"op": "join", "table": "samples", "on": "patient_id", "how": "semi",
                         "allow_cross_sample": True,
                         "where": [{"column": "sample_type", "operator": "eq", "values": ["Solid Tissue Normal"]},
                                   {"column": "slides_for_sample", "operator": "gt", "values": ["0"]}]}],
        expected_n=138,
    ),
    Case(
        "tumor_with_matched_normal",
        "Primary tumors whose patient also has a matched normal-tissue sample",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND patient_id IN (SELECT patient_id FROM samples WHERE sample_type = 'Solid Tissue Normal')""",
        steps=[PRIMARY, {"op": "join", "table": "clinical", "on": "patient_id", "how": "semi",
                         "allow_cross_sample": True,
                         "where": [{"column": "sample_type", "operator": "eq", "values": ["Solid Tissue Normal"]}]}],
        expected_n=139,
    ),
    Case(
        "her2_positive",
        "HER2-positive primary tumors",
        # Decision: HER2+ = IHC Positive OR ISH (FISH) Positive, the standard rule. ISH settles equivocal IHC.
        # Alternatives give very different cohorts: HER2_Final_Status_nature2012 = 114 (blank for 325 tumors),
        # IHC only = 164, IHC or ISH = 197. Whichever the judges use, the app must show which column it chose.
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM clinical
                               WHERE lab_proc_her2_neu_immunohistochemistry_receptor_status = 'Positive'
                                  OR lab_procedure_her2_neu_in_situ_hybrid_outcome_type = 'Positive')""",
        steps=[PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi",
                         "where": [{"any": [
                             {"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status",
                              "operator": "eq", "values": ["Positive"]},
                             {"column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type",
                              "operator": "eq", "values": ["Positive"]},
                         ]}]}],
        expected_n=197,
    ),
    Case(
        "triple_negative",
        "Triple-negative primary tumors (ER-, PR-, HER2-)",
        # Decision: ER and PR must be exactly 'Negative' (Indeterminate/blank = unknown, excluded).
        # HER2-negative = IHC Negative and ISH not Positive, OR IHC not Positive and ISH Negative (mirror of
        # her2_positive). Excludes 21 ER-/PR- tumors with unknown HER2. Alternatives: IHC-only = 116,
        # "not HER2-positive" = 179 (keeps the 21 unknowns), nature2012 column = 123. See docs/TRAP_LOG.md.
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (
               SELECT sample_id FROM clinical
               WHERE breast_carcinoma_estrogen_receptor_status = 'Negative'
                 AND breast_carcinoma_progesterone_receptor_status = 'Negative'
                 AND ((lab_proc_her2_neu_immunohistochemistry_receptor_status = 'Negative'
                       AND coalesce(lab_procedure_her2_neu_in_situ_hybrid_outcome_type, '') <> 'Positive')
                   OR (coalesce(lab_proc_her2_neu_immunohistochemistry_receptor_status, '') <> 'Positive'
                       AND lab_procedure_her2_neu_in_situ_hybrid_outcome_type = 'Negative')))""",
        steps=[PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi", "where": [
            {"column": "breast_carcinoma_estrogen_receptor_status", "operator": "eq", "values": ["Negative"]},
            {"column": "breast_carcinoma_progesterone_receptor_status", "operator": "eq", "values": ["Negative"]},
            {"any": [
                {"all": [
                    {"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status", "operator": "eq",
                     "values": ["Negative"]},
                    {"any": [
                        {"column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type", "operator": "ne",
                         "values": ["Positive"]},
                        {"column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type", "operator": "isnull",
                         "values": []},
                    ]},
                ]},
                {"all": [
                    {"any": [
                        {"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status", "operator": "ne",
                         "values": ["Positive"]},
                        {"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status", "operator": "isnull",
                         "values": []},
                    ]},
                    {"column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type", "operator": "eq",
                     "values": ["Negative"]},
                ]},
            ]},
        ]}],
        expected_n=158,
    ),
    # The data README quotes this number, so it's the most likely request a judge starts from.
    Case(
        "all_five_layers",
        "Primary tumors with all five data layers (survival, mutation, copy number, RNA, protein)",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND has_survival AND has_mutation AND has_copy_number AND has_rna AND has_protein""",
        steps=[PRIMARY, FIVE_LAYERS],
        expected_n=535,
        notes="Matches the 535 in the challenge's data/tcga-brca/README.md. 535 patients too (no duplicates).",
    ),
    Case(
        "tp53_mutated_primary",
        "Primary tumors with a TP53 mutation",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (
               SELECT sample_id FROM mutation WHERE gene = 'TP53' AND mutated
             )""",
        steps=[PRIMARY, _semi("mutation", [
            {"column": "gene", "operator": "eq", "values": ["TP53"]},
            {"column": "mutated", "operator": "eq", "values": ["true"]},
        ])],
        notes="Uses the binary gene-level matrix; this identifies mutation presence, not a specific variant.",
    ),
    Case(
        "tp53_wild_type_primary",
        "Primary tumors without a TP53 mutation",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor' AND has_mutation
             AND sample_id NOT IN (SELECT sample_id FROM mutation WHERE gene = 'TP53')""",
        steps=[PRIMARY, {"op": "filter", "where": [{"column": "has_mutation", "operator": "eq", "values": ["True"]}]},
               {"op": "join", "table": "mutation", "on": "sample_id", "how": "anti",
                "where": [{"column": "gene", "operator": "eq", "values": ["TP53"]}]}],
        expected_n=527,
        # Trap (GAPS.md #31): the anti-join alone gives 837, because 310 primary tumors were never sequenced
        # and so have no TP53 row either. "No mutation found" needs has_mutation first.
        notes="Wild type = sequenced and no TP53 row. Without the has_mutation filter: 837.",
    ),
    Case(
        "all_five_layers_diagnostic_slide",
        "Primary tumors with all five data layers and a diagnostic slide",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND has_survival AND has_mutation AND has_copy_number AND has_rna AND has_protein
             AND sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%')""",
        steps=[PRIMARY, FIVE_LAYERS, {"op": "join", "table": "slides", "on": "sample_id", "how": "semi", "where": DIAG}],
        # Naive inner join: 572 rows / 531 samples (41 extra rows), flagged as inflation.
        naive=[PRIMARY, FIVE_LAYERS, {"op": "join", "table": "slides", "on": "sample_id", "how": "inner", "where": DIAG}],
        expected_n=531,
    ),
    # ---- Nov 12 batch: TRAPS.md #5-#12. Queries and alternatives in docs/TRAP_LOG.md.
    Case(
        "age_over_50",
        "Primary tumors from patients diagnosed over age 50",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor' AND sample_id IN (
             SELECT sample_id FROM clinical WHERE TRY_CAST(age_at_initial_pathologic_diagnosis AS DOUBLE) > 50)""",
        steps=[PRIMARY, _semi("clinical", [{"column": "age_at_initial_pathologic_diagnosis", "operator": "gt", "values": ["50"]}])],
        expected_n=766,
        notes="'Over 50' = strictly > 50 (34 tumors are exactly 50; >= 50 gives 800). Age is text in clinical.tsv. "
              "Age_at_Initial_Pathologic_Diagnosis_nature2012 is mostly blank (569).",
    ),
    Case(
        "female",
        "Primary tumors from female patients",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor' AND sample_id IN (
             SELECT sample_id FROM clinical WHERE gender = 'FEMALE')""",
        steps=[PRIMARY, _semi("clinical", [{"column": "gender", "operator": "eq", "values": ["female"]}])],
        expected_n=1085,
        notes="12 male, 4 unknown. Gender_nature2012 disagrees for TCGA-E2-A14W-01 (MALE vs FEMALE).",
    ),
    Case(
        "died",
        "Primary tumors from patients who died (overall survival event)",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor' AND sample_id IN (
             SELECT sample_id FROM survival WHERE OS = 1)""",
        steps=[PRIMARY, _semi("survival", [{"column": "OS", "operator": "eq", "values": ["1"]}])],
        expected_n=151,
        notes="Decision: the curated survival table (OS = 1). clinical vital_status = DECEASED gives 152: "
              "TCGA-E9-A245-01 is DECEASED there but OS = 0 (OS.time 26).",
    ),
    Case(
        "luminal_a",
        "Luminal A primary tumors",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor' AND sample_id IN (
             SELECT sample_id FROM clinical WHERE PAM50Call_RNAseq = 'LumA')""",
        steps=[PRIMARY, _semi("clinical", [{"column": "PAM50Call_RNAseq", "operator": "eq", "values": ["LumA"]}])],
        expected_n=421,
        notes="Decision: PAM50Call_RNAseq (covers more tumors). PAM50_mRNA_nature2012 = 'Luminal A' gives 231, and "
              "where both columns have a call, they disagree on Luminal A for 43 tumors. Typing 'Luminal A' on the RNAseq column gives 0 (empty warning).",
    ),
    Case(
        "diagnostic_slide_40x",
        "Primary tumors with a 40x diagnostic slide",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor' AND sample_id IN (
             SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%' AND objective = 40)""",
        steps=[PRIMARY, _semi("slides", DIAG + [{"column": "objective", "operator": "eq", "values": ["40"]}])],
        naive=[PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "inner",
                         "where": DIAG + [{"column": "objective", "operator": "eq", "values": ["40"]}]}],
        expected_n=920,
        notes="Found by Verify with SQL: the engine returned 0 because objective has blanks, so pandas reads 40 as 40.0 "
              "and the text match failed. Fixed Nov 12 (numbers now match by value).",
    ),
    Case(
        "only_20x_diagnostic_slides",
        "Primary tumors whose diagnostic slides are all 20x",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor'
             AND sample_id IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%' AND objective = 20)
             AND sample_id NOT IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%'
                                   AND objective IS DISTINCT FROM 20)""",
        steps=[PRIMARY, _semi("slides", DIAG + [{"column": "objective", "operator": "eq", "values": ["20"]}]),
               {"op": "join", "table": "slides", "on": "sample_id", "how": "anti",
                "where": DIAG + [{"column": "objective", "operator": "ne", "values": ["20"]}]}],
        expected_n=134,
        notes="'Only' needs an anti-join. In this data no tumor mixes 20x and 40x diagnostic slides, so any-20x = "
              "only-20x = 134. Also depended on the 40 = 40.0 fix.",
    ),
    Case(
        "no_survival_record",
        "Primary tumors with no survival record",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor'
             AND sample_id NOT IN (SELECT sample_id FROM survival)""",
        steps=[PRIMARY, {"op": "join", "table": "survival", "on": "sample_id", "how": "anti"}],
        expected_n=4,
    ),
    Case(
        "all_tumor_samples",
        "All tumor samples",
        """SELECT sample_id FROM samples WHERE sample_type <> 'Solid Tissue Normal'""",
        steps=[{"op": "filter", "where": [{"column": "sample_type", "operator": "ne", "values": ["Solid Tissue Normal"]}]}],
        expected_n=1108,
        notes="Decision: 'tumor' includes the 7 Metastatic samples. Trap: sample_type contains 'tumor' gives 1101 and "
              "silently drops them (no warning possible: it's a wording question, gap #8).",
    ),
    Case(
        "one_tumor_per_patient",
        "One tumor sample per patient, preferring the primary tumor",
        """SELECT sample_id FROM samples WHERE sample_type = 'Primary Tumor'""",
        steps=[{"op": "filter", "where": [{"column": "sample_type", "operator": "ne", "values": ["Solid Tissue Normal"]}]},
               {"op": "collapse", "level": "patient"}],
        expected_n=1101,
        notes="All 7 metastatic samples belong to patients who also have a primary, so 1,108 tumors = 1,101 patients. "
              "Collapse keeps the first row in the file, which is the primary only because the manifest lists it "
              "first (gap #9).",
    ),
]


def test_mutation_table_is_sparse_and_manifest_bound():
    mutations = data.load("mutation")
    samples = data.load("samples")
    manifest_samples = set(samples["sample_id"])

    assert set(mutations.columns) == {"sample_id", "patient_id", "gene", "mutated"}
    assert mutations["sample_id"].isin(manifest_samples).all()
    assert mutations["sample_id"].str.len().eq(15).all()
    assert mutations["patient_id"].eq(mutations["sample_id"].str[:12]).all()
    assert mutations["mutated"].all()
    assert not mutations.duplicated(["sample_id", "gene"]).any()


def _param(c):
    marks = [pytest.mark.xfail(strict=True, reason=f"known gap {c.gap} in docs/GAPS.md")] if c.gap else []
    return pytest.param(c, id=c.name, marks=marks)


def _engine_ids(steps):
    df, results = run(steps)
    assert not any(r.error for r in results), [r.error for r in results if r.error]
    out = cohort_samples(df)
    assert out["sample_id"].is_unique
    return set(out["sample_id"]), results


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
def test_engine_matches_sql_answer_key(db, case):
    expected = {r[0] for r in db.sql(case.sql).fetchall()}
    got, results = _engine_ids(case.steps)
    missing, extra = sorted(expected - got), sorted(got - expected)
    assert not missing and not extra, f"{case.name}: missing {missing[:5]} ({len(missing)}), extra {extra[:5]} ({len(extra)})"
    assert not unresolved_problems(results), f"{case.name}: correct steps still flagged: {unresolved_problems(results)}"
    if case.expected_n is not None:
        assert len(expected) == case.expected_n


@pytest.mark.parametrize("case", [c for c in CASES if c.naive], ids=[c.name for c in CASES if c.naive])
def test_naive_version_is_flagged(case):
    _, results = run(case.naive)
    assert unresolved_problems(results), f"{case.name}: the careless version wasn't flagged"
