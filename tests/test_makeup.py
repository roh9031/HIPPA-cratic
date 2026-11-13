"""Makeup-shift check (docs/GAPS.md #20, #27): did a step change who is in the cohort?"""
import json
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from cohort_studio.makeup import SHIFT_TVD, describe_shift, makeup_shifts
from cohort_studio.sqlcheck import connect

DEMO = json.loads((Path(__file__).resolve().parents[1] / "examples" / "demo_diagnostic_slides.json")
                  .read_text(encoding="utf-8"))["steps"]
PRIMARY = {"op": "filter", "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]}


def _shift(entry, name):
    return next(s for s in entry["shifts"] if s["attribute"] == name)


def test_protein_step_shifts_site_and_pam50():
    # Demo step 3 (has protein): 1,097 -> 742. Another team reported a site TVD of 0.14 for this step.
    step3 = next(e for e in makeup_shifts(DEMO) if e["step"] == 3)
    assert (step3["before"], step3["after"], step3["removed"]) == (1097, 742, 355)
    assert 0.13 <= _shift(step3, "site")["tvd"] <= 0.15
    assert {s["attribute"] for s in step3["flagged"]} == {"site", "PAM50 subtype"}
    assert "site" in describe_shift(step3) and "TVD 0.14" in describe_shift(step3)


def test_site_tvd_matches_plain_sql():
    # Same number computed directly in SQL, without makeup.py's pandas code.
    con = connect()
    try:
        tvd = con.sql("""
            WITH b AS (SELECT substr(sample_id, 6, 2) site FROM samples WHERE sample_type='Primary Tumor' AND has_rna),
                 a AS (SELECT substr(sample_id, 6, 2) site FROM samples WHERE sample_type='Primary Tumor' AND has_rna AND has_protein),
                 p AS (SELECT site, count(*) / (SELECT count(*) FROM b) sh FROM b GROUP BY site),
                 q AS (SELECT site, count(*) / (SELECT count(*) FROM a) sh FROM a GROUP BY site)
            SELECT 0.5 * sum(abs(coalesce(p.sh, 0) - coalesce(q.sh, 0))) FROM p FULL JOIN q USING (site)""").fetchall()[0][0]
    finally:
        con.close()
    step3 = next(e for e in makeup_shifts(DEMO) if e["step"] == 3)
    assert abs(_shift(step3, "site")["tvd"] - tvd) < 0.001


def test_filtering_on_an_attribute_is_expected_not_flagged():
    er = [PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi",
                    "where": [{"column": "breast_carcinoma_estrogen_receptor_status", "operator": "eq",
                               "values": ["Positive"]}]}]
    step2 = next(e for e in makeup_shifts(er) if e["step"] == 2)
    er_shift = _shift(step2, "ER status")
    assert er_shift["tvd"] >= SHIFT_TVD and er_shift["expected"]
    assert er_shift not in step2["flagged"]


def test_small_steps_are_not_compared_and_unchanged_steps_skipped():
    tiny = [PRIMARY, {"op": "join", "table": "survival", "on": "sample_id", "how": "anti"}]   # 4 samples left
    res = makeup_shifts(tiny + [{"op": "collapse", "level": "sample"}])
    assert [e["step"] for e in res] == [1, 2]            # the collapse changed nothing, so it's skipped
    assert res[1]["shifts"] == [] and "Too few samples" in describe_shift(res[1])


def test_works_with_or_groups():
    her2 = [PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi", "where": [{"any": [
        {"column": "lab_proc_her2_neu_immunohistochemistry_receptor_status", "operator": "eq", "values": ["Positive"]},
        {"column": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type", "operator": "eq", "values": ["Positive"]}]}]}]
    step2 = next(e for e in makeup_shifts(her2) if e["step"] == 2)
    assert step2["after"] == 197
