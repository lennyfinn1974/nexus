import subprocess
import platform
from typing import Dict


def _run_applescript(script: str) -> str:
    """Run an AppleScript and return the output."""
    if platform.system() != "Darwin":
        return "Error: Apple Notes requires macOS"
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: AppleScript timed out"


def create_note(params: Dict) -> str:
    """Create a new note in Apple Notes."""
    title = params.get("title", "Untitled").replace('"', '\\"')
    content = params.get("content", "").replace('"', '\\"')
    folder = params.get("folder", "Notes").replace('"', '\\"')

    script = f'''
    tell application "Notes"
        try
            set targetFolder to folder "{folder}"
        on error
            set targetFolder to default account's folder "Notes"
        end try
        set newNote to make new note at targetFolder with properties {{name:"{title}", body:"{content}"}}
        return name of newNote
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    return f"Created note: {result}"


def list_notes(params: Dict) -> str:
    """List recent notes from Apple Notes."""
    folder = params.get("folder", "Notes").replace('"', '\\"')
    limit = int(params.get("limit", "10"))

    script = f'''
    tell application "Notes"
        try
            set noteList to notes of folder "{folder}"
        on error
            set noteList to notes of default account's folder "Notes"
        end try
        set output to ""
        set maxCount to {limit}
        set i to 0
        repeat with n in noteList
            if i >= maxCount then exit repeat
            set output to output & name of n & linefeed
            set i to i + 1
        end repeat
        return output
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    if not result:
        return "No notes found."

    notes = [n for n in result.split("\n") if n.strip()]
    lines = [f"**Recent Notes ({len(notes)}):**"]
    for n in notes:
        lines.append(f"- {n}")
    return "\n".join(lines)


def search_notes(params: Dict) -> str:
    """Search notes by keyword."""
    query = params.get("query", "").replace('"', '\\"')
    if not query:
        return "Error: query is required"

    script = f'''
    tell application "Notes"
        set matchingNotes to notes whose name contains "{query}" or plaintext contains "{query}"
        set output to ""
        set maxCount to 10
        set i to 0
        repeat with n in matchingNotes
            if i >= maxCount then exit repeat
            set output to output & name of n & linefeed
            set i to i + 1
        end repeat
        return output
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    if not result:
        return f"No notes matching '{query}'."

    notes = [n for n in result.split("\n") if n.strip()]
    lines = [f"**Notes matching '{query}' ({len(notes)}):**"]
    for n in notes:
        lines.append(f"- {n}")
    return "\n".join(lines)
