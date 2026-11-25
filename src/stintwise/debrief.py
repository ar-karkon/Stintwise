"""Post-race debrief for one car: where the time went, in numbers.

Compares the car with its class in the same race: pace per driver against
the class front-runners, every pit stop against the class median stop, and
caution periods the car could have used for its stop.
"""
from __future__ import annotations

from statistics import median

from .analysis import caution_periods, class_summary, flag_group, pit_stops, stints
from .fit import _robust_range
from .live import Rules
from .timing import Race


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _lap(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"


def debrief(race: Race, car: str, rules: Rules | dict | None = None) -> dict:
    if not isinstance(rules, Rules):
        rules = Rules.from_dict(rules)
    info = race.car_info(car)
    cls = info["class"]
    table = class_summary(race, cls)
    row = next(r for r in table if r["car"] == car)
    winner = table[0]

    # --- pace ------------------------------------------------------------------
    # Every driver of the class is ranked on median clean green pace; a driver's
    # pace loss is counted against the class median driver.
    class_drivers: dict[tuple[str, str], list[float]] = {}
    for other in race.cars_in_class(cls):
        for st in stints(race, other):
            if st.median_clean:
                class_drivers.setdefault((other, st.driver), []).extend(
                    [st.median_clean] * st.clean_laps)
    ranked = sorted(median(v) for v in class_drivers.values() if v)
    benchmark = median(ranked) if ranked else None
    fastest = ranked[0] if ranked else None
    drivers: dict[str, dict] = {}
    for st in stints(race, car):
        d = drivers.setdefault(st.driver, {"name": st.driver, "laps": 0, "clean_laps": 0,
                                           "drive_s": 0.0})
        d["laps"] += st.laps
        d["clean_laps"] += st.clean_laps
        d["drive_s"] += st.duration
    pace_loss = 0.0
    for d in drivers.values():
        laps = class_drivers.get((car, d["name"]), [])
        d["median_pace"] = median(laps) if laps else None
        d["class_rank"] = (ranked.index(d["median_pace"]) + 1) if d["median_pace"] else None
        d["class_drivers"] = len(ranked)
        d["delta_to_class_median_s"] = (
            round(d["median_pace"] - benchmark, 3) if d["median_pace"] and benchmark else None
        )
        d["delta_to_fastest_s"] = (
            round(d["median_pace"] - fastest, 3) if d["median_pace"] and fastest else None
        )
        d["pace_loss_s"] = round(max(0.0, d["delta_to_class_median_s"] or 0.0)
                                 * d["clean_laps"], 1)
        pace_loss += d["pace_loss_s"]

    # --- pit stops -------------------------------------------------------------
    class_stops = pit_stops(race, cls)
    green_service = [s.loss_vs_field for s in class_stops if s.kind == "service"
                     and flag_group(s.flag) == "GREEN" and s.loss_vs_field is not None]
    ref_green = median(green_service) if green_service else None
    by_flag: dict[str, list[float]] = {}
    for s in class_stops:
        if s.kind == "service" and s.loss_vs_field is not None:
            by_flag.setdefault(flag_group(s.flag), []).append(s.loss_vs_field)
    ref_by_flag = {k: median(v) for k, v in by_flag.items()}
    stops = []
    pit_excess = 0.0
    other_stop_loss = 0.0
    for s in class_stops:
        if s.car != car:
            continue
        ref = ref_by_flag.get(flag_group(s.flag)) if s.kind == "service" else None
        excess = None
        if ref is not None and s.loss_vs_field is not None:
            excess = round(s.loss_vs_field - ref, 1)
            pit_excess += max(0.0, excess)
        elif s.kind != "service" and s.loss_vs_field is not None:
            other_stop_loss += s.loss_vs_field
        stops.append({"lap": s.in_lap, "race_time": s.race_time, "kind": s.kind,
                      "flag": s.flag, "pit_time": s.pit_time, "loss_s": s.loss_vs_field,
                      "class_median_s": ref, "excess_s": excess,
                      "driver_change": s.driver_change})

    # --- cautions the car could have used ---------------------------------------
    window = None
    if rules.window_open_s is not None and rules.window_close_s is not None:
        window = (rules.window_open_s, rules.window_close_s)
    else:
        window = _robust_range([s.race_time for s in class_stops
                                if s.kind == "service" and s.driver_change])
    own_service = [s for s in stops if s["kind"] == "service"]
    first_service = own_service[0] if own_service else None
    missed = []
    used = []
    for p in caution_periods(race):
        inside = window is None or (window[0] - 60 <= p["start"] <= window[1])
        pitted = [s for s in own_service if p["start"] - 30 <= s["race_time"] <= p["end"] + 30]
        if pitted:
            used.append({**p, "lap": pitted[0]["lap"]})
            continue
        owed = first_service is None or first_service["race_time"] > p["start"]
        flag_ref = ref_by_flag.get(p["flag"])
        if inside and owed and first_service and flag_group(first_service["flag"]) == "GREEN" \
                and flag_ref is not None and ref_green is not None:
            missed.append({**p, "potential_gain_s": round(ref_green - flag_ref, 1)})
    caution_gain = max((m["potential_gain_s"] for m in missed), default=0.0)
    near_misses = []
    for p in caution_periods(race):
        for s in own_service:
            gap = p["start"] - s["race_time"]
            if flag_group(s["flag"]) == "GREEN" and 0 < gap <= 120:
                near_misses.append({"flag": p["flag"], "after_s": round(gap, 1),
                                    "lap": s["lap"]})

    # --- findings ----------------------------------------------------------------------
    findings = []
    if winner["car"] != car:
        if winner["laps"] == row["laps"] and winner["finish_time"] and row["finish_time"]:
            findings.append(f"Finished P{row['position']} in {cls}, "
                            f"{row['finish_time'] - winner['finish_time']:.1f}s behind the winner")
        else:
            findings.append(f"Finished P{row['position']} in {cls}, "
                            f"{winner['laps'] - row['laps']} lap(s) behind the winner")
    else:
        findings.append(f"Won {cls}")
    for d in sorted(drivers.values(), key=lambda d: -(d.get("pace_loss_s") or 0)):
        if d.get("delta_to_class_median_s") is not None:
            text = (f"{d['name']}: {_lap(d['median_pace'])} median pace, "
                    f"{d['class_rank']}/{d['class_drivers']} in class, "
                    f"{d['delta_to_class_median_s']:+.2f}s/lap vs the class median driver")
            if d["pace_loss_s"] > 0:
                text += f" ({d['pace_loss_s']:.0f}s over {d['clean_laps']} clean laps)"
            if d["clean_laps"] < 5:
                text += " [small sample: few clean green laps]"
            findings.append(text)
    for s in stops:
        if s["excess_s"] is not None and abs(s["excess_s"]) >= 3:
            word = "lost" if s["excess_s"] > 0 else "gained"
            findings.append(f"Lap {s['lap']} {s['kind']} stop under {s['flag']}: {word} "
                            f"{abs(s['excess_s']):.0f}s vs the class median stop")
    for m in missed:
        findings.append(f"{m['flag']} at {_clock(m['start'])} came while the stop was still owed: "
                        f"stopping then could have saved ~{m['potential_gain_s']:.0f}s")
    for n in near_misses:
        findings.append(f"Unlucky: {n['flag']} came {n['after_s']:.0f}s after the lap "
                        f"{n['lap']} stop under green")
    if other_stop_loss > 0:
        findings.append(f"Extra (short/garage) stops cost {other_stop_loss:.0f}s")

    return {
        "car": car, "class": cls, "team": info["team"], "race": race.name,
        "position": row["position"], "laps": row["laps"], "finish_time": row["finish_time"],
        "winner": {"car": winner["car"], "team": winner["team"], "laps": winner["laps"],
                   "finish_time": winner["finish_time"]},
        "class_median_driver_pace": benchmark,
        "class_fastest_driver_pace": fastest,
        "drivers": list(drivers.values()),
        "stops": stops,
        "class_stop_loss_by_flag": {k: round(v, 1) for k, v in ref_by_flag.items()},
        "pit_window": window,
        "cautions_used": used,
        "cautions_missed": missed,
        "near_misses": near_misses,
        "time_accounting_s": {
            "pace_vs_class_median_driver": round(pace_loss, 1),
            "pit_stops_vs_class_median": round(pit_excess, 1),
            "extra_stops": round(other_stop_loss, 1),
            "best_missed_caution": round(caution_gain, 1),
        },
        "findings": findings,
    }


def to_markdown(d: dict) -> str:
    lines = [
        f"# Debrief: #{d['car']} {d['team']} ({d['class']})",
        f"*{d['race']}* · P{d['position']} · {d['laps']} laps · finish {_clock(d['finish_time'])}",
        "",
        "## Key findings",
        *[f"- {f}" for f in d["findings"]],
        "",
        "## Where the time went",
        "| Item | Seconds |",
        "|---|---:|",
        *[f"| {k.replace('_', ' ')} | {v:.1f} |" for k, v in d["time_accounting_s"].items()],
        "",
        "## Drivers",
        "| Driver | Laps | Clean laps | Median | Class rank | Δ class median | Pace loss |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for dr in d["drivers"]:
        delta = dr.get("delta_to_class_median_s")
        lines.append(f"| {dr['name']} | {dr['laps']} | {dr['clean_laps']} | "
                     f"{_lap(dr.get('median_pace'))} | {dr['class_rank'] or '-'}/"
                     f"{dr['class_drivers']} | "
                     f"{'-' if delta is None else f'{delta:+.2f}s'} | "
                     f"{dr.get('pace_loss_s', 0):.0f}s |")
    lines += ["", "## Pit stops",
              "| Lap | Kind | Flag | Pit lane | Loss vs field | Class median | Δ |",
              "|---:|---|---|---:|---:|---:|---:|"]
    for s in d["stops"]:
        def f(v):
            return "-" if v is None else f"{v:.1f}s"
        lines.append(f"| {s['lap']} | {s['kind']} | {s['flag']} | {f(s['pit_time'])} | "
                     f"{f(s['loss_s'])} | {f(s['class_median_s'])} | {f(s['excess_s'])} |")
    lines += ["", "Computed from official lap timing only. Pace = median of clean green laps; "
              "stop loss = in-lap + out-lap minus the class median lap under the same flag."]
    return "\n".join(lines) + "\n"
