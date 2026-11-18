"""PostgreSQL data access (psycopg2, DB-API style).

Each project lives in its own Postgres schema with identical tables:
  live – real Playwright runs against the target site
  demo – synthetic 90-day history
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

from config import DB_CONFIG, TARGET_HOST

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
PROJECTS = {"live": f"{TARGET_HOST} (live)", "demo": "Demo (synthetic)"}

# Insert order respects foreign keys; truncate uses the reverse.
TABLES = ["features", "environments", "requirements", "use_cases", "use_case_steps", "test_cases",
          "test_runs", "test_results", "api_endpoints", "api_metrics", "code_changes"]


def connect():
    return psycopg2.connect(**DB_CONFIG)


def check_connection() -> tuple:
    """Returns (ok, message)."""
    try:
        conn = connect()
        with conn.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0].split(",")[0]
        conn.close()
        return True, version
    except psycopg2.Error as err:
        return False, str(err).strip().splitlines()[0]


def use_schema(cursor, schema: str) -> None:
    if schema not in PROJECTS:
        raise ValueError(f"unknown project schema {schema!r}")
    cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
    cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))


def create_schema(conn, schema: str) -> None:
    with conn.cursor() as cursor:
        use_schema(cursor, schema)
        cursor.execute(SCHEMA_FILE.read_text())
    conn.commit()


def run_count(conn, schema: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (f"{schema}.test_runs",))
        if cursor.fetchone()[0] is None:
            return 0
        cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}.test_runs").format(sql.Identifier(schema)))
        return cursor.fetchone()[0]


def archive_schema(conn, schema: str):
    """Rename a project schema to <schema>_archive_<timestamp> (nothing is deleted) and create an
    empty one in its place. Used when the live project switches to a different site under test.
    Returns the archive name, or None when the schema did not exist."""
    if schema not in PROJECTS:
        raise ValueError(f"unknown project schema {schema!r}")
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
        if cursor.fetchone() is None:
            archive = None
        else:
            archive = f"{schema}_archive_{datetime.now():%Y%m%d_%H%M%S}"
            cursor.execute(sql.SQL("ALTER SCHEMA {} RENAME TO {}").format(sql.Identifier(schema),
                                                                          sql.Identifier(archive)))
    conn.commit()
    create_schema(conn, schema)
    return archive


def latest_run_marker(conn, schema: str):
    """Cheap change detector used by the dashboard's auto-refresh."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (f"{schema}.test_runs",))
        if cursor.fetchone()[0] is None:
            return None
        cursor.execute(sql.SQL("SELECT MAX(id), COUNT(*) FROM {}.test_runs").format(sql.Identifier(schema)))
        return cursor.fetchone()


def save_all(conn, data: dict, schema: str = "demo") -> dict:
    """Replace ALL data in one project schema (used for the synthetic demo)."""
    create_schema(conn, schema)
    counts = {}
    with conn.cursor() as cursor:
        use_schema(cursor, schema)
        cursor.execute("TRUNCATE " + ", ".join(reversed(TABLES)) + " RESTART IDENTITY CASCADE")
        for table in TABLES:
            df = data[table]
            cols = list(df.columns)
            rows = [tuple(_py(v) for v in row) for row in df.itertuples(index=False, name=None)]
            query = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s"
            execute_values(cursor, query, rows, page_size=5000)
            counts[table] = len(rows)
            # explicit ids were inserted → move the identity sequence past them
            cursor.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                           f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")
    conn.commit()
    return counts


def load_all(conn, schema: str) -> dict:
    data = {}
    with conn.cursor() as cursor:
        use_schema(cursor, schema)
        for table in TABLES:
            cursor.execute(f"SELECT * FROM {table} ORDER BY id")
            cols = [d[0] for d in cursor.description]
            data[table] = pd.DataFrame(cursor.fetchall(), columns=cols)
    for table, col in [("test_runs", "started_at"), ("api_metrics", "measured_at"),
                       ("code_changes", "changed_at")]:
        data[table][col] = pd.to_datetime(data[table][col])
    data["test_cases"]["automated"] = data["test_cases"]["automated"].astype(bool)
    data["test_cases"]["requirement_no"] = data["test_cases"]["requirement_no"].astype("Int64")
    for table, col in [("test_results", "duration_ms"), ("api_metrics", "latency_ms"),
                       ("test_runs", "duration_ms")]:
        data[table][col] = pd.to_numeric(data[table][col], errors="coerce").astype(float)
    return data


def _py(value):
    """numpy/pandas scalars → plain Python for psycopg2."""
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        return value.item()
    return value
