---
name: wrap-an-http-api
description: Build MCP tools on top of an existing HTTP API from its real contract instead of from memory. Use when the user wants an MCP server that wraps, calls or exposes a third-party or internal REST/HTTP API (a weather service, a SaaS product, their own backend), names an API to build on, or when tools that call an upstream API return 404s or unexpected shapes.
---

# Wrap an HTTP API

## The one failure that matters

**Writing the client from memory.** You probably know roughly what the API
looks like, and roughly is the problem: a path from an older version, a
renamed parameter, the key in the wrong header. The server still starts, the
deploy goes green, the tools list fine, and every call 404s at runtime.
Nothing before a real request catches it.

So every path, parameter and auth header a tool uses must come from the API's
own description, from docs the user gave you, or from a response you actually
saw. Get the contract first, trying these sources in order.

## 1. Ask for the base URL, then look for a spec yourself

Ask the user for the API's base URL, and which product or version if the
provider has several. Don't ask them to hunt for a spec: many APIs describe
themselves, and checking takes seconds.

```bash
base=https://api.example.com/v1
for p in openapi.json swagger.json openapi.yaml v3/api-docs .well-known/api-catalog ""; do
  curl -sS -o /dev/null -w "%{http_code} %{content_type}  /$p\n" \
    -H "Accept: application/json" "$base/$p"
done
```

Try the host root too, not only the versioned base. Then read the codes:

- **200 with JSON or YAML**: that's the spec. Save it (step 4).
- **401 or 403**: the path may exist behind auth. Retry with the key before
  concluding there's no spec. Some APIs serve the spec openly and lock
  everything else; others lock the spec too.
- **404**: not there.

The empty path is the landing document. OGC APIs such as EDR link their spec
from it: follow the link with `"rel": "service-desc"`.

## 2. No spec: ask for the reference docs

Ask the user to paste the API reference for the endpoints they need: paths,
parameters, auth, an example response. One message holds roughly 16,000
characters, so ask for those endpoints, not the whole site. Save what they
paste to `.foro/specs/<api>-docs.md` so it outlives the conversation.

## 3. Neither: probe the live API, and say so

With no spec and no docs, the API itself is the only source left. Once the key
is in `.env`, make one small real request per endpoint you mean to wrap and
read the shape off the response. Tell the user plainly that this is what's
happening: the contract is being inferred from live responses, so anything the
samples didn't show (errors, pagination, optional fields) is a guess until seen.

## 4. Query the spec with jq, never read it whole

Specs are big: KNMI's EDR spec is over half a megabyte. Save it under
`.foro/specs/` (add `.foro/` to `.gitignore` if it isn't there) and pull out
only what the next decision needs. YAML only? Convert it to JSON once.

```bash
mkdir -p .foro/specs && curl -fsS "$base/openapi.json" -o .foro/specs/api.json
spec=.foro/specs/api.json

# servers and auth
jq '{servers, security, schemes: .components.securitySchemes}' "$spec"

# every operation, one line each: grep this list, don't read it
jq -r '.paths | to_entries[] | .key as $p | .value | to_entries[]
  | select(.key | IN("get","post","put","patch","delete"))
  | "\(.key | ascii_upcase) \($p)  \(.value.summary // "")"' "$spec"

# one operation in full, then a schema it references (Swagger 2: .definitions)
jq '.paths["/items/{id}"].get' "$spec"
jq '.components.schemas.Item' "$spec"
```

## 5. Wire it up

- **The key is a secret.** Locally it lives in `.env`, which is never
  committed. Deployed, it's set in the foro.sh dashboard's Secrets tab. Read it
  from the environment at call time (`foro.secret("NAME")` in Python).
- One tool per distinct job, not one per endpoint, and return what the model
  needs rather than the whole upstream payload. `design-mcp-tools` covers both.

## Done when

- Every path, parameter and header the tools send can be pointed to in
  `.foro/specs/` or in a response you saw.
- Each tool has returned real data from the real API at least once, locally,
  with the real key. A tool that has only ever been listed is untested.
