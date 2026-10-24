"""
J.A.R.V.I.S. — Virtual Hands & GUI Automation Tools
Enables Jarvis to:
  - Click, move, and drag the mouse
  - Type text into active fields
  - Press system keyboard shortcuts (Alt+Tab, Ctrl+C, Win+D, etc.)
  - Focus, maximize, and minimize specific windows
"""
from __future__ import annotations

import pyautogui
from loguru import logger
from jarvis.tools.registry import register_tool

pyautogui.FAILSAFE = False


@register_tool(name="mouse_click", description="Click the mouse cursor (button='left'|'right'|'middle', clicks=1|2).", category="gui")
def mouse_click(button: str = "left", clicks: int = 1) -> str:
    """Click the mouse cursor."""
    try:
        pyautogui.click(button=button, clicks=clicks)
        action = "Double-clicked" if clicks == 2 else f"Clicked {button} button"
        return f"{action} at current position."
    except Exception as e:
        return f"Mouse click failed: {e}"


@register_tool(name="mouse_move", description="Move mouse cursor to specific X and Y screen coordinates.", category="gui")
def mouse_move(x: int, y: int) -> str:
    """Move mouse cursor to specific screen coordinates."""
    try:
        pyautogui.moveTo(x, y, duration=0.2)
        return f"Moved cursor to ({x}, {y})."
    except Exception as e:
        return f"Mouse move failed: {e}"


@register_tool(name="keyboard_type", description="Type a string of text into the currently active input field or editor.", category="gui")
def keyboard_type(text: str) -> str:
    """Type a string of text into the currently active input field."""
    try:
        pyautogui.write(text, interval=0.01)
        return f"Typed '{text[:40]}'..."
    except Exception as e:
        return f"Typing failed: {e}"


@register_tool(name="keyboard_hotkey", description="Press a Windows keyboard shortcut (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+d', 'alt+f4').", category="gui")
def keyboard_hotkey(hotkey: str) -> str:
    """Press a Windows keyboard shortcut."""
    try:
        keys = [k.strip().lower() for k in hotkey.split("+")]
        pyautogui.hotkey(*keys)
        return f"Pressed shortcut {hotkey}."
    except Exception as e:
        return f"Shortcut failed: {e}"


@register_tool(name="keyboard_press", description="Press a single special key (e.g. 'enter', 'escape', 'space', 'tab', 'backspace').", category="gui")
def keyboard_press(key: str) -> str:
    """Press a single special key."""
    try:
        pyautogui.press(key.strip().lower())
        return f"Pressed key {key}."
    except Exception as e:
        return f"Key press failed: {e}"


@register_tool(name="focus_window", description="Bring an open window to the front by title keyword (e.g. 'Brave', 'Code', 'Discord').", category="window")
def focus_window(title_keyword: str) -> str:
    """Bring an open window to the front by title keyword."""
    try:
        import win32gui
        import win32con

        target_hwnd = None
        target_title = ""

        def enum_cb(hwnd, _):
            nonlocal target_hwnd, target_title
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title_keyword.lower() in title.lower():
                    target_hwnd = hwnd
                    target_title = title

        win32gui.EnumWindows(enum_cb, None)
        if target_hwnd:
            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target_hwnd)
            return f"Switched focus to '{target_title}'."
        return f"No open window matching '{title_keyword}' found."
    except Exception as e:
        return f"Failed to focus window: {e}"
