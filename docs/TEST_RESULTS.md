# Test results (what has and has not been verified)

Last updated: Nov 4 2026. Be careful to read the "Not yet verified" section: scripted tests are not live Switch results.

## Verified

| What | How | Result |
|---|---|---|
| Foundation: schema, ingestion, math, sanitised summary, EDGAR adapter (synthetic), evidence, dossier | `pytest` (185 tests without a database) | pass |
| Agent tooling against a real MySQL 8 server **as the restricted account** | `tests/test_agent_flow.py` and `tests/test_db_integration.py` (32 DB tests) | pass |
| Full three-stage workflow: two scripted researchers and a scripted human through the real `council-agent` and `council human` CLIs: evidence verified, `CONFLICT` detected, challenges, final positions, rulings, `finalize`, FINAL dossier | `test_full_three_stage_workflow_with_the_ruling_gate` | pass |
| Stage validation: out-of-stage commands refused; blind first pass (other's brief unreadable at stage 1 and until you have filed); work frozen after `submit`; max three challenges; bare dispute downgraded; cannot challenge own claims or a `GAP`; cannot cite the other's evidence; closed session refuses work | `test_stage_validation`, `test_researchers_cannot_cite_each_others_evidence`, workflow test | pass |
| Ruling gate: flagged claims never appear as findings; DRAFT banner counts them; `final=True` and `council human finalize` refuse while any is unresolved; `needs_evidence` is not a resolution | `tests/test_report.py`, workflow test | pass |
| Agent cannot bypass database permissions: only the `agent` account can be requested in agent mode; the human's `.env` is never loaded; the agent CLI imports no portfolio, report or stage code (AST check); direct SQL on `holdings`, `portfolios`, `dossiers`, `research_sessions.portfolio_id` is denied; `INSERT` on `sources` is denied | `test_agent_cli_never_loads_the_humans_env...`, `test_agent_package_cannot_reach...`, `test_database_refuses...`, `test_unregistered_snapshot...` | pass |
| `./council-agent` wrapper run from a generated agent directory against the real project database | manual run on session S-0001 | `whoami` and `next` work; the view contains no private value; direct SQL on private tables denied |
| `council human agents init` writes only the restricted account and never the human's secrets | `tests/test_cli_data.py` | pass |

## Not yet verified (pending)

| Item | Why | Fallback if it fails |
|---|---|---|
| **Phase 1: Switch Console connected; room `#investor-council`; a human message from Mattermost gets a reply from a live Claude Code agent; the agent runs `./council-agent`** | Switch Console is **not installed** on the development machine; installing it ties the agents to that machine and its Claude account, which is the owner's decision (see `switch/SETUP.md`) | none: this is the core of the project |
| T1: two sessions run concurrently from one message | needs Switch | sequential stage messages |
| T2: `CLAUDE.md` is loaded from the agent directory | needs Switch | the same text is pasted into the Agent instructions field |
| T3: Auto mode lets the agent run `./council-agent` without approval stalls; tool allowlist | needs Switch | answer approvals; rely on grants |
| T4: the agent can run the wrapper by relative path from its directory | needs Switch (the wrapper is verified from a normal shell) | absolute path |
| T5, T6, T9, T10 | need Switch | see docs/IMPLEMENTATION_PLAN.md |
| T11: real SEC EDGAR responses match the parser; a frozen dataset exists | needs a contact string for the SEC User-Agent that the owner provides | hand-curated subset |
| Live agent compliance with the protocol (starting only when asked, filing before reading, one challenge round) | needs Switch | tool-side gates already refuse violations |
