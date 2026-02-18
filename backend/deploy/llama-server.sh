#!/bin/bash
# ── llama-server launcher for Nexus ──
# Runs llama.cpp server with the same model Ollama uses (qwen3-coder:30b GGUF)
# Usage: ./llama-server.sh start|stop|status|test
#
# IMPORTANT: Cannot run simultaneously with Ollama — they share GPU memory.
# Stop Ollama first: brew services stop ollama

set -euo pipefail

MODEL="/Users/lennyfinn/.ollama/models/blobs/sha256-1194192cf2a187eb02722edcc3f77b11d21f537048ce04b67ccf8ba78863006a"
PORT=8082
LOG="/Users/lennyfinn/Nexus/backend/logs/llama-server.log"
PID_FILE="/Users/lennyfinn/Nexus/backend/logs/llama-server.pid"

# Tuned for M4 Pro 24GB:
# - 40/48 layers on GPU (leaves ~5GB for OS + KV cache)
# - 4096 context (enough for Nexus tool calling)
# - --jinja enables chat template tool calling
# - -np 1 single parallel slot (less memory)
GPU_LAYERS=40
CTX_SIZE=4096
PARALLEL=1

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "llama-server already running (PID $(cat "$PID_FILE"))"
        return 1
    fi

    # Check if Ollama is running
    if pgrep -f "ollama serve" > /dev/null 2>&1; then
        echo "⚠️  Ollama is running! Stop it first to free GPU memory:"
        echo "   brew services stop ollama"
        return 1
    fi

    echo "Starting llama-server on port $PORT..."
    llama-server \
        --model "$MODEL" \
        --port "$PORT" \
        --jinja \
        --n-gpu-layers "$GPU_LAYERS" \
        --ctx-size "$CTX_SIZE" \
        --no-warmup \
        --threads 8 \
        -np "$PARALLEL" \
        > "$LOG" 2>&1 &

    echo $! > "$PID_FILE"
    echo "PID: $(cat "$PID_FILE") — waiting for model load..."

    # Wait for health check
    for i in $(seq 1 30); do
        if curl -sf http://localhost:$PORT/health > /dev/null 2>&1; then
            echo "✅ llama-server is ready on http://localhost:$PORT"
            echo "   OpenAI-compatible: http://localhost:$PORT/v1/chat/completions"
            return 0
        fi
        sleep 2
    done

    echo "❌ llama-server failed to start. Check $LOG"
    return 1
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo "llama-server stopped (PID $PID)"
        fi
        rm -f "$PID_FILE"
    else
        # Fallback: kill by port
        kill $(lsof -ti :$PORT) 2>/dev/null && echo "llama-server stopped" || echo "llama-server not running"
    fi
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "llama-server running (PID $(cat "$PID_FILE"))"
        curl -sf http://localhost:$PORT/health 2>/dev/null | python3 -m json.tool 2>/dev/null
    else
        echo "llama-server not running"
    fi
}

test_tool_call() {
    echo "Testing tool calling on llama-server..."
    RESULT=$(curl -s http://localhost:$PORT/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "qwen3-coder",
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
