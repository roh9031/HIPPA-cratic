"""Cohort Studio engine: run a list of steps, count what survives each one,
and flag joins that inflate the cohort.

A cohort definition is plain JSON, a list of steps:

  {"op": "filter",   "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]}
  {"op": "join",     "table": "slides", "on": "sample_id", "how": "inner",
                     "where": [{"column": "slide_kind", "operator": "startswith", "values": ["diagnostic"]}]}
  {"op": "collapse", "level": "sample"}

Every run starts from sample_manifest.csv (one row per sample).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import pandas as pd

from . import data

OPS = ("filter", "join", "collapse")
OPERATORS = ("in", "not_in", "eq", "ne", "gt", "ge", "lt", "le", "notnull", "isnull", "startswith", "contains")
JOIN_HOW = ("inner", "left", "semi", "anti")
LEVELS = ("sample", "patient")


class StepError(ValueError):
    pass


@dataclass
class Warning_:
    kind: str              # inflation | cross_sample | missing_values | empty | multi_sample_patients | redacted
    severity: str          # "problem" (must fix or justify) | "info"
    message: str
    examples: list[dict] = field(default_factory=list)
    fixes: list[dict] = field(default_factory=list)   # {"label": str, "steps": [...]}


@dataclass
class StepResult:
    index: int
    step: dict
    label: str
    rows: int
    samples: int
    patients: int
    warnings: list[Warning_] = field(default_factory=list)
    error: str | None = None

    @property
    def extra_rows(self) -> int:
        return self.rows - self.samples


# ---------------------------------------------------------------- helpers

def clean_step(step: dict) -> dict:
    """Drop null fields (the LLM schema sends them) and normalise case."""
    s = {k: v for k, v in step.items() if v is not None}
    if "op" in s:
        s["op"] = str(s["op"]).lower()
    return s


def validate_steps(steps) -> list[str]:
    if not isinstance(steps, list):
        return ["The cohort definition must be a JSON list of steps."]
    errs = []
    for i, raw in enumerate(steps, 1):
        if not isinstance(raw, dict):
            errs.append(f"Step {i}: must be an object.")
            continue
        s = clean_step(raw)
        op = s.get("op")
        if op not in OPS:
            errs.append(f"Step {i}: op must be one of {OPS}, got {op!r}.")
            continue
        for c in s.get("where", []) or []:
            if c.get("operator") not in OPERATORS:
                errs.append(f"Step {i}: operator must be one of {OPERATORS}, got {c.get('operator')!r}.")
            if not c.get("column"):
                errs.append(f"Step {i}: every condition needs a column.")
        if op == "filter" and not s.get("where"):
            errs.append(f"Step {i}: a filter needs at least one condition in 'where'.")
        if op == "join":
            if s.get("table") not in data.TABLES:
                errs.append(f"Step {i}: table must be one of {tuple(data.TABLES)}, got {s.get('table')!r}.")
            if s.get("on", "sample_id") not in data.KEYS:
                errs.append(f"Step {i}: on must be one of {data.KEYS}.")
            if s.get("how", "inner") not in JOIN_HOW:
                errs.append(f"Step {i}: how must be one of {JOIN_HOW}.")
        if op == "collapse" and s.get("level", "sample") not in LEVELS:
            errs.append(f"Step {i}: level must be one of {LEVELS}.")
    return errs


def describe(step: dict) -> str:
    s = clean_step(step)
    conds = " AND ".join(_describe_cond(c) for c in s.get("where", []) or [])
    if s["op"] == "filter":
        return f"Filter: {conds}"
    if s["op"] == "join":
        how = s.get("how", "inner")
        verb = {"inner": "Join", "left": "Left-join", "semi": "Keep if it has", "anti": "Drop if it has"}[how]
        txt = f"{verb} {s['table']} on {s.get('on', 'sample_id')}"
        return txt + (f" where {conds}" if conds else "")
    if s["op"] == "collapse":
        return f"Collapse to one row per {s.get('level', 'sample')}"
    return str(s)


def _describe_cond(c: dict) -> str:
    op, vals = c["operator"], c.get("values") or []
    if op in ("notnull", "isnull"):
        return f"{c['column']} {'is present' if op == 'notnull' else 'is missing'}"
    sym = {"in": "in", "not_in": "not in", "eq": "=", "ne": "≠", "gt": ">", "ge": "≥", "lt": "<",
           "le": "≤", "startswith": "starts with", "contains": "contains"}[op]
    v = vals[0] if len(vals) == 1 and op not in ("in", "not_in") else vals
    return f"{c['column']} {sym} {v}"


def _mask(df: pd.DataFrame, cond: dict, where: str) -> pd.Series:
    col, op = cond["column"], cond["operator"]
    if col not in df.columns:
        close = [c for c in df.columns if col.lower() in c.lower()][:5]
        hint = f" Similar columns: {close}." if close else ""
        raise StepError(f"Column {col!r} doesn't exist in {where}.{hint}")
    s = df[col]
    vals = [str(v) for v in (cond.get("values") or [])]
    if op == "notnull":
        return s.notna()
    if op == "isnull":
        return s.isna()
    if not vals:
        raise StepError(f"Operator {op!r} on {col!r} needs at least one value.")
    if op in ("gt", "ge", "lt", "le"):
        num = pd.to_numeric(s, errors="coerce")
        try:
            x = float(vals[0])
        except ValueError:
            raise StepError(f"{op!r} on {col!r} needs a number, got {vals[0]!r}.")
        return {"gt": num > x, "ge": num >= x, "lt": num < x, "le": num <= x}[op].fillna(False)
    text = s.astype(str).str.strip().str.lower().where(s.notna(), None)
    lv = [v.strip().lower() for v in vals]
    if op in ("in", "eq"):
        m = text.isin(lv)
    elif op in ("not_in", "ne"):
        m = ~text.isin(lv) & s.notna()
    elif op == "startswith":
        m = text.fillna("").str.startswith(tuple(lv))
    elif op == "contains":
        m = text.fillna("").apply(lambda t: any(v in t for v in lv))
    return m.astype(bool)


def _apply_where(df, where_list, where_name):
    m = pd.Series(True, index=df.index)
    for c in where_list or []:
        m &= _mask(df, c, where_name)
    return m


def _prepare_right(df: pd.DataFrame, right: pd.DataFrame, table: str, on: str) -> pd.DataFrame:
    """Rename right-side columns that clash with the cohort, keeping the join key."""
    ren = {c: f"{c}__{table}" for c in right.columns if c != on and c in df.columns}
    return right.rename(columns=ren)


def _counts(df):
    return len(df), df["sample_id"].nunique(), df["patient_id"].nunique()


def _with_step(steps, i, **changes):
    new = copy.deepcopy(steps)
    new[i - 1] = {**clean_step(new[i - 1]), **changes}
    return new


def _insert_after(steps, i, step):
    new = copy.deepcopy(steps)
    new.insert(i, step)
    return new


# ---------------------------------------------------------------- run

def run(steps: list[dict], ddir: str | None = None):
    """Run steps. Returns (final_df, [StepResult, ...]); result 0 is the starting table."""
    df = data.load("samples", ddir)
    results = [StepResult(0, {"op": "start"}, "Start: all samples (sample_manifest.csv)", *_counts(df))]
    errs = validate_steps(steps)
    if errs:
        results[0].error = " ".join(errs)
        return df, results

    for i, raw in enumerate(steps, 1):
        step = clean_step(raw)
        before = df
        warns: list[Warning_] = []
        try:
            if step["op"] == "filter":
                df, warns = _filter(df, step)
            elif step["op"] == "join":
                df, warns = _join(df, step, i, steps, ddir)
            elif step["op"] == "collapse":
                key = f"{step.get('level', 'sample')}_id"
                df = df.drop_duplicates(subset=[key], keep="first")
        except (StepError, FileNotFoundError) as e:
            results.append(StepResult(i, step, describe(step), *_counts(before), error=str(e)))
            return before, results

        warns = _inflation_check(before, df, step, i, steps) + warns
        if len(df) == 0:
            warns.append(Warning_("empty", "problem", "No records survive this step. Check the values: matching is "
                                  "case-insensitive but must otherwise be exact (see the column's values)."))
        results.append(StepResult(i, step, describe(step), *_counts(df), warnings=warns))

    results[-1].warnings += _final_checks(df, steps)
    return df, results


def _filter(df, step):
    warns = []
    for c in step["where"]:
        if c["column"] in df.columns and c["operator"] not in ("isnull", "notnull"):
            missing = df[c["column"]].isna()
            if missing.any():
                n_s = df.loc[missing, "sample_id"].nunique()
                warns.append(Warning_(
                    "missing_values", "info",
                    f"{n_s} samples were dropped because `{c['column']}` is missing for them, not because "
                    f"they failed the condition. Decide whether that's acceptable.",
                    examples=df.loc[missing, ["sample_id", "patient_id"]].drop_duplicates().head(10).to_dict("records"),
                ))
    return df[_apply_where(df, step["where"], "the current cohort")], warns


def _join(df, step, i, steps, ddir):
    table, on, how = step["table"], step.get("on", "sample_id"), step.get("how", "inner")
    right = data.load(table, ddir)
    right = right[_apply_where(right, step.get("where"), f"table {table!r}")]
    warns = []
    if how != "anti":
        warns += _redaction_check(df, right, table, on, step, i, steps)

    if how in ("semi", "anti"):
        hit = df[on].isin(right[on])
        out = df[hit] if how == "semi" else df[~hit]
        if on == "patient_id" and how == "semi":
            by_sample = df["sample_id"].isin(right["sample_id"])
            only_via_patient = df[hit & ~by_sample]
            if len(only_via_patient):
                warns.append(Warning_(
                    "cross_sample", "problem",
                    f"{only_via_patient['sample_id'].nunique()} samples were kept only because a *different* "
                    f"sample of the same patient has a matching {table} record (e.g. a normal-tissue slide). "
                    f"Records should link to a sample only when the sample barcode matches.",
                    examples=only_via_patient[["sample_id", "patient_id"]].head(10).to_dict("records"),
                    fixes=[{"label": "Match on sample_id instead of patient_id",
                            "steps": _with_step(steps, i, on="sample_id")}],
                ))
        return out, warns

    right = _prepare_right(df, right, table, on)
    out = df.merge(right, on=on, how=how)
    if on == "patient_id":
        other = f"sample_id__{table}"
        if other in out.columns:
            bad = out[out[other].notna() & (out[other] != out["sample_id"])]
            if len(bad):
                warns.append(Warning_(
                    "cross_sample", "problem",
                    f"{len(bad)} joined rows attach a {table} record from a *different sample* of the same "
                    f"patient (for example a normal-tissue record on a tumor sample). "
                    f"Join on sample_id so each record belongs to the sample it describes.",
                    examples=bad[["sample_id", other]].head(10).to_dict("records"),
                    fixes=[{"label": "Join on sample_id instead of patient_id",
                            "steps": _with_step(steps, i, on="sample_id")}],
                ))
    return out, warns


def _redaction_check(df, right, table, on, step, i, steps) -> list[Warning_]:
    """Some tables mark records as redacted but still carry values (survival.tsv: 6 rows). Say so."""
    if "Redaction" not in right.columns:
        return []
    red = right[right["Redaction"].notna() & right[on].isin(df[on])]
    if red.empty:
        return []
    hit = df[df[on].isin(red[on])]
    where = list(step.get("where") or []) + [{"column": "Redaction", "operator": "isnull"}]
    return [Warning_(
        "redacted", "info",
        f"{hit['sample_id'].nunique()} samples matched {table} records marked as redacted "
        f"({', '.join(sorted(red['Redaction'].astype(str).unique()))}). Their values are still filled in, so "
        f"they count as matches. Exclude them unless you know the redaction doesn't matter for your question.",
        examples=hit[["sample_id", "patient_id"]].drop_duplicates().head(10).to_dict("records"),
        fixes=[{"label": f"Exclude redacted {table} records", "steps": _with_step(steps, i, where=where)}],
    )]


def _inflation_check(before, after, step, i, steps) -> list[Warning_]:
    extra_before = len(before) - before["sample_id"].nunique()
    extra_after = len(after) - after["sample_id"].nunique()
    if extra_after <= extra_before:
        return []
    vc = after["sample_id"].value_counts()
    dup = vc[vc > 1]
    fixes = []
    if step["op"] == "join":
        # A semi-join only keeps samples that have a match. That's the same cohort as an inner join, but for a
        # left join it would silently drop samples with no match, so only offer it for inner joins.
        if step.get("how", "inner") == "inner":
            fixes.append({"label": "Keep each sample once if it has a match (semi-join)",
                          "steps": _with_step(steps, i, how="semi")})
        fixes.append({"label": "Keep the joined columns, then collapse to one row per sample",
                      "steps": _insert_after(steps, i, {"op": "collapse", "level": "sample"})})
    return [Warning_(
        "inflation", "problem",
        f"Rows grew faster than samples: {len(after):,} rows but only {after['sample_id'].nunique():,} distinct "
        f"samples. {len(dup):,} samples now appear more than once (up to {int(dup.max())}x), so counting rows "
        f"here overstates the cohort by {extra_after:,}.",
        examples=[{"sample_id": s, "rows": int(n)} for s, n in dup.head(10).items()],
        fixes=fixes,
    )]


def _final_checks(df, steps) -> list[Warning_]:
    warns = []
    vc = df.drop_duplicates("sample_id")["patient_id"].value_counts()
    multi = vc[vc > 1]
    if len(multi):
        warns.append(Warning_(
            "multi_sample_patients", "info",
            f"{len(multi)} patients contribute more than one sample to the final cohort. That's fine for a "
            f"sample-level analysis; if your analysis counts people, collapse to one row per patient.",
            examples=[{"patient_id": p, "samples": int(n)} for p, n in multi.head(10).items()],
            fixes=[{"label": "Collapse to one row per patient",
                    "steps": steps + [{"op": "collapse", "level": "patient"}]}],
        ))
    return warns


def unresolved_problems(results: list[StepResult]) -> list[str]:
    """Problems still visible in the final cohort (an inflation fixed by a later collapse doesn't count)."""
    out = []
    final = results[-1]
    if final.error or any(r.error for r in results):
        out.append("A step failed to run.")
    if final.rows != final.samples:
        out.append(f"The final table has {final.rows - final.samples:,} duplicate sample rows.")
    for r in results:
        for w in r.warnings:
            if w.kind == "cross_sample":
                out.append(f"Step {r.index}: records linked through a different sample of the same patient.")
    return out
