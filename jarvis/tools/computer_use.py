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


# When the Windows session is locked, the compositor (DWM) blocks desktop capture,
# so screenshots come back black. Detect it and return a clear message instead.
_LOCKED_MSG = (
    "I can't see the screen right now because your workstation is locked. "
    "Please unlock it and ask me again."
)


def _is_session_locked() -> bool:
    """Best-effort check for a locked/secure Windows desktop. Never raises."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # DESKTOP_READOBJECTS (0x0001); the input desktop can't be opened when locked.
        hdesk = user32.OpenInputDesktop(0, False, 0x0001)
        if not hdesk:
            return True
        name_buf = ctypes.create_unicode_buffer(256)
        needed = ctypes.c_ulong(0)
        # UOI_NAME = 2: the secure desktop is named "Winlogon", the normal one "Default".
        user32.GetUserObjectInformationW(hdesk, 2, name_buf, ctypes.sizeof(name_buf), ctypes.byref(needed))
        user32.CloseDesktop(hdesk)
        return name_buf.value.strip().lower() != "default"
    except Exception:
        return False  # on any uncertainty, don't block capture


# ─── Screen Capture ───────────────────────────────────────────────────────────

@register_tool(
    name="screenshot",
    description="Capture the entire screen or a specific region. Returns the saved image path for visual analysis.",
    category="computer_use"
)
def screenshot(region: str = "") -> str:
    """Capture screen. region format: 'x,y,width,height' or empty for full screen."""
    if _is_session_locked():
        return _LOCKED_MSG
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
    if _is_session_locked():
        return _LOCKED_MSG
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


# ─── Visual Grounding (set-of-marks) ──────────────────────────────────────────
# Detect on-screen text elements with bounding boxes so the agent can click by
# description or by a numbered label instead of guessing pixel coordinates.

_LAST_ELEMENTS: list[dict] = []
_EASYOCR_READER = None


def _scale(img) -> tuple[float, float]:
    """Factor to convert image pixels → screen coordinates (handles DPI scaling)."""
    try:
        import pyautogui
        sw, sh = pyautogui.size()
        iw, ih = img.size
        if iw and ih:
            return sw / iw, sh / ih
    except Exception:
        pass
    return 1.0, 1.0


def _mk(text: str, x, y, w, h, sx: float, sy: float) -> dict:
    """Build an element record with its center already in screen coordinates."""
    cx = (x + w / 2) * sx
    cy = (y + h / 2) * sy
    return {"text": text.strip(), "cx": int(cx), "cy": int(cy),
            "w": int(w * sx), "h": int(h * sy)}


def _detect_text_elements(img) -> list[dict]:
    """Detect text elements with boxes. Tries pytesseract → easyocr → winocr."""
    sx, sy = _scale(img)
    elements: list[dict] = []

    # 1. pytesseract (fast, deterministic boxes)
    try:
        import pytesseract
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        for i in range(len(data["text"])):
            t = (data["text"][i] or "").strip()
            raw_conf = str(data["conf"][i])
            conf = int(raw_conf) if raw_conf.lstrip("-").isdigit() else -1
            if t and conf > 40:
                elements.append(_mk(t, data["left"][i], data["top"][i],
                                    data["width"][i], data["height"][i], sx, sy))
        if elements:
            return elements
    except Exception:
        pass

    # 2. easyocr (slower, robust; reader cached)
    try:
        import numpy as np
        global _EASYOCR_READER
        if _EASYOCR_READER is None:
            import easyocr
            _EASYOCR_READER = easyocr.Reader(["en"], gpu=False)
        for bbox, text, conf in _EASYOCR_READER.readtext(np.array(img)):
            if text.strip() and conf > 0.4:
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                x, y = min(xs), min(ys)
                elements.append(_mk(text, x, y, max(xs) - x, max(ys) - y, sx, sy))
        if elements:
            return elements
    except Exception:
        pass

    return elements


def _best_match(query: str, els: list[dict]) -> dict | None:
    """Pick the element whose visible text best matches the query."""
    import difflib
    q = (query or "").strip().lower()
    if not q or not els:
        return None
    best, best_score = None, 0.0
    q_tokens = set(q.split())
    for e in els:
        t = e["text"].lower()
        if not t:
            continue
        if q == t:
            score = 1.0
        elif q in t:
            score = 0.9
        elif t in q:
            score = 0.8
        else:
            score = difflib.SequenceMatcher(None, q, t).ratio()
            t_tokens = set(t.split())
            if q_tokens & t_tokens:
                score = max(score, len(q_tokens & t_tokens) / len(q_tokens | t_tokens))
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 0.5 else None


def _capture_and_detect() -> tuple[object, list[dict]]:
    import pyautogui
    img = pyautogui.screenshot()
    return img, _detect_text_elements(img)


@register_tool(
    name="click_text",
    description="Click the on-screen element (button, link, menu item, tab, field label) whose visible text best matches the given text. Far more reliable than guessing coordinates — prefer this for clicking UI.",
    category="computer_use",
)
def click_text(text: str, double: bool = False, right: bool = False) -> str:
    """Find the element whose text matches and click its center."""
    if _is_session_locked():
        return _LOCKED_MSG
    try:
        import pyautogui
        _img, els = _capture_and_detect()
        if not els:
            return "I couldn't read any clickable text on the screen."
        match = _best_match(text, els)
        if not match:
            return f"I couldn't find anything matching '{text}' on the screen."
        cx, cy = match["cx"], match["cy"]
        if right:
            pyautogui.rightClick(cx, cy)
        elif double:
            pyautogui.doubleClick(cx, cy)
        else:
            pyautogui.click(cx, cy)
        return f"Clicked '{match['text']}' at ({cx}, {cy})."
    except Exception as e:
        logger.error(f"click_text error: {e}")
        return f"Failed to click '{text}': {e}"


@register_tool(
    name="label_screen_elements",
    description="Detect clickable text elements on screen and return them as a NUMBERED list (set-of-marks). Use when you need to choose precisely among options, then click one with click_labeled_element.",
    category="computer_use",
)
def label_screen_elements(max_elements: int = 40) -> str:
    """Produce a numbered list of on-screen text elements for precise selection."""
    if _is_session_locked():
        return _LOCKED_MSG
    try:
        img, els = _capture_and_detect()
        els = els[:max_elements]
        _LAST_ELEMENTS.clear()
        _LAST_ELEMENTS.extend(els)
        _save_annotated(img, els)
        if not els:
            return "No text elements were detected on the screen."
        lines = [f"[{i}] {e['text']}" for i, e in enumerate(els)]
        return "Screen elements (use click_labeled_element with the number):\n" + "\n".join(lines)
    except Exception as e:
        logger.error(f"label_screen_elements error: {e}")
        return f"Failed to label screen elements: {e}"


@register_tool(
    name="click_labeled_element",
    description="Click an element by its number from the most recent label_screen_elements call.",
    category="computer_use",
)
def click_labeled_element(index: int, double: bool = False, right: bool = False) -> str:
    """Click a previously labeled element by its index."""
    try:
        import pyautogui
        if index < 0 or index >= len(_LAST_ELEMENTS):
            return "That element number isn't available. Call label_screen_elements first."
        e = _LAST_ELEMENTS[index]
        cx, cy = e["cx"], e["cy"]
        if right:
            pyautogui.rightClick(cx, cy)
        elif double:
            pyautogui.doubleClick(cx, cy)
        else:
            pyautogui.click(cx, cy)
        return f"Clicked [{index}] '{e['text']}' at ({cx}, {cy})."
    except Exception as e:
        return f"Failed to click element {index}: {e}"


def _save_annotated(img, els: list[dict]) -> None:
    """Save a screenshot with numbered marks for debugging/vision (best-effort)."""
    try:
        from PIL import ImageDraw
        sx, sy = _scale(img)
        annotated = img.copy()
        draw = ImageDraw.Draw(annotated)
        for i, e in enumerate(els):
            # Convert the stored screen-space center back to image space for drawing.
            ix = e["cx"] / sx if sx else e["cx"]
            iy = e["cy"] / sy if sy else e["cy"]
            draw.rectangle([ix - 4, iy - 8, ix + 14, iy + 8], outline="red", width=1)
            draw.text((ix - 3, iy - 7), str(i), fill="red")
        save_dir = Path("data/screenshots")
        save_dir.mkdir(parents=True, exist_ok=True)
        annotated.save(str(save_dir / "labeled.png"))
    except Exception:
        pass


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
