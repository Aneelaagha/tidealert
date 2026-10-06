"""The Harvey backtest's validation results, read from where they are stored and shown with their run, date and source.

Nothing here is typed in: every number is read, at request time, from the per-gauge backtest files
(backend/app/data/usgs-*/backtest.json, written by the isolation pipeline) or from the executed NFIP notebook
(notebooks/nfip_validation.ipynb, whose cell outputs carry their execution time). Each row names its file and the
place in it, so tests/test_validation.py can read the same place independently and compare, and check the numbers
against the tables in docs/algorithms/isolation-engine.md.

What these results are, and are not: they test the engine against the NWS minor-flood alarm time and against NFIP
insurance claims, on one event (Hurricane Harvey, 2017) in three Houston basins. They do not test it against observed
isolation: nobody recorded when a block was cut off.
"""
import json
import re
from pathlib import Path
from typing import Optional


DATA = Path(__file__).resolve().parent.parent / "data"
ROOT = DATA.parent.parent.parent
NOTEBOOK = ROOT / "notebooks" / "nfip_validation.ipynb"
RUN_NAME = "backtest:2017-08-25..2017-09-02"
GAUGES = ("08074500", "08076000", "08075770")  # White Oak, Greens, Hunting Bayou

LIMITS = (
    "These are tests of timing against the NWS minor-flood alarm and of location against NFIP insurance claims. Nobody recorded when a block was actually cut off, so there is no observed-isolation ground truth.",
    "One event (Hurricane Harvey, 2017) in three Houston basins. Two basins have an NWS flood map; Hunting Bayou uses HAND terrain modelling, at lower confidence, and its alarm is a fallback threshold, so its lead times are unverified.",
    "NFIP claims record flood damage, not isolation, and most homes had no flood insurance, so claims undercount flooding. Claims carry a date, not a time, so 'before the spike day' is the finest timing available.",
    "The static-floodplain comparison uses today's FEMA map; seven map panels touching the basins were made effective after Harvey, which slightly favours the static map.",
    "Inside the river driver's coverage the NFIP sample is 27 block groups (14 heavy): too small to rest a conclusion on.",
    "Flooding from rain alone is not modelled, and landslides and washouts are not modelled.",
    "The replayed record includes values estimated after the event; a live system would only have had provisional data at the time.",
)


def _gauge(site: str) -> dict:
    return json.loads((DATA / f"usgs-{site}" / "backtest.json").read_text())


def _minutes(x: Optional[float]) -> Optional[int]:
    return None if x is None else int(round(x))


def parse_nfip(nb: dict) -> dict:
    """The NFIP results from the notebook's executed outputs: the two flag tables and their stated sample sizes, with
    the time each cell ran. Parsed from the printed tables, so what is shown is exactly what the notebook printed."""
    def text(cell):
        return "".join("".join(o.get("text", [])) for o in cell.get("outputs", []))
    table = next(c for c in nb["cells"] if "All basins, all BGs" in text(c) and "recall_heavy" in text(c))
    out = text(table)
    ran = table["metadata"]["execution"]["iopub.status.idle"]

    def section(block: str) -> list[dict]:
        rows = []
        for line in block.splitlines():
            m = re.match(r"^(isolation Case \(any time\)|isolation Case before spike day|FEMA 100-yr floodplain \(static\)|FEMA 100\+500-yr floodplain \(static\))\s+(.*)$", line)
            if m:
                v = m.group(2).split()
                rows.append({"flag": m.group(1), "flagged_bgs": int(float(v[0])), "recall_heavy": float(v[1]),
                             "precision_lb_any_claim": float(v[2]), "share_flagged_heavy": float(v[3])})
        return rows
    all_part, _, covered_part = out.partition("Only BGs inside river-driver coverage")
    m_all = re.search(r"All basins, all BGs \((\d+) BGs, (\d+) heavy\)", all_part)
    m_cov = re.search(r"\((\d+) BGs, (\d+) heavy\)", covered_part)
    base = re.search(r"isolation Case \(any time\)\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)\s+(\S+)", all_part)
    return {"all": {"bgs": int(m_all.group(1)), "heavy": int(m_all.group(2)), "rows": section(all_part),
                    "base_rate_any_claim": float(base.group(1)), "base_rate_heavy": float(base.group(2))},
            "covered": {"bgs": int(m_cov.group(1)), "heavy": int(m_cov.group(2)), "rows": section(covered_part)},
            "executed_at": ran}


def harvey_backtest() -> dict:
    gauges, hand, zones = [], [], []
    for site in GAUGES:
        b = _gauge(site)
        f = f"backend/app/data/usgs-{site}/backtest.json"
        lead = b["lead_minutes_vs_alarm"]
        primary = b["river_driver"]["confidence"] == "primary"
        gauges.append({
            "site": site, "name": b["name"], "flood_source": b["river_driver"]["method"], "confidence": b["river_driver"]["confidence"],
            "alarm_minor_at": b["alarm_minor"], "alarm_source": b["thresholds"]["provenance"]["minor"],
            "first_road_floods_min": _minutes(lead["first road segment floods"]),
            "first_zone_isolated_min": _minutes(lead["first zone isolated"]),
            "verified": primary,
            "source": {"file": f, "path": "lead_minutes_vs_alarm['first road segment floods' | 'first zone isolated'], alarm_minor, river_driver, thresholds"}})
        if b.get("hand_vs_nws_iou"):
            hand.append({"site": site, "name": b["name"], "median": round(b["hand_vs_nws_iou"]["event_steps_median"], 2),
                         "minimum": round(b["hand_vs_nws_iou"]["event_steps_min"], 2),
                         "source": {"file": f, "path": "hand_vs_nws_iou['event_steps_median' | 'event_steps_min']"}})
        zones.append({"site": site, "name": b["name"], "status": b["zone_status"], "source": {"file": f, "path": "zone_status"}})
    nb = json.loads(NOTEBOOK.read_text())
    nfip = parse_nfip(nb)
    window = _gauge(GAUGES[0])["window_utc"]
    primary = [g for g in gauges if g["verified"]]
    eng, fp100, fp500 = (next(r for r in nfip["all"]["rows"] if r["flag"] == k) for k in
                         ("isolation Case (any time)", "FEMA 100-yr floodplain (static)", "FEMA 100+500-yr floodplain (static)"))
    return {
        "run": RUN_NAME, "event": "Hurricane Harvey", "data_window_utc": window,
        "headline": [
            {"kind": "strength", "text": f"At the {len(primary)} gauges with an NWS flood map, the first road floods {min(g['first_road_floods_min'] for g in primary)} to "
                                         f"{max(g['first_road_floods_min'] for g in primary)} minutes before the gauge reaches the NWS minor-flood alarm."},
            {"kind": "weakness", "text": f"Against NFIP claims, the engine's Cases reach {eng['recall_heavy']:.1%} of the {nfip['all']['heavy']} heaviest-claims block groups; "
                                         f"FEMA's static 100-year floodplain map reaches {fp100['recall_heavy']:.1%} (100+500-year: {fp500['recall_heavy']:.1%}), and it is available before the storm. "
                                         "The engine does not beat the static map."},
        ],
        "lead": {"title": "Lead time before the NWS minor-flood alarm (minutes; positive = before the alarm)", "rows": gauges},
        "zones": {"title": "Zones by status, by basin", "rows": zones},
        "hand": {"title": "HAND terrain model vs the NWS flood map: overlap (IoU) over the event's flooding steps", "rows": hand},
        "nfip": {"title": "NFIP insurance claims: which block groups did each flag catch?", "all": nfip["all"], "covered": nfip["covered"],
                 "source": {"file": "notebooks/nfip_validation.ipynb", "path": "the cell printing 'All basins, all BGs' (executed output)"},
                 "executed_at": nfip["executed_at"], "definitions": "Heavy-claims block group: top 20% of a basin's block groups by claims per 100 housing units, at least 5 claims. Static baseline: FEMA's floodplain map, a block group counted when at least 10% of its populated area lies in it."},
        "limits": list(LIMITS),
    }
