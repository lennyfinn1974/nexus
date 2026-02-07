import subprocess
import json
from typing import Dict


def _run_ollama(*args: str, timeout: int = 60) -> tuple:
    """Run an ollama CLI command."""
    try:
        result = subprocess.run(
            ["ollama", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return "", "ollama CLI not found", 1
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1


def ollama_list(params: Dict) -> str:
    """List all installed Ollama models."""
    stdout, stderr, rc = _run_ollama("list")
    if rc != 0:
        return f"Error: {stderr}"
    if not stdout:
        return "No models installed."

    lines = stdout.strip().split("\n")
    if len(lines) <= 1:
        return "No models installed."

    result = ["**Installed Ollama Models:**"]
    for line in lines[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 3:
            name = parts[0]
            size = parts[2] if len(parts) > 2 else "?"
            result.append(f"- {name} ({size})")

    return "\n".join(result)


def ollama_pull(params: Dict) -> str:
    """Pull/download an Ollama model."""
    model = params.get("model", "").strip()
    if not model:
        return "Error: model name is required"

    stdout, stderr, rc = _run_ollama("pull", model, timeout=300)
    if rc != 0:
        return f"Error pulling {model}: {stderr}"
    return f"Successfully pulled {model}.\n{stdout}"


def ollama_remove(params: Dict) -> str:
    """Remove an installed Ollama model."""
    model = params.get("model", "").strip()
    if not model:
        return "Error: model name is required"

    stdout, stderr, rc = _run_ollama("rm", model)
    if rc != 0:
        return f"Error removing {model}: {stderr}"
    return f"Removed {model}."


def ollama_model_info(params: Dict) -> str:
    """Get details about an installed model."""
    model = params.get("model", "").strip()
    if not model:
        return "Error: model name is required"

    stdout, stderr, rc = _run_ollama("show", model)
    if rc != 0:
        return f"Error: {stderr}"

    # Truncate to avoid overwhelming output
    lines = stdout.split("\n")[:30]
    return f"**Model: {model}**\n" + "\n".join(lines)


def ollama_running(params: Dict) -> str:
    """List currently running/loaded models."""
    stdout, stderr, rc = _run_ollama("ps")
    if rc != 0:
        return f"Error: {stderr}"
    if not stdout or stdout.strip() == "NAME":
        return "No models currently loaded."

    lines = stdout.strip().split("\n")
    if len(lines) <= 1:
        return "No models currently loaded."

    result = ["**Running Ollama Models:**"]
    for line in lines[1:]:
        parts = line.split()
        if parts:
            result.append(f"- {parts[0]}")

    return "\n".join(result)
