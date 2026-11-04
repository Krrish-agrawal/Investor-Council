"""Research sessions (one per research run, e.g. ``S-0001``)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from sqlalchemy import Connection, text

from council.errors import CouncilError, NotFoundError

_CODE = re.compile(r"^S-\d{4,6}$")
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")


@dataclass(frozen=True)
class SessionRecord:
    id: int
    code: str
    portfolio_id: int
    target_ticker: str
    target_cik: str | None
    target_sector: str | None
    thesis: str
    stage: int
    status: str
    shared_summary: dict[str, Any]
    freshness_cfg: dict[str, Any]
    session_date: date
    data_mode: str


_COLUMNS = (
    "id, code, portfolio_id, target_ticker, target_cik, target_sector, thesis, stage, status, "
    "shared_summary_json, freshness_cfg_json, session_date, data_mode"
)


def as_json(value: Any) -> Any:
    """PyMySQL returns JSON columns as text; normalise to Python objects."""
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def _record(row) -> SessionRecord:
    return SessionRecord(
        id=int(row[0]),
        code=row[1],
        portfolio_id=int(row[2]),
        target_ticker=row[3],
        target_cik=row[4],
        target_sector=row[5],
        thesis=row[6],
        stage=int(row[7]),
        status=row[8],
        shared_summary=as_json(row[9]),
        freshness_cfg=as_json(row[10]),
        session_date=row[11],
        data_mode=row[12],
    )


def create_session(
    conn: Connection,
    *,
    portfolio_id: int,
    target_ticker: str,
    thesis: str,
    shared_summary: dict[str, Any],
    freshness_cfg: dict[str, Any],
    session_date: date,
    target_cik: str | None = None,
    target_sector: str | None = None,
) -> SessionRecord:
    ticker = target_ticker.strip().upper()
    if not _TICKER.match(ticker):
        raise CouncilError(f"Invalid target ticker {target_ticker!r}")
    if not thesis.strip():
        raise CouncilError("A thesis or question is required; it is the human's own words.")
    next_number = int(
        conn.execute(text("SELECT COALESCE(MAX(CAST(SUBSTRING(code, 3) AS UNSIGNED)), 0) + 1 FROM research_sessions")).scalar_one()
    )
    code = f"S-{next_number:04d}"
    conn.execute(
        text(
            "INSERT INTO research_sessions (code, portfolio_id, target_ticker, target_cik, target_sector, thesis, "
            "shared_summary_json, freshness_cfg_json, session_date) "
            "VALUES (:code, :pid, :ticker, :cik, :sector, :thesis, :summary, :fresh, :sdate)"
        ),
        {
            "code": code,
            "pid": portfolio_id,
            "ticker": ticker,
            "cik": target_cik,
            "sector": target_sector,
            "thesis": thesis.strip(),
            "summary": json.dumps(shared_summary),
            "fresh": json.dumps(freshness_cfg),
            "sdate": session_date,
        },
    )
    return get_session(conn, code)


def get_session(conn: Connection, code: str) -> SessionRecord:
    if not _CODE.match(code):
        raise CouncilError(f"Invalid session code {code!r}; expected something like S-0001")
    row = conn.execute(text(f"SELECT {_COLUMNS} FROM research_sessions WHERE code = :c"), {"c": code}).first()
    if row is None:
        raise NotFoundError(f"Session {code} not found")
    return _record(row)


def latest_session(conn: Connection) -> SessionRecord | None:
    row = conn.execute(text(f"SELECT {_COLUMNS} FROM research_sessions ORDER BY id DESC LIMIT 1")).first()
    return _record(row) if row else None


class SessionLike(Protocol):
    """What the evidence and claim services need from a session (satisfied by both views)."""

    id: int
    code: str
    stage: int
    session_date: date
    freshness_cfg: dict[str, Any]


@dataclass(frozen=True)
class AgentSession:
    """A session as an agent sees it: no ``portfolio_id`` (the agent account cannot read it)."""

    id: int
    code: str
    target_ticker: str
    target_cik: str | None
    target_sector: str | None
    thesis: str
    stage: int
    status: str
    shared_summary: dict[str, Any]
    freshness_cfg: dict[str, Any]
    session_date: date
    data_mode: str


# Exactly the columns granted to the agent account (council/db/grants.py)
_AGENT_COLUMNS = (
    "id, code, target_ticker, target_cik, target_sector, thesis, stage, status, "
    "shared_summary_json, freshness_cfg_json, session_date, data_mode"
)


def get_agent_session(conn: Connection, code: str) -> AgentSession:
    if not _CODE.match(code):
        raise CouncilError(f"Invalid session code {code!r}; expected something like S-0001")
    row = conn.execute(text(f"SELECT {_AGENT_COLUMNS} FROM research_sessions WHERE code = :c"), {"c": code}).first()
    if row is None:
        raise NotFoundError(f"Session {code} not found")
    return AgentSession(
        id=int(row[0]), code=row[1], target_ticker=row[2], target_cik=row[3], target_sector=row[4], thesis=row[5],
        stage=int(row[6]), status=row[7], shared_summary=as_json(row[8]), freshness_cfg=as_json(row[9]),
        session_date=row[10], data_mode=row[11],
    )
