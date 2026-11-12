"""DuckDB views over the raw files, for writing independent SQL answer keys.

Used by tests/test_answer_key.py and scripts/sql.py. None of the engine's code is involved, so a SQL
answer here is a genuinely independent check on the engine.

Views (one per file, keys renamed to sample_id / patient_id):
  samples   sample_manifest.csv   one row per sample (the cohort base)
  slides    slide_manifest.csv    one row per slide, several per sample
  survival  raw/survival.tsv      one row per sample; "OS.time" etc. need double quotes
  clinical  raw/clinical.tsv      one row per sample, all columns as text (194 of them)
"""
from __future__ import annotations

from pathlib import Path

from . import data


def connect(ddir: str | None = None):
    import duckdb  # only needed for tests and the SQL console

    d = (data.data_dir() if ddir is None else Path(ddir)).as_posix()
    con = duckdb.connect()
    con.sql(f"CREATE VIEW samples  AS SELECT * FROM read_csv('{d}/sample_manifest.csv')")
    con.sql(f"CREATE VIEW slides   AS SELECT * FROM read_csv('{d}/slide_manifest.csv')")
    con.sql(f"CREATE VIEW survival AS SELECT sample AS sample_id, _PATIENT AS patient_id, * "
            f"FROM read_csv('{d}/raw/survival.tsv', delim='\t')")
    # clinical.tsv's own patient_id is a 4-char suffix; the real key is the sample barcode.
    con.sql(f"CREATE VIEW clinical AS SELECT sampleID AS sample_id, left(sampleID, 12) AS patient_id, "
            f"* EXCLUDE (patient_id) FROM read_csv('{d}/raw/clinical.tsv', delim='\t', all_varchar=true)")
    return con


# ---------------------------------------------------------------- "Verify with SQL"
# Translate a step list into one DuckDB query over the views above, run it, and compare with the engine.
# The translation re-states each step's meaning in SQL; pandas, data.py and engine.py are not involved in
# running it, so a bug in the engine's merging, filtering or de-duplication shows up as a mismatch.

def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _cond_sql(c: dict, alias: str = "") -> str:
    col = f"{alias}{_q(c['column'])}"
    op = c["operator"]
    vals = [str(v).strip().lower() for v in (c.get("values") or [])]
    text = f"lower(trim(CAST({col} AS VARCHAR)))"
    if op == "notnull":
        return f"{col} IS NOT NULL"
    if op == "isnull":
        return f"{col} IS NULL"
    if op in ("gt", "ge", "lt", "le"):
        sym = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}[op]
        return f"TRY_CAST({col} AS DOUBLE) {sym} {float(vals[0])!r}"
    lits = ", ".join(_lit(v) for v in vals)
    if op in ("in", "eq"):
        return f"{text} IN ({lits})"
    if op in ("not_in", "ne"):
        return f"{col} IS NOT NULL AND {text} NOT IN ({lits})"
    if op == "startswith":
        return "(" + " OR ".join(f"starts_with(coalesce({text}, ''), {_lit(v)})" for v in vals) + ")"
    if op == "contains":
        return "(" + " OR ".join(f"contains(coalesce({text}, ''), {_lit(v)})" for v in vals) + ")"
    raise ValueError(f"unknown operator {op!r}")


def _where_sql(where, alias="") -> str:
    conds = [_cond_sql(c, alias) for c in where or []]
    return " AND ".join(f"({c})" for c in conds) if conds else "TRUE"


def _columns(con, view: str) -> list[str]:
    return [r[0] for r in con.sql(f"SELECT column_name FROM (DESCRIBE {view})").fetchall()]


def _ctes(steps: list[dict], con) -> str:
    """WITH s0 AS (...), s1 AS (...), ...: one CTE per step, s0 = all samples."""
    from .engine import clean_step, describe

    # _ord remembers the manifest's row order: "collapse to one row per patient" keeps the first row, like the engine.
    ctes = ["s0 AS (  -- all samples (sample_manifest.csv)\n"
            "  SELECT *, row_number() OVER () AS _ord FROM samples\n)"]
    cols = _columns(con, "samples") + ["_ord"]
    for i, raw in enumerate(steps, 1):
        s = clean_step(raw)
        prev, note = f"s{i - 1}", describe(s).replace("\n", " ")
        if s["op"] == "filter":
            body = f"SELECT * FROM {prev} WHERE {_where_sql(s['where'])}"
        elif s["op"] == "collapse":
            key = _q(f"{s.get('level', 'sample')}_id")
            body = f"SELECT * FROM {prev} QUALIFY row_number() OVER (PARTITION BY {key} ORDER BY _ord) = 1"
        else:  # join
            table, on, how = s["table"], s.get("on", "sample_id"), s.get("how", "inner")
            right = f"(SELECT * FROM {table} WHERE {_where_sql(s.get('where'))})"
            if how in ("semi", "anti"):
                neg = "" if how == "semi" else "NOT "
                body = (f"SELECT * FROM {prev} l WHERE {neg}EXISTS "
                        f"(SELECT 1 FROM {right} r WHERE r.{_q(on)} = l.{_q(on)})")
            else:
                # Same column naming as the engine: a right-hand column that clashes becomes <name>__<table>.
                sel = []
                for c in _columns(con, table):
                    if c == on:
                        continue
                    new = f"{c}__{table}" if c in cols else c
                    sel.append(f"r.{_q(c)} AS {_q(new)}")
                    cols.append(new)
                join = "JOIN" if how == "inner" else "LEFT JOIN"
                body = (f"SELECT l.*, {', '.join(sel)}\n  FROM {prev} l {join} {right} r "
                        f"ON r.{_q(on)} = l.{_q(on)}")
        ctes.append(f"s{i} AS (  -- step {i}: {note}\n  {body}\n)")
    return "WITH\n" + ",\n".join(ctes)


def steps_to_sql(steps: list[dict], con) -> str:
    """The cohort as one query: returns the final sample_ids (what cohort_samples.csv should contain)."""
    return _ctes(steps, con) + f"\nSELECT DISTINCT sample_id FROM s{len(steps)} ORDER BY sample_id"


def _counts_sql(steps: list[dict], con) -> str:
    counts = "\nUNION ALL ".join(
        f"SELECT {i} AS step, count(*) AS rows, count(DISTINCT sample_id) AS samples, "
        f"count(DISTINCT patient_id) AS patients FROM s{i}" for i in range(len(steps) + 1))
    return _ctes(steps, con) + "\n" + counts + "\nORDER BY step"


def verify(steps: list[dict], engine_df, results, ddir: str | None = None) -> dict:
    """Run the SQL version and compare it with the engine, step by step and sample by sample."""
    con = connect(ddir)
    try:
        con.sql("SET threads TO 1")  # keeps row_number() OVER () in file order, for patient-level collapse
        sql = steps_to_sql(steps, con)
        ids = {r[0] for r in con.sql(sql).fetchall()}
        counts = con.sql(_counts_sql(steps, con)).fetchall()
    finally:
        con.close()
    eng_ids = set(engine_df["sample_id"])
    by_step = [{"step": r.index, "engine rows": r.rows, "SQL rows": c[1], "engine samples": r.samples,
                "SQL samples": c[2], "match": "✅" if (r.rows, r.samples, r.patients) == tuple(c[1:]) else "❌"}
               for r, c in zip(results, counts)]
    return {"sql": sql, "by_step": by_step, "sql_samples": len(ids), "engine_samples": len(eng_ids),
            "only_engine": sorted(eng_ids - ids), "only_sql": sorted(ids - eng_ids),
            "match": ids == eng_ids and all(b["match"] == "✅" for b in by_step)}
