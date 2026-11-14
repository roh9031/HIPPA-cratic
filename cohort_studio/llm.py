"""Draft cohort steps from a plain-English request with Claude (default) or NVIDIA.

The model only *drafts* the step list. The user edits it, and the deterministic
engine runs it and does every count and check. The model never sees patient rows,
only table and column names plus the allowed values of short categorical columns.

Needs an API key supplied by the user. Never commit one.
- Claude (default): ANTHROPIC_API_KEY, or a key passed in (the app's sidebar field).
- NVIDIA: NVIDIA_API_KEY, used when no Claude key is available (see llm_nvidia.py).
- To choose explicitly, set COHORT_LLM_PROVIDER to "claude" or "nvidia".
"""
from __future__ import annotations

import functools
import json
import os

from . import data, engine

MODEL = "claude-opus-5-5"

_COND = {
    "type": "object",
    "properties": {
        "column": {"type": "string"},
        "operator": {"type": "string", "enum": list(engine.OPERATORS)},
        "values": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["column", "operator", "values"],
    "additionalProperties": False,
}
_WHERE_ITEM = {
    "anyOf": [
        _COND,
        {"type": "object", "properties": {"any": {"type": "array", "items": _COND}},
         "required": ["any"], "additionalProperties": False},
    ]
}

SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": list(engine.OPS)},
                    "where": {"anyOf": [{"type": "array", "items": _WHERE_ITEM}, {"type": "null"}]},
                    "table": {"anyOf": [{"type": "string", "enum": list(data.TABLES)}, {"type": "null"}]},
                    "on": {"anyOf": [{"type": "string", "enum": list(data.KEYS)}, {"type": "null"}]},
                    "how": {"anyOf": [{"type": "string", "enum": list(engine.JOIN_HOW)}, {"type": "null"}]},
                    "allow_cross_sample": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
                    "level": {"anyOf": [{"type": "string", "enum": list(engine.LEVELS)}, {"type": "null"}]},
                },
                "required": ["op", "where", "table", "on", "how", "level"],
                "additionalProperties": False,
            },
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "cannot_answer": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["steps", "assumptions", "cannot_answer"],
    "additionalProperties": False,
}


def _describe_columns(df, max_values=12) -> str:
    lines = []
    for c in df.columns:
        s = df[c]
        vals = s.dropna().unique()
        if len(vals) <= max_values:
            shown = ", ".join(repr(str(v)) for v in sorted(map(str, vals)))
            lines.append(f"  - {c}: one of [{shown}]")
        elif str(s.dtype) in ("int64", "float64"):
            lines.append(f"  - {c}: number ({s.min()} to {s.max()})")
        else:
            lines.append(f"  - {c}: text, e.g. {str(vals[0])!r}")
    return "\n".join(lines)


@functools.lru_cache(maxsize=1)
def schema_context() -> str:
    parts = ["BASE TABLE (every cohort starts here): sample_manifest, one row per sample.\n"
             + _describe_columns(data.load("samples"))]
    for name, meta in data.TABLES.items():
        parts.append(f"JOINABLE TABLE `{name}`: {meta['about']}\n" + _describe_columns(data.load(name)))
    return "\n\n".join(parts)


SYSTEM = """You translate a researcher's cohort request into steps for Cohort Studio, a tool for TCGA-BRCA.

Step types (JSON):
- filter: {"op":"filter","where":[conditions]} keeps rows matching ALL conditions. A filter can only use
  columns already in the cohort: base-table columns, or columns from a table joined in an earlier step.
- join: {"op":"join","table":T,"on":"sample_id"|"patient_id","how":"inner"|"left"|"semi"|"anti",
  "allow_cross_sample":true|false,"where":[conditions on T]}
- collapse: {"op":"collapse","level":"sample"|"patient"}
Condition: {"column":C,"operator":OP,"values":[strings]}. Operators: in, not_in, eq, ne, gt, ge, lt, le,
notnull, isnull (no values), startswith, contains. Use {"any":[condition, condition]} for OR conditions.
Use exact category values listed in the schema below.
Set unused fields to null.

Rules:
- Use the base table's has_* flags for "has RNA / protein / mutation / copy number / survival data".
- For "GENE-mutated" requests, semi-join `mutation` on sample_id with gene = GENE and mutated = true.
  The gene column's example is not an exhaustive list; this matrix reports gene-level presence, not variant details.
- For "not GENE-mutated" / "GENE wild type" requests, first filter has_mutation = True, then anti-join
  `mutation` on sample_id with gene = GENE. Without the filter, never-sequenced samples count as wild type
  (TP53 wild-type primary tumors: 527 correct, 837 without it). State this in assumptions.
- "in" with several values means ANY of them. For "both X and Y" / "all of" on mutation genes or slide kinds,
  use one semi-join per value (TP53 and PIK3CA: 57 samples; one step with gene in [TP53, PIK3CA]: 480).
- Use official gene symbols: HER2 -> ERBB2, p53 -> TP53, PI3K -> PIK3CA, E-cadherin -> CDH1. HER2-positive
  receptor status is a clinical column, not an ERBB2 mutation; say which one you used.
- To filter on a clinical field, first join `clinical` on sample_id, then filter.
- Prefer the main clinical columns: breast_carcinoma_estrogen_receptor_status (ER),
  breast_carcinoma_progesterone_receptor_status (PR), lab_proc_her2_neu_immunohistochemistry_receptor_status
  (HER2), age_at_initial_pathologic_diagnosis (age). Columns ending in `_nature2012` come from a 2012 study that
  covers only part of the samples (ER: 782 of 1,101 primary tumors vs 1,048), so they silently drop ~300 tumors.
  Use them only if the request names that study, and say which column you used.
- HER2 has two tests: IHC (lab_proc_her2_neu_immunohistochemistry_receptor_status) and ISH
  (lab_procedure_her2_neu_in_situ_hybrid_outcome_type). HER2-positive = IHC Positive OR ISH Positive (197 primary
  tumors). HER2-negative = (IHC Negative AND ISH not Positive) OR (IHC not Positive AND ISH Negative), where
  "not Positive" = {"any":[ne Positive, isnull]} because blank or Indeterminate results count as missing.
  Triple-negative = ER Negative, PR Negative, HER2-negative (158 primary tumors).
  Write HER2-negative as these three flat where items, exactly (IHC and ISH = the two column names above):
  {"any":[{"column":IHC,"operator":"ne","values":["Positive"]},{"column":IHC,"operator":"isnull","values":[]}]},
  {"any":[{"column":ISH,"operator":"ne","values":["Positive"]},{"column":ISH,"operator":"isnull","values":[]}]},
  {"any":[{"column":IHC,"operator":"eq","values":["Negative"]},{"column":ISH,"operator":"eq","values":["Negative"]}]}
- For an intentional patient-level existence request (for example, tumors whose patient has a normal
  sample), use a semi-join on patient_id with allow_cross_sample=true. This selects the current samples
  and does not attach the other sample's columns. Never use allow_cross_sample on an inner or left join.
- Translate the request literally. For "with a <slide/record>", use an inner join; do not pre-empt
  duplicates yourself. Cohort Studio checks every join and shows the user where counts inflate.
- Only use columns that exist below. If the data can't express part of the request, say so in
  cannot_answer and draft only the part that can be expressed. Never substitute a stand-in column for the
  missing part: "responded to chemotherapy" has no response column, so don't filter on whether therapy was
  given; draft just the primary-tumor step (or nothing) and explain in cannot_answer.
- List every interpretation choice you made in assumptions (e.g. which column means "stage").
- Never give clinical advice; this is cohort selection for research only. If the request asks who should get
  a treatment, or for a diagnosis, prognosis or risk (e.g. "which patients should get endocrine therapy?"),
  return "steps": [] and explain in cannot_answer that the tool builds research cohorts and can't make that
  decision. Do not draft a "candidate" or "eligible" cohort for it, even with a disclaimer. The user can ask
  for a descriptive cohort instead (e.g. "ER-positive primary tumors").

SCHEMA
"""


PROVIDERS = ("claude", "nvidia")


def provider(api_key: str | None = None) -> str:
    """Which AI drafts the steps: "claude" or "nvidia"."""
    chosen = os.environ.get("COHORT_LLM_PROVIDER", "").strip().lower()
    if chosen in PROVIDERS:
        return chosen
    if _is_nvidia_key(api_key):         # an NVIDIA key pasted into the sidebar box
        return "nvidia"
    if api_key or os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("NVIDIA_API_KEY"):
        return "nvidia"
    return "claude"   # no key at all: the Claude path reports the missing key as before


def _is_nvidia_key(key: str | None) -> bool:
    return (key or "").strip().strip("\"'").startswith("nvapi-")


def _finish(out: dict) -> dict:
    out["steps"] = [engine.clean_step(s) for s in out.get("steps", [])]
    return out


def draft_steps(request: str, api_key: str | None = None) -> dict:
    """Return {"steps": [...], "assumptions": [...], "cannot_answer": str|None}. Raises RuntimeError on failure."""
    chosen = provider(api_key)
    if chosen == "nvidia":
        return _draft_via("llm_nvidia", "NVIDIA", "NVIDIA_API_KEY", SYSTEM + schema_context(), request,
                          api_key if _is_nvidia_key(api_key) else None)
    return _draft_with_claude(request, api_key)


def _draft_with_claude(request: str, api_key: str | None) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=[{"type": "text", "text": SYSTEM + schema_context(), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": request}],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("The Claude (Anthropic) API key was rejected. Check it and try again. "
                           "An NVIDIA key starts with nvapi- and is detected automatically.")
    except anthropic.RateLimitError:
        raise RuntimeError("Rate limited by the API. Wait a moment and retry.")
    except anthropic.APIConnectionError:
        raise RuntimeError("Couldn't reach the Claude API. Check your connection.")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API error {e.status_code}: {e.message}")

    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined this request. Build the steps by hand instead.")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("The draft was cut off. Try a shorter request.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("The model returned something that isn't valid JSON. Try again.")
    return _finish(out)


def _draft_via(module_name: str, label: str, key_name: str, prompt: str, request: str,
              api_key: str | None = None) -> dict:
    """Send the prompt through an OpenAI-compatible backend module and turn failures into clear messages."""
    import importlib
    try:
        backend = importlib.import_module(f".{module_name}", __package__)
    except ImportError:
        raise RuntimeError(f"{module_name}.py is missing from the cohort_studio folder.")
    try:
        out = backend.complete_json(prompt, request, SCHEMA, api_key=api_key)
    except ImportError as e:
        raise RuntimeError(f"A package {label} needs isn't installed ({e.name}). Run: pip install {e.name}")
    except json.JSONDecodeError:
        raise RuntimeError("The model returned something that isn't valid JSON. Try again.")
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            raise RuntimeError(f"The {label} API key was rejected. Check that it is complete and still active "
                               f"on build.nvidia.com, with no extra spaces ({key_name} or the sidebar box).")
        if status == 404:
            raise RuntimeError(f"{label} doesn't know that model. Check the model name ({e}).")
        if status in (413, 429):
            raise RuntimeError(f"{label} rate limit or size limit hit. Wait a minute and retry. ({e})")
        if "Connection" in type(e).__name__ or "Connection" in str(e):
            raise RuntimeError(f"Couldn't reach the {label} API. Check your connection.")
        raise RuntimeError(f"{label} API error{f' {status}' if status else ''}: {e}")
    return _finish(out)