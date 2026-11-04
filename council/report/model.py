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
class DossierData:
    portfolio: PortfolioRecord
    metrics: PortfolioMetrics
    shared_summary: dict[str, Any]
    session: SessionRecord | None = None
    claims: tuple[ClaimRecord, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    challenges: tuple[ChallengeRow, ...] = ()
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


def load_dossier_data(
    conn: Connection, *, portfolio_id: int, session: SessionRecord | None = None, human_note: str | None = None
) -> DossierData:
    """Gather everything the renderer needs from the database."""
    portfolio = load_portfolio(conn, portfolio_id)
    metrics = compute_metrics(load_holdings(conn, portfolio_id))
    if session is not None:
        summary = session.shared_summary  # exactly what was shared with the room
        claims = tuple(list_claims(conn, session.id))
        evidence = tuple(list_evidence(conn, session.id))
        challenges = _challenges(conn, session.id)
        freshness = FreshnessConfig.from_json(session.freshness_cfg)
    else:
        summary = build_shared_summary(
            metrics, price_as_of=portfolio.price_as_of, excluded_rows=portfolio.excluded_rows
        )
        claims, evidence, challenges, freshness = (), (), (), None
    return DossierData(
        portfolio=portfolio,
        metrics=metrics,
        shared_summary=summary,
        session=session,
        claims=claims,
        evidence=evidence,
        challenges=challenges,
        freshness=freshness,
        human_note=human_note,
    )
