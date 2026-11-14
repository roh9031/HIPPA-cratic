"""The "Verify with SQL" check: the DuckDB translation of a step list must agree with the engine,
step by step (rows, samples, patients) and sample by sample, for every answer-key case and example."""
import json
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from cohort_studio.engine import run
from cohort_studio.sqlcheck import verify

from test_answer_key import CASES

EX = Path(__file__).resolve().parents[1] / "examples"
STEP_LISTS = (
    [(c.name, c.steps) for c in CASES]
    + [(f"{c.name}_naive", c.naive) for c in CASES if c.naive]
    + [(p.stem, json.loads(p.read_text(encoding="utf-8"))["steps"]) for p in sorted(EX.glob("*.json"))]
    + [("patient_collapse", [{"op": "collapse", "level": "patient"}]),
       ("numeric_gt_after_left_join", [{"op": "join", "table": "clinical", "on": "sample_id", "how": "left"},
                                       {"op": "filter", "where": [{"column": "age_at_initial_pathologic_diagnosis",
                                                                   "operator": "gt", "values": ["50"]}]}]),
       ("anti_join", [{"op": "join", "table": "slides", "on": "sample_id", "how": "anti"}])]
)


@pytest.mark.parametrize("name,steps", STEP_LISTS, ids=[n for n, _ in STEP_LISTS])
def test_sql_translation_agrees_with_engine(name, steps):
    df, res = run(steps)
    v = verify(steps, df, res)
    assert v["match"], (v["by_step"], v["only_engine"][:5], v["only_sql"][:5])


def test_verify_reports_a_mismatch():
    steps = CASES[0].steps
    df, res = run(steps)
    dropped = df["sample_id"].iloc[0]
    v = verify(steps, df[df["sample_id"] != dropped], res)
    assert not v["match"] and v["only_sql"] == [dropped]


# ---------------------------------------------------------------- "Why isn't sample X in my cohort?"
from cohort_studio.sqlcheck import trace  # noqa: E402

FIXED_DEMO = [*CASES[0].steps]


def test_trace_explains_a_join_drop_with_the_records():
    # Has a slide, but only a frozen one: the metastatic -06 sample of the same patient holds the diagnostic slide.
    t = trace(FIXED_DEMO, "tcga-e2-a15e-01")
    assert t["status"] == "removed" and t["removed_at"] == len(FIXED_DEMO)
    assert t["details"] == [{"sample_id": "TCGA-E2-A15E-01", "slide_kind": "frozen, top section"}]


def test_trace_explains_a_filter_drop_with_the_value():
    t = trace(FIXED_DEMO, "TCGA-A7-A0DC-11")
    assert t["removed_at"] == 1 and t["details"][0]["sample_type"] == "Solid Tissue Normal"


def test_trace_handles_gene_mutation_join():
    case = next(c for c in CASES if c.name == "tp53_mutated_primary")
    con = connect()
    try:
        sample_id = con.sql(case.sql).fetchall()[0][0]
    finally:
        con.close()

    t = trace(case.steps, sample_id)
    assert t["status"] == "in_cohort"
    assert t["path"][-1]["rows for this sample"] == 1


def test_trace_sample_in_cohort_and_unknown_and_orphan():
    assert trace(FIXED_DEMO, "TCGA-A7-A0DC-01")["status"] == "in_cohort"
    assert trace(FIXED_DEMO, "TCGA-XX-0000-01")["status"] == "not_in_manifest"
    orphan = trace(FIXED_DEMO, "TCGA-A7-A56D-11")  # has slides but isn't in sample_manifest.csv (gap #19)
    assert orphan["status"] == "not_in_manifest" and "slide" in orphan["why"]


def test_trace_patient_collapse_names_the_kept_sample():
    t = trace([{"op": "collapse", "level": "patient"}], "TCGA-E2-A15E-06")
    assert "TCGA-E2-A15E-01" in t["why"]


def test_numbers_match_by_value():
    # objective has blanks, so pandas stores 40 as 40.0. "objective = 40" used to return 0 samples.
    steps = [{"op": "join", "table": "slides", "on": "sample_id", "how": "semi",
              "where": [{"column": "objective", "operator": "eq", "values": ["40"]}]}]
    df, res = run(steps)
    assert res[-1].samples > 900
    assert verify(steps, df, res)["match"]
    ne = [{"op": "join", "table": "slides", "on": "sample_id", "how": "semi",
           "where": [{"column": "objective", "operator": "ne", "values": ["40.0"]}]}]
    df2, res2 = run(ne)
    assert verify(ne, df2, res2)["match"]


# ---------------------------------------------------------------- Data notes (organizer rules, Nov 12)
from cohort_studio.sqlcheck import data_notes  # noqa: E402


def test_data_notes_point_out_file_mismatches():
    titles = " | ".join(n["title"] for n in data_notes())
    assert "24 samples have slides but aren't in the sample manifest" in titles
    assert "6 survival records are marked redacted" in titles


def test_orphan_normal_slides_never_enter_a_cohort():
    # Organizer rule: sample_manifest.csv is the official sample list. Slides of samples missing from it can't join.
    steps = [{"op": "join", "table": "slides", "on": "sample_id", "how": "inner"}]
    df, _ = run(steps)
    assert "TCGA-A7-A56D-11" not in set(df["sample_id"])


def test_redacted_survival_records_are_kept_but_flagged():
    # Organizer rule: keep them (the manifest says they have survival data), and flag them for review.
    steps = [{"op": "filter", "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]},
             {"op": "join", "table": "survival", "on": "sample_id", "how": "semi",
              "where": [{"column": "OS.time", "operator": "notnull"}]}]
    df, res = run(steps)
    assert "TCGA-A7-A0DC-01" in set(df["sample_id"])
    w = next(w for w in res[-1].warnings if w.kind == "redacted")
    assert w.severity == "info" and "kept" in w.message


# ---------------------------------------------------------------- OR groups {"any": [...]} (GAPS.md #16)
# The SQL side is ready before the engine: these tests don't run the engine on OR steps.
from cohort_studio.sqlcheck import connect, steps_to_sql  # noqa: E402

_IHC = "lab_proc_her2_neu_immunohistochemistry_receptor_status"
_ISH = "lab_procedure_her2_neu_in_situ_hybrid_outcome_type"
_OR_HER2 = [{"op": "filter", "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]},
            {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi",
             "where": [{"any": [{"column": _IHC, "operator": "eq", "values": ["Positive"]},
                                {"column": _ISH, "operator": "eq", "values": ["Positive"]}]}]}]


def test_sql_or_group_matches_her2_answer_key():
    her2 = next(c for c in CASES if c.name == "her2_positive")
    con = connect()
    try:
        con.sql("SET threads TO 1")
        got = {r[0] for r in con.sql(steps_to_sql(_OR_HER2, con)).fetchall()}
        assert got == {r[0] for r in con.sql(her2.sql).fetchall()} and len(got) == 197
    finally:
        con.close()


def test_sql_or_group_is_bracketed_before_and():
    # (IHC OR ISH) AND sample_type: without brackets SQL would read IHC OR (ISH AND ...).
    steps = [{"op": "filter", "where": [{"any": [{"column": "sample_type", "operator": "eq", "values": ["Metastatic"]},
                                                 {"column": "sample_type", "operator": "eq", "values": ["Solid Tissue Normal"]}]},
                                        {"column": "has_rna", "operator": "eq", "values": ["True"]}]}]
    con = connect()
    try:
        n = len(con.sql(steps_to_sql(steps, con)).fetchall())
        expected = con.sql("SELECT count(*) FROM samples WHERE sample_type IN ('Metastatic', 'Solid Tissue Normal') "
                           "AND has_rna").fetchall()[0][0]
        assert n == expected
    finally:
        con.close()


def test_trace_handles_or_groups():
    t = trace(_OR_HER2, "TCGA-A7-A0DC-01")
    assert t["status"] == "removed" and set(t["details"][0]) == {"sample_id", _IHC, _ISH}
