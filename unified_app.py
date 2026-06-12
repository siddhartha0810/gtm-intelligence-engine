"""
unified_app.py
==============
The single FastAPI server that hosts the entire DATA TOOL.
All three product tabs (Oracle Intent, Lead Enrichment, Prospect) are served
from this one process so the React SPA has a single origin to call.

PURPOSE:
  Entry point for the entire application.  Manages the lifecycle of two
  long-running child subprocesses (scan_worker.py and enrichment_worker.py),
  exposes all REST API endpoints consumed by the React frontend, and mounts
  the built React SPA on the root path so the browser gets both API and UI
  from port 8000.

HOW IT FITS IN THE SYSTEM:
  ┌─────────────────────────────────┐
  │  Browser → :8000                │
  │    /api/*  → FastAPI routes     │
  │    /*      → React SPA          │
  └─────────────────────────────────┘
  Two subprocesses are spawned at startup:
    scan_worker.py      — runs the Oracle Intent scanner (signal scraping)
    enrichment_worker.py — runs the contact enrichment pipeline

  Status files on disk track subprocess progress because the children
  write JSON to _scan_status.json / _enrich_status.json which the API
  reads and streams back to the browser over SSE.

KEY CLASSES/FUNCTIONS:
  lifespan()                — FastAPI startup/shutdown lifecycle handler
  _start_scan_worker()      — spawns scan_worker.py as a subprocess
  _start_enrich_worker()    — spawns enrichment_worker.py as a subprocess
  _stream_job_output()      — generator that yields SSE lines from subprocess stdout
  POST /api/scan/start      — begins a new Oracle Intent scan
  POST /api/enrich/start    — begins a new contact enrichment run
  GET  /api/companies       — returns all companies with signal counts
  GET  /api/contacts        — returns all enriched contacts
  POST /api/auth/login      — JWT auth login
  GET  /api/auth/me         — returns current user from JWT

DEPENDENCIES:
  - oracle_intent_engine/src/  (imported directly via sys.path)
  - lead_enrichment_engine/    (invoked as subprocess, never imported)
  - PostgreSQL on 10.0.0.149:5432 (Inoapps-Data-DB)
  - .env files in each engine folder (loaded at startup via python-dotenv)

Run from DATA TOOL root:
  uvicorn unified_app:app --reload --port 8000

Then open: http://localhost:8000
"""

import asyncio
import csv
import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# path setup
BASE_DIR    = Path(__file__).parent
ORACLE_DIR  = BASE_DIR / "oracle_intent_engine"
ENRICH_DIR  = BASE_DIR / "lead_enrichment_engine"

# Add oracle engine first so its `src` package is the one resolved for bare imports.
# Lead enrichment pipeline runs as subprocess with cwd=ENRICH_DIR, so no conflict.
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

import httpx
import pandas as pd
import psycopg2
import psycopg2.extras

from fastapi import FastAPI, File, Form, Request, UploadFile, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Dotenv MUST load before oracle engine imports so JWT_SECRET and DB vars
#    are in the environment when auth.py / database.py read them at import time.
from dotenv import load_dotenv
load_dotenv(BASE_DIR / "oracle_intent_engine"   / ".env")           # oracle DB vars + JWT_SECRET first
load_dotenv(BASE_DIR / "lead_enrichment_engine" / ".env", override=False)  # enrichment vars

# oracle engine imports (after path setup)
from src import config as oracle_cfg
from src import database as oracle_db
from src import exporter as oracle_exporter
from src import contact_finder as oracle_contact_finder
from src import apollo_enrichment as oracle_apollo
from src.utils import is_valid_company_name
from src.phase_classifier import PHASE_LABELS, PHASE_COLORS
from src import auth as oracle_auth
from src.audit import log_audit, get_audit_logs
from src import tech_profiles as tp_mod
import oracle_intent_engine.src.hubspot_push as hs_push
from src import events as events_mod
from src import manufacturer as mfr_mod
from src import list_import as import_mod
from src import data_quality as dqe_mod

# Explicitly set oracle DB DSN so oracle database.py never picks up PG_MASTER_CONNECTION_STRING
_oracle_env: Dict[str, str] = {}
_dotenv_path = BASE_DIR / "oracle_intent_engine" / ".env"
if _dotenv_path.exists():
    for _line in _dotenv_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            _oracle_env[_k.strip()] = _v.strip()
_oracle_pg_dsn = (
    f"host={_oracle_env.get('DB_HOST','10.0.0.149')} "
    f"port={_oracle_env.get('DB_PORT','5432')} "
    f"dbname={_oracle_env.get('DB_NAME','Inoapps-Data-DB')} "
    f"user={_oracle_env.get('DB_USER','postgres')} "
    f"password={_oracle_env.get('DB_PASSWORD','')}"
)
os.environ["ORACLE_PG_DSN"] = _oracle_pg_dsn

APOLLO_API_KEY           = os.getenv("APOLLO_API_KEY", "").strip()
ZEROBOUNCE_API_KEY       = os.getenv("ZEROBOUNCE_API_KEY", "").strip()
ZOOMINFO_USERNAME        = os.getenv("ZOOMINFO_USERNAME", "").strip()
ZOOMINFO_PASSWORD        = os.getenv("ZOOMINFO_PASSWORD", "").strip()
APIFY_TOKEN              = os.getenv("APIFY_TOKEN", "").strip()
APIFY_LINKEDIN_ACTOR_ID  = os.getenv("APIFY_LINKEDIN_ACTOR_ID", "").strip()
APIFY_EMAIL_ACTOR_ID     = os.getenv("APIFY_EMAIL_ACTOR_ID", "").strip()
PG_CONNECTION_STRING     = os.getenv("PG_CONNECTION_STRING", "").strip()
PG_MASTER_CONNECTION_STRING = os.getenv("PG_MASTER_CONNECTION_STRING", "").strip()
PG_INPUT_TABLE           = os.getenv("PG_INPUT_TABLE", "leads").strip()
PG_OUTPUT_TABLE          = os.getenv("PG_OUTPUT_TABLE", "enriched_leads").strip()

# application lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan handler — runs once at startup and once at shutdown.

    Startup tasks:
      1. oracle_db.init_db()       — CREATE TABLE IF NOT EXISTS (safe to re-run)
      2. tp_mod.seed_default_profile() — ensure at least one tech profile exists
      3. oracle_db.seed_engine_configs() — populate default engine config rows
      4. Create required input/ and output/ directories if they don't exist

    All startup steps are wrapped in try/except so a DB hiccup doesn't prevent
    the server from booting — it logs a warning and continues.

    The `yield` separates startup code (above) from shutdown code (below).
    Shutdown: psycopg2 pool connections are reclaimed by GC automatically.
    """
    _startup_log = logging.getLogger("unified_app.startup")
    try:
        oracle_db.init_db()
    except Exception as e:
        _startup_log.warning("Oracle DB init warning: %s", e)
    try:
        tp_mod.seed_default_profile()
    except Exception as e:
        _startup_log.warning("Tech profile seed warning: %s", e)
    try:
        oracle_db.seed_engine_configs()
    except Exception as e:
        _startup_log.warning("Engine configs seed warning: %s", e)
    (ENRICH_DIR / "input").mkdir(exist_ok=True)
    (ENRICH_DIR / "output").mkdir(exist_ok=True)
    (ORACLE_DIR / "output").mkdir(exist_ok=True)
    yield  # Application runs here
    # Shutdown — connection pools close automatically via psycopg2 GC

# rate limiter — guards login/register against brute force
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# app
app = FastAPI(title="Oracle Intelligence Platform", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("unified_app")

app.add_middleware(GZipMiddleware, minimum_size=500)   # compress responses > 500 bytes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# static file serving
# Production: React build output at frontend/dist
# Dev:        Vite runs on :5173 and proxies to us — no static mount needed
REACT_DIST   = BASE_DIR / "frontend" / "dist"
STATIC_DIR   = ENRICH_DIR / "static"   # old unified.html (fallback)

# SPA mount added at end of file after all API routes

# pg master contact count cache (remote host may be unreachable)
_pg_master_cache: Dict[str, object] = {"contacts": 0, "ts": 0.0}
_pg_master_lock = threading.Lock()

def _cached_pg_master_contacts() -> int:
    """Return enriched contact count, cached for 60 s to avoid blocking every poll."""
    now = time.monotonic()
    with _pg_master_lock:
        if now - _pg_master_cache["ts"] < 60:
            return _pg_master_cache["contacts"]  # type: ignore[return-value]
    # Refresh in a background thread so we don't block the event loop
    def _fetch():
        try:
            conn = psycopg2.connect(PG_MASTER_CONNECTION_STRING, connect_timeout=3)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM contacts"
                        " WHERE \"Validated_Email\" IS NOT NULL"
                        " AND \"Validated_Email\" != ''"
                    )
                    count = cur.fetchone()[0]
            conn.close()
            with _pg_master_lock:
                _pg_master_cache["contacts"] = count
                _pg_master_cache["ts"] = time.monotonic()
        except Exception:
            logger.warning("Master contacts DB unreachable — will retry in 60 s")
            with _pg_master_lock:
                _pg_master_cache["ts"] = time.monotonic()  # back-off 60 s on failure

    threading.Thread(target=_fetch, daemon=True).start()
    return _pg_master_cache["contacts"]  # type: ignore[return-value]

# oracle scan subprocess state
_SCAN_STATUS_FILE = BASE_DIR / "_scan_status.json"
_SCAN_LOG_FILE    = BASE_DIR / "_scan_log.txt"
_SCAN_PID_FILE    = BASE_DIR / "_scan_worker.pid"
_scan_proc: Optional[subprocess.Popen] = None
_scan_proc_lock   = threading.Lock()

_IDLE_STATUS = {
    "status": "idle", "progress": "",
    "run_id": None, "raw_signals": 0, "companies_found": 0,
}

def _scan_current_status() -> dict:
    try:
        if _SCAN_STATUS_FILE.exists():
            raw = _SCAN_STATUS_FILE.read_text(encoding="utf-8").strip()
            if raw:
                st = json.loads(raw)
                # If process has exited but file still says running, correct it
                with _scan_proc_lock:
                    if _scan_proc is not None and _scan_proc.poll() is not None:
                        if st.get("status") == "running":
                            st["status"]   = "idle"
                            st["progress"] = "Done." if _scan_proc.returncode == 0 else "Stopped."
                            # Auto-update Product Intelligence whenever a scan finishes
                            if _scan_proc.returncode == 0:
                                try:
                                    oracle_db.aggregate_product_intel()
                                except Exception:
                                    logger.warning("aggregate_product_intel failed after scan completed", exc_info=True)
                return st
    except Exception:
        logger.warning("Failed to read scan status file", exc_info=True)
    return dict(_IDLE_STATUS)

def _scan_get_log() -> list:
    try:
        if _SCAN_LOG_FILE.exists():
            return [
                line for line in _SCAN_LOG_FILE.read_text(encoding="utf-8").splitlines()
                if line
            ]
    except Exception:
        logger.warning("Failed to read scan log file", exc_info=True)
    return []

def _watch_scan_then_enrich(proc: subprocess.Popen, enrich_params: dict) -> None:
    """Background thread: when the scan subprocess finishes successfully,
    automatically launch the full enrichment pipeline (stages 1-7) so scanned
    companies end up in the DB with validated contacts + target_product set."""
    try:
        proc.wait()
        if proc.returncode != 0:
            logger.info("Auto-enrich skipped — scan exited with errors or was stopped")
            return
        time.sleep(2)  # let the scan status file settle
        started = _start_enrich_subprocess(**enrich_params)
        logger.info(f"Auto-enrich after scan: {'started' if started else 'already running'}")
    except Exception:
        logger.warning("Auto-enrich watcher failed", exc_info=True)

def _start_scan_subprocess(sources: list, location: str, max_pages: int,
                           jde_manufacturing: bool = False,
                           auto_enrich: bool = False,
                           enrich_params: Optional[dict] = None) -> bool:
    """Spawn scan_worker.py as a subprocess. Returns False if already running."""
    global _scan_proc
    with _scan_proc_lock:
        if _scan_proc is not None and _scan_proc.poll() is None:
            return False  # already running

        # Seed status + clear log before spawning so reads never see stale data
        _SCAN_STATUS_FILE.write_text(
            json.dumps({
                "status": "running", "progress": "Starting...",
                "run_id": None, "raw_signals": 0, "companies_found": 0,
            }),
            encoding="utf-8",
        )
        _SCAN_LOG_FILE.write_text("", encoding="utf-8")

        cmd = [
            sys.executable,
            str(BASE_DIR / "scan_worker.py"),
            "--status-file", str(_SCAN_STATUS_FILE),
            "--log-file",    str(_SCAN_LOG_FILE),
            "--max-pages",   str(max_pages),
        ]
        if sources:
            cmd += ["--sources"] + list(sources)
        if location:
            cmd += ["--location", location]
        if jde_manufacturing:
            cmd += ["--jde-manufacturing"]

        _scan_proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _SCAN_PID_FILE.write_text(str(_scan_proc.pid), encoding="utf-8")

        if auto_enrich:
            threading.Thread(
                target=_watch_scan_then_enrich,
                args=(_scan_proc, enrich_params or {}),
                daemon=True,
            ).start()
        return True

def _stop_scan_subprocess() -> None:
    global _scan_proc
    with _scan_proc_lock:
        if _scan_proc is not None and _scan_proc.poll() is None:
            _scan_proc.terminate()
            try:
                _scan_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _scan_proc.kill()

        if _SCAN_PID_FILE.exists():
            try:
                saved_pid = int(_SCAN_PID_FILE.read_text().strip())
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(saved_pid)],
                    capture_output=True,
                )
            except Exception:
                logger.warning("Could not kill scan worker by saved PID", exc_info=True)
            finally:
                _SCAN_PID_FILE.unlink(missing_ok=True)

    try:
        if _SCAN_STATUS_FILE.exists():
            st = json.loads(_SCAN_STATUS_FILE.read_text(encoding="utf-8"))
            if st.get("status") == "running":
                st["status"]   = "idle"
                st["progress"] = "Stopped by user."
                _SCAN_STATUS_FILE.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        logger.warning("Failed to update scan status file after stop", exc_info=True)

# oracle enrichment subprocess state
_ENRICH_STATUS_FILE = BASE_DIR / "_enrich_status.json"
_ENRICH_LOG_FILE    = BASE_DIR / "_enrich_log.txt"
_ENRICH_PID_FILE    = BASE_DIR / "_enrich_worker.pid"
_enrich_proc: Optional[subprocess.Popen] = None
_enrich_proc_lock   = threading.Lock()

_ENRICH_IDLE = {
    "status": "idle", "progress": "",
    "companies_processed": 0, "companies_total": 0,
    "contacts_found": 0, "contacts_validated": 0,
}

def _enrich_current_status() -> dict:
    try:
        if _ENRICH_STATUS_FILE.exists():
            raw = _ENRICH_STATUS_FILE.read_text(encoding="utf-8").strip()
            if raw:
                st = json.loads(raw)
                with _enrich_proc_lock:
                    if _enrich_proc is not None and _enrich_proc.poll() is not None:
                        if st.get("status") == "running":
                            st["status"]   = "completed"
                            st["progress"] = "Done." if _enrich_proc.returncode == 0 else "Stopped."
                return st  # type: ignore[return-value]
    except Exception:
        logger.warning("Failed to read enrich status file", exc_info=True)
    return dict(_ENRICH_IDLE)

def _enrich_get_log() -> list:
    try:
        if _ENRICH_LOG_FILE.exists():
            return [line for line in _ENRICH_LOG_FILE.read_text(encoding="utf-8").splitlines() if line]
    except Exception:
        logger.warning("Failed to read enrich log file", exc_info=True)
    return []

def _start_enrich_subprocess(
    limit: int = 50,
    max_per_company: int = 10,
    batch_size: Optional[int] = None,
    role_filters: Optional[List[str]] = None,
    provider: str = "apollo",
    company_ids: Optional[List[int]] = None,
) -> bool:
    """Spawn enrichment_worker.py. Returns False if already running."""
    global _enrich_proc
    with _enrich_proc_lock:
        if _enrich_proc is not None and _enrich_proc.poll() is None:
            return False  # already running

        _ENRICH_STATUS_FILE.write_text(
            json.dumps({
                "status": "running", "progress": "Starting...",
                "companies_processed": 0, "companies_total": 0,
                "contacts_found": 0, "contacts_validated": 0,
            }),
            encoding="utf-8",
        )
        _ENRICH_LOG_FILE.write_text("", encoding="utf-8")

        env = os.environ.copy()
        env["APOLLO_API_KEY"]     = APOLLO_API_KEY
        env["ZEROBOUNCE_API_KEY"] = ZEROBOUNCE_API_KEY
        env["ZOOMINFO_USERNAME"]  = ZOOMINFO_USERNAME
        env["ZOOMINFO_PASSWORD"]  = ZOOMINFO_PASSWORD

        cmd = [
            sys.executable,
            str(BASE_DIR / "enrichment_worker.py"),
            "--status-file",     str(_ENRICH_STATUS_FILE),
            "--log-file",        str(_ENRICH_LOG_FILE),
            "--limit",           str(limit),
            "--max-per-company", str(max_per_company),
            "--provider",        provider,
        ]
        if batch_size:
            cmd += ["--batch-size", str(batch_size)]
        if role_filters:
            cmd += ["--role-filters", json.dumps(role_filters)]
        if company_ids:
            cmd += ["--company-ids", json.dumps(company_ids)]

        _enrich_proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Persist PID so stop works even after a server restart
        _ENRICH_PID_FILE.write_text(str(_enrich_proc.pid), encoding="utf-8")
        return True

def _stop_enrich_subprocess() -> None:
    global _enrich_proc

    with _enrich_proc_lock:
        # Kill the in-memory handle if available
        if _enrich_proc is not None and _enrich_proc.poll() is None:
            _enrich_proc.terminate()
            try:
                _enrich_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _enrich_proc.kill()

        # Also kill by saved PID — works even after a server restart
        if _ENRICH_PID_FILE.exists():
            try:
                saved_pid = int(_ENRICH_PID_FILE.read_text().strip())
                # taskkill works on Windows and kills the whole process tree
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(saved_pid)],
                    capture_output=True,
                )
            except Exception:
                logger.warning("Could not kill enrich worker by saved PID", exc_info=True)
            finally:
                _ENRICH_PID_FILE.unlink(missing_ok=True)

    # Mark status file as stopped so the UI updates immediately
    try:
        if _ENRICH_STATUS_FILE.exists():
            st = json.loads(_ENRICH_STATUS_FILE.read_text(encoding="utf-8"))
            if st.get("status") == "running":
                st["status"]   = "idle"
                st["progress"] = "Stopped by user."
                _ENRICH_STATUS_FILE.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        logger.warning("Failed to update enrich status file after stop", exc_info=True)

# shared job store (enrichment + prospect jobs)
_jobs: Dict[str, dict] = {}

def _cleanup_old_jobs(keep: int = 10) -> None:
    done = [jid for jid, j in _jobs.items() if j["status"] in ("done", "error", "cancelled")]
    for jid in done[:-keep]:
        _jobs.pop(jid, None)

def _running_jobs() -> list:
    return [jid for jid, j in _jobs.items() if j["status"] == "running"]

def _make_job() -> tuple[str, queue.Queue]:
    jid = str(uuid.uuid4())[:8]
    q: queue.Queue = queue.Queue()
    return jid, q

def _launch_subprocess(cmd: list, cwd: Path, env: dict, job_id: str, q: queue.Queue):
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(cwd),
        env=env,
        bufsize=1,
    )
    _jobs[job_id]["process"] = proc

    def _read(proc, q):
        for line in iter(proc.stdout.readline, ""):
            q.put(line)
        proc.wait()
        q.put(None)
        _jobs[job_id]["status"]    = "done" if proc.returncode == 0 else "error"
        _jobs[job_id]["exit_code"] = proc.returncode
        # For prospect jobs: load the JSON result file into memory
        if _jobs[job_id].get("type") == "prospect":
            _load_prospect_results(job_id)

    threading.Thread(target=_read, args=(proc, q), daemon=True).start()
    return proc

# ═══ ROOT — serve React app (production) or redirect to Vite (dev) ════════════
def _react_index() -> HTMLResponse:
    """Return the React index.html, falling back to old unified.html."""
    if REACT_DIST.exists():
        return HTMLResponse((REACT_DIST / "index.html").read_text(encoding="utf-8"))
    return HTMLResponse((STATIC_DIR / "unified.html").read_text(encoding="utf-8"))

# ═══ SHARED: SSE STREAM + STATUS + CANCEL ═════════════════════════════════════
@app.get("/stream/{job_id}")
async def stream_output(job_id: str, current_user: dict = Depends(oracle_auth.require_user)):
    if job_id not in _jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    q = _jobs[job_id]["queue"]

    async def generate():
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, lambda: q.get(timeout=1.0))
            except Exception:
                yield "data: \n\n"
                continue
            if line is None:
                yield "data: __DONE__\n\n"
                break
            safe = line.rstrip().replace("\r", "")
            yield f"data: {safe}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/status/{job_id}")
async def get_status(job_id: str, current_user: dict = Depends(oracle_auth.require_user)):
    if job_id not in _jobs:
        return {"status": "not_found"}
    j = _jobs[job_id]
    return {"status": j["status"], "exit_code": j.get("exit_code")}

@app.post("/cancel/{job_id}")
async def cancel_job(job_id: str, current_user: dict = Depends(oracle_auth.require_analyst)):
    if job_id not in _jobs:
        return {"status": "not_found"}
    proc = _jobs[job_id].get("process")
    if proc and proc.poll() is None:
        proc.terminate()
        _jobs[job_id]["status"] = "cancelled"
    return {"status": "cancelled"}

# ═══ ORACLE INTENT — scan control ═════════════════════════════════════════════
@app.get("/oracle/config")
async def oracle_config(current_user: dict = Depends(oracle_auth.require_user)):
    try:
        oracle_db.init_db()
        db_ok = oracle_db.test_connection()
    except Exception:
        db_ok = False
    return {"db_ok": db_ok}

@app.post("/scan/start")
async def start_scan(request: Request, current_user: dict = Depends(oracle_auth.require_analyst)):
    status = _scan_current_status()
    if status["status"] == "running":
        return JSONResponse(
            {"error": "Scan already running.", "progress": status["progress"]},
            status_code=409,
        )
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    sources             = data.get("sources",   ["linkedin", "oracle_website", "news", "erp_today", "partner_casestudy", "si_casestudy", "oracle_community", "oracle_event", "home_builders"])
    location            = data.get("location",  "")
    max_pages           = int(data.get("max_pages", oracle_cfg.MAX_PAGES))
    jde_manufacturing   = bool(data.get("jde_manufacturing", False))
    auto_enrich         = bool(data.get("auto_enrich", False))
    enrich_params = {
        "limit":           int(data.get("enrich_limit", 50)),
        "max_per_company": int(data.get("enrich_per_company", 10)),
        "provider":        str(data.get("enrich_provider", "apollo")),
    }

    started = _start_scan_subprocess(sources=sources, location=location, max_pages=max_pages,
                                     jde_manufacturing=jde_manufacturing,
                                     auto_enrich=auto_enrich, enrich_params=enrich_params)
    if not started:
        return JSONResponse({"error": "Scan already running."}, status_code=409)
    return {"message": "Scan started.", "sources": sources,
            "jde_manufacturing": jde_manufacturing, "auto_enrich": auto_enrich}

@app.get("/scan/status")
async def scan_status(current_user: dict = Depends(oracle_auth.require_user)):
    return _scan_current_status()

@app.post("/scan/stop")
async def stop_scan(current_user: dict = Depends(oracle_auth.require_analyst)):
    _stop_scan_subprocess()
    return {"message": "Stop signal sent."}

@app.get("/scan/log")
async def scan_log(current_user: dict = Depends(oracle_auth.require_user)):
    return _scan_get_log()

@app.get("/scan/companies")
async def scan_companies(
    run_id: int = None,
    current_user: dict = Depends(oracle_auth.require_user),
):
    """Companies discovered in a specific scan run (defaults to latest completed run).

    Query params:
      run_id=<int>  — specific scan run
      run_id=0      — all companies ever
    """
    resolved_run_id = run_id if run_id is not None else oracle_db.get_latest_completed_run_id()
    companies = list(oracle_db.get_all_companies_with_signals(run_id=resolved_run_id))
    companies = _annotate_and_sort(companies)
    scan_runs = oracle_db.get_recent_scan_runs(10)
    return {
        "run_id":    resolved_run_id,
        "total":     len(companies),
        "companies": companies,
        "scan_runs": [dict(r) for r in scan_runs],
    }

@app.delete("/scan/companies")
async def purge_scan_companies(
    run_id: int,
    current_user: dict = Depends(oracle_auth.require_admin),
):
    """Delete all companies (+ their signals and contacts) first found in the given scan run.
    Requires admin role. Cannot be undone.
    """
    if not run_id or run_id <= 0:
        raise HTTPException(status_code=400, detail="A valid run_id is required.")
    deleted = oracle_db.purge_scan_companies(run_id)
    return {"deleted": deleted, "run_id": run_id, "message": f"Removed {deleted} companies from scan run #{run_id}."}

# ═══ ORACLE INTENT — data / companies ═════════════════════════════════════════
def _annotate_and_sort(companies: list) -> list:
    from src import lead_scorer
    for c in companies:
        lead_scorer.annotate(c)
    companies.sort(key=lambda c: c.get("priority_score", 0), reverse=True)
    return companies

# in-process ttl cache for /api/companies
# Key: show_all (0 or 1).  Value: (timestamp, list[dict]).
# TTL: 60 s — keeps the page instant on repeated visits / tab switches.
# Invalidated automatically by _invalidate_companies_cache() on writes.
_companies_cache: Dict[int, tuple] = {}
_COMPANIES_CACHE_TTL = 60  # seconds

def _invalidate_companies_cache() -> None:
    _companies_cache.clear()

@app.get("/api/companies/filter-options")
async def api_companies_filter_options(current_user: dict = Depends(oracle_auth.require_user)):
    """Returns distinct industries and locations for column filter dropdowns."""
    from oracle_intent_engine.src.industry_normalizer import normalize as _norm_industry
    try:
        with oracle_db.db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT DISTINCT industry
                FROM companies
                WHERE industry IS NOT NULL AND industry <> ''
                ORDER BY 1 LIMIT 500
            """)
            raw_industries = [r["industry"] for r in cur.fetchall()]
            # Normalize and deduplicate
            seen: set[str] = set()
            industries: list[str] = []
            for raw in raw_industries:
                canon = _norm_industry(raw)
                if canon and canon not in seen:
                    seen.add(canon)
                    industries.append(canon)
            industries.sort()

            cur.execute("""
                SELECT DISTINCT location
                FROM companies
                WHERE location IS NOT NULL AND location <> ''
                ORDER BY 1 LIMIT 300
            """)
            locations = [r["location"] for r in cur.fetchall()]
        return JSONResponse({"industries": industries, "locations": locations})
    except Exception as e:
        return JSONResponse({"industries": [], "locations": []})

@app.get("/api/companies")
async def api_companies(
    phase:    str = "",
    product:  str = "",
    industry: str = "",
    location: str = "",
    has_contacts: str = "",   # "yes" | "no"
    show_all: int = 0,
    search:   str = "",
    limit:    int = 200,
    offset:   int = 0,
    current_user: dict = Depends(oracle_auth.require_user),
):
    """Fast paginated companies endpoint.
    Uses denormalized signal_count / contact_count columns so sorting is O(log n).
    Fetches signal details (phases, products) only for the page IDs.
    Default: 200 companies per page, sorted by signal_count DESC.
    """
    try:
        page_limit = min(limit, 500) if limit > 0 else 500

        with oracle_db.db_cursor(commit=False) as cur:

            conditions: List[str] = []
            params: List = []

            if search:
                conditions.append(
                    "(LOWER(c.name) LIKE %s OR LOWER(COALESCE(c.industry,'')) LIKE %s"
                    " OR LOWER(COALESCE(c.domain,'')) LIKE %s)"
                )
                s = f"%{search.lower()}%"
                params.extend([s, s, s])

            if product:
                conditions.append("c.target_product = %s")
                params.append(product)

            if industry:
                from oracle_intent_engine.src.industry_normalizer import normalize as _norm_i, _CANONICAL
                selected_canonical = {v.strip() for v in industry.split(',') if v.strip()}
                # Expand each canonical name back to all raw variants (for DB match)
                raw_variants: list[str] = []
                for canon in selected_canonical:
                    raw_variants.extend(v.lower() for v in _CANONICAL.get(canon, [canon]))
                    raw_variants.append(canon.lower())  # also match the canonical itself
                raw_variants = list(set(raw_variants))
                if raw_variants:
                    placeholders = ','.join(['%s'] * len(raw_variants))
                    conditions.append(f"LOWER(COALESCE(c.industry,'')) IN ({placeholders})")
                    params.extend(raw_variants)

            if location:
                vals = [v.strip().lower() for v in location.split(',') if v.strip()]
                if vals:
                    loc_conds = ' OR '.join(['LOWER(COALESCE(c.location,\'\')) LIKE %s'] * len(vals))
                    conditions.append(f"({loc_conds})")
                    params.extend([f"%{v}%" for v in vals])

            if has_contacts == "yes":
                conditions.append("c.contact_count > 0")
            elif has_contacts == "no":
                conditions.append("(c.contact_count = 0 OR c.contact_count IS NULL)")

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(f"SELECT COUNT(*) AS n FROM companies c {where}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"""SELECT c.id FROM companies c {where}
                    ORDER BY c.signal_count DESC, c.last_updated DESC
                    LIMIT %s OFFSET %s""",
                params + [page_limit, offset],
            )
            page_ids = [r["id"] for r in cur.fetchall()]

            if not page_ids:
                return JSONResponse({"total": total, "offset": offset, "limit": page_limit, "rows": []})

            cur.execute("""
                SELECT company_id,
                       STRING_AGG(DISTINCT oracle_product, ',') AS products,
                       STRING_AGG(DISTINCT phase, ',')          AS phases,
                       STRING_AGG(DISTINCT source, ',')         AS sources,
                       MAX(confidence)                          AS max_confidence,
                       (ARRAY_AGG(url ORDER BY confidence DESC)
                        FILTER (WHERE url LIKE 'http%%'))[1]   AS source_url
                FROM oracle_signals
                WHERE company_id = ANY(%s)
                GROUP BY company_id
            """, (page_ids,))
            sig_map = {r["company_id"]: r for r in cur.fetchall()}

            cur.execute("""
                SELECT c.id, c.name, c.domain, c.industry, c.size, c.location, c.website,
                       c.target_product, c.status, c.source AS import_source,
                       c.first_scan_run_id, c.first_seen::text AS first_seen,
                       c.signal_count, c.contact_count, c.last_updated::text AS last_updated
                FROM companies c
                WHERE c.id = ANY(%s)
            """, (page_ids,))
            co_map = {r["id"]: dict(r) for r in cur.fetchall()}

        rows = []
        for cid in page_ids:
            co = co_map.get(cid)
            if not co:
                continue
            sig = sig_map.get(cid, {})
            products_str = (sig.get("products") or "")
            phases_str   = (sig.get("phases")   or "")
            sources_str  = (sig.get("sources")  or "")
            co.update({
                "products":       [p for p in products_str.split(",") if p],
                "phases":         [p for p in phases_str.split(",")   if p],
                "sources":        [s for s in sources_str.split(",")  if s],
                "max_confidence": sig.get("max_confidence"),
                "source_url":     sig.get("source_url"),
                "priority_score": co["signal_count"],  # used by frontend for Score col
            })

            # Phase filter — server side
            if phase and phase.lower() not in [p.lower() for p in co["phases"]]:
                continue

            rows.append(co)

        return JSONResponse({"total": total, "offset": offset, "limit": page_limit, "rows": rows})
    except Exception as e:
        logger.exception("Unhandled error in GET /api/companies")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/stats")
async def api_stats(show_all: int = 0, current_user: dict = Depends(oracle_auth.require_user)):
    run_id = 0 if show_all else None
    companies = list(oracle_db.get_all_companies_with_signals(run_id=run_id))
    companies = _annotate_and_sort(companies)
    phase_counter: Counter = Counter()
    product_counter: Counter = Counter()
    total_signals = 0
    for c in companies:
        for p in (c.get("phases") or []):
            if p: phase_counter[p] += 1
        for p in (c.get("products") or []):
            if p: product_counter[p] += 1
        total_signals += int(c.get("signal_count") or 0)
    scan_runs = oracle_db.get_recent_scan_runs(5)
    current_run_id = oracle_db.get_latest_completed_run_id()
    # total_companies = actual DB count (all companies, not just current-run signal-backed)
    try:
        with oracle_db.db_cursor(commit=False) as _cur:
            _cur.execute("SELECT COUNT(*) AS n FROM companies")
            db_total = int(_cur.fetchone()["n"] or 0)
    except Exception:
        db_total = len(companies)

    return {
        "total_companies": db_total,
        "total_signals":   total_signals,
        "phases":          dict(phase_counter.most_common()),
        "products":        dict(product_counter.most_common(10)),
        "scan_runs":       [dict(r) for r in scan_runs],
        "current_run_id":  current_run_id,
        "scan_status":     _scan_current_status(),
        "phase_labels":    PHASE_LABELS,
        "phase_colors":    PHASE_COLORS,
    }

@app.get("/api/company/{company_id}/signals")
async def api_company_signals(company_id: int, current_user: dict = Depends(oracle_auth.require_user)):
    return JSONResponse(jsonable_encoder([dict(s) for s in oracle_db.get_signals_for_company(company_id)]))

@app.get("/api/company/{company_id}/contacts")
async def api_company_contacts(company_id: int, current_user: dict = Depends(oracle_auth.require_user)):
    """Return enriched contacts for a company from company_contacts table."""
    rows = jsonable_encoder([dict(c) for c in oracle_db.get_contacts_for_company(company_id)])
    return JSONResponse(rows)

@app.get("/api/companies/duplicates")
async def api_find_duplicates(threshold: int = 85, current_user: dict = Depends(oracle_auth.require_user)):
    """Find pairs of companies with similar names using fuzzy matching."""
    from rapidfuzz import fuzz
    with oracle_db.db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT id, name, domain, industry,
                   COALESCE(signal_count, 0) AS signal_count,
                   COALESCE(contact_count, 0) AS contact_count
            FROM companies ORDER BY name
        """)
        rows = [dict(r) for r in cur.fetchall()]

    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            score = fuzz.token_sort_ratio(a["name"], b["name"])
            if score >= threshold:
                # Suggest keeping the one with more signals; ties go to more contacts
                keep = a if (a["signal_count"], a["contact_count"]) >= (b["signal_count"], b["contact_count"]) else b
                drop = b if keep["id"] == a["id"] else a
                pairs.append({
                    "score": score,
                    "keep": keep,
                    "drop": drop,
                })
    pairs.sort(key=lambda p: -p["score"])
    return {"pairs": pairs[:100]}  # cap at 100 pairs

@app.post("/api/companies/merge")
async def api_merge_companies(request: Request, current_user: dict = Depends(oracle_auth.require_admin)):
    """Merge drop_id into keep_id — moves signals/contacts, deletes the duplicate."""
    data = await request.json()
    keep_id = int(data.get("keep_id", 0))
    drop_id = int(data.get("drop_id", 0))
    if not keep_id or not drop_id or keep_id == drop_id:
        raise HTTPException(status_code=400, detail="keep_id and drop_id must be different non-zero integers")
    try:
        result = oracle_db.merge_companies(keep_id, drop_id)
    except Exception:
        logger.exception(f"merge_companies keep={keep_id} drop={drop_id} failed")
        raise HTTPException(status_code=500, detail="Internal server error")
    _invalidate_companies_cache()
    _invalidate_dashboard_cache()
    return {"merged": True, "keep_id": keep_id, "drop_id": drop_id, **result}

@app.delete("/api/companies/{company_id}")
async def api_delete_company(company_id: int, current_user: dict = Depends(oracle_auth.require_admin)):
    """Delete one company from the database. Signals and contacts cascade.
    Admin/owner only. Cannot be undone."""
    try:
        deleted = oracle_db.delete_company(company_id)
    except Exception:
        logger.exception(f"delete_company id={company_id} failed")
        raise HTTPException(status_code=500, detail="Internal server error")
    if not deleted:
        raise HTTPException(status_code=404, detail="Company not found")
    _invalidate_companies_cache()
    _invalidate_dashboard_cache()
    return {"deleted": True, "company_id": company_id}

@app.delete("/api/contacts/{contact_id}")
async def api_delete_contact(contact_id: int, current_user: dict = Depends(oracle_auth.require_admin)):
    """Delete one contact from the database. Admin/owner only. Cannot be undone."""
    try:
        deleted = oracle_db.delete_contact(contact_id)
    except Exception:
        logger.exception(f"delete_contact id={contact_id} failed")
        raise HTTPException(status_code=500, detail="Internal server error")
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    _invalidate_companies_cache()
    _invalidate_dashboard_cache()
    return {"deleted": True, "contact_id": contact_id}


@app.post("/api/contacts/{contact_id}/predict-email")
async def api_predict_contact_email(contact_id: int, current_user: dict = Depends(oracle_auth.require_analyst)):
    """
    On-demand email prediction for a single contact with no email.
    Learns the domain pattern from sibling contacts with valid emails,
    builds a candidate, validates via ZeroBounce, and saves if valid.
    """
    try:
        row = oracle_db.get_contact_by_id(contact_id)
        if not row:
            raise HTTPException(status_code=404, detail="Contact not found")
        contact = dict(row)
        if contact.get("email"):
            return {"status": "already_has_email", "email": contact["email"]}

        company_id = contact.get("company_id")
        domain = (contact.get("domain") or "").strip().lower()

        # Fallback 1: company domain from companies table
        if not domain and company_id:
            company_row = oracle_db.get_company_by_id(company_id)
            if company_row:
                domain = (dict(company_row).get("domain") or "").strip().lower()

        # Fallback 2: any sibling contact that has a domain stored
        if not domain and company_id:
            siblings = oracle_db.get_contacts_for_company(company_id)
            for s in siblings:
                sd = dict(s)
                if sd.get("domain"):
                    domain = sd["domain"].strip().lower()
                    break

        if not domain:
            return {"status": "no_domain", "message": "Cannot predict — company has no domain on record. Run domain enrichment first."}

        # Build a minimal contacts list (siblings with valid emails + this contact)
        siblings = oracle_db.get_contacts_for_company(company_id) if company_id else []
        batch = []
        for s in siblings:
            sd = dict(s)
            if sd.get("email_validation_status") == "valid" and sd.get("email"):
                batch.append({
                    "first_name": sd.get("first_name", ""),
                    "last_name":  sd.get("last_name", ""),
                    "email":      sd["email"],
                    "email_validation_status": "valid",
                    "domain":     sd.get("domain", domain),
                })
        # Append the target contact (no email)
        target_idx = len(batch)
        batch.append({
            "first_name": contact.get("first_name", ""),
            "last_name":  contact.get("last_name", ""),
            "email":      None,
            "email_validation_status": None,
            "domain":     domain,
            "_contact_id": contact_id,
        })

        updated, n_predicted = oracle_apollo._predict_and_fill_emails(
            batch, ZEROBOUNCE_API_KEY, domain, log=logger.info
        )

        target = updated[target_idx]
        if target.get("email") and target.get("email_validation_status") == "valid":
            oracle_db.update_contact_email(
                contact_id=contact_id,
                email=target["email"],
                email_validation_status="valid",
                email_source="predicted",
                ready_for_outreach=True,
            )
            _invalidate_companies_cache()
            return {
                "status": "predicted",
                "email": target["email"],
                "pattern": target.get("email_prediction_pattern"),
            }
        return {"status": "no_valid_prediction", "message": "ZeroBounce did not return a valid email for any candidate"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"predict-email for contact_id={contact_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Per-company enrichment job state (keyed by company_id)
_company_jobs: Dict[int, Dict] = {}
_company_jobs_lock = threading.Lock()

def _run_company_enrich(company_id: int, provider: str, max_per_company: int) -> None:
    """Background thread: run full Apollo/ZoomInfo pipeline for one company."""
    with _company_jobs_lock:
        _company_jobs[company_id] = {"status": "running", "contacts_found": 0, "error": ""}
    error_msg = ""
    try:
        oracle_apollo.enrich_companies(
            apollo_key=APOLLO_API_KEY,
            zerobounce_key=ZEROBOUNCE_API_KEY,
            limit=1,
            max_per_company=max_per_company,
            provider=provider,
            company_ids=[company_id],
        )
    except Exception as e:
        logger.exception("Per-company enrich failed for id=%s", company_id)
        error_msg = str(e)
    finally:
        # Always count from DB — contacts may have been saved before any exception
        try:
            rows = oracle_db.get_contacts_for_company(company_id)
            # Count only contacts with at least one contact method (email or linkedin)
            saved = sum(1 for r in rows if dict(r).get("email") or dict(r).get("linkedin_url"))
        except Exception:
            saved = 0
        status = "error" if error_msg else "done"
        with _company_jobs_lock:
            _company_jobs[company_id] = {"status": status, "contacts_found": saved, "error": error_msg}

@app.post("/api/company/{company_id}/contacts/enrich")
async def api_enrich_contacts(company_id: int, request: Request,
                               current_user: dict = Depends(oracle_auth.require_analyst)):
    """Start Apollo/ZoomInfo enrichment for a single company (background thread)."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    provider        = str(data.get("provider", "apollo")).lower().strip()
    max_per_company = int(data.get("max_per_company", 10))

    if provider == "zoominfo" and not (ZOOMINFO_USERNAME and ZOOMINFO_PASSWORD):
        return JSONResponse({"error": "ZoomInfo not configured. Add ZOOMINFO_USERNAME and ZOOMINFO_PASSWORD to oracle_intent_engine/.env"}, status_code=400)
    if provider == "apollo" and not APOLLO_API_KEY:
        return JSONResponse({"error": "Apollo API key not configured. Add APOLLO_API_KEY to oracle_intent_engine/.env"}, status_code=400)

    try:
        company = oracle_db.get_company_by_id(company_id)
    except Exception as e:
        return JSONResponse({"error": f"DB lookup failed: {e}"}, status_code=500)
    if not company:
        return JSONResponse({"error": "Company not found"}, status_code=404)

    # Check if already running for this company
    with _company_jobs_lock:
        job = _company_jobs.get(company_id, {})
        if job.get("status") == "running":
            return JSONResponse({"error": "Enrichment already running for this company"}, status_code=409)

    t = threading.Thread(target=_run_company_enrich,
                         args=(company_id, provider, max_per_company), daemon=True)
    t.start()
    return {"started": True, "company_id": company_id, "provider": provider}

@app.get("/api/company/{company_id}/enrich-status")
async def api_company_enrich_status(company_id: int,
                                     current_user: dict = Depends(oracle_auth.require_user)):
    """Poll enrichment job status for a single company."""
    with _company_jobs_lock:
        job = _company_jobs.get(company_id, {"status": "idle", "contacts_found": 0, "error": ""})
    return job

# bulk enrich
_bulk_enrich_state: Dict[str, object] = {"running": False, "done": 0, "total": 0, "errors": 0}
_bulk_enrich_lock  = threading.Lock()

def _bulk_enrich_worker(company_ids: list, provider: str = "apollo", max_per_company: int = 10):
    """
    Bulk enrichment via the full 7-stage pipeline (contacts_master → Apollo/ZoomInfo
    → ZeroBounce → prediction → scoring).  Replaces the old contact_finder path which
    bypassed ZeroBounce, scoring, and contacts_master lookup entirely.
    """
    for cid in company_ids:
        try:
            oracle_apollo.enrich_companies(
                apollo_key=APOLLO_API_KEY,
                zerobounce_key=ZEROBOUNCE_API_KEY,
                limit=1,
                max_per_company=max_per_company,
                provider=provider,
                company_ids=[cid],
            )
        except Exception:
            logger.exception("Bulk enrich failed for company_id=%s", cid)
            _bulk_enrich_state["errors"] = _bulk_enrich_state["errors"] + 1
        _bulk_enrich_state["done"] = _bulk_enrich_state["done"] + 1
    _bulk_enrich_state["running"] = False

@app.post("/api/companies/bulk-enrich")
async def api_bulk_enrich(request: Request, current_user: dict = Depends(oracle_auth.require_analyst)):
    body = await request.json()
    company_ids = body.get("company_ids", [])
    provider = str(body.get("provider", "apollo"))
    max_per_company = int(body.get("max_per_company", 10))
    if not company_ids:
        return JSONResponse({"error": "No company IDs provided"}, status_code=400)
    with _bulk_enrich_lock:
        if _bulk_enrich_state.get("running"):
            return JSONResponse({"error": "Enrichment already running", "progress": _bulk_enrich_state}, status_code=409)
        _bulk_enrich_state.update({"running": True, "done": 0, "total": len(company_ids), "errors": 0})
    t = threading.Thread(target=_bulk_enrich_worker, args=(company_ids, provider, max_per_company), daemon=True)
    t.start()
    return {"message": f"Bulk enrichment started for {len(company_ids)} companies", "total": len(company_ids)}

@app.get("/api/companies/bulk-enrich/progress")
async def api_bulk_enrich_progress(current_user: dict = Depends(oracle_auth.require_user)):
    return dict(_bulk_enrich_state)

# ═══ ORACLE INTENT — admin ════════════════════════════════════════════════════
@app.post("/admin/normalize-industries")
async def normalize_industries(current_user: dict = Depends(oracle_auth.require_admin)):
    """Normalize all raw industry strings in the companies table to canonical English names."""
    from oracle_intent_engine.src.industry_normalizer import normalize as _norm
    updated = 0
    with oracle_db.db_cursor() as cur:
        cur.execute("SELECT id, industry FROM companies WHERE industry IS NOT NULL AND industry <> ''")
        rows = cur.fetchall()
        for row in rows:
            canon = _norm(row["industry"])
            if canon and canon != row["industry"]:
                cur.execute("UPDATE companies SET industry = %s WHERE id = %s", (canon, row["id"]))
                updated += 1
    _invalidate_companies_cache()
    return {"updated": updated, "message": f"Normalized {updated} industry values."}

@app.post("/admin/purge-invalid")
async def purge_invalid(current_user: dict = Depends(oracle_auth.require_admin)):
    count = oracle_db.purge_invalid_companies(is_valid_company_name)
    log_audit(current_user, "purge_invalid", "system", "", new_value={"deleted": count})
    return {"deleted": count, "message": f"Purged {count} invalid company names."}

@app.post("/admin/reset-all")
async def reset_all(current_user: dict = Depends(oracle_auth.require_admin)):
    oracle_db.reset_all_data()
    log_audit(current_user, "reset_all", "system", "")
    return {"message": "All data cleared. Ready for a fresh scan."}

# ═══ ORACLE INTENT — export ═══════════════════════════════════════════════════
def _companies_to_export_format(db_rows) -> list:
    result = []
    for row in db_rows:
        phases   = row.get("phases")   or []
        products = row.get("products") or []
        sources  = row.get("sources")  or []
        result.append({
            "company_name":  row.get("name", ""),
            "domain":        row.get("domain", ""),
            "location":      row.get("location", ""),
            "industry":      row.get("industry", ""),
            "size":          row.get("size", ""),
            "website":       row.get("website", ""),
            "oracle_product": products[0] if products else "Oracle (General)",
            "all_products":  [p for p in products if p],
            "phase":         phases[0] if phases else "hiring",
            "all_phases":    [p for p in phases if p],
            "sources":       [s for s in sources if s],
            "signal_count":  row.get("signal_count", 0),
            "confidence":    float(row.get("max_confidence") or 0),
            "evidence":      "",
            "source_url":    row.get("source_url", ""),
            "signals":       [],
        })
    return result

@app.get("/export/csv")
async def export_csv(current_user: dict = Depends(oracle_auth.require_analyst)):
    companies = oracle_db.get_all_companies_with_signals()
    path = oracle_exporter.export_csv(_companies_to_export_format(companies))
    return FileResponse(path, filename=os.path.basename(path), media_type="text/csv")

@app.get("/export/excel")
async def export_excel(current_user: dict = Depends(oracle_auth.require_analyst)):
    companies = oracle_db.get_all_companies_with_signals()
    path = oracle_exporter.export_excel(_companies_to_export_format(companies))
    return FileResponse(path, filename=os.path.basename(path),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/export/excel/all")
async def export_excel_all(current_user: dict = Depends(oracle_auth.require_analyst)):
    companies = oracle_db.get_all_companies_with_signals(run_id=0)
    filename  = f"oracle_intent_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = oracle_exporter.export_excel(_companies_to_export_format(companies), filename=filename)
    return FileResponse(path, filename=os.path.basename(path),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/export/csv/all")
async def export_csv_all(current_user: dict = Depends(oracle_auth.require_analyst)):
    companies = oracle_db.get_all_companies_with_signals(run_id=0)
    filename  = f"oracle_intent_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path = oracle_exporter.export_csv(_companies_to_export_format(companies), filename=filename)
    return FileResponse(path, filename=os.path.basename(path), media_type="text/csv")

# ═══ LEAD ENRICHMENT — config / upload / run / results / download ═════════════
@app.get("/config")
async def get_config(current_user: dict = Depends(oracle_auth.require_user)):
    return {
        "pg_configured":  bool(PG_CONNECTION_STRING),
        "pg_input_table": PG_INPUT_TABLE,
        "pg_output_table": PG_OUTPUT_TABLE,
        "apollo_key":     bool(APOLLO_API_KEY),
        "zb_key":         bool(ZEROBOUNCE_API_KEY),
        "apify_ready":    bool(APIFY_TOKEN and APIFY_LINKEDIN_ACTOR_ID and APIFY_EMAIL_ACTOR_ID),
    }

@app.get("/config/status")
async def config_status(current_user: dict = Depends(oracle_auth.require_user)):
    """Return real connection status for each API key — used by Settings page."""
    async def _test_hubspot(key: str) -> str:
        if not key or key.startswith("•"):
            return "unconfigured"
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.hubapi.com/crm/v3/objects/contacts",
                    params={"limit": 1},
                    headers={"Authorization": f"Bearer {key}"},
                )
            return "connected" if r.status_code in (200, 204) else "error"
        except Exception:
            return "error"

    async def _test_apollo(key: str) -> str:
        if not key or key.startswith("•"):
            return "unconfigured"
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.apollo.io/api/v1/auth/health",
                    headers={"X-Api-Key": key},
                )
            data = r.json() if r.status_code == 200 else {}
            return "connected" if data.get("is_logged_in") else "error"
        except Exception:
            return "error"

    async def _test_zerobounce(key: str) -> str:
        if not key or key.startswith("•"):
            return "unconfigured"
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.zerobounce.net/v2/getcredits",
                    params={"api_key": key},
                )
            data = r.json() if r.status_code == 200 else {}
            credits = data.get("Credits", -1)
            return "connected" if int(credits) >= 0 else "error"
        except Exception:
            return "error"

    async def _test_apify(key: str) -> str:
        if not key or key.startswith("•"):
            return "unconfigured"
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.apify.com/v2/users/me",
                    headers={"Authorization": f"Bearer {key}"},
                )
            return "connected" if r.status_code == 200 else "error"
        except Exception:
            return "error"

    hs, ap, zb, af = await asyncio.gather(
        _test_hubspot(os.getenv("HUBSPOT_API_KEY", "") or os.getenv("HUBSPOT_TOKEN", "")),
        _test_apollo(APOLLO_API_KEY),
        _test_zerobounce(ZEROBOUNCE_API_KEY),
        _test_apify(APIFY_TOKEN),
    )
    return {"hubspot": hs, "apollo": ap, "zerobounce": zb, "apify": af}

@app.post("/config/test/{service}")
async def config_test(service: str, request: Request,
                      current_user: dict = Depends(oracle_auth.require_admin)):
    """Test a single API key supplied in the request body."""
    data = await request.json()
    key  = (data.get("key") or "").strip()

    if not key:
        return JSONResponse({"status": "error", "message": "No key provided"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            if service == "hubspot":
                r = await c.get(
                    "https://api.hubapi.com/crm/v3/objects/contacts",
                    params={"limit": 1},
                    headers={"Authorization": f"Bearer {key}"},
                )
                ok = r.status_code in (200, 204)
                return {"status": "connected" if ok else "error",
                        "message": "HubSpot connected" if ok else f"HubSpot error {r.status_code}"}

            elif service == "apollo":
                r = await c.get("https://api.apollo.io/api/v1/auth/health",
                                headers={"X-Api-Key": key})
                ok = r.status_code == 200 and r.json().get("is_logged_in")
                return {"status": "connected" if ok else "error",
                        "message": "Apollo authenticated" if ok else f"Apollo auth failed (HTTP {r.status_code})"}

            elif service == "zerobounce":
                r = await c.get("https://api.zerobounce.net/v2/getcredits",
                                params={"api_key": key})
                data = r.json() if r.status_code == 200 else {}
                credits = int(data.get("Credits", -1))
                ok = credits >= 0
                return {"status": "connected" if ok else "error",
                        "message": f"ZeroBounce connected — {credits} credits remaining" if ok else "Invalid ZeroBounce key"}

            elif service == "apify":
                r = await c.get("https://api.apify.com/v2/users/me",
                                headers={"Authorization": f"Bearer {key}"})
                ok = r.status_code == 200
                username = r.json().get("data", {}).get("username", "") if ok else ""
                return {"status": "connected" if ok else "error",
                        "message": f"Apify connected as {username}" if ok else "Invalid Apify token"}

            else:
                return JSONResponse({"status": "error", "message": "Unknown service"}, status_code=400)

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/config/save/{service}")
async def config_save(service: str, request: Request,
                      current_user: dict = Depends(oracle_auth.require_admin)):
    """Persist an API key to lead_enrichment_engine/.env and reload it in memory."""
    global APOLLO_API_KEY, ZEROBOUNCE_API_KEY, APIFY_TOKEN

    data = await request.json()
    key  = (data.get("key") or "").strip()
    if not key:
        return JSONResponse({"ok": False, "message": "No key provided"}, status_code=400)

    _VAR_MAP = {
        "apollo":     "APOLLO_API_KEY",
        "zerobounce": "ZEROBOUNCE_API_KEY",
        "apify":      "APIFY_TOKEN",
        "hubspot":    "HUBSPOT_API_KEY",
    }
    if service not in _VAR_MAP:
        return JSONResponse({"ok": False, "message": "Unknown service"}, status_code=400)

    env_var  = _VAR_MAP[service]
    env_file = ENRICH_DIR / ".env"

    # Rewrite .env — update existing line or append
    lines   = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    found   = False
    updated = []
    for line in lines:
        if line.strip().startswith(f"{env_var}=") or line.strip().startswith(f"{env_var} ="):
            updated.append(f"{env_var}={key}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"{env_var}={key}")
    env_file.write_text("\n".join(updated) + "\n", encoding="utf-8")

    # Hot-reload into os.environ and module-level globals so current process picks it up
    os.environ[env_var] = key
    if env_var == "APOLLO_API_KEY":
        APOLLO_API_KEY = key
    elif env_var == "ZEROBOUNCE_API_KEY":
        ZEROBOUNCE_API_KEY = key
    elif env_var == "APIFY_TOKEN":
        APIFY_TOKEN = key

    return {"ok": True, "message": f"{service} key saved and active"}

@app.post("/upload")
async def upload_csv(file: UploadFile = File(...),
                     current_user: dict = Depends(oracle_auth.require_analyst)):
    dest_dir = ENRICH_DIR / "input"
    dest_dir.mkdir(exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        return JSONResponse({"error": "Only .csv and .xlsx files are accepted"}, status_code=400)
    dest   = dest_dir / f"leads{suffix}"
    content = await file.read()
    dest.write_bytes(content)
    if suffix == ".csv":
        row_count = max(content.decode("utf-8", errors="replace").count("\n") - 1, 0)
    else:
        row_count = "?"
    return {"filename": file.filename, "rows": row_count, "saved_as": str(dest)}

@app.post("/run")
async def run_pipeline(
    restart:  bool = Form(False),
    use_db:   bool = Form(False),
    filename: str  = Form(""),
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    running = _running_jobs()
    if running:
        return JSONResponse(
            {"error": "A pipeline is already running. Cancel it before starting a new one.",
             "running_job_id": running[0]},
            status_code=409,
        )

    _cleanup_old_jobs()
    job_id, q = _make_job()

    cmd = [sys.executable, "-m", "src.pipeline"]
    if filename and not filename.endswith(".csv"):
        suffix = Path(filename).suffix.lower()
        cmd.append(f"input/leads{suffix}")
    cmd.append("--restart" if restart else "--resume")

    env = os.environ.copy()
    if not use_db:
        env.pop("PG_CONNECTION_STRING", None)

    _jobs[job_id] = {"process": None, "queue": q, "status": "running", "exit_code": None, "type": "enrich"}
    _launch_subprocess(cmd, cwd=ENRICH_DIR, env=env, job_id=job_id, q=q)
    return {"job_id": job_id}

@app.get("/api/leads")
async def get_leads(current_user: dict = Depends(oracle_auth.require_analyst)):
    path = ENRICH_DIR / "output" / "final_outreach_ready.csv"
    if not path.exists():
        return JSONResponse({"error": "No output available — run the pipeline first"}, status_code=404)
    df = pd.read_csv(path, dtype=str).fillna("")
    cols = ["first_name", "last_name", "company", "email", "email_source",
            "email_validation_status", "linkedin_url", "ready_for_outreach", "failure_reason"]
    cols = [c for c in cols if c in df.columns]
    return JSONResponse(df[cols].to_dict("records"))

_ALLOWED_DOWNLOADS = {"final_outreach_ready.csv", "audit_log.csv", "vendor_performance.csv"}

@app.get("/download/{filename}")
async def download_file(filename: str, current_user: dict = Depends(oracle_auth.require_analyst)):
    if filename not in _ALLOWED_DOWNLOADS:
        return JSONResponse({"error": "File not available"}, status_code=404)
    path = ENRICH_DIR / "output" / filename
    if not path.exists():
        return JSONResponse({"error": "File not ready — run the pipeline first"}, status_code=404)
    return FileResponse(path, filename=filename, media_type="text/csv")

# ═══ PROSPECT — estimate / run / db-search / status / results / download ══════
# In-memory store for the last prospect result set (single-user tool)
_prospect_results: list = []
_prospect_stats: dict   = {}

def _load_prospect_results(job_id: str):
    """After prospect subprocess exits, read its JSON output into memory."""
    global _prospect_results, _prospect_stats
    tmp = _jobs[job_id].get("tmp_file", "")
    # Result file is next to the companies temp file, named _prospect_results_<job_id>.json
    result_path = Path(BASE_DIR / f"_prospect_results_{job_id}.json")
    if not result_path.exists():
        return
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
        _prospect_results          = data.get("contacts", [])
        _prospect_stats            = data.get("stats", {})
        _jobs[job_id]["stats"]     = _prospect_stats
        _jobs[job_id]["contacts"]  = len(_prospect_results)
        result_path.unlink(missing_ok=True)
    except Exception:
        logger.exception("Failed to load prospect results for job_id=%s", job_id)

@app.post("/prospect/estimate")
async def prospect_estimate(request: Request, current_user: dict = Depends(oracle_auth.require_analyst)):
    data = await request.json()
    companies = [c.strip() for c in (data.get("companies") or []) if c and c.strip()]

    if not companies:
        return JSONResponse({"error": "No companies provided"}, status_code=400)

    # Count hits across both oracle company_contacts and contacts table — same DB
    db_hits = 0
    try:
        for name in companies:
            row = oracle_db.get_company_by_name(name)
            if row and oracle_db.get_contacts_for_company(row["id"]):
                db_hits += 1
    except Exception:
        logger.warning("DB hit count failed during prospect estimate", exc_info=True)

    apollo_needed = max(len(companies) - db_hits, 0)
    est_seconds   = db_hits * 0.5 + apollo_needed * 2.5

    return {
        "companies":      len(companies),
        "db_hits":        db_hits,
        "apollo_credits": apollo_needed,
        "est_seconds":    round(est_seconds),
    }

@app.post("/prospect/db-search")
async def prospect_db_search(request: Request, current_user: dict = Depends(oracle_auth.require_analyst)):
    """Synchronous DB-only search — oracle SQLite contacts + PG master."""
    data      = await request.json()
    companies = [c.strip() for c in (data.get("companies") or []) if c and c.strip()]

    if not companies:
        return JSONResponse({"error": "No companies provided"}, status_code=400)

    all_contacts: list = []
    per_company: dict  = {}

    for name in companies:
        found: list = []

        # 1. Oracle Intent PostgreSQL contact store
        try:
            row = oracle_db.get_company_by_name(name)
            if row:
                contacts = oracle_db.get_contacts_for_company(row["id"])
                for c in contacts:
                    found.append({
                        "first_name":              c.get("first_name", ""),
                        "last_name":               c.get("last_name", ""),
                        "company":                 name,
                        "job_title":               c.get("title", ""),
                        "email":                   c.get("email", ""),
                        "email_validation_status": "",
                        "linkedin_url":            c.get("linkedin_url", ""),
                        "domain":                  row.get("domain", ""),
                        "source":                  c.get("source", "oracle_db"),
                    })
        except Exception:
            logger.warning("Oracle DB lookup failed for company '%s'", name, exc_info=True)

        # 2. Contacts table (280k-contacts-db) if oracle company_contacts came up empty
        if not found:
            try:
                conn = psycopg2.connect(PG_MASTER_CONNECTION_STRING, connect_timeout=5)
                with conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            """
                            SELECT "FirstName", "LastName", "Title", "Validated_Email",
                                   "Validated_Email_Status", "LinkedIn_URL__c",
                                   "LinkedIn_URL_Enriched", "Domain", "Existing_Company"
                            FROM contacts
                            WHERE  LOWER("Existing_Company") LIKE %s
                              AND  "Validated_Email" IS NOT NULL
                              AND  "Validated_Email" != ''
                            ORDER  BY "Validated_Email_Status" ASC
                            LIMIT  50
                            """,
                            (f"%{name.lower()}%",),
                        )
                        for r in cur.fetchall():
                            found.append({
                                "first_name":              r.get("FirstName", ""),
                                "last_name":               r.get("LastName", ""),
                                "company":                 name,
                                "job_title":               r.get("Title", ""),
                                "email":                   r.get("Validated_Email", ""),
                                "email_validation_status": r.get("Validated_Email_Status", ""),
                                "linkedin_url":            r.get("LinkedIn_URL__c") or r.get("LinkedIn_URL_Enriched") or "",
                                "domain":                  r.get("Domain", ""),
                                "source":                  "contacts_db",
                            })
                conn.close()
            except Exception:
                logger.warning("Master contacts DB lookup failed for company '%s'", name, exc_info=True)

        per_company[name] = len(found)
        all_contacts.extend(found)

    global _prospect_results, _prospect_stats
    _prospect_results = all_contacts
    _prospect_stats   = {
        "total_companies": len(companies),
        "pg_hits":         sum(1 for v in per_company.values() if v > 0),
        "apollo_searched": 0,
        "total_contacts":  len(all_contacts),
    }

    return {
        "total_contacts":   len(all_contacts),
        "companies_found":  sum(1 for v in per_company.values() if v > 0),
        "per_company":      per_company,
        "contacts":         all_contacts,
    }

@app.post("/prospect/run")
async def prospect_run(request: Request, current_user: dict = Depends(oracle_auth.require_analyst)):
    """Launch Apollo prospecting as a subprocess; returns job_id for SSE streaming."""
    data = await request.json()
    companies       = [c.strip() for c in (data.get("companies") or []) if c and c.strip()]
    max_per_company = int(data.get("max_per_company", 25))

    if not companies:
        return JSONResponse({"error": "No companies provided"}, status_code=400)

    running = _running_jobs()
    if running:
        return JSONResponse(
            {"error": "Another job is already running.", "running_job_id": running[0]},
            status_code=409,
        )

    if not APOLLO_API_KEY:
        return JSONResponse(
            {"error": "APOLLO_API_KEY is not configured in .env"},
            status_code=400,
        )

    _cleanup_old_jobs()
    job_id, q = _make_job()

    # Write company list to a temp file so the subprocess can read it
    tmp_file = BASE_DIR / f"_prospect_{job_id}.txt"
    tmp_file.write_text("\n".join(companies), encoding="utf-8")

    cmd = [
        sys.executable,
        str(BASE_DIR / "prospect_runner.py"),
        "--companies-file", str(tmp_file),
        "--max-per-company", str(max_per_company),
        "--job-id", job_id,
    ]

    env = os.environ.copy()
    env["APOLLO_API_KEY"]              = APOLLO_API_KEY
    env["PG_MASTER_CONNECTION_STRING"] = PG_MASTER_CONNECTION_STRING
    env["ORACLE_PG_DSN"]               = PG_MASTER_CONNECTION_STRING  # same DB

    _jobs[job_id] = {
        "process":   None,
        "queue":     q,
        "status":    "running",
        "exit_code": None,
        "type":      "prospect",
        "stats":     {},
        "contacts":  0,
        "tmp_file":  str(tmp_file),
    }
    _launch_subprocess(cmd, cwd=BASE_DIR, env=env, job_id=job_id, q=q)
    return {"job_id": job_id}

@app.get("/prospect/status/{job_id}")
async def prospect_status(job_id: str, current_user: dict = Depends(oracle_auth.require_user)):
    if job_id not in _jobs:
        return JSONResponse({"status": "not_found"}, status_code=404)
    j = _jobs[job_id]
    return {
        "status":   j["status"],
        "stats":    j.get("stats", {}),
        "contacts": j.get("contacts", 0),
    }

@app.get("/prospect/results")
async def prospect_results(current_user: dict = Depends(oracle_auth.require_analyst)):
    if not _prospect_results:
        return JSONResponse({"error": "No prospect results yet — run a search first"}, status_code=404)
    return JSONResponse(_prospect_results)

@app.get("/prospect/download/csv")
async def prospect_download_csv(current_user: dict = Depends(oracle_auth.require_analyst)):
    if not _prospect_results:
        return JSONResponse({"error": "No results to download"}, status_code=404)
    buf = io.StringIO()
    fieldnames = ["first_name", "last_name", "company", "job_title",
                  "email", "email_validation_status", "linkedin_url", "domain", "source"]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(_prospect_results)
    filename = f"prospect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.get("/prospect/download/excel")
async def prospect_download_excel(current_user: dict = Depends(oracle_auth.require_analyst)):
    if not _prospect_results:
        return JSONResponse({"error": "No results to download"}, status_code=404)
    df  = pd.DataFrame(_prospect_results)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    filename = f"prospect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# ═══ DASHBOARD — combined stats for the React frontend ════════════════════════
# dashboard ttl cache — 60 s so 5-s polling never hits the db
_dashboard_cache: Dict[str, object] = {}
_DASHBOARD_TTL = 60  # seconds

def _invalidate_dashboard_cache() -> None:
    _dashboard_cache.clear()

def _fetch_dashboard_stats() -> dict:
    """Run all dashboard queries in a SINGLE connection, using fast subqueries."""
    companies_tracked = contacts_enriched = total_signals = 0
    implementing = evaluating = researching = pushed_to_hubspot = 0
    try:
        with oracle_db.db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT
                    (SELECT COUNT(*) FROM companies)                                            AS companies_tracked,
                    (SELECT COUNT(*) FROM company_contacts)                                     AS contacts_enriched,
                    (SELECT COUNT(*) FROM oracle_signals)                                       AS total_signals,
                    (SELECT COUNT(DISTINCT CASE WHEN phase='implementing' THEN company_id END)
                     FROM oracle_signals)                                                       AS implementing,
                    (SELECT COUNT(DISTINCT CASE WHEN phase='evaluating'   THEN company_id END)
                     FROM oracle_signals)                                                       AS evaluating,
                    (SELECT COUNT(DISTINCT CASE WHEN phase='researching'  THEN company_id END)
                     FROM oracle_signals)                                                       AS researching,
                    (SELECT COUNT(*) FROM company_contacts
                     WHERE status = 'pushed_to_hubspot')                                        AS pushed_to_hubspot
            """)
            row = cur.fetchone()
            if row:
                companies_tracked = int(row["companies_tracked"] or 0)
                contacts_enriched = int(row["contacts_enriched"] or 0)
                total_signals     = int(row["total_signals"]     or 0)
                implementing      = int(row["implementing"]      or 0)
                evaluating        = int(row["evaluating"]        or 0)
                researching       = int(row["researching"]       or 0)
                pushed_to_hubspot = int(row["pushed_to_hubspot"] or 0)
    except Exception:
        logger.warning("Dashboard query failed — returning zeros", exc_info=True)
    return dict(
        companies_tracked=companies_tracked,
        contacts_enriched=contacts_enriched,
        total_signals=total_signals,
        implementing=implementing,
        evaluating=evaluating,
        researching=researching,
        pushed_to_hubspot=pushed_to_hubspot,
    )

@app.get("/api/dashboard")
async def api_dashboard(current_user: dict = Depends(oracle_auth.require_user)):
    """Single endpoint that powers the Dashboard page KPI cards.
    Results are cached for 60 s so the 5-second frontend poll never hits the DB
    more than once per minute.
    """
    cached = _dashboard_cache.get("stats")
    if not cached or (time.time() - cached["ts"]) > _DASHBOARD_TTL:
        stats = _fetch_dashboard_stats()
        _dashboard_cache["stats"] = {"ts": time.time(), "data": stats}
    else:
        stats = cached["data"]

    return {
        "companies_tracked": stats["companies_tracked"],
        "contacts_enriched": stats["contacts_enriched"],
        "intent_signals":    stats["total_signals"],
        "pushed_to_hubspot": stats["pushed_to_hubspot"],
        "implementing":      stats["implementing"],
        "evaluating":        stats["evaluating"],
        "researching":       stats["researching"],
        "scan_status":       _scan_current_status(),
    }

@app.get("/api/contacts")
async def api_contacts(
    company: str = "",
    search:  str = "",
    limit:   int = 500,
    offset:  int = 0,
    current_user: dict = Depends(oracle_auth.require_user),
):
    """Enriched contacts — paginated (default 500 per page).
    Pass ?search=name/title/email for server-side filtering.
    Pass ?limit=0 to fetch all (use with caution on large datasets).
    """
    try:
        page_limit = min(limit, 5000) if limit > 0 else 5000

        with oracle_db.db_cursor(commit=False) as cur:
            conditions = []
            params: List = []

            if company:
                conditions.append("LOWER(c.name) LIKE %s")
                params.append(f"%{company.lower()}%")
            if search:
                conditions.append(
                    "(LOWER(cc.first_name || ' ' || cc.last_name) LIKE %s "
                    " OR LOWER(COALESCE(cc.title,'')) LIKE %s "
                    " OR LOWER(COALESCE(cc.email,'')) LIKE %s "
                    " OR LOWER(COALESCE(c.name,'')) LIKE %s)"
                )
                s = f"%{search.lower()}%"
                params.extend([s, s, s, s])

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            # total count (fast — uses indexes)
            cur.execute(
                f"""SELECT COUNT(*) AS n
                    FROM company_contacts cc
                    JOIN companies c ON cc.company_id = c.id
                    {where}""",
                params,
            )
            total = cur.fetchone()["n"]

            # paginated rows
            cur.execute(
                f"""SELECT cc.id, cc.first_name, cc.last_name, cc.title,
                           cc.email, cc.linkedin_url, cc.confidence,
                           cc.is_target, cc.source, cc.email_source,
                           cc.email_validation_status, cc.email_prediction_pattern,
                           cc.fetched_at::text AS created_at,
                           c.name AS company_name, c.domain AS company_domain
                    FROM company_contacts cc
                    JOIN companies c ON cc.company_id = c.id
                    {where}
                    ORDER BY cc.is_target DESC, cc.confidence DESC
                    LIMIT %s OFFSET %s""",
                params + [page_limit, offset],
            )
            rows = [dict(r) for r in cur.fetchall()]

        return JSONResponse({"total": total, "offset": offset, "limit": page_limit, "rows": rows})
    except Exception as e:
        logger.exception("Unhandled error in GET /api/contacts")
        return JSONResponse({"error": str(e)}, status_code=500)

# ═══ STARTUP ══════════════════════════════════════════════════════════════════
# SIGNALS  /  REVIEW QUEUE  /  REPORTING
# ---
@app.get("/api/signals")
async def api_signals(limit: int = 200, current_user: dict = Depends(oracle_auth.require_user)):
    """All Oracle intent signals with company name, newest first."""
    try:
        with oracle_db.db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT s.id, s.oracle_product, s.phase, s.source, s.signal_type,
                       s.job_title, s.evidence, s.url, s.confidence,
                       s.detected_at::text AS detected_at,
                       c.name AS company_name
                FROM oracle_signals s
                JOIN companies c ON s.company_id = c.id
                ORDER BY s.detected_at DESC, s.confidence DESC
                LIMIT %s
            """, (min(limit, 500),))
            rows = [dict(r) for r in cur.fetchall()]
        return JSONResponse(rows)
    except Exception as e:
        logger.exception("Unhandled error in GET /api/signals")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/contacts/push-hubspot")
async def push_contact_to_hubspot_endpoint(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    """Push a single contact to HubSpot using email-based upsert."""
    body = await request.json()
    result = await hs_push.push_contact_to_hubspot(body)
    if result["ok"]:
        # Update local status
        contact_id = body.get("id")
        if contact_id:
            with oracle_db.db_cursor() as cur:
                cur.execute(
                    "UPDATE company_contacts SET status='pushed_to_hubspot', hubspot_id=%s, hubspot_synced_at=NOW() WHERE id=%s",
                    (result.get("hubspot_id"), contact_id),
                )
        log_audit(current_user, "push_to_hubspot", "contact", str(body.get("id","")),
                  new_value={"hubspot_id": result.get("hubspot_id"), "action": result.get("action")})
    return result

@app.get("/api/reporting")
async def api_reporting(current_user: dict = Depends(oracle_auth.require_user)):
    """Reporting stats: company KPIs, contact KPIs, phase distribution, scan-run history."""
    companies = list(oracle_db.get_all_companies_with_signals(run_id=0))
    companies = _annotate_and_sort(companies)

    phase_counter: Counter = Counter()
    source_counter: Counter = Counter()
    total_signals = 0
    for c in companies:
        for p in (c.get("phases") or []):
            if p: phase_counter[p] += 1
        for s in (c.get("sources") or []):
            if s: source_counter[s] += 1
        total_signals += int(c.get("signal_count") or 0)

    scan_runs = oracle_db.get_recent_scan_runs(10)
    total_src = sum(source_counter.values()) or 1

    # ── Extended KPIs ──────────────────────────────────────────────────────────
    with oracle_db.db_cursor(commit=False) as cur:

        # Companies by target product
        cur.execute("""
            SELECT COALESCE(target_product, 'Unknown') AS product, COUNT(*) AS cnt
            FROM companies
            GROUP BY target_product
            ORDER BY cnt DESC
        """)
        companies_by_product = [{"product": r["product"], "count": int(r["cnt"])} for r in cur.fetchall()]

        # Companies with / without contacts
        cur.execute("""
            SELECT
                COUNT(*)                                              AS total,
                COUNT(*) FILTER (WHERE contact_count > 0)            AS with_contacts,
                COUNT(*) FILTER (WHERE contact_count = 0
                                    OR contact_count IS NULL)        AS without_contacts
            FROM companies
        """)
        co = cur.fetchone()
        company_contact_stats = {
            "total":            int(co["total"] or 0),
            "with_contacts":    int(co["with_contacts"] or 0),
            "without_contacts": int(co["without_contacts"] or 0),
        }

        # Companies covered per source
        cur.execute("""
            SELECT
                COUNT(DISTINCT CASE WHEN source IN ('contacts_master','master_leads','280k_master_db','master db') THEN company_id END) AS contacts_master,
                COUNT(DISTINCT CASE WHEN source IN ('apollo','apollo.io') THEN company_id END)                        AS apollo,
                COUNT(DISTINCT CASE WHEN source IN ('zoominfo','zoom info','zoom_info') THEN company_id END)          AS zoominfo
            FROM company_contacts
        """)
        sc = cur.fetchone()
        company_coverage_by_source = {
            "contacts_master": int(sc["contacts_master"] or 0),
            "apollo":          int(sc["apollo"] or 0),
            "zoominfo":        int(sc["zoominfo"] or 0),
        }

        # Contact reach breakdown
        cur.execute("""
            SELECT
                COUNT(*)                                                            AS total,
                COUNT(*) FILTER (
                    WHERE (email IS NOT NULL AND email <> '')
                      AND (linkedin_url IS NOT NULL AND linkedin_url <> ''))        AS email_and_linkedin,
                COUNT(*) FILTER (
                    WHERE (email IS NOT NULL AND email <> '')
                      AND (linkedin_url IS NULL OR linkedin_url = ''))             AS email_only,
                COUNT(*) FILTER (
                    WHERE (email IS NULL OR email = '')
                      AND (linkedin_url IS NOT NULL AND linkedin_url <> ''))       AS linkedin_only,
                COUNT(*) FILTER (
                    WHERE (email IS NULL OR email = '')
                      AND (linkedin_url IS NULL OR linkedin_url = ''))             AS no_reach,
                COUNT(*) FILTER (WHERE email_validation_status = 'valid')          AS valid_emails
            FROM company_contacts
        """)
        ct = cur.fetchone()
        contact_reach_stats = {
            "total":              int(ct["total"] or 0),
            "email_and_linkedin": int(ct["email_and_linkedin"] or 0),
            "email_only":         int(ct["email_only"] or 0),
            "linkedin_only":      int(ct["linkedin_only"] or 0),
            "no_reach":           int(ct["no_reach"] or 0),
            "valid_emails":       int(ct["valid_emails"] or 0),
        }

        # Contacts by source
        cur.execute("""
            SELECT
                CASE
                    WHEN source IN ('apollo', 'apollo.io') THEN 'Apollo'
                    WHEN source IN ('contacts_master', 'master_leads', '280k_master_db', 'master db') THEN 'Contacts Master'
                    WHEN source IN ('zoominfo', 'ZoomInfo') THEN 'ZoomInfo'
                    WHEN source IN ('phantombuster', 'PhantomBuster') THEN 'PhantomBuster'
                    ELSE COALESCE(NULLIF(TRIM(source), ''), 'Other')
                END AS source_label,
                COUNT(*) AS cnt
            FROM company_contacts
            GROUP BY source_label
            ORDER BY cnt DESC
        """)
        total_contacts = contact_reach_stats["total"] or 1
        contact_by_source = [
            {"label": r["source_label"], "count": int(r["cnt"]),
             "pct": round(int(r["cnt"]) / total_contacts * 100, 1)}
            for r in cur.fetchall()
        ]

    return {
        "total_companies":       company_contact_stats["total"],
        "total_signals":         total_signals,
        "phases":                dict(phase_counter.most_common()),
        "sources": [
            {"label": k, "count": v, "pct": round(v / total_src * 100)}
            for k, v in source_counter.most_common(6)
        ],
        "scan_runs":             [dict(r) for r in scan_runs],
        "companies_by_product":  companies_by_product,
        "company_contact_stats": company_contact_stats,
        "company_coverage_by_source": company_coverage_by_source,
        "contact_reach_stats":   contact_reach_stats,
        "contact_by_source":     contact_by_source,
    }

@app.get("/api/scan/{run_id}/enrichment-plan")
async def scan_enrichment_plan(
    run_id: int,
    max_per: int = 10,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    """
    For each company in a scan run, classify enrichment status:
      has_contacts        — already has contacts with email/linkedin in DB
      from_contacts_master — found in Salesforce CRM export (free, no API cost)
      needs_apollo         — not found anywhere; must use Apollo/ZoomInfo credits
    Also returns a summary with estimated Apollo credit cost.
    """
    try:
        companies = list(oracle_db.get_all_companies_with_signals(run_id=run_id))
        result = []
        has_ct = from_cm = needs_api = 0

        for c in companies:
            cid  = int(c["id"])
            name = str(c["name"])

            # contact_count is already joined into the company record by the SQL query —
            # no extra DB round-trip needed.  It counts email-bearing contacts only, which
            # is the right gate: if a company was enriched before (even in a prior run)
            # this will be > 0 and we skip Apollo for it.
            existing_ct = int(c.get("contact_count") or 0)

            if existing_ct > 0:
                status        = "has_contacts"
                contact_count = existing_ct
                has_ct       += 1
            else:
                # Check contacts_master (Salesforce CRM — no API cost)
                cm_rows = oracle_db.get_master_leads_by_company(name)
                if cm_rows:
                    status        = "from_contacts_master"
                    contact_count = len(cm_rows)
                    from_cm      += 1
                else:
                    status        = "needs_apollo"
                    contact_count = 0
                    needs_api    += 1

            result.append({
                "id":             cid,
                "name":           name,
                "domain":         c.get("domain"),
                "industry":       c.get("industry"),
                "signal_count":   int(c.get("signal_count") or 0),
                "target_product": c.get("target_product"),
                "status":         status,
                "contact_count":  contact_count,
                "first_seen":     str(c["first_seen"]) if c.get("first_seen") else None,
            })

        return {
            "run_id":    run_id,
            "companies": result,
            "summary": {
                "total":                len(result),
                "has_contacts":         has_ct,
                "from_contacts_master": from_cm,
                "needs_apollo":         needs_api,
                "est_credits":          needs_api * max_per,
            },
        }
    except Exception as e:
        logger.exception("scan enrichment-plan failed for run_id=%s", run_id)
        return JSONResponse({"error": str(e)}, status_code=500)


# enrichment endpoints
@app.get("/api/enrich/pending")
async def enrich_pending(limit: int = 500, current_user: dict = Depends(oracle_auth.require_analyst)):
    """Companies awaiting enrichment — for the pick-companies UI in the pre-flight modal."""
    try:
        rows = oracle_db.get_companies_needing_enrichment(min(limit, 2000))
        return {"total": len(rows), "companies": jsonable_encoder([dict(r) for r in rows])}
    except Exception:
        logger.exception("Unhandled error in GET /api/enrich/pending")
        return JSONResponse({"error": "Internal server error"}, status_code=500)

@app.get("/api/enrich/preflight")
async def enrich_preflight(current_user: dict = Depends(oracle_auth.require_analyst)):
    """
    Pre-flight estimate: how many companies need enrichment, how many can be served
    from contacts_master (free), how many need Apollo (credit cost), and estimated time.
    """
    try:
        companies = oracle_db.get_companies_needing_enrichment(5000)
        total = len(companies)

        if not total:
            return {
                "total": 0, "from_contacts_master": 0, "need_apollo": 0,
                "est_credits": 0, "est_minutes": 0,
                "apollo_configured": bool(APOLLO_API_KEY),
                "zerobounce_configured": bool(ZEROBOUNCE_API_KEY),
                "zoominfo_configured": bool(ZOOMINFO_USERNAME and ZOOMINFO_PASSWORD),
            }

        # All companies go through Apollo — contacts_master is checked first (no credit cost)
        need_apollo = total

        # Apollo credit estimate: 2 credits per company (targeted pass + possible broad pass)
        est_credits = need_apollo * 2
        # Time estimate: ~3s per company (1.2s × 2 passes + ZB overhead)
        est_seconds = need_apollo * 3
        est_minutes = max(0.5, round(est_seconds / 60, 1))

        return {
            "total":               total,
            "from_contacts_master": 0,
            "need_apollo":         need_apollo,
            "est_credits":         est_credits,
            "est_minutes":         est_minutes,
            "apollo_configured":   bool(APOLLO_API_KEY),
            "zerobounce_configured": bool(ZEROBOUNCE_API_KEY),
            "zoominfo_configured": bool(ZOOMINFO_USERNAME and ZOOMINFO_PASSWORD),
        }
    except Exception as e:
        logger.exception("Unhandled error in GET /api/enrich/preflight")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/enrich/start")
async def enrich_start(request: Request, current_user: dict = Depends(oracle_auth.require_analyst)):
    """Launch the Apollo enrichment subprocess for companies without contacts."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    limit           = int(data.get("limit", 50))
    max_per_company = int(data.get("max_per_company", 10))
    batch_size      = data.get("batch_size")
    role_filters    = data.get("role_filters") or None
    provider        = str(data.get("provider", "apollo")).lower().strip()
    company_ids     = data.get("company_ids") or None

    if batch_size:
        batch_size = int(batch_size)
    if company_ids:
        try:
            company_ids = [int(x) for x in company_ids]
        except (TypeError, ValueError):
            return JSONResponse({"error": "company_ids must be a list of integers"}, status_code=400)

    if provider == "zoominfo":
        if not (ZOOMINFO_USERNAME and ZOOMINFO_PASSWORD):
            return JSONResponse({"error": "ZoomInfo not configured. Add ZOOMINFO_USERNAME and ZOOMINFO_PASSWORD to oracle_intent_engine/.env"}, status_code=400)
    elif not APOLLO_API_KEY:
        return JSONResponse({"error": "Apollo API key not configured. Add APOLLO_API_KEY to oracle_intent_engine/.env"}, status_code=400)

    started = _start_enrich_subprocess(
        limit=limit,
        max_per_company=max_per_company,
        batch_size=batch_size,
        role_filters=role_filters,
        provider=provider,
        company_ids=company_ids,
    )
    if not started:
        return JSONResponse({"error": "Enrichment already running"}, status_code=409)
    return {"started": True, "limit": limit, "max_per_company": max_per_company,
            "batch_size": batch_size, "provider": provider,
            "company_ids_count": len(company_ids) if company_ids else 0,
            "role_filters_count": len(role_filters) if role_filters else 0}

@app.post("/api/enrich/stop")
async def enrich_stop(current_user: dict = Depends(oracle_auth.require_analyst)):
    _stop_enrich_subprocess()
    return {"stopped": True}

@app.get("/api/enrich/status")
async def enrich_status(current_user: dict = Depends(oracle_auth.require_user)):
    return _enrich_current_status()

@app.get("/api/enrich/log")
async def enrich_log(current_user: dict = Depends(oracle_auth.require_user)):
    return _enrich_get_log()

@app.get("/api/enrich/stats")
async def enrich_stats(current_user: dict = Depends(oracle_auth.require_user)):
    """Returns enrichment readiness: how many companies need enrichment."""
    try:
        stats = oracle_db.get_enrichment_stats()
        return {
            **stats,
            "apollo_configured":     bool(APOLLO_API_KEY),
            "zerobounce_configured": bool(ZEROBOUNCE_API_KEY),
        }
    except Exception as e:
        logger.exception("Unhandled error in GET /api/enrich/stats")
        return {"error": str(e)}

# ---
# ═══ AUTH / RBAC ══════════════════════════════════════════════════════════════
@app.post("/api/auth/register")
@limiter.limit("10/minute")
async def auth_register(request: Request):
    """Create a new user. First user ever becomes owner automatically."""
    data = await request.json()
    email    = (data.get("email") or "").strip().lower()
    name     = (data.get("name")  or "").strip()
    password = (data.get("password") or "").strip()
    if not email or not password:
        return JSONResponse({"error": "email and password are required"}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)
    if oracle_auth.get_user_by_email(email):
        return JSONResponse({"error": "Registration failed. Please try again or contact support."}, status_code=409)
    # role is always viewer for self-registration — admins/owner elevate via /api/users PATCH
    user  = oracle_auth.create_user(email, name, password, role="viewer")
    token = oracle_auth.create_token(user["id"], user["email"], user["role"])
    return {"token": token, "user": {k: v for k, v in user.items() if k != "password_hash"}}

@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def auth_login(request: Request):
    data     = await request.json()
    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    user = oracle_auth.get_user_by_email(email)
    if not user or not oracle_auth.verify_password(password, user["password_hash"]):
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)
    oracle_auth.update_last_login(user["id"])
    token = oracle_auth.create_token(user["id"], user["email"], user["role"])
    safe  = {k: v for k, v in user.items() if k != "password_hash"}
    return {"token": token, "user": safe}

@app.get("/api/auth/me")
async def auth_me(current_user: dict = Depends(oracle_auth.require_user)):
    user = oracle_auth.get_user_by_id(current_user["id"])
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    return {k: v for k, v in user.items() if k != "password_hash"}

@app.post("/api/auth/change-password")
async def auth_change_password(request: Request,
                                current_user: dict = Depends(oracle_auth.require_user)):
    data = await request.json()
    old  = data.get("old_password", "")
    new  = data.get("new_password", "")
    user = oracle_auth.get_user_by_id(current_user["id"])
    if not oracle_auth.verify_password(old, user["password_hash"]):
        return JSONResponse({"error": "Current password incorrect"}, status_code=400)
    if len(new) < 8:
        return JSONResponse({"error": "New password must be at least 8 characters"}, status_code=400)
    oracle_auth.change_password(current_user["id"], new)
    log_audit(current_user, "change_password", "user", str(current_user["id"]))
    return {"ok": True}

# ═══ USER MANAGEMENT  (admin / owner only) ════════════════════════════════════
@app.get("/api/users")
async def list_users(current_user: dict = Depends(oracle_auth.require_admin)):
    return oracle_auth.list_users()

@app.patch("/api/users/{user_id}")
async def update_user(user_id: int, request: Request,
                       current_user: dict = Depends(oracle_auth.require_admin)):
    data    = await request.json()
    updated = oracle_auth.update_user(user_id, data, caller_role=current_user["role"])
    log_audit(current_user, "update_user", "user", str(user_id), new_value=data)
    return updated

@app.delete("/api/users/{user_id}")
async def deactivate_user(user_id: int,
                           current_user: dict = Depends(oracle_auth.require_admin)):
    if user_id == current_user["id"]:
        return JSONResponse({"error": "Cannot deactivate yourself"}, status_code=400)
    oracle_auth.update_user(user_id, {"is_active": False}, caller_role=current_user["role"])
    log_audit(current_user, "deactivate_user", "user", str(user_id))
    return {"ok": True}

# ═══ AUDIT LOGS ═══════════════════════════════════════════════════════════════
@app.get("/api/audit-logs")
async def api_audit_logs(
    entity_type: str = "", entity_id: str = "",
    user_email: str = "", action: str = "",
    limit: int = 200, offset: int = 0,
    current_user: dict = Depends(oracle_auth.require_user),
):
    return get_audit_logs(entity_type, entity_id, user_email, action, limit, offset)

# ═══ TECHNOLOGY PROFILES ══════════════════════════════════════════════════════
@app.get("/api/technology-profiles")
async def api_list_profiles(active_only: bool = False, current_user: dict = Depends(oracle_auth.require_user)):
    return tp_mod.list_profiles(active_only=active_only)

@app.get("/api/technology-profiles/{profile_id}")
async def api_get_profile(profile_id: int, current_user: dict = Depends(oracle_auth.require_user)):
    p = tp_mod.get_profile(profile_id)
    if not p:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return p

@app.post("/api/technology-profiles")
async def api_create_profile(request: Request,
                               current_user: dict = Depends(oracle_auth.require_analyst)):
    data    = await request.json()
    profile = tp_mod.create_profile(**{k: v for k, v in data.items()
                                        if k in ("name","description","keywords","target_websites",
                                                  "competitor_domains","partner_domains",
                                                  "manufacturer_domain","oracle_products")})
    log_audit(current_user, "create", "technology_profile", str(profile["id"]), new_value=data)
    return profile

@app.patch("/api/technology-profiles/{profile_id}")
async def api_update_profile(profile_id: int, request: Request,
                               current_user: dict = Depends(oracle_auth.require_analyst)):
    data    = await request.json()
    updated = tp_mod.update_profile(profile_id, data)
    log_audit(current_user, "update", "technology_profile", str(profile_id), new_value=data)
    return updated

@app.delete("/api/technology-profiles/{profile_id}")
async def api_delete_profile(profile_id: int,
                               current_user: dict = Depends(oracle_auth.require_admin)):
    tp_mod.delete_profile(profile_id)
    log_audit(current_user, "delete", "technology_profile", str(profile_id))
    return {"ok": True}

# product taxonomy
@app.get("/api/technology-profiles/{profile_id}/taxonomy")
async def api_list_taxonomy(profile_id: int, current_user: dict = Depends(oracle_auth.require_user)):
    return tp_mod.list_taxonomy(profile_id)

@app.post("/api/technology-profiles/{profile_id}/taxonomy")
async def api_create_taxonomy(profile_id: int, request: Request,
                               current_user: dict = Depends(oracle_auth.require_analyst)):
    data = await request.json()
    row  = tp_mod.create_taxonomy(
        profile_id,
        canonical_name    = data.get("canonical_name", ""),
        aliases           = data.get("aliases", []),
        category          = data.get("category", ""),
        confidence_weight = float(data.get("confidence_weight", 1.0)),
    )
    log_audit(current_user, "create", "product_taxonomy", str(row["id"]), new_value=data)
    return row

@app.patch("/api/taxonomy/{taxonomy_id}")
async def api_update_taxonomy(taxonomy_id: int, request: Request,
                               current_user: dict = Depends(oracle_auth.require_analyst)):
    data    = await request.json()
    updated = tp_mod.update_taxonomy(taxonomy_id, data)
    log_audit(current_user, "update", "product_taxonomy", str(taxonomy_id), new_value=data)
    return updated

@app.delete("/api/taxonomy/{taxonomy_id}")
async def api_delete_taxonomy(taxonomy_id: int,
                               current_user: dict = Depends(oracle_auth.require_admin)):
    tp_mod.delete_taxonomy(taxonomy_id)
    log_audit(current_user, "delete", "product_taxonomy", str(taxonomy_id))
    return {"ok": True}

# ═══ EVENTS INTELLIGENCE ══════════════════════════════════════════════════════
@app.get("/api/events")
async def api_list_events(profile_id: int = 0, limit: int = 100, current_user: dict = Depends(oracle_auth.require_user)):
    return events_mod.list_events(profile_id or None, limit)

@app.post("/api/events")
async def api_create_event(request: Request,
                            current_user: dict = Depends(oracle_auth.require_analyst)):
    data  = await request.json()
    event = events_mod.create_event(**{k: v for k, v in data.items()
                                        if k in ("name","event_type","technology_profile_id",
                                                  "location","event_date","description","attendee_count")})
    log_audit(current_user, "create", "event", str(event["id"]), new_value=data)
    return event

@app.patch("/api/events/{event_id}")
async def api_update_event(event_id: int, request: Request,
                            current_user: dict = Depends(oracle_auth.require_analyst)):
    data    = await request.json()
    updated = events_mod.update_event(event_id, data)
    log_audit(current_user, "update", "event", str(event_id), new_value=data)
    return updated

@app.delete("/api/events/{event_id}")
async def api_delete_event(event_id: int,
                            current_user: dict = Depends(oracle_auth.require_admin)):
    events_mod.delete_event(event_id)
    log_audit(current_user, "delete", "event", str(event_id))
    return {"ok": True}

@app.get("/api/events/{event_id}/attendees")
async def api_event_attendees(event_id: int, current_user: dict = Depends(oracle_auth.require_user)):
    return events_mod.list_attendees(event_id)

@app.post("/api/events/{event_id}/attendees")
async def api_add_attendee(event_id: int, request: Request,
                            current_user: dict = Depends(oracle_auth.require_analyst)):
    data = await request.json()
    row  = events_mod.add_attendee(event_id, int(data["contact_id"]), data.get("role", "attendee"))
    log_audit(current_user, "add_attendee", "event", str(event_id),
              new_value={"contact_id": data["contact_id"]})
    return row

@app.delete("/api/events/{event_id}/attendees/{contact_id}")
async def api_remove_attendee(event_id: int, contact_id: int,
                               current_user: dict = Depends(oracle_auth.require_analyst)):
    events_mod.remove_attendee(event_id, contact_id)
    return {"ok": True}

# ═══ MANUFACTURER INTELLIGENCE ════════════════════════════════════════════════
@app.get("/api/manufacturer-contacts")
async def api_list_mfr(profile_id: int = 0, limit: int = 200, current_user: dict = Depends(oracle_auth.require_user)):
    return mfr_mod.list_manufacturer_contacts(profile_id or None, limit)

@app.post("/api/manufacturer-contacts")
async def api_create_mfr(request: Request,
                          current_user: dict = Depends(oracle_auth.require_analyst)):
    data    = await request.json()
    contact = mfr_mod.create_manufacturer_contact(data)
    log_audit(current_user, "create", "manufacturer_contact", str(contact["id"]), new_value=data)
    return contact

@app.patch("/api/manufacturer-contacts/{contact_id}")
async def api_update_mfr(contact_id: int, request: Request,
                          current_user: dict = Depends(oracle_auth.require_analyst)):
    data    = await request.json()
    updated = mfr_mod.update_manufacturer_contact(contact_id, data)
    log_audit(current_user, "update", "manufacturer_contact", str(contact_id), new_value=data)
    return updated

@app.delete("/api/manufacturer-contacts/{contact_id}")
async def api_delete_mfr(contact_id: int,
                          current_user: dict = Depends(oracle_auth.require_admin)):
    mfr_mod.delete_manufacturer_contact(contact_id)
    log_audit(current_user, "delete", "manufacturer_contact", str(contact_id))
    return {"ok": True}

@app.post("/api/manufacturer-contacts/{contact_id}/link/{company_id}")
async def api_link_mfr(contact_id: int, company_id: int, request: Request,
                        current_user: dict = Depends(oracle_auth.require_analyst)):
    data = await request.json()
    return mfr_mod.link_to_company(contact_id, company_id, data.get("link_type", "partner"))

@app.delete("/api/manufacturer-contacts/{contact_id}/link/{company_id}")
async def api_unlink_mfr(contact_id: int, company_id: int,
                          current_user: dict = Depends(oracle_auth.require_analyst)):
    mfr_mod.unlink_from_company(contact_id, company_id)
    return {"ok": True}

@app.get("/api/companies/{company_id}/manufacturer-contacts")
async def api_company_mfr(company_id: int, current_user: dict = Depends(oracle_auth.require_user)):
    return mfr_mod.get_company_manufacturer_contacts(company_id)

# ═══ LIST IMPORT ══════════════════════════════════════════════════════════════
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

@app.get("/api/import/fields/{entity_type}")
async def api_import_fields(entity_type: str, current_user: dict = Depends(oracle_auth.require_user)):
    raw = import_mod._FIELD_LISTS.get(entity_type.lower(), [])
    fields = [{"value": f["key"], "label": f["label"], "required": f.get("required", False)} for f in raw]
    return {"fields": fields}

@app.post("/api/import/parse-headers")
async def api_parse_headers(
    file: UploadFile = File(...),
    entity_type: str = Form("company"),
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "File exceeds 10 MB limit"}, status_code=413)
    return import_mod.parse_csv_headers(content, entity_type.lower())

@app.post("/api/import/upload")
async def api_import_upload(
    file: UploadFile = File(...),
    entity_type: str = Form("company"),
    mappings: str = Form("{}"),
    template_name: str = Form(""),
    template_id: int = Form(0),
    default_product: str = Form(""),
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    content  = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "File exceeds 10 MB limit"}, status_code=413)
    entity_type = entity_type.lower()
    mappings_dict = json.loads(mappings)
    if import_mod._is_xlsx(content):
        row_count = len(import_mod._parse_xlsx_rows(content))
    else:
        row_count = max(0, content.count(b"\n") - 1)

    batch = import_mod.create_batch(
        file_name    = file.filename,
        entity_type  = entity_type,
        record_count = row_count,
        template_id  = template_id or None,
    )

    # Save template if requested
    if template_name and mappings_dict:
        import_mod.save_template(template_name, entity_type, mappings_dict)

    result = import_mod.process_import(
        content, entity_type, mappings_dict, batch["id"],
        default_product=default_product,
        apollo_key=APOLLO_API_KEY,
        zerobounce_key=ZEROBOUNCE_API_KEY,
    )

    # Company imports automatically flow into the contact-enrichment pipeline
    # (same Oracle/IT/finance title criteria as the lead enrichment workflow).
    auto_enrich_started = False
    if entity_type == "company" and result.get("company_names") and APOLLO_API_KEY:
        try:
            ids = oracle_db.get_company_ids_by_names(result["company_names"])
            if ids:
                auto_enrich_started = _start_enrich_subprocess(
                    limit=len(ids), company_ids=ids,
                )
        except Exception:
            logger.exception("Auto-enrich after company import failed to start")

    return {"batch_id": batch["id"], **result, "auto_enrich_started": auto_enrich_started}

@app.get("/api/import/batches")
async def api_import_batches(limit: int = 50, current_user: dict = Depends(oracle_auth.require_user)):
    return import_mod.list_batches(limit)

@app.get("/api/import/templates")
async def api_import_templates(entity_type: str = "", current_user: dict = Depends(oracle_auth.require_user)):
    return import_mod.list_templates(entity_type)

@app.post("/api/import/templates")
async def api_save_template(request: Request,
                             current_user: dict = Depends(oracle_auth.require_analyst)):
    data = await request.json()
    return import_mod.save_template(
        data["name"], data["entity_type"], data["mappings"], current_user["id"]
    )

@app.delete("/api/import/templates/{template_id}")
async def api_delete_template(template_id: int,
                               current_user: dict = Depends(oracle_auth.require_analyst)):
    import_mod.delete_template(template_id)
    return {"ok": True}

# ═══ DATA QUALITY ENGINE ══════════════════════════════════════════════════════
@app.post("/api/dqe/check/company")
async def api_dqe_company(request: Request, current_user: dict = Depends(oracle_auth.require_user)):
    data   = await request.json()
    issues = dqe_mod.run_dqe_on_company(data)
    return {"issues": issues, "has_critical": any(i["severity"] == "critical" for i in issues)}

@app.post("/api/dqe/check/contact")
async def api_dqe_contact(request: Request, current_user: dict = Depends(oracle_auth.require_user)):
    data   = await request.json()
    issues = dqe_mod.run_dqe_on_contact(data)
    return {"issues": issues, "has_critical": any(i["severity"] == "critical" for i in issues)}

@app.post("/api/dqe/promote-staged")
async def api_promote_staged(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    data   = await request.json()
    limit  = int(data.get("limit", 100))
    result = dqe_mod.promote_staged_companies(limit)
    log_audit(current_user, "dqe_promote_staged", "company", "", new_value=result)
    return result

# ═══ COMPANY STATUS LIFECYCLE ═════════════════════════════════════════════════
ORACLE_PRODUCTS = [
    "JD Edwards", "Oracle Cloud ERP", "Oracle EBS", "Oracle HCM",
    "Oracle SCM", "Oracle EPM", "Oracle CX", "Oracle Database",
    "Oracle OCI", "Oracle Integration", "NetSuite", "Oracle (General)",
]

@app.patch("/api/companies/{company_id}/product")
async def api_company_product(
    company_id: int,
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    data    = await request.json()
    product = data.get("target_product", "").strip()
    oracle_db.set_company_target_product(company_id, product)
    _invalidate_companies_cache()
    log_audit(current_user, "set_target_product", "company", str(company_id),
              new_value={"target_product": product})
    return {"id": company_id, "target_product": product}

@app.get("/api/companies/products")
async def api_product_list(current_user: dict = Depends(oracle_auth.require_user)):
    """Return the canonical list of Oracle products for dropdowns."""
    return ORACLE_PRODUCTS

@app.post("/api/companies/backfill-products")
async def api_backfill_products(current_user: dict = Depends(oracle_auth.require_analyst)):
    """Auto-populate target_product from dominant oracle_signal for companies without one."""
    updated = oracle_db.backfill_target_product()
    return {"updated": updated}

@app.patch("/api/companies/{company_id}/status")
async def api_company_status(
    company_id: int,
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    data       = await request.json()
    new_status = data.get("status", "")
    valid      = {"staged", "pending_review", "approved", "pushed_to_hubspot", "rejected", "excluded"}
    if new_status not in valid:
        return JSONResponse({"error": f"Invalid status. Must be one of: {valid}"}, status_code=400)

    with oracle_db.db_cursor() as cur:
        cur.execute(
            "UPDATE companies SET status=%s, last_updated=NOW() WHERE id=%s RETURNING id, name, status",
            (new_status, company_id),
        )
        row = cur.fetchone()

    if not row:
        return JSONResponse({"error": "Company not found"}, status_code=404)

    _invalidate_companies_cache()
    log_audit(current_user, f"status_{new_status}", "company", str(company_id),
              new_value={"status": new_status})
    return dict(row)

# ═══ HUBSPOT SYNC PULL (two-way) ══════════════════════════════════════════════
@app.post("/api/hubspot/sync-pull")
async def api_hubspot_sync_pull(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_admin),
):
    """Pull companies AND contacts from HubSpot into local DB (doc §6.3)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    hs_key  = body.get("hubspot_key") or os.getenv("HUBSPOT_API_KEY", "")
    cfg     = oracle_db.get_hubspot_config()
    if not hs_key:
        hs_key = cfg.get("api_key", "")
    if not hs_key:
        return JSONResponse({"error": "No HubSpot API key configured. Save one in HubSpot Sync → Credentials first."}, status_code=400)

    result = await hs_push.sync_pull_from_hubspot(hs_key)
    log_audit(current_user, "hubspot_sync_pull", "system", "",
              new_value=result)
    return result

# hubspot config
@app.get("/api/hubspot/config")
async def get_hubspot_config(current_user: dict = Depends(oracle_auth.require_admin)):
    """Get stored HubSpot config (API key masked)."""
    cfg = oracle_db.get_hubspot_config()
    if cfg.get("api_key"):
        cfg["api_key"] = cfg["api_key"][:8] + "••••••••" + cfg["api_key"][-4:]
    return cfg

@app.post("/api/hubspot/config")
async def save_hubspot_config(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_admin),
):
    """Save HubSpot API key and portal ID."""
    body = await request.json()
    api_key   = (body.get("api_key") or "").strip()
    portal_id = (body.get("portal_id") or "").strip()
    # Allow saving portal_id alone (without changing the key)
    existing  = oracle_db.get_hubspot_config()
    if not api_key:
        api_key = existing.get("api_key", "")   # keep existing key
    if not api_key and not portal_id:
        return JSONResponse({"error": "At least api_key or portal_id required"}, status_code=400)
    cfg = oracle_db.upsert_hubspot_config(api_key, portal_id)
    # Also set in env for current process
    os.environ["HUBSPOT_API_KEY"] = api_key
    log_audit(current_user, "update_hubspot_config", "system", "",
              new_value={"portal_id": portal_id})
    return {"ok": True, "id": cfg.get("id")}

@app.post("/api/hubspot/test")
async def test_hubspot_connection(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_admin),
):
    """Test HubSpot API key by calling /crm/v3/objects/contacts?limit=1."""
    body    = await request.json()
    api_key = body.get("api_key") or os.getenv("HUBSPOT_API_KEY", "")
    cfg     = oracle_db.get_hubspot_config()
    if not api_key:
        api_key = cfg.get("api_key", "")
    if not api_key:
        return JSONResponse({"ok": False, "error": "No API key"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if r.status_code == 200:
            return {"ok": True, "message": "HubSpot connected"}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# company single push
@app.post("/api/companies/{company_id}/push-hubspot")
async def push_company_to_hubspot_endpoint(
    company_id: int,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    """Push a single company to HubSpot using domain-based upsert (doc §6.2)."""
    with oracle_db.db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM companies WHERE id=%s", (company_id,))
        row = cur.fetchone()
    if not row:
        return JSONResponse({"error": "Company not found"}, status_code=404)
    record = dict(row)
    result = await hs_push.push_company_to_hubspot(record)
    if result["ok"]:
        with oracle_db.db_cursor() as cur:
            cur.execute(
                "UPDATE companies SET status='pushed_to_hubspot', hubspot_id=%s, last_updated=NOW() WHERE id=%s",
                (result.get("hubspot_id"), company_id),
            )
        log_audit(current_user, "push_to_hubspot", "company", str(company_id),
                  new_value={"hubspot_id": result.get("hubspot_id"), "action": result.get("action")})
    return result

# bulk push
@app.post("/api/hubspot/bulk-push/companies")
async def bulk_push_companies_endpoint(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    """Bulk push all approved companies to HubSpot (doc §6.2)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    status = body.get("status", "approved")
    limit  = min(int(body.get("limit", 100)), 500)
    result = await hs_push.bulk_push_companies(status, limit)
    log_audit(current_user, "bulk_push_companies", "system", "",
              new_value=result)
    return result

@app.post("/api/hubspot/bulk-push/contacts")
async def bulk_push_contacts_endpoint(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    """Bulk push all approved contacts to HubSpot."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    status = body.get("status", "approved")
    limit  = min(int(body.get("limit", 100)), 500)
    result = await hs_push.bulk_push_contacts(status, limit)
    log_audit(current_user, "bulk_push_contacts", "system", "",
              new_value=result)
    return result

# engine configs
@app.get("/api/engine-configs")
async def get_engine_configs(current_user: dict = Depends(oracle_auth.require_analyst)):
    return oracle_db.list_engine_configs()

@app.get("/api/engine-configs/{engine_type}")
async def get_engine_config(engine_type: str, current_user: dict = Depends(oracle_auth.require_analyst)):
    """Get a single engine config by type."""
    configs = oracle_db.list_engine_configs()
    for cfg in configs:
        if cfg.get("engine_type") == engine_type:
            return cfg
    return JSONResponse({"error": f"Engine '{engine_type}' not found"}, status_code=404)

@app.patch("/api/engine-configs/{engine_type}")
async def update_engine_config_endpoint(
    engine_type: str,
    request: Request,
    current_user: dict = Depends(oracle_auth.require_admin),
):
    body = await request.json()
    result = oracle_db.update_engine_config(
        engine_type,
        is_enabled=body.get("is_enabled"),
        schedule_expression=body.get("schedule_expression"),
        last_run_status=body.get("last_run_status"),
    )
    log_audit(current_user, "update_engine_config", "system", engine_type, new_value=body)
    return result

# review queue (proper table)
@app.get("/api/review-queue")
async def get_review_queue(
    status: str = None,
    entity_type: str = None,
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    return oracle_db.list_review_queue(status=status, entity_type=entity_type,
                                        limit=limit, offset=offset)

@app.post("/api/review-queue")
async def add_review_queue_item(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    body = await request.json()
    return oracle_db.add_to_review_queue(
        entity_type=body["entity_type"],
        entity_id=body["entity_id"],
        issue_type=body["issue_type"],
        severity=body.get("severity", "warning"),
        issue_detail=body.get("issue_detail"),
    )

@app.patch("/api/review-queue/{item_id}")
async def resolve_review_item(
    item_id: int,
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    body = await request.json()
    result = oracle_db.resolve_review_queue_item(
        item_id,
        status=body["status"],
        notes=body.get("notes"),
        resolved_by=current_user.get("email"),
    )
    log_audit(current_user, f"review_queue_{body['status']}", "review_queue",
              str(item_id), new_value=body)
    return result

@app.post("/api/review-queue/bulk-resolve")
async def bulk_resolve_review(
    request: Request,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    body = await request.json()
    oracle_db.bulk_resolve_review_queue(
        body["ids"], body["status"], current_user.get("email")
    )
    log_audit(current_user, f"bulk_review_{body['status']}", "review_queue", "",
              new_value={"count": len(body["ids"])})
    return {"ok": True, "resolved": len(body["ids"])}

# product intelligence
@app.get("/api/product-intelligence")
async def get_product_intelligence(
    limit: int = 100,
    offset: int = 0,
    product_filter: str = None,
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    """Company-product matrix built from oracle_signals aggregation."""
    with oracle_db.db_cursor(commit=False) as cur:
        # Base filter: companies that have at least one oracle product detected
        # or have manually populated cloud/onprem fields
        if product_filter:
            where = """
                WHERE (
                    %s = ANY(c.oracle_cloud_solutions)
                    OR %s = ANY(c.oracle_on_premise_solutions)
                    OR %s = ANY(c.detected_products)
                )"""
            params: list = [product_filter] * 3
        else:
            where = """
                WHERE (
                    cardinality(c.oracle_cloud_solutions) > 0
                    OR cardinality(c.oracle_on_premise_solutions) > 0
                    OR cardinality(c.detected_products) > 0
                )"""
            params = []

        cur.execute(
            f"""SELECT c.id, c.name, c.domain, c.industry, c.status,
                       c.oracle_cloud_solutions,
                       c.oracle_on_premise_solutions  AS oracle_onprem_solutions,
                       c.oracle_version,
                       c.oracle_relationship_type     AS relationship_type,
                       c.number_of_oracle_users       AS oracle_users,
                       c.oracle_support_end_date,
                       c.detected_products            AS product_taxonomy,
                       c.product_confidence_scores,
                       COUNT(DISTINCT cc.id)          AS contacts_count
                FROM companies c
                LEFT JOIN company_contacts cc ON cc.company_id = c.id
                {where}
                GROUP BY c.id
                ORDER BY cardinality(c.detected_products) DESC, c.name
                LIMIT %s OFFSET %s""",
            params + [limit, offset],
        )
        companies_raw = cur.fetchall()
        companies     = jsonable_encoder([dict(r) for r in companies_raw])

        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM companies c {where}",
            params,
        )
        total = cur.fetchone()["cnt"]

        # Stats: cloud-only, onprem-only, mixed
        cur.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE cardinality(oracle_cloud_solutions) > 0
                      AND cardinality(oracle_on_premise_solutions) = 0
                ) AS cloud,
                COUNT(*) FILTER (
                    WHERE cardinality(oracle_on_premise_solutions) > 0
                      AND cardinality(oracle_cloud_solutions) = 0
                ) AS onprem,
                COUNT(*) FILTER (
                    WHERE cardinality(oracle_cloud_solutions) > 0
                      AND cardinality(oracle_on_premise_solutions) > 0
                ) AS mixed,
                COUNT(*) FILTER (
                    WHERE cardinality(detected_products) > 0
                ) AS total_with_products
            FROM companies
        """)
        s = cur.fetchone()

        # All unique product names for the filter dropdown
        cur.execute("""
            SELECT DISTINCT unnest(detected_products) AS product
            FROM companies
            WHERE cardinality(detected_products) > 0
            ORDER BY 1
        """)
        products = [r["product"] for r in cur.fetchall()]

    return {
        "companies": companies,
        "total":     total,
        "limit":     limit,
        "offset":    offset,
        "stats": {
            "total":  int(s["total_with_products"] or 0),
            "cloud":  int(s["cloud"]  or 0),
            "onprem": int(s["onprem"] or 0),
            "mixed":  int(s["mixed"]  or 0),
        },
        "products": products,
    }

@app.post("/api/product-intelligence/refresh")
async def refresh_product_intelligence(
    current_user: dict = Depends(oracle_auth.require_analyst),
):
    """Aggregate oracle_signals → populate product intel columns on companies."""
    try:
        result = oracle_db.aggregate_product_intel()
        return {"ok": True, **result}
    except Exception as e:
        logger.exception("Unhandled error in POST /api/product-intelligence/refresh")
        return JSONResponse({"error": str(e)}, status_code=500)

# static assets (js/css chunks)
if REACT_DIST.exists() and (REACT_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=REACT_DIST / "assets"), name="assets")

# react spa catch-all — must be last so all api routes take priority
@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_fallback(full_path: str):
    return _react_index()
