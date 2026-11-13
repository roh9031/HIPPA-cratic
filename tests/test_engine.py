import json
from pathlib import Path

import pandas as pd

from cohort_studio.engine import _mask, run, unresolved_problems
from cohort_studio.export import cohort_samples

EX = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EX / f"{name}.json").read_text(encoding="utf-8"))["steps"]


def kinds(result):
    return {w.kind for w in result.warnings}


def test_demo_slide_join_inflates():
    df, res = run(load("demo_diagnostic_slides"))
    assert [(r.rows, r.samples) for r in res] == [(1247, 1247), (1101, 1101), (1097, 1097), (742, 742), (776, 731)]
    assert "inflation" in kinds(res[4])
    assert unresolved_problems(res)


def test_semi_join_fix_resolves_inflation():
    _, res = run(load("demo_diagnostic_slides"))
    fix = next(w for w in res[4].warnings if w.kind == "inflation").fixes[0]["steps"]
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


def test_intentional_patient_level_match_allows_cross_sample_selection():
    steps = load("trap_patient_level_survival")
    steps[-1]["allow_cross_sample"] = True
    _, res = run(steps)
    assert "cross_sample" not in kinds(res[-1])


def test_allow_cross_sample_must_be_boolean():
    _, res = run([{"op": "join", "table": "survival", "on": "patient_id",
                   "allow_cross_sample": "yes"}])
    assert res[0].error and "allow_cross_sample must be true or false" in res[0].error


def test_allow_cross_sample_requires_patient_existence_join():
    _, res = run([{"op": "join", "table": "survival", "on": "patient_id",
                   "how": "inner", "allow_cross_sample": True}])
    assert res[0].error and "requires a semi or anti join" in res[0].error


def test_unknown_column_is_reported_not_crashed():
    _, res = run([{"op": "filter", "where": [{"column": "er_status", "operator": "eq", "values": ["x"]}]}])
    assert res[-1].error and "doesn't exist" in res[-1].error


PRIMARY = {"op": "filter", "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]}


def test_left_join_inflation_offers_only_collapse_fix():
    # A semi-join "fix" on a left join would silently drop the 3 primary tumors that have no slide.
    _, res = run([PRIMARY, {"op": "join", "table": "slides", "on": "sample_id", "how": "left"}])
    w = next(w for w in res[-1].warnings if w.kind == "inflation")
    assert [f["label"] for f in w.fixes] == ["Keep the joined columns, then collapse to one row per sample"]
    _, res2 = run(w.fixes[0]["steps"])
    assert res2[-1].rows == res2[-1].samples == 1101
    assert not unresolved_problems(res2)


def test_redacted_survival_records_are_flagged_with_exclude_fix():
    steps = [PRIMARY, {"op": "join", "table": "survival", "on": "sample_id", "how": "semi",
                       "where": [{"column": "OS.time", "operator": "notnull"}]}]
    _, res = run(steps)
    w = next(w for w in res[-1].warnings if w.kind == "redacted")
    assert w.severity == "info" and "5 samples" in w.message
    _, res2 = run(w.fixes[0]["steps"])
    assert res2[-1].samples == res[-1].samples - 5
    assert not any(w.kind == "redacted" for r in res2 for w in r.warnings)


def test_join_where_reports_missing_values():
    steps = [PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi",
                       "where": [{"column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type",
                                  "operator": "ne", "values": ["Positive"]}]}]
    _, res = run(steps)
    warnings = [w for w in res[-1].warnings if w.kind == "missing_values"]
    assert len(warnings) == 1
    assert "lab_procedure_her2_neu_in_situ_hybrid_outcome_type" in warnings[0].message
    assert warnings[0].examples


def test_unknown_coded_values_do_not_match_not_equal():
    steps = [PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi",
                       "where": [{"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status",
                                  "operator": "ne", "values": ["Positive"]}]}]
    _, res = run(steps)
    warning = next(w for w in res[-1].warnings if w.kind == "missing_values")
    assert "missing" in warning.message
    assert res[-1].samples < 1101


def test_bracketed_codes_are_unknown_for_not_equal():
    df = pd.DataFrame({"status": ["Positive", "Negative", "Indeterminate", "[Discrepancy]", None]})
    mask = _mask(df, {"column": "status", "operator": "ne", "values": ["Positive"]}, "test")
    assert mask.tolist() == [False, True, False, False, False]


def test_mutation_anti_join_warns_about_unsequenced_samples_and_offers_fix():
    steps = [PRIMARY, {"op": "join", "table": "mutation", "on": "sample_id", "how": "anti",
                       "where": [{"column": "gene", "operator": "eq", "values": ["TP53"]}]}]
    _, res = run(steps)
    warning = next(w for w in res[-1].warnings if w.kind == "unsequenced_mutation")
    assert "310" in warning.message
    fix_steps = warning.fixes[0]["steps"]
    _, fixed = run(fix_steps)
    assert fixed[-1].samples == 527
    assert not any(w.kind == "unsequenced_mutation" for r in fixed for w in r.warnings)
