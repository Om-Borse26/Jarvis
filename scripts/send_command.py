"""
J.A.R.V.I.S. — Interactive Text Command Sender
Sends text queries directly to the live running Jarvis instance (http://127.0.0.1:8787/api/chat),
executing the real pipeline (HUD, TTS speech, window movement, tool execution) exactly as if spoken by voice.

Usage:
    python scripts/send_command.py "Can you make brave full screen?"
    python scripts/send_command.py --interactive
"""
import sys
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

def send(query: str) -> None:
    print(f"\n[You]: {query}")
    data = json.dumps({"text": query}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                print(f"[Jarvis]: {data.get('response', '')}\n")
            else:
                print(f"[FAIL] Jarvis Error: {data.get('error', 'Unknown error')}\n")
    except urllib.error.URLError as e:
        print(f"[FAIL] Connection error ({ENDPOINT}): Is Jarvis running via 'python main.py'? ({e})")
    except Exception as e:
        print(f"[FAIL] Error: {e}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--interactive":
        print("=" * 60)
        print("  J.A.R.V.I.S. Interactive Console (Type 'exit' to quit)")
        print("=" * 60)
        while True:
            try:
                line = input("💬 Command > ").strip()
                if not line:
                    continue
                if line.lower() in ("exit", "quit", "q"):
                    break
                send(line)
            except (KeyboardInterrupt, EOFError):
                break
    else:
        query = " ".join(sys.argv[1:])
        send(query)

if __name__ == "__main__":
    main()
