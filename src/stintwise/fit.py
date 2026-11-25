"""Learn race rules and planner inputs from past races of the same championship.

A small team rarely has the regulations' numbers at hand on the pit wall.
Timing files from earlier rounds show them: how many service stops a car
makes, when the driver-change window opens and closes, how much a stop costs
under green and under caution, and how long a stint can run.
"""
from __future__ import annotations

from collections import Counter
from statistics import median

from .analysis import caution_periods, flag_group, pit_stops, stints
from .timing import Race


def _quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def _robust_range(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 4:
        return None
    q1, q3 = _quantile(values, 0.25), _quantile(values, 0.75)
    spread = q3 - q1
    kept = [v for v in values if q1 - 1.5 * spread <= v <= q3 + 1.5 * spread]
    return min(kept), max(kept)


def _same_length(races: list[Race], duration: float | None) -> list[Race]:
    if duration is None:
        return races
    same = [r for r in races if abs(r.scheduled_duration - duration) <= 300]
    return same or races


def fit_caution_model(races: list[Race], green_extra: float = 5.5) -> dict:
    """Past stops under FCY / Safety Car: how long into the caution they were made and
    what share of the pit-lane time they saved against staying out for a green stop.

    Pooled over every class (the whole field runs at the same speed under a caution).
    Repairs (pit-lane time over 1.3 x the race's median service stop) are left out.
    The live call uses the stops made at a similar point of a caution (see
    :mod:`stintwise.caution_model`).
    """
    from .costs import stop_costs

    samples: dict[str, list[list[float]]] = {}
    durations: dict[str, list[float]] = {}
    for race_no, race in enumerate(races):
        periods = caution_periods(race)
        for p in periods:
            durations.setdefault(p["flag"], []).append(p["duration"])
        costs = stop_costs(race)
        normal = [c.stop.pit_time for c in costs if c.stop.kind == "service" and c.stop.pit_time]
        if not normal:
            continue
        limit = 1.3 * median(normal)
        for c in costs:
            st = c.stop
            g = flag_group(st.flag)
            if (st.kind != "service" or g == "GREEN" or c.method != "neighbours"
                    or not st.pit_time or st.pit_time > limit or c.cost_s is None):
                continue
            p = next((p for p in periods if p["start"] - 1 <= st.race_time <= p["end"] + 30), None)
            if p:
                gain_frac = (green_extra - (c.cost_s - st.pit_time)) / st.pit_time
                samples.setdefault(g, []).append([round(st.race_time - p["start"], 1),
                                                  round(gain_frac, 3), race_no])
    from .caution_model import neighbours

    model = {}
    for flag, rows in samples.items():
        if len(rows) < 5:
            continue
        # Conformal range: how far the estimate was from the outcome on races it had
        # not seen (leave one race out).
        residuals = []
        for row in rows:
            others = {"samples": [r for r in rows if r[2] != row[2]]}
            near = [r[1] for r in neighbours(others, row[0])]
            if len(near) >= 5:
                residuals.append(abs(row[1] - median(near)))
        entry = {"samples": sorted([r[0], r[1]] for r in rows),
                 "periods": len(durations.get(flag, []))}
        if len(residuals) >= 10:
            entry["residual_q80"] = round(_quantile(residuals, 0.8), 3)
            entry["residual_q90"] = round(_quantile(residuals, 0.9), 3)
        model[flag] = entry
    return model


def fit_rules(races: list[Race], car_class: str, duration: float | None = None,
              officials: list | None = None, caution_races: list[Race] | None = None,
              caution_model: dict | None = None) -> dict:
    """Rules a pit wall can use live, inferred from earlier races.

    ``duration``: length of the race the rules are for; stop counts, the window and the
    minimum drive time are then taken from races of the same length (the window is
    scaled from other lengths if none match). ``officials``: classifications of the
    same races (see :mod:`stintwise.official`), for the minimum drive time.
    """
    from .costs import stop_costs
    from .official import min_drive_time

    # Red-flagged races are left out: the stoppage disturbs stop timing and race length.
    pairs = [(r, (officials or [None] * len(races))[k]) for k, r in enumerate(races)
             if car_class in r.classes and not r.red_flagged]
    if not pairs:
        pairs = [(r, (officials or [None] * len(races))[k]) for k, r in enumerate(races)
                 if car_class in r.classes]
    if not pairs:
        raise ValueError(f"Class {car_class!r} not found in the given races")
    durations = [r.scheduled_duration for r, _ in pairs]
    target = duration or Counter(durations).most_common(1)[0][0]
    same = [(r, o) for r, o in pairs if abs(r.scheduled_duration - target) <= 300] or pairs

    service_counts: list[int] = []
    change_fracs: list[float] = []
    stint_laps: list[int] = []
    stint_secs: list[float] = []
    pit_times: list[float] = []
    extras: dict[str, list[float]] = {}
    losses: dict[str, list[float]] = {}
    for race, _ in pairs:
        same_len = abs(race.scheduled_duration - target) <= 300
        stops = pit_stops(race, car_class)
        per_car = Counter(s.car for s in stops if s.kind == "service")
        max_laps = max(race.car_laps(c)[-1].lap for c in race.cars_in_class(car_class))
        finishers = [c for c in race.cars_in_class(car_class)
                     if race.car_laps(c)[-1].lap >= 0.9 * max_laps]
        if same_len or not any(abs(r.scheduled_duration - target) <= 300 for r, _ in pairs):
            service_counts += [per_car.get(car, 0) for car in finishers]
        for s in stops:
            if s.kind == "service" and s.driver_change:
                change_fracs.append(s.race_time / race.scheduled_duration)
            if s.kind == "service" and s.pit_time:
                pit_times.append(s.pit_time)
        for c in stop_costs(race, car_class):
            st = c.stop
            if st.kind != "service" or c.cost_s is None:
                continue
            g = flag_group(st.flag)
            losses.setdefault(g, []).append(c.cost_s)
            if c.method == "neighbours" and c.refs >= 2 and st.pit_time:
                extras.setdefault(g, []).append(c.cost_s - st.pit_time)
        for car in finishers:
            car_stints = stints(race, car)
            stint_laps += [x.laps for x in car_stints]
            stint_secs += [x.duration for x in car_stints if x.ended_in_pit and x.duration > 600]
    required = None
    if service_counts:
        mode, count = Counter(service_counts).most_common(1)[0]
        # A fixed stop count only when most cars agree (mandatory stop); otherwise the
        # number of stops follows fuel, which ``max_stint_s`` models.
        if count >= 0.7 * len(service_counts):
            required = mode
    pit_lane = median(pit_times) if pit_times else None
    extra = {k: median(v) for k, v in extras.items() if len(v) >= 3}
    spread = {k: [round(_quantile([x - extra[k] for x in v], 0.2), 1),
                  round(_quantile([x - extra[k] for x in v], 0.8), 1)]
              for k, v in extras.items() if k in extra}
    rules: dict = {
        "duration_s": target,
        "required_service_stops": required,
        "pit_lane_s": round(pit_lane, 1) if pit_lane else None,
        "service_loss_s": (round(pit_lane + extra["GREEN"], 1) if pit_lane and "GREEN" in extra
                           else (round(median(losses["GREEN"]), 1) if losses.get("GREEN")
                                 else None)),
        "cost_extra_s": {k: round(v, 1) for k, v in extra.items()},
        "cost_spread_s": spread,
    }
    model = caution_model if caution_model is not None else fit_caution_model(
        caution_races if caution_races is not None else [r for r, _ in pairs])
    if model:
        rules["caution_model"] = model
    cautions = {k: round(pit_lane + v, 1) for k, v in extra.items() if k != "GREEN" and pit_lane}
    if cautions:
        rules["caution_loss_s"] = cautions
    if required is None and len(stint_secs) >= 5:
        rules["max_stint_s"] = round(_quantile(stint_secs, 0.9), 0)
    window = _robust_range(change_fracs) if required == 1 else None
    if window:
        rules["window_open_s"] = round(window[0] * target, 0)
        rules["window_close_s"] = round(window[1] * target, 0)
    mins = [min_drive_time({k: v for k, v in o.items() if v.car_class == car_class})
            for r, o in same if o]
    mins = [m for m in mins if m]
    if mins:
        rules["min_drive_s"] = Counter(mins).most_common(1)[0][0]
    else:
        # No race of this length yet: scale the published minimum by race length.
        fracs = []
        for r, o in pairs:
            m = (min_drive_time({k: v for k, v in o.items() if v.car_class == car_class})
                 if o else None)
            if m:
                fracs.append(m / r.scheduled_duration)
        if fracs:
            rules["min_drive_s"] = round(median(fracs) * target / 300) * 300
    evidence = {
        "races": len(pairs),
        "same_length_races": sum(1 for r, _ in pairs if abs(r.scheduled_duration - target) <= 300),
        "service_stops_per_car": dict(Counter(service_counts)),
        "median_service_pit_lane_s": round(pit_lane, 1) if pit_lane else None,
        "median_loss_by_flag_s": {k: round(median(v), 1) for k, v in losses.items()},
        "stops_by_flag": {k: len(v) for k, v in losses.items()},
        "neighbour_measured_by_flag": {k: len(v) for k, v in extras.items()},
        "longest_stint_laps": max(stint_laps) if stint_laps else None,
        "driver_change_stops": len(change_fracs),
    }
    return {"class": car_class, "rules": rules, "evidence": evidence}


def fit_spec(races: list[Race], car_class: str) -> dict:
    """Planner inputs (see :mod:`stintwise.planner`) fitted to past races.

    Rules come from all races; pace and tyre degradation from the most recent
    race, since they depend on the circuit.
    """
    fitted = fit_rules(races, car_class)
    # Pace and degradation are circuit specific: take them from the most recent race.
    race = next((r for r in reversed(races) if car_class in r.classes), None)
    car_paces: list[float] = []
    degs: list[float] = []
    for car in race.cars_in_class(car_class):
        st = stints(race, car)
        p = [s.median_clean for s in st if s.median_clean]
        if p:
            car_paces.append(median(p))
        degs += [s.deg_per_lap for s in st if s.deg_per_lap is not None]
    car_paces.sort()
    paces = car_paces[: max(1, len(car_paces) // 2)]  # front half of the class
    rules = fitted["rules"]
    ev = fitted["evidence"]
    stops = rules.get("required_service_stops") or 1
    longest = ev.get("longest_stint_laps")
    base = median(paces) if paces else 120.0
    duration = rules["duration_s"]
    stint_cap = longest or int(duration / base)
    spec = {
        "duration_s": duration,
        "base_lap_s": round(base, 3),
        "max_stint_laps": int(stint_cap),
        "max_consecutive_stints": max(1, stops),
        "drivers": [
            {"name": "Driver A", "pace_offset_s": 0.0},
            {"name": "Driver B", "pace_offset_s": 0.0},
        ],
        "pit": {
            "lane_loss_s": rules.get("service_loss_s") or 60.0,
            "refuel_base_s": 0.0,
            "refuel_per_lap_s": 0.0,
            "tyre_change_s": 0.0,
            "driver_change_s": 0.0,
        },
        "tyres": {
            "deg_s_per_lap": round(max(0.0, median(degs)), 4) if degs else 0.03,
            "deg_quad_s": 0.0,
            "warmup_s": 1.0,
        },
    }
    return {**fitted, "pace_from": race.name, "spec": spec}
