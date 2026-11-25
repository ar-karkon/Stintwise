"""What a pit stop really cost: time lost against nearby cars that did not stop.

For a stop on in-lap ``n`` the window runs from lap ``n - 1`` to the out-lap ``n + 1``;
for a stop made under a caution it is extended to the first lap completed after the
caution ends, so the whole Safety Car queue effect is included. The reference is up to
six cars that were on the same lap within two minutes at the start of the window and
made no stop in it, same class first. Cost = our time over the window minus the median
reference time.

When no such reference exists (typically when the whole field stops under the same
caution) the in/out-lap method of :func:`stintwise.analysis.pit_stops` is used, with
laps of every class as reference under a caution, since the whole field runs at the
same speed behind a Safety Car or under FCY.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from .analysis import FieldPace, PitStop, caution_periods, flag_group, pit_stops
from .timing import Race

REF_WINDOW_S = 120.0
MAX_REFS = 6


@dataclass(frozen=True)
class StopCost:
    stop: PitStop
    cost_s: float | None
    method: str  # "neighbours" | "field" | "none"
    refs: int
    known_at: float  # race time at which this cost can be known


def stop_costs(race: Race, car_class: str | None = None) -> list[StopCost]:
    if ("stop_costs", None) not in race.cache:
        race.cache[("stop_costs", None)] = _stop_costs(race)
    every = race.cache[("stop_costs", None)]
    return [c for c in every if not car_class or c.stop.car_class == car_class]


def _stop_costs(race: Race) -> list[StopCost]:
    all_stops = pit_stops(race, None)
    by_car: dict[str, list[PitStop]] = defaultdict(list)
    for s in all_stops:
        by_car[s.car].append(s)
    laps_by_car = {c: {lap.lap: lap for lap in race.car_laps(c)} for c in race.cars}
    cautions = caution_periods(race)
    field_all = FieldPace(race, None)
    results = []
    for s in all_stops:
        mine = laps_by_car[s.car]
        period = next((p for p in cautions
                       if p["start"] - 1 <= s.race_time <= p["end"] + 30), None)
        n_a, n_b = s.in_lap - 1, s.in_lap + 1
        if period and flag_group(s.flag) != "GREEN":
            after = [lap.lap for lap in mine.values()
                     if lap.elapsed and lap.elapsed > period["end"]]
            if after:
                n_b = max(n_b, min(after))
        cost, method, nrefs, known = None, "none", 0, s.exit_time or s.race_time
        if n_a in mine and n_b in mine and mine[n_a].elapsed and mine[n_b].elapsed:
            ta, tb = mine[n_a].elapsed, mine[n_b].elapsed
            refs = []
            for other, laps in laps_by_car.items():
                if other == s.car or n_a not in laps or n_b not in laps:
                    continue
                la, lb = laps[n_a], laps[n_b]
                if (la.elapsed is None or lb.elapsed is None
                        or abs(la.elapsed - ta) > REF_WINDOW_S):
                    continue
                if any(n_a <= x.in_lap <= n_b for x in by_car[other]):
                    continue
                refs.append((la.car_class != s.car_class, abs(la.elapsed - ta),
                             lb.elapsed - la.elapsed))
            refs.sort()
            refs = refs[:MAX_REFS]
            if refs:
                cost = (tb - ta) - median(r[2] for r in refs)
                method, nrefs, known = "neighbours", len(refs), tb
        if cost is None:
            cost = s.loss_vs_field
            if cost is None and flag_group(s.flag) != "GREEN" and s.exit_time is not None:
                ref_in = field_all.at(s.race_time, s.flag)
                ref_out = field_all.at(s.exit_time, s.flag)
                if ref_in and ref_out and s.in_lap_time and s.out_lap_time:
                    cost = s.in_lap_time + s.out_lap_time - ref_in - ref_out
            if cost is not None:
                method = "field"
                known = (s.exit_time or s.race_time) + 150.0
        results.append(StopCost(stop=s, cost_s=cost, method=method, refs=nrefs, known_at=known))
    return results
