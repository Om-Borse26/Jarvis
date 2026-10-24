"""
J.A.R.V.I.S. — Web & Browser Automation Tools
Provides voice-accessible tools to:
  - Search YouTube for videos and open results
  - Search Google / Brave for any query
  - Open websites and web applications
"""
from __future__ import annotations

import subprocess
import urllib.parse
from loguru import logger
from jarvis.tools.registry import register_tool


def navigate_or_open_browser(url: str, force_new: bool = False, new_tab: bool = False) -> bool:
    """
    If a browser window is already open (Brave, Chrome, Edge), navigates the active tab to the URL
    via Ctrl+L, clipboard paste, and Enter. If new_tab is True, opens a new tab in the same window (Ctrl+T).
    Prevents spawning endless duplicate browser windows/tabs for every video or search query!
    """
    try:
        import ctypes
        import win32gui
        import win32con
        import pyautogui
        import pyperclip
        import time

        pyautogui.FAILSAFE = False

        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0100 | 0x0040)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        target_hwnd = None
        def enum_cb(hwnd, _):
            nonlocal target_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if any(b in title for b in ["brave", "chrome", "edge", "youtube", "firefox", "opera"]):
                    target_hwnd = hwnd
                    return False
            return True

        win32gui.EnumWindows(enum_cb, None)
        if target_hwnd:
            cur_fg = user32.GetForegroundWindow()
            cur_thread = user32.GetWindowThreadProcessId(cur_fg, None)
            my_thread = ctypes.windll.kernel32.GetCurrentThreadId()

            try:
                user32.AttachThreadInput(cur_thread, my_thread, True)
                user32.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                user32.SetForegroundWindow(target_hwnd)
                user32.AttachThreadInput(cur_thread, my_thread, False)
            except Exception:
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(target_hwnd)

            time.sleep(0.2)

            if new_tab:
                # Open a new tab in the same active browser window
                pyautogui.hotkey("ctrl", "t")
                time.sleep(0.1)
            else:
                # Reuse the currently active tab
                pyautogui.hotkey("ctrl", "l")
                time.sleep(0.08)

            pyperclip.copy(url)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.08)
            pyautogui.press("enter")
            logger.info(f"🌐 Navigated browser window to {url} (new_tab={new_tab})")
            return True
    except Exception as e:
        logger.debug(f"Browser tab reuse notice: {e}")
    return False


def _focus_active_browser() -> bool:
    """Bring the most recent Brave/Chrome/Edge window to the foreground. Returns True on success."""
    try:
        import ctypes
        import win32gui
        import win32con
        import time

        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0100 | 0x0040)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        target = None
        def cb(hwnd, _):
            nonlocal target
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd).lower()
                if any(b in t for b in ["brave", "chrome", "edge", "firefox", "opera"]):
                    target = hwnd
                    return False
            return True
        win32gui.EnumWindows(cb, None)
        if not target:
            return False

        cur_fg = user32.GetForegroundWindow()
        cur_thread = user32.GetWindowThreadProcessId(cur_fg, None)
        my_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        try:
            user32.AttachThreadInput(cur_thread, my_thread, True)
            user32.ShowWindow(target, win32con.SW_RESTORE)
            user32.SetForegroundWindow(target)
            user32.AttachThreadInput(cur_thread, my_thread, False)
        except Exception:
            win32gui.ShowWindow(target, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target)
        time.sleep(0.15)
        return True
    except Exception as e:
        logger.debug(f"Focus browser notice: {e}")
        return False


@register_tool(
    name="close_browser_tab",
    description="Close the currently active browser tab (like Ctrl+W) in the user's browser. Use when asked to close or remove the current tab or the tab that was just opened.",
    category="web"
)
def close_browser_tab() -> str:
    """Close the active tab in the focused browser window."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        if not _focus_active_browser():
            return "I couldn't find an open browser window to close a tab in, Sir."
        pyautogui.hotkey("ctrl", "w")
        return "Closed the active browser tab, Sir."
    except Exception as e:
        logger.error(f"close_browser_tab failed: {e}")
        return f"I couldn't close the tab: {e}"


def _browser_action(combos: list, confirm: str) -> str:
    """Focus the active browser, send one or more key combos, return a confirmation."""
    try:
        import pyautogui
        import time
        pyautogui.FAILSAFE = False
        if not _focus_active_browser():
            return "I couldn't find an open browser window, Sir."
        for combo in combos:
            pyautogui.hotkey(*combo)
            time.sleep(0.05)
        return confirm
    except Exception as e:
        logger.error(f"browser action failed: {e}")
        return f"I couldn't do that in the browser: {e}"


@register_tool(
    name="browser_new_tab",
    description="Open a NEW browser tab, optionally navigating to a URL. Use only when the user explicitly wants a new tab.",
    category="web"
)
def browser_new_tab(url: str = "") -> str:
    """Open a new tab in the user's browser, optionally at a URL."""
    try:
        import pyautogui
        import pyperclip
        import time
        pyautogui.FAILSAFE = False
        if not _focus_active_browser():
            return "I couldn't find an open browser window, Sir."
        pyautogui.hotkey("ctrl", "t")
        time.sleep(0.15)
        u = url.strip()
        if u:
            if not u.startswith(("http://", "https://")):
                u = "https://" + u
            pyperclip.copy(u)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.05)
            pyautogui.press("enter")
            return f"Opened a new tab at {u}, Sir."
        return "Opened a new browser tab, Sir."
    except Exception as e:
        logger.error(f"browser_new_tab failed: {e}")
        return f"I couldn't open a new tab: {e}"


@register_tool(
    name="reopen_closed_tab",
    description="Reopen the most recently closed browser tab (Ctrl+Shift+T).",
    category="web"
)
def reopen_closed_tab() -> str:
    return _browser_action([("ctrl", "shift", "t")], "Reopened the last closed tab, Sir.")


@register_tool(
    name="switch_browser_tab",
    description="Switch to the next or previous browser tab. direction: 'next' or 'previous'.",
    category="web"
)
def switch_browser_tab(direction: str = "next") -> str:
    if direction.lower().startswith("prev"):
        return _browser_action([("ctrl", "shift", "tab")], "Switched to the previous tab, Sir.")
    return _browser_action([("ctrl", "tab")], "Switched to the next tab, Sir.")


@register_tool(
    name="browser_back",
    description="Go back to the previous page in the browser.",
    category="web"
)
def browser_back() -> str:
    return _browser_action([("alt", "left")], "Went back, Sir.")


@register_tool(
    name="browser_forward",
    description="Go forward to the next page in the browser.",
    category="web"
)
def browser_forward() -> str:
    return _browser_action([("alt", "right")], "Went forward, Sir.")


@register_tool(
    name="browser_refresh",
    description="Reload/refresh the current browser page.",
    category="web"
)
def browser_refresh() -> str:
    return _browser_action([("ctrl", "r")], "Refreshed the page, Sir.")


@register_tool(
    name="browser_zoom",
    description="Zoom the current browser page. level: 'in', 'out', or 'reset'.",
    category="web"
)
def browser_zoom(level: str = "in") -> str:
    lv = level.lower()
    if lv.startswith("out"):
        return _browser_action([("ctrl", "-")], "Zoomed out, Sir.")
    if lv.startswith("reset") or lv == "0":
        return _browser_action([("ctrl", "0")], "Reset the zoom, Sir.")
    return _browser_action([("ctrl", "=")], "Zoomed in, Sir.")


@register_tool(
    name="close_browser_window",
    description="Close the entire current browser window (all its tabs).",
    category="web"
)
def close_browser_window() -> str:
    return _browser_action([("ctrl", "shift", "w")], "Closed the browser window, Sir.")


@register_tool(
    name="browser_scroll",
    description="Scroll the current browser page. direction: 'up' or 'down'. amount is the number of scroll steps.",
    category="web"
)
def browser_scroll(direction: str = "down", amount: int = 4) -> str:
    try:
        import pyautogui
        import time
        pyautogui.FAILSAFE = False
        if not _focus_active_browser():
            return "I couldn't find an open browser window, Sir."
        time.sleep(0.1)
        step = 400 * max(1, int(amount))
        pyautogui.scroll(step if direction.lower().startswith("up") else -step)
        return f"Scrolled {direction.lower()}, Sir."
    except Exception as e:
        logger.error(f"browser_scroll failed: {e}")
        return f"I couldn't scroll: {e}"


@register_tool(
    name="find_on_page",
    description="Find text on the current browser page (Ctrl+F) and jump to the first match.",
    category="web"
)
def find_on_page(query: str) -> str:
    try:
        import pyautogui
        import pyperclip
        import time
        pyautogui.FAILSAFE = False
        if not _focus_active_browser():
            return "I couldn't find an open browser window, Sir."
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.15)
        pyperclip.copy(query)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)
        pyautogui.press("enter")
        return f"Searching the page for '{query}', Sir."
    except Exception as e:
        logger.error(f"find_on_page failed: {e}")
        return f"I couldn't search the page: {e}"


@register_tool(
    name="search_youtube",
    description="Search YouTube for videos and open results in browser. Reuses existing browser tab unless force_new or new_tab is requested.",
    category="web"
)
def search_youtube(query: str, force_new: bool = False, new_tab: bool = False) -> str:
    """Search YouTube for videos and open the results."""
    clean_q = query.strip().strip("'").strip('"')
    encoded = urllib.parse.quote_plus(clean_q)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        if not navigate_or_open_browser(url, force_new=force_new, new_tab=new_tab):
            subprocess.Popen(f'start "" "{url}"', shell=True)
        return f"Opening YouTube search for '{clean_q}', Sir."
    except Exception as e:
        logger.error(f"Failed to open YouTube search: {e}")
        return f"Failed to search YouTube: {e}"


@register_tool(
    name="search_web",
    description="Search Google or the web for any query and open results in browser. Reuses existing browser tab unless force_new or new_tab is requested.",
    category="web"
)
def search_web(query: str, force_new: bool = False, new_tab: bool = False) -> str:
    """Search the web and open the results."""
    clean_q = query.strip().strip("'").strip('"')
    encoded = urllib.parse.quote_plus(clean_q)
    url = f"https://www.google.com/search?q={encoded}"
    try:
        if not navigate_or_open_browser(url, force_new=force_new, new_tab=new_tab):
            subprocess.Popen(f'start "" "{url}"', shell=True)
        return f"Searching web for '{clean_q}', Sir."
    except Exception as e:
        logger.error(f"Failed to search web: {e}")
        return f"Failed to search web: {e}"


@register_tool(
    name="open_website",
    description="Open any website or URL in the default browser. Reuses existing browser tab unless force_new or new_tab is requested.",
    category="web"
)
def open_website(url: str, force_new: bool = False, new_tab: bool = False) -> str:
    """Open a website in the default browser."""
    target = url.strip().strip("'").strip('"')
    if not target.startswith(("http://", "https://")):
        target = f"https://{target}"
    try:
        if not navigate_or_open_browser(target, force_new=force_new, new_tab=new_tab):
            subprocess.Popen(f'start "" "{target}"', shell=True)
        return f"Opening {target} in browser, Sir."
    except Exception as e:
        logger.error(f"Failed to open website: {e}")
        return f"Failed to open website: {e}"


@register_tool(
    name="click_active_video",
    description="Click or play the first or specified video in the active YouTube browser window.",
    category="web"
)
def click_active_video(index: int = 1) -> str:
    """Click on the video thumbnail in YouTube search results to begin playback."""
    try:
        import pyautogui
        import time
        import win32gui
        import win32con

        pyautogui.FAILSAFE = False

        # 1. Bring active browser to the foreground
        target_hwnd = None
        def enum_cb(hwnd, _):
            nonlocal target_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if any(k in title for k in ["youtube", "chrome", "brave", "edge"]):
                    target_hwnd = hwnd
        try:
            win32gui.EnumWindows(enum_cb, None)
            if target_hwnd:
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(target_hwnd)
                time.sleep(0.3)
        except Exception:
            pass

        sw, sh = pyautogui.size()
        # On YouTube search results:
        # If channel card exists (e.g. search for 'dream channel'), the 1st video is at ~35% width, 65% height
        # If normal search list, the 1st video is at ~35% width, 45% height
        click_x = int(sw * 0.35)
        if index == 1:
            click_y = int(sh * 0.65)
        elif index == 2:
            click_y = int(sh * 0.82)
        else:
            click_y = int(sh * 0.50)

        pyautogui.click(click_x, click_y)
        time.sleep(0.2)
        # Also send play key 'k' or space in case focused
        pyautogui.press("k")
        return f"Selecting and playing video #{index} on your screen, Sir."
    except Exception as e:
        logger.error(f"Error clicking active video: {e}")
        return f"Failed to click active video: {e}"


@register_tool(
    name="play_youtube_video",
    description="Directly find and play a specific video (e.g. 'Dream most watched video', 'Minecraft Speedrunner').",
    category="web"
)
def play_youtube_video(query: str) -> str:
    """Search YouTube for a specific video and play it directly in browser."""
    clean_q = query.strip().strip("'").strip('"')
    try:
        import yt_dlp
        ydl_opts = {"quiet": True, "extract_flat": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch1:{clean_q}", download=False)
            if res and "entries" in res and res["entries"]:
                entry = res["entries"][0]
                title = entry.get("title", clean_q)
                url = entry.get("url")
                if not url or not url.startswith("http"):
                    vid_id = entry.get("id")
                    url = f"https://www.youtube.com/watch?v={vid_id}"
                if not navigate_or_open_browser(url):
                    subprocess.Popen(f'start "" "{url}"', shell=True)
                return f"Playing '{title}' on YouTube, Sir."
    except Exception as e:
        logger.debug(f"yt-dlp direct search fallback: {e}")

    # Fallback to search query
    encoded = urllib.parse.quote_plus(clean_q)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        if not navigate_or_open_browser(url):
            subprocess.Popen(f'start "" "{url}"', shell=True)
        return f"Opening '{clean_q}' on YouTube, Sir."
    except Exception as e:
        return f"Failed to play YouTube video: {e}"


