# Decide what the view is for before you build it

A view earns its place when reading the answer is not the same as using it.
Picking a date, comparing four options at a glance, toggling ten things without
ten sentences: those are views. A number, a yes or no, a paragraph: those are
tool results, and wrapping them in a card makes the conversation slower, not
richer.

## Write a short intent note in the repo

Two or three paragraphs in the repo, next to the code. Not a specification, not
a template to fill in, and not a document anybody signs off. It exists so the
next person, including the agent that picks this up in a month, can tell
whether a change is in scope.

Cover:

1. **The moment.** What has just happened in the conversation when this view
   appears? A view is always downstream of a tool call, so name the call.
2. **What the user does here.** The two or three actions worth a click. If the
   list is empty, you want a better tool result, not a view.
3. **What the model must still know.** Anything the user changes on screen that
   the next message would otherwise be answered against wrongly.
4. **What stays on the server.** The data, the keys, the writes. If an action
   needs any of them it is a tool call, not view logic.

## Sketch the flows, then the tools, then the component

In that order, because each one constrains the next:

- The flow says what actions exist.
- The actions say what tools exist, and several of them will share this one
  view.
- The tools' results say what the component renders, since the view renders
  what it is given rather than fetching for itself.

Going the other way, component first, is how you end up with a view that wants
data no tool returns and a tool nobody calls.

## Keep the first version small

One view, one screen, the actions from step 2 and nothing else. The Apps tab
shows every call the view makes and every message it sends the model, so
finding out what is missing takes minutes once it is live. Guessing at it up
front takes a week and is usually wrong.
