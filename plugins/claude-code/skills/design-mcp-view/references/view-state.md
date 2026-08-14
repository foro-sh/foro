# View state, and what the model is allowed to know

## Never `localStorage`

Not as a fallback, not "just for the draft". The sandbox has no stable origin,
so storage APIs are either unavailable or scoped to something that will not be
there next time. Code that reaches for them fails in a way that reads like a
browser bug.

```tsx
import { useViewState } from "@foro/app"

const [state, setState] = useViewState<{ selected: string[] }>()
await setState({ selected: [...(state?.selected ?? []), id] })
```

`useViewState()` keeps the snapshot and tells the model about it in the same
call. Under a host that restores state itself, the value comes back on the next
mount; under foro's sandbox it does not survive a remount, and that is correct
rather than a bug to work around.

## Three tiers, and picking the right one

| What | Where it goes | Survives |
| --- | --- | --- |
| Which row is expanded, a hover, a half-typed filter | React state | nothing |
| What the user selected or changed, which the model must know | `useViewState()` | the conversation |
| Anything another session, user or tool must see | a tool call to the server | everything |

The middle row is the one people skip, and skipping it produces the classic
failure: the user picks three items in the view, sends a message, and the model
answers as if nothing happened, because nothing told it. `useViewState()` is
what closes that gap.

The bottom row is a write, so it is a tool. A view has no database.

## Keep the model's copy small

Whatever you pass to `setState` is what the model reads, so send the decision,
not the render tree: `{ selected: ["a", "b"] }` rather than the whole list with
a flag on each row. The model pays for it on the next message either way, and
a large blob buries the one fact that mattered.

Updating context does not send a message or trigger a reply. It changes what
the next message is answered against. If you want the model to actually say
something, that is `follow-up.md`.
