import subprocess
import platform
from typing import Dict


def _run_applescript(script: str) -> str:
    if platform.system() != "Darwin":
        return "Error: Apple Reminders requires macOS"
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


def create_reminder(params: Dict) -> str:
    """Create a new reminder in Apple Reminders."""
    title = params.get("title", "").replace('"', '\\"')
    target_list = params.get("list", "Reminders").replace('"', '\\"')

    if not title:
        return "Error: title is required"

    script = f'''
    tell application "Reminders"
        try
            set targetList to list "{target_list}"
        on error
            set targetList to default list
        end try
        set newReminder to make new reminder in targetList with properties {{name:"{title}"}}
        return name of newReminder
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    return f"Created reminder: {result}"


def list_reminders(params: Dict) -> str:
    """List reminders from a list."""
    target_list = params.get("list", "Reminders").replace('"', '\\"')
    limit = int(params.get("limit", "10"))

    script = f'''
    tell application "Reminders"
        try
            set targetList to list "{target_list}"
        on error
            set targetList to default list
        end try
        set reminderList to reminders of targetList whose completed is false
        set output to ""
        set maxCount to {limit}
        set i to 0
        repeat with r in reminderList
            if i >= maxCount then exit repeat
            set output to output & name of r & linefeed
            set i to i + 1
        end repeat
        return output
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    if not result:
        return f"No pending reminders in '{target_list}'."

    items = [r for r in result.split("\n") if r.strip()]
    lines = [f"**Reminders ({len(items)}):**"]
    for r in items:
        lines.append(f"- {r}")
    return "\n".join(lines)


def complete_reminder(params: Dict) -> str:
    """Mark a reminder as complete."""
    title = params.get("title", "").replace('"', '\\"')
    if not title:
        return "Error: title is required"

    script = f'''
    tell application "Reminders"
        set matchingReminders to reminders whose name is "{title}" and completed is false
        if (count of matchingReminders) > 0 then
            set completed of item 1 of matchingReminders to true
            return "Completed: {title}"
        else
            return "Not found: {title}"
        end if
    end tell
    '''

    return _run_applescript(script)
