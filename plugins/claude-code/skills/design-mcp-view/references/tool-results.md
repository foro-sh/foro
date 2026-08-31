# Reading the result, and calling more tools

## The view renders what it was handed

A host mounts a view carrying the result of the tool that triggered it. That
arrives as a notification, not as a fetch, so the view never asks for its first
payload:

```tsx
import { useToolInfo } from "@foro/app"

export default function Card() {
  const { input, structuredContent, pending } = useToolInfo()
  if (pending || !structuredContent) return <Skeleton />
  const weather = structuredContent as Weather
  return <article>{weather.summary}</article>
}
```

- `structuredContent` is the tool's structured output, the field you render.
- `input` is the arguments the tool was called with, useful for a heading
  ("Weather in Utrecht") without a second lookup.
- `pending` is true between the call starting and its result arriving.
- `_meta` carries anything the server attached out of band.

A view that renders only from its own `fetch` looks broken on a cold mount and
empty in production. If you find yourself reaching for `fetch`, the answer is
almost always a tool call.

## Calling another tool

```tsx
import { useCallTool } from "@foro/app"

const { call, pending, error } = useCallTool("complete_task")

<button disabled={pending} onClick={() => call({ id: task.id })}>Done</button>
{error ? <p role="alert">{error.message}</p> : null}
```

The call goes to the host, which calls your server: the same rate limit,
scrubbing and timeouts as any other call, and the same 60 second ceiling. The
host shows it in the bridge log with its arguments, result and duration.

Three rules that keep this from going wrong:

1. **Render `pending` and `error`.** A view that swallows a failed call leaves
   the user clicking a button that does nothing.
2. **Do not poll.** An app that calls itself into the rate limit is a bug its
   author has to see, and the log will show it happening.
3. **Never `fetch` an origin the resource did not declare.** It is blocked, and
   the failure looks like your code. If the data lives behind an API, the
   server fetches it inside a tool, where the key is.

## After the call

The result of `call()` is the tool result, so update your own state from it
rather than calling a second "get" tool to find out what changed. If the change
is something the model should know about, that is `view-state.md`.
