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
