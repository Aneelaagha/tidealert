"""The real event a recorded run replays, by name, so the page can say "replay of Hurricane Harvey".

This is a fact about the event, not something the pipeline measures, so it lives here as a short documented table
rather than in the data. A run is matched only on its stored window (it starts on the event's first day and ends on
its last day or the sweep tick just after) and only when it replays a recorded event (replay or mixed mode): a scenario is synthetic and has no real event, and an unmatched run says nothing.
Sources: Harvey landfall and flooding, 2017-08-25 to 2017-09-02 (the window this project's backtest replays);
Helene, 2024-09-25 to 2024-09-30 (the window of the Asheville run).
"""
from datetime import date, timedelta
from typing import Optional

from app.models import Run
from app.models.run import RunMode

EVENTS = (
    {"label": "Hurricane Harvey", "start": date(2017, 8, 25), "end": date(2017, 9, 2)},
    {"label": "Hurricane Helene", "start": date(2024, 9, 25), "end": date(2024, 9, 30)},
)


def run_event(run: Run) -> Optional[str]:
    if run.mode not in (RunMode.replay, RunMode.mixed) or run.window_start is None or run.window_end is None:
        return None
    for e in EVENTS:
        if run.window_start.date() == e["start"] and e["end"] <= run.window_end.date() <= e["end"] + timedelta(days=1):
            return e["label"]
    return None
