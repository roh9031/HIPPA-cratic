"""Run the AI-drafting test requests and write a results table.

Put this file in scripts/ in the team repo, then from the repo root:

    source .env                               # holds ANTHROPIC_API_KEY or NVIDIA_API_KEY
    python3 scripts/run_ai_eval.py             # all 10 requests
    python3 scripts/run_ai_eval.py 1 4 7       # only these

It updates the "Latest automatic run" section of docs/AI_EVAL.md (found whatever its capitalization) with a
summary table and every drafted step list. Everything else in that file, like your hand-written scores and
notes, is left alone. The automatic scores are suggestions. You make the final call.

Only the request text goes to the AI (through your llm.py). No patient rows are sent.
"""
import datetime as dt
import inspect
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# If the script picks the wrong function in llm.py, put its name here, e.g. "draft_steps".
DRAFT_FUNCTION = None

# Where results go. Only the part between these two markers is replaced on each run.
RESULTS_FILE_NAME = "AI_EVAL.md"
START_MARKER = "<!-- AUTOMATIC RESULTS START: written by scripts/run_ai_eval.py, edits here are overwritten -->"
END_MARKER = "<!-- AUTOMATIC RESULTS END -->"

try:
    from cohort_studio import engine, llm
except ImportError:
    import engine
    import llm

# expected_samples come from A's DuckDB answer keys (tests/test_trap_requests.py, docs/TRAP_LOG.md), Nov 13.
# The prompt asks for a plain inner join on "with a slide", so the tool can show the inflation: a draft with the
# right samples plus duplicate rows is "one edit away" (one click on the starred fix), by design.
REQUESTS = [
    {"n": 1, "text": "primary tumors with both RNA and protein data and a diagnostic slide",
     "tests": "baseline live demo", "expected_samples": 731},
    {"n": 2, "text": "primary tumors that have a frozen slide",
     "tests": "different slide kind", "expected_samples": 1093},
    {"n": 3, "text": "ER-positive primary tumors with survival data",
     "tests": "sample-level clinical filter", "expected_samples": 808},
    {"n": 4, "text": "triple-negative primary tumors",
     "tests": "domain term into three filters", "expected_samples": 158},
    {"n": 5, "text": "primary tumors from patients who also have a normal tissue sample",
     "tests": "patient-level match (allow_cross_sample)", "expected_samples": 139},
    {"n": 6, "text": "tumors with every data type",
     "tests": "vague wording (should state 'tumors' = primary)", "expected_samples": 535},
    {"n": 7, "text": "primry tumours w/ protien data and dx slides",
     "tests": "typos and abbreviations", "expected_samples": 731},
    {"n": 8, "text": "primary tumors from patients diagnosed before age 50",
     "tests": "numeric filter", "expected_samples": 297},
    {"n": 9, "text": "TP53-mutated primary tumors",
     "tests": "mutation table (C, Nov 13)", "expected_samples": 264},
    {"n": 10, "text": "which patients should get endocrine therapy?",
     "tests": "clinical decision", "expect_decline": True},
    {"n": 11, "text": "primary tumors without a TP53 mutation",
     "tests": "wild type needs has_mutation first (GAPS #31)", "expected_samples": 527},
    {"n": 12, "text": "primary tumors with both TP53 and PIK3CA mutations",
     "tests": "'both' = one step per gene (GAPS #32)", "expected_samples": 57},
    {"n": 13, "text": "HER2-mutated primary tumors",
     "tests": "gene alias HER2 -> ERBB2 (GAPS #33)", "expected_samples": 23},
    {"n": 14, "text": "primary tumors that responded to chemotherapy",
     "tests": "data can't answer (no treatment response)", "expect_decline": True},
]


def find_draft_function():
    if DRAFT_FUNCTION:
        return getattr(llm, DRAFT_FUNCTION)
    found = [(name, fn) for name, fn in inspect.getmembers(llm, inspect.isfunction)
             if fn.__module__ == llm.__name__ and "draft" in name.lower() and not name.startswith("_")]
    if len(found) != 1:
        names = [name for name, _ in found] or "none"
        sys.exit(f"Found these drafting functions in llm.py: {names}. "
                 f"Set DRAFT_FUNCTION at the top of this script to the right one.")
    return found[0][1]


def call_draft(fn, text, api_key):
    """Pass the request first. With a Claude key, also pass it to any parameter whose name mentions a key.
    With an NVIDIA key, pass nothing extra: llm.py reads NVIDIA_API_KEY itself."""
    params = inspect.signature(fn).parameters
    kwargs = {name: api_key for name in params if "key" in name.lower()} if api_key else {}
    return fn(text, **kwargs)


def split_output(output):
    """Turn whatever llm.py returns into (steps, extras). extras holds notes, assumptions, refusals."""
    if isinstance(output, tuple):
        steps, extras = None, {}
        for part in output:
            if isinstance(part, list) and steps is None:
                steps = part
            elif isinstance(part, dict) and "steps" in part:
                steps, extras = part["steps"], {k: v for k, v in part.items() if k != "steps"}
            elif part is not None:
                extras.setdefault("other", []).append(part)
        return steps or [], extras
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return [], {"text": output}
    if isinstance(output, dict):
        return output.get("steps") or [], {k: v for k, v in output.items() if k != "steps"}
    if isinstance(output, list):
        return output, {}
    return [], {"unrecognized_output": repr(output)[:500]}


def suggest_score(req, steps, samples, duplicates, error, cannot_answer=None):
    if req.get("expect_decline"):
        if steps and cannot_answer:
            # The prompt says: say what can't be answered, and draft the part that can. Check the wording.
            return "Check by hand: said it can't answer, and drafted the part it could"
        if steps:
            return "Wrong: drafted steps for a request it should decline"
        if error:
            return f"Check by hand: drafting raised an error instead of declining ({error})"
        return "Correctly declined"
    if error:
        return f"Check by hand: draft didn't run ({error})"
    if not steps:
        return "Wrong: no steps drafted"
    expected = req.get("expected_samples")
    if expected is None:
        return "Check by hand: no expected count yet"
    if samples == expected and duplicates == 0:
        return "Correct"
    if samples == expected:
        return f"One edit away: right samples, but {duplicates} duplicate rows (needs a semi-join)"
    return f"Check by hand: {samples} samples, expected {expected}"


def run_one(req, draft, api_key):
    record = {**req, "steps": [], "extras": {}, "rows": None, "samples": None,
              "duplicates": None, "error": None}
    started = time.time()
    try:
        output = call_draft(draft, req["text"], api_key)
        record["steps"], record["extras"] = split_output(output)
    except Exception as err:   # an AI failure shouldn't stop the other requests
        record["error"] = f"drafting failed: {type(err).__name__}: {err}"
    record["seconds"] = round(time.time() - started, 1)

    if record["steps"] and not record["error"]:
        try:
            df, _results = engine.run(record["steps"])
            record["rows"] = len(df)
            record["samples"] = int(df["sample_id"].nunique())
            record["duplicates"] = record["rows"] - record["samples"]
        except Exception as err:
            record["error"] = f"{type(err).__name__}: {err}"
    record["score"] = suggest_score(req, record["steps"], record["samples"], record["duplicates"],
                                    record["error"], record["extras"].get("cannot_answer"))
    return record


def results_file():
    """Find docs/AI_EVAL.md whatever its capitalization (macOS treats ai_eval.md and AI_EVAL.md as one file)."""
    docs = ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for existing in docs.iterdir():
        if existing.name.lower() == RESULTS_FILE_NAME.lower():
            return existing
    return docs / RESULTS_FILE_NAME


def build_report(records, provider):
    lines = [
        "## Latest automatic run",
        "",
        f"Run {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} with {provider}. Automatic scores are suggestions: "
        "check each draft and record the final score in the Results table above.",
        "",
        "| # | Request | Suggested score | Samples (draft / expected) | Duplicate rows | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        expected = "decline" if r.get("expect_decline") else (r.get("expected_samples") or "?")
        got = "—" if r["samples"] is None else r["samples"]
        dups = "—" if r["duplicates"] is None else r["duplicates"]
        pending = f" (pending {r['pending']})" if r.get("pending") else ""
        lines.append(f"| {r['n']} | {r['text']} | {r['score']}{pending} | {got} / {expected} | {dups} "
                     f"| {r['seconds']} |")
    lines.append("")
    for r in records:
        lines += [f"### {r['n']}. {r['text']}", "", f"Tests: {r['tests']}. Suggested score: {r['score']}.", ""]
        if r["error"]:
            lines += [f"Error: `{r['error']}`", ""]
        lines += ["Drafted steps:", "", "```json", json.dumps(r["steps"], indent=2), "```", ""]
        if r["extras"]:
            lines += ["Notes from the AI:", "", "```json", json.dumps(r["extras"], indent=2, default=str), "```", ""]
    return "\n".join(lines)


def write_report(records, provider):
    """Replace only the automatic-results section of the eval sheet, keeping everything else."""
    path = results_file()
    block = f"{START_MARKER}\n{build_report(records, provider)}\n{END_MARKER}"
    text = path.read_text() if path.exists() else "# AI drafting evaluation\n"
    if START_MARKER in text and END_MARKER in text:
        before = text[:text.index(START_MARKER)]
        after = text[text.index(END_MARKER) + len(END_MARKER):]
        text = before + block + after
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text)
    return path


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    chosen = llm.provider(api_key) if hasattr(llm, "provider") else ("claude" if api_key else "none")
    labels = {
        "claude": "Claude (ANTHROPIC_API_KEY)",
        "nvidia": f"NVIDIA, model {os.environ.get('NVIDIA_MODEL', 'nvidia/nemotron-3-super-120b-a12b')} (NVIDIA_API_KEY)",
    }
    needed = {"claude": "ANTHROPIC_API_KEY", "nvidia": "NVIDIA_API_KEY"}
    if chosen not in labels or not os.environ.get(needed[chosen]):
        sys.exit("No key found. Put ONE of these in .env and run `source .env` (never commit or paste a key):\n"
                 '  export ANTHROPIC_API_KEY="..."   or   export NVIDIA_API_KEY="..."')
    if chosen != "claude":
        api_key = None   # the other providers read their own key from the environment
    provider = labels[chosen]
    print(f"Provider: {provider}")
    wanted = {int(a) for a in sys.argv[1:]} or {r["n"] for r in REQUESTS}
    draft = find_draft_function()
    print(f"Using llm.{draft.__name__}\n")

    records = []
    for req in REQUESTS:
        if req["n"] not in wanted:
            continue
        print(f"{req['n']:>2}. {req['text']}")
        record = run_one(req, draft, api_key)
        print(f"    {record['score']}\n")
        records.append(record)

    out = write_report(records, provider)
    passed = sum(r["score"].startswith(("Correct", "One edit away")) for r in records)
    print(f"{passed}/{len(records)} correct or one edit away by automatic check. Details: {out}")


if __name__ == "__main__":
    main()