from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from council.edgar.client import EdgarClient
from council.edgar.facts import CompanyFactsSnapshot
from council.edgar.models import parse_fact_entry
from council.errors import ConfigError, EdgarCacheError
from council.evidence.freshness import LABEL, FreshnessConfig, assess_freshness, load_freshness_config
from council.evidence.verify import verify_fact, verify_file_integrity, verify_quote
from tests import synthetic

CIK = synthetic.SYNTHETIC_CIK
CFG = FreshnessConfig(annual_max_age_days=456, quarterly_max_age_days=183, snapshot_max_age_days=30)
RETRIEVED = datetime(2025, 5, 20, tzinfo=timezone.utc)


def fact(**kw):
    raw = {"end": "2024-12-31", "start": "2024-01-01", "val": 1, "accn": synthetic.ACC_FY24, "form": "10-K", "filed": "2025-02-14", "fy": 2024, "fp": "FY"}
    raw.update(kw)
    return parse_fact_entry("us-gaap", "Revenues", "USD", raw)


# ---------------- freshness config ----------------


def test_bundled_config_loads_and_is_labelled_as_heuristics() -> None:
    cfg = load_freshness_config(Path(__file__).parent.parent / "config" / "freshness.yaml")
    assert (cfg.annual_max_age_days, cfg.quarterly_max_age_days, cfg.snapshot_max_age_days) == (456, 183, 30)
    assert cfg.to_json()["label"] == LABEL and "not accounting or regulatory standards" in LABEL
    assert FreshnessConfig.from_json(cfg.to_json()) == cfg


@pytest.mark.parametrize(
    "yaml_text, fragment",
    [
        ("annual_max_age_days: 1\nquarterly_max_age_days: 1\n", "snapshot_max_age_days"),
        ("annual_max_age_days: 0\nquarterly_max_age_days: 1\nsnapshot_max_age_days: 1\n", "positive integer"),
        ("annual_max_age_days: 'x'\nquarterly_max_age_days: 1\nsnapshot_max_age_days: 1\n", "positive integer"),
        ("annual_max_age_days: 1\nquarterly_max_age_days: 1\nsnapshot_max_age_days: 1\nsurprise: 1\n", "unknown key"),
        ("- not\n- a mapping\n", "mapping"),
        ("a: [unclosed", "not valid YAML"),
    ],
)
def test_invalid_freshness_configs_are_rejected(tmp_path: Path, yaml_text: str, fragment: str) -> None:
    path = tmp_path / "f.yaml"
    path.write_text(yaml_text)
    with pytest.raises(ConfigError, match=fragment):
        load_freshness_config(path)


def test_missing_freshness_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_freshness_config(tmp_path / "nope.yaml")


# ---------------- freshness assessment ----------------


def test_fresh_fact_is_not_flagged() -> None:
    a = assess_freshness(fact(), retrieved_at=RETRIEVED, session_date=date(2025, 6, 1), cfg=CFG)
    assert a.flag == "NONE" and a.detail is None and a.fact_age_days == 152 and a.snapshot_age_days == 12


def test_old_annual_fact_is_stale_and_message_labels_the_heuristic() -> None:
    a = assess_freshness(fact(), retrieved_at=RETRIEVED, session_date=date(2026, 11, 5), cfg=CFG)
    assert a.flag == "STALE" and "674 days" in a.detail and "heuristic" in a.detail and LABEL in a.detail


def test_thresholds_are_configurable_and_use_the_right_basis() -> None:
    quarter = fact(start="2025-01-01", end="2025-03-31", form="10-Q")  # basis quarterly, limit 183
    session = date(2025, 10, 31)  # 214 days after 2025-03-31
    assert assess_freshness(quarter, retrieved_at=datetime(2025, 10, 30, tzinfo=timezone.utc), session_date=session, cfg=CFG).flag == "STALE"
    relaxed = FreshnessConfig(456, 400, 30)
    assert assess_freshness(quarter, retrieved_at=datetime(2025, 10, 30, tzinfo=timezone.utc), session_date=session, cfg=relaxed).flag == "NONE"
    annual_same_age = fact(end="2025-03-31", start="2024-04-01")  # annual basis, 214 days old, limit 456
    assert assess_freshness(annual_same_age, retrieved_at=datetime(2025, 10, 30, tzinfo=timezone.utc), session_date=session, cfg=CFG).flag == "NONE"


def test_old_snapshot_is_flagged_even_if_the_period_is_recent() -> None:
    a = assess_freshness(fact(end="2025-05-31", start="2024-06-01"), retrieved_at=RETRIEVED, session_date=date(2025, 8, 1), cfg=CFG)
    assert a.flag == "STALE" and "snapshot retrieved 2025-05-20" in a.detail


def test_future_period_relative_to_session_is_not_negative_age() -> None:
    a = assess_freshness(fact(), retrieved_at=RETRIEVED, session_date=date(2024, 1, 1), cfg=CFG)
    assert a.fact_age_days == 0 and a.snapshot_age_days == 0


# ---------------- fact verification ----------------


@pytest.fixture
def snapshot(edgar_client: EdgarClient) -> CompanyFactsSnapshot:
    return CompanyFactsSnapshot(edgar_client.get_company_facts(CIK))


def test_verified_when_value_and_period_match(snapshot: CompanyFactsSnapshot) -> None:
    r = verify_fact(snapshot, taxonomy="us-gaap", concept="Revenues", unit="USD", period_end=date(2024, 12, 31), value=Decimal(1_200_000))
    assert r.verified and r.matched.accession == synthetic.ACC_FY24 and "filed 2025-02-14" in r.detail


def test_accession_can_be_pinned(snapshot: CompanyFactsSnapshot) -> None:
    kw = dict(taxonomy="us-gaap", concept="Revenues", unit="USD", period_end=date(2023, 12, 31), period_start=date(2023, 1, 1))
    assert verify_fact(snapshot, value=Decimal(1_000_000), accession=synthetic.ACC_FY23, **kw).verified  # original filing
    pinned_wrong = verify_fact(snapshot, value=Decimal(1_000_000), accession=synthetic.ACC_FY24, **kw)
    assert not pinned_wrong.verified and "was not reported in filing" in pinned_wrong.detail


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"value": Decimal(1_200_001)}, "does not match the snapshot"),
        ({"period_end": date(2022, 12, 31)}, "no us-gaap:Revenues"),
        ({"concept": "OperatingIncomeLoss"}, "not in the snapshot"),
        ({"unit": "EUR"}, "no us-gaap:Revenues"),
    ],
)
def test_failures_explain_why(snapshot: CompanyFactsSnapshot, kwargs: dict, fragment: str) -> None:
    base = dict(taxonomy="us-gaap", concept="Revenues", unit="USD", period_end=date(2024, 12, 31), value=Decimal(1_200_000))
    base.update(kwargs)
    result = verify_fact(snapshot, **base)
    assert not result.verified and result.status == "FAILED" and fragment in result.detail


def test_close_but_wrong_value_never_verifies(snapshot: CompanyFactsSnapshot) -> None:
    r = verify_fact(snapshot, taxonomy="us-gaap", concept="Revenues", unit="USD", period_end=date(2024, 12, 31), value=Decimal("1200000.01"))
    assert not r.verified


# ---------------- quotes and file integrity ----------------

TEXT = "The Company's   revenue\n depends on a small number of customers, which creates concentration risk."


def test_quote_verification_ignores_whitespace_and_case() -> None:
    assert verify_quote(TEXT, "revenue depends on a SMALL number of customers").verified


def test_quote_must_actually_appear_and_be_long_enough() -> None:
    assert not verify_quote(TEXT, "revenue is guaranteed to grow every single year").verified
    short = verify_quote(TEXT, "revenue")
    assert not short.verified and "too short" in short.detail


def test_file_integrity(tmp_path: Path) -> None:
    import hashlib

    f = tmp_path / "s.json"
    f.write_text("{}")
    verify_file_integrity(f, hashlib.sha256(b"{}").hexdigest())
    with pytest.raises(EdgarCacheError, match="changed"):
        verify_file_integrity(f, "0" * 64)
    with pytest.raises(EdgarCacheError, match="missing"):
        verify_file_integrity(tmp_path / "gone.json", "0" * 64)
