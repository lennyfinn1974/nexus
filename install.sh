#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
# Nexus Agent — Universal Installer
# Supports: macOS (Intel/Apple Silicon), Ubuntu/Debian Linux
# ════════════════════════════════════════════════════════════════

set -euo pipefail

NEXUS_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$NEXUS_DIR/backend"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "\n${CYAN}${BOLD}── $* ──${NC}"; }

# ── Detect platform ──────────────────────────────────────────

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin) PKG_MGR="brew" ;;
    Linux)
        if command -v apt-get &>/dev/null; then
            PKG_MGR="apt"
        elif command -v dnf &>/dev/null; then
            PKG_MGR="dnf"
        else
            err "Unsupported Linux distribution. Requires apt (Debian/Ubuntu) or dnf (Fedora/RHEL)."
            exit 1
        fi
        ;;
    *)
        err "Unsupported OS: $OS. Nexus supports macOS and Linux."
        exit 1
        ;;
esac

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     Nexus Agent — Installer          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""
info "OS: $OS ($ARCH)"
info "Package manager: $PKG_MGR"
info "Install directory: $NEXUS_DIR"
echo ""

# ── Helper: check if command exists with minimum version ──

check_version() {
    local cmd="$1"
    local min_major="$2"
    local min_minor="${3:-0}"

    if ! command -v "$cmd" &>/dev/null; then
        return 1
    fi

    local version
    version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [ "$major" -gt "$min_major" ] 2>/dev/null; then
        return 0
    elif [ "$major" -eq "$min_major" ] && [ "$minor" -ge "$min_minor" ] 2>/dev/null; then
        return 0
    fi
    return 1
}

# ── 1. Homebrew (macOS only) ─────────────────────────────────

if [ "$OS" = "Darwin" ] && ! command -v brew &>/dev/null; then
    step "Installing Homebrew"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to PATH for this session
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    ok "Homebrew installed"
fi

# ── 2. Python 3.10+ ─────────────────────────────────────────

step "Checking Python"

PYTHON_CMD=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON_CMD="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    info "Installing Python 3.12..."
    case "$PKG_MGR" in
        brew) brew install python@3.12 ;;
        apt)  sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3.12-dev ;;
        dnf)  sudo dnf install -y python3.12 python3.12-devel ;;
    esac
    PYTHON_CMD="python3.12"
fi
ok "Python: $($PYTHON_CMD --version 2>&1)"

# ── 3. Node.js 20+ ──────────────────────────────────────────

step "Checking Node.js"

if ! check_version node 20; then
    info "Installing Node.js 20+..."
    case "$PKG_MGR" in
        brew) brew install node ;;
        apt)
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt-get install -y nodejs
            ;;
        dnf) sudo dnf install -y nodejs ;;
    esac
fi
ok "Node.js: $(node --version 2>&1)"
ok "npm: $(npm --version 2>&1)"

# ── 4. PostgreSQL ────────────────────────────────────────────

step "Checking PostgreSQL"

PG_INSTALLED=false
if command -v psql &>/dev/null; then
    PG_INSTALLED=true
fi

if [ "$PG_INSTALLED" = false ]; then
    info "Installing PostgreSQL..."
    case "$PKG_MGR" in
        brew)
            brew install postgresql@16
            brew services start postgresql@16
            # Wait for PostgreSQL to be ready
            sleep 3
            ;;
        apt)
            sudo apt-get update
            sudo apt-get install -y postgresql postgresql-contrib
            sudo systemctl enable postgresql
            sudo systemctl start postgresql
            sleep 2
            ;;
        dnf)
            sudo dnf install -y postgresql-server postgresql-contrib
            sudo postgresql-setup --initdb 2>/dev/null || true
            sudo systemctl enable postgresql
            sudo systemctl start postgresql
            sleep 2
            ;;
    esac
fi

# Detect psql path (Homebrew may not add to PATH immediately)
PSQL_CMD="psql"
if ! command -v psql &>/dev/null; then
    for candidate in /opt/homebrew/opt/postgresql@16/bin/psql /opt/homebrew/opt/postgresql@17/bin/psql /usr/local/bin/psql; do
        if [ -x "$candidate" ]; then
            PSQL_CMD="$candidate"
            break
        fi
    done
fi
ok "PostgreSQL: $($PSQL_CMD --version 2>&1 | head -1)"

# Create nexus database
info "Creating nexus database..."
if [ "$OS" = "Darwin" ]; then
    createdb nexus 2>/dev/null && ok "Database 'nexus' created" || ok "Database 'nexus' already exists"
else
    sudo -u postgres createdb nexus 2>/dev/null && ok "Database 'nexus' created" || ok "Database 'nexus' already exists"
    # Grant access to current user
    sudo -u postgres psql -c "CREATE USER $USER WITH SUPERUSER;" 2>/dev/null || true
fi

# Determine connection string
if [ "$OS" = "Darwin" ]; then
    DB_URL="postgresql+asyncpg://$(whoami)@localhost:5432/nexus"
else
    DB_URL="postgresql+asyncpg://$USER@localhost:5432/nexus"
fi

# ── 5. Ollama (optional) ────────────────────────────────────

step "Ollama (Local AI)"

if command -v ollama &>/dev/null; then
    ok "Ollama already installed: $(ollama --version 2>&1 | head -1)"
else
    echo -n "Install Ollama for local AI models? [Y/n] "
    read -r INSTALL_OLLAMA
    if [ "${INSTALL_OLLAMA:-Y}" != "n" ] && [ "${INSTALL_OLLAMA:-Y}" != "N" ]; then
        info "Installing Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama installed"
        echo -n "Pull a default model? (e.g. llama3.1, qwen2.5) [skip] "
        read -r OLLAMA_MODEL
        if [ -n "$OLLAMA_MODEL" ]; then
            info "Pulling $OLLAMA_MODEL (this may take a while)..."
            ollama pull "$OLLAMA_MODEL" || warn "Model pull failed — you can do this later with 'ollama pull $OLLAMA_MODEL'"
        fi
    else
        info "Skipping Ollama"
    fi
fi

# ── 6. Python virtual environment ────────────────────────────

step "Setting up Python environment"

if [ ! -d "$NEXUS_DIR/venv" ]; then
    info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$NEXUS_DIR/venv"
fi
ok "Virtual environment: $NEXUS_DIR/venv"

# Activate venv
source "$NEXUS_DIR/venv/bin/activate"

info "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r "$NEXUS_DIR/requirements.txt" -q
ok "Python dependencies installed"

# ── 7. Build frontends ───────────────────────────────────────

step "Building frontends"

if [ -d "$NEXUS_DIR/chat-ui" ]; then
    info "Building chat UI..."
    cd "$NEXUS_DIR/chat-ui"
    npm install --silent 2>/dev/null
    npm run build 2>/dev/null
    ok "Chat UI built"
    cd "$NEXUS_DIR"
fi

if [ -d "$NEXUS_DIR/admin-ui" ]; then
    info "Building admin UI..."
    cd "$NEXUS_DIR/admin-ui"
    npm install --silent 2>/dev/null
    npm run build 2>/dev/null
    ok "Admin UI built"
    cd "$NEXUS_DIR"
fi

# ── 8. Generate .env ─────────────────────────────────────────

step "Configuring environment"

ADMIN_KEY=$(openssl rand -hex 24)

if [ ! -f "$NEXUS_DIR/.env" ]; then
    cat > "$NEXUS_DIR/.env" <<ENV
# ════════════════════════════════════════════════════════
# Nexus v2 — Bootstrap Configuration
# ════════════════════════════════════════════════════════
# Generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# After first boot, settings are managed via Admin UI.

# Admin API key (auto-generated — protects /api/admin/* endpoints)
ADMIN_API_KEY=${ADMIN_KEY}

# PostgreSQL connection string
DATABASE_URL=${DB_URL}
DATABASE_SSL=false

# Server
HOST=127.0.0.1
PORT=8080
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080

# Anthropic API Key (add via Admin UI or set here)
ANTHROPIC_API_KEY=

# Ollama (local models)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=

# Routing (0=always Claude, 100=always local)
COMPLEXITY_THRESHOLD=60
ENV

    ok ".env generated"
    info "Admin API Key: ${ADMIN_KEY}"
    warn "Save this key! You'll need it to access the admin panel."
else
    ok ".env already exists (keeping existing configuration)"
fi

# ── 9. Initialize database ───────────────────────────────────

step "Initializing database"

cd "$NEXUS_DIR"
PYTHONPATH="$BACKEND_DIR" "$NEXUS_DIR/venv/bin/python" -c "
import asyncio, os, sys
sys.path.insert(0, '$BACKEND_DIR')
from dotenv import load_dotenv
load_dotenv('$NEXUS_DIR/.env')

async def init():
    from storage.engine import init_engine
    from storage.models import Base
    url = os.getenv('DATABASE_URL', '$DB_URL')
    engine = await init_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print('Tables created successfully')

asyncio.run(init())
" 2>&1 || warn "Database initialization had issues — will retry on first start"

ok "Database initialized"

# ── 10. Make scripts executable ──────────────────────────────

chmod +x "$NEXUS_DIR/nexus.sh"
chmod +x "$NEXUS_DIR/install.sh"

# ── Done! ────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Nexus Agent installed successfully!   ${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Start:${NC}    ./nexus.sh start"
echo -e "  ${BOLD}Status:${NC}   ./nexus.sh status"
echo -e "  ${BOLD}Logs:${NC}     ./nexus.sh logs"
echo -e "  ${BOLD}Admin:${NC}    http://localhost:8080/admin"
echo ""
echo -e "  ${BOLD}Auto-start:${NC}  ./nexus.sh install  (launchd/systemd)"
echo ""
echo -e "  ${YELLOW}First time?${NC} The setup wizard will guide you through"
echo -e "  configuration when you open the admin panel."
echo ""
