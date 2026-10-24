"""
J.A.R.V.I.S. — Universal Shell & Windows System Control
Provides unrestricted access to Windows shell, clipboard, and system utilities:
  - Run arbitrary PowerShell commands
  - Read and write the Windows clipboard
  - Query network status and active IP address
"""
from __future__ import annotations

import subprocess
from loguru import logger
from jarvis.tools.registry import register_tool


@register_tool(
    name="run_powershell",
    description="Execute an arbitrary PowerShell command on Windows and return its output.",
    category="shell"
)
def run_powershell(command: str) -> str:
    """Execute an arbitrary PowerShell command."""
    logger.info(f"Running PowerShell command: {command}")
    # Guard against accidental catastrophic recursive deletion
    lower_cmd = command.lower()
    if "rmdir /s /q c:\\" in lower_cmd or "format c:" in lower_cmd or "del /f /s /q c:\\windows" in lower_cmd:
        return "Refused: Potentially destructive system command."

    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=12.0
        )
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        if res.returncode == 0:
            if not stdout:
                return "Command executed successfully with no output."
            # Limit output to 1500 chars to avoid overwhelming speech/LLM context
            if len(stdout) > 1500:
                stdout = stdout[:1500] + "\n...[Output truncated]"
            return stdout
        else:
            return f"Command failed (exit code {res.returncode}): {stderr or stdout}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 12 seconds."
    except Exception as e:
        return f"PowerShell execution error: {e}"


@register_tool(
    name="get_clipboard",
    description="Get the current text copied to the Windows clipboard.",
    category="shell"
)
def get_clipboard() -> str:
    """Get the current text copied to the Windows clipboard."""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                return f"Clipboard content:\n{data[:500]}"
            return "Clipboard contains non-text data or is empty."
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        return f"Failed to read clipboard: {e}"


@register_tool(
    name="set_clipboard",
    description="Set or copy text to the Windows clipboard.",
    category="shell"
)
def set_clipboard(text: str) -> str:
    """Set or copy text to the Windows clipboard."""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            return f"Copied '{text[:40]}' to clipboard."
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        return f"Failed to set clipboard: {e}"


@register_tool(
    name="get_network_info",
    description="Get current network IP configuration and ping connectivity.",
    category="system"
)
def get_network_info() -> str:
    """Get current network IP configuration and ping connectivity."""
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127*' -and $_.IPAddress -notlike '169*'} | Select-Object -ExpandProperty IPAddress"],
            capture_output=True,
            text=True,
            timeout=5.0
        )
        ips = [ip.strip() for ip in res.stdout.strip().splitlines() if ip.strip()]
        ip_str = ", ".join(ips) if ips else "No active IPv4 address found"
        return f"Local IP Address: {ip_str}."
    except Exception as e:
        return f"Failed to get network info: {e}"
