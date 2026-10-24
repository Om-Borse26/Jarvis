# J.A.R.V.I.S. — Global Rules & Scalable Architecture Plan

## 🎯 Goals
1. **Global Application Lifecycle Rules** — universal behavior enforced before ANY tool executes
2. **Granular Per-App Tool Suites** — dedicated tools for VS Code, browser, YouTube, file manager, etc.
3. **MCP Fallback System** — if no built-in tool matches, try MCP servers automatically
4. **Dynamic Tool Creation** — if no tool/MCP can satisfy, ask user permission to create one
5. **Agentic Loop** — re-prompt until task is confirmed complete

---

## Phase 1: Global Application Lifecycle Rules (Implementing Now)

### The `AppLifecycleManager` (new file: `jarvis/tools/app_lifecycle.py`)

A centralized middleware layer that enforces these universal rules **before** any tool executes:

| # | Rule | Behavior |
|---|------|----------|
| 1 | **Open if closed** | If user asks to do something IN an app that isn't running, open it first, wait for it to be ready, then execute the command |
| 2 | **Reuse existing instances** | If app is already open, focus the existing window. NEVER spawn duplicates unless user explicitly says "new window" / "another instance" |
| 3 | **Close on command** | `kill_process` maps app names → process names intelligently (e.g., "close VS Code" → kills `Code.exe`, not search for "vs code.exe") |
| 4 | **Tab reuse in browsers** | Reuse active browser tab unless user says "new tab" |
| 5 | **Workspace awareness** | For VS Code, know which workspace is open and operate within it |
| 6 | **Sequential compound commands** | "Open VS Code and create a folder" → open first, wait, then create |

### Process Name Resolution Table (built into `kill_process`)

```python
PROCESS_NAME_MAP = {
    "vscode": "Code.exe", "vs code": "Code.exe", "code": "Code.exe",
    "brave": "brave.exe", "chrome": "chrome.exe", "edge": "msedge.exe",
    "discord": "Discord.exe", "spotify": "Spotify.exe",
    "blender": "blender.exe", "notepad": "notepad.exe",
    "terminal": "WindowsTerminal.exe", "explorer": "explorer.exe",
}
```

---

## Phase 2: Per-App Tool Suites

### VS Code Tools (`jarvis/tools/vscode_tools.py`)
- `vscode_create_folder(name)` — create folder in active workspace
- `vscode_delete_folder(name)` — delete folder from active workspace  
- `vscode_create_file(name, content)` — create file in active workspace
- `vscode_delete_file(name)` — delete file from active workspace
- `vscode_open_file(name)` — open a file in the editor
- `vscode_run_command(command_id)` — execute a VS Code command palette action

### Browser Tools (enhance `web_control.py`)
- Already has: `search_youtube`, `search_web`, `open_website`, `click_active_video`, `play_youtube_video`
- Add: `close_browser_tab()`, `browser_back()`, `browser_forward()`, `browser_refresh()`

### File Manager Tools (enhance `file_control.py`)
- Already has: `create_directory`, `delete_file`, `search_files`, `read_file`, `write_file`, `list_directory`
- Add: `delete_directory(path)` — recursively delete a folder
- Add: `rename_file(old_path, new_path)`
- Add: `move_file(source, destination)`
- Add: `copy_file(source, destination)`

---

## Phase 3: MCP Fallback & Dynamic Tool Creation (Next Session)

### Flow:
```
User Request → Fast-Path Router → Built-in Tools → MCP Bridge → Dynamic Tool Creator → User Confirmation
```

---

## Implementation Order (This Session)

1. ✅ Create `app_lifecycle.py` with `AppLifecycleManager`
2. ✅ Fix `kill_process` with proper process name resolution  
3. ✅ Create `vscode_tools.py` with granular VS Code tools
4. ✅ Add `delete_directory` tool to `file_control.py`
5. ✅ Add browser utility tools to `web_control.py`
6. ✅ Update `router.py` fast-path to handle close/delete commands properly
7. ✅ Wire everything into `__init__.py`
