"""Console script: `yearbook-agent serve`, `yearbook-agent eval`."""

from __future__ import annotations

import logging

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Yearbook chat agent service")


@app.command()
def serve(
    port: int | None = typer.Option(None, help="Overrides AGENT_PORT"),
    host: str = typer.Option("0.0.0.0", help="Bind address"),
) -> None:
    """Run the HTTP service the Go API proxies to."""
    import uvicorn

    from .app import create_app
    from .config import load_settings

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = load_settings()
    uvicorn.run(create_app(settings), host=host, port=port or settings.agent_port, log_level="info")


@app.command()
def eval(
    real: bool = typer.Option(
        False, help="Use the configured OpenAI model instead of the scripted fake"
    ),
    only: str | None = typer.Option(None, help="Run only cases whose id contains this text"),
    mcp_url: str | None = typer.Option(
        None, help="Use a running MCP server instead of the in-process fake"
    ),
) -> None:
    """Replay evals/cases.yaml through the graph; report kind, tool sequence and saveable."""
    from .evals import main as run_eval

    logging.basicConfig(level=logging.WARNING)
    raise typer.Exit(run_eval(real=real, only=only, mcp_url=mcp_url))


def main() -> None:
    app()
