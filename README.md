# J.A.R.V.I.S.
### *Just A Rather Very Intelligent System*

> A real-time, fully local, autonomous AI assistant for Windows 11 — inspired by Iron Man's J.A.R.V.I.S.

---

## What is this?

JARVIS is a **private, local-first AI assistant** that lives on your PC and can do everything you can do — and more. It listens to your voice, acts on your commands, remembers your preferences, and connects your entire digital ecosystem.

**No cloud. No subscriptions. Your data never leaves your machine.**

---

## Core Capabilities

| Capability | Details |
|:---|:---|
| 🎙️ **Voice Activated** | "Hey Jarvis" wake word + `Win+J` hotkey — both independently toggleable |
| 🔄 **Interruptible** | Barge-in mid-sentence; Jarvis picks up exactly where it left off (VS Code Copilot-style steer) |
| 🖥️ **Full PC Control** | Files, folders, apps, windows, system settings, registry, GPU tuning |
| 🌐 **Browser Agent** | Controls Brave (default) or any browser — browses, clicks, fills forms, researches |
| 🤖 **Self-Extending** | Finds or generates its own MCP tools to interface with any new application |
| 🧠 **Persistent Memory** | Tiered memory: working cache → SQLite state → LanceDB vector store → entity graph |
| 🔐 **Secure Vault** | AES-256-GCM encrypted credential store — passwords used but never spoken or displayed |
| 🎭 **Mood Adaptive** | Voice-acoustic mood detection (pitch/energy/rate) adjusts tone and response style |
| 📱 **Eve Companion** | Mobile companion on Nothing Phone 2a — shared memory, proximity-triggered task handoff |
| 🔵 **Peripherals** | Bluetooth device discovery & connection + WiFi smart device control (TV, speakers) |

---

## Local Model Stack

| Model (Ollama) | Role |
|:---|:---|
| `qwen3.5:4b` | Always-on fast brain — lives in VRAM permanently |
| `qwen2.5-coder:7b` | Code generation, MCP auto-creation |
| `gemma4:latest` | Deep reasoning, screen vision, complex planning |
| `qwen3.5-32k` / `qwen2.5-coder-32k` | Long-context variants |

| Model (HuggingFace) | Role |
|:---|:---|
| `Silero VAD v5` | Voice activity detection |
| `faster-distil-whisper-medium.en` | Speech-to-text (CUDA) |
| `Kokoro-82M` | Text-to-speech (Jarvis voice) |
| `all-MiniLM-L6-v2` | Memory embeddings |

---

## Branch Strategy

| Branch | Purpose |
|:---|:---|
| `main` | 🏁 Stable releases only |
| `dev` | 🔨 Active development — all new work goes here |
| `qa` | 🧪 Testing before merge to main |

**We always work on `dev`. Never commit directly to `main`.**

---

## Setup

### Prerequisites
- Windows 11
- Python 3.12 (via `uv`)
- [Ollama](https://ollama.ai) with the models listed above
- NVIDIA GPU with CUDA (RTX 4050 or better recommended)

### Install
```bash
# 1. Clone and enter the project
git clone https://github.com/Om-Borse26/Jarvis.git
cd Jarvis
git checkout dev

# 2. Create virtual environment and install dependencies
uv venv --python 3.12
uv sync

# 3. Download HuggingFace models (first run only, ~1.2 GB)
uv run python scripts/download_models.py

# 4. Start Ollama (from system tray or: ollama serve)
# Ensure qwen3.5:4b is pulled: ollama pull qwen3.5:4b

# 5. Launch Jarvis
uv run python main.py
```

### Configuration
Edit [`config/settings.toml`](config/settings.toml) to customize:
- Wake word on/off toggle
- Hotkey (`Win+J` by default)
- Browser preference (Brave default)
- TTS voice and speed
- Model routing preferences

---

## Project Structure

```
Jarvis/
├── jarvis/
│   ├── audio/          # VAD, STT, TTS, Mood Engine, Trigger System
│   ├── brain/          # Ollama client, model router, tool parser
│   ├── core/           # Pipeline orchestrator, Steer Arbiter, config
│   ├── memory/         # L1–L5 tiered memory + credential vault
│   ├── tools/          # PC control, browser, screen, OS, MCP discovery
│   ├── hud/            # Adaptive glassmorphism overlay UI
│   └── eve/            # Mobile companion sync server + PWA
├── scripts/            # Setup and utility scripts
├── config/             # settings.toml — all user configuration
├── models/             # Downloaded model weights (gitignored)
├── data/               # Runtime data: DB, vectors, logs (gitignored)
└── main.py             # Entry point
```

---

## Roadmap

- [x] Phase 1: Core voice loop (STT → LLM → TTS)
- [ ] Phase 2: Full-duplex audio + Steer/Interruption engine
- [ ] Phase 3: Adaptive HUD overlay (glassmorphism UI)
- [ ] Phase 4: Universal PC control + MCP auto-discovery
- [ ] Phase 5: Tiered memory + credential vault
- [ ] Phase 6: Personality + mood-adaptive model routing
- [ ] Phase 7: Eve mobile companion + Bluetooth/WiFi peripherals

---

*This is a private project. All data stays local.*
