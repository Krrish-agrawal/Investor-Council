"""Structural validation of EDGAR responses. Invalid data is rejected, never repaired."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from council.edgar.models import (
    FilingRecord,
    SubmissionsInfo,
    normalize_cik,
    parse_date,
    parse_fact_entry,
)
from council.errors import DataValidationError


@dataclass
class ValidationReport:
    entries_checked: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _cik_of(raw: dict[str, Any]) -> str:
    value = raw.get("cik")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DataValidationError(f"response has no usable 'cik' field (got {value!r})")
    return normalize_cik(value)


def validate_companyfacts(
    raw: Any, *, expected_cik: str | None = None, max_problems: int = 10
) -> ValidationReport:
    """Check every fact entry. Raises :class:`DataValidationError` if anything is wrong."""
    if not isinstance(raw, dict):
        raise DataValidationError("company facts response is not a JSON object")
    cik = _cik_of(raw)
    if expected_cik is not None and cik != normalize_cik(expected_cik):
        raise DataValidationError(f"response is for CIK {cik}, expected {normalize_cik(expected_cik)}")
    name = raw.get("entityName")
    if not isinstance(name, str) or not name.strip():
        raise DataValidationError("response has no 'entityName'")
    facts = raw.get("facts")
    if not isinstance(facts, dict) or not facts:
        raise DataValidationError("response has no 'facts' object")

    report = ValidationReport()
    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, dict):
            report.problems.append(f"{taxonomy}: not an object")
            continue
        for concept, body in concepts.items():
            units = body.get("units") if isinstance(body, dict) else None
            if not isinstance(units, dict):
                report.problems.append(f"{taxonomy}/{concept}: missing 'units' object")
                continue
            for unit, entries in units.items():
                if not isinstance(entries, list):
                    report.problems.append(f"{taxonomy}/{concept}/{unit}: entries are not a list")
                    continue
                for entry in entries:
                    report.entries_checked += 1
                    try:
                        parse_fact_entry(taxonomy, concept, unit, entry)
                    except DataValidationError as exc:
                        if len(report.problems) < max_problems:
                            report.problems.append(str(exc))
                        else:
                            report.problems.append("...")
                            raise DataValidationError(_summarise("company facts", report)) from None
    if report.problems:
        raise DataValidationError(_summarise("company facts", report))
    if report.entries_checked == 0:
        raise DataValidationError("company facts contain no fact entries")
    return report


def _summarise(what: str, report: ValidationReport) -> str:
    shown = "; ".join(report.problems[:5])
    return f"{what} failed validation ({len(report.problems)} problem(s), e.g. {shown})"


def parse_submissions(raw: Any, *, expected_cik: str | None = None) -> SubmissionsInfo:
    """Validate and parse a submissions document (recent filings only)."""
    if not isinstance(raw, dict):
        raise DataValidationError("submissions response is not a JSON object")
    cik = _cik_of(raw)
    if expected_cik is not None and cik != normalize_cik(expected_cik):
        raise DataValidationError(f"response is for CIK {cik}, expected {normalize_cik(expected_cik)}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DataValidationError("submissions response has no 'name'")

    recent = (raw.get("filings") or {}).get("recent")
    if not isinstance(recent, dict):
        raise DataValidationError("submissions response has no filings.recent object")
    accessions, dates, forms = (recent.get(k) for k in ("accessionNumber", "filingDate", "form"))
    for key, arr in (("accessionNumber", accessions), ("filingDate", dates), ("form", forms)):
        if not isinstance(arr, list):
            raise DataValidationError(f"filings.recent.{key} is missing or not a list")
    if not (len(accessions) == len(dates) == len(forms)):
        raise DataValidationError("filings.recent arrays have different lengths")
    report_dates = recent.get("reportDate")
    primary = recent.get("primaryDocument")
    for key, arr in (("reportDate", report_dates), ("primaryDocument", primary)):
        if arr is not None and (not isinstance(arr, list) or len(arr) != len(accessions)):
            raise DataValidationError(f"filings.recent.{key} does not match the other arrays")

    filings: list[FilingRecord] = []
    for i, accession in enumerate(accessions):
        if not isinstance(accession, str) or not isinstance(forms[i], str):
            raise DataValidationError(f"filings.recent entry {i} has a non-string accession or form")
        report_date = report_dates[i] if report_dates else ""
        document = primary[i] if primary else ""
        filings.append(
            FilingRecord(
                accession_no=accession,
                filing_date=parse_date(dates[i], f"filings.recent.filingDate[{i}]"),
                report_date=parse_date(report_date, f"filings.recent.reportDate[{i}]") if report_date else None,
                form=forms[i],
                primary_document=document or None,
            )
        )
    sic = raw.get("sic")
    return SubmissionsInfo(
        cik=cik,
        name=name.strip(),
        sic=str(sic) if sic not in (None, "") else None,
        sic_description=raw.get("sicDescription") or None,
        tickers=tuple(t for t in raw.get("tickers") or [] if isinstance(t, str)),
        exchanges=tuple(e for e in raw.get("exchanges") or [] if isinstance(e, str)),
        filings=tuple(filings),
    )
