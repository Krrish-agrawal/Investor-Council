#!/bin/sh
# Start (or safely re-start) everything Investor Council needs locally. Idempotent; destroys nothing.
#   - MySQL in Docker (service `mysql` only; other containers are left alone)
#   - schema + accounts (council db init is idempotent)
#   - the two agent folders (only created if missing)
#   - a health check
# Switch Console is a desktop app: open it yourself (see switch/SETUP.md).
set -eu
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "No .env: copy .env.example to .env and fill in the passwords first." >&2; exit 1; }
[ -x .venv/bin/council ] || { echo "No .venv: run  python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker Desktop and re-run." >&2; exit 1; }

port=$(grep -E '^COUNCIL_DB_PORT=' .env | head -1 | cut -d= -f2 | cut -d'#' -f1 | tr -d ' ')
echo "Starting MySQL container on 127.0.0.1:${port:-3307} (existing container is reused) ..."
docker compose up -d mysql

echo "Waiting for MySQL to be healthy ..."
i=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' investor-council-mysql 2>/dev/null)" = "healthy" ]; do
  i=$((i + 1)); [ "$i" -gt 60 ] && { echo "MySQL did not become healthy in 5 minutes." >&2; exit 1; }
  sleep 5
done

.venv/bin/council db init
if [ ! -f agents/bull-researcher/.council.env ] || [ ! -f agents/bear-researcher/.council.env ]; then
  .venv/bin/council human agents init
else
  echo "Agent folders already exist (run '.venv/bin/council human agents init --force' to regenerate CLAUDE.md after editing switch/*.md)."
fi

echo "--- health"
.venv/bin/council db status
./agents/bull-researcher/council-agent whoami | grep -E '"role"|"db_user"'
./agents/bear-researcher/council-agent whoami | grep -E '"role"|"db_user"'
echo "OK. Next: open Switch Console (switch/SETUP.md) or run  scripts/demo.sh"
