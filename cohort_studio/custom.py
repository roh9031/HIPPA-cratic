"""Bring your own data: run Cohort Studio on a researcher's own tables instead of TCGA-BRCA.

Tables come from uploaded CSV files or from a Supabase project (its standard REST API, with the
researcher's own project URL and key; nothing is saved). The researcher says which table is the sample list
and which columns hold the sample and patient IDs. The tables are written to a session folder laid out like
a data folder (sample_manifest.csv + one CSV per table) and registered in `data.TABLES`, so the unchanged
engine, builder, fixes, exports and Verify with SQL all work on them. The TCGA-only extras (makeup check, Data
notes, gene hints, the AI prompt) are switched off for custom data.
"""
from __future__ import annotations

import copy
import os
import re
import tempfile
from pathlib import Path

import pandas as pd

from . import data

TCGA_TABLES = copy.deepcopy(data.TABLES)      # restored by `deactivate()`
CUSTOM_MARK = data.CUSTOM_MARK                # a file in the folder that marks it as a custom dataset
_NAME = re.compile(r"[^A-Za-z0-9_]+")


def table_name(raw: str) -> str:
    """A safe table name from a file or Supabase table name: letters, digits and _ only, not starting with a digit."""
    name = _NAME.sub("_", Path(str(raw)).stem).strip("_").lower() or "table"
    return name if not name[0].isdigit() else f"t_{name}"


# ---------------------------------------------------------------- sources

def read_uploads(files) -> dict[str, pd.DataFrame]:
    """Streamlit UploadedFile objects (or paths) -> {table name: DataFrame}. All values are read as text."""
    out = {}
    for f in files:
        name = table_name(getattr(f, "name", f))
        out[name] = pd.read_csv(f, dtype=str, keep_default_na=True)
    return out


def fetch_supabase(url: str, key: str, tables: list[str], page: int = 1000) -> dict[str, pd.DataFrame]:
    """Read whole tables through Supabase's REST API (PostgREST): GET {url}/rest/v1/{table}?select=*.

    `key` is the project's anon or service key. With the anon key, each table needs Row Level Security off or
    a policy that allows reading. Rows are fetched in pages of `page` using the Range header."""
    import requests

    url = url.strip().rstrip("/")
    if not re.match(r"^https://[A-Za-z0-9.-]+$", url):
        raise ValueError("The Supabase URL should look like https://<project>.supabase.co")
    key = (key or "").strip().strip("\"'")
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items"}
    out = {}
    for t in [t.strip() for t in tables if t.strip()]:
        rows, start = [], 0
        while True:
            try:
                r = requests.get(f"{url}/rest/v1/{t}", params={"select": "*"}, timeout=60,
                                 headers={**headers, "Range": f"{start}-{start + page - 1}"})
            except requests.RequestException as e:
                raise RuntimeError(f"Couldn't reach Supabase at {url}: {e}") from None
            if r.status_code in (401, 403):
                raise RuntimeError("Supabase rejected the key. Use the project's anon (or service) key from "
                                   "Project Settings → API.")
            if r.status_code == 404:
                raise RuntimeError(f"Supabase has no table `{t}` it will share (check the name, and that the "
                                   "table is in the public schema).")
            if r.status_code >= 400:
                raise RuntimeError(f"Supabase error {r.status_code} for `{t}`: {r.text[:200]}")
            batch = r.json()
            rows.extend(batch)
            if len(batch) < page:
                break
            start += page
        if not rows:
            raise RuntimeError(f"`{t}` came back empty. If the table has rows, Row Level Security is probably "
                               "blocking the anon key: add a read policy or turn RLS off for this table.")
        out[table_name(t)] = pd.DataFrame(rows).astype("string").astype(object).where(lambda d: d.notna(), None)
    return out


# ---------------------------------------------------------------- mapping and activation

def guess_key(df: pd.DataFrame, kind: str) -> str | None:
    """A likely sample or patient ID column, by name."""
    words = {"sample": ("sample_id", "sampleid", "sample", "specimen_id", "specimen", "barcode"),
             "patient": ("patient_id", "patientid", "patient", "subject_id", "subject", "participant_id",
                         "participant", "person_id", "case_id")}[kind]
    lower = {c.lower(): c for c in df.columns}
    return next((lower[w] for w in words if w in lower), None)


def build(tables: dict[str, pd.DataFrame], base: str, keys: dict[str, tuple[str | None, str | None]],
          folder: str | Path | None = None) -> Path:
    """Write a data folder for these tables and return it.

    `keys[name] = (sample column, patient column)`. The sample list (`base`) needs a sample column with unique
    values; its patient column may be None (then each sample is its own patient). Other tables need a sample
    column or a patient column; a missing patient column is filled in from the sample list."""
    if base not in tables:
        raise ValueError("Choose which table is the sample list.")
    s_col, p_col = keys.get(base, (None, None))
    b = tables[base].copy()
    if not s_col or s_col not in b.columns:
        raise ValueError(f"Choose the sample ID column of `{base}`.")
    b = b.rename(columns={s_col: "sample_id"})
    if p_col and p_col in tables[base].columns and p_col != s_col:
        b = b.rename(columns={p_col: "patient_id"})
    else:
        b["patient_id"] = b["sample_id"]
    b = b[b["sample_id"].notna() & (b["sample_id"].astype(str).str.strip() != "")]
    b["sample_id"] = b["sample_id"].astype(str).str.strip()
    b["patient_id"] = b["patient_id"].astype(str).str.strip()
    dup = b["sample_id"][b["sample_id"].duplicated()]
    if len(dup):
        raise ValueError(f"The sample list must have one row per sample, but `{s_col}` repeats "
                         f"(e.g. {dup.iloc[0]!r}). Pick another table or column.")
    b = b[["sample_id", "patient_id"] + [c for c in b.columns if c not in ("sample_id", "patient_id")]]
    patient_of = dict(zip(b["sample_id"], b["patient_id"]))

    folder = Path(folder or tempfile.mkdtemp(prefix="cohort_studio_byod_"))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / CUSTOM_MARK).write_text("custom dataset\n", encoding="utf-8")
    b.to_csv(folder / data.BASE_FILE, index=False)
    meta = {"samples": {"file": data.BASE_FILE, "grain": "sample",
                        "about": f"Your sample list ({base}), one row per sample."}}
    for name, df in tables.items():
        if name == base:
            continue
        s_col, p_col = keys.get(name, (None, None))
        t = df.copy()
        if s_col and s_col in t.columns:
            t = t.rename(columns={s_col: "sample_id"})
            t["sample_id"] = t["sample_id"].astype(str).str.strip()
        if p_col and p_col in df.columns and p_col != s_col:
            t = t.rename(columns={p_col: "patient_id"})
            t["patient_id"] = t["patient_id"].astype(str).str.strip()
        if "sample_id" not in t.columns and "patient_id" not in t.columns:
            raise ValueError(f"`{name}` needs a sample ID or a patient ID column to be joined.")
        if "sample_id" in t.columns and "patient_id" not in t.columns:
            t.insert(1, "patient_id", t["sample_id"].map(patient_of))
        if "sample_id" in t.columns:
            per = t["sample_id"].value_counts()
            grain = "sample" if per.max() <= 1 else f"{name} record (several per sample)"
            about = f"Your table {name}: {len(t):,} rows, " + (
                "one per sample." if grain == "sample" else f"up to {per.max()} per sample.")
        else:
            grain = "patient"
            about = f"Your table {name}: {len(t):,} rows, keyed by patient only (join it on patient_id)."
        cols = [c for c in ("sample_id", "patient_id") if c in t.columns]
        t = t[cols + [c for c in t.columns if c not in cols]]
        t.to_csv(folder / f"{name}.csv", index=False)
        meta[name] = {"file": f"{name}.csv", "grain": grain, "about": about}
    (folder / "tables.json").write_text(pd.Series(meta).to_json(), encoding="utf-8")
    return folder


def activate(folder: str | Path) -> None:
    """Use the custom data folder for everything from now on (this process)."""
    import json
    folder = Path(folder)
    meta = json.loads((folder / "tables.json").read_text(encoding="utf-8"))
    data.TABLES.clear()
    data.TABLES.update(meta)
    os.environ["ONCOSYS_DATA"] = str(folder)
    os.environ.pop("ONCOSYS_RELEASE", None)


def deactivate(original_data: str | None) -> None:
    """Back to TCGA-BRCA."""
    data.TABLES.clear()
    data.TABLES.update(copy.deepcopy(TCGA_TABLES))
    if original_data:
        os.environ["ONCOSYS_DATA"] = original_data
    else:
        os.environ.pop("ONCOSYS_DATA", None)


def is_active(ddir=None) -> bool:
    return data.is_custom(ddir)
