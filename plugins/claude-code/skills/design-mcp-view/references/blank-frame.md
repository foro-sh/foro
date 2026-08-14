# The frame is blank

Nearly always the content policy. The view runs under a policy built from what
the resource declared, and every directive it did not declare is denied. An
omitted origin is not a warning, it is a blocked request, and a blocked script
renders nothing at all.

**foro's `/docs/apps` is the reference for what is denied and how to declare
it: https://foro.sh/docs/apps.** It is kept in step with the platform code that
builds the policy, so read it there rather than trusting a copy in a skill.

## Work the list in this order

1. **Is the built file current?** `views/dist/<name>.html` is what the server
   returns. If you edited the `.tsx` and did not rebuild, you are looking at
   the previous view working exactly as before.
2. **Does the resource URI match?** The tool's `_meta.ui.resourceUri` and the
   `@mcp.resource` URI have to be the same string. A typo shows up as a view
   that never mounts rather than as an error.
3. **Open the browser console for the frame.** A blocked resource says so in
   as many words, naming the directive and the origin. This is the fastest
   answer available and people skip it.
4. **Did you declare every origin the view loads?** A bundled view usually
   declares nothing, because its script is inlined, right up until it pulls a
   font, an image or an analytics script from somewhere.
5. **Is anything being fetched at runtime?** Network is denied by default. Move
   it into a tool.

## A bundled view has less to declare, not more

This is the practical reason to build one file rather than load React from a
CDN: with the runtime and your code inlined there is no script origin to
declare, so the most common cause of a blank frame cannot happen. Add an origin
only when you have added a dependency that needs one, and add it to the
resource's CSP at the same time.
