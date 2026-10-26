#!/usr/bin/env bash
set -e

# The 72-Hour Warning: Run script for Backend & Frontend

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
else
    PYTHON_BIN="python3"
fi

echo "=========================================================="
echo " Starting The 72-Hour Warning (Backend & Frontend)"
echo "=========================================================="

# 1. Start Backend FastAPI server on port 8000
echo "[1/2] Starting Python FastAPI backend on port 8000..."
cd "$ROOT_DIR"
$PYTHON_BIN -m uvicorn backend.app.api:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# 2. Start Frontend Vite server on port 5173
echo "[2/2] Starting Vite React frontend on port 5173..."
cd "$ROOT_DIR/frontend"
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!

echo ""
echo " Services are live:"
echo "   - Frontend UI:  http://localhost:5173"
echo "   - Backend API:  http://localhost:8000"
echo "   - API Health:   http://localhost:8000/health"
echo "   - Cities API:   http://localhost:8000/cities"
echo "=========================================================="

# Handle shutdown
cleanup() {
    echo ""
    echo "Stopping servers..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT
wait
