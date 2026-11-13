"""Cohort Studio: describe a cohort, see what survives each step, catch inflating joins, export.

Run:  streamlit run app.py
"""
import json
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from cohort_studio import advice, builder, data, engine, export, versions

st.set_page_config(page_title="Cohort Studio", layout="wide")

EXAMPLES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path("examples").glob("*.json"))}
DEFAULT = "demo_diagnostic_slides"

ss = st.session_state
if "request" not in ss:
    ex = EXAMPLES.get(DEFAULT, {"request": "", "steps": []})
    ss.request = ex["request"]
    ss.ai_notes = None
    builder.set_steps(ex["steps"])


# ---------------------------------------------------------------- callbacks (run before the rerun)

# Replaces every step at once: the examples, an AI draft and the "Apply fix" buttons all use this.
set_steps = builder.set_steps


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

st.subheader("2 · Build the steps")
st.caption("`filter` keeps the samples that match · `join` brings in another table (and can repeat or drop "
           "samples) · `collapse` keeps one row per sample or patient. Every count below is recomputed as "
           "soon as a step changes.")
steps = builder.render()

df, results = engine.run(steps)

# ---------------------------------------------------------------- 3. funnel

# Same chart st.bar_chart drew, with two changes: the x axis is pinned at 0 (st.bar_chart binds
# pan/zoom to the scales, which let the axis be dragged into negative counts), and hovering a bar
# shows the step's full label, which the axis has to truncate. Colours and the rest of the styling
# come from Streamlit's own chart theme, so it looks like it did before.
MEASURES = ["rows", "samples", "patients"]


def funnel_chart(funnel: pd.DataFrame) -> "alt.Chart":
    long = funnel.melt(id_vars=["step", "what"], value_vars=MEASURES,
                       var_name="measure", value_name="count")
    long["label"] = long["step"].astype(str) + " · " + long["what"]
    order = list(dict.fromkeys(long["label"]))
    return (
        alt.Chart(long)
        .mark_bar()
        .encode(
            y=alt.Y("label:N", sort=order, title=None),
            yOffset=alt.YOffset("measure:N"),
            x=alt.X("count:Q", title=None, scale=alt.Scale(domainMin=0, nice=True, clamp=True)),
            color=alt.Color("measure:N", title=None,
                            legend=alt.Legend(orient="bottom", direction="horizontal")),
            tooltip=[alt.Tooltip("what:N", title="step"),
                     alt.Tooltip("measure:N", title="counting"),
                     alt.Tooltip("count:Q", title="count", format=",")],
        )
        .properties(height=90 * len(order) + 60)   # the bar thickness st.bar_chart used
    )


st.subheader("3 · What survives each step")
funnel = pd.DataFrame([{
    "step": r.index, "what": r.label, "rows": r.rows, "samples": r.samples, "patients": r.patients,
    "extra rows": r.extra_rows,
    "check": "❌ error" if r.error else ("⚠️ problem" if any(w.severity == "problem" for w in r.warnings)
                                       else ("ℹ️ note" if r.warnings else "✅")),
} for r in results])
st.dataframe(funnel, hide_index=True, width="stretch")
st.altair_chart(funnel_chart(funnel), alt="Rows, samples and patients surviving each step")

for r in results:
    if r.error:
        # Step 0 is the starting table, so an error there is about the step list as a whole.
        st.error(f"**Step {r.index} failed:** {r.error}" if r.index else
                 f"**These steps can't run:** {r.error}")
    advised = advice.advise(r, steps)   # which fix is the right one, and why (docs/GAPS.md #21)
    for w_i in advice.warning_order(r, advised):
        w = r.warnings[w_i]
        box = st.error if w.severity == "problem" else st.info
        box(f"**Step {r.index} · {r.label}**\n\n{w.message}")
        with st.expander(f"Affected records and fixes (step {r.index}, {w.kind})", expanded=w.severity == "problem"):
            if w.examples:
                st.dataframe(pd.DataFrame(w.examples), hide_index=True)
            for f_i in advice.order(w_i, w.fixes, advised):
                fix = w.fixes[f_i]
                best, why = advised.get((w_i, f_i), (False, ""))
                st.button(f"Apply fix: {fix['label']}", key=f"fix-{r.index}-{w_i}-{f_i}",
                          on_click=set_steps, args=(fix["steps"],),
                          type="primary" if best else "secondary",
                          icon=":material/star:" if best else None)
                if why:
                    st.caption(f"**Recommended.** {why}" if best else why)


# ---- did a step change *who* is in the cohort? (docs/GAPS.md #20, #27)
@st.cache_data(show_spinner=False)
def _makeup(steps_json: str):
    from cohort_studio.makeup import makeup_shifts
    return makeup_shifts(json.loads(steps_json))


if not any(r.error for r in results):
    try:
        from cohort_studio.makeup import SHIFT_TVD, describe_shift
        shifts = _makeup(json.dumps(steps, sort_keys=True))
        flagged = [e for e in shifts if e["flagged"]]
        with st.container(border=True):
            st.markdown("**Did a step change who's in the cohort?** For every step that removed samples, the mix of "
                        "submitting site, PAM50 subtype, ER status and age band before vs after "
                        f"(total variation distance; a note at {SHIFT_TVD:.2f} or more).")
            for e in flagged:
                st.info(describe_shift(e))
            if not flagged:
                st.success("No step shifted the cohort's makeup noticeably.")
            with st.expander("Details for every step"):
                rows = [{"step": e["step"], "samples": f"{e['before']:,} → {e['after']:,}",
                         **{s["attribute"]: f"{s['tvd']:.2f}" + (" (filtered on)" if s["expected"] else "")
                            for s in e["shifts"]}} for e in shifts]
                if rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True)
                for e in shifts:
                    if not e["flagged"]:
                        st.caption(describe_shift(e))
                st.caption("A shift isn't an error: it means the cohort that's left is a different population, "
                           "which a person should keep in mind. \"Filtered on\" shifts are expected.")
    except ImportError:
        pass  # DuckDB missing: the rest of the page still works
    except Exception as e:
        st.caption(f"Makeup check unavailable: {e}")

with st.container(border=True):
    st.markdown("**Why isn't a sample in my cohort?** Type a sample ID to see which step removed it and why.")
    sid = st.text_input("Sample ID", key="trace_id", placeholder="e.g. TCGA-E2-A15E-01",
                        label_visibility="collapsed")
    if sid.strip() and not any(r.error for r in results):
        try:
            from cohort_studio.sqlcheck import trace
            t = trace(steps, sid)
            (st.success if t["status"] == "in_cohort" else st.info)(t["why"])
            if t["details"]:
                st.dataframe(pd.DataFrame(t["details"]), hide_index=True)
            st.caption("Rows for this sample after each step: " +
                       " → ".join(str(p["rows for this sample"]) for p in t["path"]) + " (traced in SQL with DuckDB)")
        except ImportError:
            st.error("DuckDB isn't installed: run `pip install -r requirements.txt`.")
        except Exception as e:
            st.error(f"Couldn't trace that sample: {e}")

# ---------------------------------------------------------------- 4. result + export

st.subheader("4 · Review and export")
problems = engine.unresolved_problems(results)
final = results[-1]
m1, m2, m3 = st.columns(3)
m1.metric("Samples", f"{final.samples:,}")
m2.metric("Patients", f"{final.patients:,}")
m3.metric("Rows in table", f"{final.rows:,}", delta=f"+{final.extra_rows} duplicates" if final.extra_rows else None,
          delta_color="inverse")

# ---- compare this cohort with an earlier one from this session (docs/GAPS.md #26)
history = versions.record(steps, df) if not any(r.error for r in results) else st.session_state.get("versions", [])
earlier = [v for v in history[1:]]
if earlier:
    with st.expander(f"Compare with an earlier version ({len(earlier)} to choose from)"):
        st.caption("Every set of steps you have run in this session is kept here, newest first. Nothing is saved "
                   "to disk.")
        # Options are version numbers, not the dicts: a version can leave this list (it became the
        # current cohort, or aged out), and a stale selection would break the widget.
        by_number = {v["n"]: v for v in earlier}
        if ss.get("compare_with") not in by_number:
            ss.pop("compare_with", None)
        pick = by_number[st.selectbox("Compare the cohort above with", list(by_number), key="compare_with",
                                      format_func=lambda n: by_number[n]["label"])]
        d = versions.compare(history[0], pick)
        st.markdown(versions.summary(d))
        c1, c2, c3 = st.columns(3)
        c1.metric("Rows", f"{d['rows'][1]:,}", delta=f"{d['rows'][1] - d['rows'][0]:+,}", delta_color="off")
        c2.metric("Samples", f"{d['samples'][1]:,}", delta=f"{d['samples'][1] - d['samples'][0]:+,}",
                  delta_color="off")
        c3.metric("Patients", f"{d['patients'][1]:,}", delta=f"{d['patients'][1] - d['patients'][0]:+,}",
                  delta_color="off")
        moved = versions.diff_table(d)
        if len(moved):
            st.dataframe(moved, hide_index=True, height=240)
            st.download_button("cohort_diff.csv", moved.to_csv(index=False), "cohort_diff.csv", "text/csv")
        st.caption(f"Earlier version's steps: `{json.dumps(pick['steps'])}`")

st.warning("**Human review required.** A person should confirm the steps match the research question before "
           "this cohort is used. **Limitation:** layer membership (`has_*`) comes from the sample manifest. "
           "This tool doesn't check the quality of values inside each layer, and it only joins the clinical, "
           "survival and slide tables.")


@st.cache_data(show_spinner=False)
def _data_notes():
    from cohort_studio.sqlcheck import data_notes
    return data_notes()


try:
    _notes = _data_notes()
    with st.expander(f"Data notes: {len(_notes)} places where the source files disagree (checked live with DuckDB)"):
        for n in _notes:
            st.markdown(f"**{n['title']}.** {n['detail']}  \nExamples: " + ", ".join(f"`{e}`" for e in n["examples"]))
except Exception as e:  # DuckDB missing or data not fetched: the rest of the page still works
    st.caption(f"Data notes unavailable: {e}")


def run_sql_check():
    try:
        from cohort_studio.sqlcheck import verify
        ss.sql_check = (ss.steps_text, verify(steps, df, results))
    except ImportError:
        ss.sql_check = (ss.steps_text, {"error": "DuckDB isn't installed: run `pip install -r requirements.txt`."})
    except Exception as e:  # show what DuckDB said rather than crash the page
        ss.sql_check = (ss.steps_text, {"error": f"The SQL version couldn't run: {e}"})


with st.container(border=True):
    v1, v2 = st.columns([3, 1])
    v1.markdown("**Independent check.** Rebuild this cohort a second way: the same steps written as one "
                "DuckDB SQL query over the raw files, without the app's engine. Both should give the same samples.")
    v2.button("🔎 Verify with SQL", on_click=run_sql_check, width="stretch",
              disabled=any(r.error for r in results))
    chk = ss.get("sql_check")
    if chk and chk[0] == ss.steps_text:
        v = chk[1]
        if v.get("error"):
            st.error(v["error"])
        else:
            if v["match"]:
                st.success(f"✅ **Match.** Engine: **{v['engine_samples']:,}** samples · independent SQL: "
                           f"**{v['sql_samples']:,}** samples. Same sample IDs, and the same rows, samples and "
                           f"patients after every step.")
                if problems:
                    st.warning("Both agree on the numbers, **including the problems flagged above**. "
                               "Apply a fix first, then verify again.")
            else:
                st.error(f"❌ **Mismatch.** Engine: {v['engine_samples']:,} samples · SQL: {v['sql_samples']:,}. "
                         f"Don't use this cohort until someone finds out why.")
                if v["only_engine"] or v["only_sql"]:
                    st.write("Only in the engine:", v["only_engine"][:20], "Only in SQL:", v["only_sql"][:20])
            st.dataframe(pd.DataFrame(v["by_step"]), hide_index=True)
            st.caption("This checks that the steps were *carried out* correctly. It can't tell you whether the "
                       "steps match your research question: that's the human review below.")
            with st.expander("Show the SQL (copy it, or download and run `python scripts/sql.py -f cohort.sql`)"):
                st.code(v["sql"], language="sql")
                st.download_button("cohort.sql", v["sql"], "cohort.sql", "text/plain")
    elif chk:
        st.caption("The steps changed since the last check. Click **Verify with SQL** again.")

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
