from jarvis.core.intent_scope import scope_categories
from jarvis.core.clarify import missing_slot_question
from jarvis.core.rules_engine import rules_engine
from jarvis.audio.mood import MOOD_TEMPERATURE, MOOD_TTS_SPEED, MOOD_TONES


# ── Tool scoping ─────────────────────────────────────────────────────────
def test_scope_files_command():
    assert scope_categories("create a new folder on my desktop") == ["filesystem"]


def test_scope_app_command_includes_process_and_window():
    cats = scope_categories("switch to brave")
    assert cats is not None and "process" in cats and "window" in cats


def test_scope_web_command():
    assert scope_categories("search google for the weather") is not None
    assert "web" in scope_categories("open youtube and play music")


def test_scope_returns_none_when_ambiguous():
    assert scope_categories("what do you think about life") is None
    assert scope_categories("") is None


def test_scope_broad_utterance_falls_back_to_full_toolset():
    # Lighting up most groups should disable scoping (return None).
    noisy = "open the file folder browser search volume play lock screen code terminal whatsapp gpu"
    assert scope_categories(noisy) is None


# ── Deterministic slot clarification ─────────────────────────────────────
def test_reminder_without_time_asks_when():
    assert "when" in missing_slot_question("remind me to call mom").lower()


def test_reminder_with_time_is_complete():
    assert missing_slot_question("remind me to call mom in 10 minutes") is None
    assert missing_slot_question("remind me at 5pm") is None


def test_search_without_query_asks():
    assert "search for" in missing_slot_question("search the web").lower()


def test_search_with_query_is_complete():
    assert missing_slot_question("search for the weather today") is None


def test_write_without_topic_asks():
    assert missing_slot_question("write an essay") is not None


def test_write_with_topic_is_complete():
    assert missing_slot_question("write an essay about climate change") is None


def test_message_without_recipient_asks():
    assert missing_slot_question("send a whatsapp message") is not None


def test_bare_open_asks_which_app():
    assert "application" in missing_slot_question("open").lower()


def test_complete_commands_need_no_clarification():
    for utterance in ("open brave", "what's the time", "lock my pc", "search for cats"):
        assert missing_slot_question(utterance) is None


# ── Mood wiring ──────────────────────────────────────────────────────────
def test_every_mood_has_temperature_and_speed():
    for mood in MOOD_TONES:
        assert mood in MOOD_TEMPERATURE
        assert mood in MOOD_TTS_SPEED
        assert 0.0 <= MOOD_TEMPERATURE[mood] <= 1.0


def test_focused_is_crisper_than_relaxed():
    assert MOOD_TEMPERATURE["focused"] < MOOD_TEMPERATURE["relaxed"]


# ── Focus-loss policy ────────────────────────────────────────────────────
def test_focus_application_does_not_steal_focus():
    # The explicit user-initiated focus tool is exempt from the gate.
    assert rules_engine.steals_focus("focus_application") is False


def test_gui_macros_steal_focus():
    assert rules_engine.steals_focus("keyboard_type") is True
    assert rules_engine.steals_focus("mouse_click") is True


def test_launch_only_steals_focus_when_forced_new():
    assert rules_engine.steals_focus("launch_application", {"force_new": False}) is False
    assert rules_engine.steals_focus("launch_application", {"force_new": True}) is True


# ── Centralized rules_engine policies ────────────────────────────────────
def test_should_reuse_window_policy():
    assert rules_engine.should_reuse_window("brave") is True
    assert rules_engine.should_reuse_window("brave", force_new=True) is False
    assert rules_engine.should_reuse_window("brave in a new window") is False
    assert rules_engine.should_reuse_window("a duplicate vs code") is False


def test_should_reuse_tab_policy():
    assert rules_engine.should_reuse_tab("go to reddit") is True
    assert rules_engine.should_reuse_tab("open reddit", new_tab=True) is False
    assert rules_engine.should_reuse_tab("open reddit in a new tab") is False
    assert rules_engine.should_reuse_tab("open reddit", force_new=True) is False


def test_requires_confirmation_matches_destructive():
    assert rules_engine.requires_confirmation("delete_file", {"path": "x"}) is True
    assert rules_engine.requires_confirmation("launch_application", {"app_name": "brave"}) is False

