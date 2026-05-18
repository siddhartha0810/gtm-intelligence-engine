"""
pg_connector.py
===============
PostgreSQL input/output adapter for the lead enrichment pipeline.

Set PG_CONNECTION_STRING in .env to enable Postgres support.
If set and no explicit input file is given, the pipeline reads leads from
PG_INPUT_TABLE and writes enriched results to PG_OUTPUT_TABLE (in addition
to the usual output CSV).

Connection string format:
  postgresql://user:password@host:5432/dbname

Required input table columns : first_name, last_name, company
Optional input table columns : email, linkedin_url  (pre-populated leads)
"""

from typing import Optional

import pandas as pd


def _engine(connection_string: str):
    """Create a SQLAlchemy engine. Raises ImportError if dependencies are missing."""
    try:
        from sqlalchemy import create_engine
    except ImportError:
        raise ImportError(
            "sqlalchemy and psycopg2-binary are required for PostgreSQL support.\n"
            "Install them with:  pip install sqlalchemy psycopg2-binary"
        )
    return create_engine(connection_string, future=True)


def load_leads(connection_string: str, table: str) -> Optional[pd.DataFrame]:
    """
    Read leads from a Postgres table and return a DataFrame.
    Returns None if the table is empty or does not exist.

    The table must have at minimum: first_name, last_name, company.
    Any extra columns (email, linkedin_url, etc.) are passed through to the pipeline.
    """
    engine = _engine(connection_string)
    try:
        df = pd.read_sql(f'SELECT * FROM "{table}"', engine)
    except Exception as exc:
        raise RuntimeError(
            f"Could not read from Postgres table '{table}'.\n"
            f"  Check PG_CONNECTION_STRING and that the table exists.\n"
            f"  Error: {exc}"
        ) from exc
    finally:
        engine.dispose()

    return df if not df.empty else None


def save_results(df: pd.DataFrame, connection_string: str, table: str) -> int:
    """
    Write enriched results to a Postgres table using upsert — never deletes rows.

    Creates the table on first run; on subsequent runs inserts new rows and
    updates existing ones (matched by lead_id) without touching unrelated rows.
    Returns the number of rows written.
    """
    from sqlalchemy import text

    engine = _engine(connection_string)
    try:
        with engine.begin() as conn:
            cols = list(df.columns)
            tmp  = f"_stg_{table}"

            # Write to a disposable staging table (replace is fine here — it's temporary)
            df.to_sql(tmp, conn, if_exists="replace", index=False, method="multi")

            # Ensure main table exists with lead_id as primary key
            col_defs = ", ".join(
                f'"{c}" TEXT{"  PRIMARY KEY" if c == "lead_id" else ""}'
                for c in cols
            )
            conn.execute(text(f'CREATE TABLE IF NOT EXISTS "{table}" ({col_defs})'))

            col_sql = ", ".join(f'"{c}"' for c in cols)
            if "lead_id" in cols:
                update_set = ", ".join(
                    f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "lead_id"
                )
                conn.execute(text(
                    f'INSERT INTO "{table}" ({col_sql}) '
                    f'SELECT {col_sql} FROM "{tmp}" '
                    f'ON CONFLICT (lead_id) DO UPDATE SET {update_set}'
                ))
            else:
                # No lead_id — plain append (no dedup possible)
                conn.execute(text(
                    f'INSERT INTO "{table}" ({col_sql}) SELECT {col_sql} FROM "{tmp}"'
                ))

            conn.execute(text(f'DROP TABLE IF EXISTS "{tmp}"'))
    except Exception as exc:
        raise RuntimeError(
            f"Could not write to Postgres table '{table}'.\n"
            f"  Check PG_CONNECTION_STRING and database permissions.\n"
            f"  Error: {exc}"
        ) from exc
    finally:
        engine.dispose()

    return len(df)
