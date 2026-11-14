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
    kind: str              # inflation | cross_sample | missing_values | empty | multi_sample_patients | redacted | unsequenced_mutation
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
            _validate_condition(c, i, errs)
        if op == "filter" and not s.get("where"):
            errs.append(f"Step {i}: a filter needs at least one condition in 'where'.")
        if op == "join":
            if s.get("table") not in data.TABLES:
                errs.append(f"Step {i}: table must be one of {tuple(data.TABLES)}, got {s.get('table')!r}.")
            if s.get("on", "sample_id") not in data.KEYS:
                errs.append(f"Step {i}: on must be one of {data.KEYS}.")
            if s.get("how", "inner") not in JOIN_HOW:
                errs.append(f"Step {i}: how must be one of {JOIN_HOW}.")
            if "allow_cross_sample" in s and not isinstance(s["allow_cross_sample"], bool):
                errs.append(f"Step {i}: allow_cross_sample must be true or false.")
            if s.get("allow_cross_sample"):
                if s.get("on", "sample_id") != "patient_id":
                    errs.append(f"Step {i}: allow_cross_sample requires on='patient_id'.")
                if s.get("how", "inner") not in ("semi", "anti"):
                    errs.append(f"Step {i}: allow_cross_sample requires a semi or anti join.")
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
    if "any" in c:
        return "(" + " OR ".join(_describe_cond(nested) for nested in c["any"]) + ")"
    if "all" in c:
        return "(" + " AND ".join(_describe_cond(nested) for nested in c["all"]) + ")"
    op, vals = c["operator"], c.get("values") or []
    if op in ("notnull", "isnull"):
        return f"{c['column']} {'is present' if op == 'notnull' else 'is missing'}"
    sym = {"in": "in", "not_in": "not in", "eq": "=", "ne": "≠", "gt": ">", "ge": "≥", "lt": "<",
           "le": "≤", "startswith": "starts with", "contains": "contains"}[op]
    v = vals[0] if len(vals) == 1 and op not in ("in", "not_in") else vals
    return f"{c['column']} {sym} {v}"


def _validate_condition(c: dict, step_index: int, errs: list[str]):
    group = "any" if "any" in c else "all" if "all" in c else None
    if group:
        if not isinstance(c[group], list) or not c[group]:
            errs.append(f"Step {step_index}: {group} must contain at least one condition.")
        for nested in c.get(group, []):
            if not isinstance(nested, dict):
                errs.append(f"Step {step_index}: every any condition must be an object.")
            else:
                _validate_condition(nested, step_index, errs)
        return
    if c.get("operator") not in OPERATORS:
        errs.append(f"Step {step_index}: operator must be one of {OPERATORS}, got {c.get('operator')!r}.")
    if not c.get("column"):
        errs.append(f"Step {step_index}: every condition needs a column.")


def _mask(df: pd.DataFrame, cond: dict, where: str) -> pd.Series:
    col, op = cond["column"], cond["operator"]
    if col not in df.columns:
        close = [c for c in df.columns if col.lower() in c.lower()][:5]
        hint = f" Similar columns: {close}." if close else ""
        raise StepError(f"Column {col!r} doesn't exist in {where}.{hint}")
    s = df[col]
    vals = [str(v) for v in (cond.get("values") or [])]
    unknown = _unknown_value_mask(s)
    if op == "notnull":
        return s.notna() & ~unknown
    if op == "isnull":
        return s.isna() | unknown
    if not vals:
        raise StepError(f"Operator {op!r} on {col!r} needs at least one value.")
    if op in ("gt", "ge", "lt", "le"):
        num = pd.to_numeric(s, errors="coerce")
        try:
            x = float(vals[0])
        except ValueError:
            raise StepError(f"{op!r} on {col!r} needs a number, got {vals[0]!r}.")
        return {"gt": num > x, "ge": num >= x, "lt": num < x, "le": num <= x}[op].fillna(False)
    text = s.astype(str).str.strip().str.lower().where(s.notna() & ~unknown, None)
    text = text.map(_normalise_boolean_value)
    lv = [_normalise_boolean_value(v.strip().lower()) for v in vals]
    if op in ("in", "eq", "not_in", "ne"):
        m = text.isin(lv)
        # Numbers match by value too: a column with blanks is stored as float, so 40 reads as "40.0" (objective = 40).
        nums = pd.to_numeric(pd.Series(lv, dtype=object), errors="coerce").dropna()
        if len(nums):
            m = m | pd.to_numeric(text, errors="coerce").isin(list(nums))
        if op in ("not_in", "ne"):
            m = ~m & s.notna() & ~unknown
    elif op == "startswith":
        m = text.fillna("").str.startswith(tuple(lv))
    elif op == "contains":
        m = text.fillna("").apply(lambda t: any(v in t for v in lv))
    return m.astype(bool)


def _unknown_value_mask(s: pd.Series) -> pd.Series:
    text = s.astype(str).str.strip().str.lower()
    return text.eq("indeterminate") | text.str.startswith("[") & text.str.endswith("]")


def _normalise_boolean_value(value: str) -> str:
    return {"yes": "true", "1": "true", "true": "true",
            "no": "false", "0": "false", "false": "false"}.get(value, value)


def _apply_where(df, where_list, where_name):
    m = pd.Series(True, index=df.index)
    for c in where_list or []:
        m &= _condition_mask(df, c, where_name)
    return m


def _condition_mask(df, condition, where_name):
    if "any" in condition:
        m = pd.Series(False, index=df.index)
        for nested in condition["any"]:
            m |= _condition_mask(df, nested, where_name)
        return m
    if "all" in condition:
        m = pd.Series(True, index=df.index)
        for nested in condition["all"]:
            m &= _condition_mask(df, nested, where_name)
        return m
    return _mask(df, condition, where_name)


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


def _insert_before(steps, i, step):
    new = copy.deepcopy(steps)
    new.insert(i - 1, step)
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
                df, warns = _filter(df, step, i, steps)
            elif step["op"] == "join":
                df, warns = _join(df, step, i, steps, ddir)
            elif step["op"] == "collapse":
                key = f"{step.get('level', 'sample')}_id"
                if step.get("level", "sample") == "patient":
                    priority = {"Primary Tumor": 0, "Metastatic": 1, "Solid Tissue Normal": 2}
                    ranked = df["sample_type"].map(priority).fillna(len(priority))
                    df = (df.assign(_collapse_priority=ranked)
                            .sort_values("_collapse_priority", kind="stable")
                            .drop_duplicates(subset=[key], keep="first")
                            .drop(columns="_collapse_priority"))
                else:
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


def _filter(df, step, i=0, steps=()):
    warns = _missing_value_warnings(df, step["where"], "the current cohort")
    warns += _value_not_found_warnings(df, step, i, list(steps), "the current cohort")
    return df[_apply_where(df, step["where"], "the current cohort")], warns


def _missing_value_warnings(df, where_list, where_name, cohort=None, on="sample_id"):
    warns = []
    conditions = _leaf_conditions(where_list or [])
    for c in conditions:
        if c["column"] not in df.columns or c["operator"] in ("isnull", "notnull"):
            continue
        missing = df[c["column"]].isna() | _unknown_value_mask(df[c["column"]])
        if not missing.any():
            continue
        affected = df.loc[missing]
        if cohort is not None:
            keys = affected[on].dropna().unique()
            affected = cohort[cohort[on].isin(keys)]
        n_s = affected["sample_id"].nunique()
        action = "were dropped" if cohort is None else "may be affected"
        warns.append(Warning_(
            "missing_values", "info",
            f"{n_s} samples {action} because `{c['column']}` is missing or coded as unknown for them, not because "
            f"they failed the condition. Decide whether that's acceptable.",
            examples=affected[["sample_id", "patient_id"]].drop_duplicates().head(10).to_dict("records"),
        ))
    return warns


def _leaf_conditions(conditions):
    leaves = []
    for condition in conditions:
        if "any" in condition:
            leaves.extend(_leaf_conditions(condition["any"]))
        elif "all" in condition:
            leaves.extend(_leaf_conditions(condition["all"]))
        else:
            leaves.append(condition)
    return leaves


# Common names people use for genes, mapped to the symbols in mutation_gene_level.tsv.gz.
GENE_ALIASES = {"her2": "ERBB2", "her-2": "ERBB2", "neu": "ERBB2", "her2/neu": "ERBB2", "p53": "TP53",
                "pi3k": "PIK3CA", "pik3": "PIK3CA", "e-cadherin": "CDH1", "ecad": "CDH1", "er": "ESR1",
                "esr": "ESR1", "pr": "PGR", "brca": "BRCA1"}


def _value_not_found_warnings(df, step, i, steps, where_name):
    """`gene = HER2` matches nothing (the symbol is ERBB2): say so and suggest real values (trap round, GAPS #33)."""
    import difflib

    warns = []
    raw_where = (steps[i - 1].get("where") or []) if 0 < i <= len(steps) else []
    for c_i, c in enumerate(step.get("where") or []):
        if "any" in c or "all" in c or c.get("operator") not in ("eq", "in") or c.get("column") not in df.columns:
            continue
        col = df[c["column"]]
        if pd.api.types.is_numeric_dtype(col) or pd.api.types.is_bool_dtype(col):
            continue
        known = col.dropna().astype(str).str.strip()
        known = known[~_unknown_value_mask(known)].unique()
        lower = {k.lower(): k for k in known}
        for v in c.get("values") or []:
            if str(v).strip().lower() in lower:
                continue
            alias = GENE_ALIASES.get(str(v).strip().lower()) if c["column"] == "gene" else None
            sugg = [alias] if alias and alias.lower() in lower else [
                lower[m] for m in difflib.get_close_matches(str(v).strip().lower(), list(lower), n=3, cutoff=0.6)]
            msg = f"No record in {where_name} has `{c['column']}` = {v!r}, so this value matches nothing."
            if sugg:
                msg += " Did you mean " + " or ".join(repr(s) for s in sugg) + "?"
            if alias:
                msg += f" ({v} is a common name; the gene symbol in this data is {alias}.)"
            fixes = []
            if sugg and c_i < len(raw_where) and raw_where[c_i].get("column") == c["column"]:
                new = copy.deepcopy(steps)
                vals = new[i - 1]["where"][c_i]["values"]
                new[i - 1]["where"][c_i]["values"] = [sugg[0] if x == v else x for x in vals]
                fixes.append({"label": f"Use {sugg[0]!r} instead of {v!r}", "steps": new})
            warns.append(Warning_("value_not_found", "info", msg, fixes=fixes))
    return warns


def _any_vs_all_warning(df, right, step, i, steps, on):
    """`gene in [TP53, PIK3CA]` keeps samples with ANY of them. If the user meant ALL, the count is very
    different (480 vs 57), so show both and offer one step per value (trap round, GAPS #32)."""
    where = step.get("where") or []
    for c_i, c in enumerate(where):
        if "any" in c or "all" in c or c.get("operator") not in ("in", "startswith", "contains"):
            continue
        vals = c.get("values") or []
        if len(vals) < 2 or c.get("column") not in right.columns:
            continue
        others = [w for k, w in enumerate(where) if k != c_i]
        base = right[_apply_where(right, others, "")]
        keysets = [set(base.loc[_mask(base, dict(c, values=[v]), ""), on].dropna()) for v in vals]
        n_any = df.loc[df[on].isin(set().union(*keysets)), "sample_id"].nunique()
        n_all = df.loc[df[on].isin(set.intersection(*keysets)), "sample_id"].nunique()
        if n_any == n_all:
            continue
        names = ", ".join(str(v) for v in vals)
        split = copy.deepcopy(steps)
        one = split.pop(i - 1)
        for v in reversed(vals):
            s = copy.deepcopy(one)
            s["how"] = "semi"
            s["where"][c_i] = dict(s["where"][c_i], operator="eq" if c["operator"] == "in" else c["operator"],
                                   values=[v])
            split.insert(i - 1, s)
        return [Warning_(
            "any_vs_all", "info",
            f"`{c['column']}` {c['operator']} [{names}] keeps samples with **any** of these ({n_any:,} samples). "
            f"Samples with **all** of them: {n_all:,}. If the request says \"and\" / \"both\", use one step per value.",
            fixes=[{"label": f"Require all of {names} (one step each)", "steps": split}],
        )]
    return []


def _join(df, step, i, steps, ddir):
    table, on, how = step["table"], step.get("on", "sample_id"), step.get("how", "inner")
    allow_cross_sample = step.get("allow_cross_sample", False) and how in ("semi", "anti")
    right = data.load(table, ddir)
    warns = _missing_value_warnings(right, step.get("where"), f"table {table!r}", cohort=df, on=on)
    warns += _value_not_found_warnings(right, step, i, steps, f"table {table!r}")
    if how in ("semi", "inner"):
        warns += _any_vs_all_warning(df, right, step, i, steps, on)
    if table == "mutation" and how == "anti" and "has_mutation" in df.columns:
        unsequenced = df[~df["has_mutation"].astype(bool)]
        if len(unsequenced):
            warns.append(Warning_(
                "unsequenced_mutation", "problem",
                f"{unsequenced['sample_id'].nunique()} samples have no mutation sequencing record. "
                "An anti-join keeps them because they cannot have a matching mutation row, so they must be "
                "excluded before asking which sequenced samples lack this mutation.",
                examples=unsequenced[["sample_id", "patient_id"]].drop_duplicates().head(10).to_dict("records"),
                fixes=[{"label": "Add has_mutation = True before this step",
                        "steps": _insert_before(steps, i, {
                            "op": "filter",
                            "where": [{"column": "has_mutation", "operator": "eq", "values": ["True"]}],
                        })}],
            ))
    right = right[_apply_where(right, step.get("where"), f"table {table!r}")]
    if how != "anti":
        warns += _redaction_check(df, right, table, on, step, i, steps)

    if how in ("semi", "anti"):
        hit = df[on].isin(right[on])
        out = df[hit] if how == "semi" else df[~hit]
        if on == "patient_id" and not allow_cross_sample:
            by_sample = df["sample_id"].isin(right["sample_id"])
            only_via_patient = df[hit & ~by_sample]
            if len(only_via_patient):
                if how == "semi":
                    message = (
                        f"{only_via_patient['sample_id'].nunique()} samples were kept only because a *different* "
                        f"sample of the same patient has a matching {table} record (e.g. a normal-tissue slide). "
                        "Records should link to a sample only when the sample barcode matches."
                    )
                else:
                    message = (
                        f"{only_via_patient['sample_id'].nunique()} samples were excluded only because a *different* "
                        f"sample of the same patient has a matching {table} record. "
                        "Records should link to a sample only when the sample barcode matches."
                    )
                warns.append(Warning_(
                    "cross_sample", "problem",
                    message,
                    examples=only_via_patient[["sample_id", "patient_id"]].head(10).to_dict("records"),
                    fixes=[{"label": "Match on sample_id instead of patient_id",
                            "steps": _with_step(steps, i, on="sample_id")}],
                ))
        return out, warns

    right = _prepare_right(df, right, table, on)
    out = df.merge(right, on=on, how=how)
    if on == "patient_id" and not allow_cross_sample:
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
        f"({', '.join(sorted(red['Redaction'].astype(str).unique()))}). They are **kept**: their values are filled "
        f"in and sample_manifest.csv (the official sample list) marks them as having this data, which is the "
        f"organizers' rule. A person should look at them before relying on their values.",
        examples=hit[["sample_id", "patient_id"]].drop_duplicates().head(10).to_dict("records"),
        fixes=[{"label": f"Exclude redacted {table} records (only if your question requires it)",
                "steps": _with_step(steps, i, where=where)}],
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
