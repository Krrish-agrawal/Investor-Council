from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from council.edgar.client import EdgarClient, _RateLimiter, read_cached_document
from council.edgar.facts import CompanyFactsSnapshot, identify_fiscal_periods, resolve_entries
from council.edgar.manifest import build_manifest, write_manifest
from council.edgar.metrics import lookup_metric
from council.edgar.models import normalize_cik, parse_fact_entry
from council.edgar.validate import parse_submissions, validate_companyfacts
from council.errors import (
    ConfigError,
    DataValidationError,
    EdgarCacheError,
    EdgarError,
    EdgarNotFoundError,
)
from tests import synthetic
from tests.conftest import FIXED_NOW, FakeSec

CIK = synthetic.SYNTHETIC_CIK


# ---------------- CIK + entry parsing ----------------


@pytest.mark.parametrize("raw, expected", [(320193, "0000320193"), ("320193", "0000320193"), ("CIK0000320193", "0000320193"), (" cik 12 ".replace(" ", ""), "0000000012")])
def test_normalize_cik(raw: object, expected: str) -> None:
    assert normalize_cik(raw) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5", "12345678901", "3.5"])
def test_normalize_cik_rejects_garbage(bad: str) -> None:
    with pytest.raises(DataValidationError):
        normalize_cik(bad)


def entry(**overrides: object) -> dict:
    base = {"end": "2024-12-31", "start": "2024-01-01", "val": 10, "accn": synthetic.ACC_FY24, "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-14"}
    base.update(overrides)
    return base


def test_parse_fact_entry_ok_and_basis_classification() -> None:
    annual = parse_fact_entry("us-gaap", "Revenues", "USD", entry())
    assert annual.value == Decimal(10) and annual.basis == "annual" and annual.duration_days == 365
    quarter = parse_fact_entry("us-gaap", "Revenues", "USD", entry(start="2025-01-01", end="2025-03-31", form="10-Q"))
    assert quarter.basis == "quarterly"
    ytd = parse_fact_entry("us-gaap", "Revenues", "USD", entry(start="2025-01-01", end="2025-06-30", form="10-Q"))
    assert ytd.basis == "other"
    instant_k = parse_fact_entry("us-gaap", "Assets", "USD", {k: v for k, v in entry().items() if k != "start"})
    assert instant_k.basis == "annual" and instant_k.duration_days is None
    instant_q = parse_fact_entry("us-gaap", "Assets", "USD", {**{k: v for k, v in entry().items() if k != "start"}, "form": "10-Q"})
    assert instant_q.basis == "quarterly"


def test_float_values_do_not_pick_up_binary_noise() -> None:
    assert parse_fact_entry("us-gaap", "EPS", "USD/shares", entry(val=0.1)).value == Decimal("0.1")


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"val": None}, "numeric"),
        ({"val": True}, "numeric"),
        ({"val": "NaN"}, "not finite"),
        ({"val": "abc"}, "not numeric"),
        ({"end": "12/31/2024"}, "YYYY-MM-DD"),
        ({"accn": "123"}, "accession"),
        ({"fy": "2024"}, "fy must be an integer"),
        ({"start": "2025-01-01"}, "after end"),
    ],
)
def test_parse_fact_entry_rejects_bad_values(overrides: dict, fragment: str) -> None:
    with pytest.raises(DataValidationError, match=fragment):
        parse_fact_entry("us-gaap", "Revenues", "USD", entry(**overrides))


@pytest.mark.parametrize("missing", ["val", "end", "accn", "filed"])
def test_parse_fact_entry_requires_core_fields(missing: str) -> None:
    raw = entry()
    del raw[missing]
    with pytest.raises(DataValidationError, match=missing):
        parse_fact_entry("us-gaap", "Revenues", "USD", raw)


# ---------------- document validation ----------------


def test_synthetic_companyfacts_validates() -> None:
    report = validate_companyfacts(synthetic.companyfacts(), expected_cik=CIK)
    assert report.ok and report.entries_checked == 9


@pytest.mark.parametrize(
    "path, value, fragment",
    [
        (["cik"], 123, "expected"),
        (["entityName"], "", "entityName"),
        (["facts"], {}, "facts"),
        (["facts", "us-gaap", "Revenues", "units"], "x", "units"),
        (["facts", "us-gaap", "Revenues", "units", "USD", 0, "accn"], "bad", "accession"),
    ],
)
def test_validate_companyfacts_rejects_malformed(path: list, value: object, fragment: str) -> None:
    with pytest.raises(DataValidationError, match=fragment):
        validate_companyfacts(synthetic.mutated(synthetic.companyfacts(), path, value), expected_cik=CIK)


def test_validate_rejects_non_objects_and_empty() -> None:
    with pytest.raises(DataValidationError):
        validate_companyfacts([], expected_cik=CIK)
    empty = synthetic.mutated(synthetic.companyfacts(), ["facts"], {"us-gaap": {}})
    with pytest.raises(DataValidationError, match="no fact entries"):
        validate_companyfacts(empty, expected_cik=CIK)


def test_parse_submissions_and_its_validation() -> None:
    info = parse_submissions(synthetic.submissions(), expected_cik=CIK)
    assert info.name == synthetic.ENTITY and info.sic == "7372" and info.tickers == ("SYNT",)
    assert [f.form for f in info.filings] == ["10-Q", "10-Q", "10-K"]
    assert info.filings[2].filing_date == date(2025, 2, 14) and info.filings[2].report_date == date(2024, 12, 31)
    broken = synthetic.mutated(synthetic.submissions(), ["filings", "recent", "form"], ["10-K"])
    with pytest.raises(DataValidationError, match="different lengths"):
        parse_submissions(broken, expected_cik=CIK)
    with pytest.raises(DataValidationError):
        parse_submissions({"cik": CIK, "name": "x"}, expected_cik=CIK)


# ---------------- facts, restatements, periods, metrics ----------------


@pytest.fixture
def snapshot(edgar_client: EdgarClient) -> CompanyFactsSnapshot:
    return CompanyFactsSnapshot(edgar_client.get_company_facts(CIK))


def test_restated_value_is_selected_latest_and_flagged_as_conflict(snapshot: CompanyFactsSnapshot) -> None:
    fy23 = snapshot.find("us-gaap", "Revenues", "USD", date(2023, 12, 31), period_start=date(2023, 1, 1))
    assert fy23 is not None
    assert fy23.selected.value == Decimal(1_010_000) and fy23.selected.accession == synthetic.ACC_FY24
    assert fy23.conflict and [a.value for a in fy23.conflicting_entries] == [Decimal(1_000_000)]


def test_identical_repeats_are_not_conflicts() -> None:
    a = parse_fact_entry("us-gaap", "Revenues", "USD", entry())
    b = parse_fact_entry("us-gaap", "Revenues", "USD", entry(accn=synthetic.ACC_Q1_25, filed="2025-05-10"))
    (resolved,) = resolve_entries([a, b])
    assert not resolved.conflict and resolved.selected.filed == date(2025, 5, 10)


def test_latest_by_basis(snapshot: CompanyFactsSnapshot) -> None:
    annual = snapshot.latest("us-gaap", "Revenues", "annual")
    quarterly = snapshot.latest("us-gaap", "Revenues", "quarterly")
    assert annual.selected.end == date(2024, 12, 31) and annual.selected.value == Decimal(1_200_000)
    assert quarterly.selected.end == date(2025, 3, 31)  # six-month YTD (basis 'other') is excluded
    assert snapshot.latest("us-gaap", "OperatingIncomeLoss", "annual") is None
    assert snapshot.latest("us-gaap", "Assets", "quarterly").selected.value == Decimal(5_100_000)


def test_identify_fiscal_periods(snapshot: CompanyFactsSnapshot) -> None:
    periods = identify_fiscal_periods(snapshot)
    assert periods.latest_annual.end == date(2024, 12, 31) and periods.latest_annual.form == "10-K"
    assert periods.latest_annual.filed == date(2025, 2, 14) and periods.latest_annual.accession == synthetic.ACC_FY24
    assert periods.latest_quarterly.end == date(2025, 3, 31) and periods.latest_quarterly.form == "10-Q"
    # The cover-page 'dei' fact is dated 2025-02-01; it must not be mistaken for a period end.
    assert date(2025, 2, 1) not in (periods.latest_annual.end, periods.latest_quarterly.end)


def test_metric_lookup_found_and_gap(snapshot: CompanyFactsSnapshot) -> None:
    found = lookup_metric(snapshot, "revenue", "annual")
    assert found.found and found.resolved.selected.concept == "Revenues"
    gap = lookup_metric(snapshot, "operating_income", "annual")
    assert not gap.found and "OperatingIncomeLoss" in gap.gap_text() and "Nothing was estimated" in gap.gap_text()
    assert lookup_metric(snapshot, "shares_outstanding", "annual").found  # dei taxonomy
    with pytest.raises(KeyError):
        lookup_metric(snapshot, "made_up_metric")


# ---------------- client: caching, errors, rate limit ----------------


def test_fetch_writes_cache_with_provenance_and_second_call_uses_it(edgar_client: EdgarClient, fake_sec: FakeSec, tmp_path: Path) -> None:
    first = edgar_client.get_company_facts(CIK)
    assert not first.from_cache and len(fake_sec.requests) == 1
    assert first.meta.url == f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
    assert first.meta.retrieved_at == FIXED_NOW and first.meta.status_code == 200
    assert first.meta.sha256 == hashlib.sha256(first.path.read_bytes()).hexdigest()
    second = edgar_client.get_company_facts(CIK)
    assert second.from_cache and len(fake_sec.requests) == 1
    refreshed = edgar_client.get_company_facts(CIK, refresh=True)
    assert not refreshed.from_cache and len(fake_sec.requests) == 2
    assert (tmp_path / "edgar" / f"CIK{CIK}" / "companyfacts.meta.json").exists()


def test_submissions_are_cached_separately(edgar_client: EdgarClient, fake_sec: FakeSec) -> None:
    doc = edgar_client.get_submissions(synthetic.SYNTHETIC_CIK.lstrip("0"))
    assert doc.meta.url.endswith(f"/submissions/CIK{CIK}.json") and doc.meta.kind == "submissions"


def test_requests_declare_a_user_agent_and_never_send_credentials(edgar_client: EdgarClient, fake_sec: FakeSec) -> None:
    edgar_client.get_company_facts(CIK)
    req = fake_sec.requests[0]
    assert req.headers["user-agent"] == "Test Suite test@example.com"
    assert "authorization" not in req.headers and "cookie" not in req.headers


def test_user_agent_is_required(tmp_path: Path) -> None:
    for bad in ("", "no contact info here"):
        with pytest.raises(ConfigError):
            EdgarClient(user_agent=bad, cache_dir=tmp_path)


def test_not_found(edgar_client: EdgarClient) -> None:
    with pytest.raises(EdgarNotFoundError):
        edgar_client.get_company_facts("1234567")


def test_forbidden_message_points_at_user_agent_and_rate_limit(tmp_path: Path) -> None:
    client = EdgarClient(user_agent="T t@example.com", cache_dir=tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(403)), sleep=lambda s: None)
    with pytest.raises(EdgarError, match="User-Agent"):
        client.get_company_facts(CIK)


def test_server_errors_are_retried_then_succeed(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json=synthetic.companyfacts())

    client = EdgarClient(user_agent="T t@example.com", cache_dir=tmp_path, transport=httpx.MockTransport(handler), sleep=lambda s: None, retries=2)
    assert client.get_company_facts(CIK).raw["entityName"] == synthetic.ENTITY and calls["n"] == 3


def test_persistent_server_errors_fail_clearly(tmp_path: Path) -> None:
    client = EdgarClient(user_agent="T t@example.com", cache_dir=tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(500)), sleep=lambda s: None, retries=1)
    with pytest.raises(EdgarError, match="failed after 2 attempts"):
        client.get_company_facts(CIK)


def test_invalid_responses_are_never_cached(tmp_path: Path) -> None:
    for body in (b"<html>not json</html>", json.dumps(synthetic.mutated(synthetic.companyfacts(), ["entityName"], "")).encode()):
        client = EdgarClient(user_agent="T t@example.com", cache_dir=tmp_path, transport=httpx.MockTransport(lambda r, b=body: httpx.Response(200, content=b)), sleep=lambda s: None)
        with pytest.raises(DataValidationError):
            client.get_company_facts(CIK)
    assert not list(tmp_path.rglob("*.json"))


def test_response_for_a_different_cik_is_rejected(tmp_path: Path) -> None:
    other = synthetic.mutated(synthetic.companyfacts(), ["cik"], 1)
    client = EdgarClient(user_agent="T t@example.com", cache_dir=tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=other)), sleep=lambda s: None)
    with pytest.raises(DataValidationError, match="expected"):
        client.get_company_facts(CIK)


def test_tampered_cache_is_refused_not_silently_replaced(edgar_client: EdgarClient) -> None:
    doc = edgar_client.get_company_facts(CIK)
    doc.path.write_text(doc.path.read_text().replace("1200000", "9999999"))
    with pytest.raises(EdgarCacheError, match="SHA-256"):
        edgar_client.get_company_facts(CIK)
    with pytest.raises(EdgarCacheError):
        read_cached_document(doc.path.parent.parent, CIK, "companyfacts")


def test_incomplete_cache_is_reported(edgar_client: EdgarClient) -> None:
    doc = edgar_client.get_company_facts(CIK)
    doc.path.with_name("companyfacts.meta.json").unlink()
    with pytest.raises(EdgarCacheError, match="Incomplete"):
        edgar_client.get_company_facts(CIK)


def test_load_cached_does_not_hit_the_network(edgar_client: EdgarClient, fake_sec: FakeSec) -> None:
    assert edgar_client.load_cached(CIK, "companyfacts") is None
    edgar_client.get_company_facts(CIK)
    n = len(fake_sec.requests)
    assert edgar_client.load_cached(CIK, "companyfacts").from_cache and len(fake_sec.requests) == n


def test_rate_limiter_spaces_requests() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = _RateLimiter(5, clock=lambda: now[0], sleep=sleep)  # 5 rps -> 0.2 s apart
    for _ in range(4):
        limiter.wait()
    assert sleeps == pytest.approx([0.2, 0.2, 0.2])
    with pytest.raises(ConfigError):
        _RateLimiter(10.5)
    with pytest.raises(ConfigError):
        _RateLimiter(0)


# ---------------- manifest ----------------


def test_manifest_lists_every_cached_document_with_provenance(edgar_client: EdgarClient, tmp_path: Path) -> None:
    edgar_client.get_company_facts(CIK)
    edgar_client.get_submissions(CIK)
    manifest = build_manifest(tmp_path / "edgar")
    assert manifest["data_mode"] == "FROZEN_SNAPSHOT"
    kinds = {d["kind"]: d for d in manifest["documents"]}
    assert set(kinds) == {"companyfacts", "submissions"}
    assert kinds["companyfacts"]["retrieved_at"] == FIXED_NOW.isoformat()
    assert kinds["companyfacts"]["source_url"].startswith("https://data.sec.gov/")
    path = write_manifest(tmp_path / "edgar")
    assert json.loads(path.read_text())["documents"]
