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
