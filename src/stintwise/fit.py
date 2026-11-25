"""Learn race rules and planner inputs from past races of the same championship.

A small team rarely has the regulations' numbers at hand on the pit wall.
Timing files from earlier rounds show them: how many service stops a car
makes, when the driver-change window opens and closes, how much a stop costs
under green and under caution, and how long a stint can run.
"""
from __future__ import annotations

from collections import Counter
from statistics import median

from .analysis import flag_group, pit_stops, stints
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


def fit_rules(races: list[Race], car_class: str) -> dict:
    """Rules a pit wall can use live, inferred from earlier races."""
    service_counts: list[int] = []
    change_times: list[float] = []
    losses: dict[str, list[float]] = {}
    pit_times: list[float] = []
    stint_laps: list[int] = []
    durations: list[float] = []
    for race in races:
        if car_class not in race.classes:
            continue
        durations.append(race.scheduled_duration)
        stops = pit_stops(race, car_class)
        per_car = Counter(s.car for s in stops if s.kind == "service")
        finishers = race.cars_in_class(car_class)
        service_counts += [per_car.get(car, 0) for car in finishers]
        for s in stops:
            if s.kind != "service":
                continue
            if s.driver_change:
                change_times.append(s.race_time)
            if s.pit_time:
                pit_times.append(s.pit_time)
            if s.loss_vs_field is not None:
                losses.setdefault(flag_group(s.flag), []).append(s.loss_vs_field)
        for car in finishers:
            stint_laps += [st.laps for st in stints(race, car)]
    if not durations:
        raise ValueError(f"Class {car_class!r} not found in the given races")
    required = Counter(service_counts).most_common(1)[0][0] if service_counts else None
    rules: dict = {
        "duration_s": Counter(durations).most_common(1)[0][0],
        "required_service_stops": required,
        "service_loss_s": round(median(losses["GREEN"]), 1) if losses.get("GREEN") else None,
    }
    cautions = {k: round(median(v), 1) for k, v in losses.items() if k != "GREEN" and len(v) >= 3}
    if cautions:
        rules["caution_loss_s"] = cautions
    window = _robust_range(change_times) if required == 1 else None
    if window:
        rules["window_open_s"] = round(window[0], 0)
        rules["window_close_s"] = round(window[1], 0)
    evidence = {
        "races": len(durations),
        "service_stops_per_car": dict(Counter(service_counts)),
        "median_service_pit_lane_s": round(median(pit_times), 1) if pit_times else None,
        "median_loss_by_flag_s": {k: round(median(v), 1) for k, v in losses.items()},
        "stops_by_flag": {k: len(v) for k, v in losses.items()},
        "longest_stint_laps": max(stint_laps) if stint_laps else None,
        "driver_change_stops": len(change_times),
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
