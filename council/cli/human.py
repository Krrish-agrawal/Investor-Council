"""``council human ...``: commands the human runs locally in a terminal.

Everything that touches the raw portfolio lives here. None of these commands posts anything to a
Switch room; the human decides what, if anything, to paste (the sanitised summary).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer
from sqlalchemy import text

from council import config
from council.cli.common import cli_errors, echo_err, format_table, parse_iso_date
from council.db.engine import make_engine, transaction
from council.edgar.client import EdgarClient, read_cached_document
from council import stages
from council.edgar.facts import CompanyFactsSnapshot, identify_fiscal_periods
from council.edgar.manifest import write_manifest
from council.edgar.models import normalize_cik
from council.edgar.validate import parse_submissions
from council.errors import CouncilError, NotFoundError
from council.evidence.freshness import load_freshness_config
from council.evidence.service import register_snapshot_source, rule_claim
from council.portfolio.csv_ingest import parse_portfolio_csv_file
from council.portfolio.metrics import compute_metrics
from council.portfolio.repository import latest_portfolio_id, load_holdings, load_portfolio, save_portfolio
from council.portfolio.summary import build_local_summary, build_shared_summary
from council.report.lint import lint_advice_language
from council.report.model import load_dossier_data, load_ledger
from council.report.render import TEMPLATE_VERSION, render_dossier
from council.sessions import create_session, get_session, latest_session

log = logging.getLogger(__name__)

human_app = typer.Typer(help="Local, human-run commands (portfolio, sessions, rulings, dossier).", no_args_is_help=True)
session_app = typer.Typer(help="Research sessions.", no_args_is_help=True)
data_app = typer.Typer(help="Frozen SEC EDGAR data.", no_args_is_help=True)
agents_app = typer.Typer(help="Agent working directories.", no_args_is_help=True)
human_app.add_typer(agents_app, name="agents")
human_app.add_typer(session_app, name="session")
human_app.add_typer(data_app, name="data")

PortfolioOpt = Annotated[Optional[int], typer.Option("--portfolio-id", help="Defaults to the most recent portfolio.")]


def _portfolio_id(conn, explicit: int | None) -> int:
    pid = explicit if explicit is not None else latest_portfolio_id(conn)
    if pid is None:
        raise NotFoundError("No portfolio ingested yet. Run: council human ingest --file samples/portfolio.csv")
    return pid


# ---------------------------------------------------------------------------------------------
# ingest / summary
# ---------------------------------------------------------------------------------------------


@human_app.command("ingest")
@cli_errors
def ingest(
    file: Annotated[Path, typer.Option("--file", "-f", help="Portfolio CSV: ticker, shares, price[, sector].")],
    name: Annotated[Optional[str], typer.Option("--name", help="Label for this portfolio (default: file name).")] = None,
    price_as_of: Annotated[Optional[str], typer.Option("--price-as-of", help="Date of the prices in the CSV (YYYY-MM-DD).")] = None,
    sample: Annotated[bool, typer.Option("--sample", help="Mark as the bundled synthetic sample.")] = False,
    allow_partial: Annotated[bool, typer.Option("--allow-partial", help="Store valid rows even if some rows are invalid (weights will describe a subset).")] = False,
) -> None:
    """Validate a portfolio CSV locally and store it in MySQL. The file is read, never copied or uploaded."""
    report = parse_portfolio_csv_file(file)
    for warning in report.warnings:
        echo_err(f"warning (line {warning.line}): {warning.message}")
    for issue in report.errors:
        echo_err(f"invalid (line {issue.line}): {issue.message}")
    if report.errors and not allow_partial:
        echo_err(f"{report.invalid_row_count} invalid row(s); nothing was stored. Fix the file or use --allow-partial.")
        raise typer.Exit(1)
    asof = parse_iso_date(price_as_of, "--price-as-of")
    engine = make_engine("human")
    with transaction(engine) as conn:
        record, created = save_portfolio(
            conn, report, name=name or file.stem, origin="sample" if sample else "user",
            price_as_of=asof, allow_partial=allow_partial,
        )
    verb = "Stored" if created else "Already stored (identical file)"
    typer.echo(f"{verb}: portfolio id={record.id} name={record.name!r} holdings={len(report.holdings)} sha256={record.csv_sha256[:12]}...")
    if record.excluded_rows:
        typer.echo(f"WARNING: {record.excluded_rows} invalid row(s) excluded; weights describe only the valid rows.")
    typer.echo("The CSV stays on this machine. Share only `council human summary --shared` output, if anything.")


@human_app.command("summary")
@cli_errors
def summary(
    portfolio_id: PortfolioOpt = None,
    shared: Annotated[bool, typer.Option("--shared", help="Print the sanitised summary that is safe to paste into a shared room.")] = False,
    target: Annotated[Optional[str], typer.Option("--target", help="Research target ticker (used with --shared).")] = None,
    target_sector: Annotated[Optional[str], typer.Option("--target-sector", help="Sector label of the target, if not held.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Portfolio weights, sector allocation and concentration. Local detail by default."""
    engine = make_engine("human")
    with engine.connect() as conn:
        pid = _portfolio_id(conn, portfolio_id)
        record = load_portfolio(conn, pid)
        metrics = compute_metrics(load_holdings(conn, pid))
    if shared:
        data = build_shared_summary(metrics, target_ticker=target, target_sector=target_sector,
                                    price_as_of=record.price_as_of, excluded_rows=record.excluded_rows)
        typer.echo(json.dumps(data, indent=2))
        return
    data = build_local_summary(metrics, price_as_of=record.price_as_of)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    typer.echo(f"Portfolio {record.id} ({record.name}) | holdings={data['holdings_count']} | total value={data['total_value']} | prices as of {data['price_as_of'] or 'unknown'} (user-supplied)")
    if record.excluded_rows:
        typer.echo(f"WARNING: partial portfolio, {record.excluded_rows} invalid row(s) excluded.")
    typer.echo("\nPositions (LOCAL ONLY)")
    typer.echo(format_table(["Ticker", "Sector", "Shares", "Price", "Value", "Weight%"],
                            [[p["ticker"], p["sector"], p["shares"], p["price"], p["market_value"], p["weight_pct"]] for p in data["positions"]],
                            right=(2, 3, 4, 5)))
    typer.echo("\nSector allocation")
    typer.echo(format_table(["Sector", "Weight%", "Holdings"], [[s["sector"], s["weight_pct"], s["holdings"]] for s in data["sectors"]], right=(1, 2)))
    c = data["concentration"]
    typer.echo("\nConcentration")
    typer.echo(f"  top1={c['top1_pct']}%  top3={c['top3_pct']}%  top5={c['top5_pct']}%  HHI={c['hhi']}  effective holdings={c['effective_holdings']}  sector HHI={c['sector_hhi']}")


# ---------------------------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------------------------


@session_app.command("new")
@cli_errors
def session_new(
    ticker: Annotated[str, typer.Option("--ticker", help="Research target ticker.")],
    thesis: Annotated[str, typer.Option("--thesis", help="Your thesis or question, in your own words.")],
    portfolio_id: PortfolioOpt = None,
    target_sector: Annotated[Optional[str], typer.Option("--target-sector", help="Sector label of the target (for overlap), if it is not held.")] = None,
    cik: Annotated[Optional[str], typer.Option("--cik", help="Target's SEC CIK, if known.")] = None,
    session_date: Annotated[Optional[str], typer.Option("--session-date", help="Defaults to today (UTC).")] = None,
) -> None:
    """Open a research session and print the sanitised summary to paste into the room."""
    freshness = load_freshness_config(config.freshness_config_path())
    sdate = parse_iso_date(session_date, "--session-date") or datetime.now(timezone.utc).date()
    engine = make_engine("human")
    with transaction(engine) as conn:
        pid = _portfolio_id(conn, portfolio_id)
        record = load_portfolio(conn, pid)
        metrics = compute_metrics(load_holdings(conn, pid))
        shared = build_shared_summary(metrics, target_ticker=ticker, target_sector=target_sector,
                                      price_as_of=record.price_as_of, excluded_rows=record.excluded_rows)
        session = create_session(
            conn, portfolio_id=pid, target_ticker=ticker, thesis=thesis, shared_summary=shared,
            freshness_cfg=freshness.to_json(), session_date=sdate,
            target_cik=normalize_cik(cik) if cik else None, target_sector=target_sector or shared.get("target_sector"),
        )
    typer.echo(f"Created session {session.code} (target {session.target_ticker}, stage {session.stage}).")
    if cik:
        cached = read_cached_document(config.edgar_dir(), normalize_cik(cik), "companyfacts")
        if cached is None:
            typer.echo(f"Note: no frozen snapshot cached for CIK{normalize_cik(cik)}. Run `council human data fetch --cik {int(normalize_cik(cik))}` "
                       "then `council human data register --cik ...` so the agents can cite it.")
        else:
            with transaction(engine) as conn:
                register_snapshot_source(conn, CompanyFactsSnapshot(cached))
            typer.echo(f"Registered the cached snapshot for CIK{normalize_cik(cik)} as a citable source.")
    typer.echo("Sanitised summary (safe to paste into a shared room; contains no shares, values or other tickers):")
    typer.echo(json.dumps(shared, indent=2))


@session_app.command("show")
@cli_errors
def session_show(code: Annotated[Optional[str], typer.Argument(help="Session code, e.g. S-0001 (default: latest).")] = None) -> None:
    """Show a session."""
    engine = make_engine("human")
    with engine.connect() as conn:
        session = get_session(conn, code) if code else latest_session(conn)
        if session is None:
            raise NotFoundError("No sessions yet. Run: council human session new --ticker T --thesis '...'")
    typer.echo(json.dumps({
        "code": session.code, "target_ticker": session.target_ticker, "target_cik": session.target_cik,
        "stage": session.stage, "status": session.status, "session_date": session.session_date.isoformat(),
        "data_mode": session.data_mode, "thesis": session.thesis, "freshness": session.freshness_cfg,
    }, indent=2))


# ---------------------------------------------------------------------------------------------
# rulings and report
# ---------------------------------------------------------------------------------------------


@human_app.command("rule")
@cli_errors
def rule(
    session_code: Annotated[str, typer.Argument(help="Session code, e.g. S-0001.")],
    claim_code: Annotated[str, typer.Argument(help="Claim code, e.g. C-B1.")],
    ruling: Annotated[str, typer.Argument(help="accept | reject | needs_evidence")],
    note: Annotated[Optional[str], typer.Option("--note", help="Your reason, in your own words.")] = None,
) -> None:
    """Record your ruling on a claim."""
    if ruling not in ("accept", "reject", "needs_evidence"):
        raise typer.BadParameter("ruling must be accept, reject or needs_evidence")
    engine = make_engine("human")
    with transaction(engine) as conn:
        claim = rule_claim(conn, get_session(conn, session_code), claim_code, ruling, note)  # type: ignore[arg-type]
    typer.echo(f"{claim.code}: ruling recorded as {claim.human_ruling}")


@human_app.command("message")
@cli_errors
def stage_message(
    session: Annotated[str, typer.Argument(help="Session code.")],
    stage: Annotated[int, typer.Option("--stage", help="1, 2 or 3.")],
    copy: Annotated[bool, typer.Option("--copy", help="Also copy it to the macOS clipboard (pbcopy).")] = False,
) -> None:
    """Print the stage message to paste into the room, tagging both researchers (built from the session; sanitised only)."""
    if stage not in (1, 2, 3):
        raise typer.BadParameter("--stage must be 1, 2 or 3")
    engine = make_engine("human")
    with engine.connect() as conn:
        sess = get_session(conn, session)
    c = sess.session_code if hasattr(sess, "session_code") else sess.code
    tag = f"@bull-researcher @bear-researcher [session {c}]"
    if stage == 1:
        summary = json.dumps(sess.shared_summary, separators=(",", ":"))
        cik = f", CIK {int(sess.target_cik)}" if sess.target_cik else ""
        text = (f"{tag} Stage 1: initial analysis. Target: {sess.target_ticker}{cik}. My question: {sess.thesis} "
                f"Portfolio context (sanitised): {summary} . Run ./council-agent next {c}, research independently, file your evidence "
                "and claims, submit, and post a brief of about 120 words. Do not read the other researcher's work.")
    elif stage == 2:
        text = (f"{tag} Stage 2: challenge round. (I have run council human advance {c} --to 2.) Read the other researcher's filed brief "
                f"with ./council-agent brief show {c} --other, challenge up to three of their claims (restate fairly, then dispute with your "
                "own evidence, partly agree, agree, or ask for evidence), then submit and post a short summary. One round only.")
    else:
        text = (f"{tag} Stage 3: final synthesis. (I have ruled on the flagged claims and run council human advance {c} --to 3.) "
                f"Run ./council-agent next {c} to see the challenges against you and my rulings, file your final position with "
                "./council-agent final, and post a one-line note that you did.")
    if sess.stage < stage:
        echo_err(f"note: {c} is at stage {sess.stage}; run `council human advance {c} --to {stage}` before posting this.")
    typer.echo(text)
    if copy:
        import subprocess
        subprocess.run(["pbcopy"], input=text.encode(), check=False)
        echo_err("copied to the clipboard")


@human_app.command("status")
@cli_errors
def status(session: Annotated[Optional[str], typer.Argument(help="Session code (default: latest).")] = None) -> None:
    """Where a session stands: submissions, claims, challenges, unresolved flagged claims and the next step."""
    engine = make_engine("human")
    with engine.connect() as conn:
        sess = get_session(conn, session) if session else latest_session(conn)
        if sess is None:
            raise NotFoundError("No sessions yet.")
        st = stages.compute_status(sess, load_ledger(conn, sess.id))
    typer.echo(f"{sess.code}  target {sess.target_ticker}  stage {sess.stage} ({stages.STAGE_NAMES[sess.stage]})  status {sess.status}")
    rows = [[f"stage {n}", "yes" if st.submitted[n]["bull"] else "-", "yes" if st.submitted[n]["bear"] else "-"] for n in (1, 2, 3)]
    typer.echo(format_table(["submitted", "bull", "bear"], rows))
    typer.echo(f"claims: bull {st.claims_by_agent['bull']}, bear {st.claims_by_agent['bear']}   "
               f"challenges made: bull {st.challenges_by_agent['bull']}, bear {st.challenges_by_agent['bear']}")
    typer.echo(f"flagged claims: {len(st.flagged)}   unresolved (need an accept/reject ruling): {len(st.unresolved)}")
    for u in st.unresolved:
        typer.echo(f"  {u.claim.code} [{u.claim.agent}, {u.claim.claim_type}] {u.claim.text[:90]}")
        typer.echo(f"      why: {'; '.join(u.reasons)}")
    typer.echo(f"next: {st.next_step}")


@human_app.command("advance")
@cli_errors
def advance(
    session: Annotated[str, typer.Argument(help="Session code.")],
    to: Annotated[int, typer.Option("--to", help="Next stage: 2 or 3.")],
    force: Annotated[bool, typer.Option("--force", help="Advance even if an agent has not submitted (needed for the sequential fallback or a failed agent).")] = False,
) -> None:
    """Move a session to the next stage (human-only). Normally both agents must have submitted the current stage."""
    engine = make_engine("human")
    with transaction(engine) as conn:
        sess = get_session(conn, session)
        stages.advance(conn, sess, load_ledger(conn, sess.id), to, force=force)
    typer.echo(f"{session} is now at stage {to} ({stages.STAGE_NAMES[to]}). Post the stage message tagging both agents.")


@human_app.command("finalize")
@cli_errors
def finalize(
    session: Annotated[str, typer.Argument(help="Session code.")],
    note: Annotated[str, typer.Option("--note", help="Your own decision note, in your own words.")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Also write the final dossier to a file.")] = None,
    force_missing_final: Annotated[bool, typer.Option("--force-missing-final", help="Finalize although an agent filed no final position (the dossier says so).")] = False,
) -> None:
    """Finalize at stage 3: every flagged claim needs an accept/reject ruling (no override), then store the FINAL dossier."""
    engine = make_engine("human")
    with transaction(engine) as conn:
        sess = get_session(conn, session)
        ledger = load_ledger(conn, sess.id)
        stages.finalize_checks(sess, ledger, note, force_submissions=force_missing_final)
        data = load_dossier_data(conn, portfolio_id=sess.portfolio_id, session=sess, human_note=note)
        markdown = render_dossier(data, generated_at=stages.now_utc(), final=True)
        version = conn.execute(text("SELECT COALESCE(MAX(version), 0) + 1 FROM dossiers WHERE session_id = :s"), {"s": sess.id}).scalar_one()
        conn.execute(
            text("INSERT INTO dossiers (session_id, version, body_markdown, template_ver, human_note, status) VALUES (:s, :v, :b, :t, :n, 'FINAL')"),
            {"s": sess.id, "v": int(version), "b": markdown, "t": TEMPLATE_VERSION, "n": note.strip()},
        )
        stages.mark_finalized(conn, sess)
    for f in lint_advice_language(markdown):
        echo_err(f"lint ({f.rule}): {f.excerpt!r}")
    typer.echo(f"{session} finalized; FINAL dossier version {int(version)} stored.")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        typer.echo(f"Wrote {output}")


@human_app.command("report")
@cli_errors
def report(
    session: Annotated[Optional[str], typer.Option("--session", help="Session code (default: latest session; if none, portfolio-only).")] = None,
    portfolio_id: PortfolioOpt = None,
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write to a file instead of stdout.")] = None,
    local_detail: Annotated[bool, typer.Option("--local-detail", help="Include position-level data. LOCAL ONLY; never share.")] = False,
    note: Annotated[Optional[str], typer.Option("--note", help="Your own decision note to include.")] = None,
    save: Annotated[bool, typer.Option("--save", help="Store this dossier version in the database (not allowed with --local-detail).")] = False,
    strict: Annotated[bool, typer.Option("--strict", help="Exit non-zero if advice-like language is found.")] = False,
) -> None:
    """Render the Markdown research dossier from the database (deterministic; no LLM involved)."""
    if save and local_detail:
        raise typer.BadParameter("--save cannot be combined with --local-detail")
    engine = make_engine("human")
    with transaction(engine) as conn:
        sess = None
        if session:
            sess = get_session(conn, session)
        elif portfolio_id is None:
            sess = latest_session(conn)
        pid = sess.portfolio_id if sess else _portfolio_id(conn, portfolio_id)
        data = load_dossier_data(conn, portfolio_id=pid, session=sess, human_note=note)
        markdown = render_dossier(data, generated_at=datetime.now(timezone.utc), include_local_detail=local_detail)
        if save:
            if sess is None:
                raise CouncilError("--save needs a research session")
            version = conn.execute(text("SELECT COALESCE(MAX(version), 0) + 1 FROM dossiers WHERE session_id = :s"), {"s": sess.id}).scalar_one()
            conn.execute(
                text("INSERT INTO dossiers (session_id, version, body_markdown, template_ver, human_note, status) VALUES (:s, :v, :b, :t, :n, 'DRAFT')"),
                {"s": sess.id, "v": int(version), "b": markdown, "t": TEMPLATE_VERSION, "n": note},
            )
            echo_err(f"Saved dossier version {int(version)} for {sess.code}")
    findings = lint_advice_language(markdown)
    for f in findings:
        echo_err(f"lint ({f.rule}): {f.excerpt!r}")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        echo_err(f"Wrote {output}" + ("  (LOCAL ONLY: do not share)" if local_detail else ""))
    else:
        typer.echo(markdown, nl=False)
    if findings and strict:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------------------------
# frozen EDGAR data
# ---------------------------------------------------------------------------------------------


def _print_company(cik: str) -> None:
    cache_dir = config.edgar_dir()
    facts_doc = read_cached_document(cache_dir, cik, "companyfacts")
    if facts_doc is None:
        raise NotFoundError(f"CIK{cik} is not cached. Run: council human data fetch --cik {int(cik)}")
    snapshot = CompanyFactsSnapshot(facts_doc)
    periods = identify_fiscal_periods(snapshot)
    typer.echo(f"{snapshot.entity_name} (CIK{snapshot.cik})")
    typer.echo(f"  company facts: retrieved {facts_doc.meta.retrieved_at.isoformat()}  sha256 {facts_doc.meta.sha256[:16]}...  {facts_doc.meta.url}")
    for label, p in (("latest annual period", periods.latest_annual), ("latest quarterly period", periods.latest_quarterly)):
        if p is None:
            typer.echo(f"  {label}: none found")
        else:
            typer.echo(f"  {label}: ends {p.end.isoformat()}, filed {p.filed.isoformat()}, form {p.form}, accession {p.accession}, "
                       f"fy/fp as reported {p.fiscal_year}/{p.fiscal_period}")
    sub_doc = read_cached_document(cache_dir, cik, "submissions")
    if sub_doc is None:
        typer.echo("  submissions: not cached")
        return
    info = parse_submissions(sub_doc.raw, expected_cik=cik)
    typer.echo(f"  submissions: retrieved {sub_doc.meta.retrieved_at.isoformat()}  {sub_doc.meta.url}")
    typer.echo(f"  SIC: {info.sic or 'n/a'} {info.sic_description or ''}  tickers: {', '.join(info.tickers) or 'n/a'}  recent filings: {len(info.filings)} (older filings not fetched)")


def _edgar_client() -> EdgarClient:
    sec = config.sec_settings()
    return EdgarClient(user_agent=sec.user_agent, cache_dir=config.edgar_dir(), max_rps=sec.max_rps)


@data_app.command("fetch")
@cli_errors
def data_fetch(
    cik: Annotated[str, typer.Option("--cik", help="SEC CIK, e.g. 320193 or 0000320193.")],
    refresh: Annotated[bool, typer.Option("--refresh", help="Re-download even if cached (replaces the frozen snapshot).")] = False,
) -> None:
    """Download and cache company facts + filing metadata for a CIK (validated, rate-limited)."""
    normalized = normalize_cik(cik)
    with _edgar_client() as client:
        client.get_company_facts(normalized, refresh=refresh)
        client.get_submissions(normalized, refresh=refresh)
    _print_company(normalized)
    manifest = write_manifest(config.edgar_dir())
    typer.echo(f"Manifest updated: {manifest}")


@data_app.command("register")
@cli_errors
def data_register(cik: Annotated[str, typer.Option("--cik", help="SEC CIK whose cached snapshot agents may cite.")]) -> None:
    """Register a cached snapshot as a citable source (human-only: agents cannot insert sources)."""
    normalized = normalize_cik(cik)
    cached = read_cached_document(config.edgar_dir(), normalized, "companyfacts")
    if cached is None:
        raise NotFoundError(f"CIK{normalized} is not cached. Run: council human data fetch --cik {int(normalized)}")
    engine = make_engine("human")
    with transaction(engine) as conn:
        source_id = register_snapshot_source(conn, CompanyFactsSnapshot(cached))
    typer.echo(f"Registered source id={source_id}: CIK{normalized} retrieved {cached.meta.retrieved_at.isoformat()} sha256 {cached.meta.sha256[:12]}...")


@data_app.command("inspect")
@cli_errors
def data_inspect(cik: Annotated[str, typer.Option("--cik", help="SEC CIK.")]) -> None:
    """Describe a cached company without touching the network."""
    _print_company(normalize_cik(cik))


@data_app.command("manifest")
@cli_errors
def data_manifest() -> None:
    """Rewrite data/edgar/MANIFEST.json from the cached documents."""
    typer.echo(f"Manifest written: {write_manifest(config.edgar_dir())}")


# ---------------------------------------------------------------------------------------------
# agent working directories
# ---------------------------------------------------------------------------------------------

AGENT_ROLES = {"bull": "bull-researcher", "bear": "bear-researcher"}


@agents_app.command("init")
@cli_errors
def agents_init(
    directory: Annotated[Path, typer.Option("--dir", help="Parent folder for the agent directories.")] = Path("agents"),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing .council.env and wrapper files.")] = False,
    switch_dir: Annotated[Path, typer.Option("--switch-dir", help="Folder with agent-manual.md and role-bull.md / role-bear.md.")] = Path("switch"),
) -> None:
    """Create bull-researcher/ and bear-researcher/ with the restricted-account settings and a `council-agent` wrapper.

    Each directory gets a git-ignored `.council.env` holding ONLY the restricted agent account, its role and the
    data folder, never the human's credentials. Register these folders as the agents' working directories in Switch Console.
    """
    import os
    import shlex
    import sys

    password = config.db_password("agent", required=False)
    if not password:
        raise CouncilError("COUNCIL_DB_AGENT_PASSWORD is not set in .env; run `council db init` after setting it.")
    exe = Path(sys.executable).with_name("council-agent")
    if not exe.exists():
        raise CouncilError(f"{exe} not found; run `pip install -e .` in this environment.")
    data = config.data_dir().resolve()
    host = config._get("COUNCIL_DB_HOST", "127.0.0.1")
    port = config._get("COUNCIL_DB_PORT", "3307")
    for role, folder in AGENT_ROLES.items():
        target = (directory / folder).resolve()
        target.mkdir(parents=True, exist_ok=True)
        env_file, wrapper = target / ".council.env", target / "council-agent"
        if (env_file.exists() or wrapper.exists()) and not force:
            raise CouncilError(f"{target} already has agent files; pass --force to overwrite them.")
        env_file.write_text(
            f"COUNCIL_AGENT_ROLE={role}\nCOUNCIL_DB_HOST={host}\nCOUNCIL_DB_PORT={port}\nCOUNCIL_DB_NAME={config.db_name()}\n"
            f"COUNCIL_DB_AGENT_USER={config.db_user('agent')}\nCOUNCIL_DB_AGENT_PASSWORD={password}\nCOUNCIL_DATA_DIR={data}\n",
            encoding="utf-8")
        os.chmod(env_file, 0o600)
        wrapper.write_text(f'#!/bin/sh\n# Runs the agent CLI from this directory so it reads only this directory\'s .council.env.\ncd "$(dirname "$0")" && exec {shlex.quote(str(exe))} "$@"\n', encoding="utf-8")
        os.chmod(wrapper, 0o755)
        manual, role_text = switch_dir / "agent-manual.md", switch_dir / f"role-{role}.md"
        if manual.is_file() and role_text.is_file():
            (target / "CLAUDE.md").write_text(role_text.read_text(encoding="utf-8") + "\n" + manual.read_text(encoding="utf-8"), encoding="utf-8")
        typer.echo(f"{folder}: wrote {env_file.name} (mode 600, role={role}, restricted account only), the council-agent wrapper and CLAUDE.md in {target}")
    typer.echo("Both files are git-ignored. Next: register each folder as an agent's working directory (see switch/SETUP.md).")
