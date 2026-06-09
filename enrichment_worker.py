"""
enrichment_worker.py
====================
Subprocess for the Apollo contact enrichment pipeline.
Mirrors the design of scan_worker.py — runs isolated so it never
blocks the FastAPI event loop.

Called by unified_app.py:
  python enrichment_worker.py
      --limit         50
      --max-per-company  10
      --status-file   /tmp/enrich_status.json
      --log-file      /tmp/enrich_log.txt

Status file is updated every 1.5 s; log file is appended line-by-line.
Parent reads both to serve /api/enrich/status and /api/enrich/log.
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

BASE_DIR   = Path(__file__).parent
ORACLE_DIR = BASE_DIR / "oracle_intent_engine"
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

# Load oracle .env
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ORACLE_DIR / ".env")

# Set ORACLE_PG_DSN so database.py connects to Inoapps-Data-DB
_dotenv_path = ORACLE_DIR / ".env"
_oracle_env: dict = {}
if _dotenv_path.exists():
    for _line in _dotenv_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _oracle_env[_k.strip()] = _v.strip()

os.environ["ORACLE_PG_DSN"] = (
    f"host={_oracle_env.get('DB_HOST', '10.0.0.149')} "
    f"port={_oracle_env.get('DB_PORT', '5432')} "
    f"dbname={_oracle_env.get('DB_NAME', 'Inoapps-Data-DB')} "
    f"user={_oracle_env.get('DB_USER', 'postgres')} "
    f"password={_oracle_env.get('DB_PASSWORD', '')}"
)

from src import database as db          # noqa: E402
from src import apollo_enrichment       # noqa: E402


def _status_writer(status_path: Path, stop_evt: threading.Event) -> None:
    while not stop_evt.is_set():
        try:
            status_path.write_text(
                json.dumps(apollo_enrichment.current_status()),
                encoding="utf-8",
            )
        except Exception:
            pass
        stop_evt.wait(1.5)


def _make_file_log(log_path: Path):
    def _patched(message: str) -> None:
        print(message, flush=True)
        try:
            ts    = datetime.now().strftime("%H:%M:%S")
            upper = message.upper()
            if "ERROR" in upper or message.startswith("✗"):
                level = "ERROR"
            elif "WARN" in upper:
                level = "WARN"
            else:
                level = "INFO"
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{ts}] [{level}] {message}\n")
        except Exception:
            pass
    return _patched


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrichment worker")
    parser.add_argument("--limit",           type=int, default=50,
                        help="Max companies to enrich per run")
    parser.add_argument("--max-per-company", type=int, default=10,
                        help="Max contacts per company from Apollo")
    parser.add_argument("--batch-size",      type=int, default=None,
                        help="Process in sub-batches of this size with a pause between")
    parser.add_argument("--role-filters",    type=str, default=None,
                        help="JSON array of job title strings to filter Apollo results")
    parser.add_argument("--status-file",     required=True)
    parser.add_argument("--log-file",        required=True)
    args = parser.parse_args()

    role_filters = None
    if args.role_filters:
        try:
            role_filters = json.loads(args.role_filters)
        except Exception:
            role_filters = None

    status_path = Path(args.status_file)
    log_path    = Path(args.log_file)
    log_path.write_text("", encoding="utf-8")

    # Seed status immediately
    status_path.write_text(
        json.dumps({
            "status": "running",
            "progress": "Starting...",
            "companies_processed": 0,
            "companies_total": 0,
            "contacts_found": 0,
            "contacts_validated": 0,
        }),
        encoding="utf-8",
    )

    log_fn = _make_file_log(log_path)

    stop_evt  = threading.Event()
    sw_thread = threading.Thread(
        target=_status_writer, args=(status_path, stop_evt), daemon=True
    )
    sw_thread.start()

    try:
        db.init_db()
    except Exception as exc:
        print(f"[enrichment_worker] DB init error: {exc}", file=sys.stderr)

    # Read API keys from environment (set by unified_app.py before launching subprocess)
    apollo_key     = os.environ.get("APOLLO_API_KEY", "").strip()
    zerobounce_key = os.environ.get("ZEROBOUNCE_API_KEY", "").strip()

    result = apollo_enrichment.enrich_companies(
        apollo_key=apollo_key,
        zerobounce_key=zerobounce_key,
        limit=args.limit,
        max_per_company=args.max_per_company,
        log=log_fn,
        role_filters=role_filters,
        batch_size=args.batch_size,
    )

    stop_evt.set()
    try:
        status_path.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass

    had_error = result.get("status") == "error"
    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()
