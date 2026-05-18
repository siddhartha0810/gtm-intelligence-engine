"""
scan_worker.py
==============
Runs the Oracle Intent Engine scan as a completely isolated subprocess
so it never blocks the FastAPI event loop or competes for the GIL.

Called by unified_app.py:
  python scan_worker.py --sources linkedin indeed news \
                        --max-pages 3 \
                        --status-file /tmp/scan_status.json \
                        --log-file    /tmp/scan_log.txt

Status file is updated every ~1.5 s; log file is appended line-by-line.
Parent process reads both files to serve /scan/status and /scan/log.
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

# Load oracle .env before any src imports
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ORACLE_DIR / ".env")

# Explicitly set ORACLE_PG_DSN so database.py always connects to oracle_intent,
# never to the enrichment DB even if PG_MASTER_CONNECTION_STRING is in env.
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
    f"dbname={_oracle_env.get('DB_NAME', 'oracle_intent')} "
    f"user={_oracle_env.get('DB_USER', 'postgres')} "
    f"password={_oracle_env.get('DB_PASSWORD', '')}"
)

from src import database as db    # noqa: E402
from src import pipeline           # noqa: E402


def _status_writer(status_path: Path, stop_evt: threading.Event) -> None:
    """Background thread: flush current_status() to file every 1.5 s."""
    while not stop_evt.is_set():
        try:
            status_path.write_text(
                json.dumps(pipeline.current_status()), encoding="utf-8"
            )
        except Exception:
            pass
        stop_evt.wait(1.5)


def _make_file_log(log_path: Path):
    """Return a drop-in replacement for pipeline._log that also writes to file."""
    _original = pipeline._log

    def _patched(message: str) -> None:
        _original(message)
        try:
            ts    = datetime.now().strftime("%H:%M:%S")
            upper = message.upper()
            if message.startswith("✗") or "ERROR" in upper:
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
    parser = argparse.ArgumentParser(description="Oracle scan worker")
    parser.add_argument("--sources",          nargs="+", default=None,
                        help="Signal source IDs to enable")
    parser.add_argument("--max-pages",        type=int,  default=None,
                        help="Max pages per query per source")
    parser.add_argument("--location",         default="",
                        help="Geographic filter (optional)")
    parser.add_argument("--status-file",      required=True,
                        help="Path to JSON file for live status updates")
    parser.add_argument("--log-file",         required=True,
                        help="Path to text file for log lines")
    parser.add_argument("--jde-manufacturing", action="store_true",
                        help="Use JDE manufacturing-focused queries + LinkedIn industry filter")
    args = parser.parse_args()

    status_path = Path(args.status_file)
    log_path    = Path(args.log_file)
    log_path.write_text("", encoding="utf-8")  # clear on start

    # Seed status file immediately so parent never reads stale data
    status_path.write_text(
        json.dumps({
            "status": "running", "progress": "Starting...",
            "run_id": None, "raw_signals": 0, "companies_found": 0,
        }),
        encoding="utf-8",
    )

    # Patch pipeline logger to also write to the log file
    pipeline._log = _make_file_log(log_path)  # type: ignore[assignment]

    # Start background status writer
    stop_evt = threading.Event()
    sw_thread = threading.Thread(
        target=_status_writer, args=(status_path, stop_evt), daemon=True
    )
    sw_thread.start()

    # Ensure schema exists (idempotent)
    try:
        db.init_db()
    except Exception as exc:
        print(f"[scan_worker] DB init error: {exc}", file=sys.stderr)

    # Run the scan synchronously — this is the only thread doing CPU/network work
    result = pipeline.run_scan(
        sources=args.sources,
        max_pages=args.max_pages,
        location=args.location,
        jde_manufacturing_focus=args.jde_manufacturing,
    )

    # Flush final status
    stop_evt.set()
    try:
        final = pipeline.current_status()
        final["result"] = result
        status_path.write_text(json.dumps(final), encoding="utf-8")
    except Exception:
        pass

    sys.exit(1 if result.get("error") else 0)


if __name__ == "__main__":
    main()
