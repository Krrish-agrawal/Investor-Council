"""The ruling gate: which claims need the human's ruling, and which are still unresolved.

A claim is **flagged** (needs a ruling) when any of these holds:
* it is ``UNVERIFIED`` (including a ``FACT`` that was downgraded because its evidence did not verify);
* a cited evidence reference is not ``VERIFIED`` or carries a ``STALE`` / ``CONFLICT`` flag;
* the other agent challenged it with stance ``disputes`` or ``needs_evidence``.

A flagged claim is **resolved** only by a human ruling of ``accept`` or ``reject``. No ruling, or the
ruling ``needs_evidence``, leaves it **unresolved**, and an unresolved claim must never be presented as
an approved conclusion. ``GAP`` claims state missing data and are never flagged.

The renderer, ``council human status`` and ``council human finalize`` all use this module, so they cannot
disagree about what is open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from council.errors import ClaimRuleError
from council.evidence.service import ClaimRecord, EvidenceRecord
from council.report.model import ChallengeRow

RESOLVING_RULINGS = ("accept", "reject")
CONTESTING_STANCES = ("disputes", "needs_evidence")


@dataclass(frozen=True)
class FlaggedClaim:
    claim: ClaimRecord
    reasons: tuple[str, ...]

    @property
    def resolved(self) -> bool:
        return self.claim.human_ruling in RESOLVING_RULINGS


def flag_reasons(
    claim: ClaimRecord, evidence_by_code: dict[str, EvidenceRecord], challenges: Iterable[ChallengeRow]
) -> list[str]:
    """Why a claim needs a ruling (empty list: no ruling needed)."""
    if claim.claim_type == "GAP":
        return []
    reasons: list[str] = []
    if claim.claim_type == "UNVERIFIED":
        reasons.append("downgraded from FACT: its evidence did not verify" if claim.downgraded else "UNVERIFIED: no verified evidence")
    for code in claim.evidence_codes:
        e = evidence_by_code.get(code)
        if e is None:
            reasons.append(f"cites unknown evidence {code}")
            continue
        if e.verification != "VERIFIED":
            reasons.append(f"cites evidence {code} whose verification is {e.verification}")
        if e.flag != "NONE":
            reasons.append(f"cites evidence {code} flagged {e.flag}")
    for ch in challenges:
        if ch.target_claim == claim.code and ch.stance in CONTESTING_STANCES:
            reasons.append(f"challenged by the {ch.from_agent} ({ch.stance})")
    return reasons


def flagged_claims(
    claims: Sequence[ClaimRecord], evidence: Sequence[EvidenceRecord], challenges: Sequence[ChallengeRow]
) -> list[FlaggedClaim]:
    by_code = {e.code: e for e in evidence}
    out: list[FlaggedClaim] = []
    for c in claims:
        reasons = flag_reasons(c, by_code, challenges)
        if reasons:
            out.append(FlaggedClaim(c, tuple(reasons)))
    return out


def unresolved_claims(
    claims: Sequence[ClaimRecord], evidence: Sequence[EvidenceRecord], challenges: Sequence[ChallengeRow]
) -> list[FlaggedClaim]:
    return [f for f in flagged_claims(claims, evidence, challenges) if not f.resolved]


def assert_ready_to_finalize(unresolved: Sequence[FlaggedClaim]) -> None:
    """Raise if any flagged claim lacks an accept/reject ruling."""
    if unresolved:
        listing = "; ".join(f"{u.claim.code} ({'; '.join(u.reasons)})" for u in unresolved)
        raise ClaimRuleError(
            f"{len(unresolved)} flagged claim(s) have no accept/reject ruling: {listing}. "
            "Rule on each with `council human rule SESSION CLAIM accept|reject`; 'needs_evidence' is not a resolution."
        )
