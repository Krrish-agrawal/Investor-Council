"""SYNTHETIC test fixtures shaped like SEC EDGAR responses.

Everything here is invented for tests: the company, the CIK (9999999) and every number. None of it
is real company or market data and it must never be used outside tests.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SYNTHETIC_CIK = "0009999999"
ENTITY = "SYNTHETIC TEST CORP (fixture, not real data)"

ACC_FY23 = "0009999999-24-000001"
ACC_FY24 = "0009999999-25-000001"
ACC_Q1_25 = "0009999999-25-000002"
ACC_Q2_25 = "0009999999-25-000003"


def _fact(val: Any, end: str, accn: str, filed: str, form: str, fy: int, fp: str, start: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}
    if start:
        entry["start"] = start
    return entry


def companyfacts() -> dict[str, Any]:
    """Synthetic companyfacts document.

    * Revenues: FY2023 was reported at 1,000,000 and RESTATED to 1,010,000 in the FY2024 10-K
      (a CONFLICT), plus FY2024, a Q1-2025 quarter and a six-month year-to-date value (basis "other").
    * No OperatingIncomeLoss concept at all (so that metric is a GAP).
    """
    return {
        "cik": 9999999,
        "entityName": ENTITY,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            _fact(1_000_000, "2023-12-31", ACC_FY23, "2024-02-15", "10-K", 2023, "FY", "2023-01-01"),
                            _fact(1_010_000, "2023-12-31", ACC_FY24, "2025-02-14", "10-K", 2024, "FY", "2023-01-01"),
                            _fact(1_200_000, "2024-12-31", ACC_FY24, "2025-02-14", "10-K", 2024, "FY", "2024-01-01"),
                            _fact(330_000, "2025-03-31", ACC_Q1_25, "2025-05-10", "10-Q", 2025, "Q1", "2025-01-01"),
                            _fact(700_000, "2025-06-30", ACC_Q2_25, "2025-08-08", "10-Q", 2025, "Q2", "2025-01-01"),
                        ]
                    },
                },
                "NetIncomeLoss": {
                    "label": "Net income",
                    "units": {"USD": [_fact(150_000, "2024-12-31", ACC_FY24, "2025-02-14", "10-K", 2024, "FY", "2024-01-01")]},
                },
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            _fact(5_000_000, "2024-12-31", ACC_FY24, "2025-02-14", "10-K", 2024, "FY"),
                            _fact(5_100_000, "2025-03-31", ACC_Q1_25, "2025-05-10", "10-Q", 2025, "Q1"),
                        ]
                    },
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "label": "Shares outstanding",
                    "units": {"shares": [_fact(10_000_000, "2025-02-01", ACC_FY24, "2025-02-14", "10-K", 2024, "FY")]},
                }
            },
        },
    }


def submissions() -> dict[str, Any]:
    return {
        "cik": SYNTHETIC_CIK,
        "name": ENTITY,
        "sic": "7372",
        "sicDescription": "Services-Prepackaged Software (synthetic)",
        "tickers": ["SYNT"],
        "exchanges": ["SYNTH"],
        "filings": {
            "recent": {
                "accessionNumber": [ACC_Q2_25, ACC_Q1_25, ACC_FY24],
                "filingDate": ["2025-08-08", "2025-05-10", "2025-02-14"],
                "reportDate": ["2025-06-30", "2025-03-31", "2024-12-31"],
                "form": ["10-Q", "10-Q", "10-K"],
                "primaryDocument": ["q2.htm", "q1.htm", "k.htm"],
            }
        },
    }


def mutated(raw: dict[str, Any], path: list[Any], value: Any) -> dict[str, Any]:
    """Deep copy with ``raw[path...] = value`` applied (``...`` deletes the key)."""
    clone = deepcopy(raw)
    node = clone
    for key in path[:-1]:
        node = node[key]
    if value is ...:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return clone
