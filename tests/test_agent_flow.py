"""End-to-end test of the agent tooling against a real MySQL server, as the real restricted account.

No LLM is involved: the test plays both researchers and the human through the real CLIs, which is exactly
what the Switch agents will do through their shells. Data is the synthetic EDGAR fixture (tests/synthetic.py).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from typer.testing import CliRunner

from council import config
from council.agent.cli import app as agent_app
from council.cli.main import app as council_app
from council.db.engine import make_engine
from council.edgar.client import EdgarClient, read_cached_document
from council.edgar.facts import CompanyFactsSnapshot
from council.evidence.freshness import FreshnessConfig
from council.evidence.service import register_snapshot_source
from council.portfolio.csv_ingest import parse_portfolio_csv_text
from council.portfolio.metrics import compute_metrics
from council.portfolio.repository import load_holdings, save_portfolio
from council.portfolio.summary import build_shared_summary
from council.sessions import create_session
from tests import synthetic

pytestmark = pytest.mark.db

CIK = synthetic.SYNTHETIC_CIK
CSV = "ticker,shares,price,sector\nSYNT,10,20,Tech\nPRIVA,5,40,Tech\nPRIVB,100,3,Health\nPRIVC,50,6,\n"
runner = CliRunner()


class World:
    """A throwaway database, two agent directories and helpers that run the real CLIs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, engine: Engine, tmp_path: Path, test_db: str, accounts: dict[str, str]) -> None:
        self.mp, self.engine, self.tmp, self.db = monkeypatch, engine, tmp_path, test_db
        self.repo = Path(__file__).parent.parent
        self.dirs = {role: tmp_path / "agents" / role for role in ("bull", "bear")}
        for role, directory in self.dirs.items():
            directory.mkdir(parents=True)
            (directory / ".council.env").write_text(
                f"COUNCIL_AGENT_ROLE={role}\nCOUNCIL_DB_HOST=127.0.0.1\nCOUNCIL_DB_PORT={config._get('COUNCIL_DB_PORT', '3307')}\n"
                f"COUNCIL_DB_NAME={test_db}\nCOUNCIL_DB_AGENT_USER={accounts['agent']}\n"
                f"COUNCIL_DB_AGENT_PASSWORD={config._get('COUNCIL_DB_AGENT_PASSWORD')}\nCOUNCIL_DATA_DIR={tmp_path}\n")
        monkeypatch.setenv("COUNCIL_FRESHNESS_CONFIG", str(self.repo / "config" / "freshness.yaml"))
        monkeypatch.setenv("COUNCIL_DATA_DIR", str(tmp_path))

    # --- running the real CLIs ---
    def agent(self, role: str, *args: str, ok: bool = True) -> Any:
        self.mp.chdir(self.dirs[role])
        result = runner.invoke(agent_app, list(args))
        config.reset_agent_mode()
        if ok:
            assert result.exit_code == 0, f"agent {role} {args}\nstdout={result.stdout}\nstderr={result.stderr}"
            return json.loads(result.stdout)
        assert result.exit_code != 0, f"agent {role} {args} should have failed:\n{result.stdout}"
        return result.stderr

    def human(self, *args: str, ok: bool = True) -> str:
        config.reset_agent_mode()
        self.mp.chdir(self.repo)
        result = runner.invoke(council_app, ["human", *args])
        if ok:
            assert result.exit_code == 0, f"human {args}\nstdout={result.stdout}\nstderr={result.stderr}"
            return result.stdout
        assert result.exit_code != 0, f"human {args} should have failed:\n{result.stdout}"
        return result.stderr

    # --- human-side setup done through the real code paths ---
    def create_session(self, session_date: date = date(2025, 6, 1)) -> str:
        with self.engine.begin() as conn:
            report = parse_portfolio_csv_text(CSV)
            portfolio, _ = save_portfolio(conn, report, name="p", origin="sample", price_as_of=date(2025, 5, 30))
            summary = build_shared_summary(compute_metrics(load_holdings(conn, portfolio.id)), target_ticker="SYNT", price_as_of=portfolio.price_as_of)
            session = create_session(conn, portfolio_id=portfolio.id, target_ticker="SYNT", thesis="Is SYNT durable?", shared_summary=summary,
                                     freshness_cfg=FreshnessConfig(456, 183, 30).to_json(), session_date=session_date, target_cik=CIK)
        return session.code

    def register_snapshot(self) -> None:
        cached = read_cached_document(self.tmp / "edgar", CIK, "companyfacts")
        with self.engine.begin() as conn:
            register_snapshot_source(conn, CompanyFactsSnapshot(cached))


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, engine: Engine, accounts: dict[str, str], test_db: str, tmp_path: Path, edgar_client: EdgarClient) -> World:
    edgar_client.get_company_facts(CIK)  # writes the synthetic snapshot to tmp_path/edgar
    yield World(monkeypatch, engine, tmp_path, test_db, accounts)
    config.reset_agent_mode()


@pytest.fixture
def engine(mysql_admin: Engine, test_db: str):
    eng = create_engine(config.db_url("admin", with_database=False).set(database=test_db), future=True)
    yield eng
    eng.dispose()


def run_stage_1(w: World, code: str) -> None:
    """Both researchers file evidence and claims and submit. Returns nothing; asserts as it goes."""
    ev = w.agent("bull", "evidence", "add", code, "--metric", "revenue", "--basis", "annual")
    assert ev["evidence"]["code"] == "E-1" and ev["evidence"]["verification"] == "VERIFIED" and ev["evidence"]["flag"] == "NONE"
    w.agent("bull", "claim", "add", code, "--type", "FACT", "--text", "FY2024 revenue was 1,200,000 USD.", "--evidence", "E-1", "--rank", "1")
    restated = w.agent("bull", "evidence", "add", code, "--concept", "Revenues", "--unit", "USD", "--period-end", "2023-12-31", "--period-start", "2023-01-01")
    assert restated["evidence"]["flag"] == "CONFLICT"
    w.agent("bull", "claim", "add", code, "--type", "FACT", "--text", "FY2023 revenue was 1,010,000 USD.", "--evidence", restated["evidence"]["code"], "--rank", "2")
    w.agent("bull", "claim", "add", code, "--type", "ASSUMPTION", "--text", "Growth continues.", "--basis", "C-B1", "--falsifier", "Revenue falls two years running.")
    w.agent("bull", "submit", code, "--summary", "Revenue grew; FY2023 was restated upward.")

    gap = w.agent("bear", "evidence", "add", code, "--metric", "operating_income", "--basis", "annual")
    assert gap["result"] == "gap" and gap["gap_claim"]["type"] == "GAP" and gap["gap_claim"]["code"] == "C-X1"
    w.agent("bear", "claim", "add", code, "--type", "UNVERIFIED", "--text", "Customer churn is rising.", "--rank", "1")
    w.agent("bear", "submit", code, "--summary", "No operating income is reported; churn is unsupported.")


# ----------------------------------------------------------------------------------------------------------


def test_agent_cli_never_loads_the_humans_env_and_can_only_use_the_agent_account(world: World, tmp_path: Path) -> None:
    (world.dirs["bull"] / ".env").write_text("CANARY_SECRET=leaked\nCOUNCIL_DB_HUMAN_PASSWORD=stolen\n")
    world.mp.chdir(world.dirs["bull"])
    config.load_agent_env()
    try:
        assert config._get("CANARY_SECRET") is None and config._get("COUNCIL_DB_HUMAN_PASSWORD") is None  # a nearby .env is ignored
        assert config.agent_mode() and config.agent_role() == "bull"
        for role in ("human", "admin"):
            with pytest.raises(config.ConfigError, match="restricted agent"):
                config.db_url(role)  # type: ignore[arg-type]
    finally:
        config.reset_agent_mode()
    me = world.agent("bull", "whoami")
    assert me["role"] == "bull" and me["db_user"].startswith("t_agent_") and "password" not in json.dumps(me).lower()


def test_agent_package_cannot_reach_holdings_or_human_code() -> None:
    """Importing the agent CLI must not pull in portfolio code, and its source never names the human accounts."""
    code = ("import sys, council.agent.cli; bad = [m for m in sys.modules if m.startswith(('council.portfolio', 'council.report', 'council.stages'))]; "
            "print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "", f"agent CLI imports human-only modules: {out}"
    import ast

    for path in (Path(__file__).parent.parent / "council" / "agent").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("council.portfolio", "council.report", "council.stages", "council.db.grants", "council.db.migrate")), (path.name, node.module)
                assert not any(a.name == "load_env" for a in node.names), (path.name, "load_env")
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("make_engine", "db_url", "db_password", "db_user"):
                roles = [a.value for a in node.args if isinstance(a, ast.Constant)]
                assert all(r == "agent" for r in roles), (path.name, roles)  # only the agent account is ever requested


def test_database_refuses_the_agent_account_direct_access_to_private_tables(world: World, accounts: dict[str, str]) -> None:
    world.create_session()
    world.mp.chdir(world.dirs["bull"])
    config.load_agent_env()
    try:
        engine = make_engine("agent")
        with engine.connect() as conn:
            for sql in ("SELECT * FROM holdings", "SELECT * FROM portfolios", "SELECT portfolio_id FROM research_sessions",
                        "UPDATE research_sessions SET stage = 3", "INSERT INTO sources (source_key, source_type, source_name, url, retrieved_at, content_sha256, snapshot_path) "
                        "VALUES ('x','FINANCIAL_STATEMENT','x','x',NOW(),REPEAT('a',64),'x')"):
                with pytest.raises(DBAPIError, match="denied"):
                    conn.execute(text(sql))
        engine.dispose()
    finally:
        config.reset_agent_mode()


def test_next_shows_only_the_sanitised_summary_and_never_holdings(world: World) -> None:
    world.register_snapshot()
    code = world.create_session()
    view = world.agent("bull", "next", code)
    blob = json.dumps(view)
    for private in ("PRIVA", "PRIVB", "PRIVC", "portfolio_id", "shares", "market_value", "cost"):
        assert private not in blob, private
    assert view["role"] == "bull" and view["stage"] == 1 and view["target"]["ticker"] == "SYNT" and view["thesis"] == "Is SYNT durable?"
    assert view["portfolio_summary_sanitised"]["holdings_count"] == 4 and view["data_mode"] == "FROZEN_SNAPSHOT"
    assert "submit" in view["allowed_commands_now"] and "brief show --other" not in view["allowed_commands_now"]
    assert view["data_available"][0]["cik"] == CIK and view["data_available"][0]["registered_as_source"] is True
    assert "No stock-price data" in json.dumps(world.agent("bull", "data", "show", "--cik", CIK))


def test_stage_validation(world: World) -> None:
    world.register_snapshot()
    code = world.create_session()
    # stage 1: the other researcher's brief is unreadable; challenges and final positions are not allowed yet
    assert "blind first pass" in world.agent("bull", "brief", "show", code, "--other", ok=False)
    assert "stage 1" in world.agent("bull", "challenge", "add", code, "--target", "C-X1", "--stance", "agrees", "--restated", "r", "--argument", "a", ok=False)
    assert "stage 1" in world.agent("bull", "final", code, "--json", '{"could_not_establish": ["x"]}', ok=False)
    # a brief needs at least one claim, and the summary is bounded
    assert "file at least one claim" in world.agent("bull", "submit", code, "--summary", "Nothing yet.", ok=False)
    world.agent("bull", "claim", "add", code, "--type", "UNVERIFIED", "--text", "Management is strong.")
    assert "limit is 150" in world.agent("bull", "submit", code, "--summary", " ".join(["word"] * 151), ok=False)
    # claim typing rules still apply through the CLI
    assert "at least one evidence" in world.agent("bull", "claim", "add", code, "--type", "FACT", "--text", "x", ok=False)
    assert "falsifier" in world.agent("bull", "claim", "add", code, "--type", "ASSUMPTION", "--text", "x", "--basis", "C-B1", ok=False)
    assert "Unknown claim type" in world.agent("bull", "claim", "add", code, "--type", "OPINION", "--text", "x", ok=False)
    world.agent("bull", "submit", code, "--summary", "A brief.")
    # work is frozen after submitting
    assert "frozen" in world.agent("bull", "submit", code, "--summary", "again", ok=False)
    assert "frozen" in world.agent("bull", "claim", "add", code, "--type", "UNVERIFIED", "--text", "late", ok=False)
    assert "frozen" in world.agent("bull", "evidence", "add", code, "--metric", "revenue", ok=False)
    # still blind until the human advances and the reader has submitted
    assert "blind first pass" in world.agent("bull", "brief", "show", code, "--other", ok=False)
    # unknown sessions and unregistered snapshots fail cleanly
    assert "not found" in world.agent("bull", "next", "S-0099", ok=False)


def test_unregistered_snapshot_cannot_be_cited_and_agents_cannot_register_one(world: World) -> None:
    code = world.create_session()  # snapshot cached on disk but NOT registered in the database
    err = world.agent("bull", "evidence", "add", code, "--metric", "revenue", ok=False)
    assert "not registered as a source" in err and "council human data register" in err
    world.human("data", "register", "--cik", CIK)
    assert world.agent("bull", "evidence", "add", code, "--metric", "revenue")["evidence"]["verification"] == "VERIFIED"


def test_evidence_is_verified_not_trusted(world: World) -> None:
    world.register_snapshot()
    code = world.create_session()
    wrong = world.agent("bull", "evidence", "add", code, "--concept", "Revenues", "--unit", "USD", "--period-end", "2024-12-31",
                        "--period-start", "2024-01-01", "--value", "1300000")
    assert wrong["evidence"]["verification"] == "FAILED"
    claim = world.agent("bull", "claim", "add", code, "--type", "FACT", "--text", "Revenue was 1.3m.", "--evidence", wrong["evidence"]["code"])
    assert claim["claim"]["type"] == "UNVERIFIED" and claim["claim"]["downgraded"] and "cannot be presented as a fact" in claim["warning"]
    assert "Give either --metric" in world.agent("bull", "evidence", "add", code, "--concept", "Revenues", ok=False)


def test_researchers_cannot_cite_each_others_evidence(world: World) -> None:
    world.register_snapshot()
    code = world.create_session()
    world.agent("bull", "evidence", "add", code, "--metric", "revenue")
    err = world.agent("bear", "claim", "add", code, "--type", "FACT", "--text", "Borrowed.", "--evidence", "E-1", ok=False)
    assert "other researcher" in err
    assert world.agent("bear", "evidence", "list", code)["evidence"] == []  # the other's evidence is hidden during the blind pass


def test_full_three_stage_workflow_with_the_ruling_gate(world: World) -> None:
    world.register_snapshot()
    code = world.create_session()
    run_stage_1(world, code)

    # --- human: status, then advance (refused until both have submitted; both have) ---
    status = world.human("status", code)
    assert "stage 1 (initial analysis)" in status and "unresolved" in status and "Both agents have submitted stage 1" in status
    assert "only move is to stage 2" in world.human("advance", code, "--to", "3", ok=False)
    world.human("advance", code, "--to", "2")

    # --- stage 2: the blind pass ends; each reads the other and challenges ---
    assert "Submit your own stage-1 brief" not in json.dumps(world.agent("bull", "next", code))
    other = world.agent("bull", "brief", "show", code, "--other")
    assert other["from"] == "bear" and {c["code"] for c in other["claims"]} == {"C-X1", "C-X2"}
    assert world.agent("bear", "brief", "show", code, "--other")["from"] == "bull"

    err = world.agent("bull", "challenge", "add", code, "--target", "C-X1", "--stance", "disputes", "--restated", "r", "--argument", "a", ok=False)
    assert "cannot be challenged" in err  # C-X1 is a GAP
    assert "only the other" in world.agent("bull", "challenge", "add", code, "--target", "C-B1", "--stance", "agrees", "--restated", "r", "--argument", "a", ok=False).lower()
    ch = world.agent("bull", "challenge", "add", code, "--target", "C-X2", "--stance", "disputes", "--restated", "Churn is rising.", "--argument", "No evidence offered.")
    assert ch["stance"] == "needs_evidence" and "needs counter-evidence" in ch["warning"]  # a bare dispute is downgraded
    assert "already challenged" in world.agent("bull", "challenge", "add", code, "--target", "C-X2", "--stance", "agrees", "--restated", "r", "--argument", "a", ok=False)
    world.agent("bull", "submit", code, "--summary", "Churn claim is unsupported.")

    ch = world.agent("bear", "challenge", "add", code, "--target", "C-B2", "--stance", "disputes", "--restated", "FY2023 restated up.",
                     "--argument", "The restatement undermines the trend.", "--counter-evidence", "E-2")
    assert ch["stance"] == "disputes"
    world.agent("bear", "challenge", "add", code, "--target", "C-B1", "--stance", "partly_agrees", "--restated", "FY24 revenue 1.2m.", "--argument", "Level is right.")
    world.agent("bear", "submit", code, "--summary", "Disputed the restated year; agreed on the level.")

    # --- human advances to stage 3; flagged claims now exist and none is resolved ---
    world.human("advance", code, "--to", "3")
    status = world.human("status", code)
    for flagged in ("C-B2", "C-X2"):
        assert flagged in status
    assert "C-B3" not in status  # an unchallenged, unflagged assumption needs no ruling
    assert "flagged claims: 2   unresolved (need an accept/reject ruling): 2" in status
    assert "unresolved (need an accept/reject ruling):" in status

    # --- stage 3: agents see challenges and rulings, then file final positions ---
    view = world.agent("bull", "next", code)
    assert view["stage"] == 3 and "final" in view["allowed_commands_now"]
    assert {c["claim"] for c in view["challenges_on_your_claims"]} == {"C-B1", "C-B2"}
    assert set(view["final_position_format"]) == {"summary", "concessions", "still_holds", "could_not_establish"}
    assert "not one of your claims" in world.agent("bull", "final", code, "--json", '{"concessions": [{"claim": "C-X2", "reason": "x"}]}', ok=False)
    world.agent("bull", "final", code, "--json", json.dumps({
        "summary": "Level holds; the trend is less certain.",
        "concessions": [{"claim": "C-B3", "reason": "Growth cannot be assumed after the restatement."}],
        "still_holds": [{"claim": "C-B1", "reason": "FY2024 revenue is verified."}], "could_not_establish": ["Operating margin"]}))
    assert "frozen" in world.agent("bull", "final", code, "--json", '{"could_not_establish": ["x"]}', ok=False)

    # --- finalize is gated: bear's final missing, then unresolved claims ---
    assert "bear has not filed a final position" in world.human("finalize", code, "--note", "mine", ok=False)
    world.agent("bear", "final", code, "--json", json.dumps({"concessions": [{"claim": "C-X2", "reason": "Unsupported."}], "could_not_establish": ["Churn data"]}))
    assert "decision note" in world.human("finalize", code, "--note", "  ", ok=False)
    err = world.human("finalize", code, "--note", "My view.", ok=False)
    assert "2 flagged claim(s) have no accept/reject ruling" in err and all(c in err for c in ("C-B2", "C-X2"))
    assert "FINAL" not in world.human("report", "--session", code).split("## 1.")[0]  # the draft says it is a draft

    draft = world.human("report", "--session", code)
    assert "DRAFT: 2 flagged claim(s) await the human's ruling (C-B2, C-X2)" in draft
    bull_section = draft.split("## 4.")[1].split("## 5.")[0]
    unresolved_block = bull_section.split("### UNRESOLVED")[1].split("###")[0]
    assert "C-B2" in unresolved_block and "cites evidence E-2 flagged CONFLICT" in unresolved_block  # unresolved, never supported
    for heading in ("### Supported by verified evidence (FACT); no flag raised", "### Assumptions (inferences, with what would prove them wrong); no flag raised"):
        if heading in bull_section:  # only the block under an unflagged-findings heading
            assert "- **C-B2**" not in bull_section.split(heading)[1].split("\n### ")[0]

    # 'needs_evidence' is not a resolution
    world.human("rule", code, "C-B2", "needs_evidence", "--note", "Show the restatement filing.")
    assert "C-B2" in world.human("finalize", code, "--note", "My view.", ok=False)
    world.human("rule", code, "C-B2", "accept", "--note", "Restatement understood.")
    world.human("rule", code, "C-B3", "reject", "--note", "Conceded by its author.")  # a human may rule on any claim
    world.human("rule", code, "C-X2", "reject", "--note", "No evidence.")

    out = world.tmp / "final.md"
    result = world.human("finalize", code, "--note", "The level looks durable; I will not rely on the growth assumption.", "-o", str(out))
    assert "finalized; FINAL dossier version 1 stored" in result
    final = out.read_text()
    assert "**FINAL.**" in final and "UNRESOLVED" not in final and "DRAFT" not in final.split("## 1.")[0]
    for needle in ("Brief (stage 1)", "Final position (stage 3)", "Growth cannot be assumed", "Operating margin", "Rejected by the human",
                   "The level looks durable", "FROZEN SNAPSHOT"):
        assert needle in final, needle
    for private in ("PRIVA", "PRIVB", "PRIVC"):
        assert private not in final  # the shareable dossier stays sanitised

    # --- after finalizing the session is closed to agents ---
    assert "FINALIZED" in world.agent("bull", "claim", "add", code, "--type", "UNVERIFIED", "--text", "late", ok=False)
    assert "FINALIZED" in world.human("finalize", code, "--note", "again", ok=False)
    with world.engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM dossiers")).scalar_one() == "FINAL"


def test_advance_rules(world: World) -> None:
    world.register_snapshot()
    code = world.create_session()
    assert "has not submitted stage 1" in world.human("advance", code, "--to", "2", ok=False)
    world.agent("bull", "claim", "add", code, "--type", "UNVERIFIED", "--text", "x")
    world.agent("bull", "submit", code, "--summary", "brief")
    err = world.human("advance", code, "--to", "2", ok=False)
    assert "bear has not submitted" in err  # only one of two submitted
    world.human("advance", code, "--to", "2", "--force")  # the sequential fallback / failed agent path
    assert "stage 2" in world.human("status", code)
    assert "only move is to stage 3" in world.human("advance", code, "--to", "2", ok=False)


def test_finalize_requires_stage_three(world: World) -> None:
    code = world.create_session()
    assert "finalize only at stage 3" in world.human("finalize", code, "--note", "too early", ok=False)
