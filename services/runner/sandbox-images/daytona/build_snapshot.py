# /// script
# requires-python = ">=3.11"
# dependencies = ["daytona"]
# ///
"""Build a Daytona snapshot for the Agenta sandbox-agent runner.

The `-full` sandbox-agent base image already bakes ALL FOUR harnesses: its own build
runs `sandbox-agent install-agent --all` as its last layer, which installs the claude,
codex, and opencode native binaries + ACP adapters (verified by pulling the image
manifest and inspecting the layer: `bin/claude`, `bin/codex` + `agent_processes/codex-acp`
(`@zed-industries/codex-acp`), `bin/opencode` + `agent_processes/opencode-acp`), plus the
`pi-acp` adapter for Pi. The ONE thing `install-agent --all` does NOT bake is the
standalone `pi` CLI binary itself (`@earendil-works/pi-coding-agent`) that `pi-acp` shells
out to -- so this script's only real job is adding that. Everything else below is a
verify-and-mark step, not a re-install: we set the `_INSTALLED` marker for
claude/codex/opencode too so `daytona.ts` never re-runs their daemon auto-install
(currently a no-op safety net at runtime, since the daemon's own install is idempotent,
but skipping it avoids the "is it already there" round-trip on every run) and never pays
their (far larger) per-run cost were that ever to regress. Set the runner service to use
this snapshot:

    DAYTONA_SNAPSHOT=agenta-sandbox-pi
    AGENTA_AGENT_SANDBOX_PI_INSTALLED=true
    AGENTA_AGENT_SANDBOX_CODEX_INSTALLED=true
    AGENTA_AGENT_SANDBOX_OPENCODE_INSTALLED=true
    AGENTA_AGENT_SANDBOX_CLAUDE_INSTALLED=true

Run: DAYTONA_API_KEY=... DAYTONA_TARGET=eu uv run build_snapshot.py [--force]

Licensing (see services/agent/docker/README.md):
    This script is the build recipe we ship, NOT a snapshot we distribute. Whoever
    runs it builds the snapshot in their own Daytona account: Agenta Cloud builds
    its own for internal use; self-hosters build their own. We never hand anyone a
    Claude-containing image, so this is compliant even though the `-full` base bundles
    Claude (Anthropic's Commercial Terms forbid us *distributing* Claude Code, not
    building/using it).

    Cleaner-provenance follow-up (needs a live Daytona build to verify): base on a
    daemon-only sandbox-agent image and install Claude from Anthropic at build (npm
    `@anthropic-ai/claude-code` or `claude.ai/install.sh`), so the snapshot's Claude
    comes straight from Anthropic instead of from a third party's bundled image. Pin
    that only after confirming the daemon-only tag also ships the ACP adapters.
"""

import sys
import time

from daytona import (
    CreateSnapshotParams,
    Daytona,
    DaytonaConfig,
    Image,
    Resources,
)

SNAPSHOT_NAME = "agenta-sandbox-pi"
SANDBOX_AGENT_IMAGE = "rivetdev/sandbox-agent:0.5.0-rc.2-full"
PI_PACKAGE = "@earendil-works/pi-coding-agent@0.79.4"
# Durable session cwd: geesefs (FUSE-over-S3) mounts the store prefix INSIDE the sandbox for
# remote runs. fuse provides fusermount + /etc/fuse.conf; geesefs is the static mount binary.
# amd64 is correct here regardless of the builder's local arch: the snapshot is built and run
# on Daytona's x86_64 cloud hosts, not on this machine. (The local/prod runner Dockerfiles, by
# contrast, arch-match via `dpkg --print-architecture` because they may build on arm64 Macs.)
GEESEFS_VERSION = "v0.43.0"
GEESEFS_URL = (
    "https://github.com/yandex-cloud/geesefs/releases/download/"
    f"{GEESEFS_VERSION}/geesefs-linux-amd64"
)


def main() -> None:
    force = "--force" in sys.argv
    daytona = Daytona(DaytonaConfig())

    try:
        existing = daytona.snapshot.get(SNAPSHOT_NAME)
    except Exception:
        existing = None

    if existing and not force:
        print(f"snapshot '{SNAPSHOT_NAME}' already exists; pass --force to rebuild.")
        return
    if existing:
        print(f"deleting existing snapshot '{SNAPSHOT_NAME}'...")
        daytona.snapshot.delete(existing)

    # Base on the full sandbox-agent image and add the pi CLI globally so it is on PATH for
    # the sandbox user the daemon runs as. The image's default user is the non-root
    # `sandbox`, so switch to root for the global install, then back.
    #
    # claude/codex/opencode are NOT re-installed here: the base image's own last build layer
    # already runs `sandbox-agent install-agent --all`, which bakes their native binaries
    # and ACP adapters. We only verify that here (fail the build loudly if a future base tag
    # drops one) instead of re-running `install-agent`, since the daemon's own install is
    # idempotent but the verify is cheaper and documents the assumption in one place.
    image = Image.base(SANDBOX_AGENT_IMAGE).dockerfile_commands(
        [
            "USER root",
            f"RUN npm install -g --ignore-scripts {PI_PACKAGE}",
            "RUN pi --version || true",
            # Base image already bakes these three via `install-agent --all`, run as the
            # `sandbox` user (see module docstring); fail fast if a future base tag stops
            # shipping one. Still root here, so the path is spelled out rather than $HOME.
            "RUN test -x /home/sandbox/.local/share/sandbox-agent/bin/claude "
            '&& echo "claude: baked in base image"',
            "RUN test -x /home/sandbox/.local/share/sandbox-agent/bin/codex "
            '&& echo "codex: baked in base image"',
            "RUN test -x /home/sandbox/.local/share/sandbox-agent/bin/opencode "
            '&& echo "opencode: baked in base image"',
            # Durable cwd: fuse + geesefs so the remote sandbox can mount its store prefix.
            "RUN apt-get update && apt-get install -y --no-install-recommends fuse curl "
            "&& rm -rf /var/lib/apt/lists/* && echo user_allow_other >> /etc/fuse.conf",
            f"RUN curl -fsSL -o /usr/local/bin/geesefs {GEESEFS_URL} "
            "&& chmod +x /usr/local/bin/geesefs",
            "USER sandbox",
        ]
    )

    print(f"building snapshot '{SNAPSHOT_NAME}' from {SANDBOX_AGENT_IMAGE} (+ pi)...")
    started = time.monotonic()
    daytona.snapshot.create(
        CreateSnapshotParams(
            name=SNAPSHOT_NAME,
            image=image,
            resources=Resources(cpu=2, memory=4, disk=8),
        ),
        on_logs=print,
    )
    print(f"\nsnapshot '{SNAPSHOT_NAME}' built in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
