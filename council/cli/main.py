"""``council`` command-line entry point."""

from __future__ import annotations

from typing import Annotated

import typer

from council import __version__, config
from council.agent.cli import app as agent_app
from council.cli.db_cmds import db_app
from council.cli.human import human_app
from council.logging_setup import configure_logging

app = typer.Typer(
    name="council",
    help="Investor Council: deterministic research tools (not financial advice).",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(db_app, name="db")
app.add_typer(human_app, name="human")
app.add_typer(agent_app, name="agent")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"investor-council {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    log_level: Annotated[str | None, typer.Option("--log-level", help="DEBUG, INFO, WARNING, ERROR (default: COUNCIL_LOG_LEVEL or INFO).")] = None,
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version and exit.")] = False,
) -> None:
    if ctx.invoked_subcommand == "agent":
        return  # agent mode reads only .council.env; never touch the human's .env here
    configure_logging(log_level or config.log_level())


if __name__ == "__main__":  # pragma: no cover
    app()
