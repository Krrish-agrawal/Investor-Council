"""Plain-SQL migrations with a ``schema_migrations`` bookkeeping table.

Files live in ``council/db/migrations`` as ``NNNN_name.sql`` and are applied in order. Applied
files are checksummed: editing one afterwards is an error (write a new migration instead).
MySQL DDL auto-commits, so migrations are not atomic; every statement is idempotent
(``CREATE TABLE IF NOT EXISTS``) so a failed run can simply be repeated.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from council import config
from council.errors import DatabaseSetupError

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_BOOKKEEPING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INT UNSIGNED NOT NULL PRIMARY KEY,
  name        VARCHAR(120) NOT NULL,
  checksum    CHAR(64) NOT NULL,
  applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def split_statements(sql: str) -> list[str]:
    """Split a SQL script on ``;`` while respecting quotes and ``--`` line comments."""
    statements: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote in ("'", '"') and i + 1 < n:
                buf.append(sql[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
        elif ch == "-" and sql.startswith("--", i) and (i + 2 >= n or sql[i + 2] in " \t\r\n"):
            while i < n and sql[i] != "\n":
                i += 1
            continue
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILE.match(path.name)
        if not match:
            raise DatabaseSetupError(f"Migration file {path.name!r} must be named NNNN_name.sql")
        sql = path.read_text(encoding="utf-8")
        found.append(
            Migration(int(match.group(1)), match.group(2), sql, hashlib.sha256(sql.encode()).hexdigest())
        )
    versions = [m.version for m in found]
    if len(versions) != len(set(versions)):
        raise DatabaseSetupError("Duplicate migration version numbers")
    return found


def ensure_database(admin_engine: Engine, name: str) -> None:
    config.validate_identifier(name, "database name")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        )


def applied_versions(engine: Engine) -> dict[int, str]:
    """Map of applied version -> checksum (empty if the bookkeeping table does not exist yet)."""
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'"
            )
        ).scalar_one()
        if not exists:
            return {}
        rows = conn.execute(text("SELECT version, checksum FROM schema_migrations")).all()
    return {int(v): str(c) for v, c in rows}


def apply_migrations(engine: Engine, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Apply pending migrations in order. Returns the ones applied in this call."""
    migrations = discover_migrations(directory)
    with engine.begin() as conn:
        conn.execute(text(_BOOKKEEPING))
    done = applied_versions(engine)
    applied: list[Migration] = []
    for migration in migrations:
        recorded = done.get(migration.version)
        if recorded is not None:
            if recorded != migration.checksum:
                raise DatabaseSetupError(
                    f"Migration {migration.version:04d}_{migration.name} changed after it was applied. "
                    "Add a new migration instead of editing an applied one."
                )
            continue
        log.info("Applying migration %04d_%s", migration.version, migration.name)
        try:
            with engine.connect() as conn:
                for statement in split_statements(migration.sql):
                    conn.execute(text(statement))
                conn.execute(
                    text(
                        "INSERT INTO schema_migrations (version, name, checksum) "
                        "VALUES (:v, :n, :c)"
                    ),
                    {"v": migration.version, "n": migration.name, "c": migration.checksum},
                )
                conn.commit()
        except DBAPIError as exc:
            raise DatabaseSetupError(
                f"Migration {migration.version:04d}_{migration.name} failed: {exc.orig}"
            ) from exc
        applied.append(migration)
    return applied
