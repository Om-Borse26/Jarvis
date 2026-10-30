"""Live feature battery: memory, vault, scheduler firing, access toggle, web fallback."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loguru import logger
logger.remove(); logger.add(sys.stderr, level="ERROR")

import jarvis.tools  # noqa
from jarvis.tools.registry import registry


async def call(name, **kw):
    r = await registry.execute(name, **kw)
    return r.get("result", r.get("message", r))


async def main():
    print("=== 1. MEMORY (remember / recall) ===")
    print(" save:", await call("save_user_memory", fact="User's favourite colour is teal"))
    print(" save:", await call("save_user_memory", fact="User prefers the Brave browser"))
    rec = await call("recall_user_memories", query="what colour does the user like")
    print(" recall:", rec)
    print(" -> teal remembered:", "teal" in str(rec).lower())

    print("\n=== 1b. MEMORY LAYERS ===")
    from jarvis.memory.working import working_memory
    from jarvis.memory.semantic import semantic_memory
    from jarvis.memory.episodic import episodic_memory
    working_memory.start_task("demo task")
    working_memory.add_observation("set_volume", {"percent": 30}, "done")
    print(" working task:", getattr(working_memory, "current_task", "?"))
    semantic_memory.add("User enjoys lo-fi music while coding", "preference")
    print(" semantic recall:", semantic_memory.recall("what music does the user like", k=2))
    try:
        episodic_memory.record("user asked to set volume", "set_volume", "done")
    except Exception as e:
        print(" episodic.record n/a:", e)
    try:
        print(" episodic recent:", episodic_memory.recent(3))
    except Exception as e:
        print(" episodic.recent n/a:", e)

    print("\n=== 2. VAULT (credentials) ===")
    print(" save:", await call("save_secret", name="demo_test_key", value="s3cr3t-value"))
    print(" list:", await call("list_secrets"))
    print(" check:", await call("check_secret", name="demo_test_key"))
    print(" delete:", await call("delete_secret", name="demo_test_key"))

    print("\n=== 3. SCHEDULER FIRING ===")
    from jarvis.core.scheduler import scheduler
    fired = []
    scheduler.notify_fn = lambda title, body="": fired.append(("notify", title, body))
    async def _spk(t): fired.append(("speak", t))
    scheduler.speak_fn = _spk
    jid = scheduler.add_job("once", "Drink water", time.time() + 1.0, None)
    print(f"  scheduled job {jid}, waiting to fire...")
    time.sleep(1.3)
    await scheduler._fire_due()
    print("  fired callbacks:", fired)
    print("  -> reminder fired:", any("Drink water" in str(x) for x in fired))

    print("\n=== 4. ACCESS TOGGLE enforcement ===")
    from jarvis.core.permissions import permission_policy
    permission_policy.set("web", False)
    r = await registry.execute("search_web", query="cats")
    print("  web OFF -> search_web:", r.get("status"), "|", r.get("message"))
    permission_policy.set("web", True)
    print("  web restored:", permission_policy.is_allowed("web"))

    print("\n=== 5. WEB ANSWER FALLBACK (no Tavily answer) ===")
    key = os.environ.pop("TAVILY_API_KEY", None)
    from jarvis.tools import knowledge
    knowledge.fact_memory  # ensure import
    # Force the no-key path so it must fall back to a web search.
    from jarvis.tools.knowledge import _tavily_answer
    print("  tavily (no key) ->", repr(_tavily_answer("obscure xyzzy question")))
    if key:
        os.environ["TAVILY_API_KEY"] = key


if __name__ == "__main__":
    asyncio.run(main())
