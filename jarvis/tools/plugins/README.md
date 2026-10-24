# Jarvis Custom Tool Plugins

Any Python script placed in this `plugins/` directory is **automatically discovered and loaded** when Jarvis starts!

## How to add a new tool:
Simply create a `.py` file (e.g. `my_tool.py`) and use the `@register_tool` decorator:

```python
from jarvis.tools.registry import register_tool

@register_tool(
    name="my_custom_action",
    description="Explain what this tool does clearly so the AI knows when to call it.",
    category="custom"
)
def my_custom_action(arg1: str, count: int = 1) -> str:
    # Your custom Python or Windows logic here
    return f"Executed with {arg1} {count} times!"
```

## How to remove a tool:
Simply delete or rename the `.py` file, or comment out the `@register_tool` decorator.
Jarvis will automatically update its registered tools and LLM prompt schemas on next boot!
