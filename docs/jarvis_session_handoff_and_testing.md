# J.A.R.V.I.S. — Session Handoff & Full Test Plan

> Purpose: give Antigravity (and you) the complete context of what we changed this
> session, **why**, and **how**, plus a start‑to‑end checklist to test every part on
> your real PC. Work is on the **`dev`** branch. After pulling, do the one‑time setup
> in Part 3, then run the tests in Part 4 and note anything that doesn't match.

---

## Part 0 — TL;DR of the session

We started from a working-but-rough build and fixed the things that made Jarvis feel
dumb/slow on a weak local model, then added the architecture we'd agreed on, then
replaced the boxed orb with a Dynamic Island.

Branch `dev`, commits in order:

| Commit | Title |
|---|---|
| `6498a58` | focus: background‑by‑default launches + smart focus/switch command |
| `6bc26ba` | arch: tool scoping, mood wiring, slot clarification, focus‑loss gate |
| `ace08b9` | arch: web knowledge Q&A (Tavily + fact memory) + procedure memory |
| `70eace5` | refactor: centralize reuse/path/confirm policies in rules_engine |
| `63cf811` | feat: .env secrets loader, invisible background launch, model assignment |
| `af9d17a` | ui: Dynamic Island replaces the orb |

Unit tests: **~141 passing** (`python -m pytest tests/unit -q`).

---

## Part 1 — The problems that drove these changes

1. **Latency** — the 7B local model took ~15–20 s and sometimes spoke tool‑call JSON
   aloud or only ran the last step of a compound command.
2. **Focus stealing** — opening an app or creating a folder yanked you away from what
   you were doing (it force‑focused VS Code / the launched app).
3. **No explicit "switch to X"** — and launching an already‑open app spawned noise or
   dumbly re‑opened it.
4. **Weak model asked to do too much** — routing, slot‑filling, and answering facts all
   fell on the 7B, which is slow and error‑prone.
5. **Boxed orb** — WebView2 can't do true transparency, so the orb showed as a dark
   square with the orb inside it.

## Part 1b — Decisions we made (and why)

- **Background by default; explicit focus on command.** Actions that don't need to
  steal focus run in the background; a real `focus/switch` command exists for when you
  *do* want to come to an app. (Matches how you actually work.)
- **Tool scoping (poor‑man's two‑brain).** Instead of handing the model all ~90 tools,
  we classify the request into a few relevant categories and send only those tools.
  Smaller prompt → faster + more accurate on a weak model. Ambiguous → full toolset
  (never trade capability for speed).
- **Deterministic slot clarification.** Missing info (reminder time, search query, essay
  topic, message recipient) is detected by rules and asked instantly — the weak model
  is never asked to guess.
- **Cloud answer for open‑web questions (Tavily), local model stays private.** General
  knowledge is answered by Tavily's `include_answer`; the local model only routes and
  phrases. **Privacy rule (hard):** files, file contents, credentials, and screen text
  are NEVER sent to the cloud — questions that look private are kept local.
- **Self‑learning fact cache.** Answers are remembered so the same question is instant
  next time (no second web call).
- **Procedure/recipe memory.** Name a multi‑step routine once, run it with one phrase.
- **Policies centralized in `rules_engine`.** Single‑instance reuse, tab reuse, path
  resolution, and "needs confirmation" live in one place.
- **Models assigned for 6 GB VRAM.** Small fast model resident for everyday/routing;
  bigger models load on demand only for code/deep/long tasks. `gemma4` excluded (too
  big for 6 GB → CPU → slow).
- **Dynamic Island instead of the orb.** A solid rounded pill (clipped window region)
  sidesteps the transparency limitation and looks clean. Default **not‑on‑top**; comes
  forward only on command; hover → mini panel; click/voice → full dashboard.

## Part 1c — Architecture overview (how a request flows)

```
Wake word / Win+J → VAD → STT → (consent? ) → Router fast‑path ──► instant action
                                              │ (no match)
                                              ▼
                              slot clarification? ──► ask & stop
                                              │ (complete)
                                              ▼
                          scope tools → LLM tool decision (mood temp)
                                              │
                        tool_calls? ──► AgentLoop (focus‑loss gate, consent) → TTS
                        else ──► speak answer → TTS
```

Key files touched this session:
- Routing / fast‑paths: [jarvis/tools/router.py](../jarvis/tools/router.py)
- Tool scoping: [jarvis/core/intent_scope.py](../jarvis/core/intent_scope.py)
- Slot clarification: [jarvis/core/clarify.py](../jarvis/core/clarify.py)
- Focus / background launch / invisible launch: [jarvis/tools/process_control.py](../jarvis/tools/process_control.py)
- Focus‑loss + policies: [jarvis/core/rules_engine.py](../jarvis/core/rules_engine.py), [jarvis/core/agent_loop.py](../jarvis/core/agent_loop.py)
- Mood wiring: [jarvis/audio/mood.py](../jarvis/audio/mood.py), [jarvis/audio/tts.py](../jarvis/audio/tts.py), [jarvis/core/pipeline.py](../jarvis/core/pipeline.py)
- Web Q&A + fact memory: [jarvis/tools/knowledge.py](../jarvis/tools/knowledge.py), [jarvis/memory/facts.py](../jarvis/memory/facts.py)
- Procedures: [jarvis/tools/procedures.py](../jarvis/tools/procedures.py), [jarvis/memory/procedures.py](../jarvis/memory/procedures.py)
- Secrets loader: [jarvis/core/env.py](../jarvis/core/env.py)
- Dynamic Island: [jarvis/ui/island.py](../jarvis/ui/island.py), [jarvis/ui/web/island.html](../jarvis/ui/web/island.html), [jarvis/ui/state.py](../jarvis/ui/state.py), [jarvis/ui/server.py](../jarvis/ui/server.py)
- Config: [config/settings.toml](../config/settings.toml)

---

## Part 2 — What each commit did (what / why / how)

### 1) `6498a58` — Background‑by‑default launches + smart focus/switch
- **What:** New `focus_application` tool with smart rules; launches/`create_directory`
  stopped force‑focusing.
- **Why:** Stop yanking you away; give a real "switch to X".
- **How:** Added `find_app_window` (inspect without focusing), `is_app_open`,
  `decide_focus_message` (pure), and router fast‑paths (`switch to`, `focus on`,
  `show me`, `bring up`, `go to`, `jarvis focus`).

### 2) `6bc26ba` — Tool scoping, mood wiring, slot clarification, focus‑loss gate
- **What:** `scope_categories` narrows tools; mood → LLM temperature + TTS speed;
  `missing_slot_question` asks for missing info; `steals_focus` gate asks once per task
  before a focus‑stealing macro.
- **Why:** Speed + accuracy on the weak model; mood was dead; weak model shouldn't guess.
- **How:** `intent_scope.py`, `clarify.py`, `rules_engine.steals_focus`,
  `agent_loop` one‑approval‑per‑task gate, pipeline passes scoped tools + mood temp.

### 3) `ace08b9` — Web knowledge Q&A + procedure memory
- **What:** `answer_from_web` (Tavily `include_answer`, privacy guard, fact cache,
  browser fallback); `save/list/delete/run_procedure`.
- **Why:** Factual answers without hallucination; one‑phrase routines; self‑learning.
- **How:** `knowledge.py`, `facts.py`, `procedures.py`; router routes open‑web questions
  and "run my … routine".

### 4) `70eace5` — Centralize policies in `rules_engine`
- **What:** `should_reuse_window`, `should_reuse_tab`, `resolve_path`,
  `requires_confirmation` as the single source of truth; `launch()` uses them.
- **Why:** Stop re‑implementing the same rules in multiple tools.

### 5) `63cf811` — `.env` loader, invisible launch, model assignment
- **What:** `.env` secrets loader (one place for keys); true invisible launch (restore
  your window after an app grabs focus); 6 GB‑VRAM model map in settings.
- **Why:** Simple secret handling; honor "background unless I say focus"; responsiveness.

### 6) `af9d17a` — Dynamic Island
- **What:** Rounded pill top‑center replacing the orb; hover → reminders; right‑nav →
  tool/access toggles; click/voice → full dashboard; voice come‑forward/step‑back.
- **Why:** Clean, non‑boxed, non‑intrusive UI that sidesteps WebView2 transparency.

---

## Part 3 — One‑time setup before testing (do these in order)

1. **Pull the branch**
   ```powershell
   cd C:\Work\Jarvis
   git checkout dev
   git pull origin dev
   ```

2. **Create the secrets file** (root of repo, next to `main.py`):
   - Copy `.env.example` → `.env`
   - Put your key in it:
     ```
     TAVILY_API_KEY=tvly-YOURKEYHERE
     ```
   - `.env` is gitignored. This single file is read by BOTH the direct Tavily call and
     the Tavily MCP server.
   - **MCP vs direct call:** Jarvis answers questions via a direct Tavily REST call
     (fast, one‑line answer). The `tavily` MCP server is optional/for richer search and
     reads the same key from the environment. You do **not** need to run the MCP server
     for `answer_from_web` to work — just the `.env` key.

3. **Verify your Ollama models exist** (names must match `config/settings.toml`):
   ```powershell
   ollama list
   ```
   Expected to include: `qwen3.5:4b`, `qwen2.5-coder:7b`, `qwen3.5-32k:latest`,
   `qwen2.5-coder-32k:latest`. (If `qwen3.5:4b` doesn't do tool‑calling well on your
   build, tell me and we'll move `fast_model` to `qwen2.5-coder:7b`.)

4. **Install deps** (if not already):
   ```powershell
   uv sync
   ```

5. **Run the unit tests** (pure logic, no mic/models needed):
   ```powershell
   python -m pytest tests/unit -q
   ```
   - ✅ **Expected:** `~141 passed`. If any fail, copy the failing test name here.

6. **Start Jarvis**
   ```powershell
   python main.py
   ```
   - Trigger listening with **Win+J** or the wake word **"Hey Jarvis"**.

> How to report a failure for any test below: note the **test number**, **what you said/did**,
> **what Jarvis actually said/did**, and **what you expected**.

---

## Part 4 — Full start‑to‑end test checklist

Legend: 🗣 = say it (voice) · ✅ = expected · ⬜ = your result

### A. Smoke / startup
- **A1** 🗣 "Hey Jarvis" (or Win+J) → ✅ it starts listening (Island shows listening
  animation / chime). ⬜
- **A2** Look at the top‑center of the desktop → ✅ a dark rounded **pill** (Dynamic
  Island) is visible, **no square background**. ⬜
- **A3** 🗣 "What time is it" → ✅ speaks the time. ⬜

### B. Focus & background launch
- **B1** With Brave **closed**, 🗣 "switch to brave" → ✅ "Brave isn't open, Sir." ⬜
- **B2** With Brave **open but not focused**, 🗣 "switch to brave" → ✅ Brave comes to
  front, "Switched to Brave, Sir." ⬜
- **B3** With Brave **already in front**, 🗣 "switch to brave" → ✅ "You're already on
  Brave, Sir." (does NOT open a second one). ⬜
- **B4** While working in VS Code, 🗣 "open notepad" (Notepad closed) → ✅ "Opening
  Notepad in the background, Sir." and **focus stays on VS Code** (Notepad opens behind /
  focus returns to you within ~1 s). ⬜ *(Honest caveat: a brief flicker is possible.)*
- **B5** With VS Code already open, 🗣 "open vs code" → ✅ "VS Code is already open, Sir.
  Say 'switch to VS Code' to bring it up." (no focus steal, no duplicate). ⬜
- **B6** 🗣 "focus" (nothing else) → ✅ "Which application should I switch to, Sir?" ⬜
- **B7** 🗣 "show me brave" / "bring up vs code" / "go to brave" → ✅ same focus behavior
  as B2/B3. ⬜

### C. Slot clarification (deterministic)
- **C1** 🗣 "remind me to call mom" → ✅ "When would you like me to remind you, Sir?" ⬜
- **C2** 🗣 "remind me to call mom in 10 minutes" → ✅ sets the reminder (no "when"
  question). ⬜
- **C3** 🗣 "search the web" → ✅ "What would you like me to search for, Sir?" ⬜
- **C4** 🗣 "write an essay" → ✅ "What should it be about, Sir?" ⬜
- **C5** 🗣 "send a whatsapp message" → ✅ "Who should I send it to, Sir?" ⬜

### D. Web knowledge Q&A (needs TAVILY_API_KEY in `.env`)
- **D1** 🗣 "what is the capital of France" → ✅ speaks a concise answer (e.g., "Paris").
  ⬜
- **D2** Immediately repeat **D1** → ✅ answers instantly (served from fact memory; watch
  the log for "Answered from learned‑fact memory"). ⬜
- **D3** 🗣 "what's on my screen" → ✅ stays **local** (screen/vision path), NOT a web
  search. ⬜
- **D4** *(No key test)* temporarily blank the key, 🗣 "who won the last world cup" → ✅
  "I couldn't get a direct answer, so I've opened a web search for '…', Sir." + browser
  opens a search. ⬜

### E. Procedure / recipe memory
- **E1** 🗣 "save a routine called work setup that opens vs code and opens brave" → ✅
  "Saved your 'work setup' routine with 2 steps, Sir." *(This goes through the model to
  call `save_procedure`; if it doesn't, note it.)* ⬜
- **E2** 🗣 "run my work setup routine" → ✅ runs each step (VS Code + Brave handling),
  "Ran your 'work setup' routine — completed 2 of 2 steps, Sir." ⬜
- **E3** 🗣 "list my routines" → ✅ "Your saved routines: work setup." ⬜
- **E4** 🗣 "delete my work setup routine" → ✅ "Deleted your 'work setup' routine, Sir."
  ⬜

### F. Focus‑loss confirmation gate
- **F1** Ask something that makes Jarvis use keyboard/mouse automation (e.g., 🗣 "type
  'hello world' into notepad") while you're focused elsewhere → ✅ it asks once:
  "This will switch away from your current window. Shall I proceed?" → say "yes" → it
  proceeds; later steps in the same task don't re‑ask. ⬜
- **F2** Repeat F1 and say "no" → ✅ "Understood, I'll leave your current window in
  focus." ⬜

### G. Dynamic Island UI
- **G1** Hover the pill → ✅ it expands to a **mini panel** showing reminders/schedule.
  ⬜ *(If hover doesn't trigger, try clicking — note it; we can switch to click‑expand.)*
- **G2** In the mini panel, click the **›** (right chevron) → ✅ **Tools & Access** panel
  with on/off toggles. Flip one off (e.g., `web`) → ✅ that category is blocked (try a web
  command → Jarvis says it's not allowed). Flip it back on. ⬜
- **G3** Click the **‹** to go back, then **×** to collapse → ✅ returns to the pill. ⬜
- **G4** Click the pill (or the "Open full dashboard" button) → ✅ it **morphs into the
  full dashboard** (same window grows). ⬜
- **G5** 🗣 "open dashboard" → ✅ the Island morphs to the dashboard (if running), else a
  browser dashboard opens. ⬜
- **G6** 🗣 "come forward" / "focus on yourself" → ✅ the Island rises **on top** of other
  windows. ⬜
- **G7** 🗣 "step back" / "minimize yourself" → ✅ it collapses to the pill and drops
  **behind** your apps. ⬜
- **G8** Maximize an app over where the Island sits → ✅ the Island is **covered** (it does
  not float over your apps) until you call it forward. ⬜

### H. State animation (Island reflects what Jarvis is doing)
- **H1** While idle → ✅ gentle glowing dot. ⬜
- **H2** While you speak → ✅ equalizer bars animate (listening). ⬜
- **H3** While Jarvis thinks/speaks → ✅ color shifts (purple thinking / blue speaking) +
  caption text. ⬜

### I. Mood → delivery (subtle, observe)
- **I1** Speak calmly vs. urgently across a few turns → ✅ TTS pace shifts slightly
  (a touch quicker when you sound focused/energized, slower when tired/stressed). This is
  subtle — just confirm nothing sounds broken. ⬜

### J. Regression / core still works
- **J1** 🗣 "set volume to 30" → ✅ "Master volume set to 30 percent, Sir." ⬜
- **J2** 🗣 "lock my pc" → ✅ locks (say it only when ready). ⬜
- **J3** 🗣 "create a folder called demo on my desktop" → ✅ creates it, and **does not
  steal focus**. ⬜
- **J4** 🗣 "what apps are running" → ✅ lists active apps. ⬜
- **J5** 🗣 "delete the demo folder" → ✅ asks for confirmation first, then deletes on
  "yes". ⬜

### K. Latency check (model assignment)
- **K1** Do a few everyday commands (B/C/J above) and note the delay from end‑of‑speech
  to Jarvis responding. ✅ Should feel noticeably snappier than before (fast path is
  instant; model path on `qwen3.5:4b` with scoped tools). Note rough seconds. ⬜

---

## Part 5 — What is deferred / known caveats (so you don't flag these as bugs)

- **Hover‑expand** depends on the non‑activating window receiving mouse events; if it
  doesn't on your machine, click/voice still work and we'll switch to click‑to‑expand.
- **Morph animation** is a clean resize + fade, not a frame‑by‑frame eased animation
  (native window easing stutters). Say if you want me to try an eased version.
- **Per‑MCP‑server toggles** in the Island show access **categories** for now, not each
  MCP server individually.
- **Fresh app launch** may still briefly flash before focus returns (Windows
  foreground‑lock) — expected, not a bug.
- **CDP‑attached Brave profile** for background browser control is **not** built yet
  (future increment); browser actions still use keyboard automation.
- `orb.py` remains in the repo but is no longer launched; can be deleted later.

---

## Part 6 — How to send results back

For each ⬜ you can just mark ✅/❌. For any ❌, send:
```
Test: <e.g., B4>
I said/did: <...>
Jarvis did: <...>
I expected: <...>
```
I'll triage and we'll fix in order of impact.
