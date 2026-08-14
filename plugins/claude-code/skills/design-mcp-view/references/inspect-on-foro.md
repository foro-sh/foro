# Drive the view on foro before calling it done

Order matters here: build, run the server, deploy, then drive it. Each step
catches a different class of failure and the later ones are slower.

## 1. Build, and run the Python server locally

```
npm run build:views
uvx foro dev
```

`build:views` regenerates `views/dist/*.html`. `foro dev` runs the server the
way the container will, which is the cheap way to catch a tool that raises
before you spend a deploy on it. Local is a real MCP server, so tools answer,
but no host renders the view: this step proves the server, not the interface.

## 2. Deploy

Commit the `.tsx` and its built `.html` together, then hand off to
`deploy-to-foro`. Secrets go in the dashboard, never the repo.

## 3. The Apps tab is the workshop

Open the project, then Apps. It lists each view with the tools attached to it,
and it is the only surface that shows you both halves of the conversation the
view is having:

- **The frame** renders the real built document under the real policy.
- **Mount with a tool result** runs one of the attached tools and mounts the
  view carrying its result, which is how a host does it in production. A cold
  mount, with no result, is useful for poking at layout and will look empty for
  a view that renders only from its tool result. That is correct, not a bug.
- **The bridge log** lists every call the view makes with arguments, result and
  timing, plus what it told the model and any link it asked to open. This is
  the half you otherwise debug blind.
- **Reload** re-reads the resource from the server, so a rebuild and redeploy
  shows up without leaving the tab.

Check while you are there: toggle the dashboard theme and watch the view follow
it, and confirm the log shows the calls you expected and nothing you did not.

## 4. Chat is the rehearsal

Chat mounts views the way production does: the model calls a tool, the view
appears under the result. It is where a follow-up message actually reaches a
model, and where you find out whether the model and the view agree about what
is on screen.

## 5. One other host

The point of building on `@foro/app` is that the same file runs elsewhere.
Before you call the view finished, load it in ChatGPT or Claude too. Anything
that only works on foro is a bug in the view, not a difference between hosts.

## When something is wrong

- Blank frame: `blank-frame.md`.
- A call in the log with an error: read the arguments in the log first, then
  the tool. Most are the view sending a field the tool does not take.
- Nothing in the log at all: the view never connected. Rebuild, redeploy,
  reload, and check the browser console for the frame.
