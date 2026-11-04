"""Engine factory. Credentials come from the environment via :mod:`council.config`."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from council import config
from council.errors import DatabaseSetupError

log = logging.getLogger(__name__)


def make_engine(role: config.Role = "human", *, with_database: bool = True) -> Engine:
    """Create an engine for ``admin`` (create DB/users), ``human`` (everything) or ``agent``."""
    url = config.db_url(role, with_database=with_database)
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that commits on success and rolls back on error."""
    with engine.begin() as conn:
        yield conn


def check_connection(engine: Engine) -> str:
    """Return the server version, or raise :class:`DatabaseSetupError` with a helpful message."""
    try:
        with engine.connect() as conn:
            return str(conn.execute(text("SELECT VERSION()")).scalar_one())
    except OperationalError as exc:
        raise DatabaseSetupError(
            "Cannot connect to MySQL. Is `docker compose up -d` running and are the COUNCIL_DB_* "
            f"settings in .env correct? ({exc.orig})"
        ) from exc
