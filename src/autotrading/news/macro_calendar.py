from __future__ import annotations

from pathlib import Path

import yaml

from autotrading.news.models import MacroEvent


def load_macro_events(path: str | Path) -> list[MacroEvent]:
    raw = yaml.safe_load(Path(path).read_text())
    return [
        MacroEvent(date=e["date"], type=e["type"], label=e["label"])
        for e in raw.get("events", [])
    ]
