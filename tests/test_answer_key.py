"""Answer-key tests: our engine vs. an independent DuckDB SQL query.

This mirrors how judging works: the organizers' checker compares our cohort_samples.csv with a correct
cohort. For every case below we write the *correct* cohort as plain SQL, run straight on the raw files
(no engine code involved), and check that the engine's exported sample set is identical.

To add a trap: add a Case with
  - request: the plain-English ask
  - sql:     a query returning one column, sample_id, that is the right answer
  - steps:   the engine steps a careful user ends up with (after applying fixes)
  - naive:   (optional) the steps a careless user would write first. The engine must flag them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

duckdb = pytest.importorskip("duckdb")

from cohort_studio import data
from cohort_studio.engine import run, unresolved_problems
from cohort_studio.export import cohort_samples


@pytest.fixture(scope="module")
def db():
    d = data.data_dir().as_posix()
    con = duckdb.connect()
    con.sql(f"CREATE VIEW samples  AS SELECT * FROM read_csv('{d}/sample_manifest.csv')")
    con.sql(f"CREATE VIEW slides   AS SELECT * FROM read_csv('{d}/slide_manifest.csv')")
    con.sql(f"CREATE VIEW survival AS SELECT sample AS sample_id, _PATIENT AS patient_id, * "
            f"FROM read_csv('{d}/raw/survival.tsv', delim='\t')")
    # clinical.tsv's own patient_id is a 4-char suffix; the sample barcode is the real key.
    con.sql(f"CREATE VIEW clinical AS SELECT sampleID AS sample_id, * "
            f"FROM read_csv('{d}/raw/clinical.tsv', delim='\t', all_varchar=true)")
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
        "no_diagnostic_slide",
        "Primary tumors with RNA data but no diagnostic slide",
        """SELECT sample_id FROM samples
           WHERE sample_type = 'Primary Tumor' AND has_rna
             AND sample_id NOT IN (SELECT sample_id FROM slides WHERE slide_kind LIKE 'diagnostic%')""",
        steps=[PRIMARY, {"op": "filter", "where": [{"column": "has_rna", "operator": "eq", "values": ["True"]}]},
               {"op": "join", "table": "slides", "on": "sample_id", "how": "anti", "where": DIAG}],
    ),
]


def _engine_ids(steps):
    df, results = run(steps)
    assert not any(r.error for r in results), [r.error for r in results if r.error]
    out = cohort_samples(df)
    assert out["sample_id"].is_unique
    return set(out["sample_id"]), results


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
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
