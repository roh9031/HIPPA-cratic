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
