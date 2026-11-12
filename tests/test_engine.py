import json
from pathlib import Path

from cohort_studio.engine import run, unresolved_problems
from cohort_studio.export import cohort_samples

EX = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EX / f"{name}.json").read_text())["steps"]


def kinds(result):
    return {w.kind for w in result.warnings}


def test_demo_slide_join_inflates():
    df, res = run(load("demo_diagnostic_slides"))
    assert [(r.rows, r.samples) for r in res] == [(1247, 1247), (1101, 1101), (742, 742), (776, 731)]
    assert "inflation" in kinds(res[3])
    assert unresolved_problems(res)


def test_semi_join_fix_resolves_inflation():
    _, res = run(load("demo_diagnostic_slides"))
    fix = next(w for w in res[3].warnings if w.kind == "inflation").fixes[0]["steps"]
    df, res2 = run(fix)
    assert res2[-1].rows == res2[-1].samples == 731
    assert not unresolved_problems(res2)
    out = cohort_samples(df)
    assert out["sample_id"].is_unique and len(out) == 731
    assert out["sample_id"].str.len().eq(15).all()


def test_patient_level_join_flags_cross_sample_links():
    _, res = run(load("trap_patient_level_survival"))
    assert {"inflation", "cross_sample"} <= kinds(res[-1])
    fix = next(w for w in res[-1].warnings if w.kind == "cross_sample").fixes[0]["steps"]
    _, res2 = run(fix)
    assert not unresolved_problems(res2)


def test_unknown_column_is_reported_not_crashed():
    _, res = run([{"op": "filter", "where": [{"column": "er_status", "operator": "eq", "values": ["x"]}]}])
    assert res[-1].error and "doesn't exist" in res[-1].error
