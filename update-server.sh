#!/usr/bin/env bash
set -euo pipefail

RCON_HOST="localhost"
RCON_PORT="25575"
RCON_PASSWORD=""
RCON_CLI="mcrcon"

SERVER_DIR=""
START_CMD="sh start.sh"

UPDATER_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="python"

WARN_SECONDS=30

rcon() {
    "$RCON_CLI" -H "$RCON_HOST" -P "$RCON_PORT" -p "$RCON_PASSWORD" "$@"
}

echo "==> Notifying players..."
rcon "say Server restarting for updates in ${WARN_SECONDS}s"
sleep "$WARN_SECONDS"
rcon "say Restarting now."

echo "==> Stopping server..."
rcon "stop"

echo "==> Waiting for server to shut down..."
while rcon "" 2>/dev/null; do
    sleep 10
done
echo "    Server offline."

echo "==> Updating mods..."
"$PYTHON" "$UPDATER_DIR/updater.py" --yes --server-dir "$SERVER_DIR" update

echo "==> Starting server..."
cd "$SERVER_DIR"
nohup bash -c "$START_CMD" > logs/updater-start.log 2>&1 &

echo "==> Done. Server starting in background (PID $!)."
