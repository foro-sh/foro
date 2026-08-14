---
name: design-mcp-view
description: Design and build a React view that an MCP server returns instead of raw JSON, so a tool renders as an interface inside ChatGPT, Claude, or the foro Apps tab. Use when the user wants UI from their MCP server, mentions an MCP App, a widget, a view, or a card in the chat, when a tool result would read better as an interface than as text, or when a view they wrote renders blank or only works in one host.
---

# Design an MCP view that runs in every host

An MCP server can answer with an interface. A tool points at a `ui://`
resource, the host reads that resource and runs it in a sandboxed iframe next
to the conversation, and the iframe talks back over JSON-RPC: calling more
tools, telling the model what is on screen, opening links.

The split that matters, and the one people get backwards:

**Python is the server. React is the view.** The server keeps the data, the
secrets and the tools. The view is one HTML document that renders a tool result
and calls tools back. It has no database, no API key, and no server of its own.

Everything below assumes FastMCP on the server and `@foro/app` in the view.
Both halves ship from the same repo and deploy together.

## Start with the flows, not the component

An MCP view is not a page. It is the visible half of a conversation that the
model is also participating in, so the first question is what the user does
here that they could not do by reading text. Write that down before any code:
`references/intent.md`.

## One view, several tools

The common mistake is one tool with a UI attached. A view is a resource plus
every tool that points at it, so five tools can drive a single list: add,
complete, delete, reopen, list. That mapping lives in each tool's
`_meta.ui.resourceUri`, and the host groups them for you.

Name new views `ui://views/<name>`, matching `views/<name>.tsx` in the repo.
`references/views-and-tools.md` has the FastMCP side.

## The view is built before you push, never on deploy

```
views/card.tsx          your component, default-exported
views/dist/card.html    generated, committed, what Python returns
```

The bundle inlines React, the guest runtime and your code into one file, so a
view fetches no JavaScript when it renders. foro builds Python, not JavaScript:
there is no Node step in the image, so a forgotten build deploys the previous
view, silently and successfully. Add a `build:views` script to `package.json`
that bundles `views/*.tsx` into `views/dist/*.html`, run `npm run build:views`,
and commit the output with the code that produced it.

## What the view can and cannot reach

The iframe runs with scripts allowed and no same-origin access. That single
decision explains most of what surprises people:

- **No `localStorage`, no cookies, no stable origin.** Use `useViewState()` for
  state and keep anything that must persist on the server, behind a tool.
  `references/view-state.md`.
- **No network the resource did not declare.** An undeclared origin is a
  blocked request, and a blank frame is nearly always this.
  `references/blank-frame.md`.
- **No secrets.** An API key in a view is shipped to every user who opens it.
  Keys live in the foro dashboard and are read by the server.
  `references/sandbox-auth.md`.
- **Links open through the host**, not by navigating.
  `references/external-links.md`.

## Talking to the model

The view and the model are looking at the same thing and neither can see the
other's half. Two different acts, easy to confuse:

- **Update what the model knows** when the user changes something on screen, so
  the next message is not answered against a stale picture. `useViewState()`
  does this as a side effect of persisting.
- **Say something as the user** only when the user asked for it, typically from
  a button. `references/follow-up.md`.

Reading the tool result that mounted the view, and calling more tools from it,
are both in `references/tool-results.md`.

## Inline is a host decision

A view asks for fullscreen; the host answers. The foro Apps tab answers
`inline` today, and a view that assumes it got what it asked for will lay
itself out wrong. `references/host-display.md`.

## Prove it on foro before you call it done

Deploy, then drive it: the Apps tab renders the view with a real tool result
and logs every call it makes, and Chat mounts it the way a host does in
production. `references/inspect-on-foro.md`. Hand off to `deploy-to-foro` for
the deploy itself and to `design-mcp-tools` for what the tools cost.

## Done when

- The tools that drive the view all point at the same `ui://views/<name>`.
- `views/dist/<name>.html` is committed and current with `views/<name>.tsx`.
- The view renders from its tool result on a cold mount, not from a fetch it
  makes itself.
- Nothing in the view holds a secret, a key, or an origin-bound session.
- The Apps tab bridge log shows the calls you expected and no errors you did
  not.
- The same built file renders in one other host, not only in foro.
