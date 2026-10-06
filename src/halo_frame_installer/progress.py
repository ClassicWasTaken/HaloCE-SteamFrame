"""Monotonic overall progress from completed setup phases, never elapsed time."""
from __future__ import annotations

import math
from numbers import Real


# Ranges describe work in the setup flow, not a prediction of its duration.
# A supplied percentage is local to its phase (for example, uploaded bytes or
# Ninja's completed build tasks), rather than the whole installation.
PHASES = {
    "preparing maps": (0, 10, "Preparing Xbox game data"),
    "connect": (10, 12, "Connecting to your Frame"),
    "preflight": (12, 15, "Checking your Frame"),
    "detect": (15, 20, "Checking the existing installation"),
    "verify": (15, 20, "Verifying Xbox game data"),
    "reuse": (15, 20, "Checking reusable Xbox game data"),
    "repair": (15, 20, "Preparing the repair"),
    "uninstall": (15, 96, "Removing native Halo VR"),
    "upload": (20, 40, "Sending Xbox maps to your Frame"),
    "source": (40, 45, "Downloading the native VR source"),
    "build": (45, 45, "Preparing the native build container"),
    "dependencies": (45, 52, "Installing Linux build tools"),
    "toolchain": (52, 60, "Installing the ARM64 compiler"),
    "configure": (60, 64, "Configuring the native game"),
    "sdl": (64, 73, "Building the SDL graphics and input library"),
    "compile": (73, 90, "Compiling Halo and VR support"),
    "build-check": (90, 92, "Checking the native game build"),
    "install": (92, 96, "Installing the native game and Xbox controls"),
    "steam": (96, 99, "Updating Halo's Steam library information"),
    "disconnect": (99, 99, "Closing the setup connection"),
    "disconnected": (99, 99, "Disconnected from your Frame"),
    "cleanup-pending": (99, 99, "Connection cleanup needs attention"),
    "removal-pending": (99, 99, "Uninstall needs attention"),
    "complete": (99, 99, "Finishing setup"),
}


class SetupProgress:
    """An approximate, one-way view of work completed in the current attempt."""

    def __init__(self):
        self.value = 0.0

    def reset(self):
        self.value = 0.0

    def update(self, stage: str, percent=None) -> float:
        phase = PHASES.get(str(stage).strip().lower())
        if phase is None:
            return self.value
        start, end, _ = phase
        candidate = float(start)
        if (isinstance(percent, Real) and not isinstance(percent, bool)
                and 0 <= percent <= 100 and math.isfinite(percent)):
            candidate += (end - start) * float(percent) / 100
        self.value = max(self.value, min(99.0, candidate))
        return self.value

    @staticmethod
    def caption(stage: str) -> str:
        phase = PHASES.get(str(stage).strip().lower())
        return phase[2] if phase else str(stage)

    def finish(self, *, pending: bool = False) -> float:
        # Only the installer result can mark the complete wizard as 100%.
        self.value = 99.0 if pending else 100.0
        return self.value
