"""The exported rebuild_cohort.py must reproduce the app's cohort_samples.csv exactly.

Runs the generated script as a separate process (as a colleague would), then compares its CSV with the engine's.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from cohort_studio.engine import run
from cohort_studio.export import cohort_samples, rebuild_script

ROOT = Path(__file__).resolve().parents[1]


def _fixed_demo():
    steps = json.loads((ROOT / "examples" / "demo_diagnostic_slides.json").read_text(encoding="utf-8"))["steps"]
    steps[-1]["how"] = "semi"
    return steps


def _fixed_survival_trap():
    steps = json.loads((ROOT / "examples" / "trap_patient_level_survival.json").read_text(encoding="utf-8"))["steps"]
    steps[-1]["on"] = "sample_id"
    return steps


@pytest.mark.parametrize("name,steps,n", [("demo", _fixed_demo(), 731), ("survival_trap", _fixed_survival_trap(), 807)])
def test_rebuild_script_reproduces_export(tmp_path, name, steps, n):
    df, _ = run(steps)
    expected = cohort_samples(df)

    script = tmp_path / "rebuild_cohort.py"
    script.write_text(rebuild_script(steps, f"test {name}"), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]

    rebuilt = pd.read_csv(tmp_path / "cohort_samples.csv")
    assert len(rebuilt) == n
    assert list(rebuilt["sample_id"]) == list(expected["sample_id"])
    assert rebuilt.equals(expected.reset_index(drop=True))
