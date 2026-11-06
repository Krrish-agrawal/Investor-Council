# Switch setup (Phase 1): first connection

Everything here is documented at docs.switchagents.ai; the page for each step is linked. Steps marked **(Console)**
are clicks in Switch Console, a desktop app. Nothing in this repository can click them for you.

## 0. Decisions only you can make

* **Which machine and which Claude account run the agents.** Switch Console starts Claude Code sessions on the
  machine where it runs, using that machine's `claude auth login` account. Agents inherit the owner's access
  ([identity and access](https://docs.switchagents.ai/switch-rooms/internals/identity-and-access)). Use the machine
  and the account you intend the project to run on.
* Agents Switch Console runs on this computer answer only while Switch Console is open; agents moved to a managed machine (the default on a server Console runs, since Console 0.40) keep answering without Console, but the machine must be on. Check **Your Agents → the agent**. Keep the machine awake either way
  ([what keeps your agent running](https://docs.switchagents.ai/switch-rooms/getting-started/what-keeps-your-agent-running)).

## 1. Prerequisites (already done in this repo)

```bash
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env            # fill in the passwords
docker compose up -d && .venv/bin/council db init
.venv/bin/council human agents init     # creates agents/bull-researcher and agents/bear-researcher
```

`agents init` writes, in each agent folder, a git-ignored `.council.env` (restricted DB account only, mode 600), a
`council-agent` wrapper and a `CLAUDE.md` (role contract plus tool manual). It never writes the human's credentials.

## 2. Install and start Switch Console **(Console)**

1. Download the macOS Apple-silicon `.dmg` from
   [Install Switch Console](https://docs.switchagents.ai/switch-rooms/getting-started/install-switch-console),
   drag it to Applications, open it.
2. **Settings > Agent providers:** Claude Code must read **Signed in** (else run `claude auth login`, then **Recheck**).
3. **Add a server > Run a server on this computer > Start.** Wait for "Docker is ready", then "Running locally".
   The first start downloads a few GB. Switch runs its own Docker containers (server, Mattermost); our
   `docker-compose.yml` only runs MySQL.
4. Server **Home > Messaging apps > Mattermost row > Sign-in details... > Open in Mattermost** and sign in.

## 3. Register the first agent: Bull **(Console)**

[Add a custom agent](https://docs.switchagents.ai/switch-rooms/getting-started/add-a-second-agent) ·
[Agent settings](https://docs.switchagents.ai/switch-rooms/getting-started/agent-settings)

| Field | Value |
|---|---|
| Name | `bull-researcher` (cannot be changed later) |
| Description | Bull Researcher: evidence-backed positive case |
| Agent instructions | paste the whole of `agents/bull-researcher/CLAUDE.md` (also the fallback if `CLAUDE.md` is not loaded, test T2) |
| Run location | This computer |
| Directory | the absolute path of `agents/bull-researcher` (cannot be changed later) |
| Agent provider | Claude Code |
| Auto mode | on (default). **Bypass permissions: off** |
| Who can talk to your agent | Me and my agents (default) |

## 4. Create the room **(Console)**

[Create a room](https://docs.switchagents.ai/switch-rooms/getting-started/create-a-room): **Your Rooms > Create room**,
messaging app Mattermost, **Name `investor-council`**, description "Investor Council research room", **Instructions:**
paste `switch/room-instructions.md`, add `bull-researcher`. Then, in the channel (the command must be the first thing in
the message): `!set-alias @bull-researcher @bull`.

## 5. First verification (human message from Mattermost)

In the room, as yourself: `@bull-researcher run ./council-agent whoami and reply with the JSON`.
Expected: a reply showing `"role": "bull"` and `"db_user": "council_agent"`. If Auto mode escalates a permission
request, answer it in the thread (Allow once / Allow for this session). If there is no reply, see
[When an agent doesn't answer](https://docs.switchagents.ai/switch-rooms/using/agent-not-answering).

Then a real session (the CLI prints the sanitised summary to paste):

```bash
.venv/bin/council human session new --ticker <TICKER> --cik <CIK> --thesis "<your question>"
```
Post a Stage-1 message tagging the agent (template below) and watch it call `./council-agent next S-0001`.

## 6. Add Bear, then test the two-agent flow

Repeat step 3 for `bear-researcher` (folder `agents/bear-researcher`, paste its `CLAUDE.md`), add it to the room,
`!set-alias @bear-researcher @bear`. Then:

* **T1 (concurrency):** one message tagging both agents. Do both sessions run at the same time? If not, use the
  sequential fallback: send the same message to `@bull`, wait for its brief, then to `@bear`
  (`council human advance --force` is only needed if an agent cannot finish).
* Stage messages the human sends (always tag both agents, include the session code):

```
@bull-researcher @bear-researcher [session S-0001] Stage 1: initial analysis.
Target: <TICKER>. My question: <text>.
Portfolio context (sanitised): <paste the JSON from `council human session new`>.
Run ./council-agent next S-0001, research independently, file your evidence and claims, submit, and
post a brief of about 120 words. Do not read the other researcher's work.
```
```
@bull-researcher @bear-researcher [session S-0001] Stage 2: challenge round.
(I have run `council human advance S-0001 --to 2`.) Read the other's brief with ./council-agent brief show S-0001 --other,
challenge up to three of their claims, submit, and post a short summary. One round only.
```
```
@bull-researcher @bear-researcher [session S-0001] Stage 3: final synthesis.
(I have ruled on the flagged claims and run `council human advance S-0001 --to 3`.) File your final position
with ./council-agent final, and post a one-line note that you did.
```

The human then runs `council human status S-0001`, rules on flagged claims with `council human rule`, and
`council human finalize S-0001 --note "..."`. Python renders the dossier.

## 7. Record what you observe

Write each observation into `docs/TEST_RESULTS.md` (T1 to T6, T9) and flip the matching UNVERIFIED tags in the docs.

## 8. Known gap: agents that run outside Switch Console
Console registers its own agents with your signed-in session (no key to create). An agent built with its own client would instead need a
**registration key**; Switch's docs say anyone signed in to the Gateway can create one under **API Keys**
([People and agents](https://docs.switchagents.ai/switch-rooms/administer/people-and-agents#register-an-agent-that-runs-outside-switch-console)).
Console 0.40.1's Admin pages do not show API Keys, and this project has not located the Gateway page, so a room-side agent that would run
`advance`/`rule`/`finalize` from the chat was not built. Do not create a Mattermost bot account for this without deciding it deliberately.

