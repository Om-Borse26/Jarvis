"""
J.A.R.V.I.S. — Web Knowledge / Q&A
Answers open-web factual questions with a concise spoken answer using a cloud
answer API (Tavily `include_answer`), so the weak local model never has to
hallucinate facts. The local model's only job is routing/phrasing.

PRIVACY RULE (hard): only the natural-language question is ever sent to the
cloud. Files, file contents, credentials, and screen contents are NEVER sent.
Questions that look like they reference private/local data are refused here and
handled locally instead.

Flow: fact-memory cache → Tavily answer → remember it → (fallback) browser search.
Requires TAVILY_API_KEY in the environment; without it we gracefully fall back
to opening a normal web search in the browser.
"""
from __future__ import annotations

import os
import re

from loguru import logger

from jarvis.tools.registry import register_tool
from jarvis.memory.facts import fact_memory

# Signals that a question may contain private/local content — never send to cloud.
_PRIVATE_MARKERS = re.compile(
    r"\b(my (file|files|folder|document|password|passwords|credential|credentials|"
    r"screen|desktop|email|account|code|project|photo|photos)|"
    r"on my (screen|pc|computer|desktop)|this (file|code|screen|document)|"
    r"[a-z]:\\\\|/users/|~/|\.(py|txt|docx?|xlsx?|pdf|json|env)\b)"
)


def looks_private(question: str) -> bool:
    """True if the question appears to reference local/private data."""
    return bool(_PRIVATE_MARKERS.search((question or "").lower()))


def _tavily_answer(question: str) -> str:
    """Return a concise cloud answer, or '' if unavailable."""
    from jarvis.core.env import load_env_file
    load_env_file()
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return ""
    try:
        import requests
    except Exception:
        return ""
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": question,
                "include_answer": True,
                "max_results": 3,
                "search_depth": "basic",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("answer") or "").strip()
    except Exception as e:
        logger.warning(f"Tavily answer notice: {e}")
        return ""


@register_tool(
    name="answer_from_web",
    description="Answer a general-knowledge or current-events question with a concise spoken answer from the web (NOT about the user's PC, files, or screen). Use for facts like 'who won', 'what is', 'capital of', 'current price of'.",
    category="web",
)
def answer_from_web(question: str) -> str:
    """Answer an open-web factual question concisely, learning it for next time."""
    q = (question or "").strip()
    if not q:
        return "What would you like me to look up, Sir?"

    # Privacy guard — never route private/local questions to the cloud.
    if looks_private(q):
        return "That looks like something on your PC, Sir — I'll keep it local rather than searching the web."

    # 1. Answer instantly from the learned-fact cache if we've seen it.
    cached = fact_memory.recall(q)
    if cached:
        logger.info("🧠 Answered from learned-fact memory.")
        return cached

    # 2. Ask the cloud answer API.
    answer = _tavily_answer(q)
    if answer:
        fact_memory.remember(q, answer, source="tavily")
        return answer

    # 3. Fallback: open a normal web search in the browser.
    try:
        from jarvis.tools.web_control import search_web
        search_web(q)
        return f"I couldn't get a direct answer, so I've opened a web search for '{q}', Sir."
    except Exception:
        return "I couldn't reach the web to answer that right now, Sir."
