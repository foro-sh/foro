from fastmcp import FastMCP

mcp = FastMCP("stdio-only")


@mcp.tool
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    # Deliberately the stdio-transport footgun `foro dev` exists to catch:
    # this never opens a TCP port, so foro-wrapper.sh's health probe (and
    # foro dev's mirror of it) never sees it come up.
    mcp.run()
