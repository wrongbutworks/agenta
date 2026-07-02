# Daytona Sandbox Snapshot

This folder contains the supported self-host recipe for building a Daytona snapshot for the
Agenta `sandbox-agent` runner path.

We ship the recipe, not a built snapshot. The operator runs it in their own Daytona account:

```bash
DAYTONA_API_KEY=... DAYTONA_TARGET=eu uv run build_snapshot.py --force
```

Configure the runner service with:

```bash
SANDBOX_AGENT_PROVIDER=daytona
DAYTONA_SNAPSHOT=agenta-sandbox-pi
```

## What's baked

The recipe bases on `rivetdev/sandbox-agent:*-full`. That base image's own last build layer
runs `sandbox-agent install-agent --all`, which already bakes, per harness:

| harness | native binary | ACP adapter |
| --- | --- | --- |
| claude | yes (`bin/claude`) | yes (`agent_processes/claude-acp`) |
| codex | yes (`bin/codex`) | yes (`agent_processes/codex-acp`, `@zed-industries/codex-acp`) |
| opencode | yes (`bin/opencode`) | yes (`agent_processes/opencode-acp`) |
| pi | **no** | yes (`agent_processes/pi/…/pi-acp`) |

(Verified by pulling the base image manifest and inspecting its final layer, not by a live
Daytona build.) So the only harness this script adds anything for is Pi: it globally
`npm install`s `@earendil-works/pi-coding-agent`, the standalone `pi` CLI binary that
`pi-acp` shells out to (the base image's `install-agent --all` installs `pi-acp` but not
`pi` itself). For claude/codex/opencode the build only verifies the base image still ships
them (fails loudly if a future base tag drops one); it does not reinstall them.

## The levers (`AGENTA_AGENT_SANDBOX_*_INSTALLED`)

`daytona.ts` defaults to **install-OFF**: it assumes the configured snapshot already bakes
`pi` and never installs it into the sandbox at session time unless told to.

- `AGENTA_AGENT_SANDBOX_PI_INSTALLED=true` — opt IN to installing `pi` into the sandbox at
  session time. Use this only when running against a bare/non-snapshot image that lacks
  `pi` (e.g. local iteration without a custom snapshot). Unset or `false` both mean
  "assume the snapshot has it" — the old `=false` opt-out spelling still works, since it
  was never `true`, so it stays off under the new default too.
- `AGENTA_AGENT_SANDBOX_{CODEX,OPENCODE,CLAUDE}_INSTALLED` — reserved for symmetry only.
  The runner has no session-time install path for these three harnesses today (only Pi
  does); they only ever auto-install via the sandbox-agent daemon itself, and the same
  `-full` base image already bakes all three. Nothing reads these yet.

## Per-run cost when unbaked

Running against a bare (non-snapshot) `sandbox-agent` image, per fresh sandbox:

- **pi**: ~150s `npm install` if `AGENTA_AGENT_SANDBOX_PI_INSTALLED=true` is set (or the
  daemon's own auto-install if not going through this runner's install path at all).
- **claude**: by far the most expensive — a daemon `install-agent claude` on a cold
  sandbox took ~300s to download the native binary plus ~60s to npm-install the
  `claude-agent-acp` ACP adapter (measured directly against the shipped darwin-arm64
  `sandbox-agent` CLI).
- **codex**: a native binary fetch plus an npm install of the platform-specific
  `codex-acp` package.
- **opencode**: cheapest of the three daemon-installed harnesses; the CLI's own
  `install-agent opencode` reported "already installed" in the same probe (the
  `sandbox-agent` package appears to vendor an opencode compatibility layer).

This is exactly the cost the Daytona snapshot exists to avoid: ephemeral, never-reused
sandboxes pay it on every run, while a session against this baked snapshot pays it zero
times for all four harnesses.

The base image includes Claude Code. We do not distribute the resulting snapshot. Cloud
builds its own internal snapshot; self-hosters build their own.

Keep credentials out of the image and snapshot. Provider keys and self-managed login paths are
runtime concerns.
