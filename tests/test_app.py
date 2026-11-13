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
    return {m.label: m.value for m in at.metric}


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
