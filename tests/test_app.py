"""The Streamlit app itself: the builder produces the same cohort the engine tests pin.

These run the real script in-process with AppTest (no browser, no server), so a broken
widget or a broken round-trip between the builder and the JSON view fails `pytest -q`.
"""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from cohort_studio.builder import HOW_LABELS

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _in_repo_root(monkeypatch):
    """app.py reads examples/ relative to the working directory."""
    monkeypatch.chdir(ROOT)


def run_app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception, at.exception
    return at


def counts(at):
    """Section 4's three metrics. The compare panel repeats Samples/Patients lower down, so
    only the first of each label counts."""
    out = {}
    for m in at.metric:
        if m.label in ("Samples", "Patients", "Rows in table"):
            out.setdefault(m.label, m.value)
    return out


def has_widget(at, key):
    try:
        at.selectbox(key=key)
        return True
    except KeyError:
        return False


def test_demo_example_loads_and_flags_the_inflating_join():
    at = run_app()
    assert counts(at) == {"Samples": "731", "Patients": "731", "Rows in table": "776"}
    assert any("Rows grew faster than samples" in e.value for e in at.error)
    assert any("duplicate sample rows" in e.value for e in at.error)


def test_apply_fix_button_rewrites_the_steps_and_clears_the_problem():
    at = run_app()
    at.button(key="fix-4-0-0").click().run()          # "keep each sample once (semi-join)"
    assert counts(at) == {"Samples": "731", "Patients": "731", "Rows in table": "731"}
    assert any("No unresolved problems" in s.value for s in at.success)
    assert json.loads(at.session_state.steps_text)[-1]["how"] == "semi"


def test_builder_dropdown_changes_the_cohort():
    """The same fix, made the way a non-coder makes it: pick another option in the join."""
    at = run_app()
    join_uid = at.session_state.b_uids[-1]
    at.selectbox(key=f"b_w_{join_uid}_how").set_value(HOW_LABELS["semi"]).run()
    assert counts(at)["Rows in table"] == "731"
    assert json.loads(at.session_state.steps_text)[-1]["how"] == "semi"


def test_removing_a_step_keeps_the_other_steps_intact():
    at = run_app()
    protein_uid = at.session_state.b_uids[2]          # filter: has_protein
    at.button(key=f"b_w_{protein_uid}_del").click().run()
    steps = json.loads(at.session_state.steps_text)
    assert [s["op"] for s in steps] == ["filter", "filter", "join"]
    assert steps[1]["where"][0]["column"] == "has_rna"


def test_json_view_round_trips_into_the_builder():
    at = run_app()
    at.text_area(key="steps_text").set_value(
        '[{"op": "filter", "where": [{"column": "sample_type", "operator": "in", '
        '"values": ["Solid Tissue Normal"]}]}]').run()
    assert not at.exception
    assert len(at.session_state.b_uids) == 1
    assert counts(at)["Samples"] == "139"


def test_her2_example_preserves_or_group():
    at = run_app()
    next(b for b in at.button if b.label == "her2 positive").click().run()
    assert counts(at)["Samples"] == "197"
    steps = json.loads(at.session_state.steps_text)
    assert steps[1]["where"][0]["any"]


def test_an_or_group_loads_as_editable_rows():
    """The HER2 group is two dropdown rows joined by "or", not a read-only blob (#16, #30)."""
    at = run_app()
    next(b for b in at.button if b.label == "her2 positive").click().run()
    uid = at.session_state.b_uids[1]
    first, second = at.session_state.b_conds[uid]
    assert at.segmented_control(key=f"b_w_{uid}_{second}_join").value == "or"
    assert not has_widget(at, f"b_w_{uid}_{first}_join")       # nothing to join the first row to
    assert "her2" in at.selectbox(key=f"b_w_{uid}_{second}_col").value


def test_switching_a_connector_to_or_widens_the_cohort():
    """Two conditions that no sample can satisfy at once: "and" gives 0, "or" gives both groups."""
    at = run_app()
    steps = [{"op": "filter", "where": [
        {"column": "sample_type", "operator": "eq", "values": ["Primary Tumor"]},
        {"column": "sample_type", "operator": "eq", "values": ["Metastatic"]}]}]
    at.text_area(key="steps_text").set_value(json.dumps(steps)).run()
    assert counts(at)["Samples"] == "0"

    uid = at.session_state.b_uids[0]
    second = at.session_state.b_conds[uid][1]
    at.segmented_control(key=f"b_w_{uid}_{second}_join").set_value("or").run()
    assert not at.exception
    assert counts(at)["Samples"] == "1,108"
    assert json.loads(at.session_state.steps_text)[0]["where"] == [{"any": steps[0]["where"]}]


def test_json_view_preserves_patient_level_opt_in():
    at = run_app()
    steps = [
        {"op": "filter", "where": [{"column": "sample_type", "operator": "eq",
                                    "values": ["Primary Tumor"]}]},
        {"op": "join", "table": "samples", "on": "patient_id", "how": "semi",
         "allow_cross_sample": True,
         "where": [{"column": "sample_type", "operator": "eq",
                     "values": ["Solid Tissue Normal"]}]},
    ]
    at.text_area(key="steps_text").set_value(json.dumps(steps)).run()
    assert not at.exception
    assert json.loads(at.session_state.steps_text)[1]["allow_cross_sample"] is True


def test_invalid_json_is_reported_and_leaves_the_cohort_alone():
    at = run_app()
    at.text_area(key="steps_text").set_value("[{not json").run()
    assert not at.exception
    assert any("isn't valid JSON" in e.value for e in at.error)
    assert counts(at)["Rows in table"] == "776"


def test_unfinished_step_is_left_out_instead_of_breaking_the_funnel():
    """Clearing a filter's values must not take the whole funnel down with it."""
    at = run_app()
    uid = at.session_state.b_uids[1]                  # filter: has_rna
    cuid = at.session_state.b_conds[uid][0]
    at.multiselect(key=f"b_w_{uid}_{cuid}_vals").set_value([]).run()
    assert not at.exception
    assert [s["op"] for s in json.loads(at.session_state.steps_text)] == ["filter", "filter", "join"]
    assert any("Not applied yet" in m.value for m in at.markdown)
    assert not any("can't run" in e.value or "failed" in e.value for e in at.error)
    assert at.metric  # the funnel still ran


def test_the_starred_fix_is_shown_first_and_resolves_the_trap():
    """The patient-level survival trap: three fixes, and the starred one is the real fix."""
    at = run_app()
    trap = json.loads((ROOT / "examples" / "trap_patient_level_survival.json")
                      .read_text(encoding="utf-8"))["steps"]
    at.text_area(key="steps_text").set_value(json.dumps(trap)).run()
    assert any("Recommended." in c.value for c in at.caption)
    star = [b for b in at.button if "sample_id instead of patient_id" in b.label]
    assert len(star) == 1
    star[0].click().run()
    assert not at.exception
    assert any("No unresolved problems" in s.value for s in at.success)
    assert json.loads(at.session_state.steps_text)[-1]["on"] == "sample_id"


def test_comparing_with_the_previous_version_shows_what_the_fix_changed():
    at = run_app()                                     # v1: the inflated demo cohort
    assert not has_widget(at, "compare_with"), "nothing to compare on the first version"
    at.button(key="fix-4-0-0").click().run()           # v2: the semi-join fix
    assert not at.exception
    assert any("Exactly the same 731 samples" in m.value and "45 duplicate rows" in m.value
               for m in at.markdown)
    assert has_widget(at, "compare_with")


def test_the_compared_version_can_become_the_current_one_without_breaking():
    """Toggling a fix back makes the selected version the current cohort: the widget must cope."""
    at = run_app()
    at.button(key="fix-4-0-0").click().run()
    join_uid = at.session_state.b_uids[-1]
    at.selectbox(key=f"b_w_{join_uid}_how").set_value(HOW_LABELS["inner"]).run()
    assert not at.exception
    assert any("45 rows now repeat a sample" in m.value for m in at.markdown)
