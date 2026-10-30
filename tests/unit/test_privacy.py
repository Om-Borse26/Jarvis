"""Privacy-aware routing: non-private, no-tool turns may use the cloud; else local."""
import pytest

from jarvis.core.privacy import is_private, allow_cloud


@pytest.mark.parametrize("text", [
    "how are you", "tell me a joke", "what is quantum computing",
    "who won the world cup", "what is the capital of France",
    "explain photosynthesis", "thanks", "good morning",
])
def test_non_private_turns_allow_cloud(text):
    assert is_private(text) is False
    assert allow_cloud(text, tools_offered=False) is True


@pytest.mark.parametrize("text", [
    "what's in my file notes.txt", "remind me to call mom", "what do you remember about me",
    "what's on my screen", "open my downloads folder", "what is my name",
    "set the volume to 30", "whats my gpu temperature", "save my password",
    "read my email", "what's my schedule",
])
def test_private_turns_stay_local(text):
    assert is_private(text) is True
    assert allow_cloud(text, tools_offered=False) is False


def test_any_tool_use_forces_local():
    # Even a non-private utterance must stay local if it would run a tool.
    assert allow_cloud("open youtube", tools_offered=True) is False


def test_empty_is_treated_private():
    assert is_private("") is True
    assert allow_cloud("", tools_offered=False) is False
