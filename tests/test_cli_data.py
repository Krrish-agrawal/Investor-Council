"""CLI tests that need no database: EDGAR cache inspection, manifest, and clean failures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from council.cli.main import app
from council.edgar.client import EdgarClient
from tests import synthetic

runner = CliRunner()


@pytest.fixture
def cached(clean_env: pytest.MonkeyPatch, tmp_path: Path, edgar_client: EdgarClient) -> Path:
    edgar_client.get_company_facts(synthetic.SYNTHETIC_CIK)
    edgar_client.get_submissions(synthetic.SYNTHETIC_CIK)
    clean_env.setenv("COUNCIL_DATA_DIR", str(tmp_path))  # edgar_client wrote to tmp_path/edgar
    return tmp_path


def test_inspect_describes_a_cached_company_without_network(cached: Path) -> None:
    result = runner.invoke(app, ["human", "data", "inspect", "--cik", "9999999"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert synthetic.ENTITY in out and "CIK0009999999" in out
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json" in out
    assert "latest annual period: ends 2024-12-31, filed 2025-02-14, form 10-K" in out
    assert "latest quarterly period: ends 2025-03-31" in out
    assert "SIC: 7372" in out and "recent filings: 3 (older filings not fetched)" in out


def test_manifest_command_writes_frozen_data_manifest(cached: Path) -> None:
    result = runner.invoke(app, ["human", "data", "manifest"])
    assert result.exit_code == 0, result.stderr
    manifest = json.loads((cached / "edgar" / "MANIFEST.json").read_text())
    assert manifest["data_mode"] == "FROZEN_SNAPSHOT" and len(manifest["documents"]) == 2


def test_inspect_of_an_uncached_company_is_a_clean_error(cached: Path) -> None:
    result = runner.invoke(app, ["human", "data", "inspect", "--cik", "12345"])
    assert result.exit_code == 1 and "not cached" in result.stderr and "Traceback" not in result.stderr


def test_fetch_refuses_to_run_without_a_declared_identity(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("COUNCIL_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["human", "data", "fetch", "--cik", "320193"])
    assert result.exit_code == 1
    assert "COUNCIL_SEC_USER_AGENT" in result.stderr and "your own" in result.stderr
    assert not list(tmp_path.rglob("*.json"))  # nothing was requested or written


def test_invalid_cik_is_a_clean_error(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("COUNCIL_SEC_USER_AGENT", "Jane jane@example.com")
    result = runner.invoke(app, ["human", "data", "fetch", "--cik", "not-a-cik"])
    assert result.exit_code == 1 and "not a valid CIK" in result.stderr


def test_missing_database_settings_fail_with_guidance(clean_env: pytest.MonkeyPatch) -> None:
    result = runner.invoke(app, ["human", "summary"])
    assert result.exit_code == 1 and "COUNCIL_DB_HUMAN_PASSWORD" in result.stderr and ".env.example" in result.stderr


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and "investor-council" in result.stdout


# ---------------- agent working directories ----------------


def test_agents_init_writes_only_the_restricted_account_and_never_the_humans_secrets(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = Path(__file__).parent.parent
    clean_env.setenv("COUNCIL_DB_AGENT_PASSWORD", "agent-pw-123")
    clean_env.setenv("COUNCIL_DB_HUMAN_PASSWORD", "HUMAN-SECRET-456")
    clean_env.setenv("COUNCIL_DB_ADMIN_PASSWORD", "ADMIN-SECRET-789")
    clean_env.setenv("COUNCIL_DATA_DIR", str(tmp_path / "data"))
    target = tmp_path / "agents"
    result = runner.invoke(app, ["human", "agents", "init", "--dir", str(target), "--switch-dir", str(repo / "switch")])
    assert result.exit_code == 0, result.stderr
    for role, folder in (("bull", "bull-researcher"), ("bear", "bear-researcher")):
        d = target / folder
        env = (d / ".council.env").read_text()
        assert f"COUNCIL_AGENT_ROLE={role}" in env and "COUNCIL_DB_AGENT_PASSWORD=agent-pw-123" in env
        assert f"COUNCIL_DATA_DIR={tmp_path / 'data'}" in env  # absolute
        for secret in ("HUMAN-SECRET-456", "ADMIN-SECRET-789", "HUMAN_PASSWORD", "ADMIN"):
            assert secret not in env and secret not in (d / "CLAUDE.md").read_text()
        assert oct((d / ".council.env").stat().st_mode & 0o777) == "0o600"
        assert (d / "council-agent").stat().st_mode & 0o111  # executable wrapper
        claude = (d / "CLAUDE.md").read_text()
        assert "./council-agent next S-XXXX" in claude and ("Bull Researcher" if role == "bull" else "Bear Researcher") in claude
    again = runner.invoke(app, ["human", "agents", "init", "--dir", str(target)])
    assert again.exit_code == 1 and "--force" in again.stderr  # never silently overwrites


def test_agents_init_needs_the_agent_password(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = runner.invoke(app, ["human", "agents", "init", "--dir", str(tmp_path / "a")])
    assert result.exit_code == 1 and "COUNCIL_DB_AGENT_PASSWORD" in result.stderr
