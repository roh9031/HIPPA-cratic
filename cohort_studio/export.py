"""Turn a finished cohort into files someone else can check and rerun."""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from . import data

TOOL = "Cohort Studio"
VERSION = "0.1.0"


def cohort_samples(df: pd.DataFrame) -> pd.DataFrame:
    """One row per sample: what the organizers' checker reads."""
    return (df[["sample_id", "patient_id"]].drop_duplicates("sample_id")
            .sort_values("sample_id").reset_index(drop=True))


def cohort_definition(steps, request: str, results) -> dict:
    return {
        "tool": TOOL,
        "version": VERSION,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "request": request,
        "data_dir": str(data.data_dir()),
        "release": str(data.release_dir()) if data.release_dir() else None,   # changed raw files, if any
        "input_sha256": data.file_fingerprints(),
        "steps": steps,
        "funnel": [{"step": r.index, "label": r.label, "rows": r.rows, "samples": r.samples,
                    "patients": r.patients} for r in results],
    }


def rebuild_script(steps, request: str) -> str:
    steps_json = json.dumps(steps, indent=2)
    return f'''"""Rebuild a cohort exported by {TOOL} {VERSION}.

Request: {request or "(none given)"}

Save this file in the cohort-studio repo root and run:
    python rebuild_cohort.py
It writes cohort_samples.csv and prints the step-by-step funnel.
"""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cohort_studio.engine import run, unresolved_problems
from cohort_studio.export import cohort_samples

STEPS = json.loads(r"""
{steps_json}
""")

df, results = run(STEPS)
for r in results:
    print(f"{{r.index:>2}}  {{r.label:<70}} rows={{r.rows:>5}} samples={{r.samples:>5}} patients={{r.patients:>5}}")
    for w in r.warnings:
        print(f"      [{{w.severity}}] {{w.message}}")
for p in unresolved_problems(results):
    print("UNRESOLVED:", p)
out = cohort_samples(df)
out.to_csv("cohort_samples.csv", index=False)
print(f"wrote cohort_samples.csv ({{len(out)}} samples)")
'''
