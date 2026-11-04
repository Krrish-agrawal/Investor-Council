"""``council db ...``: database lifecycle commands."""

from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import text

from council import config
from council.cli.common import cli_errors
from council.db.engine import check_connection, make_engine
from council.db.grants import apply_grants
from council.db.migrate import apply_migrations, applied_versions, discover_migrations, ensure_database

db_app = typer.Typer(help="Database setup and status.", no_args_is_help=True)


@db_app.command("init")
@cli_errors
def init(
    no_agent: Annotated[bool, typer.Option("--no-agent", help="Do not create the restricted agent account.")] = False,
) -> None:
    """Create the database, apply migrations and create the human (and agent) MySQL accounts.

    Uses the admin credentials from .env. Safe to run repeatedly.
    """
    name = config.db_name()
    admin_server = make_engine("admin", with_database=False)
    version = check_connection(admin_server)
    typer.echo(f"Connected to MySQL {version}")
    ensure_database(admin_server, name)
    typer.echo(f"Database `{name}` is ready")

    admin_db = make_engine("admin", with_database=True)
    applied = apply_migrations(admin_db)
    typer.echo(f"Migrations applied: {[f'{m.version:04d}_{m.name}' for m in applied] or 'none (already up to date)'}")

    accounts = apply_grants(admin_server, name, create_agent=not no_agent)
    typer.echo(f"Accounts configured: {', '.join(accounts)}")
    typer.echo("Done. Next: council human ingest --file samples/portfolio.csv --sample")


@db_app.command("status")
@cli_errors
def status() -> None:
    """Show the server version, applied migrations and row counts (as the human account)."""
    engine = make_engine("human")
    typer.echo(f"MySQL {check_connection(engine)}  database={config.db_name()}")
    done = applied_versions(engine)
    for migration in discover_migrations():
        state = "applied" if migration.version in done else "PENDING"
        typer.echo(f"  {migration.version:04d}_{migration.name}: {state}")
    tables = ("portfolios", "holdings", "research_sessions", "sources", "evidence_refs", "claims",
              "claim_evidence", "submissions", "challenges", "dossiers")
    with engine.connect() as conn:
        for table in tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            typer.echo(f"  {table:<16} {count}")
