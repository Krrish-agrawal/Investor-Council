#!/bin/sh
# Start Switch Console safely and make sure its Mattermost container is up. Idempotent; touches no other container.
# Why a clean environment: if ELECTRON_RUN_AS_NODE is set in your shell (some tools export it), Electron apps run as
# plain Node and exit immediately with no window. This launches Console with a minimal environment instead.
set -eu
APP="/Applications/Switch Console.app/Contents/MacOS/Switch Console"
[ -x "$APP" ] || { echo "Switch Console is not installed (see switch/SETUP.md)." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker Desktop first." >&2; exit 1; }
CLAUDE_DIR=$(dirname "$(command -v claude 2>/dev/null || echo /usr/local/bin/claude)")
if pgrep -f "Switch Console.app/Contents/MacOS/Switch Console" >/dev/null 2>&1; then
  echo "Switch Console is already running."
else
  echo "Launching Switch Console ..."
  nohup /usr/bin/env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" SHELL=/bin/zsh LANG=en_US.UTF-8 \
    PATH="$CLAUDE_DIR:$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
    "$APP" >/dev/null 2>&1 &
  sleep 15
fi
MM=switchdash-local-mattermost-mattermost-1
if docker ps -a --format '{{.Names}}' | grep -qx "$MM"; then
  [ "$(docker inspect -f '{{.State.Running}}' $MM)" = "true" ] || { echo "Starting $MM ..."; docker start $MM >/dev/null; }
  i=0; until [ "$(docker inspect -f '{{.State.Health.Status}}' $MM 2>/dev/null)" = "healthy" ]; do i=$((i+1)); [ $i -gt 30 ] && { echo "Mattermost not healthy" >&2; exit 1; }; sleep 4; done
  echo "Mattermost healthy at $(docker port $MM 8065/tcp)"
else
  echo "Mattermost container not created yet: open Switch Console and finish the server setup (switch/SETUP.md)."
fi
