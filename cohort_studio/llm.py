"""Draft cohort steps from a plain-English request with Claude.

The model only *drafts* the step list. The user edits it, and the deterministic
engine runs it and does every count and check. The model never sees patient rows,
only table and column names plus the allowed values of short categorical columns.

Needs an API key supplied by the user (ANTHROPIC_API_KEY or passed in). Never commit one.
"""
from __future__ import annotations

import functools
import json

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
- To filter on a clinical field, first join `clinical` on sample_id, then filter.
- For an intentional patient-level existence request (for example, tumors whose patient has a normal
  sample), use a semi-join on patient_id with allow_cross_sample=true. This selects the current samples
  and does not attach the other sample's columns. Never use allow_cross_sample on an inner or left join.
- Translate the request literally. For "with a <slide/record>", use an inner join; do not pre-empt
  duplicates yourself. Cohort Studio checks every join and shows the user where counts inflate.
- Only use columns that exist below. If the data can't express part of the request, say so in
  cannot_answer and draft the part that can be expressed.
- List every interpretation choice you made in assumptions (e.g. which column means "stage").
- Never give clinical advice; this is cohort selection for research only.

SCHEMA
"""


def draft_steps(request: str, api_key: str | None = None) -> dict:
    """Return {"steps": [...], "assumptions": [...], "cannot_answer": str|None}. Raises RuntimeError on failure."""
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
    out["steps"] = [engine.clean_step(s) for s in out.get("steps", [])]
    return out
