# Investor Council — Technical Risks and Fallbacks

Status: **v0.2, synchronised with the implemented pre-kickoff foundation (Nov 3 2026)** · L = likelihood, I = impact (H/M/L). Tn = test in IMPLEMENTATION_PLAN §3. Tags as in ARCHITECTURE.md.

### v0.2 changes
Removed risks built on agent-triggered handoffs and on attachment privacy. Added: human-initiated stage overhead, privacy-by-design limits (same OS user), agent environment-variable limits, two-session concurrency, EDGAR fair access and field/tag variance, absence of price data, freshness heuristics, frozen-data labelling.

### Status of mitigations (Nov 3 2026, before kickoff)

Mitigations that exist in code are marked here; everything touching Switch is **pending** until the event.

| Risk | Status |
|---|---|
| S1 to S14 (Switch integration), A1, A3, A4, A6 to A8, A11 | **Pending**: need the Switch room and agents |
| A2 hallucinated figures | Library **implemented and tested** (`FACT` needs verified evidence; the verifier re-reads the hash-checked snapshot; the dossier body is rendered by Python). The agent-facing commands are pending |
| A5 advice language | Dossier disclaimer and keyword lint **implemented and tested** (`council human report`, `--strict`); agent output is not yet produced |
| A9 prompt injection | MVP surface is small and **implemented**: the CSV is parsed by code, there is no live web access, and filing text evidence is not stored yet |
| A10 agent bypasses the CLI | DB grants **implemented and tested** against a real server; the remaining limit is documented (P2) |
| D1 EDGAR fair access | Client **implemented** (User-Agent required with no default, default 5 requests/second and never above 10, retries); **never run live** |
| D2 field names unverified | Strict validation **implemented** (fails loudly); **T11 pending** |
| D3, D4, D5, D7, D8, D9, D12 | **Implemented and tested** (curated metric map with `GAP`; restatements as `CONFLICT`; no price data; frozen labelling; configurable heuristics stored per session; provenance-only verification stated in the dossier; hand-computed unit tests) |
| D6 sector classification | `sector_source` records `csv` or `unclassified` today; `edgar_sic` is reserved and unused |
| D10 SEC reuse terms, D11 selection bias | Pending (Day 2 and the challenge round) |
| P1, P3, P5, P6, P7, P8 | **Implemented and verified** (see section 4) |
| P2 | Grants **implemented and tested**; it remains defence in depth, not a hard boundary |
| P4 | Pending (Switch) |

---

## 1. Switch integration risks

| # | Risk | L/I | Evidence | Mitigation | Fallback |
|---|---|---|---|---|---|
| S1 | **Agents stop answering when Console is closed or the laptop sleeps** | H/H | Local agents answer only while Console runs [Docs: what-keeps-your-agent-running] | Keep Console open; prevent sleep (`caffeinate`); `!agents-status` before runs | Pre-recorded successful run; stretch: remote host [Docs: host-remotely] |
| S2 | **Two Claude Code sessions don't run concurrently, or usage limits bite** | M/M | Not documented — **T1** | Test two only; no third agent assumed | Sequential stage messages (`@bull`, wait, `@bear`) |
| S3 | **Agent→agent handoff doesn't work or isn't allowed** | — | "Follow-ups start only from a person's message, never from an agent's"; the docs don't say what an agent mention does [Docs: work-in-a-room] | **Not used.** Every stage starts with a human message | n/a (informational test T8) |
| S4 | **Reply loops between agents** | L/M | No documented agent-to-agent loop guard | Agents are instructed not to address each other; humans start stages; one round enforced by the CLI (`uq_ch`, `uq_sub`) | `!interrupt-all-agents` / `!reset-all-agents` [Docs: room-commands] |
| S5 | **Session lacks room history** (new session, `!reset`, compaction) | M/M | Event lines can say history was lost [Docs: connectors-and-runtime] | Stage messages carry `[session S-xxxx]`; agents re-hydrate via `council agent next` | Re-state context in the stage message |
| S6 | **CLI can't be invoked** (PATH/env: agents get only a fixed set of environment variables [Docs: onboard-your-agents]; Console reads PATH at startup [Docs: quickstart]) | M/H | **T4** | Absolute CLI path; restricted config file in the agent directory | Wrapper script in the agent directory |
| S7 | **Approval prompts stall a run** | M/M | By default only the owner answers; a stalled agent may have a request in a thread [Docs: work-in-a-room, quickstart] | Auto mode on; allowlist if T3 permits; watch the thread | Allow for this session; Bypass only for a synthetic demo (not recommended) |
| S8 | **`CLAUDE.md` not honoured** | L–M/M | **T2**; docs only say directory instructions become default behaviour [Docs: onboard-your-agents] | Test | Manual in Agent instructions |
| S9 | **Mattermost routing/threads with two agents; follow-ups ambiguous** | M/L | Follow-ups route to the agent that last spoke [Docs: work-in-a-room] — **T6** | Always tag both explicitly; keep `!follow-ups` off | Tag a single agent per message |
| S10 | **Posting large dossiers/attachments** | M/L | **T9** | Test | Human pastes text |
| S11 | **Template import doesn't reproduce setup** | M/L | **T10** [Docs: room-templates] | P2 | README manual steps (~10 min) |
| S12 | **Immutable names/directories; credentials regenerated on re-registration** | M/L | [Docs: agent-settings, onboard-your-agents] | Fix names/directories before creating agents | Delete, re-register, re-invite |
| S13 | **Switch version drift** (follow-ups need 0.31; docs moved domains) | L–M/M | | Record Console/server versions in README | Pin versions |
| S14 | **No scheduler in Switch** | certain/L | [Docs: work-in-a-room] | Human triggers every run (by design) | — |

## 2. Agent execution risks

| # | Risk | L/I | Mitigation | Fallback |
|---|---|---|---|---|
| A1 | **Agents ignore instructions** (start unasked, skip filing, answer early) | H/H | Short numbered Room Instructions; `council agent next` returns the only allowed actions for the current stage; CLI refuses out-of-stage commands | Human nudge in thread; `!reset @agent` |
| A2 | **Hallucinated numbers or sources** | H/H | `FACT` requires verified evidence; verifier re-reads the hashed snapshot; dossier body is rendered by Python | Auto-downgrade to `UNVERIFIED`; separate dossier section |
| A3 | **Bear manufactures negatives / Bull cheerleads** | M/M | "No material contrary evidence" is valid; typing rules; human rulings | Tighten prompts |
| A4 | **Bull and Bear converge or copy** (both see all room messages) | M/M | Parallel run, "file before reading", CLI blocks `brief show --other` until stage 2, different standing priors | Collapse criterion (AGENT_DESIGN §9); sequential fallback weakens independence — say so in the demo |
| A5 | **Advice language leaks** | M/H | Instructions; dossier template check; keyword lint on test runs; disclaimers | Edit/re-run before recording |
| A6 | **Human effort and pacing:** three human messages + rulings + terminal steps may make the demo slow or tedious | M/M | Message templates in AGENT_DESIGN §6; `status` shows exactly what is pending; keep claims per agent small (e.g., ≤8) | Trim waiting in the video; shorten the dataset |
| A7 | **Latency and usage cost** | H/M | Small data; cap Max turns; concise briefs | Pre-warm sessions; record and trim |
| A8 | **Non-deterministic runs** | M/M | Reproducibility claim limited to numbers and the verified evidence set; 3 clean runs before freeze | Pre-recorded run |
| A9 | **Prompt injection** (via filing text if P1 is used, or user thesis) | M/M | MVP uses numeric XBRL data and quote-verified excerpts only; no live web browsing; agents have no portfolio access; CSV is parsed by code | Disable P1 text excerpts |
| A10 | **Agent bypasses the CLI** (writes SQL, edits data files) | L/H | DB grants (agent user: no access to portfolio tables; no UPDATE/DELETE); snapshot directory read-only by convention; hash re-check in verifier | Treat as demo-only on synthetic data; documented limit |
| A11 | **Tool allowlist doesn't behave as expected** | M/M | **T3** [Docs: agent-settings] | Rely on grants and instructions |

## 3. Financial data availability and accuracy

| # | Risk | Mitigation | Fallback |
|---|---|---|---|
| D1 | **EDGAR fair access:** max 10 requests/second; requests should declare a User-Agent with identity/contact; no crawling [Docs: sec.gov fair-access policy] | Small company set; throttled client reading the User-Agent from `COUNCIL_SEC_USER_AGENT`; fetch once and cache under `data/edgar/` (git-ignored; add the chosen dataset with `git add -f`); a committed dataset means judges need not call EDGAR | Hand-curated subset |
| D2 | **XBRL field names and structure not verified** (the SEC page we fetched didn't document `end/val/accn/fy/fp/form/filed`) | **T11** on Day 2 against real responses; adjust `evidence_refs.fact_*` columns | Hand-curated subset |
| D3 | **Concept-tag variance:** companies use different tags for the same idea (e.g., revenue) | Curated metric map with candidate concepts per metric; absent → `GAP` | Choose companies with clean tags |
| D4 | **Restatements / duplicate facts** for the same period | Keep all, flag `CONFLICT`, show filing dates, human rules | Show the latest filed with the conflict noted |
| D5 | **No stock-price data** — EDGAR (as documented on the fetched page) covers filing metadata and financial statements | No price feed in MVP; prices only from the user's CSV; price-dependent claims are `GAP`; optional P2 snapshot after licence check | State the limitation in the dossier |
| D6 | **Sector classification** differs (user CSV label vs EDGAR SIC) | `sector_source` recorded (`csv` or `unclassified` today; `edgar_sic` reserved); overlap is by label and described as a heuristic; unknown sector → overlap not computed | User supplies `sector` in CSV |
| D7 | **Stale or outdated data** | Frozen snapshot labelled with retrieval date; "newer filings may exist"; STALE flag from configurable heuristics | — |
| D8 | **Freshness thresholds misread as standards** | Config file and every output label them *application heuristics, not accounting or regulatory standards*; stored per session | — |
| D9 | **Verification overclaim** | Verifier proves provenance (the figure/quote exists in the stored snapshot), not correctness or completeness; stated in the dossier | — |
| D10 | **Public-reuse of SEC snapshots** | Confirm reuse terms; cite source, URL and retrieval date | Provide the fetch command (`council human data fetch`) and a small committed subset |
| D11 | **Selection bias** (agents choose which evidence to cite) | Gap list, challenge round and human rulings; no completeness claim | — |
| D12 | **Calculation errors** | Unit tests with hand-computed values; weights sum to 100 ± 0.01; documented rounding | — |

## 4. Security and privacy

| # | Risk | Mitigation | Remaining limit |
|---|---|---|---|
| P1 | **Raw CSV exposure.** An attachment is readable by every room member and agent [Docs: work-in-a-room, working-safely-with-agents] | CSV never enters the room; processed locally in Python; only a sanitised summary is shared (implemented; a regression test derives every private value from the holdings and asserts none appears in the shareable summary or dossier) | The summary and thesis are still visible to room members and the model provider; demo with the synthetic sample |
| P2 | **Agents inherit the owner's OS permissions** [Docs: identity-and-access] and could read files the user can read | Keep the CSV and human DB credentials outside agent directories; agent DB user has no access to portfolio tables; consider a separate OS user; tool restrictions if T3 allows | **Not a hard boundary** — stated in README and ARCHITECTURE §8 |
| P3 | **Credentials on disk:** `.switch/agents/<name>.json` [Docs: connectors-and-runtime]; `.council.env` (restricted DB user); `.env` (human DB user) | `.gitignore`; secrets scan before publishing | — |
| P4 | **Room membership drift** (agents can invite agents [Docs: working-safely-with-agents]) | `!list-agents` before runs; default "Who can talk to your agent" policy | — |
| P5 | **MySQL exposure** | Port published on `127.0.0.1` only (verified with `docker port`); credentials in git-ignored files; `.env.example` committed with every secret blank | — |
| P6 | **No brokerage credentials / trades** | No code path; the CSV validator refuses files with credential-like or account-number columns (implemented); README states it | — |
| P7 | **Perceived investment advice** | Disclaimers in room instructions, dossier header and README; no recommendations; lint | — |
| P8 | **Unnecessary data ingestion** | Only `ticker, shares, price` (+ optional `sector`; the price date is given with `--price-as-of`); cost basis and any other column are ignored and not stored | — |

## 5. Fallback strategies

| Trigger | Fallback |
|---|---|
| T1 fails (no concurrency) | Sequential stage messages; note reduced independence in the demo |
| T2 fails | Tool manual in Agent instructions |
| T3 fails | DB grants + instructions; synthetic data only |
| T4 fails | Wrapper script in agent directory |
| T5 fails | Human pastes the other agent's brief |
| T9 fails | Human pastes dossier text |
| T10 fails | README manual setup |
| T11 fails / data awkward | Hand-curated subset with clear labels |
| Agent keeps ignoring instructions | Tighter CLI stage checks; shorter prompts; model/Effort in Advanced config |
| Agents unstable on the day | Pre-recorded run; sequential mode |
| Bull/Bear indistinguishable | Merge into one Researcher (last resort) |
| Time overrun | Freeze features at end of Day 3; drop P1/P2 |
| Total Switch failure | Show recorded run and the CLI pipeline, stating plainly that Switch was unavailable (scores poorly on "Switch is central") |

## 6. Process and legal risks
- **Authoring-machine use:** if the machine used for code is employer-managed, confirm you are permitted to use it for this project; keep employer code, data, credentials and IP out of the repository; use your own contact for the SEC User-Agent. If it is not permitted, author on the runtime machine only.
- **Hackathon rules:** build the Switch setup on or after Nov 4 12:01 AM IST; before then only docs and the non-Switch foundation exist (no room, agents or prompts); be able to explain everything submitted; confirm Track 02 and video requirements with organisers.
- **Licensing:** Switch is source-available (Apache 2.0 with Commons Clause per its repository page); we use it, we don't redistribute it.
- **Single point of failure:** the runtime machine. Push often; `council db init` is idempotent, so a fresh machine can be set up from the README.

## 7. Risks found while implementing

| # | Risk | Mitigation | Status |
|---|---|---|---|
| I1 | **Python version.** Only Python 3.13 has been run and tested; other versions (including the machine default) may behave differently or fail to build a virtual environment | `requires-python = ">=3.13,<3.14"`; README says `python3.13 -m venv` | Pinned |
| I2 | **Accounts use host `%`** (Docker port mapping hides the client address), so network reachability is controlled only by the published port | `docker-compose.yml` publishes `127.0.0.1:${COUNCIL_DB_PORT:-3307}` only; README tells the user to check `docker port` | Verified; do not change the mapping |
| I3 | **Fixed container name and a destructive reset.** One stack per machine; `docker compose down -v` deletes the database | Documented in README and DATABASE_SCHEMA §6 | Accepted |
| I4 | **Session codes use `MAX + 1`**: concurrent writers could collide (the unique constraint prevents duplicates but one writer would fail) | Single-user tool | Accepted |
| I5 | **Migrations are not atomic** (MySQL DDL auto-commits) | `CREATE TABLE IF NOT EXISTS`, so a failed run can be repeated; applied migrations are checksummed | Mitigated |
| I6 | **Secrets are plain text in `.env`** and readable by anything running as the same user | Passwords have no defaults; `.env` is git-ignored; the restricted account has the least privilege that works | Accepted, documented |
| I7 | **The dossier does not refuse unruled claims** (the design says it should) | It labels every unruled claim ("not yet ruled", "Awaiting a human ruling"); a hard gate belongs to the pending stage tooling | Open: a dossier can be rendered and shared with unruled claims |
| I8 | **A real EDGAR response may not match the strict parser** (for example an unexpected accession format) and be refused | Nothing is cached when validation fails; T11 will show real shapes; any change to strictness must be a reviewed code change | Open until T11 |
| I9 | **Strict CSV rules reject common broker exports** (currency symbols, thousands separators, extra encodings) | Errors name the line and the problem; the user fixes the file; nothing is repaired silently | By design |
| I10 | **A local MySQL on port 3306 would clash** | Default project port is 3307 | Mitigated |
| I11 | **Local-detail dossiers contain positions** and could be written to a committable path | `*.local.md` and every CSV except the sample are git-ignored; the README example uses a `.local.md` name | Mitigated |
