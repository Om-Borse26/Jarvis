"""
J.A.R.V.I.S. — File System & Explorer Control Tools
Provides voice-accessible tools to:
  - Search files across drives and user directories
  - Read file contents (code, logs, documents)
  - Write text notes and files
  - List folder directories
  - Open folders or files directly in Windows Explorer
"""
from __future__ import annotations

import os
import re
import json
import urllib.parse
import subprocess
from pathlib import Path
from typing import Optional
from loguru import logger
from jarvis.tools.registry import register_tool


def get_active_vscode_workspace() -> Optional[Path]:
    """
    Detect the active root workspace folder currently opened in Visual Studio Code.
    Only returns a workspace if a VS Code window is actually running on the user's desktop!
    """
    try:
        import ctypes
        import win32gui

        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0100 | 0x0040)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        # 1. Check if any VS Code window is open and get its title
        open_titles = []
        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if "visual studio code" in title.lower() and "antigravity" not in title.lower():
                    open_titles.append(title)
            return True
        win32gui.EnumWindows(cb, None)

        # If VS Code is not open at all, there is no active workspace!
        if not open_titles:
            return None

        # 2. Check workspaceStorage for folder matching active window title
        ws_dir = Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "workspaceStorage"
        if not ws_dir.exists():
            return None

        entries = []
        for p in ws_dir.iterdir():
            f = p / "workspace.json"
            if f.exists():
                try:
                    entries.append((f.stat().st_mtime, f))
                except Exception:
                    pass
        if not entries:
            return None

        entries.sort(key=lambda x: x[0], reverse=True)
        for _, f in entries[:15]:
            try:
                data = json.loads(f.read_text("utf-8"))
                folder_uri = data.get("folder")
                if folder_uri and folder_uri.startswith("file:///"):
                    raw = urllib.parse.unquote(folder_uri[8:])
                    p = Path(raw)
                    if p.exists() and p.is_dir() and p.name != "test_dummy_dir":
                        # Check if this folder's name appears in any of the open VS Code window titles
                        for t in open_titles:
                            if p.name.lower() in t.lower():
                                return p
            except Exception:
                pass

        # Fallback to the most recently modified workspace in storage if VS Code is running
        for _, f in entries[:5]:
            try:
                data = json.loads(f.read_text("utf-8"))
                folder_uri = data.get("folder")
                if folder_uri and folder_uri.startswith("file:///"):
                    raw = urllib.parse.unquote(folder_uri[8:])
                    p = Path(raw)
                    if p.exists() and p.is_dir() and p.name != "test_dummy_dir":
                        return p
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Could not detect VS Code workspace: {e}")
    return None

# Common search paths for rapid lookup
COMMON_DIRS = [
    Path.cwd(),
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path("D:/02_Interests (Up Skilling )/04_Projects"),
]


@register_tool(
    name="search_files",
    description="Search for files or folders matching a query across Desktop, Documents, Downloads, or custom path.",
    category="filesystem"
)
def search_files(query: str, search_path: str = "") -> str:
    """Search for files or folders matching a query with maximum speed."""
    clean_q = query.strip('"').strip("'").lower()
    pattern = clean_q if "*" in clean_q else f"*{clean_q}*"
    results = []
    seen = set()

    roots = [Path(search_path)] if search_path and Path(search_path).exists() else COMMON_DIRS

    for root in roots:
        if not root.exists():
            continue
        try:
            root_depth = len(root.parts)
            for dirpath, dirnames, filenames in os.walk(root):
                curr_p = Path(dirpath)
                if len(curr_p.parts) - root_depth > 4:
                    dirnames.clear()
                    continue
                dirnames[:] = [d for d in dirnames if d not in {".venv", "node_modules", ".git", "__pycache__", "AppData", "$RECYCLE.BIN"}]
                
                for f in filenames:
                    p = curr_p / f
                    if p.match(pattern) or clean_q in f.lower():
                        res_p = str(p.resolve())
                        if res_p not in seen:
                            seen.add(res_p)
                            results.append(str(p))
                            if len(results) >= 8:
                                break
                if len(results) >= 8:
                    break
        except Exception:
            continue
        if len(results) >= 8:
            break

    if not results:
        return f"No files matching '{query}' were found."
    return f"Found {len(results)} matches:\n" + "\n".join(f"- {r}" for r in results)


@register_tool(
    name="read_file",
    description="Read the textual contents of a file (up to 2000 characters).",
    category="filesystem"
)
def read_file(file_path: str, max_chars: int = 2000) -> str:
    """Read the textual contents of a file."""
    p = Path(file_path.strip('"').strip("'"))
    if not p.exists():
        return f"File does not exist: {file_path}"
    if p.is_dir():
        return f"Path is a directory, not a file: {file_path}"

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        preview = text[:max_chars]
        more = f" ... [truncated, total {len(text)} chars]" if len(text) > max_chars else ""
        return f"Content of {p.name}:\n{preview}{more}"
    except Exception as e:
        return f"Failed to read file: {e}"


@register_tool(
    name="create_file",
    description="Create a new file with optional content. If directory is omitted, 'here', or 'in it', automatically resolves to the open VS Code workspace folder or Desktop.",
    category="filesystem"
)
def create_file(
    filename: str = "",
    content: str = "",
    directory: str = "",
    in_vscode: bool = False,
    *args,
    **kwargs,
) -> str:
    """Create a new file, resolving 'here' or 'in it' to the active VS Code workspace or Desktop."""
    raw_name = filename or kwargs.get("name") or kwargs.get("file_path") or kwargs.get("path") or ""
    clean_name = raw_name.strip('"').strip("'").strip()
    if not clean_name:
        return "Please specify a filename, Sir."

    # Normalize speech recognition oddities like "demo dot TXD" or "demo dot TXT" -> "demo.txt"
    clean_name = re.sub(r"\bdot\s+([a-zA-Z0-9]+)\b", r".\1", clean_name, flags=re.I)
    clean_name = re.sub(r"\.txd\b", ".txt", clean_name, flags=re.I)

    p_name = Path(clean_name)
    target_dir: Optional[Path] = None

    clean_dir = directory.strip('"').strip("'").strip().lower()
    if in_vscode or clean_dir in ("", "here", "in it", "current", "this folder", "workspace", "vscode", "vs code", "v.s code"):
        ws = get_active_vscode_workspace()
        if ws and ws.exists():
            target_dir = ws
        else:
            target_dir = Path.cwd()
    elif directory:
        target_dir = Path(directory.strip('"').strip("'"))

    if p_name.is_absolute():
        final_path = p_name
    elif target_dir:
        final_path = target_dir / p_name
    else:
        final_path = Path.cwd() / p_name

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(content, encoding="utf-8")
        loc_desc = f"in active workspace '{final_path.parent.name}'" if target_dir and target_dir.name == final_path.parent.name else f"at {final_path.resolve()}"
        return f"Created file '{final_path.name}' {loc_desc}, Sir."
    except Exception as e:
        logger.error(f"Failed to create file: {e}")
        return f"Failed to create file '{clean_name}': {e}"


@register_tool(
    name="write_file",
    description="Write or append text content to a file on disk.",
    category="filesystem"
)
def write_file(file_path: str, content: str, mode: str = "w") -> str:
    """Write or append text content to a file."""
    clean_p = file_path.strip('"').strip("'")
    p = Path(clean_p)
    if not p.is_absolute():
        ws = get_active_vscode_workspace()
        if ws and ws.exists():
            p = ws / clean_p
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "a" if mode.lower() in ("append", "a") else "w"
        with open(p, write_mode, encoding="utf-8") as f:
            f.write(content)
        verb = "Appended to" if write_mode == "a" else "Created"
        return f"{verb} file at {p.resolve()}."
    except Exception as e:
        return f"Failed to write file: {e}"


@register_tool(
    name="list_directory",
    description="List items inside a folder directory.",
    category="filesystem"
)
def list_directory(folder_path: str = "") -> str:
    """List items inside a folder directory."""
    target = Path(folder_path.strip('"').strip("'")) if folder_path else Path.cwd()
    if not target.exists():
        return f"Directory does not exist: {folder_path}"
    if not target.is_dir():
        return f"Path is not a directory: {folder_path}"

    try:
        items = list(target.iterdir())
        dirs = [f"[DIR]  {i.name}" for i in items if i.is_dir()]
        files = [f"[FILE] {i.name}" for i in items if i.is_file()]
        total = dirs[:15] + files[:20]
        return f"Items in {target}:\n" + "\n".join(total)
    except Exception as e:
        return f"Failed to list directory: {e}"


@register_tool(
    name="open_in_explorer",
    description="Open a file or folder in Windows File Explorer.",
    category="filesystem"
)
def open_in_explorer(path: str = "") -> str:
    """Open a file or folder in Windows File Explorer."""
    target = path.strip('"').strip("'") if path else str(Path.home())
    try:
        subprocess.run(["explorer.exe", target], check=False)
        return f"Opened {target} in File Explorer."
    except Exception as e:
        return f"Failed to open explorer: {e}"


@register_tool(
    name="create_directory",
    description="Create a new folder or directory on disk. Set in_vscode=True if creating inside an active VS Code window or workspace.",
    category="filesystem"
)
def create_directory(path: str, in_vscode: bool = False) -> str:
    """Create a new folder on disk. If in_vscode is True, resolves to the open VS Code workspace or opens it directly in VS Code."""
    clean_p = path.strip('"').strip("'").strip()
    if not clean_p:
        return "Please specify a folder name or path to create."
    try:
        from jarvis.tools.process_control import is_app_open

        if in_vscode:
            import psutil

            # Check if VS Code window is open (does NOT steal focus)
            vscode_open = is_app_open("vscode")
            active_ws = get_active_vscode_workspace()

            if vscode_open and active_ws and active_ws.exists():
                target = active_ws / clean_p
                target.mkdir(parents=True, exist_ok=True)
                return f"Created folder '{clean_p}' inside your active VS Code workspace ({active_ws.name}), Sir."

            # Create on Desktop
            desktop = Path.home() / "Desktop"
            target = desktop / clean_p
            target.mkdir(parents=True, exist_ok=True)
            resolved_path = str(target.resolve())

            # Check if Code.exe is running in background
            is_running = any(
                p.info['name'] and p.info['name'].lower() == "code.exe"
                for p in psutil.process_iter(['name'])
            )

            if vscode_open or is_running:
                # Reuse existing window with -r (background; no forced focus)
                subprocess.Popen(f'code -r "{resolved_path}"', shell=True)
                return f"Created folder '{clean_p}' on your Desktop and opened it in your VS Code window, Sir."
            else:
                # Use -r so we never spawn a duplicate window if one is already open.
                subprocess.Popen(f'code -r "{resolved_path}"', shell=True)
                return f"Created folder '{clean_p}' on your Desktop and launched VS Code with it, Sir."

        target = Path(clean_p)
        target.mkdir(parents=True, exist_ok=True)
        resolved_path = str(target.resolve())
        return f"Created folder '{clean_p}' at {resolved_path}, Sir."
    except Exception as e:
        return f"Failed to create folder '{clean_p}': {e}"


@register_tool(
    name="delete_file",
    description="Delete a file from disk.",
    category="filesystem"
)
def delete_file(file_path: str) -> str:
    """Delete a specified file from disk."""
    clean_p = file_path.strip('"').strip("'").strip()
    try:
        p = Path(clean_p)
        # Check active workspace
        if not p.is_absolute() or not p.exists():
            ws = get_active_vscode_workspace()
            if ws:
                cand = ws / clean_p
                if cand.exists():
                    p = cand
            if not p.exists():
                desk_cand = Path.home() / "Desktop" / clean_p
                if desk_cand.exists():
                    p = desk_cand

        if not p.exists():
            return f"File '{clean_p}' does not exist."
        if p.is_dir():
            return f"'{clean_p}' is a directory, not a file. Use delete_directory instead."
        p.unlink()
        return f"Deleted file '{clean_p}', Sir."
    except Exception as e:
        return f"Failed to delete file '{clean_p}': {e}"


@register_tool(
    name="delete_directory",
    description="Delete a folder/directory and all its contents recursively. Moves to recycle bin when possible for safety.",
    category="filesystem"
)
def delete_directory(path: str, force: bool = False) -> str:
    """Delete a directory and all contents. Tries recycle bin first for safety."""
    import shutil

    clean_p = path.strip('"').strip("'").strip()
    target = Path(clean_p)

    # Check if it's a relative path in the active VS Code workspace
    if not target.is_absolute() or not target.exists():
        ws = get_active_vscode_workspace()
        if ws:
            candidate = ws / clean_p
            if candidate.exists():
                target = candidate
        # Check Desktop
        if not target.exists():
            desktop_cand = Path.home() / "Desktop" / clean_p
            if desktop_cand.exists():
                target = desktop_cand
        # Check COMMON_DIRS
        if not target.exists():
            for cdir in COMMON_DIRS:
                cand = cdir / clean_p
                if cand.exists():
                    target = cand
                    break

    if not target.exists():
        return f"Directory '{clean_p}' does not exist."
    if not target.is_dir():
        return f"'{clean_p}' is a file, not a directory. Use delete_file instead."

    # Safety: block deleting critical system directories
    protected = [
        Path.home(),
        Path("C:/Windows"),
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
    ]
    if any(target.resolve() == p.resolve() for p in protected):
        return f"Cannot delete protected directory '{target}'. This is a safety restriction."

    try:
        # Try to send to recycle bin first (safe delete)
        try:
            from send2trash import send2trash  # type: ignore
            send2trash(str(target.resolve()))
            return f"Moved folder '{target.name}' to recycle bin, Sir."
        except ImportError:
            pass

        # Fallback: permanent delete
        item_count = sum(1 for _ in target.rglob("*"))
        shutil.rmtree(str(target))
        return f"Deleted folder '{target.name}' ({item_count} items removed), Sir."

    except Exception as e:
        return f"Failed to delete directory '{clean_p}': {e}"


@register_tool(
    name="rename_path",
    description="Rename a file or folder to a new name.",
    category="filesystem"
)
def rename_path(old_path: str, new_name: str) -> str:
    """Rename a file or folder."""
    clean_p = old_path.strip('"').strip("'").strip()
    clean_name = new_name.strip('"').strip("'").strip()
    try:
        source = Path(clean_p)
        if not source.exists():
            return f"'{clean_p}' does not exist."
        dest = source.parent / clean_name
        if dest.exists():
            return f"'{clean_name}' already exists in the same directory."
        source.rename(dest)
        return f"Renamed '{source.name}' to '{clean_name}', Sir."
    except Exception as e:
        return f"Failed to rename: {e}"


@register_tool(
    name="move_path",
    description="Move a file or folder to a different location.",
    category="filesystem"
)
def move_path(source: str, destination: str) -> str:
    """Move a file or folder to a new location."""
    import shutil
    clean_src = source.strip('"').strip("'").strip()
    clean_dst = destination.strip('"').strip("'").strip()
    try:
        src = Path(clean_src)
        dst = Path(clean_dst)
        if not src.exists():
            return f"Source '{clean_src}' does not exist."
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved '{src.name}' to '{dst}', Sir."
    except Exception as e:
        return f"Failed to move: {e}"


@register_tool(
    name="copy_path",
    description="Copy a file or folder to a different location.",
    category="filesystem"
)
def copy_path(source: str, destination: str) -> str:
    """Copy a file or folder to a new location."""
    import shutil
    clean_src = source.strip('"').strip("'").strip()
    clean_dst = destination.strip('"').strip("'").strip()
    try:
        src = Path(clean_src)
        dst = Path(clean_dst)
        if not src.exists():
            return f"Source '{clean_src}' does not exist."
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        else:
            shutil.copytree(str(src), str(dst))
        return f"Copied '{src.name}' to '{dst}', Sir."
    except Exception as e:
        return f"Failed to copy: {e}"

