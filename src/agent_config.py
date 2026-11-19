"""Load the agent settings: which tools run, which model to use and the limits."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text())
