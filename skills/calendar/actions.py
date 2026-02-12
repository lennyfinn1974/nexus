import subprocess
import platform
from typing import Dict


def _run_applescript(script: str) -> str:
    if platform.system() != "Darwin":
        return "Error: Apple Calendar requires macOS"
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


def list_events(params: Dict) -> str:
    """List upcoming calendar events."""
    days = int(params.get("days", "7"))

    script = f'''
    set startDate to current date
    set endDate to startDate + ({days} * days)

    tell application "Calendar"
        set output to ""
        set allCalendars to calendars
        repeat with cal in allCalendars
            set eventList to (every event of cal whose start date >= startDate and start date <= endDate)
            repeat with evt in eventList
                set evtStart to start date of evt
                set evtName to summary of evt
                set output to output & (evtStart as string) & " | " & evtName & linefeed
            end repeat
        end repeat
        return output
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    if not result:
        return f"No events in the next {days} days."

    events = [e for e in result.split("\n") if e.strip()]
    events.sort()
    lines = [f"**Upcoming Events (next {days} days, {len(events)} found):**"]
    for e in events[:20]:
        parts = e.split(" | ", 1)
        if len(parts) == 2:
            lines.append(f"- **{parts[1]}** — {parts[0]}")
        else:
            lines.append(f"- {e}")
    return "\n".join(lines)


def create_event(params: Dict) -> str:
    """Create a new calendar event."""
    title = params.get("title", "").replace('"', '\\"')
    start_date = params.get("start_date", "").replace('"', '\\"')
    end_date = params.get("end_date", "").replace('"', '\\"')
    calendar_name = params.get("calendar", "").replace('"', '\\"')

    if not title or not start_date or not end_date:
        return "Error: title, start_date, and end_date are required"

    if calendar_name:
        cal_ref = f'calendar "{calendar_name}"'
    else:
        cal_ref = "first calendar"

    script = f'''
    tell application "Calendar"
        set startDate to date "{start_date}"
        set endDate to date "{end_date}"
        tell {cal_ref}
            set newEvent to make new event with properties {{summary:"{title}", start date:startDate, end date:endDate}}
            return summary of newEvent
        end tell
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    return f"Created event: {result}"


def list_calendars(params: Dict) -> str:
    """List available calendars."""
    script = '''
    tell application "Calendar"
        set output to ""
        repeat with cal in calendars
            set output to output & name of cal & linefeed
        end repeat
        return output
    end tell
    '''

    result = _run_applescript(script)
    if result.startswith("Error:"):
        return result
    if not result:
        return "No calendars found."

    cals = [c for c in result.split("\n") if c.strip()]
    lines = ["**Available Calendars:**"]
    for c in cals:
        lines.append(f"- {c}")
    return "\n".join(lines)
