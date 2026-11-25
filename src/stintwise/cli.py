"""Command line interface: ``stintwise plan|caution|analyze|sample|serve``."""
from __future__ import annotations

import argparse
import json
import sys

from . import analysis
from .caution import CautionCall, evaluate
from .debrief import debrief, to_markdown
from .fit import fit_rules, fit_spec
from .live import Rules, race_events, race_state
from .planner import InfeasiblePlan, plan, spec_from_dict
from .presets import PRESETS, preset
from .sample import write_sample
from .timing import load_csv


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    h, rem = divmod(int(round(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def laptime(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"


def _plan(args: argparse.Namespace) -> int:
    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = preset(args.preset)
    try:
        result = plan(spec_from_dict(data))
    except InfeasiblePlan as exc:
        print(f"Infeasible: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0
    print(f"Laps at the flag: {result['laps_completed']}  ·  finish {clock(result['finish_time'])}"
          f"  ·  tyre sets used {result['tyre_sets_used']}")
    print(f"{'Stint':>5}  {'Driver':<12} {'Laps':>4}  {'Start':>8}  {'End':>8}  Tyres")
    for s in result["stints"]:
        state = "NEW" if s["new_tyres"] else f"used ({s['tyre_age_start']} laps)"
        tyres = f"set {s['tyre_set']} {state}"
        print(f"{s['stint']:>5}  {s['driver']:<12} {s['laps']:>4}  {clock(s['start']):>8}  "
              f"{clock(s['end']):>8}  {tyres}")
    print("\nDrive time:")
    for d in result["drivers"]:
        limits = f"min {clock(d['min_s'])}" + (f", max {clock(d['max_s'])}" if d["max_s"] else "")
        print(f"  {d['name']:<12} {clock(d['drive_s'])}   ({limits})")
    ref = result["reference_fresh_tyres_every_stop"]
    if ref:
        delta = ref["plan_minus_reference_s"]
        print(f"\nVs fresh tyres every stop (allocation ignored): {delta:+.1f}s"
              f" using {result['tyre_sets_used']} sets instead of {ref['tyre_sets_used']}")
    return 0


def _caution(args: argparse.Namespace) -> int:
    call = CautionCall(
        green_lap_s=args.green_lap, caution_lap_s=args.caution_lap,
        pit_lane_transit_s=args.pit_transit, track_equivalent_s=args.track_equivalent,
        stationary_s=args.stationary, laps_into_stint=args.laps_into_stint,
        max_stint_laps=args.max_stint_laps, race_time_left_s=args.race_left,
        caution_time_left_s=args.caution_left,
    )
    result = evaluate(call)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["verdict"])
        print(f"  green stop loss {result['green_stop_loss_s']}s, under caution "
              f"{result['caution_stop_loss_s']}s")
        print(f"  stay out: {result['stay_out']['remaining_stops']} more stops; "
              f"pit now: {result['pit_now']['remaining_stops']} incl. this one")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    race = load_csv(args.csv)
    if args.car:
        rep = analysis.car_report(race, args.car)
        if args.json:
            print(json.dumps(rep, indent=2))
            return 0
        print(f"#{rep['car']} {rep['team']} ({rep['class']})  laps {rep['laps']}  "
              f"best {laptime(rep['best_lap'])}")
        print(f"{'St':>3} {'Driver':<24} {'Laps':>4} {'Start':>8} {'Pace':>9} {'Deg/lap':>8}")
        for s in rep["stints"]:
            deg = f"{s['deg_per_lap']:+.3f}" if s["deg_per_lap"] is not None else "-"
            print(f"{s['number']:>3} {s['driver'][:24]:<24} {s['laps']:>4} "
                  f"{clock(s['start_time']):>8} {laptime(s['median_clean']):>9} {deg:>8}")
        print("Drive time:", ", ".join(f"{k} {clock(v)}" for k, v in rep["driver_time"].items()))
        return 0
    overview = analysis.race_overview(race, args.car_class)
    if args.json:
        print(json.dumps(overview, indent=2))
        return 0
    print(f"{race.name}: classes {', '.join(overview['classes'])}")
    print(f"{'Pos':>3} {'Car':>4} {'Class':<9} {'Team':<28} {'Laps':>4} {'Pace':>9} {'Stops':>5}")
    for r in overview["cars"]:
        print(f"{r['position']:>3} {r['car']:>4} {r['class'][:9]:<9} {r['team'][:28]:<28} "
              f"{r['laps']:>4} {laptime(r['median_pace']):>9} {r['stops']:>5}")
    print("\nCautions:")
    for c in overview["cautions"]:
        print(f"  {c['flag']:<4} {clock(c['start'])} -> {clock(c['end'])}")
    print("\nMedian time lost to the field per pit stop:")
    for flag, v in overview["pit_loss_by_flag"].items():
        print(f"  {flag:<6} {v['median_loss_s']:>6.1f}s  ({v['stops']} stops)")
    return 0


def parse_clock(text: str) -> float:
    """'55m', '1h05m', '3300', '1:05:00' -> seconds."""
    text = text.strip().lower()
    if ":" in text:
        total = 0.0
        for part in text.split(":"):
            total = total * 60 + float(part)
        return total
    if text.endswith(("h", "m", "s")) or "h" in text:
        total, num = 0.0, ""
        for ch in text:
            if ch.isdigit() or ch == ".":
                num += ch
            else:
                total += float(num or 0) * {"h": 3600, "m": 60, "s": 1}[ch]
                num = ""
        return total + float(num or 0)
    return float(text)


def _load_rules(args: argparse.Namespace) -> Rules:
    data: dict = {}
    if getattr(args, "rules", None):
        with open(args.rules, encoding="utf-8") as fh:
            data = json.load(fh)
        data = data.get("rules", data)
    return Rules.from_dict(data)


def _replay(args: argparse.Namespace) -> int:
    race = load_csv(args.csv)
    rules = _load_rules(args)
    state = race_state(race, parse_clock(args.at), args.car_class, args.car, rules)
    if args.json:
        print(json.dumps(state, indent=2, default=str))
        return 0
    print(f"{clock(state['t'])}  flag {state['flag']}  ·  {clock(state['race_time_left_s'])} left"
          + (f"  ·  stop loss {state['service_loss_s']:.0f}s" if state["service_loss_s"] else ""))
    print(f"{'P':>2} {'Car':>4} {'Laps':>4} {'Gap':>8} {'Stint':>5} {'Stops':>5} {'Owed':>4} "
          f"{'Net':>3} {'Net gap':>8}  Driver")
    for c in state["cars"]:
        gap = "-" if c["gap_s"] is None else f"{c['gap_s']:.1f}"
        net_gap = "-" if c.get("net_gap_s") is None else f"{c['net_gap_s']:.1f}"
        pit = " (PIT)" if c["in_pit"] else ""
        net_pos = c.get("net_position", "-")
        print(f"{c['position']:>2} {c['car']:>4} {c['laps']:>4} {gap:>8} {c['stint_laps']:>5} "
              f"{c['service_stops']:>5} {c['remaining_service']:>4} {net_pos:>3} "
              f"{net_gap:>8}  {c['driver']}{pit}")
    focus = state.get("focus")
    if focus and focus.get("drive_status"):
        ds = focus["drive_status"]
        print(f"\nDrive time #{focus['car']}: {ds['status']}, latest change "
              f"{clock(ds['latest_change_time'])}")
        for d in ds["drivers"]:
            print(f"  {d['name']:<28} {clock(d['driven_s'])}  min {clock(d['min_s'])}")
    return 0


def _events(args: argparse.Namespace) -> int:
    race = load_csv(args.csv)
    events = race_events(race, args.car_class, args.car, _load_rules(args))
    if args.json:
        print(json.dumps(events, indent=2, default=str))
        return 0
    for e in events:
        if args.car and args.only_focus and e["car"] not in (args.car, None):
            continue
        mark = {"urgent": "!!", "warn": "! ", "info": "  "}[e["severity"]]
        print(f"{clock(e['t'])} {mark} {e['text']}")
    return 0


def _debrief(args: argparse.Namespace) -> int:
    race = load_csv(args.csv)
    result = debrief(race, args.car, _load_rules(args))
    print(json.dumps(result, indent=2, default=str) if args.json else to_markdown(result))
    return 0


def _fit(args: argparse.Namespace) -> int:
    races = [load_csv(p) for p in args.csv]
    result = fit_spec(races, args.car_class) if args.spec else fit_rules(races, args.car_class)
    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stintwise", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="optimise a stint / driver / tyre plan")
    p.add_argument("--preset", default="example-lmgt3-6h", choices=sorted(PRESETS))
    p.add_argument("--spec", help="JSON file with a race spec (overrides --preset)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_plan)

    c = sub.add_parser("caution", help="pit now under FCY/SC or stay out?")
    c.add_argument("--green-lap", type=float, required=True)
    c.add_argument("--caution-lap", type=float, required=True)
    c.add_argument("--pit-transit", type=float, required=True)
    c.add_argument("--track-equivalent", type=float, required=True)
    c.add_argument("--stationary", type=float, required=True)
    c.add_argument("--laps-into-stint", type=int, required=True)
    c.add_argument("--max-stint-laps", type=int, required=True)
    c.add_argument("--race-left", type=float, required=True, help="seconds")
    c.add_argument("--caution-left", type=float, required=True, help="seconds")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=_caution)

    a = sub.add_parser("analyze", help="analyse an Al Kamel Analysis CSV")
    a.add_argument("csv")
    a.add_argument("--class", dest="car_class")
    a.add_argument("--car")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=_analyze)

    r = sub.add_parser("replay", help="pit-wall view of a race at a given race time")
    r.add_argument("csv")
    r.add_argument("--at", required=True, help="race time, e.g. 55m, 1h05m, 3300")
    r.add_argument("--class", dest="car_class")
    r.add_argument("--car", help="focus car (your car)")
    r.add_argument("--rules", help="JSON rules file (e.g. output of `stintwise fit`)")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=_replay)

    e = sub.add_parser("events", help="radio feed: cautions, stops, pit calls, warnings")
    e.add_argument("csv")
    e.add_argument("--class", dest="car_class")
    e.add_argument("--car", help="focus car (your car)")
    e.add_argument("--rules")
    e.add_argument("--only-focus", action="store_true", help="hide other cars' stops")
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=_events)

    d = sub.add_parser("debrief", help="post-race debrief for one car")
    d.add_argument("csv")
    d.add_argument("--car", required=True)
    d.add_argument("--rules")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=_debrief)

    f = sub.add_parser("fit", help="infer rules (and planner inputs) from earlier races")
    f.add_argument("csv", nargs="+")
    f.add_argument("--class", dest="car_class", required=True)
    f.add_argument("--spec", action="store_true", help="also fit planner inputs")
    f.set_defaults(func=_fit)

    m = sub.add_parser("mcp", help="run the MCP server (Claude Desktop / Claude Code)")
    m.set_defaults(func=_mcp)

    s = sub.add_parser("sample", help="write a synthetic demo race CSV")
    s.add_argument("path", nargs="?", default="data/races/synthetic-sample.csv")
    s.set_defaults(func=lambda ns: print(write_sample(ns.path)) or 0)

    v = sub.add_parser("serve", help="run the dashboard and API")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(func=_serve)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


def _mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main as run

    run()
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("stintwise.api:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
