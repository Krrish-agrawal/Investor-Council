# Investor Council — Product Requirements Document

Status: **v0.2, synchronised with the implemented pre-kickoff foundation (Nov 3 2026)** · Hackathon: WeMakeDevs *Flip the Switch* (Nov 4–7 2026; submissions close 11:59 PM IST Nov 7) · **Track 02 — Best Personal or Creative Workflow** · **Solo build**

> Investor Council is a **research and decision-support** workspace. It is not a financial adviser, produces no buy/sell/hold recommendation, never touches a brokerage account and never executes trades.

Conventions: **[Docs: page]** = verified against docs.switchagents.ai (page name given). **[UNVERIFIED — Tn]** = not documented; proven or replaced by a fallback in Day-1/Day-2 test *Tn* (see IMPLEMENTATION_PLAN §3). **No essential feature depends on an UNVERIFIED item.**

### v0.2 revision notes (what changed from v0.1)
- Two LLM agents (Bull, Bear), not three. Portfolio analysis is deterministic Python run locally.
- The human drives three explicit stages; no agent→agent handoff is assumed.
- The raw portfolio CSV never enters the Switch room; only a sanitised summary does.
- Market data = frozen SEC EDGAR financial-statement snapshots. No stock-price data. Freshness thresholds are configurable heuristics.

### Implementation status (Nov 3 2026, before kickoff)

The deterministic foundation is built and tested (197 tests, MySQL 8 and Python 3.13). The Switch workflow is
deliberately not started: the hackathon requires it to be built during the event.

| MVP feature (section 4) | Status |
|---|---|
| 2. Local portfolio processing, 3. sanitised summary | **Implemented** (`council human ingest`, `summary`, `session new`) |
| 4. Frozen SEC EDGAR data | **Adapter implemented**, tested on synthetic fixtures only; no live SEC run yet (test T11) and no dataset chosen yet (Day 2) |
| 5. Evidence ledger and typing, 6. data-quality flags | **Implemented** as a tested library (`council/evidence/`); human rulings via `council human rule` |
| 8. Dossier | **Implemented**: deterministic renderer, `council human report`; agent-written sections arrive after kickoff |
| 9. MySQL persistence | **Implemented** (10 tables, migrations, human and agent accounts) |
| 10. Reproducible setup | **Implemented**: README, Docker Compose, `council db init` |
| 1. Switch room and two agents; 7. stage flag and `council agent` commands; 11. sequential-fallback demo | **Pending**: built after kickoff, after the Day-1 tests (T1 to T11) |

Known behaviour differences from the plan below: `council human report` labels unruled claims instead of
refusing to render; `advance`, `status` and `finalize` do not exist yet.

---

## 1. Problem statement

A self-directed retail investor researching one stock typically faces three problems:
1. **Research ignores the investor's own portfolio.** The useful question is "what would this position do to *my* concentration and overlap?", not only "is this a good company?".
2. **Single-LLM research is one-sided and hard to audit.** One chat answer mixes facts, guesses and persuasion, rarely shows sources and tends to agree with the user.
3. **The investor is passive.** Tools hand over a verdict; they don't let the human interrogate disagreements and decide what counts.

Investor Council puts two research agents and the human in one shared Switch room. The agents investigate independently, then challenge each other in the open. The human adjudicates the disputes and the final dossier records *the human's* conclusions plus every data gap — never a recommendation.

## 2. Target user and track fit

**Primary:** the self-directed investor with a concentrated personal portfolio (5–30 holdings), who can export a CSV from a broker or spreadsheet and wants to stress-test a thesis before acting. Comfortable with chat; not necessarily technical.

**Track 02 fit:** a personal workflow ("my portfolio, my thesis, my decision") where a person and agents complete a real task together in a shared room. Hackathon requirement: at least one agent and one person working in a chat connected through Switch — satisfied by one human and two agents.

**Secondary audience:** hackathon judges, who must be able to clone the repo and reproduce the run with the bundled sample portfolio and frozen data.

## 3. User journey (MVP)

The human controls every stage. Stage messages are sent by the human; Switch documents that "follow-ups start only from a person's message, never from an agent's" [Docs: work-in-a-room], so the design never relies on an agent triggering another agent.

| Step | Actor | Where | What happens |
|---|---|---|---|
| **0. Prepare (local, outside the room)** | Human | Terminal | `council human ingest --file portfolio.csv` validates the CSV and computes weights, sector exposure, concentration and overlap **in Python**; rows go to MySQL. `council human session new --ticker … --thesis …` opens session `S-0001` and prints a **sanitised summary**. The raw CSV never goes to the room. |
| **1. Initial analysis** | Human → Bull + Bear | Room (one thread) | Human posts the sanitised summary, the ticker and the thesis, tagging `@bull @bear`. Each agent independently builds a case from frozen EDGAR data, files typed claims with evidence, and posts a short brief. They are told to file before reading the other's. |
| **2. Challenge round** | Human → Bull + Bear | Room | Human advances the stage (`council human advance`, pending) and asks both to challenge the other's findings. Each reads the other's filed brief (via CLI), then responds claim-by-claim: disputes / partly agrees / agrees / needs evidence, citing claim IDs and evidence. |
| **Human rulings** | Human | Room + Terminal | Human reviews disputed, unsupported, conflicting and stale items and records rulings: accept · reject · needs more evidence (`council human rule …`). *Needs evidence* may trigger one targeted follow-up message to one agent. |
| **3. Final synthesis** | Human → Bull + Bear, then Python | Room + Terminal | Human asks both to file a final position that includes concessions and what they could not establish. Human then runs `council human report`, which renders a **structured research dossier** deterministically from the database and posts it back to the room. Human adds their own decision note (`--note`; a `finalize` command is pending). |

Target duration for one full run on the sample data: **< 20 minutes** including human reading time (to be measured; it is a target, not a result).

## 4. MVP features

**P0**
1. One Switch room (bundled Mattermost), two Claude Code agents (`bull-researcher`, `bear-researcher`), one human; one thread per research session.
2. **Local portfolio processing in Python:** CSV schema validation with clear errors; position weights; sector exposure; top-N concentration; same-sector overlap with the target. All numbers are computed in code, never by an LLM.
3. **Sanitised summary** for the room (rounded target weight, top sector weights, top-N concentration, holding count, overlap *count*). No shares, values, cost basis or other tickers by default.
4. **Frozen SEC EDGAR dataset** for 3–5 US-listed companies: financial-statement data with source URL, fiscal period, period dates, **filing date**, form, accession number, retrieval timestamp and content hash. Labelled `FROZEN_SNAPSHOT` — never "live". The local cache is git-ignored; a chosen dataset is added deliberately with `git add -f`.
5. **Evidence ledger:** every claim typed `FACT | ASSUMPTION | UNVERIFIED | GAP`. A `FACT` requires ≥1 evidence reference that passed deterministic verification against the stored snapshot.
6. **Data-quality flags:** `STALE` (against configurable heuristics), `CONFLICT` (e.g., restated values for the same period, both shown with filing dates), `GAP` (missing data is recorded, never filled).
7. **Three human-controlled stages**; agent CLI commands check the session's `stage` so the challenge round cannot run before stage-1 submissions exist. This is a flag, not a workflow engine. (The `stage` column and the per-stage uniqueness constraints exist; the agent CLI and `advance` are pending.)
8. **Dossier** rendered by a deterministic template: sanitised exposure, agreed facts, contested claims with human rulings, concessions, data gaps and freshness flags, open questions, and the human's own decision field (never auto-filled).
9. **MySQL persistence** via a small Python CLI (`council`) with two command groups (human / agent).
10. **Reproducible setup:** README, `docker compose` for MySQL, `council db init` and Python 3.13; the frozen dataset is added deliberately once chosen. There is no separate bootstrap script.
11. **Sequential fallback** documented and demonstrated (human messages `@bull`, waits, then `@bear`).

**P1:** filing-text excerpts (e.g., risk-factor passages) as quote-verified `FILING_TEXT` evidence; second sample company; CLI posts the sanitised summary into the room via the Mattermost API; automated smoke test of the CLI flow.
**P2:** frozen price snapshot (after licence check); room template import; PDF export of the dossier.

## 5. Out of scope

| Removed | Reason |
|---|---|
| React dashboard, any custom UI | Chat is the product. |
| FastAPI / any backend service; elaborate workflow orchestrator | Switch is the collaboration and shared-context layer; the human controls stages; Python is a small CLI. |
| A third LLM agent (Portfolio Analyst) | Deterministic Python does the portfolio work. Kept as a documented future extension (AGENT_DESIGN §9). |
| Attaching the portfolio CSV (or any holdings detail) in the room | Every agent and member of a room can read its conversation [Docs: working-safely-with-agents]; the CSV stays local. |
| **Stock-price / market data** and anything derived from it (valuation multiples, returns) | EDGAR provides financial-statement data, not prices. Prices come only from the user's CSV; claims needing price data are recorded as `GAP`. |
| Live data, real-time anything | Frozen snapshots for reproducibility. |
| Buy/sell/hold, price targets, scores, "conviction" | Product principle. |
| Brokerage login/OAuth, trade execution, tax lots, derivatives, crypto, non-US markets | Safety and data availability. |
| Authentication, multi-user, hosting, remote hosts, other chat platforms | One local operator. |

## 6. Success criteria

**Functional (on a fresh clone with the sample portfolio):**
- F1. The full journey (steps 0–3) completes with only the human actions described — no developer intervention.
- F2. Every claim in the dossier is typed; every `FACT` links to ≥1 verified evidence item with source name, URL, fiscal period, filing date and retrieval timestamp.
- F3. A human ruling visibly changes the dossier (e.g., a rejected claim moves out of "agreed facts").
- F4. The agent CLI refuses `challenge` while stage = 1 and refuses reading the other agent's brief before stage 2 (blind first pass, tool-enforced for CLI data; room visibility is a stated limitation).
- F5. Demonstrate each flag on frozen data: `STALE`, `CONFLICT` and `GAP`.
- F6. Zero buy/sell/hold language in dossier output (template check + keyword lint on test runs).
- F7. Sequential fallback produces an equivalent dossier.

**Data and privacy:**
- D1. Frozen data is labelled `FROZEN_SNAPSHOT` with retrieval timestamp everywhere it is shown; the dossier states that newer filings may exist.
- D2. Freshness thresholds are configurable (`config/freshness.yaml`) and displayed as *application heuristics, not accounting or regulatory standards*.
- D3. No price-derived figure is presented as market data; missing data is never invented.
- P1. The raw CSV, share counts, cost basis and non-target tickers never appear in the room, in agent-visible database tables or in agent-readable files (design + DB grants + convention; see ARCHITECTURE §8 for honest limits).

**Quality:** portfolio math unit-tested against hand-computed values (weights sum to 100 ± 0.01); re-running on identical inputs reproduces the same numbers and the same verified evidence set (LLM prose may differ).

**Hackathon:**
- H1. A judge can reproduce from the README in ≤ 30 minutes given Python 3.13, Docker, Switch Console and a signed-in Claude Code.
- H2. The demo video shows: local ingest and sanitised summary, parallel (or sequential) agent work in the room, the challenge round, a human ruling, and the dossier.
- H3. The README states what Switch provides (shared room context, room/agent instructions, human-in-the-loop, addressable agents, audit trail) and what would have to be built without it.

## 7. Product principles
1. **Research, not advice.** Considerations and open questions only.
2. **Show your work.** Source, URL, period, filing date and retrieval time — or it isn't a fact.
3. **Say "I don't know".** Missing data is a first-class result.
4. **Disagreement is a feature.** The Bear must not manufacture negatives; "no material contrary evidence found" is valid.
5. **The human decides.** Humans start every stage and write the decision note.
6. **Frozen means frozen.** Never label snapshot data as live.
