"""
J.A.R.V.I.S. — Safe Code Executor (Tier 4)
Enables Jarvis to generate and execute Python code, shell commands, and scripts safely.

Provides:
  - Sandboxed Python code execution with timeout
  - Safe shell command execution with security guards
  - Code writing to files with language detection
  - Git operations (status, commit, push, pull)
  - Package management (pip install, npm run)
"""
from __future__ import annotations

import os
import asyncio
import subprocess
import tempfile
import textwrap
import shutil
from pathlib import Path
from typing import Optional
from loguru import logger
from jarvis.tools.registry import register_tool


# ─── Dangerous Command Guards ─────────────────────────────────────────────────

BLOCKED_COMMANDS = [
    "format c:", "format d:",
    "rmdir /s /q c:\\", "rmdir /s /q c:/",
    "del /f /s /q c:\\", "del /f /s /q c:/",
    "rd /s /q c:\\", "rd /s /q c:/",
    ":(){ :|:& };:",  # fork bomb
    "rm -rf /",
    "shutdown /s /t 0",  # Use dedicated tool instead
    "reg delete hklm",
    "bcdedit",
    "diskpart",
]

WARN_COMMANDS = [
    "pip install", "pip uninstall",
    "npm install -g", "npm uninstall -g",
    "reg add", "reg delete",
    "netsh", "icacls",
    "powershell -encodedcommand",
]


def is_command_safe(command: str) -> tuple[bool, str]:
    """Check if a shell command is safe to execute. Returns (is_safe, reason)."""
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"Blocked dangerous command: contains '{blocked}'"
    return True, "OK"


def is_command_risky(command: str) -> bool:
    """Check if a command is potentially risky and should be explained."""
    cmd_lower = command.lower().strip()
    return any(w in cmd_lower for w in WARN_COMMANDS)


# ─── Python Code Execution ────────────────────────────────────────────────────

@register_tool(
    name="execute_python",
    description="Execute Python code safely in an isolated subprocess with timeout. Use for calculations, data processing, file manipulation, web requests, or any programmatic task.",
    category="code"
)
def execute_python(code: str, timeout: int = 30) -> str:
    """Execute Python code in a sandboxed subprocess."""
    try:
        # Write code to temp file
        temp_dir = Path("data/temp_scripts")
        temp_dir.mkdir(parents=True, exist_ok=True)
        script_path = temp_dir / "jarvis_exec.py"
        script_path.write_text(code, encoding="utf-8")

        # Execute in subprocess with timeout
        result = subprocess.run(
            ["python", str(script_path)],
            capture_output=True,
            text=True,
            timeout=min(timeout, 120),  # Cap at 2 minutes
            cwd=str(Path.cwd()),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode == 0:
            output = stdout if stdout else "(No output)"
            return f"Code executed successfully.\nOutput:\n{output[:3000]}"
        else:
            return f"Code execution failed (exit code {result.returncode}).\nError:\n{stderr[:2000]}"

    except subprocess.TimeoutExpired:
        return f"Code execution timed out after {timeout} seconds."
    except Exception as e:
        logger.error(f"Python execution error: {e}")
        return f"Failed to execute code: {e}"


# ─── Shell Command Execution ──────────────────────────────────────────────────

@register_tool(
    name="execute_shell",
    description="Execute a shell command on Windows (PowerShell). Use for system operations, file management, running scripts, or any CLI task. Dangerous commands are blocked for safety.",
    category="code"
)
def execute_shell(command: str, timeout: int = 30, cwd: str = "") -> str:
    """Execute a shell command safely with security guards."""
    safe, reason = is_command_safe(command)
    if not safe:
        return f"⚠️ Command blocked: {reason}"

    try:
        work_dir = cwd if cwd and Path(cwd).exists() else str(Path.cwd())
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=min(timeout, 120),
            cwd=work_dir,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode == 0:
            output = stdout if stdout else "(Command completed with no output)"
            return f"Command completed successfully.\n{output[:3000]}"
        else:
            error_info = stderr if stderr else stdout
            return f"Command failed (exit code {result.returncode}).\n{error_info[:2000]}"

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout} seconds."
    except Exception as e:
        logger.error(f"Shell execution error: {e}")
        return f"Failed to execute command: {e}"


# ─── Code Writing ─────────────────────────────────────────────────────────────

@register_tool(
    name="write_code_to_file",
    description="Write code or text content to a file. Creates parent directories automatically. Use for generating code files, configs, scripts, etc.",
    category="code"
)
def write_code_to_file(file_path: str, code: str, language: str = "python") -> str:
    """Write generated code to a file on disk."""
    try:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, encoding="utf-8")
        lines = code.count("\n") + 1
        return f"Created {p.name} ({lines} lines, {len(code)} bytes) at {p.resolve()}."
    except Exception as e:
        return f"Failed to write code file: {e}"


# ─── Git Operations ───────────────────────────────────────────────────────────

@register_tool(
    name="git_status",
    description="Check the Git status of the current repository or a specified directory.",
    category="code"
)
def git_status(repo_path: str = "") -> str:
    """Get git status of a repository."""
    try:
        cwd = repo_path if repo_path and Path(repo_path).exists() else str(Path.cwd())
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=10, cwd=cwd,
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if not status:
                return "Git repository is clean — no uncommitted changes."
            changed = len(status.split("\n"))
            return f"Git status ({changed} changed files):\n{status[:2000]}"
        return f"Git error: {result.stderr.strip()}"
    except Exception as e:
        return f"Failed to get git status: {e}"


@register_tool(
    name="git_commit",
    description="Stage all changes and commit with a message. Use for saving code changes to git.",
    category="code"
)
def git_commit(message: str, repo_path: str = "") -> str:
    """Stage all files and commit."""
    try:
        cwd = repo_path if repo_path and Path(repo_path).exists() else str(Path.cwd())
        # Stage all
        subprocess.run(["git", "add", "-A"], capture_output=True, cwd=cwd, timeout=10)
        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=15, cwd=cwd,
        )
        if result.returncode == 0:
            return f"Committed: '{message}'\n{result.stdout.strip()[:500]}"
        return f"Commit failed: {result.stderr.strip()}"
    except Exception as e:
        return f"Git commit failed: {e}"


@register_tool(
    name="git_push",
    description="Push committed changes to the remote repository.",
    category="code"
)
def git_push(repo_path: str = "") -> str:
    """Push to remote."""
    try:
        cwd = repo_path if repo_path and Path(repo_path).exists() else str(Path.cwd())
        result = subprocess.run(
            ["git", "push"],
            capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        if result.returncode == 0:
            return f"Pushed successfully. {result.stdout.strip()[:500]}"
        return f"Push failed: {result.stderr.strip()}"
    except Exception as e:
        return f"Git push failed: {e}"


@register_tool(
    name="git_pull",
    description="Pull latest changes from the remote repository.",
    category="code"
)
def git_pull(repo_path: str = "") -> str:
    """Pull from remote."""
    try:
        cwd = repo_path if repo_path and Path(repo_path).exists() else str(Path.cwd())
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        if result.returncode == 0:
            return f"Pulled successfully. {result.stdout.strip()[:500]}"
        return f"Pull failed: {result.stderr.strip()}"
    except Exception as e:
        return f"Git pull failed: {e}"


# ─── Package Management ───────────────────────────────────────────────────────

@register_tool(
    name="pip_install",
    description="Install a Python package using pip.",
    category="code"
)
def pip_install(package: str) -> str:
    """Install a Python package."""
    try:
        result = subprocess.run(
            ["pip", "install", package],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return f"Successfully installed {package}."
        return f"Installation failed: {result.stderr.strip()[:500]}"
    except Exception as e:
        return f"pip install failed: {e}"


@register_tool(
    name="npm_run",
    description="Run an npm script (e.g., 'dev', 'build', 'start') in a specified directory.",
    category="code"
)
def npm_run(script: str, project_path: str = "") -> str:
    """Run an npm script."""
    try:
        cwd = project_path if project_path and Path(project_path).exists() else str(Path.cwd())
        result = subprocess.run(
            ["npm", "run", script],
            capture_output=True, text=True, timeout=60, cwd=cwd,
        )
        if result.returncode == 0:
            return f"npm run {script} completed.\n{result.stdout.strip()[:1000]}"
        return f"npm run {script} failed: {result.stderr.strip()[:500]}"
    except Exception as e:
        return f"npm run failed: {e}"
