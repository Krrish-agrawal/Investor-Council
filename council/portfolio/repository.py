"""Persistence for portfolios and holdings (human-only tables)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import Connection, text

from council.errors import CsvValidationError, NotFoundError
from council.portfolio.csv_ingest import HoldingRow, IngestReport

log = logging.getLogger(__name__)

Origin = Literal["sample", "user"]


@dataclass(frozen=True)
class PortfolioRecord:
    id: int
    name: str
    origin: str
    csv_sha256: str
    price_as_of: date | None
    excluded_rows: int
    created_at: datetime


def save_portfolio(
    conn: Connection,
    report: IngestReport,
    *,
    name: str,
    origin: Origin,
    price_as_of: date | None,
    allow_partial: bool = False,
) -> tuple[PortfolioRecord, bool]:
    """Store a validated portfolio. Returns ``(record, created)``.

    Re-ingesting byte-identical content with the same origin returns the existing record.
    Refuses to store when the report has errors unless ``allow_partial`` is set, in which case the
    number of excluded rows is stored so later reports can say the portfolio is partial.
    """
    if report.errors and not allow_partial:
        raise CsvValidationError(
            f"{report.invalid_row_count} invalid row(s); nothing stored. Fix the file or pass --allow-partial.", report
        )
    if not report.holdings:
        raise CsvValidationError("No valid holdings to store.", report)

    existing = conn.execute(
        text("SELECT id FROM portfolios WHERE csv_sha256 = :h AND origin = :o"),
        {"h": report.csv_sha256, "o": origin},
    ).scalar()
    if existing is not None:
        log.info("Portfolio already ingested as id=%s (identical content)", existing)
        return load_portfolio(conn, int(existing)), False

    warnings = [{"line": w.line, "code": w.code, "message": w.message} for w in report.warnings]
    warnings += [{"line": e.line, "code": e.code, "message": e.message} for e in report.errors]
    result = conn.execute(
        text(
            "INSERT INTO portfolios (name, origin, csv_sha256, price_as_of, excluded_rows, ingest_warnings) "
            "VALUES (:name, :origin, :h, :asof, :excluded, :warn)"
        ),
        {
            "name": name,
            "origin": origin,
            "h": report.csv_sha256,
            "asof": price_as_of,
            "excluded": report.invalid_row_count if allow_partial else 0,
            "warn": json.dumps(warnings) if warnings else None,
        },
    )
    portfolio_id = int(result.lastrowid)
    conn.execute(
        text(
            "INSERT INTO holdings (portfolio_id, ticker, shares, price, sector, sector_source) "
            "VALUES (:pid, :ticker, :shares, :price, :sector, :src)"
        ),
        [
            {
                "pid": portfolio_id,
                "ticker": h.ticker,
                "shares": h.shares,
                "price": h.price,
                "sector": h.sector,
                "src": "csv" if h.sector else "unclassified",
            }
            for h in report.holdings
        ],
    )
    log.info("Stored portfolio id=%s with %d holdings", portfolio_id, len(report.holdings))
    return load_portfolio(conn, portfolio_id), True


def load_portfolio(conn: Connection, portfolio_id: int) -> PortfolioRecord:
    row = conn.execute(
        text(
            "SELECT id, name, origin, csv_sha256, price_as_of, excluded_rows, created_at "
            "FROM portfolios WHERE id = :id"
        ),
        {"id": portfolio_id},
    ).first()
    if row is None:
        raise NotFoundError(f"Portfolio {portfolio_id} not found")
    return PortfolioRecord(*row)


def latest_portfolio_id(conn: Connection) -> int | None:
    value = conn.execute(text("SELECT MAX(id) FROM portfolios")).scalar()
    return int(value) if value is not None else None


def load_holdings(conn: Connection, portfolio_id: int) -> list[HoldingRow]:
    rows = conn.execute(
        text("SELECT ticker, shares, price, sector FROM holdings WHERE portfolio_id = :id ORDER BY id"),
        {"id": portfolio_id},
    ).all()
    if not rows:
        raise NotFoundError(f"Portfolio {portfolio_id} has no holdings")
    return [HoldingRow(i + 1, r[0], r[1], r[2], r[3]) for i, r in enumerate(rows)]
