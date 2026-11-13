"""Dropdown step builder: build a cohort without writing JSON.

Every control here only *produces* the step format documented in docs/ARCHITECTURE.md
(`filter` / `join` / `collapse`). The format itself is unchanged, so the engine, the AI
draft and the "Apply fix" buttons keep working.

How the state fits together:

- `st.session_state.b_uids`  : one id per step, in order. Widget keys are built from the id,
  not the position, so moving or deleting a step doesn't shuffle anyone's values.
- `st.session_state.b_steps` : id -> the step dict as last built (used to seed the widgets).
- `st.session_state.b_conds` : id -> ids of that step's `where` conditions.
- `set_steps()` replaces everything (examples, AI draft, fix buttons, JSON edits): it drops
  every builder widget key so the new steps seed cleanly.
"""
from __future__ import annotations

import copy
import json

import pandas as pd
import streamlit as st

from . import data, engine

WIDGET_PREFIX = "b_w_"
MAX_VALUE_OPTIONS = 60

OP_LABELS = {"filter": "Filter rows", "join": "Join a table", "collapse": "Collapse rows"}
HOW_LABELS = {
    "inner": "Add its columns (drops samples with no match)",
    "left": "Add its columns, keep samples with no match",
    "semi": "Keep samples that have a match (no new columns, never duplicates)",
    "anti": "Drop samples that have a match",
}
OPERATOR_LABELS = {
    "in": "is one of", "not_in": "is not one of", "eq": "is", "ne": "is not",
    "gt": "is greater than", "ge": "is at least", "lt": "is less than", "le": "is at most",
    "notnull": "is present", "isnull": "is missing",
    "startswith": "starts with", "contains": "contains",
}
LEVEL_LABELS = {"sample": "One row per sample", "patient": "One row per patient"}
NO_VALUE_OPS = ("isnull", "notnull")
NUMBER_OPS = ("gt", "ge", "lt", "le")

DEFAULT_STEPS = {
    "filter": {"op": "filter",
               "where": [{"column": "sample_type", "operator": "in", "values": ["Primary Tumor"]}]},
    "join": {"op": "join", "table": "slides", "on": "sample_id", "how": "semi", "where": []},
    "collapse": {"op": "collapse", "level": "sample"},
}


# ---------------------------------------------------------------- schema lookups (cached)

def _value_map(df: pd.DataFrame) -> dict[str, list[str]]:
    """Column -> its values, for columns short enough to offer as a dropdown."""
    out: dict[str, list[str]] = {}
    for c in df.columns:
        s = df[c].dropna()
        if s.empty:
            continue
        if not pd.api.types.is_bool_dtype(s) and pd.api.types.is_numeric_dtype(s):
            continue  # a number: let the user type one instead
        vals = pd.unique(s.astype(str).str.strip())
        if len(vals) <= MAX_VALUE_OPTIONS:
            out[c] = sorted(str(v) for v in vals)
    return out


@st.cache_data(show_spinner=False)
def _cohort_schema(prefix_json: str) -> tuple[list[str], dict[str, list[str]]]:
    """Columns and values the cohort has *after* the steps before this one."""
    df, _ = engine.run(json.loads(prefix_json))
    return list(df.columns), _value_map(df)


@st.cache_data(show_spinner=False)
def _table_schema(table: str) -> tuple[list[str], dict[str, list[str]]]:
    df = data.load(table)
    return list(df.columns), _value_map(df)


def _schema_for(prefix: list[dict]) -> tuple[list[str], dict[str, list[str]]]:
    try:
        return _cohort_schema(json.dumps(prefix))
    except Exception:
        return list(data.load("samples").columns), {}


def _with_current(options, *current) -> list[str]:
    """Options, plus anything already selected that isn't in them (a stale column, a typed value)."""
    out = list(options)
    for c in current:
        for v in (c if isinstance(c, list) else [c]):
            if v not in out and v not in (None, ""):
                out.insert(0, v)
    return out


# ---------------------------------------------------------------- state

def _new_uid() -> int:
    ss = st.session_state
    ss.b_next_uid = ss.get("b_next_uid", 0) + 1
    return ss.b_next_uid


def _drop_keys(prefix: str) -> None:
    for k in [k for k in list(st.session_state.keys()) if str(k).startswith(prefix)]:
        del st.session_state[k]


def set_steps(steps) -> None:
    """Replace the whole step list. Used by the examples, the AI draft and the fix buttons."""
    ss = st.session_state
    steps = [engine.clean_step(s) if isinstance(s, dict) else s for s in steps]
    _drop_keys(WIDGET_PREFIX)
    ss.b_uids, ss.b_steps, ss.b_conds = [], {}, {}
    for s in steps:
        uid = _new_uid()
        ss.b_uids.append(uid)
        ss.b_steps[uid] = s
        ss.b_conds[uid] = [_new_uid() for c in (s.get("where") or []) if not _is_group(c)]
    text = json.dumps(steps, indent=2)
    ss.steps_text = text
    ss.b_json_shown = text
    ss.b_json_error = None


def _move(uid: int, delta: int) -> None:
    uids = st.session_state.b_uids
    i, j = uids.index(uid), uids.index(uid) + delta
    if 0 <= j < len(uids):
        uids[i], uids[j] = uids[j], uids[i]


def _remove(uid: int) -> None:
    ss = st.session_state
    ss.b_uids.remove(uid)
    ss.b_steps.pop(uid, None)
    ss.b_conds.pop(uid, None)
    _drop_keys(f"{WIDGET_PREFIX}{uid}_")


def _add_step(op: str) -> None:
    ss = st.session_state
    uid, step = _new_uid(), copy.deepcopy(DEFAULT_STEPS[op])
    ss.b_uids.append(uid)
    ss.b_steps[uid] = step
    ss.b_conds[uid] = [_new_uid() for _ in (step.get("where") or [])]


def _add_cond(uid: int) -> None:
    st.session_state.b_conds.setdefault(uid, []).append(_new_uid())


def _remove_cond(uid: int) -> None:
    cuids = st.session_state.b_conds.get(uid) or []
    if cuids:
        _drop_keys(f"{WIDGET_PREFIX}{uid}_{cuids.pop()}_")


# ---------------------------------------------------------------- conditions

def _is_group(condition: dict) -> bool:
    return "any" in condition or "all" in condition


def _condition(uid: int, cuid: int, columns: list[str], values: dict[str, list[str]],
               seed: dict) -> dict | None:
    """One condition row. Returns None while it has no value yet, so a half-typed
    condition leaves the funnel alone instead of failing the step."""
    ss = st.session_state
    col_key = f"{WIDGET_PREFIX}{uid}_{cuid}_col"
    opr_key = f"{WIDGET_PREFIX}{uid}_{cuid}_opr"
    val_key = f"{WIDGET_PREFIX}{uid}_{cuid}_vals"
    num_key = f"{WIDGET_PREFIX}{uid}_{cuid}_num"
    seed_vals = [str(v) for v in (seed.get("values") or [])]
    ss.setdefault(col_key, seed.get("column") or (columns[0] if columns else ""))
    ss.setdefault(opr_key, seed.get("operator") or "in")
    ss.setdefault(val_key, seed_vals)
    ss.setdefault(num_key, seed_vals[0] if seed_vals else "")

    row = st.container(horizontal=True, vertical_alignment="bottom")
    col = row.selectbox("Column", _with_current(columns, ss[col_key]), key=col_key)
    opr = row.selectbox("Condition", list(OPERATOR_LABELS), key=opr_key,
                        format_func=lambda o: OPERATOR_LABELS[o])
    cond = {"column": col, "operator": opr}
    if opr in NO_VALUE_OPS:
        return cond
    if opr in NUMBER_OPS:
        num = row.text_input("Number", key=num_key, placeholder="e.g. 1825")
        picked = [num.strip()] if num.strip() else []
    else:
        picked = [str(v) for v in row.multiselect(
            "Values", _with_current(values.get(col, []), ss[val_key]), key=val_key,
            accept_new_options=True, placeholder="pick a value, or type one",
            help="Matching ignores case and surrounding spaces. Several values mean 'any of these'.")]
    if not picked:
        st.caption(f":material/info: `{col}` has no value yet, so this condition isn't being applied.")
        return None
    return {**cond, "values": picked}


def _conditions(uid: int, columns: list[str], values: dict[str, list[str]],
                seed_where: list[dict]) -> list[dict]:
    cuids = st.session_state.b_conds.setdefault(uid, [])
    simple_seeds = [c for c in seed_where if not _is_group(c)]
    conds = [c for c in (_condition(uid, cuid, columns, values,
                                    simple_seeds[n] if n < len(simple_seeds) else {})
                         for n, cuid in enumerate(cuids)) if c]
    groups = [c for c in seed_where if _is_group(c)]
    for group in groups:
        st.caption("OR/AND group is read-only here; edit it in the JSON view.")
        st.json(group)
    with st.container(horizontal=True):
        st.button("Add condition", icon=":material/add:", key=f"{WIDGET_PREFIX}{uid}_addc",
                  on_click=_add_cond, args=(uid,))
        st.button("Remove last condition", icon=":material/remove:", key=f"{WIDGET_PREFIX}{uid}_rmc",
                  on_click=_remove_cond, args=(uid,), disabled=not cuids)
    return conds + groups


# ---------------------------------------------------------------- one step

def _step(number: int, uid: int, prefix: list[dict]) -> tuple[dict, bool]:
    """Draw one step. Returns it and whether it's finished enough to run: a filter with
    no conditions yet is left out of the cohort instead of breaking the whole funnel.

    `number` is the step number this will get *if* it runs, so the card numbers and the
    funnel's step numbers always agree.
    """
    ss = st.session_state
    seed = ss.b_steps.get(uid) or {"op": "filter"}
    op_key = f"{WIDGET_PREFIX}{uid}_op"
    ss.setdefault(op_key, seed.get("op", "filter"))

    with st.container(border=True):
        heading = st.empty()
        with st.container(horizontal=True, vertical_alignment="bottom"):
            op = st.segmented_control("Step type", list(OP_LABELS), key=op_key, required=True,
                                      format_func=lambda o: OP_LABELS[o]) or seed.get("op", "filter")
            st.button("Up", icon=":material/arrow_upward:", key=f"{WIDGET_PREFIX}{uid}_up",
                      on_click=_move, args=(uid, -1), disabled=uid == ss.b_uids[0])
            st.button("Down", icon=":material/arrow_downward:", key=f"{WIDGET_PREFIX}{uid}_down",
                      on_click=_move, args=(uid, 1),
                      disabled=uid == ss.b_uids[-1])
            st.button("Remove", icon=":material/delete:", key=f"{WIDGET_PREFIX}{uid}_del",
                      on_click=_remove, args=(uid,))

        if op == "filter":
            columns, values = _schema_for(prefix)
            st.caption("Keeps the samples that match. Every condition must be true "
                       "(there's no OR yet — see the limitations).")
            step = {"op": "filter", "where": _conditions(uid, columns, values, seed.get("where") or [])}

        elif op == "join":
            tbl_key = f"{WIDGET_PREFIX}{uid}_table"
            on_key = f"{WIDGET_PREFIX}{uid}_on"
            how_key = f"{WIDGET_PREFIX}{uid}_how"
            ss.setdefault(tbl_key, seed.get("table") or "slides")
            ss.setdefault(on_key, seed.get("on") or "sample_id")
            ss.setdefault(how_key, seed.get("how") or "inner")
            with st.container(horizontal=True, vertical_alignment="bottom"):
                table = st.selectbox("Table", _with_current(list(data.TABLES), ss[tbl_key]), key=tbl_key)
                on = st.selectbox("Match on", list(data.KEYS), key=on_key)
                how = st.selectbox("What the join does", list(HOW_LABELS), key=how_key,
                                   format_func=lambda h: HOW_LABELS[h])
            meta = data.TABLES.get(table, {})
            st.caption(meta.get("about", ""))
            if meta.get("grain") != "sample" and how in ("inner", "left"):
                st.caption(f":material/warning: `{table}` has several rows per sample, so this join will "
                           f"repeat samples. *Keep samples that have a match* counts each sample once.")
            if on == "patient_id":
                st.caption(":material/warning: matching on `patient_id` can attach a record that belongs to "
                           "a *different* sample of the same patient (a normal sample's record on a tumor).")
            columns, values = _table_schema(table) if table in data.TABLES else ([], {})
            st.caption(f"Conditions on the `{table}` rows themselves (which records count as a match):")
            conds = _conditions(uid, columns, values, seed.get("where") or [])
            step = {"op": "join", "table": table, "on": on, "how": how}
            if "allow_cross_sample" in seed:
                step["allow_cross_sample"] = seed["allow_cross_sample"]
            if conds:
                step["where"] = conds

        else:
            lvl_key = f"{WIDGET_PREFIX}{uid}_level"
            ss.setdefault(lvl_key, seed.get("level") or "sample")
            level = st.segmented_control("Keep", list(LEVEL_LABELS), key=lvl_key, required=True,
                                         format_func=lambda l: LEVEL_LABELS[l]) or "sample"
            st.caption("Drops repeated rows, keeping the first one for each sample or patient.")
            step = {"op": "collapse", "level": level}

        applied = not (step["op"] == "filter" and not step["where"])
        if applied:
            heading.markdown(f"**Step {number}**")
            try:
                st.caption(f"**In words:** {engine.describe(step)}")
            except Exception:
                applied = False
        if not applied:
            heading.markdown(":material/info: **Not applied yet** — this filter has no condition with a "
                             "value, so it doesn't change the cohort and isn't exported.")
    return step, applied


# ---------------------------------------------------------------- JSON view

def _json_edited() -> None:
    ss = st.session_state
    try:
        parsed = json.loads(ss.steps_text)
    except json.JSONDecodeError as e:
        ss.b_json_error = f"That isn't valid JSON, so the steps above didn't change: {e}"
        return
    if not isinstance(parsed, list):
        ss.b_json_error = "The steps must be a JSON list, so the steps above didn't change."
        return
    set_steps(parsed)


def _json_view(steps: list[dict]) -> None:
    ss = st.session_state
    current = json.dumps(steps, indent=2)
    if ss.get("b_json_shown") != current:          # the builder changed the steps: refresh the box
        ss.steps_text = current
        ss.b_json_shown = current
    with st.expander("Advanced: edit the steps as JSON"):
        st.caption("The same steps in the format the engine, the AI draft and `run_cohort.py` use. "
                   "Edit and press Ctrl+Enter to load them back into the builder.")
        st.text_area("Steps (JSON)", key="steps_text", height=240, on_change=_json_edited,
                     label_visibility="collapsed")
        if ss.get("b_json_error"):
            st.error(ss.b_json_error)


# ---------------------------------------------------------------- entry point

def render() -> list[dict]:
    """Draw the builder and return the current steps."""
    ss = st.session_state
    if "b_uids" not in ss:
        set_steps([])

    steps: list[dict] = []
    for uid in list(ss.b_uids):
        step, applied = _step(len(steps) + 1, uid, steps)
        ss.b_steps[uid] = step                      # seed the widgets on the next run
        if applied:
            steps.append(step)

    if not steps:
        st.info("No steps yet, so the cohort is every sample in the manifest. Add a step below, or load "
                "an example from the sidebar.")
    chosen = st.menu_button("Add a step", list(DEFAULT_STEPS), key="b_add_step",
                            icon=":material/add:", format_func=lambda o: OP_LABELS[o])
    if chosen:
        _add_step(chosen)
        st.rerun()

    for problem in engine.validate_steps(steps):
        st.warning(problem)
    _json_view(steps)
    return steps
