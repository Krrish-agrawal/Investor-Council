"""Configuration from environment variables (optionally loaded from a local ``.env``).

No credential has a default value: a missing secret raises :class:`ConfigError` instead of
silently falling back to something guessable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv, load_dotenv
from sqlalchemy.engine import URL

from council.errors import ConfigError

Role = Literal["admin", "human", "agent"]

_IDENT = re.compile(r"^[A-Za-z0-9_]{1,32}$")
SEC_MAX_RPS_CEILING = 10.0  # SEC fair-access policy: max 10 requests/second

_loaded = False

# Agent mode: the agent tooling must never see the human's credentials. When active, every setting is
# read from ONE agent-specific file and nothing else (no process environment, no ``.env``), and the
# only database account that can be requested is ``agent``.
_agent_values: dict[str, str] | None = None
AGENT_ENV_FILENAME = ".council.env"
AGENT_ENV_VAR = "COUNCIL_AGENT_ENV_FILE"


def load_env() -> None:
    """Load ``.env`` from the working directory (or a parent). Real environment variables win."""
    global _loaded
    if _loaded:
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
    _loaded = True


def agent_mode() -> bool:
    return _agent_values is not None


def load_agent_env(path: Path | str | None = None) -> Path:
    """Switch to agent mode, reading settings only from ``.council.env`` in the working directory
    (or the file named by ``COUNCIL_AGENT_ENV_FILE``). Raises :class:`ConfigError` if it is missing."""
    global _agent_values
    from dotenv import dotenv_values

    chosen = Path(path) if path else Path(os.environ.get(AGENT_ENV_VAR) or Path.cwd() / AGENT_ENV_FILENAME)
    if not chosen.is_file():
        raise ConfigError(
            f"Agent settings file not found: {chosen}. Each agent directory needs a {AGENT_ENV_FILENAME} "
            "holding the restricted database account and COUNCIL_AGENT_ROLE (see docs/AGENT_DESIGN.md)."
        )
    _agent_values = {k: v for k, v in dotenv_values(chosen).items() if v is not None}
    return chosen


def reset_agent_mode() -> None:
    """Leave agent mode (used by tests)."""
    global _agent_values
    _agent_values = None


def _get(name: str, default: str | None = None) -> str | None:
    if _agent_values is not None:
        value = _agent_values.get(name)
        return default if value is None or value.strip() == "" else value.strip()
    load_env()
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _require(name: str, hint: str = "") -> str:
    value = _get(name)
    if value is None:
        suffix = f" {hint}" if hint else ""
        raise ConfigError(f"Environment variable {name} is not set.{suffix} See .env.example.")
    return value


def validate_identifier(value: str, what: str) -> str:
    """Names that are interpolated into SQL (database, users) must be plain identifiers."""
    if not _IDENT.match(value):
        raise ConfigError(f"{what} {value!r} must match [A-Za-z0-9_]{{1,32}}")
    return value


def db_name() -> str:
    return validate_identifier(_get("COUNCIL_DB_NAME", "investor_council") or "", "COUNCIL_DB_NAME")


def _check_role(role: Role) -> None:
    if _agent_values is not None and role != "agent":
        raise ConfigError("Agent mode may only use the restricted agent database account.")


def db_user(role: Role) -> str:
    _check_role(role)
    var, default = {
        "admin": ("COUNCIL_DB_ADMIN_USER", "root"),
        "human": ("COUNCIL_DB_HUMAN_USER", "council_human"),
        "agent": ("COUNCIL_DB_AGENT_USER", "council_agent"),
    }[role]
    return validate_identifier(_get(var, default) or "", var)


def db_password(role: Role, *, required: bool = True) -> str | None:
    _check_role(role)
    var = {
        "admin": "COUNCIL_DB_ADMIN_PASSWORD",
        "human": "COUNCIL_DB_HUMAN_PASSWORD",
        "agent": "COUNCIL_DB_AGENT_PASSWORD",
    }[role]
    return _require(var) if required else _get(var)


def db_url(role: Role, *, with_database: bool = True) -> URL:
    """SQLAlchemy URL for a role. ``URL`` hides the password in ``repr``/logs."""
    host = _get("COUNCIL_DB_HOST", "127.0.0.1") or "127.0.0.1"
    port_text = _get("COUNCIL_DB_PORT", "3307") or "3307"
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ConfigError(f"COUNCIL_DB_PORT must be an integer, got {port_text!r}") from exc
    return URL.create(
        "mysql+pymysql",
        username=db_user(role),
        password=db_password(role),
        host=host,
        port=port,
        database=db_name() if with_database else None,
        query={"charset": "utf8mb4"},
    )


def data_dir() -> Path:
    return Path(_get("COUNCIL_DATA_DIR", "data") or "data")


def edgar_dir() -> Path:
    return data_dir() / "edgar"


def freshness_config_path() -> Path:
    return Path(_get("COUNCIL_FRESHNESS_CONFIG", "config/freshness.yaml") or "config/freshness.yaml")


def log_level() -> str:
    return (_get("COUNCIL_LOG_LEVEL", "INFO") or "INFO").upper()


@dataclass(frozen=True)
class SecSettings:
    user_agent: str
    max_rps: float


def sec_settings() -> SecSettings:
    """EDGAR access settings. The declared User-Agent has no default on purpose."""
    user_agent = _require(
        "COUNCIL_SEC_USER_AGENT",
        'Set it to your own "Name contact@example.com"; the SEC asks automated clients to declare identity.',
    )
    if "@" not in user_agent:
        raise ConfigError('COUNCIL_SEC_USER_AGENT should include a contact email, e.g. "Jane Doe jane@example.com".')
    rps_text = _get("COUNCIL_SEC_MAX_RPS", "5") or "5"
    try:
        rps = float(rps_text)
    except ValueError as exc:
        raise ConfigError(f"COUNCIL_SEC_MAX_RPS must be a number, got {rps_text!r}") from exc
    if not 0 < rps <= SEC_MAX_RPS_CEILING:
        raise ConfigError(f"COUNCIL_SEC_MAX_RPS must be in (0, {SEC_MAX_RPS_CEILING}] (SEC limit is 10/s)")
    return SecSettings(user_agent=user_agent, max_rps=rps)


def agent_role() -> str:
    """The research role bound to this agent directory: ``bull`` or ``bear``."""
    value = _get("COUNCIL_AGENT_ROLE")
    if value not in ("bull", "bear"):
        raise ConfigError(f"COUNCIL_AGENT_ROLE must be 'bull' or 'bear' in {AGENT_ENV_FILENAME}, got {value!r}")
    return value
