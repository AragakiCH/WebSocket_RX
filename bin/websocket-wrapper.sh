#!/bin/sh
set -eu

export OPCUA_URL="${OPCUA_URL:-opc.tcp://127.0.0.1:4840}"
export OPCUA_USER="${OPCUA_USER:-boschrexroth}"
export OPCUA_PASSWORD="${OPCUA_PASSWORD:-boschrexroth}"
export LOG_TO_EXCEL="${LOG_TO_EXCEL:-false}"

# Port donde vive tu API dentro del snap
export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"

export PYTHONPATH="$SNAP/app"
exec "$SNAP/bin/python3" -m uvicorn main:app --app-dir "$SNAP/app" --host 0.0.0.0 --port 8000
