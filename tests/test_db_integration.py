"""Integration tests against a real MySQL 8 server (skipped if none is reachable).

Each test uses a throwaway database named ``council_test_*`` and, where accounts are needed,
uniquely named test accounts. The developer's real database and accounts are never touched.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from typer.testing import CliRunner

from council import config
from council.cli.main import app
from council.db.engine import make_engine
from council.db.grants import apply_grants
from council.db.migrate import apply_migrations, applied_versions, discover_migrations
from council.edgar.client import EdgarClient
from council.edgar.facts import CompanyFactsSnapshot
from council.errors import ClaimRuleError, CsvValidationError, DatabaseSetupError, EdgarCacheError, EvidenceError, NotFoundError
from council.evidence.freshness import FreshnessConfig
from council.evidence.service import (
    add_claim,
    get_claim,
    list_claims,
    list_evidence,
    record_fact_evidence,
    record_metric_evidence,
    rule_claim,
)
from council.portfolio.csv_ingest import parse_portfolio_csv_text
from council.portfolio.metrics import compute_metrics
from council.portfolio.repository import latest_portfolio_id, load_holdings, load_portfolio, save_portfolio
from council.portfolio.summary import build_shared_summary
from council.report.lint import lint_advice_language
from council.report.model import load_dossier_data
from council.report.render import render_dossier
from council.sessions import create_session, get_session, latest_session
from tests import synthetic
from tests.conftest import FIXED_NOW

pytestmark = pytest.mark.db

CIK = synthetic.SYNTHETIC_CIK
CSV = "ticker,shares,price,sector\nAAA,10,20,Tech\nBBB,5,40,Tech\nCCC,100,3,Health\nDDD,50,6,\n"
CFG = FreshnessConfig(456, 183, 30)


# ---------------- helpers ----------------


@pytest.fixture
def engine(mysql_admin: Engine, test_db: str) -> Iterator[Engine]:
    eng = create_engine(config.db_url("admin", with_database=False).set(database=test_db), future=True)
    yield eng
    eng.dispose()


def new_session(conn, *, session_date: date = date(2025, 6, 1), ticker: str = "AAA"):
    report = parse_portfolio_csv_text(CSV)
    portfolio, _ = save_portfolio(conn, report, name="t", origin="sample", price_as_of=date(2025, 5, 30))
    metrics = compute_metrics(load_holdings(conn, portfolio.id))
    summary = build_shared_summary(metrics, target_ticker=ticker, price_as_of=portfolio.price_as_of)
    return create_session(conn, portfolio_id=portfolio.id, target_ticker=ticker, thesis="Is it durable?", shared_summary=summary,
                          freshness_cfg=CFG.to_json(), session_date=session_date, target_cik=CIK)


@pytest.fixture
def snapshot(edgar_client: EdgarClient) -> CompanyFactsSnapshot:
    return CompanyFactsSnapshot(edgar_client.get_company_facts(CIK))


# ---------------- migrations ----------------


def test_migrations_apply_once_and_are_checksummed(engine: Engine, tmp_path: Path) -> None:
    assert apply_migrations(engine) == []  # the fixture already applied them
    assert set(applied_versions(engine)) == {1}
    original = discover_migrations()[0]
    (tmp_path / "0001_initial.sql").write_text(original.sql + "\n-- edited after being applied\n")
    with pytest.raises(DatabaseSetupError, match="changed after it was applied"):
        apply_migrations(engine, tmp_path)


def test_schema_has_the_ten_v02_tables(engine: Engine, test_db: str) -> None:
    with engine.connect() as c:
        tables = {r[0] for r in c.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = :d"), {"d": test_db})}
    assert tables == {"portfolios", "holdings", "research_sessions", "sources", "evidence_refs", "claims", "claim_evidence",
                      "submissions", "challenges", "dossiers", "schema_migrations"}


def test_database_check_constraints_back_up_the_python_rules(conn) -> None:
    session = new_session(conn)
    with pytest.raises(DBAPIError):
        conn.execute(text("INSERT INTO holdings (portfolio_id, ticker, shares, price) VALUES (:p, 'ZZZ', 1, 0)"), {"p": session.portfolio_id})
    with pytest.raises(DBAPIError):  # ASSUMPTION without falsifier
        conn.execute(text("INSERT INTO claims (code, session_id, agent, stage, claim_type, text) VALUES ('C-B9', :s, 'bull', 1, 'ASSUMPTION', 'x')"), {"s": session.id})


# ---------------- portfolio persistence ----------------


def test_portfolio_roundtrip_is_exact_and_reingest_is_idempotent(conn) -> None:
    report = parse_portfolio_csv_text("ticker,shares,price\nAAA,1.123456,10.1234\nBBB,3,0.0001\n")
    record, created = save_portfolio(conn, report, name="p", origin="user", price_as_of=None)
    assert created and record.excluded_rows == 0
    rows = load_holdings(conn, record.id)
    assert [(r.ticker, r.shares, r.price) for r in rows] == [("AAA", Decimal("1.123456"), Decimal("10.1234")), ("BBB", Decimal("3"), Decimal("0.0001"))]
    again, created_again = save_portfolio(conn, report, name="other name", origin="user", price_as_of=None)
    assert not created_again and again.id == record.id
    assert latest_portfolio_id(conn) == record.id
    with pytest.raises(NotFoundError):
        load_portfolio(conn, 9999)


def test_invalid_rows_block_storage_unless_partial_is_explicitly_allowed(conn) -> None:
    report = parse_portfolio_csv_text("ticker,shares,price\nAAA,1,1\nBAD,x,1\nCCC,2,2\n")
    with pytest.raises(CsvValidationError, match="1 invalid row"):
        save_portfolio(conn, report, name="p", origin="user", price_as_of=None)
    assert conn.execute(text("SELECT COUNT(*) FROM portfolios")).scalar_one() == 0
    record, _ = save_portfolio(conn, report, name="p", origin="user", price_as_of=None, allow_partial=True)
    assert record.excluded_rows == 1
    warnings = json.loads(conn.execute(text("SELECT ingest_warnings FROM portfolios WHERE id = :i"), {"i": record.id}).scalar_one())
    assert any("BAD" not in w["message"] and w["code"] == "invalid_value" for w in warnings)


# ---------------- sessions ----------------


def test_session_codes_increment_and_inputs_are_validated(conn) -> None:
    first = new_session(conn)
    assert first.code == "S-0001" and first.stage == 1 and first.data_mode == "FROZEN_SNAPSHOT" and first.status == "OPEN"
    assert first.shared_summary["target_ticker"] == "AAA" and first.freshness_cfg["label"].startswith("application heuristics")
    second = create_session(conn, portfolio_id=first.portfolio_id, target_ticker="bbb", thesis="x", shared_summary={}, freshness_cfg=CFG.to_json(), session_date=date(2025, 6, 1))
    assert second.code == "S-0002" and second.target_ticker == "BBB"
    assert latest_session(conn).code == "S-0002" and get_session(conn, "S-0001").id == first.id
    with pytest.raises(NotFoundError):
        get_session(conn, "S-0099")
    with pytest.raises(Exception, match="Invalid session code"):
        get_session(conn, "nope")
    with pytest.raises(Exception, match="Invalid target ticker"):
        create_session(conn, portfolio_id=first.portfolio_id, target_ticker="no spaces", thesis="x", shared_summary={}, freshness_cfg={}, session_date=date.today())
    with pytest.raises(Exception, match="thesis"):
        create_session(conn, portfolio_id=first.portfolio_id, target_ticker="AAA", thesis="  ", shared_summary={}, freshness_cfg={}, session_date=date.today())


# ---------------- evidence ----------------

FACT = dict(metric_name="Revenue", taxonomy="us-gaap", concept="Revenues", unit="USD")


def test_verified_evidence_carries_full_provenance(conn, snapshot) -> None:
    s = new_session(conn)
    e = record_fact_evidence(conn, s, added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1), **FACT)
    assert (e.code, e.verification, e.flag, e.value) == ("E-1", "VERIFIED", "NONE", Decimal("1200000.000000"))
    assert (e.fiscal_year, e.fiscal_period, e.form, e.filed_date, e.accession) == (2024, "FY", "10-K", date(2025, 2, 14), synthetic.ACC_FY24)
    assert (e.period_start, e.period_end, e.unit, e.concept) == (date(2024, 1, 1), date(2024, 12, 31), "USD", "Revenues")
    assert e.source_url == f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
    assert e.source_retrieved_at.replace(tzinfo=None) == FIXED_NOW.replace(tzinfo=None) and e.source_sha256 == snapshot.sha256


def test_sources_are_content_addressed_and_registered_once(conn, snapshot) -> None:
    s = new_session(conn)
    for _ in range(2):
        record_fact_evidence(conn, s, added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1), **FACT)
    assert conn.execute(text("SELECT COUNT(*) FROM sources")).scalar_one() == 1
    assert [e.code for e in list_evidence(conn, s.id)] == ["E-1", "E-2"]
    key = conn.execute(text("SELECT source_key FROM sources")).scalar_one()
    assert key == f"edgar:CIK{CIK}:companyfacts:{snapshot.sha256[:12]}"


def test_restatement_is_flagged_as_conflict_with_both_values_and_filing_dates(conn, snapshot) -> None:
    e = record_fact_evidence(conn, new_session(conn), added_by="bear", snapshot=snapshot, period_end=date(2023, 12, 31), period_start=date(2023, 1, 1), **FACT)
    assert e.flag == "CONFLICT" and e.verification == "VERIFIED" and e.value == Decimal("1010000.000000")
    assert "1010000" in e.flag_detail and "1000000" in e.flag_detail and "2024-02-15" in e.flag_detail and "2025-02-14" in e.flag_detail


def test_stale_flag_uses_the_session_dates_and_configured_heuristics(conn, snapshot) -> None:
    late = new_session(conn, session_date=date(2026, 11, 5))
    e = record_fact_evidence(conn, late, added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1), **FACT)
    assert e.flag == "STALE" and "heuristic" in e.flag_detail and "not accounting or regulatory standards" in e.flag_detail


def test_wrong_claimed_value_is_stored_as_failed_not_silently_corrected(conn, snapshot) -> None:
    e = record_fact_evidence(conn, new_session(conn), added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1),
                             claimed_value=Decimal("1300000"), **FACT)
    assert e.verification == "FAILED" and e.value == Decimal("1300000.000000") and "does not match" in e.verification_detail


def test_missing_fact_cannot_become_evidence(conn, snapshot) -> None:
    s = new_session(conn)
    with pytest.raises(EvidenceError, match="record a GAP"):
        record_fact_evidence(conn, s, added_by="bull", snapshot=snapshot, period_end=date(2019, 12, 31), **FACT)
    failed = record_fact_evidence(conn, s, added_by="bull", snapshot=snapshot, period_end=date(2019, 12, 31), claimed_value=Decimal(5), **FACT)
    assert failed.verification == "FAILED" and failed.accession is None  # a claimed figure with no source is visibly unverified


def test_altered_snapshot_cannot_be_cited(conn, snapshot) -> None:
    snapshot.document.path.write_text(snapshot.document.path.read_text().replace("1200000", "1200001"))
    with pytest.raises(EdgarCacheError):
        record_fact_evidence(conn, new_session(conn), added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1), **FACT)


# ---------------- claims ----------------


def test_claim_typing_rules(conn, snapshot) -> None:
    s = new_session(conn)
    good = record_fact_evidence(conn, s, added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1), **FACT)
    bad = record_fact_evidence(conn, s, added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1), claimed_value=Decimal(1), **FACT)

    with pytest.raises(ClaimRuleError, match="at least one evidence"):
        add_claim(conn, s, agent="bull", claim_type="FACT", text_value="Revenue grew")
    fact = add_claim(conn, s, agent="bull", claim_type="FACT", text_value="Revenue was 1.2m", evidence_codes=[good.code], rank_in_brief=1)
    assert (fact.code, fact.claim_type, fact.downgraded, fact.evidence_codes) == ("C-B1", "FACT", False, ("E-1",))
    downgraded = add_claim(conn, s, agent="bull", claim_type="FACT", text_value="Revenue was 1", evidence_codes=[bad.code])
    assert downgraded.claim_type == "UNVERIFIED" and downgraded.downgraded
    mixed = add_claim(conn, s, agent="bull", claim_type="FACT", text_value="x", evidence_codes=[bad.code, good.code])
    assert mixed.claim_type == "FACT"  # at least one verified reference is enough

    with pytest.raises(ClaimRuleError, match="falsifier"):
        add_claim(conn, s, agent="bear", claim_type="ASSUMPTION", text_value="Margins fall", basis=["C-B1"])
    with pytest.raises(ClaimRuleError, match="basis"):
        add_claim(conn, s, agent="bear", claim_type="ASSUMPTION", text_value="Margins fall", falsifier="Margins rise")
    assumption = add_claim(conn, s, agent="bear", claim_type="ASSUMPTION", text_value="Margins fall", basis=["C-B1"], falsifier="Margins rise two quarters")
    assert assumption.code == "C-X1" and assumption.basis == ["C-B1"]
    assert add_claim(conn, s, agent="bear", claim_type="UNVERIFIED", text_value="Churn rising").code == "C-X2"
    with pytest.raises(ClaimRuleError, match="Unknown claim type"):
        add_claim(conn, s, agent="bull", claim_type="OPINION", text_value="x")  # type: ignore[arg-type]
    with pytest.raises(ClaimRuleError, match="empty"):
        add_claim(conn, s, agent="bull", claim_type="UNVERIFIED", text_value="  ")
    with pytest.raises(NotFoundError):
        add_claim(conn, s, agent="bull", claim_type="FACT", text_value="x", evidence_codes=["E-99"])
    assert [c.code for c in list_claims(conn, s.id)] == ["C-B1", "C-B2", "C-B3", "C-X1", "C-X2"]


def test_metric_lookup_records_evidence_or_an_explicit_gap(conn, snapshot) -> None:
    s = new_session(conn)
    found = record_metric_evidence(conn, s, agent="bull", snapshot=snapshot, metric="revenue", basis="annual")
    assert found.evidence.verification == "VERIFIED" and found.gap_claim is None
    assert found.evidence.metric_name == "Revenue" and found.evidence.period_end == date(2024, 12, 31)
    missing = record_metric_evidence(conn, s, agent="bear", snapshot=snapshot, metric="operating_income", basis="annual")
    assert missing.evidence is None and missing.gap_claim.claim_type == "GAP" and missing.gap_claim.agent == "bear"
    assert "Nothing was estimated" in missing.gap_claim.text
    assert len(list_evidence(conn, s.id)) == 1  # a gap does not create fake evidence


def test_human_rulings(conn) -> None:
    s = new_session(conn)
    c = add_claim(conn, s, agent="bull", claim_type="UNVERIFIED", text_value="Mgmt is strong")
    ruled = rule_claim(conn, s, c.code, "reject", "No evidence offered")
    assert ruled.human_ruling == "reject" and ruled.human_note == "No evidence offered"
    assert get_claim(conn, s.id, c.code).human_ruling == "reject"
    with pytest.raises(ClaimRuleError):
        rule_claim(conn, s, c.code, "approve")  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        rule_claim(conn, s, "C-B99", "accept")


# ---------------- report from the database ----------------


def test_dossier_end_to_end_from_the_database(conn, snapshot) -> None:
    s = new_session(conn, session_date=date(2025, 6, 1))
    e1 = record_fact_evidence(conn, s, added_by="bull", snapshot=snapshot, period_end=date(2024, 12, 31), period_start=date(2024, 1, 1), **FACT)
    e2 = record_fact_evidence(conn, s, added_by="bear", snapshot=snapshot, period_end=date(2023, 12, 31), period_start=date(2023, 1, 1), **FACT)
    bull = add_claim(conn, s, agent="bull", claim_type="FACT", text_value="FY2024 revenue was 1,200,000 USD.", evidence_codes=[e1.code])
    bear = add_claim(conn, s, agent="bear", claim_type="FACT", text_value="FY2023 revenue was restated upward.", evidence_codes=[e2.code])
    record_metric_evidence(conn, s, agent="bear", snapshot=snapshot, metric="operating_income")
    rule_claim(conn, s, bear.code, "accept", "Restatement is real")
    conn.execute(text("INSERT INTO challenges (session_id, from_agent, target_claim_id, stance, restated, argument, counter_evidence) VALUES (:s, 'bear', :c, 'partly_agrees', 'FY24 revenue 1.2m', 'Agree on level, not trend', :ce)"),
                 {"s": s.id, "c": bull.id, "ce": json.dumps([e2.code])})

    data = load_dossier_data(conn, portfolio_id=s.portfolio_id, session=get_session(conn, s.code), human_note="Still thinking.")
    md = render_dossier(data, generated_at=FIXED_NOW)

    assert "Session:** S-0001" in md and "Is it durable?" in md
    assert "FY2024 revenue was 1,200,000 USD." in md and "accepted by the human" in md
    assert "| E-1 | Revenue | 1,200,000 | USD |" in md
    assert "CONFLICT" in md and "No operating income" not in md and "OperatingIncomeLoss" in md  # the GAP names what was tried
    assert "| bear | C-B1 | partly_agrees |" in md
    assert "> Still thinking." in md and "DATA MODE: FROZEN SNAPSHOT" in md
    assert "DDD" not in md and "Shares" not in md  # sanitised by default
    assert lint_advice_language(md) == []
    assert render_dossier(data, generated_at=FIXED_NOW) == md  # deterministic

    local = render_dossier(data, generated_at=FIXED_NOW, include_local_detail=True)
    assert "DDD" in local and "LOCAL ONLY" in local


# ---------------- accounts and the privacy boundary ----------------


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch, mysql_admin: Engine, test_db: str) -> Iterator[dict[str, str]]:
    """Uniquely named test accounts (apply_grants resets privileges, so never reuse the real ones)."""
    suffix = uuid.uuid4().hex[:8]
    names = {"human": f"t_human_{suffix}", "agent": f"t_agent_{suffix}"}
    monkeypatch.setenv("COUNCIL_DB_HUMAN_USER", names["human"])
    monkeypatch.setenv("COUNCIL_DB_AGENT_USER", names["agent"])
    monkeypatch.setenv("COUNCIL_DB_HUMAN_PASSWORD", "Human-" + suffix + "-pw")
    monkeypatch.setenv("COUNCIL_DB_AGENT_PASSWORD", "Agent-" + suffix + "-pw")
    monkeypatch.setenv("COUNCIL_DB_NAME", test_db)
    apply_grants(mysql_admin, test_db)
    yield names
    with mysql_admin.begin() as c:
        for user in names.values():
            c.execute(text(f"DROP USER IF EXISTS '{user}'@'%'"))


def test_agent_account_cannot_see_the_portfolio(engine: Engine, accounts: dict[str, str]) -> None:
    with engine.begin() as c:  # committed so other connections can see it
        report = parse_portfolio_csv_text(CSV)
        portfolio, _ = save_portfolio(c, report, name="p", origin="sample", price_as_of=None)
        summary = build_shared_summary(compute_metrics(load_holdings(c, portfolio.id)), target_ticker="AAA")
        session = create_session(c, portfolio_id=portfolio.id, target_ticker="AAA", thesis="t", shared_summary=summary, freshness_cfg=CFG.to_json(), session_date=date(2025, 6, 1))
    agent = make_engine("agent")
    human = make_engine("human")
    try:
        with agent.connect() as a:
            for forbidden in ("SELECT * FROM holdings", "SELECT * FROM portfolios", "SELECT * FROM dossiers",
                              "SELECT portfolio_id FROM research_sessions", "SELECT * FROM research_sessions"):
                with pytest.raises(DBAPIError, match="denied"):
                    a.execute(text(forbidden))
            # what it needs works
            row = a.execute(text("SELECT code, target_ticker, thesis, stage, shared_summary_json FROM research_sessions")).one()
            assert row[0] == "S-0001"
            assert "BBB" not in str(row[4])
            a.execute(text("INSERT INTO claims (code, session_id, agent, stage, claim_type, text) VALUES ('C-B1', :s, 'bull', 1, 'UNVERIFIED', 'x')"), {"s": session.id})
            # but it cannot rule on claims, rewrite, or delete
            with pytest.raises(DBAPIError, match="denied"):
                a.execute(text("INSERT INTO claims (code, session_id, agent, stage, claim_type, text, human_ruling) VALUES ('C-B2', :s, 'bull', 1, 'UNVERIFIED', 'y', 'accept')"), {"s": session.id})
            with pytest.raises(DBAPIError, match="denied"):
                a.execute(text("UPDATE claims SET text = 'tampered'"))
            with pytest.raises(DBAPIError, match="denied"):
                a.execute(text("DELETE FROM claims"))
            with pytest.raises(DBAPIError, match="denied"):
                a.execute(text("UPDATE research_sessions SET stage = 3"))
            a.commit()
        with human.connect() as h:  # the human account sees everything
            assert h.execute(text("SELECT COUNT(*) FROM holdings")).scalar_one() == 4
            assert h.execute(text("SELECT COUNT(*) FROM claims")).scalar_one() == 1
    finally:
        agent.dispose()
        human.dispose()


def test_grants_are_idempotent_and_agent_account_is_optional(monkeypatch: pytest.MonkeyPatch, mysql_admin: Engine, test_db: str, accounts: dict[str, str]) -> None:
    assert apply_grants(mysql_admin, test_db) == [accounts["human"], accounts["agent"]]
    monkeypatch.delenv("COUNCIL_DB_AGENT_PASSWORD")
    assert apply_grants(mysql_admin, test_db) == [accounts["human"]]


# ---------------- CLI end to end ----------------


def test_cli_end_to_end(monkeypatch: pytest.MonkeyPatch, accounts: dict[str, str], engine: Engine, tmp_path: Path) -> None:
    repo = Path(__file__).parent.parent
    monkeypatch.setenv("COUNCIL_FRESHNESS_CONFIG", str(repo / "config" / "freshness.yaml"))
    runner = CliRunner()

    def run(*args: str, ok: bool = True):
        result = runner.invoke(app, list(args))
        assert (result.exit_code == 0) == ok, f"{args}\nstdout={result.stdout}\nstderr={result.stderr}"
        return result

    # a bad file is rejected, reported line-by-line, and nothing is stored
    bad = tmp_path / "bad.csv"
    bad.write_text("ticker,shares,price\nAAA,1,1\nBBB,-4,2\n")
    result = run("human", "ingest", "--file", str(bad), ok=False)
    assert "line 3" in result.stderr and "must be positive" in result.stderr and "nothing was stored" in result.stderr
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM portfolios")).scalar_one() == 0

    sample = repo / "samples" / "portfolio.csv"
    out = run("human", "ingest", "--file", str(sample), "--sample", "--price-as-of", "2026-10-30").stdout
    assert "Stored: portfolio id=1" in out and "holdings=7" in out and "stays on this machine" in out
    assert "Already stored" in run("human", "ingest", "--file", str(sample), "--sample").stdout

    local = run("human", "summary").stdout
    assert "SYNF" in local and "29.48" in local and "HHI=1740.2" in local  # hand-checked: 7824 / 26537

    shared = json.loads(run("human", "summary", "--shared", "--target", "SYNA").stdout)
    assert shared["target_weight_pct"] == 8.4 and shared["holdings_count"] == 7
    assert not any(t in json.dumps(shared) for t in ("SYNB", "SYNF", "SYNG", "shares"))

    out = run("human", "session", "new", "--ticker", "SYNA", "--thesis", "Durable?", "--session-date", "2026-11-05").stdout
    assert "Created session S-0001" in out and "safe to paste" in out

    md = run("human", "report", "--session", "S-0001").stdout
    for heading in ("## 1. Portfolio overview", "## 6. Verified financial evidence", "## 9. Sources", "## 10. Human decision"):
        assert heading in md
    assert "SYNF" not in md  # sanitised

    target = tmp_path / "out" / "local.md"
    run("human", "report", "--local-detail", "--output", str(target))
    assert "SYNF" in target.read_text() and "LOCAL ONLY" in target.read_text()

    run("human", "report", "--session", "S-0001", "--save")
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM dossiers")).scalar_one() == 1
    run("human", "report", "--session", "S-0001", "--save", "--local-detail", ok=False)  # refuses to store local-only detail
    run("human", "rule", "S-0001", "C-B1", "accept", ok=False)  # no such claim yet: a clean error, not a traceback


def test_cli_db_init_creates_everything_from_scratch(monkeypatch: pytest.MonkeyPatch, mysql_admin: Engine) -> None:
    suffix = uuid.uuid4().hex[:8]
    db = f"council_test_init_{suffix}"
    users = [f"t_h_{suffix}", f"t_a_{suffix}"]
    monkeypatch.setenv("COUNCIL_DB_NAME", db)
    monkeypatch.setenv("COUNCIL_DB_HUMAN_USER", users[0])
    monkeypatch.setenv("COUNCIL_DB_AGENT_USER", users[1])
    monkeypatch.setenv("COUNCIL_DB_HUMAN_PASSWORD", "h-" + suffix)
    monkeypatch.setenv("COUNCIL_DB_AGENT_PASSWORD", "a-" + suffix)
    runner = CliRunner()
    try:
        first = runner.invoke(app, ["db", "init"])
        assert first.exit_code == 0, first.stderr
        assert "0001_initial" in first.stdout and "Accounts configured" in first.stdout
        second = runner.invoke(app, ["db", "init"])
        assert second.exit_code == 0 and "already up to date" in second.stdout
        status = runner.invoke(app, ["db", "status"])
        assert status.exit_code == 0 and "0001_initial: applied" in status.stdout and "dossiers" in status.stdout
    finally:
        with mysql_admin.begin() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS `{db}`"))
            for user in users:
                c.execute(text(f"DROP USER IF EXISTS '{user}'@'%'"))
