from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, text

from council import config
from council.db.engine import make_engine
from council.db.grants import apply_grants
from council.db.migrate import apply_migrations, ensure_database
from council.edgar.client import EdgarClient
from tests import synthetic

FIXED_NOW = datetime(2025, 5, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """No COUNCIL_* variables and no .env loading: tests must not depend on a developer's machine."""
    monkeypatch.setattr(config, "_loaded", True)
    for name in list(os.environ):
        if name.startswith(("COUNCIL_", "MYSQL_")):
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ---------- EDGAR helpers ----------------------------------------------------------------------


class FakeSec:
    """MockTransport handler serving synthetic EDGAR documents and recording requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Callable[[], httpx.Response]] = {
            f"/api/xbrl/companyfacts/CIK{synthetic.SYNTHETIC_CIK}.json": lambda: httpx.Response(200, json=synthetic.companyfacts()),
            f"/submissions/CIK{synthetic.SYNTHETIC_CIK}.json": lambda: httpx.Response(200, json=synthetic.submissions()),
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.url.path)
        return route() if route else httpx.Response(404, text="not found")


@pytest.fixture
def fake_sec() -> FakeSec:
    return FakeSec()


@pytest.fixture
def edgar_client(tmp_path: Path, fake_sec: FakeSec) -> Iterator[EdgarClient]:
    client = EdgarClient(
        user_agent="Test Suite test@example.com",
        cache_dir=tmp_path / "edgar",
        max_rps=10,
        transport=httpx.MockTransport(fake_sec),
        sleep=lambda _s: None,
        now=lambda: FIXED_NOW,
    )
    yield client
    client.close()


# ---------- MySQL (integration) ----------------------------------------------------------------


def _admin_server_engine() -> Engine:
    config.load_env()
    try:
        engine = make_engine("admin", with_database=False)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as exc:  # noqa: BLE001 - any failure means "no usable MySQL here"
        pytest.skip(f"MySQL not available for integration tests ({type(exc).__name__}); see README")
        raise  # pragma: no cover


@pytest.fixture(scope="session")
def mysql_admin() -> Engine:
    return _admin_server_engine()


@pytest.fixture
def test_db(mysql_admin: Engine) -> Iterator[str]:
    """A throwaway database with migrations applied; dropped afterwards. Never touches the real one."""
    name = f"council_test_{uuid.uuid4().hex[:10]}"
    ensure_database(mysql_admin, name)
    url = config.db_url("admin", with_database=False).set(database=name)
    from sqlalchemy import create_engine

    engine = create_engine(url, future=True)
    apply_migrations(engine)
    engine.dispose()
    yield name
    with mysql_admin.begin() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))


@pytest.fixture
def conn(mysql_admin: Engine, test_db: str) -> Iterator:
    """Transactional connection to the throwaway database (admin account), rolled back at the end."""
    from sqlalchemy import create_engine

    engine = create_engine(config.db_url("admin", with_database=False).set(database=test_db), future=True)
    with engine.connect() as connection:
        trans = connection.begin()
        yield connection
        trans.rollback()
    engine.dispose()


def write_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch, mysql_admin: Engine, test_db: str) -> Iterator[dict[str, str]]:
    """Uniquely named test accounts (apply_grants resets privileges, so never reuse the real ones)."""
    suffix = uuid.uuid4().hex[:8]
    names = {"human": f"t_human_{suffix}", "agent": f"t_agent_{suffix}"}
    monkeypatch.setenv("COUNCIL_DB_HUMAN_USER", names["human"])
    monkeypatch.setenv("COUNCIL_DB_AGENT_USER", names["agent"])
    monkeypatch.setenv("COUNCIL_DB_HUMAN_PASSWORD", "Human-" + suffix + "-pw")
    monkeypatch.setenv("COUNCIL_DB_AGENT_PASSWORD", "Agent-" + suffix + "-pw")
    monkeypatch.setenv("COUNCIL_DB_NAME", test_db)
    apply_grants(mysql_admin, test_db)
    yield names
    with mysql_admin.begin() as c:
        for user in names.values():
            c.execute(text(f"DROP USER IF EXISTS '{user}'@'%'"))
