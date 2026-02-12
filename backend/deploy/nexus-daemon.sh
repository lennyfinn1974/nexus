#!/bin/bash
# Nexus Agent Daemon Manager
# Usage: ./nexus-daemon.sh [install|uninstall|start|stop|restart|status|logs]

PLIST_NAME="com.nexus.agent.plist"
PLIST_SRC="$(cd "$(dirname "$0")" && pwd)/$PLIST_NAME"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_DIR="/Users/lennyfinn/Nexus/backend/logs"

case "$1" in
    install)
        echo "Installing Nexus Agent daemon..."
        mkdir -p "$HOME/Library/LaunchAgents"
        mkdir -p "$LOG_DIR"
        cp "$PLIST_SRC" "$PLIST_DST"
        echo "Installed: $PLIST_DST"
        echo "Run './nexus-daemon.sh start' to start the daemon"
        ;;

    uninstall)
        echo "Uninstalling Nexus Agent daemon..."
        launchctl unload "$PLIST_DST" 2>/dev/null
        rm -f "$PLIST_DST"
        echo "Uninstalled."
        ;;

    start)
        echo "Starting Nexus Agent daemon..."
        launchctl load "$PLIST_DST" 2>/dev/null || true
        launchctl start com.nexus.agent
        echo "Started. Check status with: ./nexus-daemon.sh status"
        ;;

    stop)
        echo "Stopping Nexus Agent daemon..."
        launchctl stop com.nexus.agent
        echo "Stopped."
        ;;

    restart)
        echo "Restarting Nexus Agent daemon..."
        launchctl stop com.nexus.agent 2>/dev/null
        sleep 2
        launchctl start com.nexus.agent
        echo "Restarted."
        ;;

    status)
        echo "=== Nexus Agent Daemon Status ==="
        if launchctl list 2>/dev/null | grep -q "com.nexus.agent"; then
            PID=$(launchctl list | grep "com.nexus.agent" | awk '{print $1}')
            echo "Status: RUNNING (PID: $PID)"
        else
            echo "Status: NOT RUNNING"
        fi

        echo ""
        echo "=== Process Check ==="
        ps aux | grep "[u]vicorn.*app:create_app" || echo "No uvicorn process found"

        echo ""
        echo "=== Health Check ==="
        curl -s http://localhost:8080/api/health | python3 -m json.tool 2>/dev/null || echo "Server not responding"
        ;;

    logs)
        echo "=== Recent Stdout ==="
        tail -20 "$LOG_DIR/launchd-stdout.log" 2>/dev/null || echo "No stdout log"
        echo ""
        echo "=== Recent Stderr ==="
        tail -20 "$LOG_DIR/launchd-stderr.log" 2>/dev/null || echo "No stderr log"
        echo ""
        echo "=== Application Log ==="
        tail -30 "$LOG_DIR/access.log" 2>/dev/null || echo "No application log"
        ;;

    *)
        echo "Nexus Agent Daemon Manager"
        echo ""
        echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs}"
        echo ""
        echo "  install   - Install the LaunchAgent plist"
        echo "  uninstall - Remove the LaunchAgent plist and stop daemon"
        echo "  start     - Start the daemon"
        echo "  stop      - Stop the daemon"
        echo "  restart   - Restart the daemon"
        echo "  status    - Check daemon and server status"
        echo "  logs      - Show recent log output"
        ;;
esac
