"""MySQL users and grants.

* ``human``: full access to the Investor Council database (used by ``council human ...``).
* ``agent``: research tables only. No access to ``portfolios``, ``holdings`` or ``dossiers`` and
  no UPDATE/DELETE anywhere. Used by the agent tooling that is added after kickoff.

This is defence in depth, not a hard security boundary: anything running as your OS user can read
whatever that user can, including ``.env`` (see docs/ARCHITECTURE.md section 8).

Accounts are created for host ``%`` because, with Docker's port mapping, MySQL sees connections
arriving from the Docker network rather than from 127.0.0.1. The container port is published on
127.0.0.1 only (docker-compose.yml), which is what actually restricts network access.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

from council import config

log = logging.getLogger(__name__)

HOST = "%"

# Columns an agent may read/insert. Holdings-related columns (portfolio_id) are deliberately absent.
SESSION_COLUMNS_READ = (
    "id, code, target_ticker, target_cik, target_sector, thesis, stage, status, "
    "shared_summary_json, data_mode, freshness_cfg_json, session_date"
)
CLAIM_COLUMNS_READ = (
    "id, code, session_id, agent, stage, claim_type, text, basis, falsifier, relevance, "
    "rank_in_brief, downgraded, human_ruling, human_note, created_at"
)
CLAIM_COLUMNS_INSERT = (
    "code, session_id, agent, stage, claim_type, text, basis, falsifier, relevance, "
    "rank_in_brief, downgraded"
)

# Tables an agent can both read and insert into.
AGENT_RW_TABLES = ("evidence_refs", "claim_evidence", "submissions", "challenges")


def _create_or_update_user(conn, user: str, password: str) -> None:
    conn.execute(
        text(f"CREATE USER IF NOT EXISTS '{user}'@'{HOST}' IDENTIFIED BY :pw"),
        {"pw": password},
    )
    conn.execute(text(f"ALTER USER '{user}'@'{HOST}' IDENTIFIED BY :pw"), {"pw": password})
    # Start from a clean slate so re-running init always converges to the intended grants.
    conn.execute(text(f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM '{user}'@'{HOST}'"))


def apply_grants(admin_engine: Engine, db: str, *, create_agent: bool = True) -> list[str]:
    """Create/refresh the human (and optionally agent) account. Returns the accounts configured."""
    config.validate_identifier(db, "database name")
    configured: list[str] = []

    human = config.db_user("human")
    human_pw = config.db_password("human") or ""
    with admin_engine.begin() as conn:
        _create_or_update_user(conn, human, human_pw)
        conn.execute(text(f"GRANT ALL PRIVILEGES ON `{db}`.* TO '{human}'@'{HOST}'"))
        configured.append(human)

    agent_pw = config.db_password("agent", required=False)
    if create_agent and agent_pw:
        agent = config.db_user("agent")
        grantee = f"'{agent}'@'{HOST}'"
        with admin_engine.begin() as conn:
            _create_or_update_user(conn, agent, agent_pw)
            conn.execute(text(f"GRANT SELECT ({SESSION_COLUMNS_READ}) ON `{db}`.research_sessions TO {grantee}"))
            conn.execute(text(f"GRANT SELECT ON `{db}`.sources TO {grantee}"))
            for table in AGENT_RW_TABLES:
                conn.execute(text(f"GRANT SELECT, INSERT ON `{db}`.{table} TO {grantee}"))
            conn.execute(text(f"GRANT SELECT ({CLAIM_COLUMNS_READ}) ON `{db}`.claims TO {grantee}"))
            conn.execute(text(f"GRANT INSERT ({CLAIM_COLUMNS_INSERT}) ON `{db}`.claims TO {grantee}"))
        configured.append(agent)
    elif create_agent:
        log.info("COUNCIL_DB_AGENT_PASSWORD not set; skipping the agent account")
    return configured
