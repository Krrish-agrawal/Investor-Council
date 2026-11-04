from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from council.evidence.freshness import FreshnessConfig
from council.evidence.service import ClaimRecord, EvidenceRecord
from council.portfolio.csv_ingest import HoldingRow
from council.portfolio.metrics import compute_metrics
from council.portfolio.repository import PortfolioRecord
from council.portfolio.summary import build_shared_summary
from council.report.lint import lint_advice_language
from council.report.model import ChallengeRow, DossierData
from council.report.render import render_dossier
from council.sessions import SessionRecord

NOW = datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc)
RETRIEVED = datetime(2026, 11, 4, 8, 0)
CFG = FreshnessConfig(456, 183, 30)

HOLDINGS = [
    HoldingRow(1, "AAA", Decimal(10), Decimal(20), "Tech"),
    HoldingRow(2, "BBB", Decimal(5), Decimal(40), "Tech"),
    HoldingRow(3, "SECRETCO", Decimal(100), Decimal(3), "Health"),
]
METRICS = compute_metrics(HOLDINGS)
SUMMARY = build_shared_summary(METRICS, target_ticker="AAA", price_as_of=date(2026, 10, 30))
PORTFOLIO = PortfolioRecord(1, "sample", "sample", "a" * 64, date(2026, 10, 30), 0, datetime(2026, 11, 4))
SESSION = SessionRecord(1, "S-0001", 1, "AAA", "0009999999", "Tech", "Is AAA durable? | with a pipe", 2, "OPEN", SUMMARY, CFG.to_json(), date(2026, 11, 5), "FROZEN_SNAPSHOT")


def evidence(code: str, *, verification: str = "VERIFIED", flag: str = "NONE", flag_detail: str | None = None, value: str = "1200000") -> EvidenceRecord:
    return EvidenceRecord(
        id=1, code=code, session_id=1, added_by="bull", metric_name="Revenue", taxonomy="us-gaap", concept="Revenues", unit="USD",
        period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), fiscal_year=2025, fiscal_period="FY", form="10-K",
        filed_date=date(2026, 2, 14), accession="0009999999-26-000001", value=Decimal(value), verification=verification,
        verification_detail="matches filing" if verification == "VERIFIED" else "value does not match the snapshot",
        flag=flag, flag_detail=flag_detail, source_name="SEC EDGAR (data.sec.gov)",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json", source_retrieved_at=RETRIEVED, source_sha256="b" * 64,
    )


def claim(code: str, agent: str, ctype: str, text: str, *, ev: tuple[str, ...] = (), ruling: str | None = None, note: str | None = None,
          falsifier: str | None = None, basis: list[str] | None = None, downgraded: bool = False) -> ClaimRecord:
    return ClaimRecord(id=1, code=code, session_id=1, agent=agent, stage=1, claim_type=ctype, text=text, basis=basis, falsifier=falsifier,
                       relevance=None, rank_in_brief=None, downgraded=downgraded, human_ruling=ruling, human_note=note, evidence_codes=ev)


def data(**kw) -> DossierData:
    base = dict(portfolio=PORTFOLIO, metrics=METRICS, shared_summary=SUMMARY, session=SESSION, freshness=CFG)
    base.update(kw)
    return DossierData(**base)


def render(d: DossierData, **kw) -> str:
    return render_dossier(d, generated_at=NOW, **kw)


FULL = data(
    claims=(
        claim("C-B1", "bull", "FACT", "Revenue was 1.2m in FY2025.", ev=("E-1",), ruling="accept"),
        claim("C-B2", "bull", "ASSUMPTION", "Growth continues.", falsifier="Two quarters of decline.", basis=["C-B1"]),
        claim("C-B3", "bull", "UNVERIFIED", "Management is strong."),
        claim("C-B4", "bull", "GAP", "No operating income concept in the snapshot."),
        claim("C-X1", "bear", "FACT", "Revenue restated for FY2024.", ev=("E-2",), ruling="needs_evidence"),
        claim("C-X2", "bear", "UNVERIFIED", "Customer churn is rising.", ruling="reject", note="No support"),
        claim("C-X3", "bear", "UNVERIFIED", "Was a FACT.", ev=("E-3",), downgraded=True),
    ),
    evidence=(
        evidence("E-1"),
        evidence("E-2", flag="CONFLICT", flag_detail="selected 1010000 vs 1000000", value="1010000"),
        evidence("E-3", verification="FAILED", value="999"),
        evidence("E-4", flag="STALE", flag_detail="period ended long ago [application heuristics, not accounting or regulatory standards]"),
    ),
    challenges=(ChallengeRow("bear", "C-B1", "disputes", "Bull says revenue 1.2m", "See restatement", ("E-2",)),),
    human_note="My own note.",
)


def test_all_required_sections_are_present_in_order() -> None:
    md = render(FULL)
    headings = [line for line in md.splitlines() if line.startswith("## ")]
    assert headings == [
        "## 1. Portfolio overview", "## 2. Sector allocation", "## 3. Concentration analysis",
        "## 4. Positive arguments (Bull Researcher)", "## 5. Negative arguments (Bear Researcher)",
        "## 6. Verified financial evidence", "## 7. Missing information", "## 8. Limitations", "## 9. Sources", "## 10. Human decision",
    ]


def test_rendering_is_deterministic() -> None:
    assert render(FULL) == render(FULL)
    assert render(FULL, include_local_detail=True) == render(FULL, include_local_detail=True)


def test_sanitised_dossier_leaks_no_holdings_detail() -> None:
    md = render(FULL)
    assert "SECRETCO" not in md and "BBB" not in md  # other tickers
    for forbidden in ("Shares", "Market value", "Total portfolio value", "Positions (local only)", "LOCAL ONLY"):
        assert forbidden not in md
    assert "AAA" in md  # the research target is not secret


def test_local_detail_version_contains_positions_and_a_loud_warning() -> None:
    md = render(FULL, include_local_detail=True)
    assert "SECRETCO" in md and "Positions (local only)" in md and "LOCAL ONLY" in md
    assert "Total portfolio value (from user-supplied prices): 700.00" in md


def test_frozen_data_banner_and_disclaimer() -> None:
    md = render(FULL)
    assert "not financial advice" in md and "FROZEN SNAPSHOT" in md and "not live" in md
    assert "retrieved 2026-11-04 (UTC)" in md and "newer filings may exist" in md


def test_verified_evidence_table_has_all_provenance_fields_and_excludes_failures() -> None:
    md = render(FULL)
    section = md.split("## 6. Verified financial evidence")[1].split("## 7.")[0]
    for needle in ("E-1", "Revenue", "1,200,000", "USD", "2025-01-01 to 2025-12-31", "2025 FY (as reported on the filing)", "10-K",
                   "2026-02-14", "0009999999-26-000001", "https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json", "2026-11-04 08:00:00"):
        assert needle in section, needle
    assert "E-3" not in section  # FAILED verification is not evidence


def test_missing_information_lists_gaps_failures_flags_and_standing_gap() -> None:
    section = render(FULL).split("## 7. Missing information")[1].split("## 8.")[0]
    assert "C-B4" in section and "No operating income concept" in section
    assert "E-3" in section and "verification FAILED" in section and "Not treated as evidence" in section
    assert "E-2" in section and "CONFLICT" in section and "E-4" in section and "STALE" in section
    assert "C-X1" in section and "asked for more evidence" in section
    assert "Awaiting a human ruling: C-B2, C-B3" in section
    assert "No stock-price or market-data source" in section


def test_claims_are_grouped_by_type_and_never_blend_facts_with_unverified() -> None:
    md = render(FULL)
    bull = md.split("## 4.")[1].split("## 5.")[0]
    assert "Supported by verified evidence (FACT)" in bull and "C-B1" in bull and "accepted by the human" in bull
    assert "Assumptions" in bull and "Two quarters of decline." in bull and "Basis: C-B1" in bull
    assert "Unverified (not presented as fact)" in bull and "C-B3" in bull
    assert "C-B4" not in bull  # GAP claims live under Missing information
    bear = md.split("## 5.")[1].split("## 6.")[0]
    assert "Rejected by the human" in bear and "C-X2" in bear and "No support" in bear
    assert "Downgraded from FACT" in bear


def test_rejected_claims_leave_the_live_sections() -> None:
    bear = render(FULL).split("## 5.")[1].split("## 6.")[0]
    live_part = bear.split("Rejected by the human")[0]
    assert "C-X2" not in live_part


def test_empty_agent_sections_state_the_gap_instead_of_inventing_text() -> None:
    md = render(data())
    assert md.count("No research has been filed by this agent") == 2
    assert "No claims have been filed yet" in md and "No verified financial evidence has been recorded" in md
    assert "No external sources have been cited yet" in md


def test_challenge_table_is_rendered() -> None:
    md = render(FULL)
    assert "### Challenge round" in md and "| bear | C-B1 | disputes |" in md


def test_pipes_and_newlines_in_text_cannot_break_tables() -> None:
    md = render(FULL)
    assert "Is AAA durable? \\| with a pipe" in md


def test_limitations_state_the_configured_heuristics_with_their_label() -> None:
    lim = render(FULL).split("## 8. Limitations")[1].split("## 9.")[0]
    assert "456 days" in lim and "183 days" in lim and "30 days" in lim
    assert "application heuristics, not accounting or regulatory standards" in lim
    assert "frozen snapshot" in lim and "provenance" in lim


def test_sources_table_lists_provenance_and_withholds_the_csv_fingerprint_when_shareable() -> None:
    src = render(FULL).split("## 9. Sources")[1].split("## 10.")[0]
    assert "SEC EDGAR (data.sec.gov)" in src and "bbbbbbbbbbbbbbbb" in src  # snapshot hash prefix: public-source provenance
    assert "aaaaaaaaaaaa" not in src and "neither the file nor its fingerprint" in src  # CSV hash: private, withheld
    local_src = render(FULL, include_local_detail=True).split("## 9. Sources")[1].split("## 10.")[0]
    assert "content hash aaaaaaaaaaaa" in local_src and "the file itself is not included" in local_src


def _exact_variants(value: Decimal) -> set[str]:
    return {format(value.normalize(), "f"), format(value.normalize(), ",f"), format(value, "f"), format(value, ",f"),
            format(value.quantize(Decimal("0.01")), "f"), format(value.quantize(Decimal("0.01")), ",f")}


def test_sanitised_outputs_contain_no_private_values_but_local_detail_does() -> None:
    """Derive every private value from the holdings and search the shareable outputs for it."""
    import json
    import re

    # Distinctive numbers, so a match cannot be a coincidence with a count or a percentage.
    holdings = [
        HoldingRow(1, "AAA", Decimal("123.45"), Decimal("67.89"), "Tech"),
        HoldingRow(2, "SECRETCO", Decimal("987.654"), Decimal("41.37"), "Health"),
        HoldingRow(3, "HIDDEN2", Decimal("55.5"), Decimal("208.75"), None),
    ]
    metrics = compute_metrics(holdings)
    summary = build_shared_summary(metrics, target_ticker="AAA", price_as_of=date(2026, 10, 30))
    shareable = data(metrics=metrics, shared_summary=summary)

    forbidden: dict[str, str] = {}
    for h in holdings:
        if h.ticker != "AAA":  # AAA is the research target; its ticker is shared
            forbidden[h.ticker] = f"ticker {h.ticker}"
        for v in _exact_variants(h.shares) | {str(h.shares)}:
            forbidden[v] = f"shares of {h.ticker}"
        for v in _exact_variants(h.price) | {str(h.price)}:
            forbidden[v] = f"price of {h.ticker}"
        for v in _exact_variants(h.shares * h.price):
            forbidden[v] = f"market value of {h.ticker}"
    for v in _exact_variants(metrics.total_value):
        forbidden[v] = "total value"

    def scan(text: str) -> list[str]:
        hits = []
        for token, why in forbidden.items():
            numeric = token.replace(".", "").replace(",", "").isdigit()
            pattern = rf"(?<![\w.,-]){re.escape(token)}(?![\w.]|,\d)" if numeric else re.escape(token)
            if re.search(pattern, text):
                hits.append(f"{token} ({why})")
        return hits

    assert scan(json.dumps(summary)) == []
    assert scan(render(shareable)) == []
    assert scan(render(shareable, include_local_detail=True)), "control: the checker must be able to see leaks"


def test_human_decision_is_never_auto_filled() -> None:
    assert "never fills this field" in render(data())
    assert "> My own note." in render(FULL)


def test_portfolio_only_dossier_without_a_session() -> None:
    summary = build_shared_summary(METRICS)
    md = render(data(session=None, shared_summary=summary, freshness=None))
    assert "Session:** none" in md and "no research target selected" in md
    assert "No research session" in md
    assert "Freshness thresholds, when used, are application heuristics" in md


def test_partial_portfolio_warning() -> None:
    partial = build_shared_summary(METRICS, target_ticker="AAA", excluded_rows=2)
    md = render(data(shared_summary=partial, portfolio=replace(PORTFOLIO, excluded_rows=2)))
    assert "partial portfolio" in md and "2 invalid row(s)" in md


def test_unknown_overlap_is_stated_not_guessed() -> None:
    s = build_shared_summary(METRICS, target_ticker="ZZZ")
    assert "not computed because the target's sector label is unknown" in render(data(shared_summary=s))


def test_dossier_contains_no_advice_language() -> None:
    assert lint_advice_language(render(FULL)) == []
    assert lint_advice_language(render(FULL, include_local_detail=True)) == []


# ---------------- lint ----------------


@pytest.mark.parametrize(
    "text",
    [
        "You should buy this stock now.", "We recommend selling before earnings.", "This is a strong buy.",
        "Our price target is 50.", "A buy recommendation.", "Sell immediately", "guaranteed returns", "I suggest you hold",
    ],
)
def test_lint_catches_obvious_advice(text: str) -> None:
    assert lint_advice_language(text), text


@pytest.mark.parametrize("text", ["Share buyback programme announced.", "The company sells software.", "Buyers of the product churn.", "Holding company structure."])
def test_lint_ignores_innocent_text(text: str) -> None:
    assert lint_advice_language(text) == []
