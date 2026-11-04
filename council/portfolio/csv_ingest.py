"""Portfolio CSV validation.

Expected columns: ``ticker``, ``shares``, ``price`` and optionally ``sector``.
Principles: never invent or silently repair data. A bad row is reported with its line number;
by default any bad row aborts ingestion, because weights computed from a subset of the
portfolio would be misleading. Other columns (e.g. cost basis) are ignored and not stored.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from council.errors import CsvValidationError

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("ticker", "shares", "price")
OPTIONAL_COLUMNS = ("sector",)
MAX_ROWS = 10_000
MAX_BYTES = 5 * 1024 * 1024
MAX_SHARES_SCALE = 6  # DECIMAL(18,6)
MAX_PRICE_SCALE = 4  # DECIMAL(18,4)
MAX_INTEGER_DIGITS = 12
MAX_SECTOR_LEN = 80

_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
# Columns that suggest credentials or account identifiers: refuse the whole file.
_SENSITIVE_HEADER = re.compile(
    r"pass(word|wd)?|secret|token|api[_\s-]?key|account|acct|ssn|\bpin\b|login|username|credential",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HoldingRow:
    """One validated holding. ``line`` is the 1-based CSV line the row came from."""

    line: int
    ticker: str
    shares: Decimal
    price: Decimal
    sector: str | None


@dataclass(frozen=True)
class RowIssue:
    line: int | None
    code: str
    message: str


@dataclass
class IngestReport:
    csv_sha256: str
    rows_read: int = 0
    holdings: list[HoldingRow] = field(default_factory=list)
    errors: list[RowIssue] = field(default_factory=list)
    warnings: list[RowIssue] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    invalid_row_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.holdings)


def _parse_decimal(raw: str, name: str, *, max_scale: int) -> tuple[Decimal | None, str | None]:
    value = raw.strip()
    if not value:
        return None, f"{name} is empty"
    if not _NUMBER.match(value):
        return None, f"{name} {raw!r} is not a plain number (no currency symbols or thousands separators)"
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None, f"{name} {raw!r} is not a valid number"
    if number <= 0:
        return None, f"{name} must be positive, got {value}"
    exponent = number.as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if scale > max_scale:
        return None, f"{name} {value} has more than {max_scale} decimal places (would need rounding)"
    if number >= Decimal(10) ** MAX_INTEGER_DIGITS:
        return None, f"{name} {value} is too large"
    return number, None


def _normalise_sector(raw: str | None) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    sector = " ".join(raw.split())
    if not sector:
        return None, None
    if len(sector) > MAX_SECTOR_LEN:
        return None, f"sector longer than {MAX_SECTOR_LEN} characters"
    return sector, None


def parse_portfolio_csv_text(text: str, *, csv_sha256: str | None = None) -> IngestReport:
    """Validate CSV text. Never raises for bad *rows*; raises :class:`CsvValidationError` only when
    the file as a whole is unusable (no header, missing required columns, credential-like columns)."""
    digest = csv_sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest()
    report = IngestReport(csv_sha256=digest)

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header_raw = next(reader)
    except StopIteration:
        raise CsvValidationError("The CSV file is empty.", report) from None
    header = [h.strip().lower() for h in header_raw]

    if len(set(header)) != len(header):
        raise CsvValidationError("The CSV header contains duplicate column names.", report)
    sensitive = [h for h in header if _SENSITIVE_HEADER.search(h)]
    if sensitive:
        raise CsvValidationError(
            f"Refusing to ingest: column(s) {sensitive} look like credentials or account identifiers. "
            "Export only ticker, shares, price (and optionally sector).",
            report,
        )
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise CsvValidationError(
            f"Missing required column(s): {', '.join(missing)}. Expected: ticker, shares, price[, sector].",
            report,
        )
    index = {name: header.index(name) for name in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if name in header}
    report.ignored_columns = [h for h in header if h not in index]
    if report.ignored_columns:
        report.warnings.append(
            RowIssue(1, "ignored_columns", f"Ignoring column(s) not used by Investor Council: {report.ignored_columns}")
        )

    candidates: list[HoldingRow] = []
    for row in reader:
        line = reader.line_num
        if not any(cell.strip() for cell in row):
            continue  # blank line
        report.rows_read += 1
        if report.rows_read > MAX_ROWS:
            raise CsvValidationError(f"More than {MAX_ROWS} rows; this tool is for personal portfolios.", report)
        if len(row) != len(header):
            report.errors.append(RowIssue(line, "field_count", f"expected {len(header)} fields, found {len(row)}"))
            report.invalid_row_count += 1
            continue

        problems: list[str] = []
        ticker = row[index["ticker"]].strip().upper()
        if not _TICKER.match(ticker):
            problems.append(f"ticker {row[index['ticker']]!r} is not a valid symbol (letters, digits, '.' or '-')")
        shares, err = _parse_decimal(row[index["shares"]], "shares", max_scale=MAX_SHARES_SCALE)
        if err:
            problems.append(err)
        price, err = _parse_decimal(row[index["price"]], "price", max_scale=MAX_PRICE_SCALE)
        if err:
            problems.append(err)
        sector, err = _normalise_sector(row[index["sector"]] if "sector" in index else None)
        if err:
            problems.append(err)

        if problems or shares is None or price is None:
            for message in problems:
                report.errors.append(RowIssue(line, "invalid_value", message))
            report.invalid_row_count += 1
            continue
        candidates.append(HoldingRow(line, ticker, shares, price, sector))

    if report.rows_read == 0:
        raise CsvValidationError("The CSV has a header but no data rows.", report)

    _resolve_duplicates(candidates, report)
    report.holdings.sort(key=lambda h: h.line)
    return report


def _resolve_duplicates(candidates: list[HoldingRow], report: IngestReport) -> None:
    """Merge duplicate tickers only when it is unambiguous; otherwise report every involved row.

    Same ticker with the same price: shares are summed (warning). Different prices or conflicting
    sectors cannot be reconciled without inventing a value, so all of those rows are errors.
    """
    by_ticker: dict[str, list[HoldingRow]] = {}
    for row in candidates:
        by_ticker.setdefault(row.ticker, []).append(row)

    for ticker, rows in by_ticker.items():
        if len(rows) == 1:
            report.holdings.append(rows[0])
            continue
        lines = [r.line for r in rows]
        prices = {r.price for r in rows}
        sectors = {r.sector for r in rows if r.sector}
        if len(prices) > 1:
            report.errors.append(
                RowIssue(lines[0], "duplicate_conflict", f"{ticker} appears on lines {lines} with different prices; not merging")
            )
            report.invalid_row_count += len(rows)
            continue
        if len(sectors) > 1:
            report.errors.append(
                RowIssue(lines[0], "duplicate_conflict", f"{ticker} appears on lines {lines} with different sectors {sorted(sectors)}; not merging")
            )
            report.invalid_row_count += len(rows)
            continue
        total = sum((r.shares for r in rows), Decimal(0))
        exponent = total.as_tuple().exponent
        scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        if scale > MAX_SHARES_SCALE or total >= Decimal(10) ** MAX_INTEGER_DIGITS:
            report.errors.append(
                RowIssue(lines[0], "duplicate_conflict", f"{ticker}: merged share total {total} exceeds supported precision")
            )
            report.invalid_row_count += len(rows)
            continue
        merged = HoldingRow(rows[0].line, ticker, total, rows[0].price, next(iter(sectors), None))
        report.holdings.append(merged)
        report.warnings.append(
            RowIssue(lines[0], "duplicate_merged", f"{ticker} appeared on lines {lines} with the same price; shares summed to {total}")
        )


def parse_portfolio_csv_file(path: Path | str) -> IngestReport:
    """Read and validate a CSV file (UTF-8, optional BOM)."""
    file_path = Path(path)
    if not file_path.is_file():
        raise CsvValidationError(f"File not found: {file_path}")
    size = file_path.stat().st_size
    if size > MAX_BYTES:
        raise CsvValidationError(f"{file_path.name} is {size} bytes; the limit is {MAX_BYTES}.")
    raw = file_path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvValidationError(f"{file_path.name} is not valid UTF-8: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    report = parse_portfolio_csv_text(text, csv_sha256=digest)
    log.info(
        "Parsed %s: %d rows read, %d valid holdings, %d invalid rows (sha256 %s...)",
        file_path.name,
        report.rows_read,
        len(report.holdings),
        report.invalid_row_count,
        digest[:12],
    )
    return report
