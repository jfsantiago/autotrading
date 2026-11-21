from autotrading.news.macro_calendar import load_macro_events


def test_load_macro_events(tmp_path):
    path = tmp_path / "macro.yaml"
    path.write_text(
        """
events:
  - date: "2026-12-16"
    type: fomc
    label: "FOMC meeting decision"
"""
    )
    events = load_macro_events(path)
    assert len(events) == 1
    assert events[0].date == "2026-12-16"
    assert events[0].type == "fomc"
    assert events[0].label == "FOMC meeting decision"


def test_load_macro_events_empty(tmp_path):
    path = tmp_path / "macro.yaml"
    path.write_text("events: []\n")
    assert load_macro_events(path) == []
