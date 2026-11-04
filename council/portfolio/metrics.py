"""Deterministic portfolio calculations. Pure functions over :class:`HoldingRow`; no I/O.

All arithmetic uses :class:`decimal.Decimal`. Values are kept unrounded; rounding happens only
at presentation time (see :func:`quantize`). Prices are whatever the user supplied; this module
never fetches or estimates prices.

Concentration measures
* ``topN_pct``: combined weight (percent) of the N largest positions (all of them if fewer than N).
* ``hhi``: Herfindahl-Hirschman index on the 0-10,000 scale: sum of squared percent weights.
  A single holding gives 10,000; ``n`` equal holdings give ``10,000 / n``.
* ``effective_holdings``: ``10,000 / hhi``, the number of equal-weight positions with the same HHI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from council.portfolio.csv_ingest import HoldingRow

UNCLASSIFIED = "Unclassified"
_HUNDRED = Decimal(100)
_TEN_THOUSAND = Decimal(10_000)
PRECISION = 34


@dataclass(frozen=True)
class Position:
    ticker: str
    shares: Decimal
    price: Decimal
    sector: str | None
    market_value: Decimal
    weight_pct: Decimal


@dataclass(frozen=True)
class SectorAllocation:
    sector: str
    market_value: Decimal
    weight_pct: Decimal
    holdings: int


@dataclass(frozen=True)
class Concentration:
    top1_pct: Decimal
    top3_pct: Decimal
    top5_pct: Decimal
    hhi: Decimal
    effective_holdings: Decimal
    sector_hhi: Decimal


@dataclass(frozen=True)
class PortfolioMetrics:
    holdings_count: int
    total_value: Decimal
    positions: tuple[Position, ...]  # largest first, ticker as tie-break
    sectors: tuple[SectorAllocation, ...]  # largest first, name as tie-break
    concentration: Concentration
    unclassified_weight_pct: Decimal


def quantize(value: Decimal, places: int) -> Decimal:
    """Round half-up to ``places`` decimal places (presentation only)."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def compute_metrics(rows: Sequence[HoldingRow]) -> PortfolioMetrics:
    """Compute value, weights, sector allocation and concentration for validated holdings."""
    if not rows:
        raise ValueError("Cannot compute metrics for an empty portfolio")
    tickers = [r.ticker for r in rows]
    if len(set(tickers)) != len(tickers):
        raise ValueError("Duplicate tickers must be resolved before computing metrics")

    with localcontext() as ctx:
        ctx.prec = PRECISION
        values = {r.ticker: r.shares * r.price for r in rows}
        total = sum(values.values(), Decimal(0))
        if total <= 0:  # unreachable with validated rows; guards against misuse
            raise ValueError("Total portfolio value must be positive")

        positions = sorted(
            (
                Position(r.ticker, r.shares, r.price, r.sector, values[r.ticker], values[r.ticker] / total * _HUNDRED)
                for r in rows
            ),
            key=lambda p: (-p.market_value, p.ticker),
        )

        buckets: dict[str, list[Position]] = {}
        labels: dict[str, str] = {}
        for p in positions:  # positions are already in deterministic order, so labels are too
            label = p.sector or UNCLASSIFIED
            key = label.casefold()
            labels.setdefault(key, label)
            buckets.setdefault(key, []).append(p)
        sectors = sorted(
            (
                SectorAllocation(
                    labels[k],
                    sum((p.market_value for p in ps), Decimal(0)),
                    sum((p.market_value for p in ps), Decimal(0)) / total * _HUNDRED,
                    len(ps),
                )
                for k, ps in buckets.items()
            ),
            key=lambda s: (-s.market_value, s.sector),
        )

        weights = [p.weight_pct for p in positions]
        hhi = sum((w * w for w in weights), Decimal(0))
        sector_hhi = sum((s.weight_pct * s.weight_pct for s in sectors), Decimal(0))
        concentration = Concentration(
            top1_pct=sum(weights[:1], Decimal(0)),
            top3_pct=sum(weights[:3], Decimal(0)),
            top5_pct=sum(weights[:5], Decimal(0)),
            hhi=hhi,
            effective_holdings=_TEN_THOUSAND / hhi,
            sector_hhi=sector_hhi,
        )
        unclassified = next(
            (s.weight_pct for s in sectors if s.sector.casefold() == UNCLASSIFIED.casefold()), Decimal(0)
        )

    return PortfolioMetrics(
        holdings_count=len(positions),
        total_value=total,
        positions=tuple(positions),
        sectors=tuple(sectors),
        concentration=concentration,
        unclassified_weight_pct=unclassified,
    )


def find_position(metrics: PortfolioMetrics, ticker: str) -> Position | None:
    wanted = ticker.strip().upper()
    return next((p for p in metrics.positions if p.ticker == wanted), None)


def overlap_count(metrics: PortfolioMetrics, target_ticker: str, target_sector: str | None) -> int | None:
    """Number of *other* holdings whose sector label equals the target's sector label.

    Returns ``None`` when the target's sector is unknown (we do not guess it). Sector labels come
    from the user's CSV, so this is a heuristic: two labels for the same industry will not match.
    """
    held = find_position(metrics, target_ticker)
    sector = target_sector or (held.sector if held else None)
    if not sector:
        return None
    key = sector.casefold()
    return sum(
        1
        for p in metrics.positions
        if (p.sector or UNCLASSIFIED).casefold() == key and p.ticker != target_ticker.strip().upper()
    )
