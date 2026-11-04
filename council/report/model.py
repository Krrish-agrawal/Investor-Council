"""Inputs to the dossier renderer and the DB loader that builds them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from council.evidence.freshness import FreshnessConfig
from council.evidence.service import ClaimRecord, EvidenceRecord, list_claims, list_evidence
from council.portfolio.metrics import PortfolioMetrics, compute_metrics
from council.portfolio.repository import PortfolioRecord, load_holdings, load_portfolio
from council.portfolio.summary import build_shared_summary
from council.sessions import SessionRecord, as_json


@dataclass(frozen=True)
class ChallengeRow:
    from_agent: str
    target_claim: str
    stance: str
    restated: str
    argument: str
    counter_evidence: tuple[str, ...]


@dataclass(frozen=True)
class SubmissionRow:
    agent: str
    stage: int
    summary: str | None
    concessions: tuple[dict, ...] = ()
    still_holds: tuple[dict, ...] = ()
    could_not_establish: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ledger:
    claims: tuple[ClaimRecord, ...]
    evidence: tuple[EvidenceRecord, ...]
    challenges: tuple[ChallengeRow, ...]
    submissions: tuple[SubmissionRow, ...]


@dataclass(frozen=True)
class DossierData:
    portfolio: PortfolioRecord
    metrics: PortfolioMetrics
    shared_summary: dict[str, Any]
    session: SessionRecord | None = None
    claims: tuple[ClaimRecord, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    challenges: tuple[ChallengeRow, ...] = ()
    submissions: tuple[SubmissionRow, ...] = ()
    freshness: FreshnessConfig | None = None
    human_note: str | None = None
    extra_warnings: tuple[str, ...] = field(default=())


def _challenges(conn: Connection, session_id: int) -> tuple[ChallengeRow, ...]:
    rows = conn.execute(
        text(
            "SELECT ch.from_agent, c.code, ch.stance, ch.restated, ch.argument, ch.counter_evidence "
            "FROM challenges ch JOIN claims c ON c.id = ch.target_claim_id "
            "WHERE ch.session_id = :s ORDER BY ch.id"
        ),
        {"s": session_id},
    ).all()
    return tuple(
        ChallengeRow(r[0], r[1], r[2], r[3], r[4], tuple(as_json(r[5]) or ()) if r[5] is not None else ())
        for r in rows
    )


def _json_list(value) -> tuple:
    return tuple(as_json(value) or ()) if value is not None else ()


def load_submissions(conn: Connection, session_id: int) -> tuple[SubmissionRow, ...]:
    rows = conn.execute(
        text("SELECT agent, stage, summary, concessions, still_holds, could_not_establish FROM submissions "
             "WHERE session_id = :s ORDER BY stage, agent"),
        {"s": session_id},
    ).all()
    return tuple(SubmissionRow(r[0], int(r[1]), r[2], _json_list(r[3]), _json_list(r[4]), _json_list(r[5])) for r in rows)


def load_ledger(conn: Connection, session_id: int) -> Ledger:
    """Everything recorded for a session; the single source for the dossier, status and finalize."""
    return Ledger(tuple(list_claims(conn, session_id)), tuple(list_evidence(conn, session_id)),
                  _challenges(conn, session_id), load_submissions(conn, session_id))


def load_dossier_data(
    conn: Connection, *, portfolio_id: int, session: SessionRecord | None = None, human_note: str | None = None
) -> DossierData:
    """Gather everything the renderer needs from the database."""
    portfolio = load_portfolio(conn, portfolio_id)
    metrics = compute_metrics(load_holdings(conn, portfolio_id))
    if session is not None:
        summary = session.shared_summary  # exactly what was shared with the room
        ledger = load_ledger(conn, session.id)
        claims, evidence, challenges, submissions = ledger.claims, ledger.evidence, ledger.challenges, ledger.submissions
        freshness = FreshnessConfig.from_json(session.freshness_cfg)
    else:
        summary = build_shared_summary(
            metrics, price_as_of=portfolio.price_as_of, excluded_rows=portfolio.excluded_rows
        )
        claims, evidence, challenges, submissions, freshness = (), (), (), (), None
    return DossierData(
        portfolio=portfolio,
        metrics=metrics,
        shared_summary=summary,
        session=session,
        claims=claims,
        evidence=evidence,
        challenges=challenges,
        submissions=submissions,
        freshness=freshness,
        human_note=human_note,
    )
