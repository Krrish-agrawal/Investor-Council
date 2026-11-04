"""Curated metric map: friendly metric name -> candidate XBRL concepts.

Companies tag the same idea with different concepts (revenue is the classic case), so each metric
lists candidates in priority order. The first candidate that has data for the requested basis wins.
If none do, the lookup reports what was tried and the caller records a ``GAP``; we never estimate
or substitute a different metric.

These are standard us-gaap/dei tag names, but coverage per company is unverified until the
Day-2 EDGAR test (T11). Treat this list as a starting point.
"""

from __future__ import annotations

from dataclasses import dataclass

from council.edgar.facts import CompanyFactsSnapshot, ResolvedFact
from council.edgar.models import Basis


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str
    unit: str
    candidates: tuple[tuple[str, str], ...]  # (taxonomy, concept)


METRICS: dict[str, MetricSpec] = {
    m.name: m
    for m in (
        MetricSpec("revenue", "Revenue", "USD", (
            ("us-gaap", "Revenues"),
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ("us-gaap", "SalesRevenueNet"),
        )),
        MetricSpec("gross_profit", "Gross profit", "USD", (("us-gaap", "GrossProfit"),)),
        MetricSpec("operating_income", "Operating income", "USD", (("us-gaap", "OperatingIncomeLoss"),)),
        MetricSpec("net_income", "Net income", "USD", (("us-gaap", "NetIncomeLoss"),)),
        MetricSpec("eps_diluted", "Diluted EPS", "USD/shares", (("us-gaap", "EarningsPerShareDiluted"),)),
        MetricSpec("total_assets", "Total assets", "USD", (("us-gaap", "Assets"),)),
        MetricSpec("total_liabilities", "Total liabilities", "USD", (("us-gaap", "Liabilities"),)),
        MetricSpec("stockholders_equity", "Stockholders' equity", "USD", (("us-gaap", "StockholdersEquity"),)),
        MetricSpec("cash_and_equivalents", "Cash and cash equivalents", "USD", (
            ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        )),
        MetricSpec("long_term_debt", "Long-term debt", "USD", (
            ("us-gaap", "LongTermDebt"),
            ("us-gaap", "LongTermDebtNoncurrent"),
        )),
        MetricSpec("operating_cash_flow", "Operating cash flow", "USD", (
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        )),
        MetricSpec("capital_expenditure", "Capital expenditure", "USD", (
            ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        )),
        MetricSpec("shares_outstanding", "Shares outstanding (cover page)", "shares", (
            ("dei", "EntityCommonStockSharesOutstanding"),
        )),
    )
}


@dataclass(frozen=True)
class MetricLookup:
    metric: MetricSpec
    basis: Basis
    resolved: ResolvedFact | None
    tried: tuple[tuple[str, str], ...]

    @property
    def found(self) -> bool:
        return self.resolved is not None

    def gap_text(self) -> str:
        tried = ", ".join(f"{t}:{c}" for t, c in self.tried)
        return (
            f"No {self.basis} {self.metric.label} ({self.metric.unit}) found in the snapshot; "
            f"concepts tried: {tried}. Nothing was estimated."
        )


def lookup_metric(snapshot: CompanyFactsSnapshot, metric: str, basis: Basis = "annual") -> MetricLookup:
    spec = METRICS.get(metric)
    if spec is None:
        raise KeyError(f"Unknown metric {metric!r}; known: {', '.join(sorted(METRICS))}")
    for taxonomy, concept in spec.candidates:
        resolved = snapshot.latest(taxonomy, concept, basis, unit=spec.unit)
        if resolved is not None:
            return MetricLookup(spec, basis, resolved, spec.candidates)
    return MetricLookup(spec, basis, None, spec.candidates)
