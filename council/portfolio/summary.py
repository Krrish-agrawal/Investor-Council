"""Portfolio summaries.

* :func:`build_local_summary` is for the human's terminal only and contains position-level detail.
* :func:`build_shared_summary` is the *sanitised* summary that may be pasted into a shared room.
  It contains rounded percentages and counts only: no shares, no currency values, no cost basis
  and no tickers other than the research target.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from council.portfolio.metrics import (
    UNCLASSIFIED,
    PortfolioMetrics,
    find_position,
    overlap_count,
    quantize,
)

SHARED_SUMMARY_VERSION = 1
TOP_SECTORS_SHARED = 5


def _pct1(value) -> float:
    return float(quantize(value, 1))


def build_shared_summary(
    metrics: PortfolioMetrics,
    *,
    target_ticker: str | None = None,
    target_sector: str | None = None,
    price_as_of: date | None = None,
    excluded_rows: int = 0,
) -> dict[str, Any]:
    """Sanitised summary. With no ``target_ticker`` the target fields are left empty (``None``)."""
    target = target_ticker.strip().upper() if target_ticker else None
    held = find_position(metrics, target) if target else None
    sector = target_sector or (held.sector if held else None)
    conc = metrics.concentration
    return {
        "schema_version": SHARED_SUMMARY_VERSION,
        "target_ticker": target,
        "target_held": held is not None if target else None,
        "target_weight_pct": (_pct1(held.weight_pct) if held else 0.0) if target else None,
        "target_sector": sector,
        "overlap_count": overlap_count(metrics, target, target_sector) if target else None,
        "holdings_count": metrics.holdings_count,
        "top_sectors": [[s.sector, _pct1(s.weight_pct)] for s in metrics.sectors[:TOP_SECTORS_SHARED]],
        "top1_pct": _pct1(conc.top1_pct),
        "top3_pct": _pct1(conc.top3_pct),
        "top5_pct": _pct1(conc.top5_pct),
        "hhi": float(quantize(conc.hhi, 0)),
        "effective_holdings": float(quantize(conc.effective_holdings, 1)),
        "unclassified_pct": _pct1(metrics.unclassified_weight_pct),
        "price_as_of": price_as_of.isoformat() if price_as_of else None,
        "price_source": "user-supplied (CSV); not market data retrieved by this tool",
        "portfolio_partial": excluded_rows > 0,
    }


def build_local_summary(metrics: PortfolioMetrics, *, price_as_of: date | None = None) -> dict[str, Any]:
    """Full detail for local use. Never post this to a shared room."""
    conc = metrics.concentration
    return {
        "holdings_count": metrics.holdings_count,
        "total_value": str(quantize(metrics.total_value, 2)),
        "price_as_of": price_as_of.isoformat() if price_as_of else None,
        "positions": [
            {
                "ticker": p.ticker,
                "shares": str(p.shares),
                "price": str(p.price),
                "sector": p.sector or UNCLASSIFIED,
                "market_value": str(quantize(p.market_value, 2)),
                "weight_pct": str(quantize(p.weight_pct, 2)),
            }
            for p in metrics.positions
        ],
        "sectors": [
            {"sector": s.sector, "weight_pct": str(quantize(s.weight_pct, 2)), "holdings": s.holdings}
            for s in metrics.sectors
        ],
        "concentration": {
            "top1_pct": str(quantize(conc.top1_pct, 2)),
            "top3_pct": str(quantize(conc.top3_pct, 2)),
            "top5_pct": str(quantize(conc.top5_pct, 2)),
            "hhi": str(quantize(conc.hhi, 1)),
            "effective_holdings": str(quantize(conc.effective_holdings, 2)),
            "sector_hhi": str(quantize(conc.sector_hhi, 1)),
        },
    }
