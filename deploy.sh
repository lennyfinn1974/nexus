#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════
# Nexus Production Deployment Script
# ══════════════════════════════════════════════════════════
set -euo pipefail

# Configuration
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="${1:-/Users/lennyfinn/Desktop/Nexus}"
PYTHON="${PYTHON:-python3}"

echo "═══════════════════════════════════════════"
echo "  Nexus Production Deployment"
echo "═══════════════════════════════════════════"
echo "Source:  $SOURCE_DIR"
echo "Target:  $DEPLOY_DIR"
echo ""

# ── 1. Create deployment directory ──
echo "[1/7] Creating deployment directory..."
mkdir -p "$DEPLOY_DIR"

# ── 2. Copy application files ──
echo "[2/7] Copying application files..."
rsync -av --delete \
    --exclude='venv/' \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='.github/' \
    --exclude='tests/' \
    --exclude='.pytest_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='htmlcov/' \
    --exclude='.coverage' \
    --exclude='*.db' \
    --exclude='*.db-journal' \
    --exclude='*.db-wal' \
    --exclude='backend/logs/*.log*' \
    --exclude='backend/data/' \
    --exclude='.env' \
    --exclude='node_modules/' \
    "$SOURCE_DIR/" "$DEPLOY_DIR/"

# ── 3. Create required directories ──
echo "[3/7] Creating data directories..."
mkdir -p "$DEPLOY_DIR/data"
mkdir -p "$DEPLOY_DIR/data/backups"
mkdir -p "$DEPLOY_DIR/docs"
mkdir -p "$DEPLOY_DIR/docs_input"
mkdir -p "$DEPLOY_DIR/skills"
mkdir -p "$DEPLOY_DIR/backend/logs"

# ── 4. Set up Python virtual environment ──
echo "[4/7] Setting up Python environment..."
if [ ! -d "$DEPLOY_DIR/venv" ]; then
    $PYTHON -m venv "$DEPLOY_DIR/venv"
fi
source "$DEPLOY_DIR/venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$DEPLOY_DIR/requirements.txt"

# ── 5. Create production .env if it doesn't exist ──
echo "[5/7] Checking configuration..."
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
    echo "  Created .env from template — please configure it before starting!"
    echo "  Edit: $DEPLOY_DIR/.env"
else
    echo "  .env already exists — keeping existing configuration"
fi

# ── 6. Create start script ──
echo "[6/7] Creating start script..."
cat > "$DEPLOY_DIR/start.sh" << 'STARTEOF'
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
STARTEOF
chmod +x "$DEPLOY_DIR/start.sh"

# ── 7. Verify deployment ──
echo "[7/7] Verifying deployment..."
VERIFY_RESULT=$($PYTHON -c "
import sys
sys.path.insert(0, '$DEPLOY_DIR/backend')
try:
    from config_manager import ConfigManager
    from storage.database import Database
    from models.router import ModelRouter
    print('OK: All core modules importable')
except ImportError as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" 2>&1) || true
echo "  $VERIFY_RESULT"

echo ""
echo "═══════════════════════════════════════════"
echo "  Deployment Complete!"
echo "═══════════════════════════════════════════"
echo ""
echo "To start Nexus:"
echo "  cd $DEPLOY_DIR && ./start.sh"
echo ""
echo "To configure:"
echo "  Edit $DEPLOY_DIR/.env"
echo ""
