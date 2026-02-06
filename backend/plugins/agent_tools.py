"""Agent Tools plugin — gives the AI autonomous capabilities.

This is the brain's hands. It lets the AI:
- Execute code (Python/bash) in a sandbox
- Read and write files on the local filesystem
- Install skill packs from GitHub repos
- Introspect its own codebase
- Manage its own skills and config

The AI uses these via tool_call tags in its responses. The WebSocket
handler's tool loop detects tool calls, executes them, feeds results
back, and lets the AI iterate.
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.agent")

# Safety: limit code execution
MAX_EXEC_TIME = 30  # seconds
MAX_OUTPUT_SIZE = 10_000  # chars
NEXUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AgentToolsPlugin(NexusPlugin):
    name = "agent"
    description = "Autonomous agent tools — code execution, file ops, GitHub skill install, self-modification"
    version = "1.0.0"

    def __init__(self, config, db, router):
        super().__init__(config, db, router)
        self.nexus_root = NEXUS_ROOT
        self.workspace = os.path.join(NEXUS_ROOT, "data", "workspace")
        self.skills_dir = os.path.join(NEXUS_ROOT, "data", "skills")
        self.skill_packs_dir = os.path.join(NEXUS_ROOT, "skill-packs")

    async def setup(self):
        os.makedirs(self.workspace, exist_ok=True)
        logger.info(f"  Workspace: {self.workspace}")
        logger.info(f"  Nexus root: {self.nexus_root}")
        return True

    def register_tools(self):
        # ── Code Execution ──
        self.add_tool(
            "run_python",
            "Execute Python code and return stdout/stderr. Use for computation, data processing, testing, or any task that needs code.",
            {"code": "Python code to execute"},
            self._run_python,
        )
        self.add_tool(
            "run_bash",
            "Execute a bash command and return output. Use for system tasks, file management, package installs, git operations.",
            {"command": "Bash command to run"},
            self._run_bash,
        )

        # ── File Operations ──
        self.add_tool(
            "read_file",
            "Read a file's contents. Paths relative to Nexus root or absolute.",
            {"path": "File path to read"},
            self._read_file,
        )
        self.add_tool(
            "write_file",
            "Create or overwrite a file. Use for creating skills, config, scripts, or any output.",
            {"path": "File path (relative to Nexus root or absolute)", "content": "File content to write"},
            self._write_file,
        )
        self.add_tool(
            "list_dir",
            "List directory contents with file sizes. Use to explore project structure.",
            {"path": "Directory path (default: Nexus root)"},
            self._list_dir,
        )

        # ── Self-Introspection ──
        self.add_tool(
            "nexus_structure",
            "Get an overview of the Nexus codebase — directory tree, key files, architecture. Use when you need to understand or modify the system.",
            {},
            self._nexus_structure,
        )

        # ── Skill Management ──
        self.add_tool(
            "install_skill_from_github",
            "Clone a skill pack from a GitHub repo and install it. The repo should have a skill.yaml in its root or in a subdirectory.",
            {
                "repo": "GitHub repo in owner/name format",
                "path": "Optional: subdirectory within repo containing skill.yaml",
            },
            self._install_from_github,
        )
        self.add_tool(
            "create_skill",
            "Create a new skill pack by writing skill.yaml, knowledge.md, and optionally actions.py. Use when you've learned something and want to persist it.",
            {
                "id": "Skill ID (lowercase, hyphens ok)",
                "yaml_content": "Content for skill.yaml",
                "knowledge_content": "Content for knowledge.md",
                "actions_content": "Optional: content for actions.py",
            },
            self._create_skill_pack,
        )
        self.add_tool(
            "list_skills",
            "List all installed skills with their status.",
            {},
            self._list_skills,
        )

    def register_commands(self):
        self.add_command("exec", "Execute code: /exec python <code> or /exec bash <command>", self._handle_exec)
        self.add_command(
            "install-skill", "Install skill from GitHub: /install-skill owner/repo [path]", self._handle_install
        )

    # ────────────────────────────────────────────
    # Code Execution
    # ────────────────────────────────────────────

    async def _run_python(self, params):
        code = params.get("code", "")
        if not code.strip():
            return "Error: No code provided."

        # Write to temp file and execute
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", dir=self.workspace, delete=False) as f:
            f.write(code)
            script_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=MAX_EXEC_TIME)
            except asyncio.TimeoutError:
                proc.kill()
                return f"⏱ Execution timed out after {MAX_EXEC_TIME}s"

            output = ""
            if stdout:
                out = stdout.decode(errors="replace")[:MAX_OUTPUT_SIZE]
                output += f"stdout:\n{out}\n"
            if stderr:
                err = stderr.decode(errors="replace")[:MAX_OUTPUT_SIZE]
                output += f"stderr:\n{err}\n"
            if proc.returncode != 0:
                output += f"\nExit code: {proc.returncode}"

            return output.strip() or "(no output)"
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def _run_bash(self, params):
        command = params.get("command", "")
        if not command.strip():
            return "Error: No command provided."

        # Block dangerous commands
        dangerous = ["rm -rf /", "mkfs", "> /dev/sd", "dd if=", ":(){ :|:&", "chmod -R 777 /"]
        cmd_lower = command.lower().strip()
        for d in dangerous:
            if d in cmd_lower:
                return "⚠ Blocked: potentially dangerous command."

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=MAX_EXEC_TIME)
            except asyncio.TimeoutError:
                proc.kill()
                return f"⏱ Timed out after {MAX_EXEC_TIME}s"

            output = ""
            if stdout:
                output += stdout.decode(errors="replace")[:MAX_OUTPUT_SIZE]
            if stderr:
                err = stderr.decode(errors="replace")[:MAX_OUTPUT_SIZE]
                if err.strip():
                    output += f"\nstderr: {err}"
            if proc.returncode != 0:
                output += f"\nExit code: {proc.returncode}"

            return output.strip() or "(no output)"
        except Exception as e:
            return f"Error: {e}"

    # ────────────────────────────────────────────
    # File Operations
    # ────────────────────────────────────────────

    def _resolve_path(self, path_str: str) -> str:
        """Resolve a path relative to Nexus root. Prevent escaping."""
        p = path_str.strip()
        if not os.path.isabs(p):
            p = os.path.join(self.nexus_root, p)
        p = os.path.realpath(p)
        # Allow access to nexus root and workspace
        if not (p.startswith(os.path.realpath(self.nexus_root)) or p.startswith(os.path.realpath(self.workspace))):
            raise PermissionError("Access denied: path is outside Nexus root")
        return p

    async def _read_file(self, params):
        path = params.get("path", "")
        try:
            full = self._resolve_path(path)
            if not os.path.exists(full):
                return f"File not found: {path}"
            if os.path.isdir(full):
                return await self._list_dir({"path": path})
            size = os.path.getsize(full)
            if size > 500_000:
                return f"File too large ({size / 1024:.0f}KB). Use run_bash with head/tail."
            with open(full, errors="replace") as f:
                content = f.read()
            return f"**{path}** ({size} bytes):\n```\n{content}\n```"
        except PermissionError as e:
            return str(e)
        except Exception as e:
            return f"Error reading {path}: {e}"

    async def _write_file(self, params):
        path = params.get("path", "")
        content = params.get("content", "")
        try:
            full = self._resolve_path(path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(content)
            return f"✅ Wrote {len(content)} bytes to {path}"
        except PermissionError as e:
            return str(e)
        except Exception as e:
            return f"Error writing {path}: {e}"

    async def _list_dir(self, params):
        path = params.get("path", "")
        try:
            full = self._resolve_path(path) if path else self.nexus_root
            if not os.path.isdir(full):
                return f"Not a directory: {path}"

            lines = [f"📁 **{os.path.relpath(full, self.nexus_root) or '.'}/**\n"]
            entries = sorted(os.listdir(full))
            for entry in entries:
                if entry.startswith(".") or entry == "__pycache__" or entry == "node_modules":
                    continue
                fp = os.path.join(full, entry)
                if os.path.isdir(fp):
                    count = len([f for f in os.listdir(fp) if not f.startswith(".")])
                    lines.append(f"  📁 {entry}/ ({count} items)")
                else:
                    size = os.path.getsize(fp)
                    if size > 1024 * 1024:
                        sz = f"{size / 1024 / 1024:.1f}MB"
                    elif size > 1024:
                        sz = f"{size / 1024:.0f}KB"
                    else:
                        sz = f"{size}B"
                    lines.append(f"  📄 {entry} ({sz})")
            return "\n".join(lines)
        except PermissionError as e:
            return str(e)
        except Exception as e:
            return f"Error listing {path}: {e}"

    # ────────────────────────────────────────────
    # Self-Introspection
    # ────────────────────────────────────────────

    async def _nexus_structure(self, params):
        """Return a comprehensive overview of the Nexus codebase."""
        lines = ["# Nexus Agent — Codebase Structure\n"]
        lines.append(f"Root: `{self.nexus_root}`\n")

        # Walk top-level
        for d in sorted(os.listdir(self.nexus_root)):
            if d.startswith(".") or d in ("__pycache__", "node_modules", ".git"):
                continue
            full = os.path.join(self.nexus_root, d)
            if os.path.isdir(full):
                lines.append(f"\n## {d}/")
                for f in sorted(os.listdir(full)):
                    if f.startswith(".") or f == "__pycache__":
                        continue
                    fp = os.path.join(full, f)
                    if os.path.isdir(fp):
                        lines.append(f"  📁 {f}/")
                        for sf in sorted(os.listdir(fp)):
                            if sf.startswith(".") or sf == "__pycache__":
                                continue
                            sfp = os.path.join(fp, sf)
                            sz = os.path.getsize(sfp) if os.path.isfile(sfp) else 0
                            icon = "📁" if os.path.isdir(sfp) else "📄"
                            lines.append(f"    {icon} {sf} ({sz}B)" if os.path.isfile(sfp) else f"    {icon} {sf}/")
                    else:
                        sz = os.path.getsize(fp)
                        lines.append(f"  📄 {f} ({sz}B)")
            else:
                sz = os.path.getsize(full)
                lines.append(f"📄 {d} ({sz}B)")

        lines.append("\n## Key Architecture")
        lines.append("- `backend/main.py` — FastAPI app, WebSocket chat, slash commands, system prompt")
        lines.append("- `backend/skills/engine.py` — Skills v2 engine (knowledge + integration skills)")
        lines.append("- `backend/plugins/` — Plugin system (GitHub, Browser, Agent Tools)")
        lines.append("- `backend/models/router.py` — Model routing (Claude/Ollama)")
        lines.append("- `backend/config_manager.py` — Database-backed settings with encryption")
        lines.append("- `backend/admin.py` — Admin panel API endpoints")
        lines.append("- `frontend/index.html` — Main chat UI")
        lines.append("- `frontend/admin.html` — Admin panel UI")
        lines.append("- `data/skills/` — Installed skill packs (skill.yaml + knowledge.md + actions.py)")
        lines.append("- `skill-packs/` — Available but not-yet-installed skill templates")
        lines.append("- `data/nexus.db` — SQLite database (conversations, skills, settings)")

        lines.append("\n## How Skills Work")
        lines.append("Each skill is a folder in `data/skills/<id>/` with:")
        lines.append("- `skill.yaml` — manifest with triggers, config schema, action definitions")
        lines.append("- `knowledge.md` — context injected into prompts when skill matches")
        lines.append("- `actions.py` — optional executable functions the AI can call")

        lines.append("\n## How to Add a New Skill")
        lines.append("1. Create folder in `data/skills/<id>/`")
        lines.append("2. Write `skill.yaml` with id, name, triggers, config, actions")
        lines.append("3. Write `knowledge.md` with context for the AI")
        lines.append("4. Optionally write `actions.py` with handler functions")
        lines.append("5. Call skills_engine.load_all() or restart server")

        return "\n".join(lines)

    # ────────────────────────────────────────────
    # Skill Management
    # ────────────────────────────────────────────

    async def _install_from_github(self, params):
        """Clone a GitHub repo and install skill pack(s) from it."""
        repo = params.get("repo", "").strip()
        subpath = params.get("path", "").strip()

        if not repo or "/" not in repo:
            return "Error: repo must be in owner/name format"

        # Check if git is available
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except FileNotFoundError:
            return "Error: git not installed. Run: apt-get install git"

        # Check if GitHub token is available for private repos
        token = ""
        if self.config:
            token = getattr(self.config, "github_token", "") or self.config.get("GITHUB_TOKEN", "")

        clone_url = f"https://github.com/{repo}.git"
        if token:
            clone_url = f"https://{token}@github.com/{repo}.git"

        # Clone to temp dir
        tmp_dir = tempfile.mkdtemp(prefix="nexus-skill-")
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                "1",
                clone_url,
                tmp_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                err = stderr.decode(errors="replace")
                return f"Git clone failed: {err[:500]}"

            # Find skill.yaml
            search_dir = os.path.join(tmp_dir, subpath) if subpath else tmp_dir
            if not os.path.isdir(search_dir):
                return f"Path not found in repo: {subpath}"

            manifest_path = os.path.join(search_dir, "skill.yaml")
            if os.path.exists(manifest_path):
                # Single skill pack at this path
                return await self._install_pack_from_dir(search_dir, repo)

            # Search subdirectories for skill packs
            installed = []
            for item in os.listdir(search_dir):
                item_path = os.path.join(search_dir, item)
                if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "skill.yaml")):
                    result = await self._install_pack_from_dir(item_path, repo)
                    installed.append(result)

            if installed:
                return f"Installed {len(installed)} skill(s) from {repo}:\n" + "\n".join(installed)
            return f"No skill.yaml found in {repo}" + (f"/{subpath}" if subpath else "")

        except asyncio.TimeoutError:
            return "Git clone timed out after 60s"
        except Exception as e:
            return f"Install error: {e}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def _install_pack_from_dir(self, source_dir: str, source_repo: str) -> str:
        """Install a single skill pack from a directory."""
        try:
            import yaml

            with open(os.path.join(source_dir, "skill.yaml")) as f:
                manifest = yaml.safe_load(f) or {}

            skill_id = manifest.get("id", os.path.basename(source_dir))
            dest = os.path.join(self.skills_dir, skill_id)

            # Copy to skills dir
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(source_dir, dest)

            # Remove .git if present
            git_dir = os.path.join(dest, ".git")
            if os.path.exists(git_dir):
                shutil.rmtree(git_dir)

            return f"✅ **{manifest.get('name', skill_id)}** installed from {source_repo}"
        except Exception as e:
            return f"❌ Failed to install from {source_dir}: {e}"

    async def _create_skill_pack(self, params):
        """Create a skill pack from scratch."""
        skill_id = params.get("id", "").strip()
        yaml_content = params.get("yaml_content", "")
        knowledge_content = params.get("knowledge_content", "")
        actions_content = params.get("actions_content", "")

        if not skill_id:
            return "Error: skill id required"
        if not yaml_content:
            return "Error: yaml_content required (the skill.yaml content)"

        skill_dir = os.path.join(self.skills_dir, skill_id)
        os.makedirs(skill_dir, exist_ok=True)

        try:
            with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
                f.write(yaml_content)
            if knowledge_content:
                with open(os.path.join(skill_dir, "knowledge.md"), "w") as f:
                    f.write(knowledge_content)
            if actions_content:
                with open(os.path.join(skill_dir, "actions.py"), "w") as f:
                    f.write(actions_content)

            return f"✅ Skill pack '{skill_id}' created at {skill_dir}\nRestart or reload skills to activate."
        except Exception as e:
            return f"Error creating skill: {e}"

    async def _list_skills(self, params):
        """List all installed skills."""
        if not os.path.isdir(self.skills_dir):
            return "No skills directory found."

        lines = ["📚 **Installed Skills:**\n"]
        for item in sorted(os.listdir(self.skills_dir)):
            item_path = os.path.join(self.skills_dir, item)
            if not os.path.isdir(item_path):
                continue
            manifest_path = os.path.join(item_path, "skill.yaml")
            if os.path.exists(manifest_path):
                try:
                    import yaml

                    with open(manifest_path) as f:
                        m = yaml.safe_load(f) or {}
                    stype = m.get("type", "knowledge")
                    icon = "🔌" if stype == "integration" else "📖"
                    has_actions = "⚡" if os.path.exists(os.path.join(item_path, "actions.py")) else ""
                    lines.append(f"{icon} **{m.get('name', item)}** ({stype}) {has_actions}")
                    lines.append(f"   {m.get('description', '')}")
                except Exception:
                    lines.append(f"❓ {item}/ (invalid manifest)")
            else:
                lines.append(f"📄 {item}/ (legacy — no skill.yaml)")

        # Also list available packs not yet installed
        if os.path.isdir(self.skill_packs_dir):
            available = []
            for item in sorted(os.listdir(self.skill_packs_dir)):
                if item.startswith("_"):
                    continue
                if os.path.exists(os.path.join(self.skill_packs_dir, item, "skill.yaml")):
                    installed = os.path.exists(os.path.join(self.skills_dir, item))
                    if not installed:
                        available.append(item)
            if available:
                lines.append(f"\n📦 **Available to install:** {', '.join(available)}")

        return "\n".join(lines) if len(lines) > 1 else "No skills installed."

    # ────────────────────────────────────────────
    # Slash Command Handlers
    # ────────────────────────────────────────────

    async def _handle_exec(self, args):
        """Handle /exec command."""
        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            return "Usage: `/exec python <code>` or `/exec bash <command>`"

        lang, code = parts[0].lower(), parts[1]
        if lang == "python":
            return await self._run_python({"code": code})
        elif lang == "bash":
            return await self._run_bash({"command": code})
        return f"Unknown language: {lang}. Use `python` or `bash`."

    async def _handle_install(self, args):
        """Handle /install-skill command."""
        parts = args.strip().split(None, 1)
        if not parts:
            return "Usage: `/install-skill owner/repo [subdirectory]`"

        repo = parts[0]
        subpath = parts[1] if len(parts) > 1 else ""
        return await self._install_from_github({"repo": repo, "path": subpath})
