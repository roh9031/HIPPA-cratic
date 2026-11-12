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
