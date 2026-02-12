"""macOS Plugin — Desktop control, file operations, and keyboard automation.

Provides tools for:
- Opening apps and files
- Notifications
- Clipboard access
- Window management
- File operations (move, copy, delete, find, info)
- Keyboard automation (type, shortcuts, key presses)

All operations use osascript (AppleScript) or system commands via asyncio.create_subprocess_exec.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.macos")

MAX_EXEC_TIME = 30  # seconds


class MacOSPlugin(NexusPlugin):
    name = "macos"
    description = "macOS desktop control — apps, files, notifications, clipboard, windows, keyboard"
    version = "1.0.0"

    async def setup(self):
        logger.info("  macOS plugin ready")
        return True

    def register_tools(self):
        # ── Desktop Tools ──
        self.add_tool(
            "macos_open_app",
            "Open a macOS application by name (e.g., 'Safari', 'Terminal', 'Finder')",
            {"app_name": "Application name to open"},
            self._macos_open_app,
            category="system",
        )
        self.add_tool(
            "macos_open_file",
            "Open a file with its default application (like double-clicking in Finder)",
            {"path": "Full path to file or directory to open"},
            self._macos_open_file,
            category="system",
        )
        self.add_tool(
            "macos_notify",
            "Display a macOS notification banner",
            {"title": "Notification title", "message": "Notification message"},
            self._macos_notify,
            category="system",
        )
        self.add_tool(
            "macos_clipboard_get",
            "Get the current clipboard contents",
            {},
            self._macos_clipboard_get,
            category="system",
        )
        self.add_tool(
            "macos_clipboard_set",
            "Set the clipboard to specific text",
            {"text": "Text to copy to clipboard"},
            self._macos_clipboard_set,
            category="system",
        )
        self.add_tool(
            "macos_window_list",
            "List all visible windows from all applications",
            {},
            self._macos_window_list,
            category="system",
        )
        self.add_tool(
            "macos_screenshot",
            "Take a screenshot and save to a file (default: ~/Desktop/screenshot.png)",
            {"path": "Optional: full path where to save screenshot (default: ~/Desktop/screenshot.png)"},
            self._macos_screenshot,
            category="system",
        )

        # ── File Tools ──
        self.add_tool(
            "file_move",
            "Move or rename a file or directory",
            {"src": "Source path", "dest": "Destination path"},
            self._file_move,
            category="files",
        )
        self.add_tool(
            "file_copy",
            "Copy a file or directory",
            {"src": "Source path", "dest": "Destination path"},
            self._file_copy,
            category="files",
        )
        self.add_tool(
            "file_delete",
            "Delete a file or directory (use with caution!)",
            {"path": "Path to delete", "confirm": "Set to 'yes' to confirm deletion"},
            self._file_delete,
            category="files",
        )
        self.add_tool(
            "file_find",
            "Find files matching a pattern (recursive search)",
            {"pattern": "Filename pattern to search for (e.g., '*.txt', 'config*')", "path": "Directory to search in (default: current directory)"},
            self._file_find,
            category="files",
        )
        self.add_tool(
            "file_info",
            "Get detailed info about a file or directory (size, permissions, modified date)",
            {"path": "Path to inspect"},
            self._file_info,
            category="files",
        )

        # ── Keyboard Tools ──
        self.add_tool(
            "keyboard_type",
            "Type text as if typed on the keyboard (simulates keypresses)",
            {"text": "Text to type"},
            self._keyboard_type,
            category="system",
        )
        self.add_tool(
            "keyboard_shortcut",
            "Press a keyboard shortcut (e.g., 'command c' for copy, 'command v' for paste)",
            {"keys": "Shortcut keys, e.g., 'command c', 'control shift t'"},
            self._keyboard_shortcut,
            category="system",
        )
        self.add_tool(
            "keyboard_press",
            "Press a single key (e.g., 'return', 'tab', 'escape', 'space')",
            {"key": "Key name: return, tab, escape, space, delete, etc."},
            self._keyboard_press,
            category="system",
        )

    def register_commands(self):
        self.add_command("open", "Open an app or file: /open <app_name or path>", self._handle_open)
        self.add_command("notify", "Send notification: /notify <title> | <message>", self._handle_notify)
        self.add_command("clipboard", "Clipboard operations: /clipboard get|set <text>", self._handle_clipboard)

    # ────────────────────────────────────────────
    # Desktop Tools
    # ────────────────────────────────────────────

    async def _macos_open_app(self, params):
        app_name = params.get("app_name", "").strip()
        if not app_name:
            return "Error: app_name is required"

        script = f'tell application "{app_name}" to activate'
        result = await self._run_osascript(script)
        if "execution error" in result.lower():
            return f"Failed to open {app_name}: {result}"
        return f"✅ Opened {app_name}"

    async def _macos_open_file(self, params):
        path = params.get("path", "").strip()
        if not path:
            return "Error: path is required"

        # Expand ~ and resolve path
        full_path = os.path.expanduser(path)
        if not os.path.exists(full_path):
            return f"File not found: {path}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "open",
                full_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return f"Failed to open: {stderr.decode().strip()}"
            return f"✅ Opened {path}"
        except Exception as e:
            return f"Error: {e}"

    async def _macos_notify(self, params):
        title = params.get("title", "Nexus").strip()
        message = params.get("message", "").strip()
        if not message:
            return "Error: message is required"

        # Escape quotes for AppleScript
        title = title.replace('"', '\\"')
        message = message.replace('"', '\\"')

        script = f'display notification "{message}" with title "{title}"'
        await self._run_osascript(script)
        return f"✅ Notification sent: {title}"

    async def _macos_clipboard_get(self, params):
        try:
            proc = await asyncio.create_subprocess_exec(
                "pbpaste",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return f"Error reading clipboard: {stderr.decode()}"
            content = stdout.decode()
            if not content:
                return "(clipboard is empty)"
            return f"Clipboard contents:\n```\n{content}\n```"
        except Exception as e:
            return f"Error: {e}"

    async def _macos_clipboard_set(self, params):
        text = params.get("text", "")
        try:
            proc = await asyncio.create_subprocess_exec(
                "pbcopy",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(input=text.encode()), timeout=5)
            if proc.returncode != 0:
                return "Error setting clipboard"
            return f"✅ Copied {len(text)} characters to clipboard"
        except Exception as e:
            return f"Error: {e}"

    async def _macos_window_list(self, params):
        # Use osascript to get window list from System Events
        script = '''
        tell application "System Events"
            set windowList to {}
            repeat with proc in application processes
                if visible of proc is true then
                    try
                        set procName to name of proc
                        repeat with win in windows of proc
                            set windowTitle to name of win
                            set end of windowList to procName & " — " & windowTitle
                        end repeat
                    end try
                end if
            end repeat
            return windowList
        end tell
        '''
        result = await self._run_osascript(script)
        if not result or result == "":
            return "No visible windows found"

        # Parse the AppleScript list format
        windows = result.replace("{", "").replace("}", "").split(", ")
        lines = ["📱 **Visible Windows:**\n"]
        for i, window in enumerate(windows, 1):
            if window.strip():
                lines.append(f"{i}. {window.strip()}")
        return "\n".join(lines) if len(lines) > 1 else "No visible windows found"

    async def _macos_screenshot(self, params):
        path = params.get("path", "").strip()
        if not path:
            path = os.path.expanduser("~/Desktop/screenshot.png")
        else:
            path = os.path.expanduser(path)

        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture",
                "-x",  # No sound
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return "Failed to take screenshot"

            size = os.path.getsize(path)
            return f"✅ Screenshot saved to {path} ({size} bytes)"
        except Exception as e:
            return f"Error: {e}"

    # ────────────────────────────────────────────
    # File Tools
    # ────────────────────────────────────────────

    async def _file_move(self, params):
        src = os.path.expanduser(params.get("src", "").strip())
        dest = os.path.expanduser(params.get("dest", "").strip())

        if not src or not dest:
            return "Error: both src and dest are required"
        if not os.path.exists(src):
            return f"Source not found: {src}"

        try:
            shutil.move(src, dest)
            return f"✅ Moved {src} → {dest}"
        except Exception as e:
            return f"Error moving file: {e}"

    async def _file_copy(self, params):
        src = os.path.expanduser(params.get("src", "").strip())
        dest = os.path.expanduser(params.get("dest", "").strip())

        if not src or not dest:
            return "Error: both src and dest are required"
        if not os.path.exists(src):
            return f"Source not found: {src}"

        try:
            if os.path.isdir(src):
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
            return f"✅ Copied {src} → {dest}"
        except Exception as e:
            return f"Error copying file: {e}"

    async def _file_delete(self, params):
        path = os.path.expanduser(params.get("path", "").strip())
        confirm = params.get("confirm", "").lower().strip()

        if not path:
            return "Error: path is required"
        if confirm != "yes":
            return "⚠️ Deletion requires confirmation. Set confirm='yes' to proceed."
        if not os.path.exists(path):
            return f"Path not found: {path}"

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return f"✅ Deleted {path}"
        except Exception as e:
            return f"Error deleting: {e}"

    async def _file_find(self, params):
        pattern = params.get("pattern", "").strip()
        path = params.get("path", ".").strip()

        if not pattern:
            return "Error: pattern is required"

        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return f"Path not found: {path}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "find",
                path,
                "-name",
                pattern,
                "-type",
                "f",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode != 0:
                return f"Error: {stderr.decode()}"

            results = stdout.decode().strip()
            if not results:
                return f"No files found matching '{pattern}' in {path}"

            lines = results.split("\n")
            if len(lines) > 50:
                return f"Found {len(lines)} files (showing first 50):\n" + "\n".join(lines[:50])
            return f"Found {len(lines)} file(s):\n{results}"
        except Exception as e:
            return f"Error: {e}"

    async def _file_info(self, params):
        path = os.path.expanduser(params.get("path", "").strip())

        if not path:
            return "Error: path is required"
        if not os.path.exists(path):
            return f"Path not found: {path}"

        try:
            stat = os.stat(path)
            import time

            info_lines = [
                f"📄 **{os.path.basename(path)}**",
                f"Path: {path}",
                f"Type: {'Directory' if os.path.isdir(path) else 'File'}",
                f"Size: {stat.st_size:,} bytes ({stat.st_size / 1024:.1f} KB)",
                f"Permissions: {oct(stat.st_mode)[-3:]}",
                f"Modified: {time.ctime(stat.st_mtime)}",
                f"Created: {time.ctime(stat.st_ctime)}",
            ]

            if os.path.isdir(path):
                num_items = len(os.listdir(path))
                info_lines.append(f"Contents: {num_items} items")

            return "\n".join(info_lines)
        except Exception as e:
            return f"Error: {e}"

    # ────────────────────────────────────────────
    # Keyboard Tools
    # ────────────────────────────────────────────

    async def _keyboard_type(self, params):
        text = params.get("text", "")
        if not text:
            return "Error: text is required"

        # Escape special characters for AppleScript
        text = text.replace("\\", "\\\\").replace('"', '\\"')

        script = f'''
        tell application "System Events"
            keystroke "{text}"
        end tell
        '''
        await self._run_osascript(script)
        return f"✅ Typed {len(text)} characters"

    async def _keyboard_shortcut(self, params):
        keys = params.get("keys", "").strip().lower()
        if not keys:
            return "Error: keys is required (e.g., 'command c', 'control shift t')"

        # Parse modifier keys and main key
        parts = keys.split()
        if len(parts) < 2:
            return "Error: shortcut must have at least one modifier and one key (e.g., 'command c')"

        modifiers = []
        main_key = parts[-1]

        for mod in parts[:-1]:
            if mod in ["command", "cmd"]:
                modifiers.append("command down")
            elif mod in ["control", "ctrl"]:
                modifiers.append("control down")
            elif mod in ["option", "alt"]:
                modifiers.append("option down")
            elif mod in ["shift"]:
                modifiers.append("shift down")
            else:
                return f"Unknown modifier: {mod}. Use: command, control, option, shift"

        modifier_str = ", ".join(modifiers)

        script = f'''
        tell application "System Events"
            keystroke "{main_key}" using {{{modifier_str}}}
        end tell
        '''
        await self._run_osascript(script)
        return f"✅ Pressed {keys}"

    async def _keyboard_press(self, params):
        key = params.get("key", "").strip().lower()
        if not key:
            return "Error: key is required"

        # Map common key names to AppleScript key codes
        key_map = {
            "return": "return",
            "enter": "return",
            "tab": "tab",
            "space": "space",
            "delete": "delete",
            "escape": "escape",
            "esc": "escape",
            "backspace": "delete",
            "up": "up arrow",
            "down": "down arrow",
            "left": "left arrow",
            "right": "right arrow",
        }

        as_key = key_map.get(key, key)

        script = f'''
        tell application "System Events"
            key code {{
                if "{as_key}" is "return" then 36
                else if "{as_key}" is "tab" then 48
                else if "{as_key}" is "space" then 49
                else if "{as_key}" is "delete" then 51
                else if "{as_key}" is "escape" then 53
                else 0
            }}
        end tell
        '''

        # For simple keys, use keystroke instead
        if as_key not in ["return", "tab", "space", "delete", "escape"]:
            script = f'''
            tell application "System Events"
                keystroke "{as_key}"
            end tell
            '''

        await self._run_osascript(script)
        return f"✅ Pressed {key}"

    # ────────────────────────────────────────────
    # Command Handlers
    # ────────────────────────────────────────────

    async def _handle_open(self, args):
        args = args.strip()
        if not args:
            return "Usage: /open <app_name or file_path>"

        # Check if it's a file path
        if os.path.exists(os.path.expanduser(args)):
            return await self._macos_open_file({"path": args})
        else:
            return await self._macos_open_app({"app_name": args})

    async def _handle_notify(self, args):
        if "|" in args:
            parts = args.split("|", 1)
            title = parts[0].strip()
            message = parts[1].strip()
        else:
            title = "Nexus"
            message = args.strip()

        return await self._macos_notify({"title": title, "message": message})

    async def _handle_clipboard(self, args):
        parts = args.strip().split(None, 1)
        if not parts:
            return "Usage: /clipboard get  OR  /clipboard set <text>"

        action = parts[0].lower()
        if action == "get":
            return await self._macos_clipboard_get({})
        elif action == "set":
            if len(parts) < 2:
                return "Error: /clipboard set requires text"
            return await self._macos_clipboard_set({"text": parts[1]})
        else:
            return f"Unknown action: {action}. Use 'get' or 'set'"

    # ────────────────────────────────────────────
    # Helper
    # ────────────────────────────────────────────

    async def _run_osascript(self, script: str) -> str:
        """Execute AppleScript and return output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=MAX_EXEC_TIME)

            result = stdout.decode().strip()
            if stderr:
                err = stderr.decode().strip()
                if err:
                    return f"Error: {err}"

            return result
        except asyncio.TimeoutError:
            return f"⏱ Timed out after {MAX_EXEC_TIME}s"
        except Exception as e:
            return f"Error: {e}"
