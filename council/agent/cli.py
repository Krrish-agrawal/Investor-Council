"""``council-agent`` / ``council agent``: the commands a research agent runs.

Run as the restricted database account, configured only by ``.council.env`` in the agent's directory
(``COUNCIL_AGENT_ROLE=bull|bear``, the agent DB account, ``COUNCIL_DATA_DIR``). This module imports nothing
from ``council.portfolio`` and never reads the human's ``.env``. Output is JSON on stdout; errors go to stderr
with exit code 1.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from council import config
from council.agent import service
from council.cli.common import cli_errors, parse_iso_date
from council.db.engine import make_engine
from council.errors import CouncilError
from council.evidence.service import list_claims, list_evidence
from council.logging_setup import configure_logging
from council.sessions import get_agent_session

app = typer.Typer(help="Research-agent commands (restricted database account; JSON output).", no_args_is_help=True)
data_app = typer.Typer(help="Frozen SEC EDGAR snapshots (read-only).", no_args_is_help=True)
evidence_app = typer.Typer(help="Register verified evidence.", no_args_is_help=True)
claim_app = typer.Typer(help="File typed claims.", no_args_is_help=True)
brief_app = typer.Typer(help="Read the other researcher's filed brief.", no_args_is_help=True)
challenge_app = typer.Typer(help="Challenge the other researcher's claims (stage 2).", no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(evidence_app, name="evidence")
app.add_typer(claim_app, name="claim")
app.add_typer(brief_app, name="brief")
app.add_typer(challenge_app, name="challenge")

SessionArg = Annotated[str, typer.Argument(help="Session code, e.g. S-0001.")]


@app.callback()
def _agent_callback() -> None:
    """Enter agent mode before anything else: settings come only from .council.env."""
    config.load_agent_env()
    configure_logging("WARNING")


def _out(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _data_dir() -> Path:
    raw = config._get("COUNCIL_DATA_DIR")
    if not raw:
        raise CouncilError("COUNCIL_DATA_DIR must be set (absolute path) in .council.env")
    path = Path(raw)
    if not path.is_absolute():
        raise CouncilError("COUNCIL_DATA_DIR must be an absolute path in .council.env")
    return path


def _with_session(code: str, work: Callable[[Any, Any, str], Any], *, write: bool = True) -> None:
    """Run ``work(conn, session, role)`` as the agent account in one transaction."""
    role = config.agent_role()
    engine = make_engine("agent")
    try:
        with engine.begin() as conn:
            session = get_agent_session(conn, code)
            _out(work(conn, session, role))
    finally:
        engine.dispose()


@app.command("next")
@cli_errors
def next_cmd(session: SessionArg) -> None:
    """Where the session stands, what to do now, and the sanitised portfolio summary. Run this first."""
    data_dir = Path(config._get("COUNCIL_DATA_DIR") or "") if config._get("COUNCIL_DATA_DIR") else None
    _with_session(session, lambda c, s, r: service.next_view(c, s, r, data_dir))  # type: ignore[arg-type]


@data_app.command("list")
@cli_errors
def data_list(session: SessionArg) -> None:
    """Frozen snapshots available in the dataset."""
    _with_session(session, lambda c, s, r: {"snapshots": service.list_snapshots(c, _data_dir())})


@data_app.command("show")
@cli_errors
def data_show(cik: Annotated[Optional[str], typer.Option("--cik", help="Default: the session's target CIK.")] = None,
              session: Annotated[Optional[str], typer.Argument(help="Session code (to default the CIK).")] = None) -> None:
    """Curated metrics for a company: latest annual and quarterly value with provenance."""
    if cik:
        _out(service.show_snapshot(_data_dir(), cik))
        return
    if not session:
        raise CouncilError("Give --cik or a session code.")
    _with_session(session, lambda c, s, r: service.show_snapshot(_data_dir(), s.target_cik or _missing_cik()))


def _missing_cik() -> str:
    raise CouncilError("This session has no target CIK; pass --cik.")


@evidence_app.command("add")
@cli_errors
def evidence_add(
    session: SessionArg,
    metric: Annotated[Optional[str], typer.Option("--metric", help="Curated metric, e.g. revenue, net_income (see `data show`).")] = None,
    basis: Annotated[str, typer.Option("--basis", help="annual or quarterly (with --metric).")] = "annual",
    cik: Annotated[Optional[str], typer.Option("--cik")] = None,
    concept: Annotated[Optional[str], typer.Option("--concept", help="XBRL concept, e.g. Revenues.")] = None,
    taxonomy: Annotated[str, typer.Option("--taxonomy")] = "us-gaap",
    unit: Annotated[Optional[str], typer.Option("--unit")] = None,
    period_end: Annotated[Optional[str], typer.Option("--period-end", help="YYYY-MM-DD")] = None,
    period_start: Annotated[Optional[str], typer.Option("--period-start", help="YYYY-MM-DD (flow concepts)")] = None,
    value: Annotated[Optional[str], typer.Option("--value", help="A figure you claim; it is stored as FAILED if the snapshot differs.")] = None,
    metric_name: Annotated[Optional[str], typer.Option("--metric-name")] = None,
) -> None:
    """Register evidence from the frozen snapshot (verified automatically). A metric that is not there becomes a GAP."""
    try:
        claimed = Decimal(value) if value is not None else None
    except InvalidOperation:
        raise typer.BadParameter(f"--value {value!r} is not a number") from None
    pe: date | None = parse_iso_date(period_end, "--period-end")
    ps: date | None = parse_iso_date(period_start, "--period-start")
    _with_session(session, lambda c, s, r: service.add_evidence(
        c, s, r, _data_dir(), cik=cik, metric=metric, basis=basis, taxonomy=taxonomy, concept=concept, unit=unit,
        period_end=pe, period_start=ps, value=claimed, metric_name=metric_name))


@evidence_app.command("list")
@cli_errors
def evidence_list(session: SessionArg) -> None:
    """Your own evidence (the other researcher's is hidden until stage 2)."""
    _with_session(session, lambda c, s, r: {"evidence": [service._evidence_dict(e) for e in service.own_evidence(c, s, r)]})


@claim_app.command("add")
@cli_errors
def claim_add(
    session: SessionArg,
    type_: Annotated[str, typer.Option("--type", help="FACT | ASSUMPTION | UNVERIFIED | GAP")],
    text_: Annotated[str, typer.Option("--text", help="One atomic statement.")],
    evidence: Annotated[Optional[list[str]], typer.Option("--evidence", help="Evidence code, repeatable (e.g. E-1).")] = None,
    basis: Annotated[Optional[list[str]], typer.Option("--basis", help="Claim/evidence code an ASSUMPTION rests on, repeatable.")] = None,
    falsifier: Annotated[Optional[str], typer.Option("--falsifier", help="What would prove an ASSUMPTION wrong.")] = None,
    relevance: Annotated[Optional[str], typer.Option("--relevance")] = None,
    rank: Annotated[Optional[int], typer.Option("--rank", help="1 = your most important claim.")] = None,
) -> None:
    """File a typed claim. FACT needs verified evidence; ASSUMPTION needs --basis and --falsifier."""
    _with_session(session, lambda c, s, r: service.add_agent_claim(
        c, s, r, claim_type=type_.upper(), text_value=text_, evidence=evidence or [], basis=basis or [],
        falsifier=falsifier, relevance=relevance, rank=rank))


@claim_app.command("list")
@cli_errors
def claim_list(session: SessionArg) -> None:
    """Your own claims."""
    _with_session(session, lambda c, s, r: {"claims": [service._claim_dict(x) for x in service.own_claims(c, s, r)]})


@app.command("submit")
@cli_errors
def submit_cmd(session: SessionArg, summary: Annotated[str, typer.Option("--summary", help="Short brief (about 120 words).")]) -> None:
    """Close your work for the current stage (1 or 2). It is frozen afterwards."""
    _with_session(session, lambda c, s, r: service.submit(c, s, r, summary))


@brief_app.command("show")
@cli_errors
def brief_show(session: SessionArg, other: Annotated[bool, typer.Option("--other", help="Required: show the other researcher's brief.")] = False) -> None:
    """The other researcher's filed stage-1 brief (stage 2 onward, after you filed yours)."""
    if not other:
        raise typer.BadParameter("pass --other")
    _with_session(session, lambda c, s, r: service.show_other_brief(c, s, r))


@challenge_app.command("add")
@cli_errors
def challenge_add(
    session: SessionArg,
    target: Annotated[str, typer.Option("--target", help="Their claim code, e.g. C-X1.")],
    stance: Annotated[str, typer.Option("--stance", help="disputes | partly_agrees | agrees | needs_evidence")],
    restated: Annotated[str, typer.Option("--restated", help="Their claim, restated fairly.")],
    argument: Annotated[str, typer.Option("--argument", help="Your response.")],
    counter_evidence: Annotated[Optional[list[str]], typer.Option("--counter-evidence", help="Your evidence code, repeatable.")] = None,
) -> None:
    """Challenge one claim (up to three). 'disputes' needs counter-evidence."""
    _with_session(session, lambda c, s, r: service.add_challenge(
        c, s, r, target=target, stance=stance, restated=restated, argument=argument, counter_evidence=counter_evidence or []))


@app.command("final")
@cli_errors
def final_cmd(
    session: SessionArg,
    json_: Annotated[Optional[str], typer.Option("--json", help="Final position as JSON (see `next` at stage 3).")] = None,
    file: Annotated[Optional[Path], typer.Option("--file", help="Final position JSON file.")] = None,
) -> None:
    """File your final position at stage 3: concessions, claims you still hold, what you could not establish."""
    raw = json_ if json_ is not None else (file.read_text(encoding="utf-8") if file else None)
    if raw is None:
        raise typer.BadParameter("give --json or --file")
    try:
        position = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CouncilError(f"The final position is not valid JSON: {exc}") from exc
    if not isinstance(position, dict):
        raise CouncilError("The final position must be a JSON object")
    _with_session(session, lambda c, s, r: service.submit_final(c, s, r, position))


@app.command("whoami")
@cli_errors
def whoami() -> None:
    """The role and database account this directory is configured for (no secrets)."""
    _out({"role": config.agent_role(), "db_user": config.db_user("agent"), "db_host": config._get("COUNCIL_DB_HOST", "127.0.0.1"),
          "db_port": config._get("COUNCIL_DB_PORT", "3307"), "data_dir": config._get("COUNCIL_DATA_DIR")})


def main() -> None:  # entry point for the `council-agent` script
    app()
