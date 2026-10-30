"""
J.A.R.V.I.S. — Speech & Accent Acoustic Normalizer
Translates phonetic speech-to-text slips, regional accent homophones,
and conversational wrappers into clean, actionable AI intents.
"""
from __future__ import annotations

import re
from loguru import logger


# Common homophone and acoustic misrecognition mappings
HOMOPHONE_MAP = [
    # Mail vs Male
    # Mail vs Male / Meal
    (r"\b(compose|send|write|create|draft|check|read|open)\s+(?:a\s+)?(?:male|meal)\b", r"\1 a mail"),
    (r"\b(new|incoming|unread|my)\s+(?:male|meal)\b", r"\1 mail"),
    (r"\bwant\s+to\s+compose\s+(?:a\s+)?(?:male|meal)\b", "want to compose a mail"),

    # WhatsApp acoustic variations ("what-up group", "wassup", "whats app")
    (r"\b(?:what[\s\-_]*up|wassup|whats[\s\-_]*app|what['’]s[\s\-_]*app)\b", "whatsapp"),

    # VS Code / IDE acronyms & phonetic slips ("viscode", "vsas code", "v s code")
    (r"\b(?:viscode|vscod|vis\s*code|vsas\s*code|we\s*s\s*code)\b", "vs code"),
    (r"\b(?:v\.s\.|v\.\s*s\.|v\s+s)\s*code\b", "vs code"),
    (r"\bvisual\s+studio\s+code\b", "vs code"),
    (r"\b(?:now\s+)?try\s+opening\b", "open"),
    (r"\bdo\s+one\s+thing[,\s]+", ""),

    # URL / Web slips
    (r"\b(?:the|this)\s+u\.s\.\b", "the URL"),
    (r"\bu\.s\.\s+(?:is|was)\s+(?:wrong|invalid)\b", "URL is wrong"),

    # Assistant name variations
    (r"\b(?:jarvvis|javis|jarves|jarviz|jarvus)\b", "jarvis"),

    # YouTube, Creators & Media
    (r"\bbrem\b", "dream"),
    (r"\bdreams?\s+channel\b", "Dream channel on youtube"),
    (r"\bmine\s*craft\b", "minecraft"),
    (r"\byou\s*tube\b", "youtube"),
    (r"\byt\s+channel\b", "youtube channel"),
    (r"\byt\b", "youtube"),

    # MCPs, Software & Tools
    (r"\bstitch\s+(?:mcb|mcbb|mcibb|m\s*c\s*b)\b", "stitch mcp"),
    (r"\banti[\s\-_]*gravity\b", "antigravity"),
    (r"\bplay\s*wright\b", "playwright"),
    (r"\bpower\s*shell\b", "powershell"),
]

# Conversational prefix and suffix wrappers
WRAPPER_PREFIXES = [
    r"^(?:hey\s+|hi\s+|hello\s+)?(?:jarvis[,\s]+)?",
    r"^(?:just\s+do\s+one\s+thing[\.,\s]+|do\s+one\s+thing[\.,\s]+)?",
    r"^(?:now\s+try\s+|try\s+(?:to\s+)?|now\s+can\s+you\s+)",
    r"^(?:and\s+you\s+|and\s+then\s+|and\s+|then\s+you\s+|then\s+|also\s+you\s+|also\s+|so\s+you\s+|so\s+)",
    r"^(?:can\s+you\s+also\s+|also\s+can\s+you\s+|can\s+you\s+just\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|will\s+you\s+)(?:please\s+)?(?:just\s+)?",
    r"^(?:i\s+want\s+(?:you\s+to\s+|to\s+)?|i\s+need\s+(?:you\s+to\s+|to\s+)?|please\s+)",
    r"^(?:let\s+me[,\s]+)?(?:can\s+you\s+just\s+|can\s+you\s+)",
    r"^(?:just\s+)",
]



class SpeechNormalizer:
    """Cleans, disambiguates, and extracts intent from raw speech transcriptions."""

    @classmethod
    def normalize(cls, raw_text: str) -> str:
        """Apply phonetic homophone correction and whitespace cleanup."""
        if not raw_text:
            return ""

        text = raw_text.strip()

        # Apply homophone / acoustic substitutions
        for pattern, replacement in HOMOPHONE_MAP:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text.strip()

    @classmethod
    def clean_command(cls, text: str) -> str:
        """Strip conversational filler to uncover the core command."""
        cleaned = text.strip().rstrip(".!?")

        # Strip prefixes
        for pat in WRAPPER_PREFIXES:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

        # Strip conversational trailing questions & polite suffixes
        cleaned = re.sub(
            r"[\.,]?\s*(?:can\s+you\s+(?:do\s+that|do\s+this|help\s+me)(?:\s+or\s+not)?|is\s+that\s+possible|do\s+that\s+for\s+me)\??$",
            "",
            cleaned,
            flags=re.IGNORECASE
        ).strip()
        cleaned = re.sub(r"(?:\s+for\s+me|\s+please|\s+now|\s+right\s+now)$", "", cleaned, flags=re.IGNORECASE).strip()

        return cleaned
