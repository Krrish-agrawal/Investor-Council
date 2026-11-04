from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from council.portfolio.csv_ingest import HoldingRow, parse_portfolio_csv_text
from council.portfolio.metrics import UNCLASSIFIED, compute_metrics, find_position, overlap_count, quantize
from council.portfolio.summary import build_local_summary, build_shared_summary


def rows(*items: tuple[str, str, str, str | None]) -> list[HoldingRow]:
    return [HoldingRow(i + 1, t, Decimal(s), Decimal(p), sec) for i, (t, s, p, sec) in enumerate(items)]


# Hand-computed fixture:
#   AAA 10 x 20 = 200 (Tech)   BBB 5 x 40 = 200 (Tech)   CCC 100 x 3 = 300 (Health)   DDD 50 x 6 = 300 (no sector)
#   total = 1000 -> weights 20 / 20 / 30 / 30
PORTFOLIO = rows(("AAA", "10", "20", "Tech"), ("BBB", "5", "40", "tech"), ("CCC", "100", "3", "Health"), ("DDD", "50", "6", None))


def test_values_weights_and_ordering_are_exact() -> None:
    m = compute_metrics(PORTFOLIO)
    assert m.total_value == Decimal(1000)
    assert [(p.ticker, p.market_value, p.weight_pct) for p in m.positions] == [
        ("CCC", Decimal(300), Decimal(30)),
        ("DDD", Decimal(300), Decimal(30)),
        ("AAA", Decimal(200), Decimal(20)),
        ("BBB", Decimal(200), Decimal(20)),
    ]  # ties broken by ticker
    assert sum(p.weight_pct for p in m.positions) == Decimal(100)


def test_sector_allocation_groups_case_insensitively_and_buckets_missing_data_as_unclassified() -> None:
    m = compute_metrics(PORTFOLIO)
    by_name = {s.sector: s for s in m.sectors}
    assert by_name["Tech"].weight_pct == Decimal(40) and by_name["Tech"].holdings == 2  # 'Tech' + 'tech'
    assert by_name["Health"].weight_pct == Decimal(30)
    assert by_name[UNCLASSIFIED].weight_pct == Decimal(30)
    assert m.unclassified_weight_pct == Decimal(30)
    assert sum(s.weight_pct for s in m.sectors) == Decimal(100)


def test_concentration_and_hhi_match_hand_calculation() -> None:
    c = compute_metrics(PORTFOLIO).concentration
    assert c.top1_pct == Decimal(30)
    assert c.top3_pct == Decimal(80)
    assert c.top5_pct == Decimal(100)  # only 4 holdings: top-5 covers everything
    assert c.hhi == Decimal(30**2 + 30**2 + 20**2 + 20**2)  # 2600
    assert quantize(c.effective_holdings, 4) == quantize(Decimal(10000) / 2600, 4)
    assert c.sector_hhi == Decimal(40**2 + 30**2 + 30**2)  # 3400


def test_hhi_bounds() -> None:
    single = compute_metrics(rows(("AAA", "3", "7", "X"))).concentration
    assert single.hhi == Decimal(10000) and single.effective_holdings == Decimal(1)
    equal = compute_metrics(rows(*[(f"T{i}", "1", "10", "S") for i in range(4)])).concentration
    assert equal.hhi == Decimal(2500) and equal.effective_holdings == Decimal(4)


def test_decimal_arithmetic_has_no_float_drift() -> None:
    # 3 x 0.1 style values that break binary floats must still sum to exactly 100%.
    m = compute_metrics(rows(("A", "3", "0.1", "S"), ("B", "7", "0.1", "S"), ("C", "11", "0.1", "S")))
    assert sum(p.weight_pct for p in m.positions).quantize(Decimal("0.000000001")) == Decimal("100.000000000")


def test_metrics_reject_empty_and_duplicate_input() -> None:
    with pytest.raises(ValueError):
        compute_metrics([])
    with pytest.raises(ValueError, match="Duplicate"):
        compute_metrics(rows(("A", "1", "1", None), ("A", "1", "1", None)))


def test_metrics_are_deterministic_regardless_of_input_order() -> None:
    assert compute_metrics(PORTFOLIO) == compute_metrics(list(reversed(PORTFOLIO)))


def test_quantize_rounds_half_up() -> None:
    assert quantize(Decimal("2.345"), 2) == Decimal("2.35")
    assert quantize(Decimal("2.344"), 2) == Decimal("2.34")


def test_overlap_count_uses_sector_labels_and_excludes_target() -> None:
    m = compute_metrics(PORTFOLIO)
    assert overlap_count(m, "AAA", None) == 1  # BBB shares 'Tech'
    assert overlap_count(m, "ZZZ", "Tech") == 2  # not held; two Tech holdings overlap
    assert overlap_count(m, "ZZZ", None) is None  # unknown sector: never guessed
    assert overlap_count(m, "DDD", None) is None  # held, but without a sector label: still not guessed
    assert find_position(m, "ddd").ticker == "DDD"  # lookup is case-insensitive


# ---------------- sanitised summary ----------------


def test_shared_summary_contains_no_other_tickers_shares_or_values() -> None:
    m = compute_metrics(PORTFOLIO)
    summary = build_shared_summary(m, target_ticker="AAA", price_as_of=date(2026, 10, 30))
    blob = json.dumps(summary)
    for other in ("BBB", "CCC", "DDD"):
        assert other not in blob
    for forbidden in ("shares", "market_value", "total_value", "cost"):
        assert forbidden not in blob
    assert summary["target_ticker"] == "AAA" and summary["target_held"] is True
    assert summary["target_weight_pct"] == 20.0
    assert summary["overlap_count"] == 1
    assert summary["holdings_count"] == 4
    assert summary["top_sectors"][0] == ["Tech", 40.0]
    assert summary["price_as_of"] == "2026-10-30" and "not market data" in summary["price_source"]


def test_shared_summary_percentages_are_rounded_to_one_decimal() -> None:
    m = compute_metrics(rows(("AAA", "1", "1", "S"), ("BBB", "1", "2", "S")))  # 33.333.../66.666...
    s = build_shared_summary(m, target_ticker="AAA")
    assert s["target_weight_pct"] == 33.3 and s["top1_pct"] == 66.7


def test_shared_summary_target_not_held_and_unknown_sector() -> None:
    m = compute_metrics(PORTFOLIO)
    s = build_shared_summary(m, target_ticker="zzz")
    assert s["target_ticker"] == "ZZZ" and s["target_held"] is False and s["target_weight_pct"] == 0.0
    assert s["overlap_count"] is None and s["target_sector"] is None


def test_shared_summary_without_target_leaves_target_fields_empty() -> None:
    s = build_shared_summary(compute_metrics(PORTFOLIO))
    assert s["target_ticker"] is None and s["target_held"] is None and s["overlap_count"] is None


def test_shared_summary_flags_partial_portfolio() -> None:
    assert build_shared_summary(compute_metrics(PORTFOLIO), excluded_rows=2)["portfolio_partial"] is True


def test_local_summary_has_position_detail() -> None:
    d = build_local_summary(compute_metrics(PORTFOLIO))
    assert d["total_value"] == "1000.00" and d["positions"][0]["ticker"] == "CCC"
    assert d["concentration"]["hhi"] == "2600.0"


def test_end_to_end_from_csv_text() -> None:
    report = parse_portfolio_csv_text("ticker,shares,price,sector\nAAA,10,20,Tech\nBBB,5,40,Tech\nCCC,100,3,Health\n")
    m = compute_metrics(report.holdings)
    assert m.total_value == Decimal(700)
    assert quantize(m.positions[0].weight_pct, 2) == Decimal("42.86")
