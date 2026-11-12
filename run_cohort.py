"""Command-line Cohort Studio: run a cohort definition and write cohort_samples.csv.

  python run_cohort.py examples/demo_diagnostic_slides.json
  python run_cohort.py my_cohort.json --out cohort_samples.csv
  python run_cohort.py --ask "primary tumors with a diagnostic slide"   (needs ANTHROPIC_API_KEY)

Exit code 2 means the cohort still has an unresolved problem (duplicates or cross-sample links).
"""
import argparse, json, sys

from cohort_studio.engine import run, unresolved_problems
from cohort_studio.export import cohort_samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("definition", nargs="?", help="JSON file: a list of steps, or {request, steps}")
    ap.add_argument("--ask", help="Plain-English request; drafts steps with Claude (review them!)")
    ap.add_argument("--out", default="cohort_samples.csv")
    a = ap.parse_args()

    request = ""
    if a.ask:
        from cohort_studio.llm import draft_steps
        draft = draft_steps(a.ask)
        request, steps = a.ask, draft["steps"]
        print("Drafted steps (review before trusting):\n" + json.dumps(steps, indent=2))
        for note in draft.get("assumptions", []):
            print("  assumption:", note)
        if draft.get("cannot_answer"):
            print("  CANNOT ANSWER:", draft["cannot_answer"])
    elif a.definition:
        spec = json.load(open(a.definition))
        steps = spec["steps"] if isinstance(spec, dict) else spec
        request = spec.get("request", "") if isinstance(spec, dict) else ""
    else:
        ap.error("give a definition file or --ask")

    df, results = run(steps)
    if request:
        print(f"Request: {request}")
    for r in results:
        flag = "  <-- INFLATED" if any(w.kind == "inflation" for w in r.warnings) else ""
        print(f"{r.index:>2}  {r.label[:70]:<70} rows={r.rows:>5} samples={r.samples:>5} patients={r.patients:>5}{flag}")
        if r.error:
            print("      ERROR:", r.error)
        for w in r.warnings:
            print(f"      [{w.severity}] {w.message}")
            for f in w.fixes:
                print(f"         fix: {f['label']}")
    problems = unresolved_problems(results)
    out = cohort_samples(df)
    out.to_csv(a.out, index=False)
    print(f"\nwrote {a.out}: {len(out)} unique samples")
    for p in problems:
        print("UNRESOLVED:", p)
    sys.exit(2 if problems else 0)


if __name__ == "__main__":
    main()
