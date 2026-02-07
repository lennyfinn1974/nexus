"""macOS plugin — Apple Notes, Reminders, Calendar, system info via AppleScript."""

import asyncio
import logging
import platform

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.macos")


class MacOSPlugin(NexusPlugin):
    name = "macos"
    description = "macOS integration — Notes, Reminders, Calendar, system info"
    version = "1.0.0"

    async def setup(self):
        if platform.system() != "Darwin":
            logger.info("macOS plugin disabled — not running on macOS")
            return False
        logger.info("macOS plugin ready")
        return True

    def register_tools(self):
        self.add_tool(
            "macos_create_note",
            "Create a new note in Apple Notes",
            {"title": "Note title", "content": "Note body", "folder": "Folder (default Notes)"},
            self._create_note,
        )
        self.add_tool(
            "macos_search_notes",
            "Search Apple Notes by keyword",
            {"query": "Search text"},
            self._search_notes,
        )
        self.add_tool(
            "macos_create_reminder",
            "Create a reminder in Apple Reminders",
            {"title": "Reminder text", "list": "Reminders list (optional)"},
            self._create_reminder,
        )
        self.add_tool(
            "macos_list_reminders",
            "List pending reminders",
            {"list": "Reminders list (default Reminders)", "limit": "Max items (default 10)"},
            self._list_reminders,
        )
        self.add_tool(
            "macos_calendar_events",
            "List upcoming calendar events",
            {"days": "Number of days ahead (default 7)"},
            self._calendar_events,
        )
        self.add_tool(
            "macos_create_event",
            "Create a calendar event",
            {"title": "Event title", "start_date": "Start date/time", "end_date": "End date/time"},
            self._create_event,
        )
        self.add_tool(
            "macos_system_info",
            "Get system information (CPU, memory, disk)",
            {},
            self._system_info,
        )
        self.add_tool(
            "macos_open_app",
            "Open a macOS application",
            {"app": "Application name (e.g. Safari, Terminal)"},
            self._open_app,
        )

    def register_commands(self):
        self.add_command("note", "Create a note: /note <title> | <content>", self._cmd_note)
        self.add_command("remind", "Create a reminder: /remind <text>", self._cmd_remind)
        self.add_command("calendar", "Show calendar: /calendar [days]", self._cmd_calendar)
        self.add_command("sysinfo", "Show system info: /sysinfo", self._cmd_sysinfo)

    # ── Helpers ──

    async def _osascript(self, script: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode != 0:
            return f"Error: {stderr.decode().strip()}"
        return stdout.decode().strip()

    # ── Tool Handlers ──

    async def _create_note(self, params: dict) -> str:
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
        result = await self._osascript(script)
        if result.startswith("Error:"):
            return result
        return f"Created note: {result}"

    async def _search_notes(self, params: dict) -> str:
        query = params.get("query", "").replace('"', '\\"')
        if not query:
            return "Error: query is required"

        script = f'''
        tell application "Notes"
            set matchingNotes to notes whose name contains "{query}" or plaintext contains "{query}"
            set output to ""
            set i to 0
            repeat with n in matchingNotes
                if i >= 10 then exit repeat
                set output to output & name of n & linefeed
                set i to i + 1
            end repeat
            return output
        end tell
        '''
        result = await self._osascript(script)
        if result.startswith("Error:"):
            return result
        if not result:
            return f"No notes matching '{query}'."

        notes = [n for n in result.split("\n") if n.strip()]
        lines = [f"**Notes matching '{query}' ({len(notes)}):**"]
        for n in notes:
            lines.append(f"- {n}")
        return "\n".join(lines)

    async def _create_reminder(self, params: dict) -> str:
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
        result = await self._osascript(script)
        if result.startswith("Error:"):
            return result
        return f"Created reminder: {result}"

    async def _list_reminders(self, params: dict) -> str:
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
            set i to 0
            repeat with r in reminderList
                if i >= {limit} then exit repeat
                set output to output & name of r & linefeed
                set i to i + 1
            end repeat
            return output
        end tell
        '''
        result = await self._osascript(script)
        if result.startswith("Error:"):
            return result
        if not result:
            return "No pending reminders."

        items = [r for r in result.split("\n") if r.strip()]
        lines = [f"**Reminders ({len(items)}):**"]
        for r in items:
            lines.append(f"- {r}")
        return "\n".join(lines)

    async def _calendar_events(self, params: dict) -> str:
        days = int(params.get("days", "7"))

        script = f'''
        set startDate to current date
        set endDate to startDate + ({days} * days)
        tell application "Calendar"
            set output to ""
            repeat with cal in calendars
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
        result = await self._osascript(script)
        if result.startswith("Error:"):
            return result
        if not result:
            return f"No events in the next {days} days."

        events = sorted([e for e in result.split("\n") if e.strip()])
        lines = [f"**Upcoming Events (next {days} days):**"]
        for e in events[:20]:
            parts = e.split(" | ", 1)
            if len(parts) == 2:
                lines.append(f"- **{parts[1]}** — {parts[0]}")
            else:
                lines.append(f"- {e}")
        return "\n".join(lines)

    async def _create_event(self, params: dict) -> str:
        title = params.get("title", "").replace('"', '\\"')
        start = params.get("start_date", "").replace('"', '\\"')
        end = params.get("end_date", "").replace('"', '\\"')
        if not title or not start or not end:
            return "Error: title, start_date, and end_date are required"

        script = f'''
        tell application "Calendar"
            set startDate to date "{start}"
            set endDate to date "{end}"
            tell first calendar
                set newEvent to make new event with properties {{summary:"{title}", start date:startDate, end date:endDate}}
                return summary of newEvent
            end tell
        end tell
        '''
        result = await self._osascript(script)
        if result.startswith("Error:"):
            return result
        return f"Created event: {result}"

    async def _system_info(self, params: dict) -> str:
        try:
            import psutil
            import datetime

            cpu_percent = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            boot = psutil.boot_time()
            uptime = datetime.datetime.now() - datetime.datetime.fromtimestamp(boot)
            hours, remainder = divmod(int(uptime.total_seconds()), 3600)
            minutes = remainder // 60

            return (
                f"**System Info**\n"
                f"OS: {platform.system()} {platform.release()} ({platform.machine()})\n"
                f"CPU: {psutil.cpu_count()} cores, {cpu_percent}% usage\n"
                f"Memory: {mem.used / (1024**3):.1f} / {mem.total / (1024**3):.1f} GB ({mem.percent}%)\n"
                f"Disk: {disk.used / (1024**3):.1f} / {disk.total / (1024**3):.1f} GB ({disk.percent}%)\n"
                f"Uptime: {hours}h {minutes}m"
            )
        except ImportError:
            # Fallback to shell commands
            proc = await asyncio.create_subprocess_exec(
                "sysctl", "-n", "hw.ncpu",
                stdout=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            cores = stdout.decode().strip()

            proc2 = await asyncio.create_subprocess_exec(
                "sysctl", "-n", "hw.memsize",
                stdout=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await proc2.communicate()
            mem_bytes = int(stdout2.decode().strip())
            mem_gb = mem_bytes / (1024**3)

            return (
                f"**System Info**\n"
                f"OS: {platform.system()} {platform.release()}\n"
                f"CPU: {cores} cores\n"
                f"Memory: {mem_gb:.1f} GB total"
            )

    async def _open_app(self, params: dict) -> str:
        app = params.get("app", "").replace('"', '\\"')
        if not app:
            return "Error: app name is required"

        script = f'''
        tell application "{app}"
            activate
        end tell
        return "Opened {app}"
        '''
        return await self._osascript(script)

    # ── Slash Commands ──

    async def _cmd_note(self, args: str) -> str:
        if "|" in args:
            title, content = args.split("|", 1)
            return await self._create_note({"title": title.strip(), "content": content.strip()})
        return await self._create_note({"title": args.strip(), "content": ""})

    async def _cmd_remind(self, args: str) -> str:
        if not args.strip():
            return await self._list_reminders({})
        return await self._create_reminder({"title": args.strip()})

    async def _cmd_calendar(self, args: str) -> str:
        days = args.strip() if args.strip().isdigit() else "7"
        return await self._calendar_events({"days": days})

    async def _cmd_sysinfo(self, args: str) -> str:
        return await self._system_info({})
