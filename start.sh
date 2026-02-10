#!/usr/bin/env bash
# Start Nexus in production mode
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Activate venv
source venv/bin/activate

# Export .env
set -a
source .env 2>/dev/null || true
set +a

echo "Starting Nexus..."
echo "  URL: http://${HOST:-127.0.0.1}:${PORT:-8080}"
echo "  Admin: http://${HOST:-127.0.0.1}:${PORT:-8080}/admin"
echo ""

exec python backend/main.py
