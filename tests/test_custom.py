"""Bring your own data (cohort_studio/custom.py): the unchanged engine, fixes and SQL check on the user's tables.
Uses the synthetic example in examples/byod_synthetic (made-up data)."""
import os
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")

from cohort_studio import custom, data
from cohort_studio.engine import run
from cohort_studio.sqlcheck import connect, trace, verify

EX = Path(__file__).resolve().parents[1] / "examples" / "byod_synthetic"
BIOPSY = {"op": "filter", "where": [{"column": "sample_type", "operator": "eq", "values": ["Biopsy"]}]}
BLOOD = {"op": "filter", "where": [{"column": "sample_type", "operator": "eq", "values": ["Blood"]}]}


@pytest.fixture
def byod(tmp_path, monkeypatch):
    original = os.environ.get("ONCOSYS_DATA")
    tables = custom.read_uploads([EX / "samples.csv", EX / "labs.csv", EX / "visits.csv"])
    keys = {name: (custom.guess_key(df, "sample"), custom.guess_key(df, "patient")) for name, df in tables.items()}
    folder = custom.build(tables, "samples", keys, tmp_path / "byod")
    monkeypatch.delenv("ONCOSYS_RELEASE", raising=False)
    custom.activate(folder)
    yield tables
    custom.deactivate(original)


def _sql(q):
    con = connect()
    try:
        return con.sql(q).fetchall()[0][0]
    finally:
        con.close()


def test_tables_registered_with_grain(byod):
    assert data.is_custom()
    assert set(data.TABLES) == {"samples", "labs", "visits"}
    assert data.TABLES["labs"]["grain"].startswith("labs record")
    assert data.TABLES["visits"]["grain"] == "patient"
    assert len(data.load("samples")) == len(byod["samples"])


def test_inflation_and_fix_on_user_data(byod):
    steps = [BLOOD, {"op": "join", "table": "labs", "on": "sample_id", "how": "inner"}]
    df, res = run(steps)
    want = _sql("SELECT count(DISTINCT sample_id) FROM labs WHERE sample_id IN "
                "(SELECT sample_id FROM samples WHERE sample_type = 'Blood')")
    assert res[-1].samples == want
    w = next(w for w in res[-1].warnings if w.kind == "inflation")
    fixed = w.fixes[0]["steps"]
    df2, res2 = run(fixed)
    assert res2[-1].rows == res2[-1].samples == want
    assert verify(fixed, df2, res2)["match"]


def test_cross_sample_link_on_user_data(byod):
    steps = [BIOPSY, {"op": "join", "table": "labs", "on": "patient_id", "how": "semi"}]
    df, res = run(steps)
    assert any(w.kind == "cross_sample" for w in res[-1].warnings)
    assert verify(steps, df, res)["match"]


def test_patient_level_table_joins_without_false_alarm(byod):
    steps = [BIOPSY, {"op": "join", "table": "visits", "on": "patient_id", "how": "semi",
                      "where": [{"column": "smoker", "operator": "eq", "values": ["yes"]}]}]
    df, res = run(steps)
    assert not any(w.kind == "cross_sample" for w in res[-1].warnings)
    want = _sql("SELECT count(*) FROM samples WHERE sample_type = 'Biopsy' AND patient_id IN "
                "(SELECT patient_id FROM visits WHERE smoker = 'yes')")
    assert res[-1].samples == want
    assert verify(steps, df, res)["match"]


def test_trace_and_collapse_on_user_data(byod):
    steps = [BIOPSY, {"op": "collapse", "level": "patient"}]
    df, res = run(steps)
    assert res[-1].samples == 60
    t = trace([BIOPSY], "SYN-P001-L")
    assert t["status"] in ("removed", "not_in_manifest") or t["status"] == "in_cohort"


def test_build_rejects_a_sample_list_with_repeats(tmp_path):
    labs = pd.read_csv(EX / "labs.csv", dtype=str)
    with pytest.raises(ValueError, match="one row per sample"):
        custom.build({"labs": labs}, "labs", {"labs": ("sample_id", None)}, tmp_path / "bad")


def test_back_to_tcga_after_custom(byod):
    original = os.environ.get("ONCOSYS_DATA")
    custom.deactivate(None if original and "byod" in original else original)
    assert not data.is_custom()
    assert "clinical" in data.TABLES and len(data.load("samples")) == 1247


def test_supabase_fetch_pages_and_errors(monkeypatch):
    calls = []

    class R:
        def __init__(self, code, body):
            self.status_code, self._body, self.text = code, body, str(body)

        def json(self):
            return self._body

    def fake_get(url, params, timeout, headers):
        calls.append((url, headers["Range"], headers["apikey"]))
        if url.endswith("/missing"):
            return R(404, {})
        start = int(headers["Range"].split("-")[0])
        rows = [{"sample_id": f"S{i}", "patient_id": f"P{i}"} for i in range(start, min(start + 2, 3))]
        return R(200, rows)

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    out = custom.fetch_supabase("https://abc.supabase.co/", '"key"', ["samples"], page=2)
    assert list(out["samples"]["sample_id"]) == ["S0", "S1", "S2"]
    assert calls[0][0] == "https://abc.supabase.co/rest/v1/samples" and calls[0][2] == "key"
    with pytest.raises(RuntimeError, match="no table"):
        custom.fetch_supabase("https://abc.supabase.co", "key", ["missing"])
    with pytest.raises(ValueError):
        custom.fetch_supabase("http://not-https.example", "key", ["samples"])
