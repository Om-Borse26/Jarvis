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
import subprocess
from pathlib import Path
from loguru import logger
from jarvis.tools.registry import register_tool

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
    name="write_file",
    description="Write or append text content to a file on disk.",
    category="filesystem"
)
def write_file(file_path: str, content: str, mode: str = "w") -> str:
    """Write or append text content to a file."""
    p = Path(file_path.strip('"').strip("'"))
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
    description="Create a new folder or directory on disk (e.g. 'new_folder', 'src/components').",
    category="filesystem"
)
def create_directory(path: str) -> str:
    """Create a new folder on disk."""
    clean_p = path.strip('"').strip("'").strip()
    if not clean_p:
        return "Please specify a folder name or path to create."
    try:
        target = Path(clean_p)
        target.mkdir(parents=True, exist_ok=True)
        return f"Created folder '{clean_p}' at {target.resolve()}, Sir."
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
        if not p.exists():
            return f"File '{clean_p}' does not exist."
        if p.is_dir():
            return f"'{clean_p}' is a directory, not a file."
        p.unlink()
        return f"Deleted file '{clean_p}', Sir."
    except Exception as e:
        return f"Failed to delete file '{clean_p}': {e}"

