"""Runtime switch for the temporary presentation-oriented redesign policy."""
from __future__ import annotations

import os


def demo_strong_redesign_enabled() -> bool:
    """Default to demo mode for the current MVP; strict mode remains opt-in."""
    explicit = os.getenv("DEMO_STRONG_REDESIGN")
    if explicit is not None:
        return explicit.strip().casefold() in {"1", "true", "yes", "on"}
    return os.getenv("REDESIGN_MODE", "demo").strip().casefold() == "demo"

