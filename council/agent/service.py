"""Research-agent operations: session lookup, evidence and claim submission, briefs, challenges, final position.

Everything here runs as the restricted ``council_agent`` database account (see ``council/db/grants.py``).
It deliberately imports nothing from ``council.portfolio`` and never asks for another account, so an agent
cannot reach holdings through this code. Stage rules live here, in one place:

* Stage 1 (initial analysis): file evidence and claims independently, then ``submit``. The other agent's
  work is not readable.
* Stage 2 (challenge round): read the other agent's brief, challenge up to three of their claims, then ``submit``.
  Further evidence and claims are allowed (counter-evidence, a human-requested follow-up) until you submit.
* Stage 3 (final synthesis): file one final position. Evidence and claims are closed.

Only the human advances the stage.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Sequence

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from council.edgar.client import read_cached_document
from council.edgar.facts import CompanyFactsSnapshot, identify_fiscal_periods
from council.edgar.metrics import METRICS, lookup_metric
from council.edgar.models import normalize_cik
from council.errors import ClaimRuleError, CouncilError, EvidenceError, NotFoundError
from council.evidence.service import (
    ClaimRecord,
    EvidenceRecord,
    add_claim,
    get_claim,
    get_evidence,
    list_claims,
    list_evidence,
    record_fact_evidence,
    record_metric_evidence,
)
from council.sessions import AgentSession, as_json

Role = Literal["bull", "bear"]
STANCES = ("disputes", "partly_agrees", "agrees", "needs_evidence")
MAX_CHALLENGES = 3
SUMMARY_WORD_LIMIT = 150

STAGE_TASKS = {
    1: "Initial analysis. Research independently from the frozen data: register evidence, file typed claims, "
       "then submit your brief. You cannot see the other researcher's work yet.",
    2: "Challenge round. Read the other researcher's brief and challenge up to three of their claims (restate "
       "fairly, then dispute / partly agree / agree / ask for evidence, citing evidence or saying none was found). "
       "Then submit. One round only.",
    3: "Final synthesis. File your final position: what you concede, what you still hold and why, and what you "
       "could not establish. Take the human's rulings into account.",
}


def other_role(role: Role) -> Role:
    return "bear" if role == "bull" else "bull"


# ---------------------------------------------------------------------------------------------
# Stage validation
# ---------------------------------------------------------------------------------------------


def require_open(session: AgentSession) -> None:
    if session.status != "OPEN":
        raise CouncilError(f"Session {session.code} is {session.status}; it no longer accepts work.")


def require_stage(session: AgentSession, allowed: Sequence[int], action: str) -> None:
    require_open(session)
    if session.stage not in allowed:
        wanted = " or ".join(str(s) for s in allowed)
        raise CouncilError(
            f"Cannot {action} at stage {session.stage}; it is allowed at stage {wanted}. "
            "Only the human advances the stage; wait for their message."
        )


def has_submitted(conn: Connection, session: AgentSession, role: Role, stage: int) -> bool:
    return bool(conn.execute(
        text("SELECT COUNT(*) FROM submissions WHERE session_id = :s AND agent = :a AND stage = :g"),
        {"s": session.id, "a": role, "g": stage},
    ).scalar_one())


def require_not_submitted(conn: Connection, session: AgentSession, role: Role) -> None:
    if has_submitted(conn, session, role, session.stage):
        raise CouncilError(f"You already submitted for stage {session.stage}; that work is frozen.")


def _words(value: str) -> int:
    return len(value.split())


def _check_summary(summary: str) -> str:
    body = summary.strip()
    if not body:
        raise ClaimRuleError("A summary is required.")
    if _words(body) > SUMMARY_WORD_LIMIT:
        raise ClaimRuleError(f"The summary has {_words(body)} words; the limit is {SUMMARY_WORD_LIMIT} (aim for 120).")
    return body


# ---------------------------------------------------------------------------------------------
# Data (frozen snapshots)
# ---------------------------------------------------------------------------------------------


def _snapshot(data_dir: Path, cik: str) -> CompanyFactsSnapshot:
    doc = read_cached_document(data_dir / "edgar", cik, "companyfacts")
    if doc is None:
        raise NotFoundError(f"No frozen snapshot for CIK{normalize_cik(cik)} in {data_dir / 'edgar'}. Ask the human to fetch it.")
    return CompanyFactsSnapshot(doc)


def list_snapshots(conn: Connection, data_dir: Path) -> list[dict[str, Any]]:
    root = data_dir / "edgar"
    found: list[dict[str, Any]] = []
    for meta in sorted(root.glob("CIK*/companyfacts.meta.json")):
        cik = meta.parent.name[3:]
        snap = _snapshot(data_dir, cik)
        registered = conn.execute(
            text("SELECT COUNT(*) FROM sources WHERE source_key = :k"),
            {"k": f"edgar:CIK{snap.cik}:companyfacts:{snap.sha256[:12]}"},
        ).scalar_one() > 0
        found.append({
            "cik": snap.cik, "entity_name": snap.entity_name, "retrieved_at": snap.retrieved_at.isoformat(),
            "sha256_prefix": snap.sha256[:12], "registered_as_source": bool(registered), "data_mode": "FROZEN_SNAPSHOT",
        })
    return found


def show_snapshot(data_dir: Path, cik: str) -> dict[str, Any]:
    """The curated metrics available for a company, latest annual and quarterly value each, with provenance."""
    snap = _snapshot(data_dir, cik)
    periods = identify_fiscal_periods(snap)
    metrics: dict[str, Any] = {}
    for name, spec in METRICS.items():
        row: dict[str, Any] = {"label": spec.label, "unit": spec.unit}
        for basis in ("annual", "quarterly"):
            found = lookup_metric(snap, name, basis)  # type: ignore[arg-type]
            if found.resolved is None:
                row[basis] = None
                continue
            f = found.resolved.selected
            row[basis] = {
                "value": format(f.value, "f"), "concept": f"{f.taxonomy}:{f.concept}",
                "period_start": f.start.isoformat() if f.start else None, "period_end": f.end.isoformat(),
                "filed": f.filed.isoformat(), "form": f.form, "accession": f.accession,
                "conflict": found.resolved.conflict,
            }
        metrics[name] = row
    return {
        "cik": snap.cik, "entity_name": snap.entity_name, "data_mode": "FROZEN_SNAPSHOT",
        "retrieved_at": snap.retrieved_at.isoformat(), "source_url": snap.document.meta.url,
        "latest_annual_period_end": periods.latest_annual.end.isoformat() if periods.latest_annual else None,
        "latest_quarterly_period_end": periods.latest_quarterly.end.isoformat() if periods.latest_quarterly else None,
        "note": "Frozen snapshot, not live; newer filings may exist. No stock-price data is available: any "
                "price-based claim must be recorded as a GAP.",
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------------------------
# Evidence and claims
# ---------------------------------------------------------------------------------------------


def _evidence_dict(e: EvidenceRecord) -> dict[str, Any]:
    return {
        "code": e.code, "metric": e.metric_name, "concept": f"{e.taxonomy}:{e.concept}" if e.concept else None,
        "value": format(e.value.normalize(), "f") if e.value is not None else None, "unit": e.unit,
        "period_start": e.period_start.isoformat() if e.period_start else None,
        "period_end": e.period_end.isoformat() if e.period_end else None,
        "filed": e.filed_date.isoformat() if e.filed_date else None, "form": e.form, "accession": e.accession,
        "verification": e.verification, "verification_detail": e.verification_detail,
        "flag": e.flag, "flag_detail": e.flag_detail, "source_url": e.source_url,
        "source_retrieved_at": e.source_retrieved_at.isoformat(sep=" "),
    }


def _claim_dict(c: ClaimRecord) -> dict[str, Any]:
    return {
        "code": c.code, "agent": c.agent, "stage": c.stage, "type": c.claim_type, "text": c.text, "evidence": list(c.evidence_codes),
        "basis": c.basis, "falsifier": c.falsifier, "downgraded": c.downgraded,
        "human_ruling": c.human_ruling, "human_note": c.human_note,
    }


def add_evidence(
    conn: Connection, session: AgentSession, role: Role, data_dir: Path, *, cik: str | None, metric: str | None,
    basis: str, taxonomy: str, concept: str | None, unit: str | None, period_end: Any, period_start: Any,
    value: Decimal | None, metric_name: str | None,
) -> dict[str, Any]:
    """Register evidence from a frozen snapshot, verified deterministically. A missing metric becomes a GAP claim."""
    require_stage(session, (1, 2), "register evidence")
    require_not_submitted(conn, session, role)
    target_cik = cik or session.target_cik
    if not target_cik:
        raise EvidenceError("This session has no target CIK; pass --cik for a snapshot in the dataset.")
    snapshot = _snapshot(data_dir, target_cik)
    if metric:
        if basis not in ("annual", "quarterly"):
            raise EvidenceError("--basis must be annual or quarterly")
        out = record_metric_evidence(conn, session, agent=role, snapshot=snapshot, metric=metric, basis=basis,  # type: ignore[arg-type]
                                     register_source=False)
        if out.evidence is not None:
            return {"result": "evidence", "evidence": _evidence_dict(out.evidence)}
        assert out.gap_claim is not None
        return {"result": "gap", "gap_claim": _claim_dict(out.gap_claim),
                "note": "The metric is not in the snapshot; a GAP claim was recorded. Nothing was estimated."}
    if not (concept and unit and period_end):
        raise EvidenceError("Give either --metric, or --concept, --unit and --period-end.")
    ev = record_fact_evidence(
        conn, session, added_by=role, snapshot=snapshot, metric_name=metric_name or concept, taxonomy=taxonomy,
        concept=concept, unit=unit, period_end=period_end, period_start=period_start, claimed_value=value,
        register_source=False,
    )
    return {"result": "evidence", "evidence": _evidence_dict(ev)}


def add_agent_claim(
    conn: Connection, session: AgentSession, role: Role, *, claim_type: str, text_value: str,
    evidence: Sequence[str], basis: Sequence[str], falsifier: str | None, relevance: str | None, rank: int | None,
) -> dict[str, Any]:
    require_stage(session, (1, 2), "file a claim")
    require_not_submitted(conn, session, role)
    for code in evidence:  # an agent may cite only its own evidence, so cited work is attributable
        if get_evidence(conn, session.id, code).added_by != role:
            raise ClaimRuleError(f"Evidence {code} was registered by the other researcher; cite only your own evidence.")
    claim = add_claim(
        conn, session, agent=role, claim_type=claim_type,  # type: ignore[arg-type]
        text_value=text_value, evidence_codes=list(evidence), basis=list(basis) or None, falsifier=falsifier,
        relevance=relevance, rank_in_brief=rank,
    )
    out = {"result": "claim", "claim": _claim_dict(claim)}
    if claim.downgraded:
        out["warning"] = "Stored as UNVERIFIED: none of the cited evidence verified. It cannot be presented as a fact."
    return out


def own_claims(conn: Connection, session: AgentSession, role: Role) -> list[ClaimRecord]:
    return [c for c in list_claims(conn, session.id) if c.agent == role]


def own_evidence(conn: Connection, session: AgentSession, role: Role) -> list[EvidenceRecord]:
    return [e for e in list_evidence(conn, session.id) if e.added_by == role]


# ---------------------------------------------------------------------------------------------
# Submissions, brief, challenges, final position
# ---------------------------------------------------------------------------------------------


def submit(conn: Connection, session: AgentSession, role: Role, summary: str) -> dict[str, Any]:
    """Close your work for stage 1 or 2. Stage 3 uses :func:`submit_final`."""
    require_stage(session, (1, 2), "submit")
    require_not_submitted(conn, session, role)
    body = _check_summary(summary)
    if session.stage == 1:
        n = sum(1 for c in own_claims(conn, session, role) if c.stage == 1)
        if n == 0:
            raise CouncilError(
                "Nothing to submit: file at least one claim first. If you found nothing material, file a GAP claim "
                "saying so (for example 'No material contrary evidence found for <topic> in the available data')."
            )
    else:
        made = conn.execute(text("SELECT COUNT(*) FROM challenges WHERE session_id = :s AND from_agent = :a"),
                            {"s": session.id, "a": role}).scalar_one()
        if made == 0:
            raise CouncilError("Nothing to submit: file at least one challenge response first.")
    conn.execute(
        text("INSERT INTO submissions (session_id, agent, stage, summary, submitted_at) VALUES (:s, :a, :g, :m, UTC_TIMESTAMP())"),
        {"s": session.id, "a": role, "g": session.stage, "m": body},
    )
    return {"result": "submitted", "stage": session.stage, "role": role,
            "note": "Your work for this stage is now frozen. Post a short brief in the room and wait for the human."}


def show_other_brief(conn: Connection, session: AgentSession, role: Role) -> dict[str, Any]:
    """The other researcher's filed brief. Refused before stage 2 and until you have filed your own."""
    require_open(session)
    if session.stage < 2:
        raise CouncilError("The other researcher's brief is not readable at stage 1 (blind first pass).")
    if not has_submitted(conn, session, role, 1):
        raise CouncilError("Submit your own stage-1 brief before reading the other researcher's.")
    other = other_role(role)
    sub = conn.execute(
        text("SELECT summary, submitted_at FROM submissions WHERE session_id = :s AND agent = :a AND stage = 1"),
        {"s": session.id, "a": other},
    ).first()
    if sub is None:
        raise CouncilError(f"The {other} has not submitted a stage-1 brief yet.")
    evidence = {e.code: e for e in list_evidence(conn, session.id) if e.added_by == other}
    claims = [c for c in list_claims(conn, session.id) if c.agent == other]
    return {
        "from": other, "summary": sub[0], "submitted_at": str(sub[1]),
        "claims": [{**_claim_dict(c), "evidence_details": [_evidence_dict(evidence[x]) for x in c.evidence_codes if x in evidence]} for c in claims],
        "reminder": f"Challenge at most {MAX_CHALLENGES} of these claims. GAP claims cannot be challenged.",
    }


def add_challenge(
    conn: Connection, session: AgentSession, role: Role, *, target: str, stance: str, restated: str, argument: str,
    counter_evidence: Sequence[str],
) -> dict[str, Any]:
    require_stage(session, (2,), "file a challenge")
    require_not_submitted(conn, session, role)
    if stance not in STANCES:
        raise ClaimRuleError(f"stance must be one of {', '.join(STANCES)}")
    if not restated.strip() or not argument.strip():
        raise ClaimRuleError("Restate the claim fairly (--restated) and give your response (--argument).")
    claim = get_claim(conn, session.id, target)
    if claim.agent == role:
        raise ClaimRuleError("You can challenge only the other researcher's claims.")
    if claim.claim_type == "GAP":
        raise ClaimRuleError("A GAP states missing data; it cannot be challenged.")
    made = conn.execute(text("SELECT COUNT(*) FROM challenges WHERE session_id = :s AND from_agent = :a"),
                        {"s": session.id, "a": role}).scalar_one()
    if made >= MAX_CHALLENGES:
        raise ClaimRuleError(f"You have already challenged {MAX_CHALLENGES} claims; that is the limit for the round.")
    for code in counter_evidence:
        get_evidence(conn, session.id, code)
    downgraded = False
    if stance == "disputes" and not counter_evidence:
        stance, downgraded = "needs_evidence", True  # a dispute without counter-evidence is only a request for evidence
    try:
        conn.execute(
            text("INSERT INTO challenges (session_id, from_agent, target_claim_id, stance, restated, argument, counter_evidence) "
                 "VALUES (:s, :a, :c, :st, :r, :g, :ce)"),
            {"s": session.id, "a": role, "c": claim.id, "st": stance, "r": restated.strip(), "g": argument.strip(),
             "ce": json.dumps(list(counter_evidence)) if counter_evidence else None},
        )
    except IntegrityError:
        raise ClaimRuleError(f"You already challenged {target}.") from None
    out: dict[str, Any] = {"result": "challenge", "target": target, "stance": stance, "challenges_made": int(made) + 1,
                           "remaining": MAX_CHALLENGES - int(made) - 1}
    if downgraded:
        out["warning"] = "'disputes' needs counter-evidence; recorded as 'needs_evidence'. Register evidence and cite it to dispute."
    return out


def submit_final(conn: Connection, session: AgentSession, role: Role, position: dict[str, Any]) -> dict[str, Any]:
    require_stage(session, (3,), "file a final position")
    require_not_submitted(conn, session, role)
    mine = {c.code for c in own_claims(conn, session, role)}

    def pairs(key: str) -> list[dict[str, str]]:
        items = position.get(key) or []
        if not isinstance(items, list):
            raise ClaimRuleError(f"'{key}' must be a list of {{claim, reason}} objects")
        clean = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get("claim", "")).strip() or not str(item.get("reason", "")).strip():
                raise ClaimRuleError(f"Every entry in '{key}' needs a 'claim' code and a 'reason'")
            if item["claim"] not in mine:
                raise ClaimRuleError(f"{item['claim']} is not one of your claims")
            clean.append({"claim": item["claim"], "reason": str(item["reason"]).strip()})
        return clean

    concessions, holds = pairs("concessions"), pairs("still_holds")
    gaps = position.get("could_not_establish") or []
    if not isinstance(gaps, list) or not all(isinstance(g, str) and g.strip() for g in gaps):
        raise ClaimRuleError("'could_not_establish' must be a list of non-empty strings")
    if not (concessions or holds or gaps):
        raise ClaimRuleError("A final position needs at least one concession, one claim you still hold, or something you could not establish.")
    summary = _check_summary(position["summary"]) if position.get("summary") else None
    conn.execute(
        text("INSERT INTO submissions (session_id, agent, stage, summary, concessions, still_holds, could_not_establish, submitted_at) "
             "VALUES (:s, :a, 3, :m, :c, :h, :g, UTC_TIMESTAMP())"),
        {"s": session.id, "a": role, "m": summary, "c": json.dumps(concessions), "h": json.dumps(holds), "g": json.dumps(gaps)},
    )
    return {"result": "final_position_filed", "role": role, "concessions": len(concessions), "still_holds": len(holds),
            "could_not_establish": len(gaps), "note": "The human will now assemble the dossier."}


# ---------------------------------------------------------------------------------------------
# `next`: the agent's single source of truth for what to do now
# ---------------------------------------------------------------------------------------------


def _allowed_commands(conn: Connection, session: AgentSession, role: Role) -> list[str]:
    if session.status != "OPEN":
        return []
    submitted = has_submitted(conn, session, role, session.stage)
    if session.stage == 1:
        return ["next"] if submitted else ["data list", "data show", "evidence add", "claim add", "claim list", "evidence list", "submit"]
    if session.stage == 2:
        base = ["next", "brief show --other"]
        return base if submitted else base + ["data show", "evidence add", "claim add", "challenge add", "submit"]
    return ["next"] if submitted else ["next", "brief show --other", "final"]


def next_view(conn: Connection, session: AgentSession, role: Role, data_dir: Path | None) -> dict[str, Any]:
    """What the agent may know and do right now. Holds only sanitised portfolio data."""
    submitted = has_submitted(conn, session, role, session.stage)
    claims = own_claims(conn, session, role)
    made = conn.execute(text("SELECT COUNT(*) FROM challenges WHERE session_id = :s AND from_agent = :a"),
                        {"s": session.id, "a": role}).scalar_one()
    view: dict[str, Any] = {
        "session": session.code, "role": role, "status": session.status, "stage": session.stage,
        "task": STAGE_TASKS[session.stage], "stage_work_submitted": submitted,
        "target": {"ticker": session.target_ticker, "cik": session.target_cik, "sector": session.target_sector},
        "thesis": session.thesis, "data_mode": session.data_mode,
        "portfolio_summary_sanitised": session.shared_summary,
        "freshness_heuristics": session.freshness_cfg,
        "your_progress": {"claims": len(claims), "evidence": len(own_evidence(conn, session, role)), "challenges_made": int(made)},
        "allowed_commands_now": _allowed_commands(conn, session, role),
        "rules": [
            "Every number comes from a registered evidence reference; otherwise file an ASSUMPTION (with basis and falsifier), UNVERIFIED or GAP.",
            "The data is a frozen SEC EDGAR snapshot, not live. There is no stock-price data; price-based claims are GAPs.",
            "You never have the user's portfolio, only the sanitised summary above.",
            "Do not give advice (no buy/sell/hold). Only the human advances the stage.",
        ],
    }
    if data_dir is not None and session.stage <= 2 and not submitted:
        view["data_available"] = list_snapshots(conn, data_dir)
    if session.stage == 3:
        mine_codes = {c.code for c in claims}
        received = conn.execute(
            text("SELECT ch.from_agent, c.code, ch.stance, ch.restated, ch.argument, ch.counter_evidence "
                 "FROM challenges ch JOIN claims c ON c.id = ch.target_claim_id WHERE ch.session_id = :s ORDER BY ch.id"),
            {"s": session.id},
        ).all()
        view["challenges_on_your_claims"] = [
            {"from": r[0], "claim": r[1], "stance": r[2], "restated": r[3], "argument": r[4],
             "counter_evidence": as_json(r[5]) if r[5] is not None else []}
            for r in received if r[1] in mine_codes
        ]
        view["human_rulings"] = [
            {"claim": c.code, "agent": c.agent, "ruling": c.human_ruling, "note": c.human_note}
            for c in list_claims(conn, session.id) if c.human_ruling
        ]
        view["final_position_format"] = {
            "summary": "optional, <=150 words",
            "concessions": [{"claim": "C-?1", "reason": "..."}],
            "still_holds": [{"claim": "C-?2", "reason": "..."}],
            "could_not_establish": ["..."],
        }
    return view
