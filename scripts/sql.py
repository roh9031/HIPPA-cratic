"""SQL console over the TCGA-BRCA files (DuckDB). For working out the correct answer to a cohort request.

  python scripts/sql.py                       interactive: type SQL ending with ;   (.tables, .cols <table>, .quit)
  python scripts/sql.py "SELECT count(*) FROM samples"
  python scripts/sql.py --cols clinical receptor     columns of a table whose name contains "receptor"
  python scripts/sql.py -f cohort.sql                run a file, e.g. the cohort.sql from the app's "Verify with SQL"

Tables: samples, slides, survival, clinical. See cohort_studio/sqlcheck.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cohort_studio.sqlcheck import connect  # noqa: E402

TABLES = ("samples", "slides", "survival", "clinical")


def show(con, sql):
    try:
        con.sql(sql).show(max_rows=40, max_width=200)
    except Exception as e:  # show the DuckDB error and keep going
        print(f"error: {e}")


def cols(con, table, like=""):
    q = f"SELECT column_name, column_type FROM (DESCRIBE {table})"
    if like:
        q += f" WHERE lower(column_name) LIKE '%{like.lower()}%'"
    show(con, q)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # DuckDB draws table borders; Windows consoles default to cp1252
    con = connect()
    args = sys.argv[1:]
    if args[:1] == ["--cols"]:
        return cols(con, args[1], args[2] if len(args) > 2 else "")
    if args[:1] == ["-f"]:
        return show(con, Path(args[1]).read_text(encoding="utf-8").strip().rstrip(";"))
    if args:
        return show(con, " ".join(args))
    print(__doc__)
    buf = ""
    while True:
        try:
            line = input("sql> " if not buf else "...> ")
        except EOFError:
            break
        s = line.strip()
        if not buf and s in (".quit", ".exit"):
            break
        if not buf and s == ".tables":
            print(", ".join(TABLES)); continue
        if not buf and s.startswith(".cols"):
            parts = s.split()
            cols(con, parts[1] if len(parts) > 1 else "samples", parts[2] if len(parts) > 2 else ""); continue
        buf += line + "\n"
        if s.endswith(";"):
            show(con, buf.rstrip().rstrip(";"))
            buf = ""


if __name__ == "__main__":
    main()
