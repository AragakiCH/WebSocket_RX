#!/bin/sh
set -eu

export OPCUA_URL="${OPCUA_URL:-opc.tcp://127.0.0.1:4840}"
export OPCUA_USER="${OPCUA_USER:-boschrexroth}"
export OPCUA_PASSWORD="${OPCUA_PASSWORD:-boschrexroth}"
export LOG_TO_EXCEL="${LOG_TO_EXCEL:-false}"

export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"

# Tu código está en la raíz del snap: $SNAP/main.py, $SNAP/ws, etc.
export PYTHONPATH="$SNAP"

exec "$SNAP/venv/bin/python" -m uvicorn main:app --app-dir "$SNAP" --host "$API_HOST" --port "$API_PORT"
