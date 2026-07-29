---
name: design-mcp-tools
description: Design the tools an MCP server exposes so they are cheap for a model to carry and easy for it to call correctly. Use when writing or reviewing MCP tool definitions, when a server's schema cost or token usage looks high in the foro.sh dashboard, when deciding how many tools to expose or how to shape their parameters, or when tools exist but the model keeps calling the wrong one.
---

# Design MCP tools that don't cost more than they're worth

A tool charges an LLM's context twice, and only one of those is obvious.

**It charges once per call** — arguments up, result back. Expected.

**It also charges on every single request, called or not.** Completion APIs are
stateless, so the client resends the full tool list each time: every name, every
description, every line of JSON Schema. Ten verbose tools are a standing tax on
every message in the conversation, including the ones that use none of them.

That second cost is invisible while you write the server and permanent once
it's deployed. Design against it up front.

`foro-docs.read_doc("tokens")` has the full economics — how both figures are
counted, which tokenizer, and why they're a ruler rather than an invoice. Read
it if the user wants the numbers justified. This skill is the procedure.

## Write the description for a model, not a reader

Descriptions dominate the schema cost, because they're prose and prose
tokenizes like prose. They're also the only thing that makes a model pick the
right tool, so this is not "make them short" — it's "make every token earn its
place."

- State what the tool does and **when to reach for it**. That is what the model
  is choosing on.
- Cut anything the model can't act on: implementation notes, changelog asides,
  "this uses the v2 endpoint", politeness.
- Don't restate the parameter list in prose. The schema already carries it, and
  saying it twice pays for it twice.
- If two tools are easy to confuse, spend tokens on the *distinction* — that's
  the highest-value sentence in either description.

## Keep the parameter surface small

Braces, quotes, colons, and long `snake_case` names are all real tokens; a
schema is not free structure around your description.

- Short but unambiguous parameter names.
- Flat over nested. Deep objects cost their whole shape on every request.
- **Enums are the sharp edge.** Forty allowed values cost forty values on every
  request forever. If the set is large or changes, take a string and validate
  inside the tool — you keep the error message, you stop paying for the list.
- Mark optional things optional; don't invent parameters nobody sends.

## Resist splitting one tool into five

The most expensive mistake is a proliferation of near-duplicates —
`get_user_by_id`, `get_user_by_email`, `get_user_by_name` — which multiplies the
standing cost while the useful work stays identical. One tool with a clear
parameter is cheaper and easier for a model to choose.

Split when the tools genuinely differ in what they *do* or in their side
effects. Don't split to avoid a parameter. And a tool nobody has called in
weeks is still charging you on every request: the Tools tab shows which those
are, and deleting one is the biggest single saving available.

## Bound what a tool returns

Result size is per-call cost, and the platform enforces its own ceilings, so an
unbounded tool is both expensive and untestable:

- Responses over roughly 1 MB are truncated rather than returned whole.
- A call gets 60 seconds total, and 10 seconds of silence before it's treated as
  stuck.

Return what the model needs, not the whole upstream payload. Paginate or take a
`limit`. A tool that dumps a full API response makes the model pay for fields it
will never read.

## Verify with the real numbers

Do not guess at any of this. Once the server is deployed, the dashboard measures
it:

- **Playground** — each tool's schema cost, and its share of the server's total.
  That share is how you pick which tool is worth trimming before you start.
- **Tools tab** — schema tokens per tool alongside call counts, p95 latency, and
  errors.
- **Metrics** — tokens and tokens per call, the other half of the picture.

Trim the biggest share first, redeploy, compare. One caveat worth passing on:
these figures come from one fixed tokenizer, so they're built for comparing
tools against each other and this week against last week — not for reconciling
against a provider's bill.

## Done when

- Every description says when to use the tool, and near-duplicate tools say how
  they differ from each other.
- No large enum is riding in the schema when validation inside the tool would do.
- Tool count reflects distinct work, not parameter avoidance.
- Results are bounded.
- The claim that it's better is backed by the Playground's numbers, not by
  having followed this list.
