"""Rust MCP server scaffold for `foro init`.

foro.sh does not deploy Rust yet — this produces a locally runnable
streamable-HTTP MCP server. `foro check` / `foro dev` / `foro deploy` will
not accept a Cargo.toml-only project until the platform grows a Rust
runtime; the README documents `cargo run` instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from foro._proc import MissingToolError
from foro._proc import run as _run

_CARGO_TOML = '''\
[package]
name = "{crate_name}"
version = "0.1.0"
edition = "2021"
description = "MCP server scaffolded by foro init"
publish = false

[dependencies]
anyhow = "1"
axum = "0.8"
rmcp = {{ version = "3", features = ["server", "macros", "transport-streamable-http-server"] }}
schemars = "1"
serde = {{ version = "1", features = ["derive"] }}
tokio = {{ version = "1", features = ["full"] }}
tokio-util = "0.7"
tracing = "0.1"
tracing-subscriber = {{ version = "0.3", features = ["env-filter"] }}
'''

_MAIN_RS = '''\
use std::net::SocketAddr;

use anyhow::Result;
use rmcp::{{
    ErrorData as McpError, ServerHandler,
    handler::server::{{router::tool::ToolRouter, wrapper::Parameters}},
    model::*,
    tool, tool_handler, tool_router,
    transport::streamable_http_server::{{
        StreamableHttpServerConfig, StreamableHttpService,
        session::local::LocalSessionManager,
    }},
}};
use schemars::JsonSchema;
use serde::Deserialize;
use tracing_subscriber::EnvFilter;

#[derive(Debug, Deserialize, JsonSchema)]
struct AddArgs {{
    a: i32,
    b: i32,
}}

#[derive(Clone)]
struct App {{
    tool_router: ToolRouter<Self>,
}}

#[tool_router]
impl App {{
    fn new() -> Self {{
        Self {{
            tool_router: Self::tool_router(),
        }}
    }}

    #[tool(description = "Add two numbers")]
    fn add(
        &self,
        Parameters(AddArgs {{ a, b }}): Parameters<AddArgs>,
    ) -> Result<CallToolResult, McpError> {{
        Ok(CallToolResult::success(vec![ContentBlock::text(
            (a + b).to_string(),
        )]))
    }}
}}

#[tool_handler]
impl ServerHandler for App {{
    fn get_info(&self) -> ServerConfig {{
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
            .with_server_info(Implementation::new("{name}", "0.1.0"))
    }}
}}

#[tokio::main]
async fn main() -> Result<()> {{
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or({port});
    let ct = tokio_util::sync::CancellationToken::new();

    let service = StreamableHttpService::new(
        || Ok(App::new()),
        LocalSessionManager::default().into(),
        StreamableHttpServerConfig::default().with_cancellation_token(ct.child_token()),
    );

    let router = axum::Router::new().nest_service("/mcp", service);
    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!("foro.sh · MCP server listening on http://0.0.0.0:{{port}}/mcp");

    axum::serve(listener, router)
        .with_graceful_shutdown(async move {{
            let _ = tokio::signal::ctrl_c().await;
            ct.cancel();
        }})
        .await?;
    Ok(())
}}
'''

_README = '''\
# {name}

An MCP server in Rust, scaffolded by `foro init`.

> **Local only for now.** foro.sh does not deploy Rust yet. Use `cargo run`
> below to develop locally; switch to the Python or Node.js scaffold when you
> are ready to `foro deploy`.

## Structure

- `src/main.rs` — streamable-HTTP MCP server on `0.0.0.0:$PORT/mcp`
- `add` tool — example tool; replace it with your own

## Run locally

```bash
cargo run
# or pin the port:
PORT={port} cargo run
```

The server speaks MCP over streamable HTTP at `http://127.0.0.1:{port}/mcp`.
'''

_GITIGNORE = """\
/target/
.env
.DS_Store
.foro/
"""

_ENV_EXAMPLE = """\
# Copy to .env for local development.
# EXAMPLE_API_KEY=
"""


def crate_name(name: str) -> str:
    """Cargo package names are snake_case; must start with a letter."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        return "mcp_server"
    if slug[0].isdigit():
        slug = f"mcp_{slug}"
    return slug


def write_files(dir_path: Path, *, name: str, port: int, write) -> None:
    src = dir_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    write(
        dir_path / "Cargo.toml",
        _CARGO_TOML.format(crate_name=crate_name(name)),
    )
    write(dir_path / "src" / "main.rs", _MAIN_RS.format(name=name, port=port))
    write(dir_path / "README.md", _README.format(name=name, port=port))
    write(dir_path / ".gitignore", _GITIGNORE)
    write(dir_path / ".env.example", _ENV_EXAMPLE)


def fetch_deps(dir_path: Path) -> None:
    """Generate Cargo.lock so the project is reproducible off the bat."""
    try:
        _run(["cargo", "generate-lockfile"], cwd=dir_path, check=True)
    except MissingToolError as err:
        raise RuntimeError(
            f"{err}. Install Rust from https://rustup.rs to scaffold a Rust project."
        ) from None
    except subprocess.CalledProcessError as err:
        raise RuntimeError(
            f"`cargo generate-lockfile` failed in {dir_path}:\n{(err.stderr or '').strip()}"
        ) from None


def cleanup_partial(dir_path: Path) -> None:
    (dir_path / "Cargo.lock").unlink(missing_ok=True)
    shutil.rmtree(dir_path / "target", ignore_errors=True)
    src = dir_path / "src"
    if src.is_dir():
        for path in src.iterdir():
            path.unlink(missing_ok=True)
        if not any(src.iterdir()):
            src.rmdir()
