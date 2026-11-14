"""Which fix should the user click? (docs/GAPS.md #21)

Every problem comes with several fixes and they are not equally good. On the
patient-level survival trap, "collapse" removes the duplicate rows but leaves another
sample's record attached, and the semi-join only happens to give the right count;
joining on `sample_id` is the real fix. This module picks one fix per step and says why.

It judges a fix by **what it changes**, not by its label, so renaming a label in the
engine can't silently un-recommend it.

If the engine ever marks its own fixes (`fix["recommended"] = True`, with an optional
`fix["why"]`), that wins and the rules here are skipped: B can take this over in
`engine.py` without the UI changing.
"""
from __future__ import annotations

from . import engine

# Said about the fix the user should click, and about the ones they shouldn't.
WHY = {
    "sample_id": "Matching on the sample barcode is what makes each record belong to the sample it "
                 "describes. The other fixes remove the duplicate rows but keep the wrong record.",
    "semi": "Keeps exactly the same samples, one row each: it keeps a sample when a match exists and "
            "never repeats it.",
    "collapse_left": "Keeps one row per sample. (A semi-join isn't offered here: on a left join it would "
                     "silently drop the samples that have no match, which changes the cohort.)",
    "still_cross": "This removes the duplicate rows, but the records still come from a different sample "
                   "of the same patient.",
    "arbitrary_row": "Keeps the joined columns, but which of the repeated rows survives is arbitrary: "
                     "whichever came first in the file.",
}


def _effect(fix: dict, index: int, steps: list[dict]) -> str:
    """What this fix does to the step list: 'collapse', 'on:X', 'how:X', 'where' or 'other'."""
    new = fix.get("steps") or []
    if len(new) == len(steps) + 1:
        return "collapse"
    if len(new) != len(steps) or not 1 <= index <= len(steps):
        return "other"
    after, before = engine.clean_step(new[index - 1]), engine.clean_step(steps[index - 1])
    for field in ("on", "how"):
        if after.get(field) != before.get(field):
            return f"{field}:{after.get(field)}"
    if after.get("where") != before.get("where"):
        return "where"
    return "other"


def advise(result, steps: list[dict]) -> dict[tuple[int, int], tuple[bool, str]]:
    """{(warning index, fix index): (is recommended, what to know about it)}.

    Only problems with a demonstrably right answer get a recommendation. Judgement calls
    (exclude redacted records, collapse to one patient per row) deliberately get none.
    """
    out: dict[tuple[int, int], tuple[bool, str]] = {}
    index = result.index
    if index < 1 or index > len(steps):
        return out
    step = engine.clean_step(steps[index - 1])
    kinds = {w.kind for w in result.warnings}

    for w_i, w in enumerate(result.warnings):
        engine_decided = any(f.get("recommended") for f in w.fixes)
        for f_i, fix in enumerate(w.fixes):
            if engine_decided:                              # the engine ranked these: don't second-guess it
                if fix.get("recommended"):
                    out[(w_i, f_i)] = (True, fix.get("why", ""))
                continue
            effect = _effect(fix, index, steps)
            if "cross_sample" in kinds:
                # The wrong record is attached to the sample. Nothing else fixes that.
                if effect == "on:sample_id":
                    out[(w_i, f_i)] = (True, WHY["sample_id"])
                elif w.kind == "inflation":
                    out[(w_i, f_i)] = (False, WHY["still_cross"])
            elif w.kind == "inflation" and step.get("op") == "join":
                how = step.get("how", "inner")
                if how == "inner" and effect == "how:semi":
                    out[(w_i, f_i)] = (True, WHY["semi"])
                elif how == "left" and effect == "collapse":
                    out[(w_i, f_i)] = (True, WHY["collapse_left"])
                elif how == "inner" and effect == "collapse":
                    out[(w_i, f_i)] = (False, WHY["arbitrary_row"])
    return out


def order(w_i: int, fixes: list[dict], advice: dict[tuple[int, int], tuple[bool, str]]) -> list[int]:
    """Fix indexes with the recommended one first. Indexes stay the engine's, so button keys don't move."""
    return sorted(range(len(fixes)), key=lambda f_i: not advice.get((w_i, f_i), (False, ""))[0])


def warning_order(result, advice: dict[tuple[int, int], tuple[bool, str]]) -> list[int]:
    """Warning indexes with the one holding the recommended fix first.

    A step can raise several problems at once (the survival trap raises three), and the fix
    worth clicking is in the last of them. Putting that box first means the user reads the
    answer before the near-misses that the other boxes offer.
    """
    best = {w_i for (w_i, _), (is_best, _) in advice.items() if is_best}
    return sorted(range(len(result.warnings)), key=lambda w_i: w_i not in best)
