"""Load test: concurrent dashboards, field clients, dispatchers and copilot users against a running API.

Passes (one per invocation):
  dashboard  Each dashboard replays what the page requests on a slider stop, every 15 s: /map/zones and
             /map/freshness together, then /tasks and /cases together. Each field client polls /tasks every 30 s.
             Reads only, against Harvey at a fixed time.
  panels     Like dashboard, but dashboards poll only /tasks and /cases (an open page's panels).
  copilot    Users ask the copilot (template mode: no model calls) every 10 s, cycling through the intents and a
             free-text question, against Harvey.
  writes     Dispatchers assign and complete tasks on the MIXED run only, through the real task actions, plus a race:
             several concurrent assigns of the same task must give exactly one success. Temporary responders
             ("Load-test responder N") are added to the mixed run first. Refuses to write to any run that isn't mixed.
             Clean up afterwards with scripts/mixed_harvey_scenario.py, which rebuilds the mixed run.

Every request's latency and status are recorded; the report has p50/p95/p99 per endpoint, server errors, timeouts
and expected refusals (409/422), as JSON. Start offsets are spread with a seeded generator so runs repeat.

Usage (from the repo root, with the API running):
    .venv/bin/python scripts/load_test.py dashboard --dashboards 30 --field 150 --duration 60 --out report.json
"""
import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict

import httpx

HARVEY = "backtest:2017-08-25..2017-09-02"
MIXED = "mixed:harvey-synthetic-responders:2017-08-25..2017-09-02"
AT = "2017-08-27T18:30:00Z"  # Harvey's peak for White Oak: 133 tasks cut off
TIMEOUT = 30.0


class Recorder:
    def __init__(self):
        self.samples = defaultdict(list)  # name -> [(seconds, status)]
        self.behind = 0  # cycles that started late because the previous one overran

    async def call(self, client: httpx.AsyncClient, name: str, method: str, url: str, **kw):
        t0 = time.perf_counter()
        try:
            r = await client.request(method, url, timeout=TIMEOUT, **kw)
            status = r.status_code
        except httpx.TimeoutException:
            r, status = None, "timeout"
        except httpx.HTTPError as exc:
            r, status = None, f"error:{type(exc).__name__}"
        self.samples[name].append((time.perf_counter() - t0, status))
        return r

    def report(self) -> dict:
        out = {}
        for name, xs in sorted(self.samples.items()):
            lat = sorted(s for s, _ in xs)
            q = statistics.quantiles(lat, n=100, method="inclusive") if len(lat) > 1 else lat * 99
            statuses = defaultdict(int)
            for _, st in xs:
                statuses[str(st)] += 1
            out[name] = {"n": len(xs), "p50_ms": round(q[49] * 1000, 1), "p95_ms": round(q[94] * 1000, 1),
                         "p99_ms": round(q[98] * 1000, 1), "max_ms": round(lat[-1] * 1000, 1),
                         "statuses": dict(statuses)}
        return out


async def every(interval: float, offset: float, until: float, rec: Recorder, body):
    """Run body() every `interval` seconds from now + offset until `until`; late cycles start at once."""
    await asyncio.sleep(offset)
    nxt = time.perf_counter()
    while time.perf_counter() < until:
        await body()
        nxt += interval
        delay = nxt - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            rec.behind += 1


async def runs_by_name(client) -> dict:
    return {r["name"]: r for r in (await client.get("/runs")).json()["runs"]}


# ---------------------------------------------------------------- read passes
async def read_pass(client, rec, args, panels_only: bool):
    harvey = (await runs_by_name(client))[HARVEY]["id"]
    q = {"run_id": harvey, "at": AT}
    rnd = random.Random(args.seed)
    until = time.perf_counter() + args.duration

    async def dashboard():
        if not panels_only:
            await asyncio.gather(rec.call(client, "map/zones", "GET", "/map/zones", params=q),
                                 rec.call(client, "map/freshness", "GET", "/map/freshness", params=q))
        await asyncio.gather(rec.call(client, "tasks", "GET", "/tasks", params=q),
                             rec.call(client, "cases", "GET", "/cases", params=q))

    async def field():
        await rec.call(client, "tasks", "GET", "/tasks", params=q)

    jobs = [every(15, rnd.uniform(0, 15), until, rec, dashboard) for _ in range(args.dashboards)]
    jobs += [every(30, rnd.uniform(0, 30), until, rec, field) for _ in range(args.field)]
    await asyncio.gather(*jobs)


async def copilot_pass(client, rec, args):
    harvey = (await runs_by_name(client))[HARVEY]["id"]
    zones = (await client.get("/map/zones", params={"run_id": harvey, "at": AT})).json()["features"]
    zone = next(f["properties"]["zone_id"] for f in zones if f["properties"]["case_count"])
    case = (await client.get("/cases", params={"run_id": harvey, "zone_id": zone, "at": AT})).json()["cases"][0]["id"]
    asks = [{"intent": "open_cases"}, {"intent": "zone_status", "zone_id": zone}, {"intent": "zone_cases", "zone_id": zone},
            {"intent": "explain_confidence", "case_id": case}, {"intent": "briefing", "zone_id": zone},
            {"question": "what's the status of this zone?", "zone_id": zone}]
    rnd = random.Random(args.seed)
    until = time.perf_counter() + args.duration

    def user(i):
        k = {"n": i}

        async def ask():
            body = {"run_id": harvey, "at": AT, **asks[k["n"] % len(asks)]}
            k["n"] += 1
            await rec.call(client, "copilot/ask", "POST", "/copilot/ask", json=body)
        return ask

    await asyncio.gather(*[every(10, rnd.uniform(0, 10), until, rec, user(i)) for i in range(args.users)])


# ---------------------------------------------------------------- writes (mixed run only)
def add_temporary_responders(run_id: str, n: int) -> list[str]:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from app.database import SessionLocal
    from app.models import Responder, Run
    from app.models.run import RunMode
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run is None or run.mode != RunMode.mixed:
            sys.exit(f"refusing to add responders: run {run_id} is not a mixed run")
        rs = [Responder(run_id=run.id, name=f"Load-test responder {i}", role="load test (temporary)", team_id="load-test")
              for i in range(1, n + 1)]
        db.add_all(rs)
        db.commit()
        return [str(r.id) for r in rs]


async def writes_pass(client, rec, args):
    run = (await runs_by_name(client)).get(MIXED)
    if run is None or run["mode"] != "mixed":
        sys.exit("refusing to write: the mixed run is not in the database (run scripts/mixed_harvey_scenario.py)")
    actor = "load-test (synthetic)"
    free = add_temporary_responders(run["id"], args.dispatchers + args.race_width * args.races)
    tasks = [t for t in (await client.get("/tasks", params={"run_id": run["id"]})).json()["tasks"]
             if t["status"] == "pending"]
    random.Random(args.seed).shuffle(tasks)
    race_tasks, work = tasks[:args.races], tasks[args.races:]
    mine = [work[i::args.dispatchers] for i in range(args.dispatchers)]  # disjoint: dispatchers don't collide here
    until = time.perf_counter() + args.duration
    done = defaultdict(int)

    async def clear_if_flagged(task):
        if task["verify_before_dispatch"]:
            await rec.call(client, "tasks/clear-verify", "POST", f"/tasks/{task['id']}/clear-verify",
                           json={"actor": actor, "note": "load test"})

    async def dispatcher(i):
        responder = free[i]
        for task in mine[i]:
            if time.perf_counter() > until:
                return
            await clear_if_flagged(task)
            r = await rec.call(client, "tasks/assign", "POST", f"/tasks/{task['id']}/assign",
                               json={"actor": actor, "responder_id": responder, "note": "load test"})
            if r is not None and r.status_code == 200:
                await rec.call(client, "tasks/status", "POST", f"/tasks/{task['id']}/status",
                               json={"actor": actor, "status": "complete", "note": "load test"})
                done["completed"] += 1

    await asyncio.gather(*[dispatcher(i) for i in range(args.dispatchers)])

    races = []
    pool = free[args.dispatchers:]
    for k, task in enumerate(race_tasks):
        await clear_if_flagged(task)
        rs = pool[k * args.race_width:(k + 1) * args.race_width]
        results = await asyncio.gather(*[rec.call(client, "tasks/assign (race)", "POST", f"/tasks/{task['id']}/assign",
                                                  json={"actor": actor, "responder_id": r, "note": "load test race"})
                                         for r in rs])
        codes = [x.status_code if x is not None else "error" for x in results]
        state = (await client.get(f"/tasks/{task['id']}")).json()
        assigned_events = sum(1 for e in state["events"] if e["note"].startswith("assigned to"))
        races.append({"task": task["id"], "concurrent_assigns": len(rs), "successes": codes.count(200),
                      "refusals_409": codes.count(409), "other": [c for c in codes if c not in (200, 409)],
                      "assignment_events_recorded": assigned_events})
    return {"completed_assign_and_complete": done["completed"], "races": races}


async def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["dashboard", "panels", "copilot", "writes"])
    p.add_argument("--base", default="http://127.0.0.1:8010")
    p.add_argument("--dashboards", type=int, default=30)
    p.add_argument("--field", type=int, default=150)
    p.add_argument("--users", type=int, default=30)
    p.add_argument("--dispatchers", type=int, default=5)
    p.add_argument("--races", type=int, default=5)
    p.add_argument("--race-width", type=int, default=10)
    p.add_argument("--duration", type=float, default=60)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--label", default="")
    p.add_argument("--out")
    args = p.parse_args()

    rec = Recorder()
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=1000)
    async with httpx.AsyncClient(base_url=args.base, limits=limits, headers={"Accept-Encoding": "gzip"}) as client:
        t0 = time.perf_counter()
        extra = None
        if args.mode in ("dashboard", "panels"):
            await read_pass(client, rec, args, panels_only=args.mode == "panels")
        elif args.mode == "copilot":
            await copilot_pass(client, rec, args)
        else:
            extra = await writes_pass(client, rec, args)
        wall = time.perf_counter() - t0
    report = {"label": args.label, "mode": args.mode, "base": args.base, "duration_s": args.duration,
              "wall_s": round(wall, 1), "config": {k: v for k, v in vars(args).items() if k not in ("out",)},
              "cycles_started_late": rec.behind, "endpoints": rec.report(), **({"writes": extra} if extra else {})}
    text = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
