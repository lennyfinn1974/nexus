#!/usr/bin/env bash
# ════════════════════════════════════════════════════
# Nexus Agent — Service Control Script (Portable)
# ════════════════════════════════════════════════════
# Usage:
#   ./nexus.sh start     — Start as background service
#   ./nexus.sh stop      — Stop the service
#   ./nexus.sh restart   — Restart the service
#   ./nexus.sh status    — Show service status
#   ./nexus.sh logs      — Tail live logs
#   ./nexus.sh skills    — Browse, search, and install skills from the catalog
#   ./nexus.sh install   — Install as system service (launchd/systemd)
#   ./nexus.sh uninstall — Remove system service

set -euo pipefail

# ── Auto-detect paths from script location ──
NEXUS_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$NEXUS_DIR/backend"
PID_FILE="$BACKEND_DIR/logs/nexus.pid"
LOG_FILE="$BACKEND_DIR/logs/nexus-stdout.log"
ERR_FILE="$BACKEND_DIR/logs/nexus-stderr.log"
PORT=8080

# ── Detect Python ──
if [ -f "$NEXUS_DIR/venv/bin/python" ]; then
    PYTHON="$NEXUS_DIR/venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="$(command -v python3)"
else
    echo "Error: Python 3 not found. Run install.sh first."
    exit 1
fi

# ── Detect OS ──
OS="$(uname -s)"
case "$OS" in
    Darwin)
        PLIST_LABEL="com.nexus.agent"
        PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
        ;;
    Linux)
        SYSTEMD_DIR="$HOME/.config/systemd/user"
        SERVICE_FILE="$SYSTEMD_DIR/nexus.service"
        ;;
esac

mkdir -p "$BACKEND_DIR/logs"

# ── Helper: find process on port ──
port_pid() {
    if command -v lsof &>/dev/null; then
        lsof -i ":$PORT" -t 2>/dev/null || true
    elif command -v ss &>/dev/null; then
        ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K\d+' | head -1 || true
    fi
}

case "${1:-status}" in

  start)
    EXISTING=$(port_pid)
    if [ -n "$EXISTING" ]; then
        echo "Nexus is already running on port $PORT (PID: $EXISTING)"
        exit 0
    fi

    echo "Starting Nexus Agent..."
    cd "$NEXUS_DIR"
    PYTHONPATH="$BACKEND_DIR" nohup "$PYTHON" backend/main.py \
        >> "$LOG_FILE" 2>> "$ERR_FILE" &
    echo $! > "$PID_FILE"
    sleep 2

    if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
        echo "Nexus is running at http://localhost:$PORT"
        echo "Admin UI: http://localhost:$PORT/admin"
        echo "PID: $(cat "$PID_FILE")"
    else
        echo "Started (PID: $(cat "$PID_FILE")), waiting for health check..."
        sleep 3
        if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
            echo "Nexus is ready at http://localhost:$PORT"
        else
            echo "Warning: Server may still be starting. Check: ./nexus.sh status"
        fi
    fi
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping Nexus (PID: $PID)..."
            kill "$PID"
            sleep 2
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null || true
            fi
            rm -f "$PID_FILE"
            echo "Stopped."
        else
            rm -f "$PID_FILE"
            echo "PID file was stale. Cleaned up."
        fi
    fi

    # Also kill anything on the port
    PORT_PID=$(port_pid)
    if [ -n "$PORT_PID" ]; then
        echo "Killing process on port $PORT (PID: $PORT_PID)..."
        kill "$PORT_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$PORT_PID" 2>/dev/null || true
        echo "Done."
    else
        echo "No process found on port $PORT."
    fi
    ;;

  restart)
    "$0" stop
    sleep 2
    "$0" start
    ;;

  status)
    PORT_PID=$(port_pid)
    if [ -n "$PORT_PID" ]; then
        echo "Nexus is RUNNING on port $PORT (PID: $PORT_PID)"
        HEALTH=$(curl -s "http://localhost:$PORT/api/health" 2>/dev/null)
        if [ -n "$HEALTH" ]; then
            echo "$HEALTH" | "$PYTHON" -c "
import sys, json
h = json.load(sys.stdin)
print(f\"  Health: {'HEALTHY' if h['healthy'] else 'UNHEALTHY'}\")
for k, v in h.get('checks', {}).items():
    print(f\"    {k}: {v.get('status', 'unknown')}\")
" 2>/dev/null || true
        fi

        STATUS=$(curl -s "http://localhost:$PORT/api/status" 2>/dev/null)
        if [ -n "$STATUS" ]; then
            echo "$STATUS" | "$PYTHON" -c "
import sys, json
s = json.load(sys.stdin)
plugins = s.get('plugins', {})
tools = sum(p.get('tools', 0) for p in plugins.values())
cmds = sum(p.get('commands', 0) for p in plugins.values())
print(f\"  Plugins: {len(plugins)} | Tools: {tools} | Commands: {cmds}\")
print(f\"  Models: Claude={'available' if s['models']['claude_available'] else 'unavailable'}, Ollama={'available' if s['models']['ollama_available'] else 'unavailable'}\")
" 2>/dev/null || true
        fi
    else
        echo "Nexus is NOT running."
    fi

    # Check service registration
    case "$OS" in
        Darwin)
            if [ -f "$PLIST_DST" ]; then
                echo "  Service: launchd INSTALLED (starts on login)"
            else
                echo "  Service: not installed (run './nexus.sh install' for auto-start)"
            fi
            ;;
        Linux)
            if [ -f "$SERVICE_FILE" ]; then
                echo "  Service: systemd user service INSTALLED"
            else
                echo "  Service: not installed (run './nexus.sh install' for auto-start)"
            fi
            ;;
    esac
    ;;

  logs)
    echo "=== Nexus Logs (Ctrl+C to stop) ==="
    tail -f "$LOG_FILE" "$ERR_FILE"
    ;;

  skills)
    shift
    PYTHONPATH="$BACKEND_DIR" "$PYTHON" -m skills.cli "$@"
    ;;

  install)
    # Stop any running instance first
    "$0" stop 2>/dev/null || true

    case "$OS" in
        Darwin)
            mkdir -p "$HOME/Library/LaunchAgents"
            cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${BACKEND_DIR}/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${NEXUS_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>${BACKEND_DIR}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>${BACKEND_DIR}/logs/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${BACKEND_DIR}/logs/launchd-stderr.log</string>
</dict>
</plist>
PLIST
            launchctl load "$PLIST_DST"
            echo "Installed launchd service."
            echo "  - Starts automatically on login"
            echo "  - Auto-restarts if it crashes"
            sleep 3
            "$0" status
            ;;

        Linux)
            mkdir -p "$SYSTEMD_DIR"
            cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=Nexus Agent
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=${NEXUS_DIR}
Environment=PYTHONPATH=${BACKEND_DIR}
ExecStart=${PYTHON} ${BACKEND_DIR}/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
            systemctl --user daemon-reload
            systemctl --user enable nexus
            systemctl --user start nexus
            echo "Installed systemd user service."
            echo "  - Starts automatically on login"
            echo "  - Auto-restarts on failure"
            sleep 3
            "$0" status
            ;;

        *)
            echo "Unsupported OS for service install: $OS"
            exit 1
            ;;
    esac
    ;;

  uninstall)
    case "$OS" in
        Darwin)
            if [ -f "$PLIST_DST" ]; then
                launchctl unload "$PLIST_DST" 2>/dev/null || true
                rm -f "$PLIST_DST"
                echo "launchd service removed."
            else
                echo "No launchd service found."
            fi
            ;;
        Linux)
            if [ -f "$SERVICE_FILE" ]; then
                systemctl --user stop nexus 2>/dev/null || true
                systemctl --user disable nexus 2>/dev/null || true
                rm -f "$SERVICE_FILE"
                systemctl --user daemon-reload
                echo "systemd service removed."
            else
                echo "No systemd service found."
            fi
            ;;
    esac
    ;;

  *)
    echo "Usage: $0 {start|stop|restart|status|logs|skills|install|uninstall}"
    exit 1
    ;;
esac
