"""Deterministic Markdown dossier renderer.

Pure function of its inputs: no clock, no randomness, no network, no LLM. The caller supplies
``generated_at``. Agent-written text (claims) is rendered verbatim and labelled by claim type; the
renderer never summarises or rewrites it. Anything missing is stated as missing, never filled in.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from council.evidence.freshness import LABEL as HEURISTICS_LABEL
from council.evidence.service import ClaimRecord, EvidenceRecord
from council.portfolio.metrics import UNCLASSIFIED, quantize
from council.report.model import DossierData

TEMPLATE_VERSION = "1"

_DISCLAIMER = (
    "> **Research and decision support only. This is not financial advice and contains no recommendation "
    "to buy, sell or hold any security.** The decision is the human investor's."
)

_RULING_LABEL = {
    "accept": "accepted by the human",
    "needs_evidence": "human asked for more evidence",
    None: "not yet ruled",
}


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _table(headers: list[str], rows: Iterable[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _num(value: Decimal | None) -> str:
    """Exact value without trailing zeros (storage keeps 6 decimals; the report shouldn't show them)."""
    return "" if value is None else format(value.normalize(), ",f")


def _money(value: Decimal) -> str:
    return format(quantize(value, 2), ",f")


def _period(e: EvidenceRecord) -> str:
    if e.period_start and e.period_end:
        return f"{e.period_start.isoformat()} to {e.period_end.isoformat()}"
    return f"as of {e.period_end.isoformat()}" if e.period_end else ""


def _fiscal(e: EvidenceRecord) -> str:
    parts = [str(e.fiscal_year) if e.fiscal_year else "", e.fiscal_period or ""]
    text = " ".join(p for p in parts if p)
    return f"{text} (as reported on the filing)" if text else "not reported"


def render_dossier(data: DossierData, *, generated_at: datetime, include_local_detail: bool = False) -> str:
    """Render the dossier. ``include_local_detail`` adds position-level data and must stay local."""
    out: list[str] = []
    add = out.append
    session = data.session
    evidence_by_code = {e.code: e for e in data.evidence}

    add("# Investor Council: Research Dossier")
    add("")
    add(_DISCLAIMER)
    add("")
    if data.evidence:
        retrieved = sorted({e.source_retrieved_at for e in data.evidence})
        span = retrieved[0].date().isoformat() if len(retrieved) == 1 else f"{retrieved[0].date()} to {retrieved[-1].date()}"
        add(f"> **DATA MODE: FROZEN SNAPSHOT.** Financial-statement data from SEC EDGAR, retrieved {span} (UTC). "
            "It is not live and newer filings may exist.")
    else:
        add("> **DATA MODE: FROZEN SNAPSHOT.** No financial data has been cited in this dossier yet. Any data used "
            "will be a frozen SEC EDGAR snapshot, not live, and newer filings may exist.")
    add("")
    if include_local_detail:
        add("> **LOCAL ONLY: this version contains position-level portfolio data. Do not post it to a shared room.**")
        add("")

    if session:
        add(f"- **Session:** {session.code}  ·  **Target:** {session.target_ticker}  ·  **Session date:** {session.session_date.isoformat()}"
            f"  ·  **Stage:** {session.stage} of 3  ·  **Status:** {session.status}")
        add(f"- **Human's thesis / question (verbatim):** {_cell(session.thesis)}")
    else:
        add("- **Session:** none. Portfolio-only dossier; no research target selected.")
    add(f"- **Generated:** {generated_at.isoformat()}  ·  **Template:** v{TEMPLATE_VERSION}")
    add("")

    _portfolio_sections(data, out, include_local_detail)

    # Arguments
    for number, (title, agent) in enumerate((("Positive arguments (Bull Researcher)", "bull"), ("Negative arguments (Bear Researcher)", "bear")), start=4):
        add(f"## {number}. {title}")
        add("")
        out.extend(_argument_section(data, agent, evidence_by_code))
    if data.challenges:
        add("### Challenge round")
        add("")
        out.extend(_table(
            ["From", "Targets", "Stance", "Restated claim", "Response", "Counter-evidence"],
            [[c.from_agent, c.target_claim, c.stance, c.restated, c.argument, ", ".join(c.counter_evidence) or "none cited"] for c in data.challenges],
        ))
        add("")

    # Verified evidence
    add("## 6. Verified financial evidence")
    add("")
    verified = [e for e in data.evidence if e.verification == "VERIFIED"]
    if verified:
        add("Each row was matched against the stored, hash-checked snapshot. Matching proves provenance, not that the source is correct or complete.")
        add("")
        out.extend(_table(
            ["ID", "Metric", "Value", "Unit", "Period", "Fiscal period", "Form", "Filed", "Accession", "Source URL", "Retrieved (UTC)", "Flag"],
            [[e.code, e.metric_name, _num(e.value), e.unit or "", _period(e), _fiscal(e), e.form or "", e.filed_date.isoformat() if e.filed_date else "",
              e.accession or "", e.source_url, e.source_retrieved_at.isoformat(sep=" "), e.flag] for e in verified],
        ))
    else:
        add("_No verified financial evidence has been recorded. This is a gap, not a finding._")
    add("")

    out.extend(_missing_section(data, evidence_by_code))
    out.extend(_limitations_section(data))
    out.extend(_sources_section(data, include_local_detail))

    add("## 10. Human decision")
    add("")
    add("_To be written by the human investor in their own words. This tool never fills this field._")
    if data.human_note:
        add("")
        add(f"> {_cell(data.human_note)}")
    add("")
    return "\n".join(out).rstrip() + "\n"


def _portfolio_sections(data: DossierData, out: list[str], local: bool) -> None:
    add = out.append
    s = data.shared_summary
    m = data.metrics
    add("## 1. Portfolio overview")
    add("")
    add(f"- **Holdings:** {s['holdings_count']}")
    asof = s.get("price_as_of")
    add(f"- **Prices:** supplied by the user in the CSV{f' (as of {asof})' if asof else ' (as-of date not provided)'}; "
        "no market data was retrieved by this tool.")
    if s.get("target_ticker"):
        if s.get("target_held"):
            add(f"- **Target {s['target_ticker']}:** currently held at about {s['target_weight_pct']}% of the portfolio.")
        else:
            add(f"- **Target {s['target_ticker']}:** not currently held.")
        sector = s.get("target_sector")
        overlap = s.get("overlap_count")
        if overlap is None:
            add("- **Same-sector overlap:** not computed because the target's sector label is unknown.")
        else:
            add(f"- **Same-sector overlap:** {overlap} other holding(s) share the sector label '{sector}' "
                "(a heuristic: sector labels come from the user's CSV and may differ for the same industry).")
    if s.get("portfolio_partial"):
        add(f"- **Warning: partial portfolio.** {data.portfolio.excluded_rows} invalid row(s) were excluded at ingestion, "
            "so weights below describe only the valid rows.")
    if s.get("unclassified_pct"):
        add(f"- **Unclassified:** {s['unclassified_pct']}% of value has no sector label.")
    add("")
    if local:
        add("### Positions (local only)")
        add("")
        out.extend(_table(
            ["Ticker", "Sector", "Shares", "Price", "Market value", "Weight %"],
            [[p.ticker, p.sector or UNCLASSIFIED, _num(p.shares), _num(p.price), _money(p.market_value), quantize(p.weight_pct, 2)] for p in m.positions],
        ))
        add("")
        add(f"Total portfolio value (from user-supplied prices): {_money(m.total_value)}")
        add("")

    add("## 2. Sector allocation")
    add("")
    if local:
        out.extend(_table(["Sector", "Weight %", "Holdings"], [[x.sector, quantize(x.weight_pct, 2), x.holdings] for x in m.sectors]))
    else:
        out.extend(_table(["Sector", "Weight % (rounded)"], [[name, pct] for name, pct in s["top_sectors"]]))
        add("")
        add("_Largest sectors only (sanitised view)._")
    add("")

    c = m.concentration
    add("## 3. Concentration analysis")
    add("")
    if local:
        rows = [
            ["Largest position", f"{quantize(c.top1_pct, 2)}%"],
            ["Top 3 positions", f"{quantize(c.top3_pct, 2)}%"],
            ["Top 5 positions", f"{quantize(c.top5_pct, 2)}%"],
            ["HHI (positions, 0 to 10,000)", quantize(c.hhi, 1)],
            ["Effective number of equal-weight holdings", quantize(c.effective_holdings, 2)],
            ["HHI (sectors, 0 to 10,000)", quantize(c.sector_hhi, 1)],
        ]
    else:
        rows = [
            ["Largest position", f"{s['top1_pct']}%"],
            ["Top 3 positions", f"{s['top3_pct']}%"],
            ["Top 5 positions", f"{s['top5_pct']}%"],
            ["HHI (positions, 0 to 10,000)", s["hhi"]],
            ["Effective number of equal-weight holdings", s["effective_holdings"]],
        ]
    out.extend(_table(["Measure", "Value"], rows))
    add("")
    add("_HHI is the sum of squared percentage weights; it is descriptive and carries no recommendation. "
        "With fewer than 3 or 5 holdings the top-N figures cover all holdings._")
    add("")


def _evidence_refs(claim: ClaimRecord, by_code: dict[str, EvidenceRecord]) -> str:
    parts = []
    for code in claim.evidence_codes:
        e = by_code.get(code)
        parts.append(f"{code} ({e.verification.lower()}{', ' + e.flag if e and e.flag != 'NONE' else ''})" if e else code)
    return ", ".join(parts) if parts else "none"


def _argument_section(data: DossierData, agent: str, by_code: dict[str, EvidenceRecord]) -> list[str]:
    claims = [c for c in data.claims if c.agent == agent and c.claim_type != "GAP"]
    if not claims:
        return [
            "_No research has been filed by this agent for this dossier. Nothing has been written in its place; "
            "this is recorded under Missing information._",
            "",
        ]
    out: list[str] = []
    rejected = [c for c in claims if c.human_ruling == "reject"]
    live = [c for c in claims if c.human_ruling != "reject"]
    groups = (
        ("FACT", "Supported by verified evidence (FACT)"),
        ("ASSUMPTION", "Assumptions (inferences, with what would prove them wrong)"),
        ("UNVERIFIED", "Unverified (not presented as fact)"),
    )
    for ctype, heading in groups:
        subset = [c for c in live if c.claim_type == ctype]
        if not subset:
            continue
        out += [f"### {heading}", ""]
        for c in subset:
            out.append(f"- **{c.code}** ({_RULING_LABEL[c.human_ruling]}): {_cell(c.text)}")
            out.append(f"  - Evidence: {_evidence_refs(c, by_code)}")
            if c.claim_type == "ASSUMPTION":
                out.append(f"  - Basis: {', '.join(map(str, c.basis or []))}. Would be wrong if: {_cell(c.falsifier or '')}")
            if c.downgraded:
                out.append("  - Downgraded from FACT: the cited evidence did not verify.")
        out.append("")
    if rejected:
        out += ["### Rejected by the human", ""]
        for c in rejected:
            note = f" Note: {_cell(c.human_note)}" if c.human_note else ""
            out.append(f"- **{c.code}** ({c.claim_type}): {_cell(c.text)}{note}")
        out.append("")
    return out


def _missing_section(data: DossierData, by_code: dict[str, EvidenceRecord]) -> list[str]:
    out = ["## 7. Missing information", ""]
    items: list[str] = []
    for c in data.claims:
        if c.claim_type == "GAP":
            items.append(f"- **{c.code}** ({c.agent}) gap: {_cell(c.text)}")
    for e in data.evidence:
        if e.verification != "VERIFIED":
            items.append(f"- **{e.code}** {e.metric_name}: verification {e.verification} ({_cell(e.verification_detail or 'no detail')}). Not treated as evidence.")
    for e in data.evidence:
        if e.flag != "NONE":
            items.append(f"- **{e.code}** {e.metric_name}: flagged {e.flag}. {_cell(e.flag_detail or '')}")
    for c in data.claims:
        if c.human_ruling == "needs_evidence":
            items.append(f"- **{c.code}**: the human asked for more evidence before relying on this claim.")
    unruled = [c.code for c in data.claims if c.human_ruling is None and c.claim_type in ("UNVERIFIED", "ASSUMPTION")]
    if unruled:
        items.append(f"- Awaiting a human ruling: {', '.join(unruled)}.")
    if data.session and not data.claims:
        items.append("- No claims have been filed yet, so there are no positive or negative arguments to show.")
    if not data.session:
        items.append("- No research session: positive and negative arguments are not available for a portfolio-only dossier.")
    items.append("- No stock-price or market-data source is part of this dataset. Valuation multiples, returns and "
                 "any price-based analysis are therefore out of scope and are not estimated.")
    out += items
    out.append("")
    return out


def _limitations_section(data: DossierData) -> list[str]:
    out = ["## 8. Limitations", ""]
    cfg = data.freshness
    out += [
        "- The data is a **frozen snapshot**, not live. Newer filings, restatements or corrections may exist.",
        "- Verification confirms that a figure appears in the stored snapshot (provenance). It does not confirm that the "
        "source is correct, complete or current.",
        "- Fiscal year/period labels are shown as reported on the filing that contained each value; a comparative "
        "figure inside a later filing carries that filing's labels.",
        "- Portfolio weights use prices supplied by the user and are only as accurate as that file. Sector overlap "
        "depends on the user's own sector labels.",
        "- Claims are made by AI research agents. Typing (FACT, ASSUMPTION, UNVERIFIED, GAP) and human rulings show "
        "how much weight each deserves; none is a recommendation.",
    ]
    if cfg:
        out.append(
            f"- Freshness flags use thresholds of {cfg.annual_max_age_days} days (annual data), {cfg.quarterly_max_age_days} days "
            f"(quarterly data) and {cfg.snapshot_max_age_days} days (snapshot age). These are {HEURISTICS_LABEL}."
        )
    else:
        out.append(f"- Freshness thresholds, when used, are {HEURISTICS_LABEL}.")
    out.append("")
    return out


def _sources_section(data: DossierData, local: bool) -> list[str]:
    out = ["## 9. Sources", ""]
    seen: dict[tuple[str, str], list[EvidenceRecord]] = {}
    for e in data.evidence:
        seen.setdefault((e.source_url, e.source_sha256), []).append(e)
    if seen:
        out += _table(
            ["Source", "URL", "Retrieved (UTC)", "SHA-256 (first 16)", "Evidence"],
            [[rows[0].source_name, url, rows[0].source_retrieved_at.isoformat(sep=" "), sha[:16], ", ".join(r.code for r in rows)] for (url, sha), rows in seen.items()],
        )
    else:
        out.append("_No external sources have been cited yet._")
    out.append("")
    # The content hash is withheld from the shareable version: for a small, low-entropy file it would let
    # anyone holding a guess confirm it. The local-detail version keeps it for the owner's own records.
    if local:
        out.append(f"Portfolio: user-supplied CSV (content hash {data.portfolio.csv_sha256[:12]}...); the file itself is not included.")
    else:
        out.append("Portfolio: user-supplied CSV; neither the file nor its fingerprint is included in this shareable version.")
    out.append("")
    return out
