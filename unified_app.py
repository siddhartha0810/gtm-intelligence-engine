"""
unified_app.py
==============
Single FastAPI server for all three tabs:
  • Oracle Intent  (scan, companies, signals, contacts, export)
  • Lead Enrichment (upload, pipeline, results, download)
  • Prospect       (DB search, Apollo people search, streaming)

Run from DATA TOOL root:
  uvicorn unified_app:app --reload --port 8000

Then open: http://localhost:8000
"""

import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# ── Path setup ─────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
ORACLE_DIR  = BASE_DIR / "oracle_intent_engine"
ENRICH_DIR  = BASE_DIR / "lead_enrichment_engine"

# Add oracle engine first so its `src` package is the one resolved for bare imports.
# Lead enrichment pipeline runs as subprocess with cwd=ENRICH_DIR, so no conflict.
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Oracle engine imports (after path setup) ────────────────────────────────
from src import config as oracle_cfg
from src import database as oracle_db
from src import exporter as oracle_exporter
from src import contact_finder as oracle_contact_finder
from src.utils import is_valid_company_name
from src.phase_classifier import PHASE_LABELS, PHASE_COLORS

# ── Dotenv for enrichment/prospect credentials ──────────────────────────────
from dotenv import load_dotenv
load_dotenv(BASE_DIR / "oracle_intent_engine"   / ".env")           # oracle DB vars first
load_dotenv(BASE_DIR / "lead_enrichment_engine" / ".env", override=False)  # enrichment vars

# Explicitly set oracle DB DSN so oracle database.py never picks up PG_MASTER_CONNECTION_STRING
import os as _os
_oracle_env = {}
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
    f"dbname={_oracle_env.get('DB_NAME','oracle_intent')} "
    f"user={_oracle_env.get('DB_USER','postgres')} "
    f"password={_oracle_env.get('DB_PASSWORD','')}"
)
_os.environ["ORACLE_PG_DSN"] = _oracle_pg_dsn

APOLLO_API_KEY           = os.getenv("APOLLO_API_KEY", "").strip()
ZEROBOUNCE_API_KEY       = os.getenv("ZEROBOUNCE_API_KEY", "").strip()
APIFY_TOKEN              = os.getenv("APIFY_TOKEN", "").strip()
APIFY_LINKEDIN_ACTOR_ID  = os.getenv("APIFY_LINKEDIN_ACTOR_ID", "").strip()
APIFY_EMAIL_ACTOR_ID     = os.getenv("APIFY_EMAIL_ACTOR_ID", "").strip()
PG_CONNECTION_STRING     = os.getenv("PG_CONNECTION_STRING", "").strip()
PG_MASTER_CONNECTION_STRING = os.getenv("PG_MASTER_CONNECTION_STRING", "").strip()
PG_INPUT_TABLE           = os.getenv("PG_INPUT_TABLE", "leads").strip()
PG_OUTPUT_TABLE          = os.getenv("PG_OUTPUT_TABLE", "enriched_leads").strip()

# ── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Oracle Intelligence Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static file serving ──────────────────────────────────────────────────────
# Production: React build output at frontend/dist
# Dev:        Vite runs on :5173 and proxies to us — no static mount needed
REACT_DIST   = BASE_DIR / "frontend" / "dist"
STATIC_DIR   = ENRICH_DIR / "static"   # old unified.html (fallback)

# SPA mount added at end of file after all API routes

# ── Oracle scan subprocess state ────────────────────────────────────────────
_SCAN_STATUS_FILE = BASE_DIR / "_scan_status.json"
_SCAN_LOG_FILE    = BASE_DIR / "_scan_log.txt"
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
                return st
    except Exception:
        pass
    return dict(_IDLE_STATUS)


def _scan_get_log() -> list:
    try:
        if _SCAN_LOG_FILE.exists():
            return [
                line for line in _SCAN_LOG_FILE.read_text(encoding="utf-8").splitlines()
                if line
            ]
    except Exception:
        pass
    return []


def _start_scan_subprocess(sources: list, location: str, max_pages: int,
                           jde_manufacturing: bool = False) -> bool:
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


# ── Oracle enrichment subprocess state ──────────────────────────────────────
_ENRICH_STATUS_FILE = BASE_DIR / "_enrich_status.json"
_ENRICH_LOG_FILE    = BASE_DIR / "_enrich_log.txt"
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
                return st
    except Exception:
        pass
    return dict(_ENRICH_IDLE)


def _enrich_get_log() -> list:
    try:
        if _ENRICH_LOG_FILE.exists():
            return [l for l in _ENRICH_LOG_FILE.read_text(encoding="utf-8").splitlines() if l]
    except Exception:
        pass
    return []


def _start_enrich_subprocess(limit: int = 50, max_per_company: int = 10) -> bool:
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

        cmd = [
            sys.executable,
            str(BASE_DIR / "enrichment_worker.py"),
            "--status-file",     str(_ENRICH_STATUS_FILE),
            "--log-file",        str(_ENRICH_LOG_FILE),
            "--limit",           str(limit),
            "--max-per-company", str(max_per_company),
        ]
        _enrich_proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True


def _stop_enrich_subprocess() -> None:
    global _enrich_proc
    with _enrich_proc_lock:
        if _enrich_proc is not None and _enrich_proc.poll() is None:
            _enrich_proc.terminate()
            try:
                _enrich_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _enrich_proc.kill()


# ── Shared job store (enrichment + prospect jobs) ───────────────────────────
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


# ═══════════════════════════════════════════════════════════════════════════
# ROOT — serve React app (production) or redirect to Vite (dev)
# ═══════════════════════════════════════════════════════════════════════════

def _react_index() -> HTMLResponse:
    """Return the React index.html, falling back to old unified.html."""
    if REACT_DIST.exists():
        return HTMLResponse((REACT_DIST / "index.html").read_text(encoding="utf-8"))
    return HTMLResponse((STATIC_DIR / "unified.html").read_text(encoding="utf-8"))



# ═══════════════════════════════════════════════════════════════════════════
# SHARED: SSE STREAM + STATUS + CANCEL
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/stream/{job_id}")
async def stream_output(job_id: str):
    if job_id not in _jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    q = _jobs[job_id]["queue"]

    async def generate():
        loop = asyncio.get_event_loop()
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
async def get_status(job_id: str):
    if job_id not in _jobs:
        return {"status": "not_found"}
    j = _jobs[job_id]
    return {"status": j["status"], "exit_code": j.get("exit_code")}


@app.post("/cancel/{job_id}")
async def cancel_job(job_id: str):
    if job_id not in _jobs:
        return {"status": "not_found"}
    proc = _jobs[job_id].get("process")
    if proc and proc.poll() is None:
        proc.terminate()
        _jobs[job_id]["status"] = "cancelled"
    return {"status": "cancelled"}


# ═══════════════════════════════════════════════════════════════════════════
# ORACLE INTENT — scan control
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/oracle/config")
async def oracle_config():
    try:
        oracle_db.init_db()
        db_ok = oracle_db.test_connection()
    except Exception:
        db_ok = False
    return {"db_ok": db_ok}


@app.post("/scan/start")
async def start_scan(request: Request):
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

    started = _start_scan_subprocess(sources=sources, location=location, max_pages=max_pages,
                                     jde_manufacturing=jde_manufacturing)
    if not started:
        return JSONResponse({"error": "Scan already running."}, status_code=409)
    return {"message": "Scan started.", "sources": sources, "jde_manufacturing": jde_manufacturing}


@app.get("/scan/status")
async def scan_status():
    return _scan_current_status()


@app.post("/scan/stop")
async def stop_scan():
    _stop_scan_subprocess()
    return {"message": "Stop signal sent."}


@app.get("/scan/log")
async def scan_log():
    return _scan_get_log()


# ═══════════════════════════════════════════════════════════════════════════
# ORACLE INTENT — data / companies
# ═══════════════════════════════════════════════════════════════════════════

def _annotate_and_sort(companies: list) -> list:
    from src import lead_scorer
    for c in companies:
        lead_scorer.annotate(c)
    companies.sort(key=lambda c: c.get("priority_score", 0), reverse=True)
    return companies


@app.get("/api/companies")
async def api_companies(phase: str = "", product: str = "", show_all: int = 0):
    try:
        run_id = 0 if show_all else None
        companies = list(oracle_db.get_all_companies_with_signals(run_id=run_id))
        companies = _annotate_and_sort(companies)
        if phase:
            companies = [c for c in companies if phase in (c.get("phases") or [])]
        if product:
            companies = [c for c in companies if product in (c.get("products") or [])]
        return [dict(c) for c in companies]
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/stats")
async def api_stats(show_all: int = 0):
    from collections import Counter
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
    return {
        "total_companies": len(companies),
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
async def api_company_signals(company_id: int):
    return JSONResponse([dict(s) for s in oracle_db.get_signals_for_company(company_id)])


@app.get("/api/company/{company_id}/contacts")
async def api_company_contacts(company_id: int):
    return JSONResponse([dict(c) for c in oracle_db.get_contacts_for_company(company_id)])


@app.post("/api/company/{company_id}/contacts/enrich")
async def api_enrich_contacts(company_id: int):
    company = oracle_db.get_company_by_id(company_id)
    if not company:
        return JSONResponse({"error": "Company not found"}, status_code=404)
    domain = company.get("domain") or oracle_contact_finder.infer_domain(company["name"])
    try:
        contacts = oracle_contact_finder.find_contacts(company["name"], domain)
        oracle_db.save_contacts(company_id, contacts)
        return {"contacts": contacts, "count": len(contacts)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════════
# ORACLE INTENT — admin
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/admin/purge-invalid")
async def purge_invalid():
    count = oracle_db.purge_invalid_companies(is_valid_company_name)
    return {"deleted": count, "message": f"Purged {count} invalid company names."}


@app.post("/admin/reset-all")
async def reset_all():
    oracle_db.reset_all_data()
    return {"message": "All data cleared. Ready for a fresh scan."}


# ═══════════════════════════════════════════════════════════════════════════
# ORACLE INTENT — export
# ═══════════════════════════════════════════════════════════════════════════

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
async def export_csv():
    companies = oracle_db.get_all_companies_with_signals()
    path = oracle_exporter.export_csv(_companies_to_export_format(companies))
    return FileResponse(path, filename=os.path.basename(path), media_type="text/csv")


@app.get("/export/excel")
async def export_excel():
    companies = oracle_db.get_all_companies_with_signals()
    path = oracle_exporter.export_excel(_companies_to_export_format(companies))
    return FileResponse(path, filename=os.path.basename(path),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/export/excel/all")
async def export_excel_all():
    companies = oracle_db.get_all_companies_with_signals(run_id=0)
    filename  = f"oracle_intent_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = oracle_exporter.export_excel(_companies_to_export_format(companies), filename=filename)
    return FileResponse(path, filename=os.path.basename(path),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/export/csv/all")
async def export_csv_all():
    companies = oracle_db.get_all_companies_with_signals(run_id=0)
    filename  = f"oracle_intent_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path = oracle_exporter.export_csv(_companies_to_export_format(companies), filename=filename)
    return FileResponse(path, filename=os.path.basename(path), media_type="text/csv")


# ═══════════════════════════════════════════════════════════════════════════
# LEAD ENRICHMENT — config / upload / run / results / download
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/config")
async def get_config():
    return {
        "pg_configured":  bool(PG_CONNECTION_STRING),
        "pg_input_table": PG_INPUT_TABLE,
        "pg_output_table": PG_OUTPUT_TABLE,
        "apollo_key":     bool(APOLLO_API_KEY),
        "zb_key":         bool(ZEROBOUNCE_API_KEY),
        "apify_ready":    bool(APIFY_TOKEN and APIFY_LINKEDIN_ACTOR_ID and APIFY_EMAIL_ACTOR_ID),
    }


@app.get("/config/status")
async def config_status():
    """Return real connection status for each API key — used by Settings page."""
    import httpx

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
async def config_test(service: str, request: Request):
    """Test a single API key supplied in the request body."""
    import httpx
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
                return JSONResponse({"status": "error", "message": f"Unknown service: {service}"}, status_code=400)

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/config/save/{service}")
async def config_save(service: str, request: Request):
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
        return JSONResponse({"ok": False, "message": f"Unknown service: {service}"}, status_code=400)

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
async def upload_csv(file: UploadFile = File(...)):
    dest_dir = ENRICH_DIR / "input"
    dest_dir.mkdir(exist_ok=True)
    suffix = Path(file.filename).suffix.lower()
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
async def get_leads():
    import pandas as pd
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
async def download_file(filename: str):
    if filename not in _ALLOWED_DOWNLOADS:
        return JSONResponse({"error": "File not available"}, status_code=404)
    path = ENRICH_DIR / "output" / filename
    if not path.exists():
        return JSONResponse({"error": "File not ready — run the pipeline first"}, status_code=404)
    return FileResponse(path, filename=filename, media_type="text/csv")


# ═══════════════════════════════════════════════════════════════════════════
# PROSPECT — estimate / run / db-search / status / results / download
# ═══════════════════════════════════════════════════════════════════════════

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
        import json as _json
        data = _json.loads(result_path.read_text(encoding="utf-8"))
        _prospect_results          = data.get("contacts", [])
        _prospect_stats            = data.get("stats", {})
        _jobs[job_id]["stats"]     = _prospect_stats
        _jobs[job_id]["contacts"]  = len(_prospect_results)
        result_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"[prospect] Failed to load results: {e}")


@app.post("/prospect/estimate")
async def prospect_estimate(request: Request):
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
        pass

    apollo_needed = max(len(companies) - db_hits, 0)
    est_seconds   = db_hits * 0.5 + apollo_needed * 2.5

    return {
        "companies":      len(companies),
        "db_hits":        db_hits,
        "apollo_credits": apollo_needed,
        "est_seconds":    round(est_seconds),
    }


@app.post("/prospect/db-search")
async def prospect_db_search(request: Request):
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
            pass

        # 2. Contacts table (280k-contacts-db) if oracle company_contacts came up empty
        if not found:
            try:
                import psycopg2
                import psycopg2.extras
                conn = psycopg2.connect(PG_MASTER_CONNECTION_STRING)
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
                pass

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
async def prospect_run(request: Request):
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
async def prospect_status(job_id: str):
    if job_id not in _jobs:
        return JSONResponse({"status": "not_found"}, status_code=404)
    j = _jobs[job_id]
    return {
        "status":   j["status"],
        "stats":    j.get("stats", {}),
        "contacts": j.get("contacts", 0),
    }


@app.get("/prospect/results")
async def prospect_results():
    if not _prospect_results:
        return JSONResponse({"error": "No prospect results yet — run a search first"}, status_code=404)
    return JSONResponse(_prospect_results)


@app.get("/prospect/download/csv")
async def prospect_download_csv():
    if not _prospect_results:
        return JSONResponse({"error": "No results to download"}, status_code=404)
    import io, csv as csv_mod
    buf = io.StringIO()
    fieldnames = ["first_name", "last_name", "company", "job_title",
                  "email", "email_validation_status", "linkedin_url", "domain", "source"]
    writer = csv_mod.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(_prospect_results)
    filename = f"prospect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/prospect/download/excel")
async def prospect_download_excel():
    if not _prospect_results:
        return JSONResponse({"error": "No results to download"}, status_code=404)
    import io
    import pandas as pd
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


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD — combined stats for the React frontend
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
async def api_dashboard():
    """Single endpoint that powers the Dashboard page KPI cards."""
    from collections import Counter
    companies = list(oracle_db.get_all_companies_with_signals(run_id=0))
    companies = _annotate_and_sort(companies)

    phase_counter: Counter = Counter()
    total_signals = 0
    for c in companies:
        for p in (c.get("phases") or []):
            if p: phase_counter[p] += 1
        total_signals += int(c.get("signal_count") or 0)

    # Count enriched contacts from PG master store
    enriched_contacts = 0
    pushed_to_hubspot = 0
    try:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(PG_MASTER_CONNECTION_STRING)
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM contacts WHERE \"Validated_Email\" IS NOT NULL AND \"Validated_Email\" != ''")
                enriched_contacts = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM contacts WHERE \"HubSpot_Pushed\" = true") if False else None
        conn.close()
    except Exception:
        pass

    return {
        "companies_tracked":    len(companies),
        "contacts_enriched":    enriched_contacts,
        "intent_signals":       total_signals,
        "pushed_to_hubspot":    pushed_to_hubspot,
        "implementing":         phase_counter.get("implementing", 0),
        "evaluating":           phase_counter.get("evaluating", 0),
        "researching":          phase_counter.get("researching", 0),
        "scan_status":          _scan_current_status(),
    }


@app.get("/api/contacts")
async def api_contacts(company: str = "", limit: int = 200):
    """Enriched contacts from company_contacts table."""
    try:
        with oracle_db.db_cursor(commit=False) as cur:
            if company:
                cur.execute(
                    """SELECT cc.id, cc.first_name, cc.last_name, cc.title,
                              cc.email, cc.linkedin_url, cc.confidence,
                              cc.is_target, cc.source, cc.email_validation_status,
                              cc.fetched_at::text AS created_at,
                              c.name AS company_name, c.domain AS company_domain
                       FROM company_contacts cc
                       JOIN companies c ON cc.company_id = c.id
                       WHERE LOWER(c.name) LIKE %s
                       ORDER BY cc.is_target DESC, cc.confidence DESC
                       LIMIT %s""",
                    (f"%{company.lower()}%", min(limit, 500)),
                )
            else:
                cur.execute(
                    """SELECT cc.id, cc.first_name, cc.last_name, cc.title,
                              cc.email, cc.linkedin_url, cc.confidence,
                              cc.is_target, cc.source, cc.email_validation_status,
                              cc.fetched_at::text AS created_at,
                              c.name AS company_name, c.domain AS company_domain
                       FROM company_contacts cc
                       JOIN companies c ON cc.company_id = c.id
                       ORDER BY cc.is_target DESC, cc.confidence DESC
                       LIMIT %s""",
                    (min(limit, 500),),
                )
            rows = [dict(r) for r in cur.fetchall()]
        return JSONResponse(rows)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════
# SIGNALS  /  REVIEW QUEUE  /  REPORTING
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/signals")
async def api_signals(limit: int = 200):
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
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/review-queue")
async def api_review_queue(limit: int = 100):
    """Oracle-enriched contacts (company_contacts table) for review."""
    try:
        with oracle_db.db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT cc.id, cc.first_name, cc.last_name, cc.title,
                       cc.email, cc.linkedin_url, cc.confidence,
                       cc.is_target, cc.source,
                       cc.fetched_at::text AS created_at,
                       c.name AS company_name,
                       c.domain AS company_domain
                FROM company_contacts cc
                JOIN companies c ON cc.company_id = c.id
                WHERE cc.email IS NOT NULL AND cc.email != ''
                ORDER BY cc.is_target DESC, cc.confidence DESC
                LIMIT %s
            """, (min(limit, 500),))
            rows = [dict(r) for r in cur.fetchall()]
        return JSONResponse(rows)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/contacts/push-hubspot")
async def push_contact_to_hubspot(request: Request):
    """Push a single contact dict to HubSpot CRM."""
    import httpx
    body = await request.json()
    hubspot_key = os.getenv("HUBSPOT_API_KEY", "") or os.getenv("HUBSPOT_TOKEN", "")
    if not hubspot_key:
        return JSONResponse({"ok": False, "message": "HubSpot API key not configured — add it in Settings."})
    payload = {
        "properties": {
            "firstname": body.get("first_name", ""),
            "lastname":  body.get("last_name", ""),
            "email":     body.get("email", ""),
            "jobtitle":  body.get("job_title", ""),
            "company":   body.get("company_name", ""),
        }
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.hubapi.com/crm/v3/objects/contacts",
                json=payload,
                headers={"Authorization": f"Bearer {hubspot_key}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201):
            return {"ok": True, "message": "Pushed to HubSpot"}
        if r.status_code == 409:
            return {"ok": True, "message": "Already exists in HubSpot"}
        data = r.json() if r.content else {}
        return JSONResponse({"ok": False, "message": data.get("message", f"HubSpot error {r.status_code}")})
    except Exception as e:
        return JSONResponse({"ok": False, "message": str(e)})


@app.get("/api/reporting")
async def api_reporting():
    """Reporting stats: phase distribution, scan-run history, source breakdown."""
    from collections import Counter
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
    return {
        "total_companies": len(companies),
        "total_signals":   total_signals,
        "phases":          dict(phase_counter.most_common()),
        "sources": [
            {"label": k, "count": v, "pct": round(v / total_src * 100)}
            for k, v in source_counter.most_common(6)
        ],
        "scan_runs": [dict(r) for r in scan_runs],
    }


# ─── Enrichment endpoints ────────────────────────────────────────────────────

@app.post("/api/enrich/start")
async def enrich_start(request: Request):
    """Launch the Apollo enrichment subprocess for companies without contacts."""
    data              = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    limit             = int(data.get("limit", 50))
    max_per_company   = int(data.get("max_per_company", 10))

    if not APOLLO_API_KEY:
        return JSONResponse({"error": "Apollo API key not configured. Add APOLLO_API_KEY to oracle_intent_engine/.env"}, status_code=400)

    started = _start_enrich_subprocess(limit=limit, max_per_company=max_per_company)
    if not started:
        return JSONResponse({"error": "Enrichment already running"}, status_code=409)
    return {"started": True, "limit": limit, "max_per_company": max_per_company}


@app.post("/api/enrich/stop")
async def enrich_stop():
    _stop_enrich_subprocess()
    return {"stopped": True}


@app.get("/api/enrich/status")
async def enrich_status():
    return _enrich_current_status()


@app.get("/api/enrich/log")
async def enrich_log():
    return _enrich_get_log()


@app.get("/api/enrich/stats")
async def enrich_stats():
    """Returns enrichment readiness: how many companies need enrichment."""
    try:
        stats = oracle_db.get_enrichment_stats()
        return {
            **stats,
            "apollo_configured":     bool(APOLLO_API_KEY),
            "zerobounce_configured": bool(ZEROBOUNCE_API_KEY),
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    try:
        oracle_db.init_db()
    except Exception as e:
        print(f"[startup] Oracle DB init warning: {e}")
    # Ensure output dirs exist
    (ENRICH_DIR / "input").mkdir(exist_ok=True)
    (ENRICH_DIR / "output").mkdir(exist_ok=True)
    (ORACLE_DIR / "output").mkdir(exist_ok=True)


# ── Static assets (JS/CSS chunks) ───────────────────────────────────────────
if REACT_DIST.exists() and (REACT_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=REACT_DIST / "assets"), name="assets")

# ── React SPA catch-all — MUST be last so all API routes take priority ───────
@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_fallback(full_path: str):
    return _react_index()
