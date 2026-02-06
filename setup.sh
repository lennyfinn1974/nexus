#!/bin/bash
# Nexus v2 — Setup Script
set -e

echo "══════════════════════════════════════"
echo "   Nexus v2 — Setup"
echo "══════════════════════════════════════"

cd "$(dirname "$0")"

# Create .env from example if not present
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env from template"
    echo "   → Edit .env and add your ANTHROPIC_API_KEY"
else
    echo "✅ .env already exists"
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt
echo "✅ Dependencies installed"

# Create directories
mkdir -p data skills docs_input
echo "✅ Directories created"

echo ""
echo "══════════════════════════════════════"
echo "   Setup complete!"
echo ""
echo "   1. Edit .env and set ANTHROPIC_API_KEY"
echo "   2. Run: cd backend && python3 main.py"
echo "   3. Open: http://localhost:8080"
echo "   4. Admin: http://localhost:8080/admin"
echo ""
echo "   All settings can be managed from the"
echo "   Admin UI after first boot."
echo "══════════════════════════════════════"
