"""
J.A.R.V.I.S. — Procedure / Recipe Tools
Teach, list, delete, and run named multi-step routines. Running a routine
replays each stored sub-command through the normal command router.
"""
from __future__ import annotations

from loguru import logger

from jarvis.tools.registry import register_tool
from jarvis.memory.procedures import procedure_memory, normalize_name


@register_tool(
    name="save_procedure",
    description="Save a named routine of multiple steps so it can be run later with one phrase. Example: name='work setup', steps='open vs code, open brave, set volume to 30'.",
    category="memory",
)
def save_procedure(name: str, steps: str) -> str:
    """Store a multi-step routine under a name."""
    n = normalize_name(name)
    count = procedure_memory.save(name, steps)
    if count == 0:
        return "I need a name and at least one step to save a routine, Sir."
    return f"Saved your '{n}' routine with {count} step{'s' if count != 1 else ''}, Sir."


@register_tool(
    name="list_procedures",
    description="List the names of all saved routines/procedures.",
    category="memory",
)
def list_procedures() -> str:
    """List saved routine names."""
    names = procedure_memory.all_names()
    if not names:
        return "You don't have any saved routines yet, Sir."
    return "Your saved routines: " + ", ".join(names) + "."


@register_tool(
    name="delete_procedure",
    description="Delete a saved routine/procedure by name.",
    category="memory",
)
def delete_procedure(name: str) -> str:
    """Delete a saved routine."""
    n = normalize_name(name)
    if procedure_memory.delete(name):
        return f"Deleted your '{n}' routine, Sir."
    return f"I couldn't find a routine called '{n}', Sir."


@register_tool(
    name="run_procedure",
    description="Run a saved routine by name, executing each of its steps in order.",
    category="process",
)
async def run_procedure(name: str) -> str:
    """Replay each step of a saved routine through the command router."""
    n = normalize_name(name)
    steps = procedure_memory.get(name)
    if not steps:
        return f"I couldn't find a routine called '{n}', Sir."

    # Import lazily to avoid a circular import at module load.
    from jarvis.tools.router import ToolRouter

    router = ToolRouter()
    done, skipped = 0, []
    for step in steps:
        try:
            result = await router.try_fast_path(step)
            if result:
                done += 1
            else:
                skipped.append(step)
        except Exception as e:
            logger.warning(f"Procedure step '{step}' failed: {e}")
            skipped.append(step)

    msg = f"Ran your '{n}' routine — completed {done} of {len(steps)} steps"
    if skipped:
        msg += f". I couldn't handle: {', '.join(skipped)}"
    return msg + ", Sir."
