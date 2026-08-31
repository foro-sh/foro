# Speaking as the user

A view can put a message into the conversation as if the user typed it. It is
the right call for exactly one shape: the user clicked something that only
makes sense as a question to the model.

```tsx
import { getAdaptor } from "@foro/app"

<button onClick={() => getAdaptor().sendFollowUpMessage(
  `Tell me more about the weather in ${city} this evening.`
)}>Ask about this</button>
```

There is no hook for it, because it is not state a component reads. Reach for
`getAdaptor()` here and nowhere else you have an alternative.

## When not to

- **After every interaction.** A view that narrates each click into the
  conversation is unusable, and every message costs a model turn.
- **To tell the model what changed.** That is `useViewState()`, which updates
  the picture without spending a turn. See `view-state.md`.
- **To fetch data.** Call the tool.
- **Without the user asking.** A message the user did not initiate reads as the
  interface talking behind their back. Put it behind a control they press.

## Write it as the user would

The text lands in the transcript attributed to the user, so write it in their
voice, in the first person, naming the thing on screen: "Tell me more about the
weather in Utrecht this evening", not "The user has requested additional
forecast detail for the selected location."

## Where it goes

Under an ext-apps host the message is a `ui/message` request. On the foro Apps
tab there is no model, so the request is logged instead of answered, and the
bridge log shows you exactly what would have been said. Chat is where you see
it actually take effect.
