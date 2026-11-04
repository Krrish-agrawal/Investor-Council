"""Human-side stage control: status, advancing and finalizing.

The human, not an agent, moves a session through the three stages (docs/ARCHITECTURE.md section 4). This is a
flag on the session row plus checks, not a workflow engine. ``finalize`` is the ruling gate: a session cannot be
finalized while any flagged claim lacks an accept/reject ruling, and that check has no override.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from council.errors import CouncilError
from council.report.gate import FlaggedClaim, assert_ready_to_finalize, flagged_claims, unresolved_claims
from council.report.model import Ledger
from council.sessions import SessionRecord

ROLES = ("bull", "bear")
STAGE_NAMES = {1: "initial analysis", 2: "challenge round", 3: "final synthesis"}


@dataclass(frozen=True)
class Status:
    session: SessionRecord
    submitted: dict[int, dict[str, bool]]
    claims_by_agent: dict[str, int]
    challenges_by_agent: dict[str, int]
    flagged: list[FlaggedClaim]
    unresolved: list[FlaggedClaim]
    next_step: str


def submitted_map(ledger: Ledger) -> dict[int, dict[str, bool]]:
    out = {stage: {role: False for role in ROLES} for stage in (1, 2, 3)}
    for sub in ledger.submissions:
        if sub.stage in out and sub.agent in out[sub.stage]:
            out[sub.stage][sub.agent] = True
    return out


def missing_for_stage(ledger: Ledger, stage: int) -> list[str]:
    return [role for role, done in submitted_map(ledger)[stage].items() if not done]


def compute_status(session: SessionRecord, ledger: Ledger) -> Status:
    submitted = submitted_map(ledger)
    flagged = flagged_claims(ledger.claims, ledger.evidence, ledger.challenges)
    unresolved = [f for f in flagged if not f.resolved]
    claims = {r: sum(1 for c in ledger.claims if c.agent == r) for r in ROLES}
    challenges = {r: sum(1 for c in ledger.challenges if c.from_agent == r) for r in ROLES}

    if session.status == "FINALIZED":
        step = "Finalized. The dossier is stored; nothing more to do."
    elif session.status != "OPEN":
        step = f"Session is {session.status}."
    else:
        missing = missing_for_stage(ledger, session.stage)
        if missing:
            step = (f"Stage {session.stage} ({STAGE_NAMES[session.stage]}): waiting for {' and '.join(missing)} to submit. "
                    "Message them in the room; use `advance --force` only if an agent cannot finish.")
        elif session.stage < 3:
            step = f"Both agents have submitted stage {session.stage}. Review, then `council human advance {session.code} --to {session.stage + 1}`."
            if session.stage == 2 and unresolved:
                step += f" Before the final synthesis, rule on the {len(unresolved)} unresolved flagged claim(s)."
        elif unresolved:
            step = f"Rule on {len(unresolved)} unresolved flagged claim(s): {', '.join(u.claim.code for u in unresolved)}."
        else:
            step = f"Ready: `council human finalize {session.code} --note \"...\"`."
    return Status(session, submitted, claims, challenges, flagged, unresolved, step)


def advance(conn: Connection, session: SessionRecord, ledger: Ledger, to: int, *, force: bool) -> None:
    """Move to the next stage. Normally both agents must have submitted the current one."""
    if session.status != "OPEN":
        raise CouncilError(f"Session {session.code} is {session.status}.")
    if to != session.stage + 1 or to not in (2, 3):
        raise CouncilError(f"Session {session.code} is at stage {session.stage}; the only move is to stage {session.stage + 1}"
                           if session.stage < 3 else f"Session {session.code} is already at the last stage (3).")
    missing = missing_for_stage(ledger, session.stage)
    if missing and not force:
        raise CouncilError(f"Cannot advance: {' and '.join(missing)} has not submitted stage {session.stage}. "
                           "Wait, or pass --force if an agent cannot finish (the dossier will show what was not filed).")
    conn.execute(text("UPDATE research_sessions SET stage = :t WHERE id = :i"), {"t": to, "i": session.id})


def finalize_checks(session: SessionRecord, ledger: Ledger, note: str, *, force_submissions: bool) -> None:
    """Every check that must pass before a dossier can be marked FINAL. The ruling gate has no override."""
    if session.status != "OPEN":
        raise CouncilError(f"Session {session.code} is {session.status}; it cannot be finalized.")
    if session.stage != 3:
        raise CouncilError(f"Session {session.code} is at stage {session.stage}; finalize only at stage 3 (final synthesis).")
    if not note.strip():
        raise CouncilError("Finalizing needs your own decision note (--note). The tool never writes it for you.")
    missing = missing_for_stage(ledger, 3)
    if missing and not force_submissions:
        raise CouncilError(f"Cannot finalize: {' and '.join(missing)} has not filed a final position. "
                           "Wait, or pass --force-missing-final to finalize without it (the dossier will say it is missing).")
    assert_ready_to_finalize(unresolved_claims(ledger.claims, ledger.evidence, ledger.challenges))


def mark_finalized(conn: Connection, session: SessionRecord) -> None:
    conn.execute(text("UPDATE research_sessions SET status = 'FINALIZED' WHERE id = :i"), {"i": session.id})


def now_utc() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)
