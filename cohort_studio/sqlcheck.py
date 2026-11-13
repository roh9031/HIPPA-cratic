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

import csv
import gzip
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
    mutation_path = _lit(f"{d}/raw/mutation_gene_level.tsv.gz")
    with gzip.open(Path(d) / "raw" / "mutation_gene_level.tsv.gz", "rt", encoding="utf-8", newline="") as f:
        mutation_header = next(csv.reader(f, delimiter="\t"), None)
    if not mutation_header or mutation_header[0] != "sample":
        raise ValueError("mutation_gene_level.tsv.gz must have a first column named 'sample'.")
    sample_columns = mutation_header[1:]
    if not sample_columns or len(sample_columns) != len(set(sample_columns)):
        raise ValueError("mutation_gene_level.tsv.gz has no sample columns.")
    unpivot_columns = ", ".join(_q(column) for column in sample_columns)
    # Explicit column types: letting DuckDB sniff this 792-column gzip made every connect() take ~3.5 s and
    # every mutation query ~8 s. With the types given, connect is instant and a query takes ~2 s.
    column_types = "{" + ", ".join(f"{_lit(c)}: 'VARCHAR'" for c in mutation_header) + "}"
    mutation_source = (
        f"read_csv({mutation_path}, delim='\\t', compression='gzip', header=true, auto_detect=false, "
        f"columns={column_types})"
    )
    con.sql(f"""CREATE VIEW mutation AS
        SELECT sample_id, left(sample_id, 12) AS patient_id, sample AS gene, TRUE AS mutated
        FROM {mutation_source}
        UNPIVOT (mutation_value FOR sample_id IN ({unpivot_columns}))
        WHERE trim(mutation_value) = '1'
          AND sample_id IN (SELECT sample_id FROM samples)""")
    return con


# ---------------------------------------------------------------- "Verify with SQL"
# Translate a step list into one DuckDB query over the views above, run it, and compare with the engine.
# The translation re-states each step's meaning in SQL; pandas, data.py and engine.py are not involved in
# running it, so a bug in the engine's merging, filtering or de-duplication shows up as a mismatch.

def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _is_number(v) -> bool:
    try:
        float(v)
        return str(v).strip().lower() not in ("nan", "inf", "-inf", "infinity", "-infinity")
    except ValueError:
        return False


def _cond_sql(c: dict, alias: str = "") -> str:
    col = f"{alias}{_q(c['column'])}"
    op = c["operator"]
    vals = [str(v).strip().lower() for v in (c.get("values") or [])]
    raw = f"lower(trim(CAST({col} AS VARCHAR)))"
    # Coded unknowns (`Indeterminate`, `[Discrepancy]`, `[Not Available]`...) count as missing (GAPS.md #7).
    unknown = f"coalesce({raw} = 'indeterminate' OR ({raw} LIKE '[%' AND {raw} LIKE '%]'), FALSE)"
    known = f"({col} IS NOT NULL AND NOT {unknown})"
    text = f"CASE WHEN {unknown} THEN NULL ELSE {raw} END"
    if op == "notnull":
        return known
    if op == "isnull":
        return f"NOT {known}"
    if op in ("gt", "ge", "lt", "le"):
        sym = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}[op]
        return f"TRY_CAST({col} AS DOUBLE) {sym} {float(vals[0])!r}"
    lits = ", ".join(_lit(v) for v in vals)
    if op in ("in", "eq", "not_in", "ne"):
        match = f"{text} IN ({lits})"
        nums = [repr(float(v)) for v in vals if _is_number(v)]
        if nums:  # numbers match by value too (40 = 40.0), same as the engine
            match = f"({match} OR TRY_CAST({text} AS DOUBLE) IN ({', '.join(nums)}))"
        return f"coalesce({match}, FALSE)" if op in ("in", "eq") else f"{known} AND NOT coalesce({match}, FALSE)"
    if op == "startswith":
        return "(" + " OR ".join(f"starts_with(coalesce({text}, ''), {_lit(v)})" for v in vals) + ")"
    if op == "contains":
        return "(" + " OR ".join(f"contains(coalesce({text}, ''), {_lit(v)})" for v in vals) + ")"
    raise ValueError(f"unknown operator {op!r}")


def _item_sql(item: dict, alias: str = "") -> str:
    """One entry of a `where` list: a condition, or an OR group {"any": [conditions]} (GAPS.md #16)."""
    if "any" in item:
        parts = [_item_sql(c, alias) for c in item["any"] or []]
        return "(" + " OR ".join(f"({p})" for p in parts) + ")" if parts else "FALSE"
    if "all" in item:
        parts = [_item_sql(c, alias) for c in item["all"] or []]
        return "(" + " AND ".join(f"({p})" for p in parts) + ")" if parts else "TRUE"
    return _cond_sql(item, alias)


def _where_sql(where, alias="") -> str:
    conds = [_item_sql(c, alias) for c in where or []]
    return " AND ".join(f"({c})" for c in conds) if conds else "TRUE"


def _columns_in(where) -> list[str]:
    """Every column a `where` list mentions, including inside OR groups, without repeats."""
    out = []
    for c in where or []:
        out += _columns_in(c["any"]) if "any" in c else _columns_in(c["all"]) if "all" in c else [c["column"]]
    return list(dict.fromkeys(out))


def _describe(step: dict) -> str:
    """The engine's plain-words label, or a fallback if the engine can't describe it yet (e.g. OR groups)."""
    from .engine import describe
    try:
        return describe(step)
    except (KeyError, TypeError):
        return f"{step.get('op')} {step.get('table', '')}".strip()


def _columns(con, view: str) -> list[str]:
    return [r[0] for r in con.sql(f"SELECT column_name FROM (DESCRIBE {view})").fetchall()]


def _ctes(steps: list[dict], con) -> str:
    """WITH s0 AS (...), s1 AS (...), ...: one CTE per step, s0 = all samples."""
    from .engine import clean_step

    # _ord remembers the manifest's row order: "collapse to one row per patient" keeps the first row, like the engine.
    ctes = ["s0 AS (  -- all samples (sample_manifest.csv)\n"
            "  SELECT *, row_number() OVER () AS _ord FROM samples\n)"]
    cols = _columns(con, "samples") + ["_ord"]
    for i, raw in enumerate(steps, 1):
        s = clean_step(raw)
        prev, note = f"s{i - 1}", _describe(s).replace("\n", " ")
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


# ---------------------------------------------------------------- "Why isn't sample X in my cohort?"

def trace(steps: list[dict], sample_id: str, ddir: str | None = None) -> dict:
    """Follow one sample through the steps (in SQL) and explain the step that removed it, with the values involved."""
    from .engine import clean_step

    sid = sample_id.strip().upper()
    con = connect(ddir)
    try:
        con.sql("SET threads TO 1")
        base = _ctes(steps, con)
        counts = con.sql(base + "\n" + "\nUNION ALL ".join(
            f"SELECT {i}, count(*) FROM s{i} WHERE sample_id = {_lit(sid)}" for i in range(len(steps) + 1))
            + "\nORDER BY 1").fetchall()
        path = [{"step": i, "rows for this sample": n} for i, n in counts]
        if counts[0][1] == 0:
            in_slides = con.sql(f"SELECT count(*) FROM slides WHERE sample_id = {_lit(sid)}").fetchall()[0][0]
            why = f"`{sid}` isn't in sample_manifest.csv, so no cohort can include it."
            if in_slides:
                why += (f" It does have {in_slides} slide(s) in slide_manifest.csv: one of the samples missing from "
                        f"the manifest (see docs/GAPS.md #19).")
            return {"sample_id": sid, "status": "not_in_manifest", "why": why, "path": path, "details": []}
        gone = next((i for i, n in counts if n == 0), None)
        if gone is None:
            return {"sample_id": sid, "status": "in_cohort", "path": path, "details": [],
                    "why": f"`{sid}` is in the final cohort ({counts[-1][1]} row(s) in the final table)."}

        s = clean_step(steps[gone - 1])
        prev = f"s{gone - 1}"
        why = f"`{sid}` was removed at **step {gone}: {_describe(s)}**."
        details = []
        if s["op"] == "filter":
            cols = ", ".join(_q(c) for c in _columns_in(s["where"]))
            details = _records(con, base + f"\nSELECT sample_id, {cols} FROM {prev} WHERE sample_id = {_lit(sid)}")
            why += " Its values for the condition columns are shown below; blank means missing."
        elif s["op"] == "collapse":
            key = f"{s.get('level', 'sample')}_id"
            kept = con.sql(base + f"\nSELECT sample_id FROM s{gone} WHERE {_q(key)} = "
                                  f"(SELECT {_q(key)} FROM {prev} WHERE sample_id = {_lit(sid)} LIMIT 1)").fetchall()
            why += f" Another sample of the same {s.get('level')} was kept instead: {', '.join(r[0] for r in kept)}."
        else:
            table, on, how = s["table"], s.get("on", "sample_id"), s.get("how", "inner")
            key = con.sql(base + f"\nSELECT {_q(on)} FROM {prev} WHERE sample_id = {_lit(sid)} LIMIT 1").fetchall()[0][0]
            cols = ["sample_id"] + [c for c in _columns_in(s.get("where")) if c != "sample_id"]
            allrec = _records(con, f"SELECT {', '.join(_q(c) for c in dict.fromkeys(cols))} FROM {table} "
                                   f"WHERE {_q(on)} = {_lit(key)}")
            ok = con.sql(f"SELECT count(*) FROM {table} WHERE {_q(on)} = {_lit(key)} "
                         f"AND {_where_sql(s.get('where'))}").fetchall()[0][0]
            if how == "anti":
                why += f" It has {ok} matching {table} record(s), and this step drops samples that do."
            elif not allrec:
                why += f" There is no {table} record for it at all (matching on {on})."
            else:
                why += (f" It has {len(allrec)} {table} record(s), but none meets the step's conditions. "
                        f"They're shown below.")
            details = allrec
    finally:
        con.close()
    return {"sample_id": sid, "status": "removed", "removed_at": gone, "why": why, "path": path, "details": details}


def _records(con, sql: str) -> list[dict]:
    rel = con.sql(sql)
    return [dict(zip(rel.columns, row)) for row in rel.fetchall()]


# ---------------------------------------------------------------- Data notes: where the source files disagree

_PAM50 = "CASE PAM50Call_RNAseq WHEN 'LumA' THEN 'Luminal A' WHEN 'LumB' THEN 'Luminal B' WHEN 'Her2' THEN 'HER2-enriched' " \
         "WHEN 'Basal' THEN 'Basal-like' WHEN 'Normal' THEN 'Normal-like' END"


def data_notes(ddir: str | None = None) -> list[dict]:
    """Facts about the frozen files a researcher should know, computed live. Each: title, detail, examples."""
    con = connect(ddir)
    try:
        def one(sql):
            return con.sql(sql).fetchall()[0]

        def ids(sql):
            return [r[0] for r in con.sql(sql + " ORDER BY 1 LIMIT 5").fetchall()]

        notes = []
        n, k = one("SELECT count(DISTINCT sample_id), count(*) FROM slides WHERE sample_id NOT IN (SELECT sample_id FROM samples)")
        notes.append({
            "title": f"{n} samples have slides but aren't in the sample manifest",
            "detail": f"slide_manifest.csv lists {k} slides for {n} samples (normal tissue, barcode -11) that "
                      f"sample_manifest.csv doesn't have. The sample manifest is the official list of samples, so "
                      f"these are left out of every cohort (organizers' rule). Type one into \"Why isn't a sample in "
                      f"my cohort?\" to see it explained.",
            "examples": ids("SELECT DISTINCT sample_id FROM slides WHERE sample_id NOT IN (SELECT sample_id FROM samples)")})
        n, t = one("SELECT count(*), count(*) FILTER (WHERE s.sample_type = 'Primary Tumor') FROM survival v "
                   "JOIN samples s USING (sample_id) WHERE v.Redaction IS NOT NULL")
        notes.append({
            "title": f"{n} survival records are marked redacted but still have values",
            "detail": f"{t} of them are primary tumors. The sample manifest marks them as having survival data, so "
                      f"they are kept (organizers' rule), and the tool shows a note whenever they enter a cohort.",
            "examples": ids("SELECT sample_id FROM survival WHERE Redaction IS NOT NULL")})
        n = one("SELECT count(*) FROM clinical c JOIN survival v USING (sample_id) "
                "WHERE (c.vital_status = 'DECEASED' AND v.OS = 0) OR (c.vital_status = 'LIVING' AND v.OS = 1)")[0]
        notes.append({
            "title": f"Vital status and overall survival disagree for {n} sample(s)",
            "detail": "clinical.tsv `vital_status` vs survival.tsv `OS`. \"Patients who died\" depends on which one "
                      "you use; our answer keys use `OS = 1` from the curated survival table.",
            "examples": ids("SELECT sample_id FROM clinical c JOIN survival v USING (sample_id) WHERE "
                            "(c.vital_status = 'DECEASED' AND v.OS = 0) OR (c.vital_status = 'LIVING' AND v.OS = 1)")})
        n = one(f"SELECT count(*) FROM clinical WHERE PAM50Call_RNAseq IS NOT NULL AND PAM50_mRNA_nature2012 IS NOT NULL "
                f"AND {_PAM50} IS DISTINCT FROM PAM50_mRNA_nature2012")[0]
        notes.append({
            "title": f"Two PAM50 subtype columns disagree for {n} samples",
            "detail": "`PAM50Call_RNAseq` vs `PAM50_mRNA_nature2012` (where both have a call). Say which column a "
                      "subtype cohort uses.",
            "examples": ids(f"SELECT sample_id FROM clinical WHERE PAM50Call_RNAseq IS NOT NULL AND "
                            f"PAM50_mRNA_nature2012 IS NOT NULL AND {_PAM50} IS DISTINCT FROM PAM50_mRNA_nature2012")})
        n = one("SELECT count(*) FROM clinical WHERE gender IS NOT NULL AND Gender_nature2012 IS NOT NULL "
                "AND gender <> Gender_nature2012")[0]
        notes.append({
            "title": f"Two gender columns disagree for {n} sample(s)",
            "detail": "`gender` vs `Gender_nature2012`.",
            "examples": ids("SELECT sample_id FROM clinical WHERE gender <> Gender_nature2012")})
    finally:
        con.close()
    return notes
