"""Draft cohort steps from a plain-English request with Claude (default), NVIDIA or Groq.

The model only *drafts* the step list. The user edits it, and the deterministic
engine runs it and does every count and check. The model never sees patient rows,
only table and column names plus the allowed values of short categorical columns.

Needs an API key supplied by the user. Never commit one.
- Claude (default): ANTHROPIC_API_KEY, or a key passed in (the app's sidebar field).
- NVIDIA: NVIDIA_API_KEY, used when no Claude key is available (see llm_nvidia.py).
- Groq: GROQ_API_KEY, used when there's no Claude or NVIDIA key (see llm_groq.py).
- To choose explicitly, set COHORT_LLM_PROVIDER to "claude", "nvidia" or "groq".
"""
from __future__ import annotations

import functools
import json
import os
import re

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

SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": list(engine.OPS)},
                    "where": {"anyOf": [{"type": "array", "items": _COND}, {"type": "null"}]},
                    "table": {"anyOf": [{"type": "string", "enum": list(data.TABLES)}, {"type": "null"}]},
                    "on": {"anyOf": [{"type": "string", "enum": list(data.KEYS)}, {"type": "null"}]},
                    "how": {"anyOf": [{"type": "string", "enum": list(engine.JOIN_HOW)}, {"type": "null"}]},
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


# --- Compact schema description for providers with small per-minute token limits (Groq's free plan
# --- allows 8,000 tokens a minute, input and output together). Claude always gets the full version above.

WIDE_TABLE = 40            # tables with more columns than this are trimmed in the compact version
GROQ_PROMPT_BUDGET = 5000  # rough token budget for the whole prompt, leaving room for the model's answer
CORE_WORDS = ("receptor", "her2", "estrogen", "progesterone", "stage", "age", "gender", "histolog",
              "menopaus", "vital", "race", "ethnic", "lymph", "metasta", "tumor", "pathologic", "sample_type")
STOP_WORDS = {"with", "have", "that", "from", "both", "data", "also", "which", "their", "tumors", "tumor",
              "primary", "patients", "patient", "samples", "sample", "slide", "slides", "every", "type"}


def _describe_compact(df, keep) -> str:
    """Like _describe_columns, but text columns get no example value and only `keep` columns get details."""
    lines, others = [], []
    for c in df.columns:
        s = df[c]
        vals = s.dropna().unique()
        if len(vals) == 0 or str(c).startswith("_"):
            continue                      # empty columns and internal "_" columns carry no meaning here
        if not keep(c):
            others.append(str(c))
            continue
        if len(vals) <= 12:
            shown = ", ".join(repr(str(v)) for v in sorted(map(str, vals)))
            lines.append(f"  - {c}: one of [{shown}]")
        elif str(s.dtype) in ("int64", "float64"):
            lines.append(f"  - {c}: number ({s.min()} to {s.max()})")
        else:
            lines.append(f"  - {c}: text")
    return "\n".join(lines), others


def schema_context_compact(request: str, with_other_names: bool = True) -> str:
    """A shorter schema: every small table in full; wide tables (clinical) show details only for columns
    that match common clinical words or words in the request, and list the rest by name."""
    words = {w for w in re.findall(r"[a-z0-9]{4,}", request.lower()) if w not in STOP_WORDS}

    def relevant(col):
        name = str(col).lower()
        return any(w in name for w in CORE_WORDS) or any(w in name for w in words)

    tables = [("BASE TABLE (every cohort starts here): sample_manifest, one row per sample.", data.load("samples"))]
    tables += [(f"JOINABLE TABLE `{n}`: {m['about']}", data.load(n)) for n, m in data.TABLES.items()]
    parts = []
    for title, df in tables:
        wide = len(df.columns) > WIDE_TABLE
        details, others = _describe_compact(df, relevant if wide else (lambda c: True))
        part = title + "\n" + details
        if others and with_other_names:
            part += ("\n  - other columns (values not shown; use only if the request names them): "
                     + ", ".join(others))
        parts.append(part)
    return "\n\n".join(parts)


def _estimate_tokens(text: str) -> int:
    return len(text) // 3   # deliberately pessimistic (about 4 characters per token is typical)


SYSTEM = """You translate a researcher's cohort request into steps for Cohort Studio, a tool for TCGA-BRCA.

Step types (JSON):
- filter: {"op":"filter","where":[conditions]} keeps rows matching ALL conditions. A filter can only use
  columns already in the cohort: base-table columns, or columns from a table joined in an earlier step.
- join: {"op":"join","table":T,"on":"sample_id"|"patient_id","how":"inner"|"left"|"semi"|"anti","where":[conditions on T]}
- collapse: {"op":"collapse","level":"sample"|"patient"}
Condition: {"column":C,"operator":OP,"values":[strings]}. Operators: in, not_in, eq, ne, gt, ge, lt, le,
notnull, isnull (no values), startswith, contains. Use exact values listed in the schema below.
Set unused fields to null.

Rules:
- Use the base table's has_* flags for "has RNA / protein / mutation / copy number / survival data".
- To filter on a clinical field, first join `clinical` on sample_id, then filter.
- Translate the request literally. For "with a <slide/record>", use an inner join; do not pre-empt
  duplicates yourself. Cohort Studio checks every join and shows the user where counts inflate.
- Only use columns that exist below. If the data can't express part of the request, say so in
  cannot_answer and draft the part that can be expressed.
- List every interpretation choice you made in assumptions (e.g. which column means "stage").
- Never give clinical advice; this is cohort selection for research only.

SCHEMA
"""


PROVIDERS = ("claude", "nvidia", "groq")


def provider(api_key: str | None = None) -> str:
    """Which AI drafts the steps: "claude", "nvidia" or "groq"."""
    chosen = os.environ.get("COHORT_LLM_PROVIDER", "").strip().lower()
    if chosen in PROVIDERS:
        return chosen
    if api_key or os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("NVIDIA_API_KEY"):
        return "nvidia"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return "claude"   # no key at all: the Claude path reports the missing key as before


def _finish(out: dict) -> dict:
    out["steps"] = [engine.clean_step(s) for s in out.get("steps", [])]
    return out


def draft_steps(request: str, api_key: str | None = None) -> dict:
    """Return {"steps": [...], "assumptions": [...], "cannot_answer": str|None}. Raises RuntimeError on failure."""
    chosen = provider(api_key)
    if chosen == "groq":
        return _draft_with_groq(request)
    if chosen == "nvidia":
        return _draft_via("llm_nvidia", "NVIDIA", "NVIDIA_API_KEY", SYSTEM + schema_context(), request)
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
        raise RuntimeError("The API key was rejected. Check it and try again.")
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


def _draft_with_groq(request: str) -> dict:
    """Same prompt and schema as the Claude path, through Groq, with the compact schema description
    so the request fits Groq's free-plan limit of 8,000 tokens a minute."""
    prompt = SYSTEM + schema_context_compact(request)
    if _estimate_tokens(prompt) > GROQ_PROMPT_BUDGET:
        prompt = SYSTEM + schema_context_compact(request, with_other_names=False)
    if _estimate_tokens(prompt) > GROQ_PROMPT_BUDGET:
        raise RuntimeError(f"The prompt is about {_estimate_tokens(prompt):,} tokens, too large for Groq's free "
                           f"plan. Use a Claude or NVIDIA key, or lower WIDE_TABLE / trim CORE_WORDS in llm.py.")
    return _draft_via("llm_groq", "Groq", "GROQ_API_KEY", prompt, request)


def _draft_via(module_name: str, label: str, key_name: str, prompt: str, request: str) -> dict:
    """Send the prompt through an OpenAI-compatible backend module and turn failures into clear messages."""
    import importlib
    try:
        backend = importlib.import_module(f".{module_name}", __package__)
    except ImportError:
        raise RuntimeError(f"{module_name}.py is missing from the cohort_studio folder.")
    try:
        out = backend.complete_json(prompt, request, SCHEMA)
    except ImportError as e:
        raise RuntimeError(f"A package {label} needs isn't installed ({e.name}). Run: pip install {e.name}")
    except json.JSONDecodeError:
        raise RuntimeError("The model returned something that isn't valid JSON. Try again.")
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            raise RuntimeError(f"The {label} API key was rejected. Check {key_name} and try again.")
        if status == 404:
            raise RuntimeError(f"{label} doesn't know that model. Check the model name ({e}).")
        if status in (413, 429):
            raise RuntimeError(f"{label} rate limit or size limit hit. Wait a minute and retry. ({e})")
        if "Connection" in type(e).__name__ or "Connection" in str(e):
            raise RuntimeError(f"Couldn't reach the {label} API. Check your connection.")
        raise RuntimeError(f"{label} API error{f' {status}' if status else ''}: {e}")
    return _finish(out)