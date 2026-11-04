"""Database-backed evidence and claim services.

These are the building blocks the agent tooling will call after kickoff. They are deliberately
free of any Switch or agent-prompt logic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Sequence

from sqlalchemy import Connection, text

from council.edgar.facts import CompanyFactsSnapshot
from council.edgar.metrics import MetricLookup, lookup_metric
from council.edgar.models import SOURCE_NAME, Basis
from council.errors import ClaimRuleError, EvidenceError, NotFoundError
from council.evidence.freshness import FreshnessConfig, assess_freshness
from council.evidence.verify import verify_fact, verify_file_integrity
from council.sessions import SessionLike, as_json

log = logging.getLogger(__name__)

Agent = Literal["bull", "bear"]
ClaimType = Literal["FACT", "ASSUMPTION", "UNVERIFIED", "GAP"]
Ruling = Literal["accept", "reject", "needs_evidence"]
_AGENT_LETTER = {"bull": "B", "bear": "X"}


# ---------------------------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------------------------


def register_snapshot_source(conn: Connection, snapshot: CompanyFactsSnapshot) -> int:
    """Record an exact, hash-identified snapshot as a source. Idempotent for identical content."""
    meta = snapshot.document.meta
    key = f"edgar:CIK{snapshot.cik}:companyfacts:{meta.sha256[:12]}"
    existing = conn.execute(text("SELECT id FROM sources WHERE source_key = :k"), {"k": key}).scalar()
    if existing is not None:
        return int(existing)
    result = conn.execute(
        text(
            "INSERT INTO sources (source_key, source_type, source_name, entity_name, url, cik, retrieved_at, "
            "content_sha256, snapshot_path) VALUES (:key, 'FINANCIAL_STATEMENT', :name, :entity, :url, :cik, "
            ":retrieved, :sha, :path)"
        ),
        {
            "key": key,
            "name": SOURCE_NAME,
            "entity": snapshot.entity_name,
            "url": meta.url,
            "cik": snapshot.cik,
            "retrieved": meta.retrieved_at.astimezone(timezone.utc).replace(tzinfo=None),
            "sha": meta.sha256,
            "path": str(snapshot.document.path),
        },
    )
    return int(result.lastrowid)


def find_snapshot_source(conn: Connection, snapshot: CompanyFactsSnapshot) -> int:
    """Look up an already-registered snapshot (agent path: the agent account cannot insert sources).

    Registering is a human step (``council human data register``) so an agent can only cite snapshots the
    human has put in the database, never invent a source row.
    """
    key = f"edgar:CIK{snapshot.cik}:companyfacts:{snapshot.document.meta.sha256[:12]}"
    found = conn.execute(text("SELECT id FROM sources WHERE source_key = :k"), {"k": key}).scalar()
    if found is None:
        raise EvidenceError(
            f"The snapshot for CIK{snapshot.cik} is not registered as a source. Ask the human to run "
            f"`council human data register --cik {int(snapshot.cik)}`."
        )
    return int(found)


# ---------------------------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRecord:
    id: int
    code: str
    session_id: int
    added_by: str
    metric_name: str
    taxonomy: str | None
    concept: str | None
    unit: str | None
    period_start: date | None
    period_end: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed_date: date | None
    accession: str | None
    value: Decimal | None
    verification: str
    verification_detail: str | None
    flag: str
    flag_detail: str | None
    source_name: str
    source_url: str
    source_retrieved_at: datetime
    source_sha256: str


_EVIDENCE_SELECT = (
    "SELECT e.id, e.code, e.session_id, e.added_by, e.metric_name, e.taxonomy, e.concept, e.unit, "
    "e.fact_period_start, e.fact_period_end, e.fact_fiscal_year, e.fact_fiscal_period, e.fact_form, "
    "e.fact_filed_date, e.fact_accession, e.value_num, e.verification, e.verification_detail, e.flag, "
    "e.flag_detail, s.source_name, s.url, s.retrieved_at, s.content_sha256 "
    "FROM evidence_refs e JOIN sources s ON s.id = e.source_id "
)


def _evidence(row) -> EvidenceRecord:
    return EvidenceRecord(*row)


def list_evidence(conn: Connection, session_id: int) -> list[EvidenceRecord]:
    rows = conn.execute(text(_EVIDENCE_SELECT + "WHERE e.session_id = :s ORDER BY e.id"), {"s": session_id}).all()
    return [_evidence(r) for r in rows]


def get_evidence(conn: Connection, session_id: int, code: str) -> EvidenceRecord:
    row = conn.execute(
        text(_EVIDENCE_SELECT + "WHERE e.session_id = :s AND e.code = :c"), {"s": session_id, "c": code}
    ).first()
    if row is None:
        raise NotFoundError(f"Evidence {code} not found in this session")
    return _evidence(row)


def _next_code(conn: Connection, table: str, session_id: int, prefix: str) -> str:
    like = f"{prefix}%"
    n = conn.execute(
        text(
            f"SELECT COALESCE(MAX(CAST(SUBSTRING(code, {len(prefix) + 1}) AS UNSIGNED)), 0) + 1 "
            f"FROM {table} WHERE session_id = :s AND code LIKE :like"
        ),
        {"s": session_id, "like": like},
    ).scalar_one()
    return f"{prefix}{int(n)}"


def record_fact_evidence(
    conn: Connection,
    session: SessionLike,
    *,
    added_by: Agent,
    snapshot: CompanyFactsSnapshot,
    metric_name: str,
    taxonomy: str,
    concept: str,
    unit: str,
    period_end: date,
    period_start: date | None = None,
    claimed_value: Decimal | None = None,
    register_source: bool = True,
) -> EvidenceRecord:
    """Store one financial-statement fact as evidence, verified against the snapshot.

    * Found, no ``claimed_value``: the snapshot's value is stored and verifies trivially.
    * ``claimed_value`` given: it is stored as claimed and VERIFIED only if the snapshot reports
      exactly that value; otherwise FAILED (so a wrong figure is visible, not silently corrected).
    * Not in the snapshot and no claimed value: :class:`EvidenceError`; the caller should record a GAP.
    * The snapshot file's hash is re-checked first, so altered data cannot be cited.
    """
    verify_file_integrity(snapshot.document.path, snapshot.sha256)
    resolved = snapshot.find(taxonomy, concept, unit, period_end, period_start=period_start)
    if resolved is None and claimed_value is None:
        raise EvidenceError(
            f"No {taxonomy}:{concept} ({unit}) value for a period ending {period_end.isoformat()} in the snapshot; "
            "record a GAP instead of inventing a figure."
        )

    value = claimed_value if claimed_value is not None else resolved.selected.value  # type: ignore[union-attr]
    result = verify_fact(
        snapshot,
        taxonomy=taxonomy,
        concept=concept,
        unit=unit,
        period_end=period_end,
        period_start=period_start,
        value=value,
    )
    entry = resolved.selected if resolved else None

    flag, flag_detail = "NONE", None
    if resolved is not None:
        cfg = FreshnessConfig.from_json(session.freshness_cfg)
        freshness = assess_freshness(
            resolved.selected, retrieved_at=snapshot.retrieved_at, session_date=session.session_date, cfg=cfg
        )
        notes: list[str] = []
        if resolved.conflict:
            flag = "CONFLICT"
            others = "; ".join(f"{e.value} (filed {e.filed.isoformat()}, {e.accession})" for e in resolved.conflicting_entries)
            notes.append(
                f"different values reported for the same period: selected {resolved.selected.value} "
                f"(filed {resolved.selected.filed.isoformat()}, {resolved.selected.accession}) vs {others}"
            )
        if freshness.flag == "STALE":
            flag = flag if flag == "CONFLICT" else "STALE"
            notes.append(freshness.detail or "stale")
        flag_detail = " | ".join(notes) or None

    source_id = register_snapshot_source(conn, snapshot) if register_source else find_snapshot_source(conn, snapshot)
    code = _next_code(conn, "evidence_refs", session.id, "E-")
    conn.execute(
        text(
            "INSERT INTO evidence_refs (code, session_id, source_id, added_by, metric_name, taxonomy, concept, unit, "
            "fact_period_start, fact_period_end, fact_fiscal_year, fact_fiscal_period, fact_form, fact_filed_date, "
            "fact_accession, value_num, verification, verification_detail, flag, flag_detail) VALUES "
            "(:code, :sid, :src, :by, :metric, :tax, :concept, :unit, :pstart, :pend, :fy, :fp, :form, :filed, "
            ":accn, :val, :ver, :verdetail, :flag, :flagdetail)"
        ),
        {
            "code": code,
            "sid": session.id,
            "src": source_id,
            "by": added_by,
            "metric": metric_name,
            "tax": taxonomy,
            "concept": concept,
            "unit": unit,
            "pstart": entry.start if entry else period_start,
            "pend": period_end,
            "fy": entry.fiscal_year if entry else None,
            "fp": entry.fiscal_period if entry else None,
            "form": entry.form if entry else None,
            "filed": entry.filed if entry else None,
            "accn": entry.accession if entry else None,
            "val": value,
            "ver": result.status,
            "verdetail": result.detail[:300],
            "flag": flag,
            "flagdetail": flag_detail[:500] if flag_detail else None,
        },
    )
    log.info("Recorded evidence %s (%s, %s) for %s", code, metric_name, result.status, session.code)
    return get_evidence(conn, session.id, code)


# ---------------------------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimRecord:
    id: int
    code: str
    session_id: int
    agent: str
    stage: int
    claim_type: str
    text: str
    basis: Any
    falsifier: str | None
    relevance: str | None
    rank_in_brief: int | None
    downgraded: bool
    human_ruling: str | None
    human_note: str | None
    evidence_codes: tuple[str, ...]


_CLAIM_SELECT = (
    "SELECT c.id, c.code, c.session_id, c.agent, c.stage, c.claim_type, c.text, c.basis, c.falsifier, "
    "c.relevance, c.rank_in_brief, c.downgraded, c.human_ruling, c.human_note FROM claims c "
)


def _claim_records(conn: Connection, rows) -> list[ClaimRecord]:
    records: list[ClaimRecord] = []
    for r in rows:
        codes = conn.execute(
            text(
                "SELECT e.code FROM claim_evidence ce JOIN evidence_refs e ON e.id = ce.evidence_id "
                "WHERE ce.claim_id = :c ORDER BY e.id"
            ),
            {"c": r[0]},
        ).scalars().all()
        records.append(
            ClaimRecord(
                id=int(r[0]), code=r[1], session_id=int(r[2]), agent=r[3], stage=int(r[4]), claim_type=r[5], text=r[6],
                basis=as_json(r[7]) if r[7] is not None else None, falsifier=r[8], relevance=r[9],
                rank_in_brief=r[10], downgraded=bool(r[11]), human_ruling=r[12], human_note=r[13],
                evidence_codes=tuple(codes),
            )
        )
    return records


def list_claims(conn: Connection, session_id: int) -> list[ClaimRecord]:
    rows = conn.execute(text(_CLAIM_SELECT + "WHERE c.session_id = :s ORDER BY c.id"), {"s": session_id}).all()
    return _claim_records(conn, rows)


def get_claim(conn: Connection, session_id: int, code: str) -> ClaimRecord:
    rows = conn.execute(text(_CLAIM_SELECT + "WHERE c.session_id = :s AND c.code = :c"), {"s": session_id, "c": code}).all()
    if not rows:
        raise NotFoundError(f"Claim {code} not found in this session")
    return _claim_records(conn, rows)[0]


def add_claim(
    conn: Connection,
    session: SessionLike,
    *,
    agent: Agent,
    claim_type: ClaimType,
    text_value: str,
    stage: int | None = None,
    evidence_codes: Sequence[str] = (),
    basis: Sequence[str] | None = None,
    falsifier: str | None = None,
    relevance: str | None = None,
    rank_in_brief: int | None = None,
) -> ClaimRecord:
    """Insert a claim, enforcing the typing rules.

    * ``FACT`` needs at least one evidence code. If none of the cited evidence is VERIFIED the claim
      is stored as ``UNVERIFIED`` with ``downgraded`` set; it is never kept as a FACT.
    * ``ASSUMPTION`` needs a ``falsifier`` and a ``basis``.
    * ``UNVERIFIED`` and ``GAP`` need nothing else.
    """
    body = text_value.strip()
    if not body:
        raise ClaimRuleError("Claim text is empty")
    if claim_type not in ("FACT", "ASSUMPTION", "UNVERIFIED", "GAP"):
        raise ClaimRuleError(f"Unknown claim type {claim_type!r}")
    stage_value = stage if stage is not None else session.stage
    if stage_value not in (1, 2, 3):
        raise ClaimRuleError(f"Invalid stage {stage_value}")

    evidence = [get_evidence(conn, session.id, c) for c in evidence_codes]
    downgraded = False
    final_type: str = claim_type
    if claim_type == "FACT":
        if not evidence:
            raise ClaimRuleError("A FACT needs at least one evidence reference; use ASSUMPTION or UNVERIFIED otherwise.")
        if not any(e.verification == "VERIFIED" for e in evidence):
            final_type, downgraded = "UNVERIFIED", True
            log.warning("Claim downgraded FACT -> UNVERIFIED: no verified evidence among %s", list(evidence_codes))
    elif claim_type == "ASSUMPTION":
        if not (falsifier and falsifier.strip()):
            raise ClaimRuleError("An ASSUMPTION needs a falsifier: what observation would prove it wrong.")
        if not basis:
            raise ClaimRuleError("An ASSUMPTION needs a basis: the claim/evidence codes it rests on.")

    code = _next_code(conn, "claims", session.id, f"C-{_AGENT_LETTER[agent]}")
    result = conn.execute(
        text(
            "INSERT INTO claims (code, session_id, agent, stage, claim_type, text, basis, falsifier, relevance, "
            "rank_in_brief, downgraded) VALUES (:code, :sid, :agent, :stage, :type, :text, :basis, :fals, :rel, "
            ":rank, :down)"
        ),
        {
            "code": code, "sid": session.id, "agent": agent, "stage": stage_value, "type": final_type, "text": body,
            "basis": json.dumps(list(basis)) if basis else None,
            "fals": falsifier.strip() if falsifier else None, "rel": relevance, "rank": rank_in_brief,
            "down": downgraded,
        },
    )
    claim_id = int(result.lastrowid)
    for e in evidence:
        conn.execute(text("INSERT INTO claim_evidence (claim_id, evidence_id) VALUES (:c, :e)"), {"c": claim_id, "e": e.id})
    return get_claim(conn, session.id, code)


@dataclass(frozen=True)
class MetricOutcome:
    lookup: MetricLookup
    evidence: EvidenceRecord | None
    gap_claim: ClaimRecord | None


def record_metric_evidence(
    conn: Connection,
    session: SessionLike,
    *,
    agent: Agent,
    snapshot: CompanyFactsSnapshot,
    metric: str,
    basis: Basis = "annual",
    register_source: bool = True,
) -> MetricOutcome:
    """Look up a curated metric. Found: store verified evidence. Missing: store an explicit GAP claim."""
    found = lookup_metric(snapshot, metric, basis)
    if found.resolved is None:
        gap = add_claim(conn, session, agent=agent, claim_type="GAP", text_value=found.gap_text())
        return MetricOutcome(found, None, gap)
    fact = found.resolved.selected
    evidence = record_fact_evidence(
        conn, session, added_by=agent, snapshot=snapshot, metric_name=found.metric.label,
        taxonomy=fact.taxonomy, concept=fact.concept, unit=fact.unit, period_end=fact.end, period_start=fact.start,
        register_source=register_source,
    )
    return MetricOutcome(found, evidence, None)


def rule_claim(conn: Connection, session: SessionLike, claim_code: str, ruling: Ruling, note: str | None = None) -> ClaimRecord:
    """Record the human's ruling on a claim."""
    if ruling not in ("accept", "reject", "needs_evidence"):
        raise ClaimRuleError(f"Unknown ruling {ruling!r}")
    claim = get_claim(conn, session.id, claim_code)
    conn.execute(
        text("UPDATE claims SET human_ruling = :r, human_note = :n, ruled_at = UTC_TIMESTAMP() WHERE id = :id"),
        {"r": ruling, "n": note, "id": claim.id},
    )
    return get_claim(conn, session.id, claim_code)
