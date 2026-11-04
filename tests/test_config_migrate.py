from __future__ import annotations

from pathlib import Path

import pytest

from council import config
from council.db.migrate import discover_migrations, split_statements
from council.errors import ConfigError, DatabaseSetupError


# ---------------- config ----------------


def test_database_passwords_have_no_defaults(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="COUNCIL_DB_HUMAN_PASSWORD"):
        config.db_url("human")
    with pytest.raises(ConfigError, match="COUNCIL_DB_ADMIN_PASSWORD"):
        config.db_url("admin")
    assert config.db_password("agent", required=False) is None


def test_db_url_uses_environment_and_hides_the_password(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("COUNCIL_DB_HUMAN_PASSWORD", "s3cret!p@ss")
    clean_env.setenv("COUNCIL_DB_PORT", "4000")
    url = config.db_url("human")
    assert (url.username, url.host, url.port, url.database) == ("council_human", "127.0.0.1", 4000, "investor_council")
    assert url.password == "s3cret!p@ss"  # special characters survive (URL object, not string interpolation)
    assert "s3cret" not in repr(url) and "s3cret" not in str(url)


def test_bad_port_and_identifiers_are_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("COUNCIL_DB_HUMAN_PASSWORD", "x")
    clean_env.setenv("COUNCIL_DB_PORT", "not-a-number")
    with pytest.raises(ConfigError, match="COUNCIL_DB_PORT"):
        config.db_url("human")
    clean_env.setenv("COUNCIL_DB_NAME", "bad name; DROP DATABASE x")
    with pytest.raises(ConfigError, match="COUNCIL_DB_NAME"):
        config.db_name()
    clean_env.setenv("COUNCIL_DB_HUMAN_USER", "o'brien")
    with pytest.raises(ConfigError):
        config.db_user("human")


def test_sec_settings_require_a_declared_identity(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="COUNCIL_SEC_USER_AGENT"):
        config.sec_settings()
    clean_env.setenv("COUNCIL_SEC_USER_AGENT", "anonymous")
    with pytest.raises(ConfigError, match="contact email"):
        config.sec_settings()
    clean_env.setenv("COUNCIL_SEC_USER_AGENT", "Jane Doe jane@example.com")
    assert config.sec_settings().max_rps == 5.0


@pytest.mark.parametrize("value", ["0", "-1", "11", "fast"])
def test_sec_rate_limit_cannot_exceed_the_published_ceiling(clean_env: pytest.MonkeyPatch, value: str) -> None:
    clean_env.setenv("COUNCIL_SEC_USER_AGENT", "Jane jane@example.com")
    clean_env.setenv("COUNCIL_SEC_MAX_RPS", value)
    with pytest.raises(ConfigError):
        config.sec_settings()


def test_env_example_has_no_secrets() -> None:
    text = (Path(__file__).parent.parent / ".env.example").read_text()
    for line in text.splitlines():
        if "PASSWORD=" in line or "USER_AGENT=" in line:
            assert line.split("=", 1)[1].split("#")[0].strip() == "", line


# ---------------- migrations ----------------


def test_split_statements_handles_comments_quotes_and_semicolons() -> None:
    sql = """
    -- a comment; with a semicolon
    CREATE TABLE a (x VARCHAR(5) DEFAULT 'a;b');  -- trailing comment
    INSERT INTO a VALUES ("it's;ok");
    CREATE TABLE `we;ird` (id INT)
    """
    assert split_statements(sql) == [
        "CREATE TABLE a (x VARCHAR(5) DEFAULT 'a;b')",
        'INSERT INTO a VALUES ("it\'s;ok")',
        "CREATE TABLE `we;ird` (id INT)",
    ]


def test_bundled_migrations_are_well_formed() -> None:
    migrations = discover_migrations()
    assert [m.version for m in migrations] == [1]
    statements = split_statements(migrations[0].sql)
    assert len(statements) == 10 and all(s.startswith("CREATE TABLE IF NOT EXISTS") for s in statements)
    tables = [s.split()[5] for s in statements]
    assert tables == ["portfolios", "holdings", "research_sessions", "sources", "evidence_refs", "claims",
                      "claim_evidence", "submissions", "challenges", "dossiers"]


def test_bad_migration_names_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "oops.sql").write_text("SELECT 1")
    with pytest.raises(DatabaseSetupError, match="NNNN_name.sql"):
        discover_migrations(tmp_path)
