"""Cohort Studio: describe a cohort, see what survives each step, catch inflating joins, export.

Run:  streamlit run app.py
"""
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from cohort_studio import data, engine, export

st.set_page_config(page_title="Cohort Studio", layout="wide")

EXAMPLES = {p.stem: json.loads(p.read_text()) for p in sorted(Path("examples").glob("*.json"))}
DEFAULT = "demo_diagnostic_slides"

ss = st.session_state
if "steps_text" not in ss:
    ex = EXAMPLES.get(DEFAULT, {"request": "", "steps": []})
    ss.steps_text = json.dumps(ex["steps"], indent=2)
    ss.request = ex["request"]
    ss.ai_notes = None


# ---------------------------------------------------------------- callbacks (run before the rerun)

def set_steps(steps):
    ss.steps_text = json.dumps(steps, indent=2)


def load_example(name):
    ss.request = EXAMPLES[name]["request"]
    set_steps(EXAMPLES[name]["steps"])
    ss.ai_notes = None


def draft_with_ai():
    from cohort_studio.llm import draft_steps
    key = ss.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        ss.ai_notes = {"error": "Add an Anthropic API key in the sidebar, or write the steps by hand."}
        return
    try:
        out = draft_steps(ss.request, api_key=key)
        set_steps(out["steps"])
        ss.ai_notes = out
    except RuntimeError as e:
        ss.ai_notes = {"error": str(e)}


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("Data")
    st.caption(f"`{data.data_dir()}`")
    status = data.check_data(str(data.data_dir()))
    for f, s in status.items():
        icon = {"ok": "✅", "missing": "❌", "CHANGED": "⚠️"}[s]
        st.write(f"{icon} {f} — {s}")
    if any(s != "ok" for s in status.values()):
        st.error("Run `python data/tcga-brca/fetch.py` in the challenge repo, or set ONCOSYS_DATA. "
                 "A CHANGED file doesn't match the event's frozen checksum: don't use it for judged results.")
    st.header("AI drafting (optional)")
    st.text_input("Anthropic API key", type="password", key="api_key",
                  help="Used only for this session, never saved. Leave blank to build steps by hand.")
    st.header("Examples")
    for name in EXAMPLES:
        st.button(name.replace("_", " "), on_click=load_example, args=(name,), width="stretch")

# ---------------------------------------------------------------- 1. request + steps

st.title("Cohort Studio")
st.caption("Build a TCGA-BRCA cohort step by step, see who survives each step, and catch joins that count "
           "samples twice. Research use only: no diagnosis, treatment advice or clinical claims.")

st.subheader("1 · Describe the cohort")
c1, c2 = st.columns([5, 1])
c1.text_input("Request", key="request", label_visibility="collapsed",
              placeholder="e.g. ER-positive primary tumors with RNA data and a diagnostic slide")
c2.button("Draft steps with AI", on_click=draft_with_ai, width="stretch")

notes = ss.get("ai_notes")
if notes:
    if notes.get("error"):
        st.warning(notes["error"])
    else:
        st.info("**AI draft — review before running.** The AI only proposed these steps; every count below "
                "is computed directly from the data.")
        for a in notes.get("assumptions", []):
            st.write(f"• Assumption: {a}")
        if notes.get("cannot_answer"):
            st.error(f"The data can't answer part of this request: {notes['cannot_answer']}")

st.subheader("2 · Edit the steps")
st.caption("Steps are JSON. `filter` keeps rows · `join` adds a table (`inner`, `left`, `semi` = keep if a "
           "match exists, `anti` = drop if it does) · `collapse` keeps one row per sample or patient.")
st.text_area("Steps", key="steps_text", height=300, label_visibility="collapsed")

try:
    steps = json.loads(ss.steps_text)
except json.JSONDecodeError as e:
    st.error(f"The steps aren't valid JSON: {e}")
    st.stop()

df, results = engine.run(steps)

# ---------------------------------------------------------------- 3. funnel

st.subheader("3 · What survives each step")
funnel = pd.DataFrame([{
    "step": r.index, "what": r.label, "rows": r.rows, "samples": r.samples, "patients": r.patients,
    "extra rows": r.extra_rows,
    "check": "❌ error" if r.error else ("⚠️ problem" if any(w.severity == "problem" for w in r.warnings)
                                       else ("ℹ️ note" if r.warnings else "✅")),
} for r in results])
st.dataframe(funnel, hide_index=True, width="stretch")
st.bar_chart(funnel.set_index(funnel["step"].astype(str) + " · " + funnel["what"].str[:40])[["rows", "samples", "patients"]],
             stack=False, horizontal=True)

for r in results:
    if r.error:
        st.error(f"**Step {r.index} failed:** {r.error}")
    for w_i, w in enumerate(r.warnings):
        box = st.error if w.severity == "problem" else st.info
        box(f"**Step {r.index} · {r.label}**\n\n{w.message}")
        with st.expander(f"Affected records and fixes (step {r.index}, {w.kind})", expanded=w.severity == "problem"):
            if w.examples:
                st.dataframe(pd.DataFrame(w.examples), hide_index=True)
            for f_i, fix in enumerate(w.fixes):
                st.button(f"Apply fix: {fix['label']}", key=f"fix-{r.index}-{w_i}-{f_i}",
                          on_click=set_steps, args=(fix["steps"],))

# ---------------------------------------------------------------- 4. result + export

st.subheader("4 · Review and export")
problems = engine.unresolved_problems(results)
final = results[-1]
m1, m2, m3 = st.columns(3)
m1.metric("Samples", f"{final.samples:,}")
m2.metric("Patients", f"{final.patients:,}")
m3.metric("Rows in table", f"{final.rows:,}", delta=f"+{final.extra_rows} duplicates" if final.extra_rows else None,
          delta_color="inverse")

st.warning("**Human review required.** A person should confirm the steps match the research question before "
           "this cohort is used. **Limitation:** layer membership (`has_*`) comes from the sample manifest. "
           "This tool doesn't check the quality of values inside each layer, and it only joins the clinical, "
           "survival and slide tables.")

if problems:
    st.error("Not ready to export:\n\n" + "\n".join(f"- {p}" for p in problems))
    ok = st.checkbox("I understand: export anyway. cohort_samples.csv will still contain each sample only once.")
else:
    st.success("No unresolved problems: one row per sample, and every joined record belongs to its own sample.")
    ok = True

out = export.cohort_samples(df)
defn = export.cohort_definition(steps, ss.request, results)
e1, e2, e3 = st.columns(3)
e1.download_button("cohort_samples.csv", out.to_csv(index=False), "cohort_samples.csv", "text/csv",
                   disabled=not ok, width="stretch")
e2.download_button("cohort.json (definition + funnel)", json.dumps(defn, indent=2), "cohort.json",
                   "application/json", disabled=not ok, width="stretch")
e3.download_button("rebuild_cohort.py", export.rebuild_script(steps, ss.request), "rebuild_cohort.py",
                   "text/x-python", disabled=not ok, width="stretch")

with st.expander(f"Preview final table ({len(df):,} rows)"):
    cfg = {"viewer_url": st.column_config.LinkColumn("slide viewer")} if "viewer_url" in df.columns else None
    st.dataframe(df.head(500), hide_index=True, column_config=cfg)
