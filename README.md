# Investor Council

Deterministic tooling for AI-assisted investment research: local portfolio analysis, frozen SEC EDGAR
financial-statement data, an evidence ledger with verification, and a Markdown research dossier.

> **Research and decision support only. Not financial advice.** Nothing here recommends buying,
> selling or holding anything, touches a brokerage account, or executes trades.

Design documents live in [docs/](docs/) (v0.2 is the source of truth; see [Documentation](#documentation) for how they relate to the code).

## Status

Foundation plus the agent tooling (Nov 4). Everything below "Built" is covered by tests, including a full
three-stage run with scripted agents against a real MySQL server; **no live Switch run has happened yet.**

| Built and tested | Pending |
|---|---|
| MySQL 8 schema, migrations, human and restricted agent accounts | Switch Console installed and connected (see [switch/SETUP.md](switch/SETUP.md)) |
| Local portfolio CSV ingestion, deterministic math, sanitised summary | The `#investor-council` room and live Bull/Bear agents |
| SEC EDGAR adapter (synthetic fixtures only) | Day-1 Switch tests T1 to T10; T11 (real EDGAR) and the frozen dataset |
| Evidence verification, claim typing, `GAP`, `STALE`, `CONFLICT` | Filing-text evidence |
| **`council-agent` commands** (`next`, `evidence`, `claim`, `submit`, `brief show --other`, `challenge add`, `final`) with stage validation, as the restricted account | |
| **Stage control** (`council human status`, `advance`, `finalize`) and the **ruling gate** | |
| Dossier renderer (briefs, final positions, UNRESOLVED section, DRAFT/FINAL) and advice-language lint | |
| Agent directory generator (`council human agents init`) and the instruction texts in `switch/` | |

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
pytest                 # 217 tests (185 need no database + 32 MySQL integration tests)
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

The six design documents in [docs/](docs/) describe the approved v0.2 design and mark what is implemented and
what is pending; they were synchronised with the code on Nov 4 2026. [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md)
records what has actually been verified (and what has not). Remaining differences between design and code:

* **Pending:** connecting Switch Console and running live agents; Day-1 tests T1 to T10; T11 and the frozen dataset.
* **Evidence is numeric XBRL facts only;** storing filing-text evidence is pending.
* **No `scripts/` directory yet:** reset the database with `docker compose down -v` (this deletes the volume)
  followed by `council db init`; there is no health-check script.
* **The SEC cache is git-ignored by default;** a chosen dataset is added deliberately with `git add -f`.
* **Both agents share one restricted database account.** The database cannot tell Bull from Bear; the role is bound by
  each agent directory's `.council.env`, and an agent running as your OS user could edit it. Same-user limits are
  documented in the architecture doc.
