#!/usr/bin/env bash
# macOS/Linux equivalent of start.bat — one script, one process, one port.
#
# Runs the unified FastAPI app on :8000, which builds and serves the React
# frontend itself (see unified_app.py's /assets mount + SPA catch-all). No
# separate Vite dev server to keep in sync — that split process model is
# what let the backend die silently while the frontend kept answering with
# empty-body errors ("Unexpected end of JSON input") on every API call.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "============================================"
echo " GTM Data Tool"
echo "============================================"

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "ERROR: .venv not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
echo "Python: $PYTHON"

# Free the port if a previous run is still holding it (restart-safe)
PID=$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$PID" ]; then
  echo "Stopping existing server on :8000 (pid $PID)..."
  kill "$PID" 2>/dev/null || true
  sleep 1
fi

echo "Building frontend..."
(cd frontend && npm install --silent && npm run build)
echo "Frontend built."

echo ""
echo "Starting server on http://localhost:8000 ..."
echo "Open your browser at: http://localhost:8000"
echo "Press Ctrl+C to stop."
echo ""

exec "$PYTHON" -m uvicorn unified_app:app --host 0.0.0.0 --port 8000
