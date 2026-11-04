"""Query helpers over a cached company-facts document."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from council.edgar.client import CachedDocument
from council.errors import DataValidationError
from council.edgar.models import (
    ANNUAL_FORMS,
    QUARTERLY_FORMS,
    Basis,
    FactEntry,
    FiscalPeriod,
    parse_date,
    parse_fact_entry,
)


@dataclass(frozen=True)
class ResolvedFact:
    """The value to cite for one concept and period, plus anything that disagrees with it.

    The *latest filed* value is selected (a later filing may restate an earlier one). If other
    filings reported a different number for the same period, ``conflict`` is true and both are
    kept so a human can see the filing dates; nothing is silently overwritten.
    """

    selected: FactEntry
    alternatives: tuple[FactEntry, ...]

    @property
    def conflict(self) -> bool:
        return any(a.value != self.selected.value for a in self.alternatives)

    @property
    def conflicting_entries(self) -> tuple[FactEntry, ...]:
        return tuple(a for a in self.alternatives if a.value != self.selected.value)


def resolve_entries(entries: Iterable[FactEntry]) -> list[ResolvedFact]:
    """Group entries by (concept, unit, start, end) and pick the latest-filed value of each group."""
    groups: dict[tuple, list[FactEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.period_key, []).append(entry)
    resolved = []
    for group in groups.values():
        ordered = sorted(group, key=lambda e: (e.filed, e.accession), reverse=True)
        resolved.append(ResolvedFact(ordered[0], tuple(ordered[1:])))
    return sorted(resolved, key=lambda r: (r.selected.end, r.selected.filed), reverse=True)


class CompanyFactsSnapshot:
    """A cached ``companyfacts`` document with typed accessors."""

    def __init__(self, document: CachedDocument) -> None:
        self.document = document
        self._raw = document.raw
        self.cik: str = str(int(self._raw["cik"])).zfill(10)
        self.entity_name: str = self._raw["entityName"]
        self._facts: dict[str, dict[str, Any]] = self._raw["facts"]
        self._cache: dict[tuple[str, str, str | None], list[FactEntry]] = {}

    @property
    def retrieved_at(self):
        return self.document.meta.retrieved_at

    @property
    def sha256(self) -> str:
        return self.document.meta.sha256

    def has_concept(self, taxonomy: str, concept: str) -> bool:
        return concept in self._facts.get(taxonomy, {})

    def entries(self, taxonomy: str, concept: str, unit: str | None = None) -> list[FactEntry]:
        key = (taxonomy, concept, unit)
        if key not in self._cache:
            body = self._facts.get(taxonomy, {}).get(concept)
            found: list[FactEntry] = []
            if body:
                for u, raw_entries in body["units"].items():
                    if unit is None or u == unit:
                        found.extend(parse_fact_entry(taxonomy, concept, u, e) for e in raw_entries)
            self._cache[key] = found
        return self._cache[key]

    def iter_raw(self) -> Iterator[tuple[str, str, str, dict[str, Any]]]:
        for taxonomy, concepts in self._facts.items():
            for concept, body in concepts.items():
                for unit, entries in body["units"].items():
                    for entry in entries:
                        yield taxonomy, concept, unit, entry

    def latest(
        self, taxonomy: str, concept: str, basis: Basis, unit: str | None = None
    ) -> ResolvedFact | None:
        """Latest period of ``basis`` (annual/quarterly) for a concept, or ``None`` if there is none."""
        candidates = [e for e in self.entries(taxonomy, concept, unit) if e.basis == basis]
        resolved = resolve_entries(candidates)
        return resolved[0] if resolved else None

    def find(
        self,
        taxonomy: str,
        concept: str,
        unit: str,
        period_end: date,
        *,
        period_start: date | None = None,
    ) -> ResolvedFact | None:
        """Exact period lookup (used to re-verify evidence recorded earlier)."""
        candidates = [
            e
            for e in self.entries(taxonomy, concept, unit)
            if e.end == period_end and (period_start is None or e.start == period_start)
        ]
        resolved = resolve_entries(candidates)
        return resolved[0] if resolved else None


@dataclass(frozen=True)
class FiscalPeriods:
    latest_annual: FiscalPeriod | None
    latest_quarterly: FiscalPeriod | None


def identify_fiscal_periods(snapshot: CompanyFactsSnapshot) -> FiscalPeriods:
    """Find the most recent annual and quarterly reporting periods present in the snapshot.

    Uses period duration (flows) or the filing form (instants) rather than ``fp``, because
    ``fy``/``fp`` describe the filing a value appeared in, not necessarily its own period.
    Only entries from annual (10-K family) or quarterly (10-Q) filings are considered, and only
    financial-statement taxonomies: ``dei`` cover-page facts (e.g. shares outstanding) are dated
    after the fiscal period they accompany and would otherwise be mistaken for a period end.
    """
    best: dict[str, FiscalPeriod] = {}
    for taxonomy, _concept, _unit, raw in snapshot.iter_raw():
        if taxonomy == "dei":
            continue
        form = raw.get("form")
        if form in ANNUAL_FORMS:
            wanted: Basis = "annual"
        elif form in QUARTERLY_FORMS:
            wanted = "quarterly"
        else:
            continue
        try:
            end = parse_date(raw["end"], "end")
            start = parse_date(raw["start"], "start") if raw.get("start") else None
            filed = parse_date(raw["filed"], "filed")
        except (KeyError, DataValidationError):  # validated at fetch time; skip anything odd
            continue
        days = (end - start).days if start else None
        if days is not None:
            kind: Basis = "annual" if 350 <= days <= 380 else "quarterly" if 80 <= days <= 100 else "other"
            if kind != wanted:
                continue
        current = best.get(wanted)
        if current is None or (end, filed) > (current.end, current.filed):
            best[wanted] = FiscalPeriod(
                basis=wanted,
                start=start,
                end=end,
                fiscal_year=raw.get("fy") if isinstance(raw.get("fy"), int) else None,
                fiscal_period=raw.get("fp") if isinstance(raw.get("fp"), str) else None,
                form=form,
                filed=filed,
                accession=str(raw.get("accn", "")),
            )
    return FiscalPeriods(best.get("annual"), best.get("quarterly"))


def decimal_text(value: Decimal) -> str:
    """Stable text for a value (no exponent notation)."""
    return format(value, "f")
