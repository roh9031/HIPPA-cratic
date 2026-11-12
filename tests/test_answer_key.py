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
        notes="GAPS.md #6.",
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
    # ---------------------------------------------------------------- traps that still fail (xfail)
    Case(
        "tumor_with_matched_normal",
        "Primary tumors whose patient also has a matched normal-tissue sample",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor'
             AND patient_id IN (SELECT patient_id FROM samples WHERE sample_type = 'Solid Tissue Normal')""",
        # Best the engine can do today: keep tumors whose *patient* has a normal clinical record. The sample set is
        # right, but matching on patient_id is always flagged as a cross-sample problem, so export is blocked.
        steps=[PRIMARY, {"op": "join", "table": "clinical", "on": "patient_id", "how": "semi",
                         "where": [{"column": "sample_type", "operator": "eq", "values": ["Solid Tissue Normal"]}]}],
        expected_n=139,
        gap="#2",
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
        # Closest the engine can get: conditions are AND-only, so it can't say "IHC positive OR ISH positive".
        steps=[PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi",
                         "where": [{"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status",
                                    "operator": "eq", "values": ["Positive"]}]}],
        expected_n=197,
        gap="#16",
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
        # Most natural engine attempt: all three = Negative. Gives 116 (misses 44, wrongly includes 2) and no
        # warning at all, because conditions inside a join skip the missing-value check (gap #18).
        steps=[PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi", "where": [
            {"column": "breast_carcinoma_estrogen_receptor_status", "operator": "eq", "values": ["Negative"]},
            {"column": "breast_carcinoma_progesterone_receptor_status", "operator": "eq", "values": ["Negative"]},
            {"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status", "operator": "eq", "values": ["Negative"]},
        ]}],
        expected_n=158,
        gap="#16",
    ),
]


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
