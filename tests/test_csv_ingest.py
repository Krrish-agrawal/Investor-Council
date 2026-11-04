from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from council.errors import CsvValidationError
from council.portfolio import csv_ingest
from council.portfolio.csv_ingest import parse_portfolio_csv_file, parse_portfolio_csv_text

GOOD = "ticker,shares,price,sector\nAAA,10,2.50,Tech\nBBB,4,5,Health\n"


def issues(report) -> list[str]:
    return [i.message for i in report.errors]


def test_valid_file_parses_to_decimals_and_uppercases_tickers() -> None:
    report = parse_portfolio_csv_text("Ticker , Shares,PRICE,Sector\n aaa ,10,2.50, Tech  Stocks \n")
    assert report.ok and not report.errors
    h = report.holdings[0]
    assert (h.ticker, h.shares, h.price, h.sector, h.line) == ("AAA", Decimal("10"), Decimal("2.50"), "Tech Stocks", 2)


def test_sector_column_is_optional_and_blank_sector_is_none_not_invented() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price\nAAA,1,1\n")
    assert report.holdings[0].sector is None
    report = parse_portfolio_csv_text("ticker,shares,price,sector\nAAA,1,1,\n")
    assert report.holdings[0].sector is None


@pytest.mark.parametrize(
    "csv_text, fragment",
    [
        ("", "empty"),
        ("ticker,shares,price\n", "no data rows"),
        ("ticker,shares\nAAA,1\n", "Missing required column"),
        ("ticker,shares,price,ticker\nAAA,1,1,AAA\n", "duplicate column"),
        ("ticker,shares,price,account_number\nAAA,1,1,123\n", "credentials or account identifiers"),
        ("ticker,shares,price,password\nAAA,1,1,x\n", "credentials or account identifiers"),
    ],
)
def test_unusable_files_raise_with_clear_message(csv_text: str, fragment: str) -> None:
    with pytest.raises(CsvValidationError) as exc:
        parse_portfolio_csv_text(csv_text)
    assert fragment in str(exc.value)


@pytest.mark.parametrize(
    "row, fragment",
    [
        ("AAA,abc,1", "not a plain number"),
        ("AAA,0,1", "must be positive"),
        ("AAA,-5,1", "must be positive"),
        ("AAA,1,0", "must be positive"),
        ("AAA,1,-2.5", "must be positive"),
        ("AAA,1,$10", "not a plain number"),
        ("AAA,1,\"1,000\"", "not a plain number"),
        ("AAA,,1", "is empty"),
        ("AAA,NaN,1", "not a plain number"),
        ("AAA,1e3,1", "not a plain number"),
        ("AAA,1.1234567,1", "more than 6 decimal places"),
        ("AAA,1,1.12345", "more than 4 decimal places"),
        ("AAA,1000000000000,1", "too large"),
        ("A A,1,1", "not a valid symbol"),
        (",1,1", "not a valid symbol"),
        ("AAA,1", "expected 3 fields"),
    ],
)
def test_invalid_rows_are_reported_with_line_numbers_and_never_repaired(row: str, fragment: str) -> None:
    report = parse_portfolio_csv_text(f"ticker,shares,price\nGOOD,1,1\n{row}\n")
    assert not report.ok
    assert report.invalid_row_count == 1
    assert any(fragment in m for m in issues(report)), issues(report)
    assert all(i.line == 3 for i in report.errors)
    assert [h.ticker for h in report.holdings] == ["GOOD"]


def test_every_problem_in_a_row_is_reported() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price\n!!,-1,abc\n")
    assert len(report.errors) == 3
    assert report.invalid_row_count == 1


def test_blank_lines_are_skipped_and_line_numbers_stay_physical() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price\n\nAAA,1,1\n\nBBB,x,1\n")
    assert report.rows_read == 2
    assert report.errors[0].line == 5


def test_duplicate_ticker_same_price_is_merged_with_warning() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price,sector\nAAA,10,2,Tech\naaa,5,2,\n")
    assert report.ok
    assert len(report.holdings) == 1
    assert report.holdings[0].shares == Decimal("15") and report.holdings[0].sector == "Tech"
    assert [w.code for w in report.warnings] == ["duplicate_merged"]


def test_duplicate_ticker_with_conflicting_price_is_rejected_not_averaged() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price\nAAA,10,2\nAAA,5,3\nBBB,1,1\n")
    assert not report.ok
    assert report.errors[0].code == "duplicate_conflict"
    assert [h.ticker for h in report.holdings] == ["BBB"]
    assert report.invalid_row_count == 2


def test_duplicate_ticker_with_conflicting_sector_is_rejected() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price,sector\nAAA,10,2,Tech\nAAA,5,2,Health\n")
    assert report.errors and report.errors[0].code == "duplicate_conflict"
    assert not report.holdings


def test_extra_columns_are_ignored_with_a_warning() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price,cost_basis\nAAA,1,1,99\n")
    assert report.ok
    assert report.ignored_columns == ["cost_basis"]
    assert any(w.code == "ignored_columns" for w in report.warnings)


def test_row_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(csv_ingest, "MAX_ROWS", 2)
    with pytest.raises(CsvValidationError, match="More than 2 rows"):
        parse_portfolio_csv_text("ticker,shares,price\nA,1,1\nB,1,1\nC,1,1\n")


def test_file_reading_handles_bom_and_hashes_bytes(tmp_path: Path) -> None:
    path = tmp_path / "p.csv"
    path.write_bytes(b"\xef\xbb\xbf" + GOOD.encode())
    report = parse_portfolio_csv_file(path)
    assert report.ok and len(report.holdings) == 2
    again = parse_portfolio_csv_file(path)
    assert report.csv_sha256 == again.csv_sha256 and len(report.csv_sha256) == 64


def test_file_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CsvValidationError, match="File not found"):
        parse_portfolio_csv_file(tmp_path / "missing.csv")
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"ticker,shares,price\n\xff\xfe,1,1\n")
    with pytest.raises(CsvValidationError, match="UTF-8"):
        parse_portfolio_csv_file(bad)
    big = tmp_path / "big.csv"
    big.write_text(GOOD)
    monkeypatch.setattr(csv_ingest, "MAX_BYTES", 5)
    with pytest.raises(CsvValidationError, match="limit"):
        parse_portfolio_csv_file(big)


def test_bundled_sample_is_valid() -> None:
    report = parse_portfolio_csv_file(Path(__file__).parent.parent / "samples" / "portfolio.csv")
    assert report.ok and len(report.holdings) == 7 and not report.errors
