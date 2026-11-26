"""Load step: create the target schema and insert the mapped tables.

Works with PostgreSQL (MIGRATERIGHT_DB_URL) or the default SQLite file.
The DDL in sql/schema.sql enforces primary keys, so a duplicate partner or
material number would make the load fail loudly instead of slipping through.
"""

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.config import ROOT

SCHEMA_SQL = ROOT / "sql" / "schema.sql"


def run_ddl(engine: Engine, path=SCHEMA_SQL) -> None:
    """Execute every statement in schema.sql (drop + create)."""
    sql = path.read_text(encoding="utf-8")
    # strip '--' comments, then split on ';'
    lines = [line.split("--")[0] for line in sql.splitlines()]
    statements = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def write_table(engine: Engine, table: str, df: pd.DataFrame) -> int:
    """Append a DataFrame into an existing table (column names lower-cased)."""
    if df.empty:
        return 0
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    out.to_sql(table, engine, if_exists="append", index=False)
    return len(out)


def stage_source(engine: Engine, obj: str, raw: pd.DataFrame) -> None:
    """Keep an untouched copy of the legacy extract in the database (src_<object>)."""
    staged = raw.copy()
    staged.columns = [c.lower() for c in staged.columns]
    staged.to_sql(f"src_{obj}", engine, if_exists="replace", index=False)


def load_all(engine: Engine, target_tables: dict, quarantine: pd.DataFrame, merges: pd.DataFrame) -> dict:
    """Insert every target and control table; return rows written per table."""
    written = {}
    for name, df in target_tables.items():
        written[f"tgt_{name.lower()}"] = write_table(engine, f"tgt_{name.lower()}", df)
    written["mig_quarantine"] = write_table(engine, "mig_quarantine", quarantine)
    written["mig_merge_log"] = write_table(engine, "mig_merge_log", merges)
    return written


def read_sql(engine: Engine, query: str) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


def scalar(engine: Engine, query: str):
    with engine.connect() as conn:
        return conn.execute(text(query)).scalar()
