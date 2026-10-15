"""Node.js MCP server scaffold for `foro init`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from foro._manifest import DEFAULT_PORT, DEFAULT_RUNTIME_VERSIONS
from foro._proc import MissingToolError
from foro._proc import run as _run

_SERVER_JS = '''\
import {{ McpServer }} from "@modelcontextprotocol/sdk/server/mcp.js";
import {{ StreamableHTTPServerTransport }} from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express from "express";
import {{ z }} from "zod";

function createServer() {{
  const server = new McpServer({{ name: "{name}", version: "0.1.0" }});

  server.tool(
    "add",
    "Add two numbers",
    {{ a: z.number(), b: z.number() }},
    async ({{ a, b }}) => ({{
      content: [{{ type: "text", text: String(a + b) }}],
    }}),
  );

  return server;
}}

const app = express();
app.use(express.json());

// Stateless: one server + transport per request. Required by recent SDK
// releases, and matches how foro.sh probes /mcp.
const handleMcp = async (req, res) => {{
  const server = createServer();
  const transport = new StreamableHTTPServerTransport({{
    sessionIdGenerator: undefined,
  }});
  await server.connect(transport);
  await transport.handleRequest(req, res, req.body);
}};

app.post("/mcp", handleMcp);
app.get("/mcp", handleMcp);
app.delete("/mcp", handleMcp);

const port = Number(process.env.PORT || "{port}");
app.listen(port, "0.0.0.0", () => {{
  console.log(`foro.sh · MCP server listening on http://0.0.0.0:${{port}}/mcp`);
}});
'''

_README = '''\
# {name}

An MCP server for Node.js {node_version}, deployable on [foro.sh](https://foro.sh).

## Structure

- `server.js` — entrypoint (`package.json` `main`); serves streamable HTTP on `$PORT`
- `add` tool — example tool; replace it with your own

## Run locally

```bash
npm install   # once
npm start     # or: PORT={port} node server.js
```

Or with the foro CLI (runs the server the same way foro.sh will):

```bash
uv tool install foro   # once, or: uvx foro …
foro dev
```

Copy `.env.example` to `.env` for local secrets. In production, set them as
Secrets in the foro.sh dashboard instead — `.env` is never deployed.

## Deploy

Push this repo to GitHub, then connect it from the foro.sh dashboard, or run
`foro deploy` after `foro auth login`.
'''

_GITIGNORE = """\
node_modules/
.env
.DS_Store
.foro/
npm-debug.log*
"""

_ENV_EXAMPLE = """\
# Copy to .env for local development - foro dev loads it automatically.
# Never commit the real .env; in production these are set as Secrets in
# the foro.sh dashboard instead.
#
# EXAMPLE_API_KEY=
"""


def package_json(name: str, runtime_version: str, port: int, entrypoint: str) -> dict:
    doc: dict = {
        "name": name,
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "main": entrypoint,
        "engines": {"node": f"^{runtime_version}"},
        "scripts": {
            "start": f"node {entrypoint}",
            "dev": f"node {entrypoint}",
        },
        "dependencies": {
            "@modelcontextprotocol/sdk": "^1.32.0",
            "express": "^5.0.0",
            "zod": "^3.24.0",
        },
    }
    foro: dict = {}
    if runtime_version != DEFAULT_RUNTIME_VERSIONS["node"]:
        foro["runtime_version"] = runtime_version
    if port != DEFAULT_PORT:
        foro["port"] = port
    if foro:
        doc["foro"] = foro
    return doc


def write_files(
    dir_path: Path,
    *,
    name: str,
    runtime_version: str,
    port: int,
    entrypoint: str,
    write,
) -> None:
    write(
        dir_path / "package.json",
        json.dumps(package_json(name, runtime_version, port, entrypoint), indent=2) + "\n",
    )
    write(
        dir_path / entrypoint,
        _SERVER_JS.format(name=name, port=port),
    )
    write(
        dir_path / "README.md",
        _README.format(name=name, node_version=runtime_version, port=port),
    )
    write(dir_path / ".gitignore", _GITIGNORE)
    write(dir_path / ".env.example", _ENV_EXAMPLE)


def install_deps(dir_path: Path) -> None:
    try:
        _run(["npm", "install"], cwd=dir_path, check=True)
    except MissingToolError as err:
        raise RuntimeError(
            f"{err}. A scaffolded Node project is locked with `npm`, and "
            "foro dev runs it with `node`."
        ) from None
    except subprocess.CalledProcessError as err:
        raise RuntimeError(
            f"`npm install` failed in {dir_path}:\n{(err.stderr or '').strip()}"
        ) from None


def cleanup_partial(dir_path: Path) -> None:
    (dir_path / "package-lock.json").unlink(missing_ok=True)
    import shutil

    shutil.rmtree(dir_path / "node_modules", ignore_errors=True)
