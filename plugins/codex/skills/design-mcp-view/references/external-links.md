# Links leave through the host

A sandboxed view cannot navigate. An `<a href>` that tries to open a tab, a
`window.open`, a `location.assign`: all blocked, and all fail quietly enough
that people assume the click handler never ran.

```tsx
import { useOpenExternal } from "@foro/app"

const openExternal = useOpenExternal()

<button onClick={() => openExternal(item.url)}>Open on the site</button>
```

The host decides what happens next. It may open the link, or show it and let
the user click, which is what the foro Apps tab does: the URL appears in the
bridge log for a person to follow, never followed on the view's say so. Do not
treat the promise resolving as proof a tab opened.

## Make it look like a link

You are rendering a button that behaves like a link, so keep the affordance:
show the destination host somewhere the user can read it before they commit.
A view is tenant code inside somebody's chat client, and a link whose target is
invisible is the thing a careful user will not click.

## What not to do

- No `target="_blank"` as a fallback path. It does not work, and having both
  makes the failure inconsistent instead of absent.
- No `mailto:` or custom scheme by navigation. Same route, same rule.
- Do not use a link where a tool call belongs. Sending the user out to a web
  page to do something your server could do is a worse product than a second
  tool.
