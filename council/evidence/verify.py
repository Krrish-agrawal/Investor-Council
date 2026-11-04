"""Deterministic verification utilities.

Verification establishes *provenance*: that a figure (or quote) really appears in the stored,
hash-checked snapshot. It does not establish that the source is correct, complete or current.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from council.edgar.facts import CompanyFactsSnapshot
from council.edgar.models import FactEntry
from council.errors import EdgarCacheError

Status = Literal["VERIFIED", "FAILED"]
MIN_QUOTE_LENGTH = 20


@dataclass(frozen=True)
class VerificationResult:
    status: Status
    detail: str
    matched: FactEntry | None = None

    @property
    def verified(self) -> bool:
        return self.status == "VERIFIED"


def verify_fact(
    snapshot: CompanyFactsSnapshot,
    *,
    taxonomy: str,
    concept: str,
    unit: str,
    period_end: date,
    value: Decimal,
    period_start: date | None = None,
    accession: str | None = None,
) -> VerificationResult:
    """Does the snapshot report exactly this value for this concept, unit and period?"""
    if not snapshot.has_concept(taxonomy, concept):
        return VerificationResult("FAILED", f"concept {taxonomy}:{concept} is not in the snapshot")
    entries = [
        e
        for e in snapshot.entries(taxonomy, concept, unit)
        if e.end == period_end and (period_start is None or e.start == period_start)
    ]
    if not entries:
        return VerificationResult(
            "FAILED", f"no {taxonomy}:{concept} ({unit}) value for a period ending {period_end.isoformat()}"
        )
    for entry in entries:
        if entry.value == value and (accession is None or entry.accession == accession):
            return VerificationResult("VERIFIED", f"matches filing {entry.accession} filed {entry.filed.isoformat()}", entry)
    reported = ", ".join(sorted({f"{e.value} (filing {e.accession})" for e in entries}))
    if accession is not None and any(e.value == value for e in entries):
        return VerificationResult("FAILED", f"value {value} was not reported in filing {accession}; reported in: {reported}")
    return VerificationResult("FAILED", f"value {value} does not match the snapshot; snapshot has {reported}")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def verify_quote(source_text: str, quote: str, *, min_length: int = MIN_QUOTE_LENGTH) -> VerificationResult:
    """Does ``quote`` appear verbatim (ignoring whitespace and case) in ``source_text``?"""
    needle = _normalise(quote)
    if len(needle) < min_length:
        return VerificationResult("FAILED", f"quote is shorter than {min_length} characters; too short to verify")
    if needle in _normalise(source_text):
        return VerificationResult("VERIFIED", "quote found verbatim in the stored source text")
    return VerificationResult("FAILED", "quote not found in the stored source text")


def verify_file_integrity(path: Path | str, expected_sha256: str) -> None:
    """Raise :class:`EdgarCacheError` if a snapshot file no longer matches its recorded hash."""
    file_path = Path(path)
    if not file_path.is_file():
        raise EdgarCacheError(f"Snapshot file is missing: {file_path}")
    actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise EdgarCacheError(f"{file_path} has changed since it was recorded (hash mismatch)")
