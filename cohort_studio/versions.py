"""Remember the cohorts built in this session, and say what changed between two of them.

(docs/GAPS.md #26, and "save and compare cohort versions" in the brief.)

Why it matters for the traps we chase: fixing an inflating join usually keeps *exactly the
same samples* and only removes duplicate rows. A count alone can't show that; a comparison
can ("same 731 samples, 45 duplicate rows gone"). When a fix does change who is in the
cohort — a semi-join fix on a left join, say — the sample IDs that moved are listed.

Versions live in `st.session_state` for this browser session only: nothing is written to disk.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from . import engine

MAX_VERSIONS = 10


def _label(n: int, steps: list[dict], samples: int, rows: int) -> str:
    try:
        what = engine.describe(steps[-1]) if steps else "all samples (no steps)"
    except Exception:
        what = "unfinished step"
    extra = f", {rows - samples:,} duplicate rows" if rows > samples else ""
    return f"v{n} · {samples:,} samples{extra} · {what}"


def record(steps: list[dict], df: pd.DataFrame) -> list[dict]:
    """Remember this cohort if the steps changed. Returns every version, newest first."""
    ss = st.session_state
    history: list[dict] = ss.get("versions", [])
    key = json.dumps(steps, sort_keys=True)
    if history and history[0]["key"] == key:
        return history

    samples = sorted(df["sample_id"].astype(str).unique())
    n = ss.get("version_counter", 0) + 1
    ss.version_counter = n
    version = {"key": key, "n": n, "steps": steps, "samples": samples,
               "rows": len(df), "patients": df["patient_id"].nunique(),
               "label": _label(n, steps, len(samples), len(df))}
    # An earlier identical cohort is dropped, so the list reads as the distinct cohorts tried.
    history = [version] + [h for h in history if h["key"] != key]
    ss.versions = history[:MAX_VERSIONS]
    return ss.versions


def compare(current: dict, earlier: dict) -> dict:
    """What changed from `earlier` to `current`."""
    now, before = set(current["samples"]), set(earlier["samples"])
    added, removed = sorted(now - before), sorted(before - now)
    return {
        "added": added,
        "removed": removed,
        "kept": len(now & before),
        "same_samples": not added and not removed,
        "rows": (earlier["rows"], current["rows"]),
        "samples": (len(before), len(now)),
        "patients": (earlier["patients"], current["patients"]),
    }


def summary(diff: dict) -> str:
    """One plain sentence a non-coder can read out loud."""
    (rows_before, rows_now), (s_before, s_now) = diff["rows"], diff["samples"]
    if diff["same_samples"]:
        if rows_before == rows_now:
            return "Identical: the same samples and the same number of rows."
        gone = rows_before - rows_now
        if gone > 0:
            return (f"**Exactly the same {s_now:,} samples.** The table went from {rows_before:,} rows to "
                    f"{rows_now:,}: {gone:,} duplicate rows are gone, so each sample is now counted once.")
        return (f"**Exactly the same {s_now:,} samples**, but the table grew from {rows_before:,} rows to "
                f"{rows_now:,}: {rows_now - rows_before:,} rows now repeat a sample.")
    parts = []
    if diff["added"]:
        parts.append(f"{len(diff['added']):,} samples came in")
    if diff["removed"]:
        parts.append(f"{len(diff['removed']):,} samples dropped out")
    return (f"**Different cohorts:** {' and '.join(parts)} ({s_before:,} → {s_now:,} samples). "
            f"{diff['kept']:,} samples are in both.")


def diff_table(diff: dict) -> pd.DataFrame:
    """The samples that moved, for the screen and for download."""
    return pd.DataFrame([{"sample_id": s, "change": "only in the current cohort"} for s in diff["added"]] +
                        [{"sample_id": s, "change": "only in the earlier version"} for s in diff["removed"]])
