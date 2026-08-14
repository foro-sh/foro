# Display mode and layout are the host's call

A view does not own its frame. It asks, and a host answers with what it is
willing to give.

```tsx
import { useDisplayMode, useLayout } from "@foro/app"

const [mode, requestMode] = useDisplayMode()
const { theme, maxHeight, safeArea } = useLayout()
```

## Ask, then read the answer

```tsx
const granted = await requestMode("fullscreen")
if (granted !== "fullscreen") { /* stay inline, and mean it */ }
```

`requestMode` resolves to the mode the host actually set, which is frequently
not the one you asked for. The foro Apps tab answers `inline` and says so up
front, because it is one pane of a dashboard rather than a canvas to hand over.
The request still shows in the bridge log, so you can see the ask arrived.

A view that assumes its request was granted, or that reads its own intent back
out of local state instead of the answer, renders a fullscreen layout inside an
inline box. That is the single most common layout bug here.

## Design inline first

Inline is the mode every host offers, so it is the one that has to look
finished. Treat fullscreen as an enhancement behind a control, not as the
layout you build and then squeeze.

## Read the layout, do not measure the window

- `theme` is `"light"` or `"dark"` and follows the host live, so paint from it
  rather than from `prefers-color-scheme`. Toggling the theme in the foro
  dashboard is the fastest way to prove you did.
- `maxHeight` is the tallest the host will let the frame grow. Scroll inside it
  rather than growing past it.
- `safeArea` is zeroed on desktop and real on mobile hosts. Pad with it instead
  of hardcoding a gap that is wrong in one of the two.

All three arrive at mount and again whenever they change, and all three have
safe defaults before the host has said anything, so a view still renders in a
plain browser tab while you are working on it.

## Size

The runtime reports the document's size to the host as it changes, so you do
not call anything to resize. The host clamps what it grants, which is why
`maxHeight` exists: a view cannot push the rest of the page off screen by
asking for more.
