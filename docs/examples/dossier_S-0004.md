# Investor Council: Research Dossier

> **Research and decision support only. This is not financial advice and contains no recommendation to buy, sell or hold any security.** The decision is the human investor's.

> **FINAL.** Every flagged claim has an accept or reject ruling from the human.

> **DATA MODE: FROZEN SNAPSHOT.** Financial-statement data from SEC EDGAR, retrieved 2026-11-05 (UTC). It is not live and newer filings may exist.

- **Session:** S-0004  ·  **Target:** SYNT  ·  **Session date:** 2026-11-05  ·  **Stage:** 3 of 3  ·  **Status:** FINALIZED
- **Human's thesis / question (verbatim):** Is SYNTHETIC TEST CORP a durable compounder, and would adding it deepen my technology concentration?
- **Generated:** 2026-11-05T04:18:47.344221+00:00  ·  **Template:** v1

## 1. Portfolio overview

- **Holdings:** 7
- **Prices:** supplied by the user in the CSV (as of 2026-10-30); no market data was retrieved by this tool.
- **Target SYNT:** not currently held.
- **Same-sector overlap:** 2 other holding(s) share the sector label 'Technology' (a heuristic: sector labels come from the user's CSV and may differ for the same industry).
- **Unclassified:** 7.8% of value has no sector label.

## 2. Sector allocation

| Sector | Weight % (rounded) |
| --- | --- |
| Consumer Discretionary | 29.5 |
| Technology | 22.3 |
| Financials | 14.1 |
| Healthcare | 13.7 |
| Energy | 12.7 |

_Largest sectors only (sanitised view)._

## 3. Concentration analysis

| Measure | Value |
| --- | --- |
| Largest position | 29.5% |
| Top 3 positions | 57.5% |
| Top 5 positions | 83.9% |
| HHI (positions, 0 to 10,000) | 1740.0 |
| Effective number of equal-weight holdings | 5.7 |

_HHI is the sum of squared percentage weights; it is descriptive and carries no recommendation. With fewer than 3 or 5 holdings the top-N figures cover all holdings._

## 4. Positive arguments (Bull Researcher)

### Flagged, then accepted by the human

- **C-B8** (FACT; accepted by the human after review): SYNT reported net income of $150,000 on annual revenue of $1,200,000 for FY2024, implying a ~12.5% net profit margin. Both figures are from the 10-K filed 2025-02-14. Both evidence items are flagged STALE (data is a frozen snapshot; period ended 2024-12-31).
  - Evidence: E-1 (verified, STALE), E-7 (verified, STALE)
  - Why it needs a ruling: cites evidence E-1 flagged STALE; cites evidence E-7 flagged STALE; challenged by the bear (needs_evidence)
  - Human's note: Accepted as a statement of what the frozen snapshot shows (STALE flag noted). TEST RUN ruling by the test operator on synthetic data; not an investment decision
- **C-B9** (FACT; accepted by the human after review): Q1 2025 quarterly revenue of $330,000 (10-Q filed 2025-05-10, flagged STALE) annualises to approximately $1,320,000, above FY2024 annual revenue of $1,200,000 (E-1). This suggests modest forward momentum from the single annual period available, but only one annual data point exists so no multi-year growth trend can be claimed.
  - Evidence: E-1 (verified, STALE), E-2 (verified, STALE)
  - Why it needs a ruling: cites evidence E-1 flagged STALE; cites evidence E-2 flagged STALE; challenged by the bear (needs_evidence)
  - Human's note: Accepted as stated by the snapshot; single quarter, no trend claimed. TEST RUN ruling on synthetic data; not an investment decision
- **C-B10** (FACT; accepted by the human after review): Total assets grew from $5,000,000 (FY2024 10-K, E-8, flagged STALE) to $5,100,000 (Q1 2025 10-Q, E-9, flagged STALE), a 2% increase quarter-over-quarter, suggesting modest balance sheet expansion. Without equity or debt breakdowns (C-B6, C-B7), leverage cannot be assessed.
  - Evidence: E-8 (verified, STALE), E-9 (verified, STALE)
  - Why it needs a ruling: cites evidence E-8 flagged STALE; cites evidence E-9 flagged STALE
  - Human's note: Accepted as a statement of what the frozen snapshot shows (STALE flag noted). TEST RUN ruling by the test operator on synthetic data; not an investment decision

### Rejected by the human

- **C-B13** (UNVERIFIED): SYNT is classified as Technology. The portfolio summary provided by the session shows Technology already at 22.3% of holdings (second-largest sector) with 2 existing overlapping holdings. Adding SYNT would increase Technology concentration — the portfolio's HHI is 1740 and effective holdings are 5.7 — but this is from the sanitised portfolio summary, not from EDGAR evidence. Note: Sector label comes from the portfolio summary, not from evidence. TEST RUN ruling by the test operator on synthetic data; not an investment decision

### Brief (stage 1)

Bull case for SYNT is narrow but honest. One FACT stands: FY2024 net income of $150K on $1.2M revenue implies ~12.5% net margin (C-B8, flagged STALE). Q1 2025 revenue of $330K annualises above FY2024 (C-B9), suggesting modest momentum — but only one annual period exists so no durability trend can be claimed. Total assets expanded modestly Q-o-Q (C-B10). Critical gaps: no gross profit, operating income, cash flow, capex, debt or equity data in the snapshot (C-B1 through C-B7), so the compounding thesis cannot be evidenced. Adding SYNT deepens Tech concentration (already 22.3% of portfolio, 2 overlaps) — a concentration risk the evidence does not offset. All evidence flagged STALE.

### Challenge-round summary (stage 2)

Bull challenge round: I partly agree with C-X9 (staleness) — the STALE flag is correctly applied and I registered the same flags, but the figures are VERIFIED against actual SEC filings; the limitation is recency not accuracy, and no fresher snapshot data exists. I partly agree with C-X12 (concentration) — the directional claim is correct, but the magnitude depends on the position weight chosen (target currently 0.0%), and even the Bear's falsifier acknowledges negligible impact at small weights. I fully agree with C-X10 (8 missing metrics) and filed the same gaps myself. No disputes: the Bear's negative case largely mirrors my own gap inventory.

### Final position (stage 3)

The positive case rests on two accepted arithmetic facts from a stale frozen snapshot: a ~12.5% net margin for FY2024 and a Q1 2025 revenue run-rate above the prior annual figure. Both are correctly registered but neither can be extended to a quality or momentum inference without operating-line and cash-flow data, which are absent. The durable compounder thesis cannot be evidenced. I concede C-B13 (rejected: sector label was not EDGAR evidence) and the positive framing on C-B10 (asset growth without debt context is not demonstrably positive). All evidence is flagged STALE.

Concessions:
- **C-B13**: Human ruled rejected. The Technology sector classification was drawn from the portfolio summary, not from registered EDGAR evidence — an evidentiary overreach I should not have filed as a claim tied to EDGAR data.
- **C-B10**: Bear correctly notes that asset growth without equity, debt, or cash context could be debt-funded. The numeric fact (assets $5.0M → $5.1M) is accepted, but the positive framing of this as balance sheet expansion is unwarranted. I concede the valence.

Still holds:
- **C-B8**: Human accepted. Net income $150K on revenue $1.2M and the implied ~12.5% margin are arithmetically correct per verified 10-K data. I concede the Bear challenge: without gross profit or operating income, this cannot be characterised as a quality signal — it stands only as a statement of what the snapshot shows.
- **C-B9**: Human accepted. Q1 2025 revenue of $330K and the annualised run-rate above FY2024 are correctly registered. I concede the Bear challenge: without seasonal context or prior Q1 figures, the word momentum is unsupported — the claim stands only as a revenue data point.
- **C-B12**: No multi-year trend is available; the durable compounder thesis cannot be established from one annual period. This gap is not disputed by either side.

Could not establish:
- Durable compounder thesis: only one annual period of revenue and net income; no gross profit, operating income, operating cash flow, capex, long-term debt, cash, or equity data in the snapshot
- Margin quality: net margin of ~12.5% cannot be characterised as sustainable operating performance without gross profit or operating income lines
- Revenue momentum: a single quarter vs a single annual period with no seasonal context does not establish a growth trend
- Balance sheet resilience: cash, long-term debt, and stockholders equity all absent
- Cash conversion quality: operating cash flow and capex absent
- Technology concentration impact magnitude: sector label not from EDGAR evidence; HHI impact unknown without a chosen target weight
- Valuation: no stock-price data in snapshot

## 5. Negative arguments (Bear Researcher)

### Assumptions (inferences, with what would prove them wrong); no flag raised

- **C-X12** (ASSUMPTION; no flag raised): Adding SYNT (classified Technology) to the portfolio would increase Technology sector exposure above its current 22.3% share, deepening the second-largest sector concentration in a portfolio already running an HHI of 1,740 with effective holdings of only 5.7.
  - Evidence: none
  - Basis: C-X9. Would be wrong if: SYNT is reclassified to a non-Technology sector, or the target weight assigned is negligible (near 0%).

### Flagged, then accepted by the human

- **C-X9** (FACT; accepted by the human after review): All registered evidence (revenue, net income, total assets, shares outstanding) is flagged STALE by the system heuristic: annual period ended 2024-12-31, 674 days before the session date, exceeding the 456-day annual limit. The human cannot rely on this data as current.
  - Evidence: E-3 (verified, STALE), E-4 (verified, STALE), E-5 (verified, STALE), E-6 (verified, STALE)
  - Why it needs a ruling: cites evidence E-3 flagged STALE; cites evidence E-4 flagged STALE; cites evidence E-5 flagged STALE; cites evidence E-6 flagged STALE
  - Human's note: Accepted as a statement of what the frozen snapshot shows (STALE flag noted). TEST RUN ruling by the test operator on synthetic data; not an investment decision
- **C-X10** (UNVERIFIED; accepted by the human after review): Eight key metrics are absent from the snapshot: gross profit (C-X1), operating income (C-X2), operating cash flow (C-X3), long-term debt (C-X4), cash and equivalents (C-X5), total liabilities (C-X6), stockholders equity (C-X7), and capital expenditure (C-X8). Without these, margin structure, leverage, liquidity, and cash conversion cannot be assessed. The snapshot does not support or refute the durable compounder thesis on fundamentals.
  - Evidence: none
  - Why it needs a ruling: UNVERIFIED: no verified evidence
  - Human's note: Accepted as a statement of what the frozen snapshot shows (STALE flag noted). TEST RUN ruling by the test operator on synthetic data; not an investment decision

### Brief (stage 1)

Bear brief — SYNT (S-0004): The snapshot is severely thin and entirely STALE (674 days vs 456-day limit). All registered evidence — revenue, net income, total assets, shares outstanding — carries a STALE flag (C-X9). Eight critical metrics are absent: gross profit, operating income, operating cash flow, long-term debt, cash, total liabilities, equity, and capex (C-X10, C-X1 through C-X8). Without these, leverage, liquidity, margin structure, and cash conversion are unassessable. Only one annual period exists, making 'durable compounder' unverifiable (C-X11). Adding SYNT to a portfolio with 22.3% Tech and HHI 1,740 would deepen sector concentration (C-X12). Valuation is entirely unknown (C-X13).

### Challenge-round summary (stage 2)

Bear challenge round: challenged three bull FACTs. C-B8 (net margin ~12.5%): arithmetic is correct but without gross profit or operating income, margin quality is unverifiable — could reflect non-operating items. C-B9 (Q1 momentum): revenue figures confirmed but 'momentum' inferred from one quarter with no seasonal baseline is unsupported. C-B10 (asset growth): 2% Q-o-Q asset increase is confirmed by shared evidence; challenged positive framing since debt vs equity source is unknown. All three are needs_evidence or partly_agrees — no disputes, as no counter-evidence exists beyond the shared gaps.

### Final position (stage 3)

The snapshot is too thin and stale to evaluate the durable compounder thesis. Eight critical metrics are absent; all registered data is STALE. Human accepted C-X9 and C-X10. I concede C-X12 partially — the bull is correct that concentration impact magnitude depends on position size chosen, so the material-deepening claim cannot be established without a target weight. The directional Tech concentration risk remains. I could not establish leverage, cash conversion, margin quality, multi-year trend, or valuation from the available data.

Concessions:
- **C-X12**: Bull correctly rebuts that the HHI impact of adding SYNT is proportional to the square of the assigned weight, and target_weight_pct = 0.0 means magnitude is a decision variable. I concede the claim that adding SYNT materially deepens concentration — this cannot be established without a target weight. The directional point (any non-zero Tech allocation increases the 22.3% Tech share) still holds as the rationale.

Still holds:
- **C-X9**: Human accepted. All evidence is STALE (674 days vs 456-day heuristic limit). The underlying figures are VERIFIED against filings, but cannot be treated as a current picture. The bull's nuance — that STALE is a heuristic, not an accounting finding — is noted and fair.
- **C-X10**: Human accepted. Eight critical metrics absent from the snapshot. Leverage, liquidity, margin structure, and cash conversion are unassessable. This is the core obstacle to any durable compounder evaluation.
- **C-X11**: Only one annual period (FY2024) and one quarter (Q1 2025) of data are available, both STALE. Multi-year compounding cannot be evidenced or refuted from one year.
- **C-X13**: No stock-price data in snapshot. Valuation entirely unknown. No challenge was filed against this by the bull.

Could not establish:
- Whether the ~12.5% net margin (C-B8, human-accepted) derives from operations or non-operating items — no gross profit or operating income in snapshot
- Whether Q1 2025 revenue indicates genuine momentum (C-B9, human-accepted) — no seasonal baseline or prior quarters available
- Whether asset growth (C-B10, human-accepted) is debt- or equity-funded — no liabilities or equity data
- Any multi-year revenue or earnings growth trend — one annual period only
- Leverage and liquidity position — total liabilities, long-term debt, cash, and stockholders equity all absent
- Cash conversion quality — operating cash flow and capex both absent
- Valuation on any metric — no price data in snapshot

### Challenge round

| From | Targets | Stance | Restated claim | Response | Counter-evidence |
| --- | --- | --- | --- | --- | --- |
| bear | C-B8 | needs_evidence | Bull claims SYNT's FY2024 net income of $150,000 on $1,200,000 revenue implies a ~12.5% net profit margin, treating this as a positive quality signal. | The arithmetic is correct but the margin tells us nothing about quality without gross profit or operating income. Net income is a bottom-line figure that absorbs non-operating items, tax benefits, and one-time gains. With gross profit (C-X1) and operating income (C-X2) both absent from the snapshot, there is no evidence this margin reflects sustainable operating performance rather than a below-the-line event. The claim needs operating-line evidence before margin quality can be inferred. | none cited |
| bear | C-B9 | needs_evidence | Bull claims Q1 2025 revenue of $330,000 annualises to ~$1,320,000, above FY2024, suggesting 'modest forward momentum'. | The revenue figures are correctly registered, but inferring momentum from a single quarter against a single annual period requires seasonal context that does not exist in the snapshot. Q1 may be seasonally strong or weak for SYNT — there are no prior Q1 figures to compare. The annualisation assumes uniform quarterly distribution, which is unverified. 'Modest momentum' is an inference that needs at least two comparable periods; the evidence here supports only 'one quarter of revenue is available.' | none cited |
| bull | C-X9 | partly_agrees | All registered annual evidence (revenue, net income, total assets, shares) is flagged STALE — 674 days old vs a 456-day heuristic limit — making it an unreliable current picture of SYNT. | The STALE flag and its direction are correct; I registered the same flags. The important nuance is that STALE reflects an application heuristic, not an accounting or regulatory finding (the flag_detail itself says so). The underlying figures are VERIFIED against actual SEC filings and represent the most recent filed data available in the snapshot. The quarterly data (E-2, E-9) is also STALE (584 days vs 183-day limit), so no fresher counter-evidence exists. The limitation is recency, not accuracy at filing. The human should treat these as a historical baseline with the caveat that more recent filings may exist outside this frozen snapshot. | none cited |
| bear | C-B10 | partly_agrees | Bull claims total assets grew 2% Q-o-Q from $5,000,000 to $5,100,000, characterising this as 'modest balance sheet expansion'. | The asset figures are verified by the same evidence I registered (E-5). The 2% Q-o-Q movement is confirmed. However, asset growth with no equity (C-X7), no long-term debt (C-X4), and no cash (C-X5) data cannot be characterised as positive expansion — debt-funded asset growth would be a risk, not a strength. The claim acknowledges leverage cannot be assessed, but still uses positive framing. I partly agree on the numbers; I dispute the implied positive valence of unexplained asset growth. | none cited |
| bull | C-X12 | partly_agrees | Adding SYNT (Technology sector) to the portfolio would increase Technology exposure above its current 22.3%, deepening the second-largest sector concentration in an already concentrated portfolio (HHI 1,740, effective holdings 5.7). | The directional claim is correct — any non-zero SYNT allocation increases Tech weight, and I filed the same observation (C-B13). However, the magnitude of concentration impact is proportional to the square of the weight assigned. At small position weights the incremental HHI effect is minimal; the Bear's own falsifier acknowledges 'near 0% weight would be negligible.' The portfolio summary shows target_weight_pct = 0.0 (not currently held), so the actual impact depends entirely on the position size the investor chooses. The claim that adding SYNT 'deepens' concentration in a material sense cannot be established without a target weight — this is a decision-variable gap, not a data gap. | none cited |

## 6. Verified financial evidence

Each row was matched against the stored, hash-checked snapshot. Matching proves provenance, not that the source is correct or complete.

| ID | Metric | Value | Unit | Period | Fiscal period | Form | Filed | Accession | Source URL | Retrieved (UTC) | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E-1 | Revenue | 1,200,000 | USD | 2024-01-01 to 2024-12-31 | 2024 FY (as reported on the filing) | 10-K | 2025-02-14 | 0009999999-25-000001 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-2 | Revenue | 330,000 | USD | 2025-01-01 to 2025-03-31 | 2025 Q1 (as reported on the filing) | 10-Q | 2025-05-10 | 0009999999-25-000002 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-3 | Revenue | 1,200,000 | USD | 2024-01-01 to 2024-12-31 | 2024 FY (as reported on the filing) | 10-K | 2025-02-14 | 0009999999-25-000001 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-4 | Net income | 150,000 | USD | 2024-01-01 to 2024-12-31 | 2024 FY (as reported on the filing) | 10-K | 2025-02-14 | 0009999999-25-000001 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-5 | Total assets | 5,000,000 | USD | as of 2024-12-31 | 2024 FY (as reported on the filing) | 10-K | 2025-02-14 | 0009999999-25-000001 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-6 | Shares outstanding (cover page) | 10,000,000 | shares | as of 2025-02-01 | 2024 FY (as reported on the filing) | 10-K | 2025-02-14 | 0009999999-25-000001 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-7 | Net income | 150,000 | USD | 2024-01-01 to 2024-12-31 | 2024 FY (as reported on the filing) | 10-K | 2025-02-14 | 0009999999-25-000001 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-8 | Total assets | 5,000,000 | USD | as of 2024-12-31 | 2024 FY (as reported on the filing) | 10-K | 2025-02-14 | 0009999999-25-000001 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |
| E-9 | Total assets | 5,100,000 | USD | as of 2025-03-31 | 2025 Q1 (as reported on the filing) | 10-Q | 2025-05-10 | 0009999999-25-000002 | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | STALE |

## 7. Missing information

- **C-X1** (bear) gap: No annual Gross profit (USD) found in the snapshot; concepts tried: us-gaap:GrossProfit. Nothing was estimated.
- **C-X2** (bear) gap: No annual Operating income (USD) found in the snapshot; concepts tried: us-gaap:OperatingIncomeLoss. Nothing was estimated.
- **C-X3** (bear) gap: No annual Operating cash flow (USD) found in the snapshot; concepts tried: us-gaap:NetCashProvidedByUsedInOperatingActivities. Nothing was estimated.
- **C-X4** (bear) gap: No annual Long-term debt (USD) found in the snapshot; concepts tried: us-gaap:LongTermDebt, us-gaap:LongTermDebtNoncurrent. Nothing was estimated.
- **C-X5** (bear) gap: No annual Cash and cash equivalents (USD) found in the snapshot; concepts tried: us-gaap:CashAndCashEquivalentsAtCarryingValue. Nothing was estimated.
- **C-X6** (bear) gap: No annual Total liabilities (USD) found in the snapshot; concepts tried: us-gaap:Liabilities. Nothing was estimated.
- **C-X7** (bear) gap: No annual Stockholders' equity (USD) found in the snapshot; concepts tried: us-gaap:StockholdersEquity. Nothing was estimated.
- **C-X8** (bear) gap: No annual Capital expenditure (USD) found in the snapshot; concepts tried: us-gaap:PaymentsToAcquirePropertyPlantAndEquipment. Nothing was estimated.
- **C-B1** (bull) gap: No annual Gross profit (USD) found in the snapshot; concepts tried: us-gaap:GrossProfit. Nothing was estimated.
- **C-B2** (bull) gap: No annual Operating income (USD) found in the snapshot; concepts tried: us-gaap:OperatingIncomeLoss. Nothing was estimated.
- **C-B3** (bull) gap: No annual Operating cash flow (USD) found in the snapshot; concepts tried: us-gaap:NetCashProvidedByUsedInOperatingActivities. Nothing was estimated.
- **C-B4** (bull) gap: No annual Capital expenditure (USD) found in the snapshot; concepts tried: us-gaap:PaymentsToAcquirePropertyPlantAndEquipment. Nothing was estimated.
- **C-B5** (bull) gap: No annual Cash and cash equivalents (USD) found in the snapshot; concepts tried: us-gaap:CashAndCashEquivalentsAtCarryingValue. Nothing was estimated.
- **C-B6** (bull) gap: No annual Long-term debt (USD) found in the snapshot; concepts tried: us-gaap:LongTermDebt, us-gaap:LongTermDebtNoncurrent. Nothing was estimated.
- **C-B7** (bull) gap: No annual Stockholders' equity (USD) found in the snapshot; concepts tried: us-gaap:StockholdersEquity. Nothing was estimated.
- **C-X11** (bear) gap: No multi-year revenue or earnings trend is available. Only a single annual period (FY2024) of revenue and net income is in the snapshot, plus one quarter (Q1 2025) of revenue only. 'Durable compounder' implies sustained multi-year growth; this cannot be verified or falsified from one year of data.
- **C-B11** (bull) gap: Valuation and price-based upside cannot be assessed: no stock-price data exists in the snapshot.
- **C-B12** (bull) gap: No multi-year revenue, gross profit, operating income, operating cash flow, or capex data is available in the snapshot. The durability of the compounding thesis cannot be established from the evidence registered.
- **C-X13** (bear) gap: No stock-price data exists in the snapshot. Valuation metrics (P/E, EV/EBITDA, price-to-book, etc.) cannot be computed. Whether SYNT is cheap or expensive relative to peers or its own history is entirely unknown.
- **E-1** Revenue: flagged STALE. period ended 2024-12-31, 674 days before the session (heuristic limit 456 days for annual data) [application heuristics, not accounting or regulatory standards]
- **E-2** Revenue: flagged STALE. period ended 2025-03-31, 584 days before the session (heuristic limit 183 days for quarterly/sub-year data) [application heuristics, not accounting or regulatory standards]
- **E-3** Revenue: flagged STALE. period ended 2024-12-31, 674 days before the session (heuristic limit 456 days for annual data) [application heuristics, not accounting or regulatory standards]
- **E-4** Net income: flagged STALE. period ended 2024-12-31, 674 days before the session (heuristic limit 456 days for annual data) [application heuristics, not accounting or regulatory standards]
- **E-5** Total assets: flagged STALE. period ended 2024-12-31, 674 days before the session (heuristic limit 456 days for annual data) [application heuristics, not accounting or regulatory standards]
- **E-6** Shares outstanding (cover page): flagged STALE. period ended 2025-02-01, 642 days before the session (heuristic limit 456 days for annual data) [application heuristics, not accounting or regulatory standards]
- **E-7** Net income: flagged STALE. period ended 2024-12-31, 674 days before the session (heuristic limit 456 days for annual data) [application heuristics, not accounting or regulatory standards]
- **E-8** Total assets: flagged STALE. period ended 2024-12-31, 674 days before the session (heuristic limit 456 days for annual data) [application heuristics, not accounting or regulatory standards]
- **E-9** Total assets: flagged STALE. period ended 2025-03-31, 584 days before the session (heuristic limit 183 days for quarterly/sub-year data) [application heuristics, not accounting or regulatory standards]
- No stock-price or market-data source is part of this dataset. Valuation multiples, returns and any price-based analysis are therefore out of scope and are not estimated.

## 8. Limitations

- The data is a **frozen snapshot**, not live. Newer filings, restatements or corrections may exist.
- Verification confirms that a figure appears in the stored snapshot (provenance). It does not confirm that the source is correct, complete or current.
- Fiscal year/period labels are shown as reported on the filing that contained each value; a comparative figure inside a later filing carries that filing's labels.
- Portfolio weights use prices supplied by the user and are only as accurate as that file. Sector overlap depends on the user's own sector labels.
- Claims are made by AI research agents. Typing (FACT, ASSUMPTION, UNVERIFIED, GAP) and human rulings show how much weight each deserves; none is a recommendation.
- Freshness flags use thresholds of 456 days (annual data), 183 days (quarterly data) and 30 days (snapshot age). These are application heuristics, not accounting or regulatory standards.

## 9. Sources

| Source | URL | Retrieved (UTC) | SHA-256 (first 16) | Evidence |
| --- | --- | --- | --- | --- |
| SEC EDGAR (data.sec.gov) | https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json | 2026-11-05 03:32:30 | a81e5697a68e9d19 | E-1, E-2, E-3, E-4, E-5, E-6, E-7, E-8, E-9 |

Portfolio: user-supplied CSV; neither the file nor its fingerprint is included in this shareable version.

## 10. Human decision

_To be written by the human investor in their own words. This tool never fills this field._

> TEST RUN on synthetic data. The evidence is too thin and stale to call this a durable compounder, and it would add to my technology concentration, so I would not act on it. This note is the test operator's, not investment advice.
