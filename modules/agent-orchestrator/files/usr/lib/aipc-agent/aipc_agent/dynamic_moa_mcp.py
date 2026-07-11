from mcp.server.fastmcp import FastMCP

from aipc_agent.dynamic_moa import consult_models as _consult_models

mcp = FastMCP("dynamic-moa")


@mcp.tool()
def consult_models(question: str, advisors: list[str] | None = None) -> dict:
    """Ask configured advisor models only when a second opinion is useful.

    Send a focused question plus only necessary code/context. Never include
    credentials. Keep requests likely to trigger provider moderation local.
    """
    return _consult_models(question, advisors)


if __name__ == "__main__":
    mcp.run()
