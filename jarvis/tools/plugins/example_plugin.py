"""
Example custom plugin for J.A.R.V.I.S.
Drop any .py file into jarvis/tools/plugins/ and it will be dynamically loaded!
"""
from jarvis.tools.registry import register_tool


@register_tool(
    name="open_website",
    description="Open any website or URL in the default browser.",
    category="web"
)
def open_website(url: str) -> str:
    """Open any website or URL in the default browser."""
    import webbrowser
    target = url if url.startswith("http") else f"https://{url}"
    webbrowser.open(target)
    return f"Opened {target} in browser."
