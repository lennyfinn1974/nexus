#!/bin/bash
# ── mlx-openai-server launcher for Nexus ──
# Runs MLX inference server on Apple Silicon with native tool calling support
# Usage: ./mlx-server.sh start|stop|status|test
#
# IMPORTANT: Cannot run simultaneously with Ollama — they share unified memory.
# Stop Ollama first: brew services stop ollama

set -euo pipefail

VENV="/Users/lennyfinn/Nexus/backend/.mlx-venv"
MODEL_PATH="/Users/lennyfinn/Nexus/models/qwen3-coder-30b-mlx-4bit"
CONFIG="/Users/lennyfinn/Nexus/backend/deploy/mlx-server-config.yaml"
PORT=8083
LOG="/Users/lennyfinn/Nexus/backend/logs/mlx-server.log"
PID_FILE="/Users/lennyfinn/Nexus/backend/logs/mlx-server.pid"

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "mlx-server already running (PID $(cat "$PID_FILE"))"
        return 1
    fi

    # Check if Ollama is running
    if pgrep -f "ollama serve" > /dev/null 2>&1; then
        echo "⚠️  Ollama is running! Stop it first to free GPU memory:"
        echo "   brew services stop ollama"
        return 1
    fi

    # Check model exists
    if [ ! -d "$MODEL_PATH" ]; then
        echo "❌ Model not found at $MODEL_PATH"
        echo "   Download: huggingface-cli download mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --local-dir $MODEL_PATH"
        return 1
    fi

    echo "Starting mlx-openai-server on port $PORT..."
    source "$VENV/bin/activate"

    mlx-openai-server \
        --config "$CONFIG" \
        --port "$PORT" \
        > "$LOG" 2>&1 &

    echo $! > "$PID_FILE"
    echo "PID: $(cat "$PID_FILE") — waiting for model load..."

    # Wait for health/ready
    for i in $(seq 1 60); do
        if curl -sf http://localhost:$PORT/v1/models > /dev/null 2>&1; then
            echo "✅ mlx-openai-server is ready on http://localhost:$PORT"
            echo "   OpenAI-compatible: http://localhost:$PORT/v1/chat/completions"
            echo "   Tool call parser: qwen3_coder"
            return 0
        fi
        sleep 2
    done

    echo "❌ mlx-server failed to start. Check $LOG"
    return 1
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo "mlx-server stopped (PID $PID)"
        fi
        rm -f "$PID_FILE"
    else
        kill $(lsof -ti :$PORT) 2>/dev/null && echo "mlx-server stopped" || echo "mlx-server not running"
    fi
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "mlx-server running (PID $(cat "$PID_FILE"))"
        curl -sf http://localhost:$PORT/v1/models 2>/dev/null | python3 -m json.tool 2>/dev/null
    else
        echo "mlx-server not running"
    fi
}

test_tool_call() {
    echo "Testing tool calling on mlx-openai-server..."
    RESULT=$(curl -s http://localhost:$PORT/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",
            "messages": [
                {"role": "system", "content": "You are an AI assistant. Use tools for real-time data."},
                {"role": "user", "content": "What is the weather in Dubai?"}
            ],
            "tools": [
                {"type": "function", "function": {"name": "google_search", "description": "Search the web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
            ],
            "stream": false
        }')

    echo "$RESULT" | python3 -m json.tool 2>/dev/null

    if echo "$RESULT" | grep -q "tool_calls"; then
        echo ""
        echo "✅ Tool calling works!"
    else
        echo ""
        echo "❌ No tool calls in response"
    fi
}

case "${1:-status}" in
    start)  start ;;
    stop)   stop ;;
    status) status ;;
    test)   test_tool_call ;;
    *)      echo "Usage: $0 {start|stop|status|test}" ;;
esac
