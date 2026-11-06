# Demo: Bull and Bear in a Switch room (about 10 minutes)

Uses the synthetic company ("SYNTHETIC TEST CORP", CIK 9999999, fixture data) and the sample portfolio. Nothing places an order.

## Start (once)
```bash
scripts/start.sh            # MySQL, schema, agent folders, health
scripts/start_switch.sh     # Switch Console (clean environment) and its Mattermost
```
Open Switch Console, then the room **investor-council** (or "Open in Mattermost"). Agents: `bull-researcher`, `bear-researcher`.

## Run
```bash
.venv/bin/python scripts/seed_synthetic_snapshot.py
.venv/bin/council human data register --cik 9999999
.venv/bin/council human session new --ticker SYNT --cik 9999999 --target-sector Technology \
    --thesis "Is SYNTHETIC TEST CORP a durable compounder, and would adding it deepen my technology concentration?"
S=S-000N   # the code printed above
.venv/bin/council human message $S --stage 1 --copy      # paste into the room: Bull and Bear research independently
.venv/bin/council human status $S                        # wait for both to submit (about 2 minutes)
.venv/bin/council human advance $S --to 2
.venv/bin/council human message $S --stage 2 --copy      # paste: each reads the other's brief and challenges
.venv/bin/council human status $S                        # lists every flagged claim and why
.venv/bin/council human rule $S C-B8 accept --note "..." # you rule: accept or reject each flagged claim
.venv/bin/council human advance $S --to 3
.venv/bin/council human message $S --stage 3 --copy      # paste: final positions
.venv/bin/council human finalize $S --note "your own words" -o demo_output/dossier_$S.md   # refused while any flagged claim is unresolved
```

## What to point out
1. You start the council with one pasted message; both agents work in parallel and post briefs.
2. Their claims are typed and cited (FACT, ASSUMPTION, UNVERIFIED, GAP); every figure is frozen-snapshot evidence.
3. The challenge round: each reads the other's brief and responds in the room.
4. `status` lists flagged claims; `finalize` refuses until you accept or reject each one.
5. The dossier is rendered by Python, labelled frozen/not live, with no private holdings.

Fallback without Switch: `scripts/demo.sh --auto` runs the same flow with two headless Claude Code sessions.

## Notes on the recorded run (S-0004)
- The example dossier `docs/examples/dossier_S-0004.md` (copied from the git-ignored `demo_output/`) comes from a run in which an AI assistant played the human "test operator":
  it posted the stage messages and ran `advance`, `rule` and `finalize`. Its rulings are labelled *TEST RUN* in the dossier. When you
  run the demo yourself, **you** make the rulings; claim codes (such as `C-B8`) depend on what the agents file, so use the ones
  `council human status` prints.
- Orchestration is manual by design: you paste each stage message and run the terminal commands. Nothing in the room advances a stage.
- Everything here uses synthetic data. Live SEC data needs your own `COUNCIL_SEC_USER_AGENT` (see README).

