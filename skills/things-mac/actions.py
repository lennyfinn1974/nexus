import subprocess
import platform
from typing import Dict


def _run_applescript(script: str) -> str:
    if platform.system() != "Darwin":
        return "Error: Things 3 requires macOS"
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
    except Exception as e:
        return f"Error: {e}"


def create_todo(params: Dict) -> str:
    """Create a new to-do in Things 3."""
    title = params.get("title", "").replace('"', '\\"')
    notes = params.get("notes", "").replace('"', '\\"')
    target_list = params.get("list", "").replace('"', '\\"')
    when = params.get("when", "").replace('"', '\\"')

    if not title:
        return "Error: title is required"

    props = f'name:"{title}"'
    if notes:
        props += f', notes:"{notes}"'

    if target_list:
        script = f'''
        tell application "Things3"
            set newTodo to make new to do with properties {{{props}}} in list "{target_list}"
            return name of newTodo
        end tell
        '''
    else:
        script = f'''
        tell application "Things3"
            set newTodo to make new to do with properties {{{props}}}
            return name of newTodo
        end tell
        '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    return f"Created to-do: {result}"


def list_todos(params: Dict) -> str:
    """List to-dos from Things 3."""
    target_list = params.get("list", "today").lower().replace('"', '\\"')

    list_map = {
        "inbox": "Inbox",
        "today": "Today",
        "upcoming": "Upcoming",
        "anytime": "Anytime",
        "someday": "Someday",
    }
    things_list = list_map.get(target_list, target_list)

    script = f'''
    tell application "Things3"
        set todoList to to dos of list "{things_list}"
        set output to ""
        set maxCount to 20
        set i to 0
        repeat with t in todoList
            if i >= maxCount then exit repeat
            set output to output & name of t & linefeed
            set i to i + 1
        end repeat
        return output
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    if not result:
        return f"No to-dos in {things_list}."

    todos = [t for t in result.split("\n") if t.strip()]
    lines = [f"**{things_list} ({len(todos)} items):**"]
    for t in todos:
        lines.append(f"- {t}")
    return "\n".join(lines)


def complete_todo(params: Dict) -> str:
    """Mark a to-do as complete."""
    title = params.get("title", "").replace('"', '\\"')
    if not title:
        return "Error: title is required"

    script = f'''
    tell application "Things3"
        set matchingTodos to to dos whose name is "{title}"
        if (count of matchingTodos) > 0 then
            set status of item 1 of matchingTodos to completed
            return "Completed: {title}"
        else
            return "Not found: {title}"
        end if
    end tell
    '''

    return _run_applescript(script)
