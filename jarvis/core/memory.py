"""
J.A.R.V.I.S. — Persistent Memory & User Knowledge Engine
Manages:
  1. Long-term user identity and personal preferences (e.g. name, browser, habits)
  2. Fact recollection and contextual memory injection into LLM prompts
  3. Structured self-knowledge of all Jarvis system capabilities
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger
from jarvis.tools.registry import register_tool

MEMORY_DIR = Path("data/memory")
PROFILE_FILE = MEMORY_DIR / "user_profile.json"
FACTS_FILE = MEMORY_DIR / "facts.json"


class MemoryManager:
    """Manages persistent facts, personal identity, and system knowledge."""

    def __init__(self, memory_dir: Path | str = MEMORY_DIR) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.memory_dir / "user_profile.json"
        self.facts_path = self.memory_dir / "facts.json"

        self._profile: Dict[str, Any] = {
            "user_name": "Om",
            "preferred_browser": "Brave",
            "voice_enrolled": False,
            "registered_speaker": "Om",
            "system": "Windows 11 with NVIDIA RTX 4050 GPU",
        }
        self._facts: List[Dict[str, Any]] = []

        self.load()

    def load(self) -> None:
        """Load user profile and facts from persistent JSON files."""
        if self.profile_path.exists():
            try:
                data = json.loads(self.profile_path.read_text(encoding="utf-8"))
                self._profile.update(data)
            except Exception as e:
                logger.warning(f"Could not load user profile: {e}")

        if self.facts_path.exists():
            try:
                self._facts = json.loads(self.facts_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not load facts: {e}")
        else:
            # Seed initial foundational facts
            self._facts = [
                {"fact": "User's name is Om.", "category": "identity", "timestamp": time.time()},
                {"fact": "Om prefers using Brave browser for web navigation.", "category": "preference", "timestamp": time.time()},
                {"fact": "Om's laptop is powered by an NVIDIA RTX 4050 GPU.", "category": "system", "timestamp": time.time()},
            ]
            self.save_facts()

    def save_profile(self) -> None:
        """Persist user profile to disk."""
        try:
            self.profile_path.write_text(json.dumps(self._profile, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save user profile: {e}")

    def save_facts(self) -> None:
        """Persist user facts to disk."""
        try:
            self.facts_path.write_text(json.dumps(self._facts, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save facts: {e}")

    @property
    def user_name(self) -> str:
        return self._profile.get("user_name", "Om")

    def set_user_name(self, name: str) -> None:
        clean = name.strip().title()
        self._profile["user_name"] = clean
        self.save_profile()
        self.add_fact(f"User's name is {clean}.", category="identity")

    def add_fact(self, fact: str, category: str = "general") -> str:
        """Store a new fact about the user or system."""
        clean = fact.strip().rstrip(".") + "."
        # Avoid duplicate exact facts
        for item in self._facts:
            if item.get("fact", "").lower() == clean.lower():
                return f"I already remember that {clean}"

        entry = {
            "fact": clean,
            "category": category,
            "timestamp": time.time(),
        }
        self._facts.append(entry)
        self.save_facts()
        try:
            from jarvis.memory.semantic import semantic_memory
            semantic_memory.add(clean, category)
        except Exception:
            pass
        logger.info(f"🧠 [MEMORY] Stored fact: '{clean}' [{category}]")
        return f"Understood, Sir. I will remember that {clean}"

    def get_facts_summary(self) -> str:
        """Return a formatted string of remembered facts for the LLM prompt."""
        if not self._facts:
            return f"User is {self.user_name}."
        lines = [f"- {item['fact']}" for item in self._facts[-15:]]
        return "\n".join(lines)

    def get_capabilities_summary(self) -> str:
        """Return an articulate overview of Jarvis's abilities."""
        return (
            "I am J.A.R.V.I.S., your desktop AI assistant. My capabilities include: "
            "1. Dynamic application launching and process management without hardcoded paths. "
            "2. Acoustic voice biometrics ensuring I only follow your voice and ignore background chatter. "
            "3. Live barge-in interruption so you can cut me off naturally mid-sentence. "
            "4. Web automation and browsing with Playwright and Brave. "
            "5. Real-time screen capture and active window context analysis. "
            "6. Volume, media, and hardware telemetry tracking including your RTX 4050 GPU. "
            "7. Long-term memory for remembering your personal facts, preferences, and name."
        )


# Global Memory Manager instance
memory_manager = MemoryManager()


@register_tool(name="save_user_memory", description="Save a personal fact, habit, or preference to Jarvis's persistent long-term memory (e.g. user name, favorite apps, notes).", category="memory")
def save_user_memory(fact: str, category: str = "general") -> str:
    """Store a fact into Jarvis's long-term memory."""
    # Check if the fact specifies the user's name
    import re
    m = re.search(r"(?:my\s+name\s+is|call\s+me)\s+([a-zA-Z]+)", fact, re.IGNORECASE)
    if m:
        new_name = m.group(1).title()
        memory_manager.set_user_name(new_name)
        return f"Understood, Sir. I have recorded your name as {new_name} and will address you accordingly."
    return memory_manager.add_fact(fact, category)


@register_tool(name="recall_user_memories", description="Recall saved facts, preferences, or personal details about the user.", category="memory")
def recall_user_memories(query: str = "") -> str:
    """Recall remembered facts matching a query or all recent facts."""
    facts = memory_manager._facts
    if not facts:
        return "I do not have any saved personal memories yet, Sir."

    if query.strip():
        # Prefer meaning-based recall (L4 semantic); fall back to keyword match.
        try:
            from jarvis.memory.semantic import semantic_memory
            hits = semantic_memory.recall(query, k=5)
        except Exception:
            hits = []
        if hits:
            return "Here is what I remember: " + " ".join(hits)
        q = query.lower()
        matched = [f["fact"] for f in facts if q in f["fact"].lower() or q in f.get("category", "").lower()]
        if matched:
            return "Here is what I remember: " + " ".join(matched)
        return f"I could not find any memories regarding '{query}'."

    summary = " ".join([f["fact"] for f in facts[-6:]])
    return f"Here is what I currently remember about you: {summary}"


@register_tool(name="get_jarvis_capabilities", description="Get a summary of Jarvis's functionalities and automation abilities.", category="system")
def get_jarvis_capabilities() -> str:
    """Return Jarvis's functionalities and architecture."""
    return memory_manager.get_capabilities_summary()
