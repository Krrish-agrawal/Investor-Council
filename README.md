# Investor Council

Deterministic tooling for AI-assisted investment research: local portfolio analysis, frozen SEC EDGAR
financial-statement data, an evidence ledger with verification, and a Markdown research dossier.

> **Research and decision support only. Not financial advice.** Nothing here recommends buying,
> selling or holding anything, touches a brokerage account, or executes trades.

Design documents live in [docs/](docs/) (v0.2 is the source of truth; see [Documentation](#documentation) for how they relate to the code).

## Status

This is the **pre-kickoff foundation**: independent, tested building blocks.

| Built and tested | Not built yet (starts at hackathon kickoff) |
|---|---|
| MySQL 8 schema, migrations, human/agent accounts | Switch room, Switch-connected agents, agent prompts |
| Local portfolio CSV ingestion + validation | `council agent ...` commands, stage advancing/gating |
| Weights, sector allocation, top-N concentration, HHI | Agent-written research sections |
| Sanitised summary for sharing in a room | Filing-text (`FILING_TEXT`) evidence |
| SEC EDGAR adapter (CIK lookup, company facts, filings metadata, cache) | |
| Evidence storage + deterministic verification, claim typing rules, GAP records | |
| Deterministic dossier renderer + advice-language lint | |

Verified on macOS with Python 3.13.12, Docker 29.9 and MySQL 8.0.46 (the `mysql:8.0` image).

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
* `COUNCIL_DB_AGENT_PASSWORD` is for the restricted `council_agent` account (optional until agent tooling exists).

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
pytest                 # 197 tests (176 need no database + 21 MySQL integration tests)
pytest -m "not db"     # no database needed
```

Integration tests skip, rather than fail, when MySQL is unreachable. They create throwaway
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
  cli/           council db ..., council human ...
config/freshness.yaml   samples/portfolio.csv   docker-compose.yml   tests/
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
* **Agent tooling is not built:** no `council agent ...` commands, stage advancing or gating, and no Switch
  room or agents. This is deliberate until the hackathon starts.
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

The six design documents in [docs/](docs/) were synchronised with this code on Nov 3 2026: paths, command
names, the database schema (the DDL is the real migration, and its SQL has been executed against MySQL 8),
the grants, and the privacy behaviour. They describe the approved v0.2 design and mark what is implemented
and what is pending. The differences that remain between the design and the code are all deliberate or
pending:

* **Pending (needs Switch or agents):** the `council agent ...` commands, `council human advance`, `status`
  and `finalize`, stage enforcement, and the Switch room, agents and instructions.
* **Rulings are rendered, not enforced:** `council human report` labels unruled claims instead of refusing to
  render; a hard gate belongs to the pending stage tooling.
* **Evidence is numeric XBRL facts only;** storing filing-text evidence is pending.
* **No `scripts/` directory yet:** reset the database with `docker compose down -v` (this deletes the
  volume) followed by `council db init`; there is no health-check script.
* **The SEC cache is git-ignored by default;** a chosen dataset is added deliberately with `git add -f`.
