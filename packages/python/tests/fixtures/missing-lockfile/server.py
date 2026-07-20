from fastmcp import FastMCP

import foro

mcp = FastMCP("missing-lockfile")

if __name__ == "__main__":
    foro.run(mcp)
