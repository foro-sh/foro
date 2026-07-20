from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wrong-fastmcp-import")

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
