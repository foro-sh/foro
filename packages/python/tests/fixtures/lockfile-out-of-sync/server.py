from fastmcp import FastMCP

import foro

mcp = FastMCP("lockfile-out-of-sync")

if __name__ == "__main__":
    foro.run(mcp)
