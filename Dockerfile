# syntax=docker/dockerfile:1

# ── Stage 1: build the React frontend ────────────────────────────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.13-slim AS runtime
WORKDIR /app

# psycopg2-binary needs libpq at runtime; build tools only needed transiently
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY unified_app.py scan_worker.py enrichment_worker.py seed_demo_data.py ./
COPY intent_engine/ ./intent_engine/
COPY lead_enrichment_engine/ ./lead_enrichment_engine/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN mkdir -p intent_engine/output lead_enrichment_engine/input lead_enrichment_engine/output

EXPOSE 8000
CMD ["uvicorn", "unified_app:app", "--host", "0.0.0.0", "--port", "8000"]
