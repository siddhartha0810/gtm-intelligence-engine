"""
worker.py
=========
RQ worker entrypoint for the "data_tool" queue — executes scan and
enrichment jobs enqueued by unified_app.py (see job_queue.py).

Only relevant when REDIS_URL is set; without it, unified_app.py runs scan/
enrich subprocesses directly and this worker has nothing to consume.

Run directly:
    REDIS_URL=redis://localhost:6379/0 python worker.py

Scale horizontally in Docker Compose:
    docker compose up --scale worker=3
"""

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("worker")

REDIS_URL = os.environ.get("REDIS_URL", "").strip()

if __name__ == "__main__":
    if not REDIS_URL:
        logger.error("REDIS_URL not set — nothing for this worker to do. Exiting.")
        sys.exit(1)

    import redis
    from rq import Queue, Worker

    conn = redis.from_url(REDIS_URL)
    queue = Queue("data_tool", connection=conn)
    logger.info("Starting RQ worker on queue 'data_tool' — %s", REDIS_URL)
    Worker([queue], connection=conn).work()
