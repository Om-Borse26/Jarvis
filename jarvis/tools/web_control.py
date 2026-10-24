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


@register_tool(
    name="search_youtube",
    description="Search YouTube for videos (e.g. Minecraft videos, songs, tutorials) and open the results in browser.",
    category="web"
)
def search_youtube(query: str) -> str:
    """Search YouTube for videos and open the results."""
    clean_q = query.strip().strip("'").strip('"')
    encoded = urllib.parse.quote_plus(clean_q)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        subprocess.Popen(f'start "" "{url}"', shell=True)
        return f"Opening YouTube search for '{clean_q}', Sir."
    except Exception as e:
        logger.error(f"Failed to open YouTube search: {e}")
        return f"Failed to search YouTube: {e}"


@register_tool(
    name="search_web",
    description="Search Google or the web for any query and open results in browser.",
    category="web"
)
def search_web(query: str) -> str:
    """Search the web and open the results."""
    clean_q = query.strip().strip("'").strip('"')
    encoded = urllib.parse.quote_plus(clean_q)
    url = f"https://www.google.com/search?q={encoded}"
    try:
        subprocess.Popen(f'start "" "{url}"', shell=True)
        return f"Searching web for '{clean_q}', Sir."
    except Exception as e:
        logger.error(f"Failed to search web: {e}")
        return f"Failed to search web: {e}"


@register_tool(
    name="open_website",
    description="Open any website or URL in the default browser (e.g. youtube.com, github.com, reddit.com).",
    category="web"
)
def open_website(url: str) -> str:
    """Open a website in the default browser."""
    target = url.strip().strip("'").strip('"')
    if not target.startswith(("http://", "https://")):
        target = f"https://{target}"
    try:
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
                subprocess.Popen(f'start "" "{url}"', shell=True)
                return f"Playing '{title}' on YouTube, Sir."
    except Exception as e:
        logger.debug(f"yt-dlp direct search fallback: {e}")

    # Fallback to search query
    encoded = urllib.parse.quote_plus(clean_q)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        subprocess.Popen(f'start "" "{url}"', shell=True)
        return f"Opening '{clean_q}' on YouTube, Sir."
    except Exception as e:
        return f"Failed to play YouTube video: {e}"


