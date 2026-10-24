"""
J.A.R.V.I.S. — WhatsApp Desktop & Web Automation Controller
Provides hands-free voice automation for WhatsApp:
  - Search and open any contact or group chat (e.g. "academic group", "family", "friend")
  - Send messages directly into active or specified chats
  - Read active conversation messages via native Windows OCR
  - Summarize conversations on demand
"""
from __future__ import annotations

import time
import subprocess
import pyautogui
import pyperclip
from loguru import logger
from jarvis.tools.registry import register_tool
from jarvis.tools.screen_tool import screen_tool_instance

# Ensure PyAutoGUI doesn't abort on corner touch
pyautogui.FAILSAFE = False


def _focus_whatsapp() -> bool:
    """Find and focus the WhatsApp window on the desktop."""
    try:
        import win32gui
        import win32con
        target_hwnd = None

        def enum_cb(hwnd, _):
            nonlocal target_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "whatsapp" in title.lower():
                    target_hwnd = hwnd

        win32gui.EnumWindows(enum_cb, None)

        if target_hwnd:
            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target_hwnd)
            time.sleep(0.4)
            return True
    except Exception as e:
        logger.debug(f"Win32 focus notice: {e}")

    # Fallback to launching or activating via protocol
    try:
        subprocess.Popen("cmd /c start whatsapp:", shell=True)
        time.sleep(1.0)
        return True
    except Exception as e:
        logger.error(f"Failed to launch WhatsApp: {e}")
        return False


@register_tool(
    name="send_whatsapp_message",
    description="Send a message to a WhatsApp contact or group chat (e.g. 'academic group', 'Mom', 'Project Team').",
    category="communication"
)
def send_whatsapp_message(chat_name: str, message: str = "") -> str:
    """
    Search for a WhatsApp chat or group and send a message.
    If message is empty, opens the chat ready for the user to dictate.
    """
    clean_chat = chat_name.strip().strip("'").strip('"')
    clean_msg = message.strip().strip("'").strip('"')

    if not clean_chat:
        return "Please specify the contact or group name on WhatsApp, Sir."

    logger.info(f"📱 [WHATSAPP] Navigating to chat '{clean_chat}'...")

    if not _focus_whatsapp():
        return "Could not open or focus WhatsApp on your PC, Sir."

    try:
        # 1. Search for the chat (Ctrl + F in WhatsApp Desktop)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.2)
        # Clear any existing search text
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        time.sleep(0.1)

        # 2. Type target chat name using clipboard for exact unicode matching
        pyperclip.copy(clean_chat)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.6)  # Wait for WhatsApp to filter results

        # 3. Select top search result
        pyautogui.press("enter")
        time.sleep(0.4)

        # 4. If message provided, paste and send
        if clean_msg:
            pyperclip.copy(clean_msg)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
            pyautogui.press("enter")
            return f"Message sent to '{clean_chat}' on WhatsApp: \"{clean_msg}\", Sir."
        else:
            return f"Opened chat '{clean_chat}' on WhatsApp, Sir. What would you like to say?"

    except Exception as e:
        logger.error(f"WhatsApp automation error: {e}")
        return f"Failed to send WhatsApp message: {e}"


@register_tool(
    name="open_whatsapp_chat",
    description="Search and open a specific contact or group conversation in WhatsApp.",
    category="communication"
)
def open_whatsapp_chat(chat_name: str) -> str:
    """Open a specific WhatsApp conversation without sending a message."""
    return send_whatsapp_message(chat_name=chat_name, message="")


@register_tool(
    name="read_whatsapp_messages",
    description="Read visible recent messages from an open or specified WhatsApp conversation using native OCR.",
    category="communication"
)
async def read_whatsapp_messages(chat_name: str = "") -> str:
    """Read visible messages from the active or specified WhatsApp chat."""
    if chat_name:
        send_whatsapp_message(chat_name=chat_name, message="")
        time.sleep(0.5)
    else:
        _focus_whatsapp()

    try:
        # Capture screen and extract visible text using 30ms native OCR
        img_path = screen_tool_instance.capture_screen()
        lines = await screen_tool_instance.extract_screen_text(img_path)

        # Filter out UI chrome elements
        chat_lines = [
            l for l in lines
            if not any(skip in l.lower() for skip in ["whatsapp", "search", "chats", "status", "calls", "type a message", "am", "pm", ":"])
            and len(l) > 3
        ]
        if not chat_lines:
            return "Opened WhatsApp, but could not detect readable messages in this view."
        recent = " | ".join(chat_lines[-10:])
        return f"Recent messages in {chat_name or 'active chat'}: {recent}"
    except Exception as e:
        logger.error(f"Failed to read WhatsApp chat: {e}")
        return f"Could not read messages: {e}"
