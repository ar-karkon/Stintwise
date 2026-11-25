"""Accuracy benchmark on real races.

Every race is predicted with what the pit wall could have known: rules and costs are
learned only from EARLIER races of the same series, and in-race facts only up to the
moment of each decision. Truth comes from the race's own timing (stop costs against
neighbouring cars, positions after a stop cycle) and from the official classification.

    stintwise benchmark data/races            # prints the report
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from .analysis import class_summary, driver_label, flag_group, pit_stops
from .costs import stop_costs
from .fit import fit_rules
from .live import RaceContext, Rules, race_state
from .official import OfficialEntry, official_for
from .timing import Race, load_csv

TARGETS = {
    "parser_class_order": (">=", 0.99,
                           "Class order agrees with official results (pairs, no penalties)"),
    "parser_laps": (">=", 0.99, "Laps match the official classification"),
    "window_coverage": (">=", 0.95, "Driver-change stops inside the predicted window"),
    "stops_per_car": (">=", 0.85, "Stops per car (mandatory: exact; fuel-limited: within one)"),
    "min_drive_time": (">=", 0.90, "Minimum drive time predicted exactly"),
    "drive_time_below_min": ("<=", 0.02, "Drivers computed below the official minimum"),
    "green_cost_mae_s": ("<=", 8.0, "Green stop cost beyond pit-lane time, median abs error (s)"),
    "caution_cost_mae_s": ("<=", 30.0, "Gain of a caution stop, median abs error (s)"),
    "caution_interval_coverage": (">=", 0.75, "Caution gain inside the stated range"),
    "caution_calibration": ("<=", 0.10, "Caution call probability, calibration error"),
    "caution_call_accuracy": (">=", 0.85, "Caution calls right when the outcome was clear (>10 s)"),
    "net_pairs_mixed": (">=", 0.80, "One car stopped, one not: who is ahead after the cycle"),
    "cost_coverage": (">=", 0.90, "Service stops with a measured cost"),
}


@dataclass
class Item:
    key: tuple
    series: str
    name: str
    path: Path
    race: Race
    official: dict[str, OfficialEntry] | None


def load_dataset(folder: str | Path) -> list[Item]:
    items = []
    for path in sorted(Path(folder).glob("*.csv")):
        m = re.match(r"([a-z]+)-(\d{4})-r(\d+)-.*?(?:-race(\d+))?$", path.stem)
        if not m:
            continue
        series, year, rnd, k = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4) or 1)
        items.append(Item((series, year, rnd, k), series, path.stem, path, load_csv(path),
                          official_for(path)))
    items.sort(key=lambda i: i.key)
    return items


class Acc:
    """Collects values per metric, overall and per series."""

    def __init__(self):
        self.values: dict[str, list] = defaultdict(list)

    def add(self, metric: str, value, series: str):
        self.values[metric].append(value)
        self.values[f"{metric}@{series}"].append(value)


def _norm(name: str) -> str:
    return " ".join(name.upper().split())


def _drive_times(race: Race, car: str, exclude_pit: bool) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for lap in race.car_laps(car):
        if lap.lap_time:
            t = lap.lap_time
            if exclude_pit and lap.pit_time:
                t = max(0.0, t - lap.pit_time)
            totals[_norm(driver_label(lap))] += t
    return totals


def evaluate(items: list[Item], history_limit: int = 14) -> dict:
    acc = Acc()
    model_cache: dict = {}
    for i, target in enumerate(items):
        race = target.race
        hist = [x for x in items[:i] if x.series == target.series][-history_limit:]
        _parser_metrics(target, acc)
        costs = stop_costs(race)
        cost_by_stop = {(c.stop.car, c.stop.in_lap): c for c in costs}
        for c in costs:
            if c.stop.kind == "service":
                acc.add("cost_coverage", c.cost_s is not None, target.series)
                acc.add("neighbour_coverage", c.method == "neighbours", target.series)
        _drive_time_metrics(target, acc)
        if len(hist) < 2:
            continue
        # Cautions behave the same for every class and series of the same organiser:
        # pool every race run before this one (same weekend counts as before only if
        # it is a different series, which races earlier that day).
        caution_hist = [x.race for x in items
                        if (x.key[1], x.key[2]) < (target.key[1], target.key[2])]
        from .fit import fit_caution_model

        hist_key = len(caution_hist)
        if hist_key not in model_cache:
            model_cache[hist_key] = fit_caution_model(caution_hist)
        caution_model = model_cache[hist_key]
        for cls in race.classes:
            hist_cls = [h for h in hist if cls in h.race.classes]
            if not hist_cls:
                continue
            fitted = fit_rules([h.race for h in hist_cls], cls, duration=race.scheduled_duration,
                               officials=[h.official for h in hist_cls],
                               caution_model=caution_model)
            rules = fitted["rules"]
            if race.red_flagged:
                acc.add("races_red_flagged", True, target.series)
                _cost_metrics(target, cls, rules, cost_by_stop, acc)
                continue
            if fitted["evidence"].get("same_length_races", 0) == 0:
                # No earlier race of this length: the pit wall says so instead of guessing.
                acc.add("races_without_length_history", True, target.series)
                _cost_metrics(target, cls, rules, cost_by_stop, acc)
                continue
            _rule_metrics(target, cls, rules, acc)
            _cost_metrics(target, cls, rules, cost_by_stop, acc)
            _net_metrics(target, cls, rules, acc)
    return summarise(acc)


def _parser_metrics(target: Item, acc: Acc) -> None:
    """Pairwise order agreement with the official classification (Kendall-style).

    Post-race time penalties move single cars; counting ordered pairs keeps one
    penalised car from marking every car behind it as wrong.
    """
    off = target.official
    if not off:
        return
    race = target.race
    for cls in race.classes:
        official = sorted((e for e in off.values() if e.car_class == cls and e.classified
                           and e.position is not None and e.car in race.cars),
                          key=lambda e: e.position)
        summary = class_summary(race, cls)
        rank = {r["car"]: k for k, r in enumerate(summary)}
        finish = {r["car"]: r["finish_time"] for r in summary if r["finish_time"]}
        from .official import penalised_cars

        penalised = penalised_cars({e.car: e for e in official}, finish)
        cars = [e.car for e in official if e.car in rank]
        for a in range(len(cars)):
            for b in range(a + 1, len(cars)):
                agree = rank[cars[a]] < rank[cars[b]]
                acc.add("parser_class_order_all", agree, target.series)
                if cars[a] not in penalised and cars[b] not in penalised:
                    acc.add("parser_class_order", agree, target.series)
        for e in official:
            mine = race.car_laps(e.car)[-1].lap
            acc.add("parser_laps", e.laps is None or mine == e.laps, target.series)


def _drive_time_metrics(target: Item, acc: Acc) -> None:
    off = target.official
    if not off:
        return
    race = target.race
    for e in off.values():
        if not e.classified or e.car not in race.cars:
            continue
        raw = _drive_times(race, e.car, exclude_pit=False)
        net = _drive_times(race, e.car, exclude_pit=True)
        for d in e.drivers:
            if not d.min_drive_s or _norm(d.name) not in raw:
                continue
            acc.add("drive_time_below_min", net[_norm(d.name)] < d.min_drive_s - 1, target.series)
            acc.add("drive_time_below_min_raw", raw[_norm(d.name)] < d.min_drive_s - 1,
                    target.series)


def _rule_metrics(target: Item, cls: str, rules: dict, acc: Acc) -> None:
    import math

    race = target.race
    stops = pit_stops(race, cls)
    opened = rules.get("window_open_s")
    service = defaultdict(int)
    counted = defaultdict(int)
    for s in stops:
        if s.kind == "service":
            service[s.car] += 1
            if opened is None or s.race_time >= opened - 60:
                counted[s.car] += 1
    off = target.official or {}
    for car in race.cars_in_class(cls):
        e = off.get(car)
        if off and (e is None or not e.classified):
            continue
        if rules.get("required_service_stops") is not None:
            acc.add("stops_per_car", counted[car] == rules["required_service_stops"], target.series)
        elif rules.get("max_stint_s"):
            pred = max(0, math.ceil(rules["duration_s"] / rules["max_stint_s"]) - 1)
            acc.add("stops_per_car", abs(service[car] - pred) <= 1, target.series)
            acc.add("stops_per_car_exact", service[car] == pred, target.series)
    if rules.get("window_open_s") is not None:
        lo, hi = rules["window_open_s"] - 60, rules["window_close_s"] + 60
        for s in stops:
            if s.kind == "service" and s.driver_change:
                acc.add("window_coverage", lo <= s.race_time <= hi, target.series)
    if off and rules.get("min_drive_s") is not None:
        from .official import min_drive_time

        truth = min_drive_time({k: v for k, v in off.items() if v.car_class == cls})
        if truth:
            acc.add("min_drive_time", abs(truth - rules["min_drive_s"]) < 1, target.series)


def predicted_costs(race: Race, cls: str, rules: dict, t: float, cost_by_stop: dict) -> dict:
    """Green and caution stop cost the pit wall would predict at race time t."""
    known_p = [s.pit_time for s in pit_stops(race, cls) if s.kind == "service" and s.pit_time
               and s.exit_time is not None and s.exit_time <= t]
    p_hat = median(known_p) if len(known_p) >= 2 else rules.get("pit_lane_s")
    extra = rules.get("cost_extra_s") or {}
    out = {}
    if p_hat is not None:
        for flag in ("GREEN", "SC", "FCY"):
            if flag in extra:
                out[flag] = p_hat + extra[flag]
    return out


def _cost_metrics(target: Item, cls: str, rules: dict, cost_by_stop: dict, acc: Acc) -> None:
    """Stop cost beyond the pit-lane time (which the team plans), and the caution call.

    For a stop under a caution the prediction uses only what was known at the in-lap:
    how long the caution had been out, and stops made at that point of earlier
    cautions. Repairs are not scored (their length is not a strategy choice).
    """
    from .analysis import caution_periods
    from .caution_model import THRESHOLD_S, assess

    race = target.race
    extra = rules.get("cost_extra_s") or {}
    model = rules.get("caution_model") or {}
    periods = caution_periods(race)
    normal = [s.pit_time for s in pit_stops(race, None) if s.kind == "service" and s.pit_time]
    limit = 1.3 * median(normal) if normal else float("inf")
    for s in pit_stops(race, cls):
        c = cost_by_stop.get((s.car, s.in_lap))
        if (s.kind != "service" or c is None or c.method != "neighbours" or c.cost_s is None
                or not s.pit_time or c.refs < 2 or s.pit_time > limit):
            continue
        g = flag_group(s.flag)
        if g == "GREEN":
            if "GREEN" in extra:
                acc.add("green_cost_err", c.cost_s - (s.pit_time + extra["GREEN"]), target.series)
            continue
        p = next((p for p in periods if p["start"] - 1 <= s.race_time <= p["end"] + 30), None)
        entry = model.get(g)
        if not p or not entry or "GREEN" not in extra:
            continue
        a = assess(entry, s.race_time - p["start"], s.pit_time)
        if a is None:
            continue
        real_gain = extra["GREEN"] - (c.cost_s - s.pit_time)
        acc.add("caution_cost_err", real_gain - a["gain_s"], target.series)
        acc.add("caution_interval_coverage", a["range_s"][0] <= real_gain <= a["range_s"][1],
                target.series)
        won = real_gain > THRESHOLD_S
        acc.add("caution_calibration", (a["p_gain"], won), target.series)
        call_box = a["p_gain"] >= 0.5
        acc.add("caution_call_strict", call_box == won, target.series)
        if abs(real_gain - THRESHOLD_S) >= 10:
            acc.add("caution_call_accuracy", call_box == won, target.series)


def _net_metrics(target: Item, cls: str, rules: dict, acc: Acc) -> None:
    race = target.race
    if not rules.get("required_service_stops"):
        return
    stops = sorted((s for s in pit_stops(race, cls) if s.kind == "service" and s.exit_time),
                   key=lambda s: s.race_time)
    if len(stops) < 4:
        return
    if rules.get("window_open_s") is not None:
        # One mandatory stop: the cycle is the stops made inside the window.
        lo, hi = rules["window_open_s"] - 60, rules["window_close_s"] + 60
        stops = [s for s in stops if lo <= s.race_time <= hi]
        if len(stops) < 4:
            return
    # stop cycles: groups of stops separated by more than 15 minutes
    cycles, cur = [], [stops[0]]
    for s in stops[1:]:
        if s.race_time - cur[-1].race_time > 900:
            cycles.append(cur)
            cur = []
        cur.append(s)
    cycles.append(cur)
    green_cost = rules.get("service_loss_s")
    live_rules = Rules.from_dict({k: v for k, v in rules.items()
                                  if k in Rules.__dataclass_fields__})
    ctx = RaceContext(race, cls, live_rules)
    for cyc in cycles:
        if len(cyc) < 3:
            continue
        t_mid = cyc[len(cyc) // 2].race_time + 1
        t_after = max(s.exit_time for s in cyc) + 300
        if t_after > race.duration:
            continue
        mid = race_state(race, t_mid, cls, None, live_rules, ctx)
        after = race_state(race, t_after, cls, None, live_rules, ctx)
        pos_after = {c["car"]: c["position"] for c in after["cars"]}
        cycle_cars = {s.car for s in cyc}
        cars = [c for c in mid["cars"] if c["car"] in pos_after and c["car"] in cycle_cars
                and c.get("net_position") is not None]
        if green_cost is None:
            continue
        for c in cars:
            acc.add("net_position_abs", abs(c["net_position"] - pos_after[c["car"]]), target.series)
            acc.add("naive_position_abs", abs(c["position"] - pos_after[c["car"]]), target.series)
        for i, a in enumerate(cars):
            for b in cars[i + 1:]:
                truth = pos_after[a["car"]] < pos_after[b["car"]]
                net_says = a["net_position"] < b["net_position"]
                naive_says = a["position"] < b["position"]
                kind = "mixed" if a["remaining_service"] != b["remaining_service"] else "same"
                acc.add(f"net_pairs_{kind}", net_says == truth, target.series)
                acc.add(f"naive_pairs_{kind}", naive_says == truth, target.series)


def _calibration_error(pairs: list) -> float:
    """Expected calibration error over probability bins of width 0.2."""
    bins: dict[int, list] = defaultdict(list)
    for p, won in pairs:
        bins[min(4, int(p * 5))].append((p, won))
    total = len(pairs)
    return sum(len(b) / total * abs(sum(p for p, _ in b) / len(b) - sum(1 for _, w in b if w)
                                    / len(b)) for b in bins.values())


def _stat(metric: str, values: list):
    if not values:
        return None
    if metric.endswith("_err"):
        return median(abs(v) for v in values)
    if metric == "caution_calibration":
        return _calibration_error(values)
    if metric.endswith("_abs"):
        return sum(values) / len(values)
    return sum(1 for v in values if v) / len(values)


def summarise(acc: Acc) -> dict:
    out = {}
    for metric, values in acc.values.items():
        base = metric.split("@")[0]
        name = {"green_cost_err": "green_cost_mae_s", "caution_cost_err": "caution_cost_mae_s"}.get(
            base, base)
        key = name + (metric[len(base):] if "@" in metric else "")
        out[key] = {"value": _stat(base, values), "n": len(values)}
    for name, (op, goal, label) in TARGETS.items():
        if name in out:
            v = out[name]["value"]
            out[name]["target"] = f"{op} {goal}"
            out[name]["label"] = label
            out[name]["met"] = v is not None and (v >= goal if op == ">=" else v <= goal)
    return out


def report(result: dict) -> str:
    lines = ["| Metric | Result | Target | n | Met |", "|---|---:|---:|---:|:---:|"]
    for name, (op, goal, label) in TARGETS.items():
        r = result.get(name)
        if not r:
            lines.append(f"| {label} | - | {op} {goal} | 0 | - |")
            continue
        v = r["value"]
        shown = f"{v:.1f}" if name.endswith("_s") else (
            f"{v:.3f}" if name == "caution_calibration" else f"{100 * v:.1f}%")
        goal_s = f"{goal:.0f} s" if name.endswith("_s") else (
            f"{goal:.2f}" if name == "caution_calibration" else f"{100 * goal:.0f}%")
        lines.append(f"| {label} | {shown} | {op} {goal_s} | {r['n']} | "
                     f"{'yes' if r['met'] else 'NO'} |")
    extra = [k for k in ("parser_class_order_all", "caution_call_strict", "naive_pairs_mixed",
                         "net_pairs_same", "naive_pairs_same",
                         "net_position_abs", "naive_position_abs",
                         "stops_per_car_exact", "neighbour_coverage", "drive_time_below_min_raw")
             if k in result]
    if extra:
        lines += ["", "Reference values:"]
        for k in extra:
            v = result[k]["value"]
            shown = f"{v:.2f}" if k.endswith("_abs") else f"{100 * v:.1f}%"
            lines.append(f"- {k}: {shown} (n={result[k]['n']})")
    return "\n".join(lines)
