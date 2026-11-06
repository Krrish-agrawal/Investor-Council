# Investor Council

Deterministic tooling for AI-assisted investment research: local portfolio analysis, frozen SEC EDGAR
financial-statement data, an evidence ledger with verification, and a Markdown research dossier.

> **Research and decision support only. Not financial advice.** Nothing here recommends buying,
> selling or holding anything, touches a brokerage account, or executes trades.

Design documents live in [docs/](docs/) (v0.2 is the source of truth; see [Documentation](#documentation) for how they relate to the code).

## Run the Switch demo

```bash
scripts/start.sh && scripts/start_switch.sh     # database + agent folders; Switch Console and Mattermost
```
Then follow [switch/DEMO.md](switch/DEMO.md): you paste three generated messages into the `investor-council` room
(`council human message S-000N --stage 1|2|3 --copy`), advance stages, rule on flagged claims and finalize. Actual results,
including what is blocked, are in [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md). Screenshots: `docs/screenshots/`.

## Status (updated Nov 6 2026)

**Implemented and tested:** everything in the left column below, covered by the automated suite (218 tests, see [Tests](#tests)).
**Verified live once:** on Nov 5 a full three-stage session (**S-0004**) ran in a Switch room with two live Claude Code agents,
using the synthetic company and the sample portfolio only.

> **Who played the human in S-0004:** an AI assistant, acting as "test operator" because the owner asked it to carry out the
> end-to-end verification. It pasted the stage messages into Mattermost, ran `advance`, `rule` and `finalize`, and wrote the
> rulings and the decision note. The dossier labels them *TEST RUN ruling by the test operator*. They are **not** a real
> investor's decisions, and no run with a person making the rulings is recorded here. The earlier session S-0003 was the
> headless `scripts/demo.sh --auto` fallback with automated stand-in rulings.

| Built and tested | Verified live (S-0004, synthetic data) |
|---|---|
| MySQL 8 schema, migrations, human and restricted agent accounts | Switch Console + Mattermost room `investor-council` with agents `bull-researcher` and `bear-researcher` (Claude Code, Auto mode on, Bypass off) |
| Local portfolio CSV ingestion, deterministic math, sanitised summary | One human message tagging both agents starts both sessions; they ran concurrently |
| SEC EDGAR adapter (synthetic fixtures only) | 13 typed claims from each agent; Stage-2 challenges (Bull 2, Bear 3); final positions |
| Evidence verification, claim typing, `GAP`, `STALE`, `CONFLICT` | `finalize` refused while a claim was `needs_evidence`, then succeeded after `accept`/`reject` |
| **`council-agent` commands** (`next`, `evidence`, `claim`, `submit`, `brief show --other`, `challenge add`, `final`, `whoami`) with stage validation, as the restricted account | Room transcript (33 posts) and FINAL dossier checked: none of the 7 private tickers or their shares, prices or values appear |
| **Stage control** (`council human status`, `advance`, `finalize`) and the **ruling gate** | |
| Dossier renderer (briefs, final positions, UNRESOLVED section, DRAFT/FINAL) and advice-language lint | |
| Agent directory generator (`council human agents init`) and the instruction texts in `switch/` | |

**Not done, and not claimed:**

* **Orchestration is manual.** The human generates each stage message (`council human message`), posts it in the room, and runs
  `advance`, `rule` and `finalize` in a terminal. Agents act only when a person addresses them; there is no agent-to-agent trigger
  and no automatic stage control. A room-side "Clerk" agent that would run those commands from the chat was **not built** (see
  [Known limitations](#known-limitations)).
* **Live SEC EDGAR was not run** (needs your own contact string for the SEC User-Agent). Everything above used the synthetic fixture.
* Filing-text evidence is not stored.

Verified on macOS with Python 3.13.12, Docker 29.9 and MySQL 8.0.46 (the `mysql:8.0` image); Switch Console 0.40.1 with switch-core 0.31.0.

## Requirements

* **Python 3.13.** `pyproject.toml` requires `>=3.13,<3.14`; no other version has been run or tested.
* Docker with Compose v2, and an internet connection for the first image pull.

## Setup

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env            # then fill in the passwords (see below)
docker compose up -d            # MySQL 8, published on 127.0.0.1:3307 only
council db init                 # creates the database, applies migrations, creates the accounts
```

Passwords have no defaults. Generate them yourself, e.g. `openssl rand -base64 24 | tr -d '/+='`:

* `MYSQL_ROOT_PASSWORD` and `COUNCIL_DB_ADMIN_PASSWORD` must be the same value.
* `COUNCIL_DB_HUMAN_PASSWORD` is for the full-access `council_human` account.
* `COUNCIL_DB_AGENT_PASSWORD` is for the restricted `council_agent` account (needed by the agent directories).

`.env` is git-ignored. The database port defaults to **3307** so it does not clash with a MySQL you may
already run on 3306. `council db init` is safe to run repeatedly.

### Check your installation

```bash
python --version                     # Python 3.13.x
docker compose ps                    # investor-council-mysql  Up ... (healthy)  127.0.0.1:3307->3306/tcp
docker port investor-council-mysql   # 3306/tcp -> 127.0.0.1:3307   (must say 127.0.0.1, never 0.0.0.0)
council db status                    # server version, applied migrations, row counts
pytest                               # see Tests
```

## Use

```bash
# 1. Ingest a portfolio CSV (columns: ticker, shares, price[, sector]). The file is read locally, never copied.
council human ingest --file samples/portfolio.csv --sample --price-as-of 2026-10-30

# 2. Weights, sector allocation, concentration
council human summary                            # full local detail: positions, shares, values. Do not share.
council human summary --shared --target SYNA     # the sanitised version that is safe to paste into a shared room

# 3. Open a research session (prints the sanitised summary again)
council human session new --ticker SYNA --thesis "Is SYNA a durable compounder?"

# 4. Render the dossier (sanitised by default; deterministic apart from the generation timestamp)
council human report --session S-0001
council human report --local-detail -o dossier.local.md    # includes positions; keep it on this machine (*.local.md is git-ignored)
```

`samples/portfolio.csv` is **synthetic**: the tickers and prices are invented.

CSV rules: all-or-nothing by default. Any invalid row (non-numeric or non-positive values, bad ticker,
conflicting duplicates) is reported with its line number and nothing is stored; `--allow-partial` stores
the valid rows and marks the portfolio as partial. Identical duplicate tickers are merged with a warning.
Columns that look like credentials or account numbers cause the whole file to be refused; other extra
columns (e.g. cost basis) are ignored and not stored. Numbers must be plain (`1234.5`, not `$1,234.5`).

### Research workflow (human and agents)

The human starts every stage; agents use `./council-agent` from their own directories (generated by
`council human agents init`; see [switch/SETUP.md](switch/SETUP.md)).

```bash
council human session new --ticker T --cik N --thesis "..."   # prints the sanitised summary to paste into the room
council human data register --cik N                            # let agents cite a cached snapshot (agents cannot register sources)
# stage 1: both agents run ./council-agent next / evidence add / claim add / submit
council human status S-0001
council human advance S-0001 --to 2                            # stage 2: each reads the other's brief and challenges (up to 3)
council human advance S-0001 --to 3                            # stage 3: each files a final position
council human rule S-0001 C-B2 accept --note "..."             # every flagged claim needs accept or reject
council human finalize S-0001 --note "your own words"          # refused while any flagged claim is unresolved; stores the FINAL dossier
```

**The ruling gate.** A claim is *flagged* if it is `UNVERIFIED`, cites evidence that is not verified or is flagged
`STALE`/`CONFLICT`, or the other agent disputed it or asked for evidence. A flagged claim is resolved only by an
`accept` or `reject` ruling (`needs_evidence` is not a resolution). Until then a draft dossier shows it under
**UNRESOLVED** with a banner, never among findings, and `finalize` refuses with no override.

### Frozen SEC EDGAR data

```bash
export COUNCIL_SEC_USER_AGENT="Your Name you@example.com"   # your own identity; the SEC asks automated clients to declare it
council human data fetch --cik 320193        # company facts + filing metadata, validated and cached under data/edgar/
council human data inspect --cik 320193      # latest annual/quarterly period, filings, provenance (offline)
council human data manifest                  # data/edgar/MANIFEST.json
```

Requests are rate-limited (default 5/s, never above the SEC's published 10/s). Responses are validated
before being cached, and a cached file whose SHA-256 no longer matches is refused. EDGAR is used for
financial statements only: **there is no stock-price data**, and anything needing prices is recorded as a `GAP`.
The cache under `data/edgar/` is git-ignored; if you later choose a frozen dataset to share, add it
deliberately with `git add -f`.

### Evidence and claims (library API)

`council/evidence/service.py` provides `record_fact_evidence`, `record_metric_evidence`, `add_claim` and
`rule_claim`. A `FACT` needs verified evidence (otherwise it is stored as `UNVERIFIED`), an `ASSUMPTION`
needs a basis and a falsifier, and a metric missing from the snapshot becomes an explicit `GAP` claim.
Freshness thresholds are configurable in `config/freshness.yaml` and always labelled
*application heuristics, not accounting or regulatory standards*. Human rulings: `council human rule`.

## Privacy

* The raw CSV is processed locally and never posted anywhere. Only the sanitised summary (rounded
  percentages and counts: no shares, values, cost basis, other tickers or file fingerprint) is meant for a
  shared room. The shareable dossier is built from the same sanitised data.
* The restricted `council_agent` MySQL account cannot read `portfolios`, `holdings` or `dossiers` and cannot
  update or delete anything. This is defence in depth, not a hard boundary: processes running as your OS
  user can read whatever you can (including `.env`). Use the synthetic sample for demos.
* The thesis you type is included verbatim in the dossier, and rounded weights are still personal
  information: decide what you paste.

## Tests

```bash
pytest                 # 218 tests collected: 185 need no database + 33 marked `db` (MySQL integration)
pytest -m "not db"     # no database needed
```

Integration tests skip, rather than fail, when MySQL is unreachable (with the server down, 186 pass and 32 skip, because one `db`-marked test needs no server). They create throwaway
`council_test_*` databases and uniquely named accounts and drop them afterwards; your real database and
accounts are not touched. A leak test derives every private value (tickers, shares, prices, market values,
total) from the holdings and asserts none appears in the shareable summary or dossier, with a control
proving the check can detect a leak.

## Git hygiene

Excluded by `.gitignore`: `.env` and `.env.*` (except `.env.example`), `.council.env`, `.switch/`, key files,
**every `*.csv` except `samples/portfolio.csv`**, `portfolios/`, `*.local.md` (local-detail dossiers), database dumps and backups, the SEC cache and
manifest under `data/edgar/`, virtualenvs and caches. Check what a commit would contain with
`git status --short` before committing.

## Layout

```
council/
  config.py, errors.py, logging_setup.py
  db/            engine, SQL migrations, grants
  portfolio/     csv_ingest, metrics, summary, repository
  edgar/         client (cache, rate limit), validate, facts, metrics (curated map), manifest
  evidence/      freshness, verify, service (evidence + claims)
  report/        render (deterministic), lint, model (DB loader)
  agent/         council-agent CLI and stage validation (restricted account)
  cli/           council db ..., council human ...
config/freshness.yaml   samples/portfolio.csv   docker-compose.yml   tests/
scripts/                start.sh, start_switch.sh, demo.sh, seed_synthetic_snapshot.py
switch/                 room and agent instructions, SETUP.md, DEMO.md
```

## Known limitations

* **EDGAR has not been run against live SEC responses.** The adapter is tested against synthetic fixtures
  only. The expected field names (`end`, `val`, `accn`, `fy`, `fp`, `form`, `filed`) are unconfirmed
  (test T11 in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)). Filing history covers recent
  filings only; lookup is by CIK (no ticker resolution); only the curated metrics in
  `council/edgar/metrics.py` are mapped, and any other metric is a `GAP`.
* **No price or market data.** Weights use prices from your CSV; valuation or return analysis is out of scope.
* **Evidence is numeric XBRL facts only.** Filing-text evidence is not stored (a quote-verification
  utility exists but nothing uses it yet). Verification proves a figure is in the stored snapshot, not that
  the source is correct or complete.
* **Manual orchestration.** The agent tooling and stage control are built (`council-agent ...`, `council human status`,
  `advance`, `rule`, `finalize`), but a person (or, in S-0004, an assistant acting as test operator) must paste each stage
  message into the room and run `advance`, `rule` and `finalize` in a terminal. A room-side agent that would run the human
  steps from the chat was not built: it would need an agent registered outside Switch Console. Switch's documentation
  describes registration keys under **API Keys** in the Gateway for that purpose; the Console 0.40.1 Admin pages
  (Connectors, Status, Connector apps) do not offer it, and the Gateway page itself was not located or tested here
  (see [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md)). Treat it as *not verified*, not as a platform limit.
* **No run with a person making the rulings is recorded.** S-0004's rulings and decision note were written by the test
  operator on synthetic data.
* **Agents are not isolated from your user account.** Bull and Bear run as your OS user; the restricted MySQL account and
  directory separation are defence in depth, not a hard boundary.
* **Same-sector overlap is a heuristic** that depends on your own sector labels; an unknown sector is
  reported as unknown, never guessed.
* **CSV input is narrow by design:** UTF-8, comma-separated, plain numbers, at most 10,000 rows and 5 MB.
* **Single user.** Session codes are allocated with `MAX + 1` (the unique constraint prevents duplicates
  but concurrent writers could collide). The Compose container has a fixed name, so one stack per machine.
* **Migrations are not atomic** (MySQL DDL auto-commits); statements are idempotent so a failed run can be repeated.
* **Secrets are plain text in `.env`** (git-ignored). Passwords have no defaults, but the file is only as
  private as your user account.
* **Tested only on macOS with Python 3.13**, the only version `pyproject.toml` allows.

## Documentation

The six design documents in [docs/](docs/) describe the approved v0.2 design. They were written before the live run, so
passages that say "pending" or "not installed" describe the Nov 3 to Nov 4 state; each file carries a status note at the
top. [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) is the record of what has actually been verified (and what has not).
Remaining differences between design and code:

* **Not done:** the room-side "Clerk" agent (see Known limitations); live SEC (T5/T11) and the frozen dataset; filing-text evidence.
* **Scripts:** `scripts/start.sh` (MySQL, schema, agent folders, health check), `scripts/start_switch.sh` (Console in a clean
  environment, Mattermost check), `scripts/demo.sh` (headless fallback without Switch) and `scripts/seed_synthetic_snapshot.py`.
  Resetting the database is still `docker compose down -v` (this deletes the volume) followed by `council db init`.
* **The SEC cache is git-ignored by default;** a chosen dataset is added deliberately with `git add -f`.
* **Both agents share one restricted database account.** The database cannot tell Bull from Bear; the role is bound by
  each agent directory's `.council.env`, and an agent running as your OS user could edit it. Same-user limits are
  documented in the architecture doc.
