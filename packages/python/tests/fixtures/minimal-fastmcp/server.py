from fastmcp import FastMCP

import foro

mcp = FastMCP("minimal-fastmcp")


@mcp.tool
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    foro.run(mcp)
