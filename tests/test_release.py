"""A changed data release (the challenge's make_release.py format): a folder of changed raw files at its top
level, no manifests. The tool must read the changed files, take the rest from the original data, and the
independent SQL check must read the same changed files."""
import pandas as pd
import pytest

pytest.importorskip("duckdb")

from cohort_studio import data
from cohort_studio.engine import run
from cohort_studio.sqlcheck import connect, verify

PRIMARY = {"op": "filter", "where": [{"column": "sample_type", "operator": "eq", "values": ["Primary Tumor"]}]}
ER = "breast_carcinoma_estrogen_receptor_status"
SURVIVAL = [PRIMARY, {"op": "join", "table": "survival", "on": "sample_id", "how": "semi"}]
ER_POS = [PRIMARY, {"op": "join", "table": "clinical", "on": "sample_id", "how": "semi",
                    "where": [{"column": ER, "operator": "eq", "values": ["Positive"]}]}]


def _count(steps):
    df, res = run(steps)
    v = verify(steps, df, res)
    assert v["match"], v["by_step"]
    return res[-1].samples


@pytest.fixture
def release(tmp_path, monkeypatch):
    """Release: 10 primary tumors lose their survival record; 5 ER-positive primary tumors become Negative."""
    base = data.data_dir()
    primaries = set(pd.read_csv(base / "sample_manifest.csv").query("sample_type == 'Primary Tumor'")["sample_id"])
    surv = pd.read_csv(base / "raw/survival.tsv", sep="\t", dtype=str, keep_default_na=False)
    dropped = [s for s in surv["sample"] if s in primaries][:10]
    surv[~surv["sample"].isin(dropped)].to_csv(tmp_path / "survival.tsv", sep="\t", index=False)
    clin = pd.read_csv(base / "raw/clinical.tsv", sep="\t", dtype=str, keep_default_na=False)
    flip = clin.index[(clin[ER] == "Positive") & clin["sampleID"].isin(primaries)][:5]
    clin.loc[flip, ER] = "Negative"
    clin.to_csv(tmp_path / "clinical.tsv", sep="\t", index=False)
    before = (_count(SURVIVAL), _count(ER_POS))
    monkeypatch.setenv("ONCOSYS_RELEASE", str(tmp_path))
    return tmp_path, before


def test_release_files_change_the_cohort_and_sql_agrees(release):
    folder, (surv_before, er_before) = release
    assert data.release_dir() == folder.resolve()
    assert _count(SURVIVAL) == surv_before - 10
    assert _count(ER_POS) == er_before - 5


def test_release_status_and_fallback(release):
    folder, _ = release
    status = data.check_data(str(data.location()))
    assert status["raw/survival.tsv"] == "release" and status["raw/clinical.tsv"] == "release"
    assert status["sample_manifest.csv"] == "ok"                 # manifests come from the original data
    assert data.file_path("raw/mutation_gene_level.tsv.gz").parent.name == "raw"
    con = connect()
    try:
        assert con.sql("SELECT count(*) FROM samples").fetchall()[0][0] == 1247
    finally:
        con.close()


def test_no_release_by_default(monkeypatch):
    monkeypatch.delenv("ONCOSYS_RELEASE", raising=False)
    assert data.release_dir() is None
    assert (data.data_dir() / "sample_manifest.csv").exists()


def test_organizers_practice_release_if_built(monkeypatch):
    """data/tcga-brca/releases/practice-B, built by the challenge's make_release.py (not committed)."""
    if "practice-B" not in data.available_releases():
        pytest.skip("practice-B not built (python data/tcga-brca/make_release.py in the challenge repo)")
    monkeypatch.setenv("ONCOSYS_RELEASE", "practice-B")
    assert data.release_dir().name == "practice-B"
    demo = [PRIMARY,
            {"op": "filter", "where": [{"column": "has_rna", "operator": "eq", "values": ["True"]}]},
            {"op": "filter", "where": [{"column": "has_protein", "operator": "eq", "values": ["True"]}]},
            {"op": "join", "table": "slides", "on": "sample_id", "how": "semi",
             "where": [{"column": "slide_kind", "operator": "startswith", "values": ["diagnostic"]}]}]
    assert _count(demo) == 731     # practice-B only changes protein values, which the tool reads as has_protein
