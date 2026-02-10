#!/bin/bash
# Nexus v2 - Startup Script
set -e

echo "🚀 Starting Nexus v2..."

# Navigate to Nexus directory
cd "$(dirname "$0")"

# Activate virtual environment
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
else
    echo "❌ Virtual environment not found. Run setup first."
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Please configure environment."
    exit 1
fi

# Start Nexus backend
echo "🌟 Starting Nexus backend on http://localhost:8081"
echo "🛠️  Admin interface: http://localhost:8081/admin"
echo "🤝 Bridge setup: Configure OpenClaw connection in admin"
echo ""
echo "Press Ctrl+C to stop Nexus"

cd backend
python3 main.py