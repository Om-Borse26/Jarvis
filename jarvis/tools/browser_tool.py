"""
J.A.R.V.I.S. — Browser & Web Automation Tool (Playwright & System)
Provides direct web browser automation using Playwright and system browsers:
  - Automate browser actions (navigate, click, fill forms, extract text)
  - Perform real headless or headful DOM operations
  - Fall back to system default or Brave Browser for standard navigation
"""
from __future__ import annotations

import urllib.parse
from typing import Any
from loguru import logger
from jarvis.tools.registry import register_tool


@register_tool(
    name="automate_browser",
    description="Automate a real browser using Playwright to navigate, click buttons, fill text, or extract webpage content.",
    category="web"
)
async def automate_browser(url: str, action: str = "navigate", selector: str = "", text: str = "") -> str:
    """Automate real browser interactions using Playwright."""
    from playwright.async_api import async_playwright

    target_url = url.strip()
    if not target_url.startswith(("http://", "https://")):
        target_url = f"https://{target_url}"

    try:
        async with async_playwright() as p:
            # Launch system Chrome channel
            browser = await p.chromium.launch(channel="chrome", headless=True)
            page = await browser.new_page()
            await page.goto(target_url, timeout=15000)

            act = action.lower().strip()
            if act == "click" and selector:
                await page.click(selector, timeout=6000)
                result = f"Clicked element '{selector}' on {target_url}."
            elif act in ("type", "fill") and selector and text:
                await page.fill(selector, text, timeout=6000)
                result = f"Filled '{selector}' with '{text}' on {target_url}."
            elif act == "extract":
                title = await page.title()
                body = await page.inner_text("body")
                snippet = body[:800].replace("\n", " ").strip()
                result = f"Page Title: {title}\nContent snippet: {snippet}"
            else:
                title = await page.title()
                result = f"Navigated to {target_url}. Page title: '{title}'."

            await browser.close()
            return result
    except Exception as e:
        logger.error(f"Playwright automation error: {e}")
        return f"Browser automation error: {e}"
