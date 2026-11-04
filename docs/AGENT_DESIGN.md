# Investor Council — Agent Design

Status: **v0.2, synchronised with the implemented pre-kickoff foundation (Nov 3 2026).** Tags as in ARCHITECTURE.md. Nothing essential depends on an UNVERIFIED item.

**Implementation status:** this document is the approved design. The deterministic parts it relies on are built and tested: the typing rules and evidence verification (`council/evidence/`), the sanitised summary, the dossier renderer and the `council human` commands. The agents themselves, their instructions, the `council agent` commands and the stage controls are **pending** and are built after kickoff. Sections that describe pending pieces say so.

Agents: `bull-researcher`, `bear-researcher` — provider Claude Code, run location "This computer", same Switch owner (the human), Auto mode on, Bypass off [Docs: agent-settings]. Room aliases `@bull`, `@bear` via `!set-alias` [Docs: create-a-room]. Names are immutable once created [Docs: onboard-your-agents], so they are fixed here.

### v0.2 changes
Two LLM agents; portfolio analysis is Python; three human-initiated stages; human-run rulings and dossier; agents never receive holdings; agent/human CLI split; future Portfolio Analyst extension point.

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **Session** | One research run `S-0001` (a `research_sessions` row), one room thread. |
| **Stage** | 1 Initial analysis · 2 Challenge · 3 Final synthesis. Advanced only by the human. |
| **Claim** | One atomic statement typed `FACT` · `ASSUMPTION` · `UNVERIFIED` · `GAP`. |
| **Evidence ref** | Pointer to a frozen source: source name, URL, fiscal period, filing date, retrieval timestamp, hash, concept/value or quote, verification status. |
| **Flag** | `STALE` · `CONFLICT` — set by tools. `GAP` is a claim type. |
| **Ruling** | Human decision on a flagged claim: `accept` · `reject` · `needs_evidence`. |

Typing rules (implemented in `add_claim`, `council/evidence/service.py`; the pending `council agent claim add` will call it):
- `FACT` — needs at least one evidence reference. With none, the claim is rejected (the agent must file `ASSUMPTION` or `UNVERIFIED`). If evidence is cited but none of it is `VERIFIED`, the claim is stored as `UNVERIFIED` with `downgraded = true`; it is never kept as a `FACT`.
- `ASSUMPTION` — an inference or forecast; requires `basis` (claim/evidence codes) and a `falsifier`.
- `UNVERIFIED` — plausible but no verified evidence; reported separately, never under "agreed facts".
- `GAP` — a statement that needed data is absent (e.g., "No price data in the dataset, so no valuation claim is made"); never filled in.

## 2. Inputs every agent gets (and does not get)

From `council agent next S-0001 --as bull|bear` (pending) and the human's stage message:
- the **sanitised portfolio summary** (implemented: `target_ticker`, `target_held`, `target_weight_pct`, `target_sector`, `overlap_count`, `holdings_count`, the five largest sector weights, `top1_pct`/`top3_pct`/`top5_pct`, `hhi`, `effective_holdings`, `unclassified_pct`, `price_as_of`, `price_source`, `portfolio_partial`; percentages rounded to one decimal);
- ticker, thesis, session id, current stage, allowed commands;
- the index of frozen data for the target (and any peers in the dataset);
- from stage 2: the other agent's filed brief and claims; from stage 3: challenges received and the human's rulings.

Never: the CSV, share counts, position values, cost basis, other tickers (default), or any DB table of holdings.

## 3. Bull Researcher

**Job:** build the strongest *evidence-backed* positive case relevant to the thesis and exposure context — business strengths, growth drivers, financial trends visible in the statements.

**Stage 1 output (Brief):** claims + a ≤120-word room post listing claim IDs.
```json
{
  "session": "S-0001", "agent": "bull", "stage": 1,
  "summary": "<=120 words",
  "claims": [
    {"id": "C-B1", "type": "FACT", "text": "…", "evidence": ["E-3"], "relevance": "…"},
    {"id": "C-B2", "type": "ASSUMPTION", "text": "…", "basis": ["C-B1"], "falsifier": "…"},
    {"id": "C-B3", "type": "GAP", "text": "No price data in the dataset; no valuation claim is made."}
  ]
}
```
(Schema illustration only; no market figures.)

**Stage 2 output (Challenge response)** — see §5. **Stage 3 output (Final position)** — see §6.

**Must not:** state a figure without evidence; read the Bear's filed brief before stage 2; read or ask for holdings; give advice ("you should buy").

## 4. Bear Researcher

**Job:** independently investigate weaknesses and risks — financial deterioration visible in statements, restatements or conflicting values, missing evidence, concentration/overlap implications from the sanitised summary — and challenge the Bull.

**Honesty rule:** *must not manufacture negative arguments.* A risk claim follows the same typing rules as the Bull's claims. "No material contrary evidence found for <topic> in the available data" is a valid, first-class output and appears in the dossier. Value comes from challenge and gap-finding, not pessimism. Same contracts as the Bull (`"agent": "bear"`, claim ids `C-X*`).

## 5. Challenge round (stage 2)

Triggered by the human's message tagging both agents. Each agent:
1. `council agent brief show --other` (refused at stage 1).
2. For the opponent's **top 3 claims** (by `rank_in_brief`) files a response via `council agent challenge add`:
```json
{
  "session": "S-0001", "from": "bear", "target_claim": "C-B1", "stage": 2,
  "restated": "Fair one-sentence restatement of the claim",
  "stance": "disputes | partly_agrees | agrees | needs_evidence",
  "argument": "…",
  "counter_evidence": ["E-9"],
  "if_none": "state 'no counter-evidence found' explicitly"
}
```
Rules: restate before responding; `disputes` needs counter-evidence or must downgrade to `needs_evidence`; one round only — the CLI refuses a second stage-2 submission; agreement is allowed and is reported as "agreed".
3. `council agent submit --stage 2` and a short room post.

Independence limits are in ARCHITECTURE §5 (all room messages are visible to both agents; the CLI blocks reading the other's filed brief before stage 2).

## 6. Human stage messages (templates)

Always tag both agents; include the session id. Stage 1:
```
@bull @bear [session S-0001] Stage 1 — initial analysis.
Target: <TICKER>. My thesis/question: <text>.
Portfolio context (sanitised): <paste from `council human session new`>.
Run `council agent next S-0001 --as <you>`, research independently, file your claims
and submit stage 1 BEFORE reading the other's brief. Then post a <=120-word brief.
```
Stage 2:
```
@bull @bear [session S-0001] Stage 2 — challenge round.
Read the other's filed brief (`council agent brief show --other`) and respond to their top 3 claims:
restate, then disputes / partly agrees / agrees / needs evidence, citing evidence or saying none found. One round.
```
Stage 3 (after the human has recorded rulings):
```
@bull @bear [session S-0001] Stage 3 — final synthesis.
Read the challenges and my rulings (`council agent next`). File your final position:
what you concede, what you still hold and why, what you could not establish. Submit stage 3.
I will assemble the dossier.
```
Follow-up for `needs_evidence` (optional, one agent, once): `@bear [session S-0001] Please look for evidence on C-B4 and file it, or log a gap.`

## 7. Final position (stage 3) and dossier

```json
{
  "session": "S-0001", "agent": "bull", "stage": 3,
  "concessions": [{"claim": "C-B2", "reason": "…"}],
  "still_holds": [{"claim": "C-B1", "reason": "…"}],
  "could_not_establish": ["…"]
}
```
The **dossier** is rendered by Python from the ledger (`council human report`, implemented). Its ten sections: portfolio overview, sector allocation, concentration analysis, positive arguments (Bull), negative arguments (Bear), verified financial evidence, missing information, limitations, sources, and the human's own decision field, under a disclaimer and a `FROZEN SNAPSHOT` banner. Arguments are grouped by claim type (`FACT`, `ASSUMPTION` with basis and falsifier, `UNVERIFIED`), each claim shows its evidence references and the human's ruling, rejected claims move to their own subsection, a challenge table appears when challenges exist, and `GAP` claims, failed or flagged evidence, `needs_evidence` rulings and unruled items are listed under missing information. The freshness thresholds in force are stated and labelled as heuristics. There is no free-form LLM synthesis in the body. The renderer is a pure function (the CLI supplies the timestamp), so the same data always renders the same text. Agent-written content arrives only as claims, challenges and final positions once the agents exist; until then those sections state that nothing was filed.

*Open decision for review:* Python-only dossier (recommended: nothing to hallucinate) versus a short agent-written narrative section clearly labelled as such.

## 8. Unsupported claims and missing data

| Situation | Handling |
|---|---|
| Claim without evidence | A `FACT` with no evidence is rejected; the agent files `ASSUMPTION` (basis + falsifier) or `UNVERIFIED`. (Implemented.) |
| Figure not found, or not matching, in the stored snapshot | The evidence row is stored as `FAILED` (never silently corrected) and a `FACT` citing only failed evidence is stored as `UNVERIFIED` (`downgraded = true`). Implemented for numeric facts. A quote-verification utility exists, but storing filing-text evidence is pending (P1). |
| Source older than configured heuristic | Evidence flagged `STALE` when the fact's period, or the snapshot itself, exceeds the thresholds in `config/freshness.yaml` (copied into the session; labelled application heuristics). Implemented. |
| Metric absent from the dataset (different XBRL tag, not reported) | `record_metric_evidence` stores a `GAP` claim naming the concepts tried; nothing is estimated. Implemented. |
| Restated or differing values for the same concept and period | The latest-filed value is cited; all values are kept with their filing dates; the evidence is flagged `CONFLICT` (which takes precedence over `STALE` in the single flag). Implemented. It is listed under missing information for the human's ruling. |
| Needs stock-price data | `GAP`: the dataset has none. |
| Human asks for a recommendation | Agents reply with considerations and open questions only. |

## 9. Do the agents need to be separate? And the future Analyst

| Question | Answer |
|---|---|
| Bull vs Bear | **Separate only because the protocol makes independence real:** independent first pass (parallel sessions with separate contexts [Docs: connectors-and-runtime]; CLI blocks reading the other's brief until stage 2), different standing priors, and a bounded structured challenge. A single LLM arguing both sides anchors on its first answer. **Collapse criterion (Day 3):** if the two stage-1 briefs are near-identical, or the human cannot tell the sides apart, tighten instructions; if that fails, merge into one "Researcher" that must produce both cases — less compelling but honest. |
| Portfolio analysis | **Not an LLM agent.** Deterministic Python: weights, sector exposure, concentration and overlap need exactness and privacy, not reasoning. |
| Evidence verification | Deterministic tool (snapshot match). |
| Future Portfolio Analyst | **Extension point, not built.** If added, it would (a) get only the sanitised summary through the same `council agent` interface, or (b) live in a *separate private room* that Bull and Bear are not members of, because room members can read everything in a room [Docs: working-safely-with-agents]. The CLI split and DB grants already support either. |

What separation costs: two Claude sessions' usage, session-start latency, and the need for the human to start each stage — accepted deliberately.

## 10. Agent instructions (v2 drafts; final text written on Day 3 after tests)

### 10.1 Room Instructions
```
PURPOSE: Investor Council is a research room, not an adviser. A human investor examines one
stock against their own portfolio with two research agents, @bull and @bear. Never recommend
buying, selling or holding. Never ask for brokerage credentials. Never place trades.

HOW WE WORK: The human starts each stage by posting a message that tags both agents. Do not
start work, and do not address the other agent to trigger it, unless the human has asked.
Stage 1: research independently and submit before reading the other's brief.
Stage 2: read the other's filed brief and respond to their top 3 claims, once.
Stage 3: file your final position with concessions and what you could not establish.
Use `council agent` for every number and every claim. Begin handoff-style posts with [session S-xxxx].

DATA RULES: Data is a FROZEN SNAPSHOT of SEC EDGAR financial statements, not live, and may be
out of date. There is no stock-price data. Every figure must come from a registered evidence
ref; otherwise label it ASSUMPTION or UNVERIFIED, or log a GAP. Never fill gaps. You never have
the user's portfolio; use only the sanitised summary you are given.

CONDUCT: Say what you are doing in the thread. Report tool errors plainly instead of producing
plausible output. Do not manufacture arguments: "no material contrary evidence found" is acceptable.
```
(Follows the docs' guidance: purpose, conventions, what to read first, what not to do, report failures [Docs: shared-context].)

### 10.2 `bull-researcher` — Agent instructions
```
You are the Bull Researcher. Build the strongest evidence-backed positive case relevant to the
human's thesis. Only the human starts your work. Use `council agent` (absolute path in your
CLAUDE.md or config) to read frozen data, register evidence and file typed claims. File and submit
stage 1 before reading the Bear's brief. In stage 2 restate the Bear's claim fairly, then respond
with evidence or say none was found. In stage 3 state concessions plainly. You have no access to the
user's portfolio. You do not give advice.
```
### 10.3 `bear-researcher` — Agent instructions
```
You are the Bear Researcher. Independently investigate weaknesses, risks, restatements, missing
evidence and contradictions relevant to the human's thesis. Do not manufacture negatives: if the
data does not support a concern, say "no material contrary evidence found". Same typing and stage
rules as the Bull. You have no access to the user's portfolio. You do not give advice.
```
Placement: Agent instructions field is sent every session [Docs: agent-settings]. The tool manual goes in each agent directory's `CLAUDE.md`; whether Console-launched Claude Code reads it is **[UNVERIFIED — T2]** (docs say only that standing instructions in the directory become default behaviour [Docs: onboard-your-agents]). Fallback: include the manual in Agent instructions.

## 11. CLI surface

### Implemented today (`council db …` and `council human …`, run in a terminal)

| Command | Purpose |
|---|---|
| `council db init` | Create the database, apply migrations, create or refresh the human account and (if a password is set) the restricted agent account. Idempotent |
| `council db status` | Server version, applied migrations, row counts |
| `council human ingest --file F [--name N] [--price-as-of D] [--sample] [--allow-partial]` | Validate the CSV locally, store it, report invalid rows by line number |
| `council human summary [--portfolio-id N] [--json]` / `summary --shared --target T [--target-sector S]` | Local position detail, or the sanitised summary that is safe to paste into the room |
| `council human session new --ticker T --thesis … [--target-sector S] [--cik C] [--session-date D]` / `session show [CODE]` | Open a session and print the sanitised summary; show a session |
| `council human rule SESSION CLAIM accept\|reject\|needs_evidence [--note …]` | Record a ruling |
| `council human report [--session S] [--portfolio-id N] [--local-detail] [--note …] [--save] [--strict] [-o FILE]` | Render the dossier (sanitised by default), lint advice language, optionally store it as a `DRAFT` row |
| `council human data fetch --cik N [--refresh]` / `data inspect --cik N` / `data manifest` | Fetch and cache EDGAR documents (declared User-Agent, rate-limited); describe a cached company offline; write `MANIFEST.json` |

Library functions with no CLI yet (the agent commands will wrap them): `record_fact_evidence`,
`record_metric_evidence`, `add_claim` and `rule_claim` in `council/evidence/service.py`.

### Pending: `council agent …` (design sketch; exact flags fixed after kickoff)

Restricted DB account, config from a git-ignored file in the agent directory.

| Command | Purpose / check |
|---|---|
| `next S --as ROLE` | Stage, task, sanitised summary, data index, rulings (stage 3) |
| `data list TICKER` / `data show SOURCE_KEY [--concept C]` | Read frozen sources with provenance |
| `evidence add S --as ROLE --source KEY (--concept C --period P \| --quote T)` | Creates and auto-verifies evidence; applies STALE/CONFLICT flags (wraps `record_fact_evidence`) |
| `claim add S --as ROLE --type T --text … [--evidence …] [--basis …] [--falsifier …]` | Typing rules; only at the current stage (wraps `add_claim`) |
| `submit S --as ROLE --stage N` | Records submission (once per stage) |
| `brief show S --other --as ROLE` | Refused when stage < 2 |
| `challenge add S --as ROLE --file response.json` | Only at stage 2; max top-3 targets; schema-validated |
| `final add S --as ROLE --file position.json` | Only at stage 3 |

### Pending: stage control for the human

| Command | Purpose |
|---|---|
| `council human status S [--disputes]` | Submissions per agent and stage; flagged items needing rulings |
| `council human advance S --to N [--force]` | Move the stage; normally needs both agents' submissions |
| `council human finalize S --note …` | Store the human's note and mark the dossier `FINAL` |
