import subprocess
import os
from typing import Dict


def spotlight_search(params: Dict) -> str:
    """Search for files using macOS Spotlight (mdfind)."""
    query = params.get("query", "").strip()
    directory = params.get("directory", "").strip()
    if not query:
        return "Error: query is required"

    cmd = ["mdfind"]
    if directory:
        cmd.extend(["-onlyin", os.path.expanduser(directory)])
    cmd.append(query)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"

        files = result.stdout.strip().split("\n")
        files = [f for f in files if f][:20]  # limit to 20

        if not files:
            return f"No files found for '{query}'."

        lines = [f"**Found {len(files)} files for '{query}':**"]
        for f in files:
            lines.append(f"- {f}")
        return "\n".join(lines)
    except FileNotFoundError:
        return "Error: mdfind not available (macOS only)"
    except subprocess.TimeoutExpired:
        return "Search timed out."


def find_files(params: Dict) -> str:
    """Find files by name pattern."""
    pattern = params.get("pattern", "").strip()
    directory = params.get("directory", "~").strip()
    max_depth = params.get("max_depth", "5")
    if not pattern:
        return "Error: pattern is required"

    directory = os.path.expanduser(directory)
    if not os.path.isdir(directory):
        return f"Error: directory not found: {directory}"

    cmd = ["find", directory, "-maxdepth", str(max_depth), "-iname", f"*{pattern}*", "-type", "f"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        files = result.stdout.strip().split("\n")
        files = [f for f in files if f][:20]

        if not files:
            return f"No files matching '*{pattern}*' found."

        lines = [f"**Found {len(files)} files matching '{pattern}':**"]
        for f in files:
            lines.append(f"- {f}")
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return "Search timed out."


def search_file_contents(params: Dict) -> str:
    """Search for text within files."""
    pattern = params.get("pattern", "").strip()
    directory = params.get("directory", ".").strip()
    file_type = params.get("file_type", "").strip()
    if not pattern:
        return "Error: pattern is required"

    directory = os.path.expanduser(directory)
    cmd = ["grep", "-rl", "--max-count=1", pattern, directory]
    if file_type:
        cmd.extend(["--include", f"*.{file_type}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        files = result.stdout.strip().split("\n")
        files = [f for f in files if f][:15]

        if not files:
            return f"No files containing '{pattern}' found."

        lines = [f"**Files containing '{pattern}':**"]
        for f in files:
            lines.append(f"- {f}")
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return "Search timed out."
