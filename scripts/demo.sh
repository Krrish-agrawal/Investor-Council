#!/bin/sh
# Hackathon demo without Switch: you are the Portfolio Manager, Bull and Bear are two separate Claude Code sessions.
#
#   scripts/demo.sh            interactive: pauses so YOU rule on flagged claims and finalize
#   scripts/demo.sh --auto     unattended: stand-in rulings (clearly labelled as automated test rulings)
#
# Data: with no --cik the SYNTHETIC fixture company is used (offline, labelled "fixture, not real data").
# For real SEC data set COUNCIL_SEC_USER_AGENT in .env to your OWN contact, run
#   .venv/bin/council human data fetch --cik <CIK> && .venv/bin/council human data register --cik <CIK>
# and pass  --cik <CIK> --ticker <TICKER>.
# Uses the sample portfolio only. Nothing here places an order.
set -eu
cd "$(dirname "$0")/.."

AUTO=0; CIK=""; TICKER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --auto) AUTO=1 ;;
    --cik) CIK="$2"; shift ;;
    --ticker) TICKER="$2"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

COUNCIL=.venv/bin/council
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
[ -n "$CLAUDE_BIN" ] || CLAUDE_BIN="${CLAUDE_CODE_EXECPATH:-}"
[ -x "${CLAUDE_BIN:-}" ] || { echo "Claude Code not found: set CLAUDE_BIN to the claude executable." >&2; exit 1; }
"$CLAUDE_BIN" auth status 2>/dev/null | grep -q '"loggedIn": true' || { echo "Claude Code is not signed in: run 'claude auth login'." >&2; exit 1; }

OUT="${DEMO_OUT:-demo_output}"; mkdir -p "$OUT"
[ -f samples/portfolio.csv ] || { echo "samples/portfolio.csv missing" >&2; exit 1; }

if [ -z "$CIK" ]; then
  .venv/bin/python scripts/seed_synthetic_snapshot.py
  CIK=9999999; TICKER="${TICKER:-SYNT}"
  QUESTION="Is SYNTHETIC TEST CORP a durable compounder, and would adding it deepen my technology concentration?"
else
  [ -n "$TICKER" ] || { echo "--cik needs --ticker" >&2; exit 2; }
  QUESTION="Is $TICKER a durable compounder, and would adding it deepen my technology concentration?"
fi
$COUNCIL human data register --cik "$CIK"

# the human's portfolio stays in the database; only a sanitised summary is ever shown to the agents
if [ "$($COUNCIL db status | awk '/^ *portfolios/ {print $2}')" = "0" ]; then
  $COUNCIL human ingest --file samples/portfolio.csv --name demo --sample
fi
CODE=$($COUNCIL human session new --ticker "$TICKER" --cik "$CIK" --target-sector Technology --thesis "$QUESTION" 2>/dev/null >/dev/null; $COUNCIL human status | head -1 | awk '{print $1}')
echo "== Session $CODE opened by the human. Question: $QUESTION"

run_agents() {  # $1 = stage label, $2 = prompt
  for r in bull bear; do
    ( cd "agents/$r-researcher" && "$CLAUDE_BIN" -p "$2" --allowedTools "Bash(./council-agent:*)" \
        --permission-mode dontAsk --output-format text > "../../$OUT/${CODE}_${1}_${r}.txt" 2>&1 ) &
  done
  wait
  for r in bull bear; do echo "---- $r ($1):"; cat "$OUT/${CODE}_${1}_${r}.txt"; done
}

echo "== STAGE 1: Bull and Bear research independently (blind)"
run_agents stage1 "[session $CODE] Stage 1: initial analysis. Target: $TICKER. My question: $QUESTION Run ./council-agent next $CODE, research independently, file your evidence and claims, submit, and post a brief of about 120 words as your final reply. Do not read the other researcher's work."
$COUNCIL human advance "$CODE" --to 2

echo "== STAGE 2: each researcher reads the other's brief and files up to three challenges"
run_agents stage2 "[session $CODE] Stage 2: challenge round. (I have run council human advance $CODE --to 2.) Read the other's brief with ./council-agent brief show $CODE --other, challenge up to three of their claims, submit, and post a short summary as your final reply. One round only."

echo "== HUMAN: review the flagged claims"
$COUNCIL human status "$CODE"
if [ "$AUTO" = 1 ]; then
  for c in $($COUNCIL human status "$CODE" | awk '/^  C-[BX][0-9]+ / {print $1}'); do
    $COUNCIL human rule "$CODE" "$c" accept --note "Automated demo ruling (--auto); not a real investment decision" >/dev/null
  done
else
  echo "Rule on each flagged claim in another terminal:  $COUNCIL human rule $CODE <CLAIM> accept|reject --note \"...\""
  printf "Press Enter when every flagged claim has an accept or reject ruling ... "; read -r _
fi
$COUNCIL human advance "$CODE" --to 3

echo "== STAGE 3: final positions"
run_agents stage3 "[session $CODE] Stage 3: final synthesis. (I have ruled on the flagged claims and run council human advance $CODE --to 3.) Use ./council-agent claim list $CODE to review your own claims, file your final position with ./council-agent final, and post a one-line note that you did as your final reply."

echo "== HUMAN: final decision and dossier"
if [ "$AUTO" = 1 ]; then NOTE="Automated demo finalization; the human remains the decision-maker"
else printf "Your decision note (your own words): "; read -r NOTE; fi
$COUNCIL human finalize "$CODE" --note "$NOTE" -o "$OUT/dossier_${CODE}.md"
echo "Dossier: $OUT/dossier_${CODE}.md  (agent transcripts in $OUT/)"
