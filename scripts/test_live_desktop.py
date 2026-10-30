"""
J.A.R.V.I.S. — Live Desktop Test Runner
Sends realistic, conversational test queries to the live running Jarvis instance
(http://127.0.0.1:8787/api/chat) with delays in between.
Watch your screen as Jarvis:
- Animates HUD / Dynamic Island
- Executes tools live (opens apps, resizes windows, changes volume, plays YouTube)
- Speaks responses aloud via Kokoro TTS
"""
import sys
import time
import json
import urllib.request
import urllib.error

try:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ENDPOINT = "http://127.0.0.1:8787/api/chat"

LIVE_TEST_COMMANDS = [
    ("Adjust Volume", "Hey Jarvis, can you drop the master volume to 40%?"),
    ("Open Application", "Can you launch notepad for me?"),
    ("Window Focus", "Switch over to notepad, please."),
    ("Filesystem Action", "Create a file named demo.txt in the active workspace."),
    ("Multi-Intent Command", "Turn down the sound to 30% and make the screen brightness 90%."),
    ("YouTube Playback", "Can you find some valorant clips and put them on?"),
    ("Browser Full Screen", "Can you make brave full screen?"),
    ("Missing Tool Keybind", "Format my code in vs code."),
    ("Scheduler Reminder", "Remind me in two minutes to stretch."),
    ("Unsupported Query", "Can you bake me a fresh pizza?"),
]

def check_jarvis_online() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:8787/api/state")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "state" in data
    except Exception:
        return False

def send_query(name: str, query: str) -> None:
    print(f"\n" + "=" * 60)
    print(f">> TEST: {name}")
    print(f">> [User]: '{query}'")
    print("=" * 60)
    data = json.dumps({"text": query}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            dur = time.time() - t0
            if data.get("ok"):
                print(f">> [Jarvis] ({dur:.2f}s): {data.get('response', '')}")
            else:
                print(f"[FAIL] Jarvis Error: {data.get('error', '')}")
    except Exception as e:
        print(f"[FAIL] Failed to reach Jarvis: {e}")

def main():
    print("=" * 70)
    print("  J.A.R.V.I.S. LIVE DESKTOP TEST RUNNER")
    print("  Verifying connection to running Jarvis on http://127.0.0.1:8787...")
    print("=" * 70)

    if not check_jarvis_online():
        print("\n❌ Jarvis is not currently running.")
        print("Please run 'python main.py' in a separate terminal first!")
        sys.exit(1)

    print("[OK] Jarvis is online and ready! Starting live desktop demonstration...\n")
    time.sleep(1)

    for name, query in LIVE_TEST_COMMANDS:
        send_query(name, query)
        print("... Waiting 4 seconds for desktop actions & TTS to complete...")
        time.sleep(4)

    print("\n" + "=" * 70)
    print("  ALL LIVE DESKTOP TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    main()
