"""Typed models and parsing helpers for EDGAR company facts and submissions.

Field names below follow the SEC's XBRL "company facts" / "submissions" JSON as commonly seen
(``end``, ``val``, ``accn``, ``fy``, ``fp``, ``form``, ``filed``, ``frame``). They have NOT yet been
verified against a live response (test T11), so parsing is strict and fails loudly on surprises.
Note that ``fy``/``fp`` describe the *filing* a value was reported in, so a prior-year comparative
inside a later 10-K carries that filing's ``fy``/``fp``; period duration and ``end`` identify the
actual period. We therefore classify periods by duration, not by ``fp``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from council.errors import DataValidationError

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SOURCE_NAME = "SEC EDGAR (data.sec.gov)"

_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "20-F", "40-F")
QUARTERLY_FORMS = ("10-Q", "10-Q/A")

Basis = Literal["annual", "quarterly", "other"]


def normalize_cik(value: str | int) -> str:
    """Return the 10-digit, zero-padded CIK used in EDGAR URLs. Accepts ``320193`` or ``CIK0000320193``."""
    text = str(value).strip().upper()
    if text.startswith("CIK"):
        text = text[3:]
    if not text.isdigit() or int(text) <= 0 or len(text) > 10:
        raise DataValidationError(f"{value!r} is not a valid CIK (expected 1-10 digits)")
    return text.zfill(10)


def parse_date(value: Any, what: str) -> date:
    if not isinstance(value, str):
        raise DataValidationError(f"{what} must be an ISO date string, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataValidationError(f"{what} {value!r} is not a YYYY-MM-DD date") from exc


def parse_number(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise DataValidationError(f"{what} must be numeric, got {value!r}")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise DataValidationError(f"{what} {value!r} is not numeric") from exc
    if not number.is_finite():
        raise DataValidationError(f"{what} {value!r} is not finite")
    return number


@dataclass(frozen=True)
class FactEntry:
    """One reported value of one XBRL concept for one period in one filing."""

    taxonomy: str
    concept: str
    unit: str
    value: Decimal
    start: date | None
    end: date
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed: date
    accession: str
    frame: str | None

    @property
    def duration_days(self) -> int | None:
        return (self.end - self.start).days if self.start else None

    @property
    def basis(self) -> Basis:
        """Annual / quarterly / other, from duration (flows) or from the filing form (instants)."""
        days = self.duration_days
        if days is not None:
            if 350 <= days <= 380:
                return "annual"
            if 80 <= days <= 100:
                return "quarterly"
            return "other"  # half-year, nine-month year-to-date, etc.
        if self.form in ANNUAL_FORMS:
            return "annual"
        if self.form in QUARTERLY_FORMS:
            return "quarterly"
        return "other"

    @property
    def period_key(self) -> tuple[str, str, date | None, date]:
        return (self.concept, self.unit, self.start, self.end)


def parse_fact_entry(taxonomy: str, concept: str, unit: str, raw: Any) -> FactEntry:
    where = f"{taxonomy}/{concept}/{unit}"
    if not isinstance(raw, dict):
        raise DataValidationError(f"{where}: fact entry is not an object")
    for required in ("val", "end", "accn", "filed"):
        if required not in raw:
            raise DataValidationError(f"{where}: fact entry missing required field {required!r}")
    accession = raw["accn"]
    if not isinstance(accession, str) or not _ACCESSION.match(accession):
        raise DataValidationError(f"{where}: unexpected accession number {accession!r}")
    fy = raw.get("fy")
    if fy is not None and (isinstance(fy, bool) or not isinstance(fy, int)):
        raise DataValidationError(f"{where}: fy must be an integer, got {fy!r}")
    fp = raw.get("fp")
    form = raw.get("form")
    frame = raw.get("frame")
    for name, val in (("fp", fp), ("form", form), ("frame", frame)):
        if val is not None and not isinstance(val, str):
            raise DataValidationError(f"{where}: {name} must be a string, got {val!r}")
    start = parse_date(raw["start"], f"{where}: start") if raw.get("start") is not None else None
    end = parse_date(raw["end"], f"{where}: end")
    if start is not None and start > end:
        raise DataValidationError(f"{where}: period start {start} is after end {end}")
    return FactEntry(
        taxonomy=taxonomy,
        concept=concept,
        unit=unit,
        value=parse_number(raw["val"], f"{where}: val"),
        start=start,
        end=end,
        fiscal_year=fy,
        fiscal_period=fp,
        form=form,
        filed=parse_date(raw["filed"], f"{where}: filed"),
        accession=accession,
        frame=frame,
    )


@dataclass(frozen=True)
class FilingRecord:
    accession_no: str
    filing_date: date
    report_date: date | None
    form: str
    primary_document: str | None


@dataclass(frozen=True)
class SubmissionsInfo:
    cik: str
    name: str
    sic: str | None
    sic_description: str | None
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]
    filings: tuple[FilingRecord, ...]  # "recent" filings only; older filing pages are not fetched


@dataclass(frozen=True)
class FiscalPeriod:
    basis: Basis
    start: date | None
    end: date
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed: date
    accession: str
