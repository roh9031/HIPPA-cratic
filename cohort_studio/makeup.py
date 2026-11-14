"""Did a step change *who* is in the cohort? (docs/GAPS.md #20 and #27)

Counts say how many samples a step removed. They don't say whether the step removed them evenly. If
"has protein data" drops mostly one hospital's tumors, the cohort that's left is a different population, and
that's worth knowing before analysing it.

After every step that changes the sample set, this compares the mix of four attributes before and after:

  site      submitting site, from the barcode (TCGA-**A7**-....)
  PAM50     PAM50Call_RNAseq subtype (clinical.tsv)
  ER        breast_carcinoma_estrogen_receptor_status (clinical.tsv)
  age band  age_at_initial_pathologic_diagnosis, in decades (clinical.tsv)

The size of a shift is the total variation distance, TVD = ½ · Σ |share before − share after|: 0 means the same
mix, 1 means no overlap. A shift of SHIFT_TVD or more gets a note, unless the step filters on that attribute
itself (filtering on ER is *supposed* to change the ER mix).

Sample lists come from the same per-step DuckDB SQL as "Verify with SQL", and the attributes are read
straight from the raw files, so this doesn't depend on which columns the user joined in.
"""
from __future__ import annotations

import pandas as pd

from .sqlcheck import _columns_in, _ctes, connect

SHIFT_TVD = 0.10      # a shift this large gets a note
MIN_SAMPLES = 30      # below this, shares are too noisy to compare

ATTRIBUTES = {
    # name: (SQL expression over samples s LEFT JOIN clinical c, columns that make the shift "expected")
    "site": ("substr(s.sample_id, 6, 2)", {"sample_id", "patient_id"}),
    "PAM50 subtype": ("coalesce(c.PAM50Call_RNAseq, 'unknown')", {"PAM50Call_RNAseq", "PAM50_mRNA_nature2012"}),
    "ER status": ("CASE WHEN c.breast_carcinoma_estrogen_receptor_status IN ('Positive', 'Negative') "
                  "THEN c.breast_carcinoma_estrogen_receptor_status ELSE 'unknown' END",
                  {"breast_carcinoma_estrogen_receptor_status"}),
    "age band": ("coalesce(CAST(floor(TRY_CAST(c.age_at_initial_pathologic_diagnosis AS DOUBLE) / 10) * 10 "
                 "AS INTEGER) || 's', 'unknown')",
                 {"age_at_initial_pathologic_diagnosis", "Age_at_Initial_Pathologic_Diagnosis_nature2012"}),
}


def _tvd(before: pd.Series, after: pd.Series) -> float:
    p = before.value_counts(normalize=True)
    q = after.value_counts(normalize=True)
    return float(0.5 * p.subtract(q, fill_value=0).abs().sum())


def _biggest_moves(before: pd.Series, after: pd.Series, k: int = 2) -> list[tuple[str, float, float]]:
    p = before.value_counts(normalize=True)
    q = after.value_counts(normalize=True)
    diff = q.subtract(p, fill_value=0)
    top = diff.abs().sort_values(ascending=False).head(k).index
    return [(str(c), float(p.get(c, 0.0)), float(q.get(c, 0.0))) for c in top]


def _step_columns(step: dict) -> set[str]:
    return set(_columns_in(step.get("where")))


def makeup_shifts(steps: list[dict], ddir: str | None = None) -> list[dict]:
    """One entry per step that changed the sample set: what it removed and how much each attribute's mix moved.

    Each entry: step, before, after, removed, added, shifts=[{attribute, tvd, expected, moves}], flagged=[...].
    """
    con = connect(ddir)
    try:
        con.sql("SET threads TO 1")
        base = _ctes(steps, con)
        members = con.sql(base + "\n" + "\nUNION ALL ".join(
            f"SELECT DISTINCT {i} AS step, sample_id FROM s{i}" for i in range(len(steps) + 1))).df()
        attrs = con.sql("SELECT s.sample_id, " + ", ".join(f"{expr} AS \"{name}\"" for name, (expr, _) in ATTRIBUTES.items())
                        + " FROM samples s LEFT JOIN clinical c USING (sample_id)").df().set_index("sample_id")
    finally:
        con.close()

    by_step = {i: set(g["sample_id"]) for i, g in members.groupby("step")}
    out = []
    for i in range(1, len(steps) + 1):
        before, after = by_step.get(i - 1, set()), by_step.get(i, set())
        if before == after:
            continue
        entry = {"step": i, "before": len(before), "after": len(after),
                 "removed": len(before - after), "added": len(after - before), "shifts": [], "flagged": []}
        if len(before) >= MIN_SAMPLES and len(after) >= MIN_SAMPLES:
            cols = _step_columns(steps[i - 1])
            a_before, a_after = attrs.loc[sorted(before)], attrs.loc[sorted(after)]
            for name, (_, own_cols) in ATTRIBUTES.items():
                tvd = _tvd(a_before[name], a_after[name])
                shift = {"attribute": name, "tvd": round(tvd, 3), "expected": bool(cols & own_cols),
                         "moves": _biggest_moves(a_before[name], a_after[name])}
                entry["shifts"].append(shift)
                if tvd >= SHIFT_TVD and not shift["expected"]:
                    entry["flagged"].append(shift)
        out.append(entry)
    return out


def describe_shift(entry: dict) -> str:
    """Plain words for one step, e.g. 'Step 3 removed 355 samples (1,097 → 742) and shifted the site mix
    (TVD 0.14): A2 went from 3% to 9%, ...'."""
    head = f"Step {entry['step']} "
    if entry["removed"] and not entry["added"]:
        head += f"removed {entry['removed']:,} samples ({entry['before']:,} → {entry['after']:,})"
    else:
        head += f"changed the cohort from {entry['before']:,} to {entry['after']:,} samples"
    if not entry["shifts"]:
        return head + f". Too few samples to compare the mix (fewer than {MIN_SAMPLES})."
    if not entry["flagged"]:
        top = max(entry["shifts"], key=lambda s: s["tvd"] if not s["expected"] else -1)
        return head + f" without changing the mix much (largest shift: {top['attribute']}, TVD {top['tvd']:.2f})."
    parts = []
    for s in entry["flagged"]:
        label = "site " if s["attribute"] == "site" else ""
        moves = ", ".join(f"{label}{c} went from {p:.0%} to {q:.0%}" for c, p, q in s["moves"])
        parts.append(f"the {s['attribute']} mix (TVD {s['tvd']:.2f}): {moves}")
    return head + " and shifted " + "; and ".join(parts) + "."
