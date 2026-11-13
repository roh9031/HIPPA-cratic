"""Comparing two versions of a cohort (docs/GAPS.md #26).

The case that matters most: fixing an inflating join keeps exactly the same samples and only
removes duplicate rows. The comparison has to say that in words, because the sample count
alone doesn't change at all.
"""
import json
from pathlib import Path

import pandas as pd

from cohort_studio import engine, versions

ROOT = Path(__file__).resolve().parents[1]


def cohort(steps):
    """A version dict, built the way versions.record() builds one (without session state)."""
    df, _ = engine.run(steps)
    samples = sorted(df["sample_id"].astype(str).unique())
    return {"key": json.dumps(steps, sort_keys=True), "n": 1, "steps": steps, "samples": samples,
            "rows": len(df), "patients": df["patient_id"].nunique(),
            "label": versions._label(1, steps, len(samples), len(df))}


def demo_steps():
    return json.loads((ROOT / "examples" / "demo_diagnostic_slides.json").read_text(encoding="utf-8"))["steps"]


def test_fixing_inflation_keeps_the_same_samples_and_says_so():
    careless = cohort(demo_steps())
    fixed_steps = demo_steps()
    fixed_steps[-1]["how"] = "semi"
    fixed = cohort(fixed_steps)

    d = versions.compare(fixed, careless)
    assert d["same_samples"] and not d["added"] and not d["removed"]
    assert d["rows"] == (776, 731) and d["samples"] == (731, 731)
    text = versions.summary(d)
    assert "same 731 samples" in text.lower()
    assert "45 duplicate rows" in text
    assert versions.diff_table(d).empty


def test_a_fix_that_changes_who_is_in_the_cohort_lists_the_samples():
    """A left join collapsed vs semi-joined: the semi version drops samples with no slide."""
    base = [{"op": "filter", "where": [{"column": "sample_type", "operator": "in",
                                        "values": ["Primary Tumor"]}]}]
    kept = cohort(base + [{"op": "join", "table": "slides", "on": "sample_id", "how": "left"},
                          {"op": "collapse", "level": "sample"}])
    dropped = cohort(base + [{"op": "join", "table": "slides", "on": "sample_id", "how": "semi"}])

    d = versions.compare(dropped, kept)
    assert not d["same_samples"]
    assert d["removed"] and not d["added"]
    assert len(d["removed"]) == kept["rows"] - dropped["rows"]
    assert "dropped out" in versions.summary(d)
    moved = versions.diff_table(d)
    assert len(moved) == len(d["removed"])
    assert set(moved["change"]) == {"only in the earlier version"}


def test_identical_cohorts_are_called_identical():
    one = cohort(demo_steps())
    assert versions.summary(versions.compare(one, cohort(demo_steps()))) == (
        "Identical: the same samples and the same number of rows.")


def test_label_names_the_last_step_and_flags_duplicates():
    label = cohort(demo_steps())["label"]
    assert "731 samples" in label and "45 duplicate rows" in label
    assert "Join slides on sample_id" in label


def test_diff_table_is_downloadable_csv():
    a = cohort([{"op": "filter", "where": [{"column": "sample_type", "operator": "in",
                                            "values": ["Primary Tumor"]}]}])
    b = cohort([{"op": "filter", "where": [{"column": "sample_type", "operator": "in",
                                            "values": ["Solid Tissue Normal"]}]}])
    moved = versions.diff_table(versions.compare(a, b))
    assert isinstance(moved, pd.DataFrame)
    assert set(moved.columns) == {"sample_id", "change"}
    assert len(moved) == 1101 + 139
