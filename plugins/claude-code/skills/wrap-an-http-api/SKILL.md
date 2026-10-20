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

In the foro.sh builder there is no `curl`: call `fetch_url` on each candidate
instead. A 2xx is saved to `.foro/specs/` already, whatever its type, so check
the `contentType` it returns; anything else comes back as an error naming the
status. `fetch_url` sends no headers, so one that needs an `Accept` goes
through `run_command` with the interpreter instead: `urllib.request` in
`python3`, `fetch` in `node`. Builder commands get no secrets, so there is no
key to retry a 401 or 403 with: ask the user for the spec or the docs (step 2),
and never write the key into the workspace, where a commit would carry it.

Try the host root too, not only the versioned base. Then read the codes:

- **200 with JSON or YAML**: that's the spec. Save it (step 4).
- **401 or 403**: the path may exist behind auth. Retry with the key before
  concluding there's no spec. Some APIs serve the spec openly and lock
  everything else; others lock the spec too.
- **404**: not there.

The empty path is the landing document. OGC APIs such as EDR link their spec
from it: follow the link with `"rel": "service-desc"`. Add `?f=json` if the
landing document comes back as HTML.

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

## 4. Query the spec, never read it whole

Specs are big: KNMI's EDR spec is over half a megabyte. Save it under
`.foro/specs/` (add `.foro/` to `.gitignore` if it isn't there) and pull out
only what the next decision needs. YAML only? Convert it to JSON once, since
neither interpreter reads YAML on its own:
`uv run --no-project --with pyyaml python -c 'import json,sys,yaml; json.dump(yaml.safe_load(open(sys.argv[1])), sys.stdout, default=str)' .foro/specs/api.yaml > .foro/specs/api.json`
or `npx -y js-yaml .foro/specs/api.yaml > .foro/specs/api.json`.

- **In the foro.sh builder:** `fetch_url` saves it there and returns the path.
- **Locally:** `mkdir -p .foro/specs && curl -fsS "$base/openapi.json" -o .foro/specs/api.json`

Query it with the project's own interpreter. It's there locally and in the
builder's dev container; `jq` and `curl` aren't in the container, and `jq`
may not be on a developer's machine either. Every builder command runs in a
fresh shell, so set `spec` to the path `fetch_url` returned in the same
command as the query.

```bash
spec=.foro/specs/api.json

# servers and auth (host, basePath and securityDefinitions are Swagger 2's)
python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(json.dumps({k: v for k, v in s.items() if k in ("servers", "host", "basePath", "schemes", "security", "securityDefinitions")} | {"securitySchemes": s.get("components", {}).get("securitySchemes")}, indent=2))' "$spec"

# every operation, one line each: grep this list, don't read it
python3 -c 'import json,sys
for p, ops in json.load(open(sys.argv[1]))["paths"].items():
    for m, op in ops.items():
        if m in ("get", "post", "put", "patch", "delete"): print(m.upper(), p, "", op.get("summary", ""))' "$spec"

# one operation in full, then a schema it references (Swagger 2: "definitions")
python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["paths"]["/items/{id}"]["get"], indent=2))' "$spec"
python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["components"]["schemas"]["Item"], indent=2))' "$spec"
```

The same in a Node project:

```bash
node -e 'const s = JSON.parse(require("fs").readFileSync(process.argv[1])); console.log(JSON.stringify({...Object.fromEntries(Object.entries(s).filter(([k]) => ["servers", "host", "basePath", "schemes", "security", "securityDefinitions"].includes(k))), securitySchemes: s.components?.securitySchemes}, null, 2))' "$spec"

node -e 'for (const [p, ops] of Object.entries(JSON.parse(require("fs").readFileSync(process.argv[1])).paths))
  for (const [m, op] of Object.entries(ops))
    if (["get", "post", "put", "patch", "delete"].includes(m)) console.log(`${m.toUpperCase()} ${p}  ${op.summary ?? ""}`)' "$spec"

node -e 'console.log(JSON.stringify(JSON.parse(require("fs").readFileSync(process.argv[1])).paths["/items/{id}"].get, null, 2))' "$spec"
node -e 'console.log(JSON.stringify(JSON.parse(require("fs").readFileSync(process.argv[1])).components.schemas.Item, null, 2))' "$spec"
```

Where `jq` is installed it does the same in less typing, e.g.
`jq '.paths["/items/{id}"].get' "$spec"`.

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
