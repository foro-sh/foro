# Secrets and sessions stay on the server

The view is shipped to whoever opens the conversation. Anything in the bundle
is readable: an API key in `views/card.tsx` is an API key in
`views/dist/card.html`, committed to the repo and served to every user.

The rule is short. **The view holds no credential. The server holds all of
them.** If a screen needs data behind a key, it calls a tool, and the tool
reads the key from the environment foro injects at runtime.

```python
import os

@mcp.tool(app=card_app)
def load_card(city: str) -> Weather:
    return fetch_weather(city, api_key=os.environ["KNMI_API_KEY"])
```

Secrets are added in the foro dashboard, encrypted at rest, and never committed
to the repo. `deploy-to-foro` covers adding them.

## Why an OAuth flow in the view will not work

The sandbox has no stable origin. That breaks the mechanisms browser auth is
built on, in ways that are worth knowing before you design around them:

- **No redirect URI to register.** The frame's origin is opaque, so there is no
  `https://something` you can put in a provider's allowlist.
- **No cookies, no storage.** Nothing survives to hold a session in, and a
  token kept in memory dies with the frame.
- **No allowlisting by origin.** An API that gates on `Origin` sees an opaque
  value shared by every sandboxed frame on the page.

So a view never authenticates a user. Either the server holds a service
credential (the common case), or per-user auth is a property of the deployed
server rather than of the view.

## Do not use the view as a trust boundary

Whatever the view sends, a tool can receive from anywhere. Validate arguments
in the tool: an id the view read out of its own state is still an id from a
client. Hiding a button is a UI decision, never an access control one.
