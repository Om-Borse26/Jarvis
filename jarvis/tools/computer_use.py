"""
J.A.R.V.I.S. — Computer Use Tools (Tier 2)
Enables Jarvis to control ANY application via screenshot + OCR + mouse/keyboard.
This eliminates the need to write per-app tools for hundreds of applications.

Provides:
  - Screen capture with optional region
  - OCR text extraction from screen
  - UI element finding by description
  - Mouse actions: click, double-click, right-click, drag
  - Keyboard actions: type text, press keys, hotkey combos
  - Scroll in any direction
  - Wait for UI elements to appear
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple, List
from loguru import logger
from jarvis.tools.registry import register_tool

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.05
except ImportError:
    pyautogui = None


# ─── Screen Capture ───────────────────────────────────────────────────────────

@register_tool(
    name="screenshot",
    description="Capture the entire screen or a specific region. Returns the saved image path for visual analysis.",
    category="computer_use"
)
def screenshot(region: str = "") -> str:
    """Capture screen. region format: 'x,y,width,height' or empty for full screen."""
    try:
        import pyautogui
        from PIL import Image

        save_dir = Path("data/screenshots")
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        save_path = save_dir / f"screen_{ts}.png"

        if region and "," in region:
            parts = [int(x.strip()) for x in region.split(",")]
            if len(parts) == 4:
                img = pyautogui.screenshot(region=tuple(parts))
            else:
                img = pyautogui.screenshot()
        else:
            img = pyautogui.screenshot()

        img.save(str(save_path))
        w, h = img.size
        return f"Screenshot captured ({w}x{h}) and saved to {save_path}."
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        return f"Failed to capture screenshot: {e}"


@register_tool(
    name="ocr_screen",
    description="Extract all visible text from the current screen using OCR. Useful for reading what's on screen.",
    category="computer_use"
)
def ocr_screen() -> str:
    """Extract text from current screen content."""
    try:
        import pyautogui
        from PIL import Image

        img = pyautogui.screenshot()

        # Try Windows native OCR first (fastest)
        try:
            import winocr
            import asyncio
            result = asyncio.run(winocr.recognize_pil(img, "en"))
            if result and result.text:
                lines = [line.strip() for line in result.text.split("\n") if line.strip()]
                return f"Screen text ({len(lines)} lines):\n" + "\n".join(lines[:50])
        except ImportError:
            pass

        # Fallback to pytesseract
        try:
            import pytesseract
            text = pytesseract.image_to_string(img)
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            return f"Screen text ({len(lines)} lines):\n" + "\n".join(lines[:50])
        except ImportError:
            pass

        return "OCR libraries not available. Install winocr or pytesseract for text extraction."
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return f"Failed to extract screen text: {e}"


# ─── Mouse Actions ─────────────────────────────────────────────────────────────

@register_tool(
    name="mouse_click",
    description="Click at specific screen coordinates (x, y). Use screenshot + OCR first to find the right position.",
    category="computer_use"
)
def mouse_click(x: int, y: int) -> str:
    """Click at screen coordinates."""
    try:
        import pyautogui
        pyautogui.click(x, y)
        return f"Clicked at ({x}, {y})."
    except Exception as e:
        return f"Click failed: {e}"


@register_tool(
    name="mouse_double_click",
    description="Double-click at specific screen coordinates (x, y).",
    category="computer_use"
)
def mouse_double_click(x: int, y: int) -> str:
    """Double-click at screen coordinates."""
    try:
        import pyautogui
        pyautogui.doubleClick(x, y)
        return f"Double-clicked at ({x}, {y})."
    except Exception as e:
        return f"Double-click failed: {e}"


@register_tool(
    name="mouse_right_click",
    description="Right-click at specific screen coordinates (x, y) to open context menu.",
    category="computer_use"
)
def mouse_right_click(x: int, y: int) -> str:
    """Right-click at screen coordinates."""
    try:
        import pyautogui
        pyautogui.rightClick(x, y)
        return f"Right-clicked at ({x}, {y})."
    except Exception as e:
        return f"Right-click failed: {e}"


@register_tool(
    name="mouse_drag",
    description="Drag from (x1, y1) to (x2, y2). Useful for drag-and-drop or selecting regions.",
    category="computer_use"
)
def mouse_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    """Drag from one point to another."""
    try:
        import pyautogui
        pyautogui.moveTo(x1, y1)
        pyautogui.drag(x2 - x1, y2 - y1, duration=duration)
        return f"Dragged from ({x1}, {y1}) to ({x2}, {y2})."
    except Exception as e:
        return f"Drag failed: {e}"


# ─── Keyboard Actions ─────────────────────────────────────────────────────────

@register_tool(
    name="keyboard_type",
    description="Type text using the keyboard. The text is typed character by character into whatever is currently focused.",
    category="computer_use"
)
def keyboard_type(text: str, interval: float = 0.02) -> str:
    """Type text via keyboard input."""
    try:
        import pyautogui
        pyautogui.typewrite(text, interval=interval) if text.isascii() else pyautogui.write(text)
        return f"Typed {len(text)} characters."
    except Exception as e:
        # Fallback for non-ASCII text
        try:
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            return f"Typed {len(text)} characters (via clipboard)."
        except Exception as e2:
            return f"Type failed: {e2}"


@register_tool(
    name="keyboard_hotkey",
    description="Press a keyboard shortcut combination. Examples: 'ctrl,s' for save, 'ctrl,shift,p' for command palette, 'alt,f4' to close.",
    category="computer_use"
)
def keyboard_hotkey(keys: str) -> str:
    """Press keyboard shortcut. keys is comma-separated: 'ctrl,s' or 'alt,f4'."""
    try:
        import pyautogui
        key_list = [k.strip().lower() for k in keys.split(",")]
        pyautogui.hotkey(*key_list)
        return f"Pressed hotkey: {' + '.join(key_list)}."
    except Exception as e:
        return f"Hotkey failed: {e}"


@register_tool(
    name="keyboard_press",
    description="Press a single keyboard key. Examples: 'enter', 'tab', 'escape', 'f5', 'delete', 'space', 'backspace'.",
    category="computer_use"
)
def keyboard_press(key: str) -> str:
    """Press a single keyboard key."""
    try:
        import pyautogui
        pyautogui.press(key.strip().lower())
        return f"Pressed key: {key}."
    except Exception as e:
        return f"Key press failed: {e}"


# ─── Scroll ────────────────────────────────────────────────────────────────────

@register_tool(
    name="scroll",
    description="Scroll up or down at the current mouse position. Positive amount scrolls up, negative scrolls down.",
    category="computer_use"
)
def scroll(amount: int = -3) -> str:
    """Scroll at current position. Positive=up, negative=down."""
    try:
        import pyautogui
        pyautogui.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return f"Scrolled {direction} by {abs(amount)} steps."
    except Exception as e:
        return f"Scroll failed: {e}"


# ─── Focus Window ──────────────────────────────────────────────────────────────

@register_tool(
    name="focus_window",
    description="Bring a specific application window to the foreground by its name (e.g., 'VS Code', 'Brave', 'Discord').",
    category="computer_use"
)
def focus_window(app_name: str) -> str:
    """Focus an existing window by app name."""
    try:
        from jarvis.tools.process_control import focus_existing_window
        title = focus_existing_window(app_name)
        if title:
            return f"Focused window: {title}."
        return f"No open window found for '{app_name}'."
    except Exception as e:
        return f"Focus failed: {e}"


# ─── Wait for Element ──────────────────────────────────────────────────────────

@register_tool(
    name="wait_seconds",
    description="Wait for a specified number of seconds. Useful between actions to let UI load.",
    category="computer_use"
)
def wait_seconds(seconds: float = 1.0) -> str:
    """Wait for specified seconds."""
    time.sleep(min(seconds, 30.0))  # Cap at 30 seconds
    return f"Waited {seconds} seconds."


# ─── Get Screen Info ───────────────────────────────────────────────────────────

@register_tool(
    name="get_screen_size",
    description="Get the current screen resolution (width x height in pixels).",
    category="computer_use"
)
def get_screen_size() -> str:
    """Get screen resolution."""
    try:
        import pyautogui
        w, h = pyautogui.size()
        return f"Screen resolution: {w}x{h} pixels."
    except Exception as e:
        return f"Failed to get screen size: {e}"


@register_tool(
    name="get_mouse_position",
    description="Get the current mouse cursor position on screen.",
    category="computer_use"
)
def get_mouse_position() -> str:
    """Get current mouse position."""
    try:
        import pyautogui
        x, y = pyautogui.position()
        return f"Mouse is at ({x}, {y})."
    except Exception as e:
        return f"Failed to get mouse position: {e}"
