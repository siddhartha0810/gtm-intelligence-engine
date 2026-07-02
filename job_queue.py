"""
job_queue.py
============
Optional RQ/Redis job queue for the long-running scan and enrichment
subprocesses that unified_app.py otherwise spawns directly.

When REDIS_URL is set and `redis` + `rq` are installed, scan/enrich runs are
dispatched to an RQ queue so they execute inside separate `worker.py`
processes — horizontally scalable via `docker compose up --scale worker=N`,
and job state lives in Redis instead of an in-process variable, so it
survives an app restart.

When Redis isn't configured or isn't reachable, every function here is a
no-op that returns None/False, and unified_app.py falls back to spawning the
subprocess directly in the FastAPI process — the original behavior, unchanged.
This module is purely additive; nothing depends on it being available.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time as _time
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "").strip()

_ACTIVE_STATUSES = ("queued", "started", "deferred", "scheduled")

_queue = None
_redis_conn = None
_connect_attempted = False


def _connect():
    """Lazy, memoized connect — tried once per process, then cached (even on failure,
    so a misconfigured REDIS_URL doesn't retry/log on every request)."""
    global _queue, _redis_conn, _connect_attempted
    if _connect_attempted:
        return _queue
    _connect_attempted = True

    if not REDIS_URL:
        return None
    try:
        import redis
        from rq import Queue

        conn = redis.from_url(REDIS_URL, socket_connect_timeout=2)
        conn.ping()
        _redis_conn = conn
        _queue = Queue("data_tool", connection=conn)
        logger.info("[JobQueue] Connected to Redis at %s", REDIS_URL)
    except Exception as e:
        logger.warning(
            "[JobQueue] Redis unavailable (%s) — falling back to in-process "
            "subprocess execution", e,
        )
        _queue = None
    return _queue


def get_queue():
    return _connect()


def run_subprocess_job(cmd: list, cwd: str, env: dict) -> int:
    """RQ job body — executes inside a worker.py process. Blocks until the
    subprocess (scan_worker.py / enrichment_worker.py) exits. Status/log
    files are written by that subprocess exactly as in the non-queued path,
    so unified_app.py's existing status-file readers need no changes."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.wait()


def is_job_active(job_id: str) -> bool:
    q = get_queue()
    if q is None:
        return False
    job = q.fetch_job(job_id)
    return job is not None and job.get_status() in _ACTIVE_STATUSES


def enqueue(job_id: str, cmd: list, cwd: str, env: dict, timeout: int = 7200):
    """Returns the enqueued Job, or None if no queue is configured."""
    q = get_queue()
    if q is None:
        return None
    # Clear any stale finished/failed job registered under this id so a new
    # run can reuse the same fixed id (needed for is_job_active() to work).
    old = q.fetch_job(job_id)
    if old is not None and old.get_status() not in _ACTIVE_STATUSES:
        old.delete()
    return q.enqueue(
        run_subprocess_job, cmd, cwd, env,
        job_id=job_id, job_timeout=timeout, result_ttl=86400, failure_ttl=86400,
    )


def stop_job(job_id: str) -> bool:
    """Best-effort stop: SIGTERMs a currently-executing job via its worker,
    or cancels it if only queued. Returns True if a job was found."""
    q = get_queue()
    if q is None:
        return False
    job = q.fetch_job(job_id)
    if job is None:
        return False
    try:
        status = job.get_status()
        if status == "started":
            from rq.command import send_stop_job_command
            send_stop_job_command(_redis_conn, job_id)
        elif status in ("queued", "deferred", "scheduled"):
            job.cancel()
        return True
    except Exception as e:
        logger.warning("[JobQueue] stop_job(%s) failed: %s", job_id, e)
        return False


def wait_for_job(job_id: str, poll_seconds: float = 2.0):
    """Blocks the calling thread until the job reaches a terminal state, then
    returns the Job (or None if no queue/job exists). Call from a background
    thread — used to chain auto-enrich after a queued scan job finishes,
    mirroring the in-process `proc.wait()` pattern."""
    q = get_queue()
    if q is None:
        return None
    job = q.fetch_job(job_id)
    if job is None:
        return None
    while job.get_status() in _ACTIVE_STATUSES:
        _time.sleep(poll_seconds)
        try:
            job.refresh()
        except Exception:
            return job
    return job
