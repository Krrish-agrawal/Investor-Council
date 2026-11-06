# Test results (actual, Nov 5 2026)

Environment: macOS 26.2 arm64, Python 3.13.12, Docker 29.9.2, MySQL 8.0.46, Switch Console 0.40.1 (server switch-core 0.31.0),
Claude Code 2.1.150. Data: the labelled synthetic fixture and the sample portfolio only. **Live SEC was not run.**

**Who played the human in the live run (S-0004):** an AI assistant acting as "test operator", at the project owner's request for an
end-to-end verification (traced in the assistant session log: it ran `council human message/advance/rule/finalize` and pasted the stage
messages into Mattermost through browser automation). The rulings and the decision note are therefore **test-operator rulings on
synthetic data**, as the dossier says; nothing in the repository, database or shell history shows the owner making them. The database
records no actor for a ruling (only the ruling, its note and `ruled_at`). Session S-0003 was the headless `scripts/demo.sh --auto` run
with automated stand-in rulings. No run with a real person ruling has been recorded.

## Automated suite
`pytest`: **218 passed, 0 failed** on Nov 5 with MySQL running (185 need no database, 33 use real MySQL, incl. a scripted three-stage workflow).

Re-checked Nov 6: `pytest --collect-only` gives **218 tests** (185 not marked `db` + 33 marked `db`). With Docker stopped, `pytest` gives
186 passed and 32 skipped (one `db`-marked test needs no server); the 33 integration tests were **not re-run** on Nov 6 because that needs
the MySQL container. The earlier "217" in the README and design docs was the count when those documents were written; tests were added afterwards.

## Live Switch results (executed, observed)
| Test | Result | Evidence |
|---|---|---|
| T1 Environment | **PASS** | MySQL healthy; Switch Console, switch-core and Mattermost running; unrelated containers untouched |
| T2 Database security | **PASS** | agent account denied `SELECT` on holdings/portfolios/dossiers/`portfolio_id`, denied `INSERT` on sources and any `UPDATE`/`DELETE` (automated + manual) |
| T3 Portfolio ingestion | **PASS** | valid, invalid, duplicate and conflicting CSV cases (automated) |
| T4 Portfolio privacy | **PASS** | the whole room transcript (33 posts incl. threads, via Mattermost API) and the FINAL dossier contain none of the 7 private tickers or their shares/prices/values |
| T5 SEC integration | **BLOCKED** | needs the owner's own contact string for the SEC User-Agent; adapter validated on synthetic fixtures only |
| T6 Bull Researcher | **PASS** | live Claude Code agent in Switch: 13 typed claims, evidence verified, brief posted (session S-0004) |
| T7 Bear Researcher | **PASS** | independent run: 13 claims, 3 challenges; different method and findings from Bull |
| T8 Collaboration | **PASS** | both researched in parallel (T1 concurrency confirmed: both replied within one minute), read each other's filed brief, challenged (Bull 2, Bear 3) |
| T9 Human governance | **PASS** (test operator) | status lists flagged claims; `finalize` refused while a claim was `needs_evidence`; accept/reject resolved; then finalized |
| T10 Final dossier | **PASS** | FINAL banner, frozen-snapshot disclaimer, accession/filing date/source URL per evidence row, STALE and UNVERIFIED labelled, advice-language lint clean, no private holdings |
| T11 Full demonstration | **PASS (synthetic data, test operator as the human)** | S-0004 run in the `investor-council` room: stage messages, parallel research, challenge round, rulings, final positions, FINAL dossier |

Switch behaviour observed: a human message tagging an agent starts its session ("Starting a session to handle this"); two agents
tagged in one message run concurrently; the agent runs `./council-agent` with no approval stall under Auto mode (Bypass off);
the agent's working directory (symlinked to `agents/<role>-researcher`) is honoured; managed agents keep credentials on the server,
not in the repo folder. Whether `CLAUDE.md` is loaded separately is moot: the same text is in the Agent instructions field.

## Not achieved / blocked
* **Human steps driven from the room (Clerk): not built.** The idea was a non-LLM agent that runs `advance`, `rule` and `finalize` from the
  chat. It would be an agent registered outside Switch Console, which Switch's docs say uses a **registration key** that anyone signed in to
  the **Gateway** can create under **API Keys** ([People and agents](https://docs.switchagents.ai/switch-rooms/administer/people-and-agents#register-an-agent-that-runs-outside-switch-console)).
  What was found on Nov 6 (read-only; nothing created, no credentials viewed): Switch Console 0.40.1's **Admin** area has only *Connectors*,
  *Status* and *Connector apps*, with no API Keys page; its Status page shows the local server running (switch-core 0.31.0, "runs without
  Docker") with only the Mattermost component stopped. **The Gateway page was not located, so whether the registration-key feature is
  available on this local server is unverified.** This is a Console-UI observation, not evidence of a Switch platform limit. The other
  route considered, a Mattermost bot account, means creating a new credentialed identity; it was denied by the session's permission check
  and not worked around, and it has not been authorised since. Instead `council human message S --stage N` generates the exact message to
  paste; `advance`, `rule` and `finalize` stay terminal commands.
* Live SEC (T5): BLOCKED on a contact string. **Optional pending task for the owner:** set `COUNCIL_SEC_USER_AGENT` to your own name and contact (not an employer address), then run `council human data fetch --cik <CIK>`. Until then every SEC statement in the docs and blog applies to synthetic fixtures only.
* The user's headless fallback `scripts/demo.sh --auto` (no Switch) was not re-run in this pass.

## Defects found and fixed during this pass
* Console exited at launch because the shell exported `ELECTRON_RUN_AS_NODE` (fixed by `scripts/start_switch.sh`).
* The downloaded `.dmg` in `~/Downloads` was corrupt (no valid image); the official release was fetched and its SHA-256 verified.
* Mattermost's container stopped when Docker restarted and Console did not restart it (handled by `scripts/start_switch.sh`).
