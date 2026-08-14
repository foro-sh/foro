# Wiring the view to the tools (FastMCP)

The server declares two things: a resource that returns the view's HTML, and
one or more tools that point at that resource.

```python
from pathlib import Path
from fastmcp.apps import AppConfig, ResourceCSP, app_config_to_meta_dict

CARD = "ui://views/card"
card_app = AppConfig(resource_uri=CARD)

CARD_HTML = Path(__file__).parent / "views/dist/card.html"

@mcp.resource(CARD, meta={"ui": app_config_to_meta_dict(AppConfig(csp=ResourceCSP()))})
def card_view() -> str:
    return CARD_HTML.read_text()

@mcp.tool(app=card_app)
def show_card(city: str) -> Weather: ...

@mcp.tool(app=card_app)
def refresh_card(city: str) -> Weather: ...
```

Notes that save an hour each:

- A `ui://` resource already defaults to the mime type MCP Apps expects
  (`text/html;profile=mcp-app`). You do not pass `mime_type=`.
- The URI is the identity of the view. Keep `ui://views/<name>` in step with
  `views/<name>.tsx`, and change both together or neither.
- `app=` on the tool is what writes `_meta.ui.resourceUri`. A tool without it
  returns JSON like any other tool, which is the right answer for tools the
  view does not render.
- The CSP half of the config belongs on the **resource**, the `resource_uri`
  half on the **tools**. See `blank-frame.md` before you declare anything.

## Several tools, one URI

Every tool that carries the same `resource_uri` is part of the same view. The
host groups them, and the view calls whichever it needs at runtime through
`useCallTool()`. This is the normal shape, not an advanced one: a list view
that can add, complete and delete is three tools and one URI.

Resist a second view for a variation of the first. Two URIs mean two documents
to build, ship and keep in step.

## What the tools return

The view renders `structuredContent`, so give the tools an output shape worth
rendering: the fields the component needs, named the way the component reads
them, and nothing the user will never see. A tool that returns a wall of text
for a human to read makes a poor view input, even when it makes a fine tool.

Tool count, descriptions and schema size are a standing cost on every request
whether the view is open or not. `design-mcp-tools` covers that; it applies
unchanged here, because these are ordinary tools that happen to have a UI.
