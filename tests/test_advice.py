"""Which fix gets the star (docs/GAPS.md #21).

The rule that matters: on a patient-level join, the cross-sample fix wins. Removing the
duplicate rows isn't enough when the records belong to another sample of the same patient.
"""
import json
from pathlib import Path

from cohort_studio import advice, engine

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))["steps"]


def recommended(steps):
    """[(step index, the fix label the UI stars)] over a whole run."""
    _, results = engine.run(steps)
    out = []
    for r in results:
        advised = advice.advise(r, steps)
        for (w_i, f_i), (best, why) in advised.items():
            if best:
                assert why, "a starred fix must say why"
                out.append((r.index, r.warnings[w_i].fixes[f_i]["label"]))
    return out


def test_inner_join_inflation_recommends_the_semi_join():
    steps = example("demo_diagnostic_slides")
    assert recommended(steps) == [(4, "Keep each sample once if it has a match (semi-join)")]


def test_patient_level_join_recommends_matching_on_sample_id():
    """The trap: three fixes offered, and only this one removes the wrong records."""
    steps = example("trap_patient_level_survival")
    assert recommended(steps) == [(4, "Join on sample_id instead of patient_id")]


def test_the_other_fixes_on_the_trap_are_marked_as_insufficient():
    steps = example("trap_patient_level_survival")
    _, results = engine.run(steps)
    final = [r for r in results if r.index == 4][0]
    advised = advice.advise(final, steps)
    notes = [why for (w_i, f_i), (best, why) in advised.items() if not best]
    assert notes, "the inflation fixes should carry a caveat"
    assert all("different sample" in n for n in notes)


def test_left_join_inflation_recommends_collapsing():
    steps = [{"op": "filter", "where": [{"column": "sample_type", "operator": "in",
                                         "values": ["Primary Tumor"]}]},
             {"op": "join", "table": "slides", "on": "sample_id", "how": "left"}]
    assert recommended(steps) == [(2, "Keep the joined columns, then collapse to one row per sample")]


def test_judgement_calls_get_no_star():
    """Redacted records and multi-sample patients are the user's call, not ours."""
    steps = [{"op": "filter", "where": [{"column": "sample_type", "operator": "in",
                                         "values": ["Primary Tumor"]}]},
             {"op": "join", "table": "survival", "on": "sample_id", "how": "semi"}]
    _, results = engine.run(steps)
    kinds = {w.kind for r in results for w in r.warnings}
    assert "redacted" in kinds, "this cohort should still hit the redaction note"
    assert recommended(steps) == []


def test_an_engine_recommendation_wins_over_these_rules():
    """When B marks a fix in engine.py, the UI follows that instead (no code change here)."""
    steps = example("demo_diagnostic_slides")
    _, results = engine.run(steps)
    r = [x for x in results if x.index == 4][0]
    w = r.warnings[0]
    w.fixes[-1]["recommended"] = True            # the collapse fix, not the semi-join
    w.fixes[-1]["why"] = "the engine said so"
    advised = advice.advise(r, steps)
    assert advised[(0, len(w.fixes) - 1)] == (True, "the engine said so")
    assert advice.order(0, w.fixes, advised)[0] == len(w.fixes) - 1
