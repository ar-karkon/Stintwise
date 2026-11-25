"""Endurance stint planner.

Given a timed race (e.g. 6 hours), a fuel/energy stint length, a pit-stop
model, a tyre allocation and a driver line-up with drive-time limits, find a
plan that minimises total race time:

* how many stints are needed and how long each one is;
* at which stops to change tyres (double/triple stinting) within the
  available tyre sets;
* which driver takes each stint while respecting minimum / maximum drive
  time and a maximum number of consecutive stints.

Tyre and driver decisions are each solved exactly with dynamic programming;
they only interact through the pit-stop time (when a driver change or tyre
change can overlap refuelling), which is handled by alternating the two
solvers until the plan stops changing. All inputs are explicit parameters so
a team can replace the example numbers with its own data.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Driver:
    name: str
    pace_offset_s: float = 0.0  # lap time delta vs. the base lap
    min_drive_s: float = 0.0
    max_drive_s: float = math.inf


@dataclass(frozen=True)
class PitModel:
    lane_loss_s: float = 30.0  # extra time for driving the pit lane instead of the track
    refuel_base_s: float = 4.0  # fixed refuelling overhead (rig on/off)
    refuel_per_lap_s: float = 1.0  # refuelling time per lap of fuel/energy added
    tyre_change_s: float = 14.0
    driver_change_s: float = 12.0
    tyres_parallel: bool = False  # may tyres be changed while refuelling?
    driver_change_parallel: bool = True  # may drivers swap while refuelling?

    def stationary(self, refuel_laps: int, tyres: bool, driver_change: bool) -> dict:
        refuel = self.refuel_base_s + self.refuel_per_lap_s * refuel_laps if refuel_laps else 0.0
        total = refuel
        if tyres:
            total = max(total, self.tyre_change_s) if self.tyres_parallel else total + (
                self.tyre_change_s
            )
        if driver_change:
            if self.driver_change_parallel:
                total = max(total, self.driver_change_s)
            else:
                total += self.driver_change_s
        return {"refuel_s": refuel, "stationary_s": total, "loss_s": self.lane_loss_s + total}


@dataclass(frozen=True)
class TyreModel:
    deg_s_per_lap: float = 0.03  # linear lap time loss per lap of tyre age
    deg_quad_s: float = 0.0  # quadratic term (per lap^2), for tyres that fall off a cliff
    warmup_s: float = 1.5  # extra time on the out-lap of a new set
    sets_available: int = 99  # including the starting set
    max_stints_per_set: int = 3

    def stint_cost(self, start_age: int, laps: int, fresh: bool) -> float:
        cost = self.warmup_s if fresh else 0.0
        for age in range(start_age, start_age + laps):
            cost += self.deg_s_per_lap * age + self.deg_quad_s * age * age
        return cost


@dataclass(frozen=True)
class RaceSpec:
    duration_s: float
    base_lap_s: float
    max_stint_laps: int
    drivers: tuple[Driver, ...]
    pit: PitModel = field(default_factory=PitModel)
    tyres: TyreModel = field(default_factory=TyreModel)
    max_consecutive_stints: int = 3

    def validate(self) -> None:
        if not 600 <= self.duration_s <= 30 * 3600:
            raise ValueError("duration_s must be between 10 minutes and 30 hours")
        if not 30 <= self.base_lap_s <= 600:
            raise ValueError("base_lap_s must be between 30 and 600 seconds")
        if not 1 <= self.max_stint_laps <= 200:
            raise ValueError("max_stint_laps must be between 1 and 200")
        if not 1 <= len(self.drivers) <= 4:
            raise ValueError("Between one and four drivers are supported")
        if len({d.name for d in self.drivers}) != len(self.drivers):
            raise ValueError("Driver names must be unique")
        if self.tyres.sets_available < 1 or self.tyres.max_stints_per_set < 1:
            raise ValueError("Need at least one tyre set and one stint per set")
        if self.max_consecutive_stints < 1:
            raise ValueError("max_consecutive_stints must be at least 1")
        total_min = sum(d.min_drive_s for d in self.drivers)
        if total_min > self.duration_s:
            raise ValueError("Minimum drive times exceed the race duration")


class InfeasiblePlan(ValueError):
    pass


def _layout(spec: RaceSpec, total_laps: int) -> list[int]:
    full, rest = divmod(total_laps, spec.max_stint_laps)
    return [spec.max_stint_laps] * full + ([rest] if rest else [])


def _estimate_laps(spec: RaceSpec) -> int:
    """Laps a car covers in the race at base pace with full-length stints."""
    stop = spec.pit.stationary(spec.max_stint_laps, True, True)["loss_s"]
    laps = 0
    clock = 0.0
    while clock < spec.duration_s:
        laps += 1
        clock += spec.base_lap_s
        if laps % spec.max_stint_laps == 0:
            clock += stop
    return laps + 1  # one spare lap; trimmed after simulating the real plan


def _tyre_ages(stint_laps: list[int], changes: list[bool]) -> list[tuple[int, bool, int]]:
    """For each stint: (tyre age at start in laps, fresh set?, set number)."""
    ages = []
    age, set_no = 0, 1
    for i, laps in enumerate(stint_laps):
        fresh = i == 0 or changes[i - 1]
        if i > 0 and fresh:
            age, set_no = 0, set_no + 1
        ages.append((age, fresh, set_no))
        age += laps
    return ages


def _solve_tyres(spec: RaceSpec, stint_laps: list[int], driver_seq: list[int]) -> list[bool]:
    """Exact DP: change tyres at which stops? State = (stints on set, sets used)."""
    n = len(stint_laps)
    t = spec.tyres
    # state -> (cost, decisions)
    states: dict[tuple[int, int, int], tuple[float, list[bool]]] = {
        (1, 1, stint_laps[0]): (t.stint_cost(0, stint_laps[0], True), [])
    }  # (stints on current set, sets used, laps on set)
    for i in range(1, n):
        dc = driver_seq[i] != driver_seq[i - 1]
        nxt: dict[tuple[int, int, int], tuple[float, list[bool]]] = {}
        for (on_set, used, age), (cost, path) in states.items():
            for change in (False, True):
                if change and used >= t.sets_available:
                    continue
                if not change and on_set >= t.max_stints_per_set:
                    continue
                stop = spec.pit.stationary(stint_laps[i], change, dc)["loss_s"]
                start_age = 0 if change else age
                c = cost + stop + t.stint_cost(start_age, stint_laps[i], change)
                key = (1, used + 1, stint_laps[i]) if change else (
                    on_set + 1, used, age + stint_laps[i]
                )
                if key not in nxt or c < nxt[key][0]:
                    nxt[key] = (c, path + [change])
        states = nxt
    if not states:
        raise InfeasiblePlan(
            "Not enough tyre sets for this race: increase sets_available or max_stints_per_set"
        )
    return min(states.values(), key=lambda v: v[0])[1]


def _stint_seconds(spec: RaceSpec, laps: int, driver: Driver, tyre_cost: float) -> float:
    return laps * (spec.base_lap_s + driver.pace_offset_s) + tyre_cost


def _solve_drivers(spec: RaceSpec, stint_laps: list[int], changes: list[bool]) -> list[int]:
    """DP over stints; state = (last driver, consecutive run, stints per driver)."""
    drivers = spec.drivers
    nd = len(drivers)
    ages = _tyre_ages(stint_laps, changes)
    tyre_cost = [
        spec.tyres.stint_cost(a, laps, f)
        for (a, f, _), laps in zip(ages, stint_laps, strict=True)
    ]

    def stop_extra(i: int, dc: bool) -> float:
        # extra stationary time caused by a driver change at the stop before stint i
        if i == 0 or not dc:
            return 0.0
        with_dc = spec.pit.stationary(stint_laps[i], changes[i - 1], True)["loss_s"]
        without = spec.pit.stationary(stint_laps[i], changes[i - 1], False)["loss_s"]
        return with_dc - without

    State = tuple[int, int, tuple[int, ...]]
    states: dict[State, tuple[float, tuple[float, ...], list[int]]] = {}
    for d in range(nd):
        secs = _stint_seconds(spec, stint_laps[0], drivers[d], tyre_cost[0])
        if secs > drivers[d].max_drive_s:
            continue
        counts = tuple(1 if k == d else 0 for k in range(nd))
        times = tuple(secs if k == d else 0.0 for k in range(nd))
        states[(d, 1, counts)] = (stint_laps[0] * drivers[d].pace_offset_s, times, [d])

    for i in range(1, len(stint_laps)):
        nxt: dict[State, tuple[float, tuple[float, ...], list[int]]] = {}
        for (last, run, counts), (cost, times, path) in states.items():
            for d in range(nd):
                same = d == last
                if same and run >= spec.max_consecutive_stints:
                    continue
                secs = _stint_seconds(spec, stint_laps[i], drivers[d], tyre_cost[i])
                if times[d] + secs > drivers[d].max_drive_s:
                    continue
                c = cost + stint_laps[i] * drivers[d].pace_offset_s + stop_extra(i, not same)
                new_counts = tuple(n + (1 if k == d else 0) for k, n in enumerate(counts))
                new_times = tuple(t + (secs if k == d else 0.0) for k, t in enumerate(times))
                key = (d, run + 1 if same else 1, new_counts)
                if key not in nxt or c < nxt[key][0]:
                    nxt[key] = (c, new_times, path + [d])
        states = nxt

    feasible = [
        (cost, path)
        for (_, _, _), (cost, times, path) in states.items()
        if all(times[k] >= drivers[k].min_drive_s for k in range(nd))
    ]
    if not feasible:
        raise InfeasiblePlan(
            "No driver rotation satisfies the drive-time limits; relax min/max drive time "
            "or max consecutive stints"
        )
    return min(feasible, key=lambda v: v[0])[1]


def simulate(
    spec: RaceSpec, stint_laps: list[int], changes: list[bool], driver_seq: list[int]
) -> dict:
    """Run a plan through the race clock; returns stints, stops and laps completed."""
    ages = _tyre_ages(stint_laps, changes)
    clock = 0.0
    laps_done = 0
    laps_at_flag: int | None = None
    finish_time: float | None = None
    rows, stops = [], []
    drive = {d.name: 0.0 for d in spec.drivers}
    for i, laps in enumerate(stint_laps):
        driver = spec.drivers[driver_seq[i]]
        age, fresh, set_no = ages[i]
        if i > 0:
            dc = driver_seq[i] != driver_seq[i - 1]
            stop = spec.pit.stationary(laps, changes[i - 1], dc)
            stops.append(
                {
                    "after_stint": i,
                    "race_time": clock,
                    "tyres": changes[i - 1],
                    "driver_change": dc,
                    "refuel_laps": laps,
                    **{k: round(v, 2) for k, v in stop.items()},
                }
            )
            clock += stop["loss_s"]
        start = clock
        for k in range(laps):
            lap_time = spec.base_lap_s + driver.pace_offset_s
            a = age + k
            lap_time += spec.tyres.deg_s_per_lap * a + spec.tyres.deg_quad_s * a * a
            if fresh and k == 0:
                lap_time += spec.tyres.warmup_s
            clock += lap_time
            laps_done += 1
            if laps_at_flag is None and clock >= spec.duration_s:
                laps_at_flag, finish_time = laps_done, clock
        drive[driver.name] += clock - start
        rows.append(
            {
                "stint": i + 1,
                "driver": driver.name,
                "laps": laps,
                "start": round(start, 2),
                "end": round(clock, 2),
                "tyre_set": set_no,
                "tyre_age_start": age,
                "new_tyres": fresh,
            }
        )
    return {
        "stints": rows,
        "stops": stops,
        "planned_laps": laps_done,
        "laps_completed": laps_at_flag,
        "finish_time": finish_time,
        "total_time": clock,
        "drive_time": drive,
        "tyre_sets_used": ages[-1][2] if ages else 0,
    }


def _optimise(spec: RaceSpec, stint_laps: list[int], fixed_tyres: list[bool] | None):
    changes = fixed_tyres or [True] * (len(stint_laps) - 1)
    seq = _solve_drivers(spec, stint_laps, changes)
    for _ in range(4):
        new_changes = fixed_tyres or _solve_tyres(spec, stint_laps, seq)
        new_seq = _solve_drivers(spec, stint_laps, new_changes)
        if new_changes == changes and new_seq == seq:
            break
        changes, seq = new_changes, new_seq
    return changes, seq


def plan(spec: RaceSpec) -> dict:
    spec.validate()
    total = _estimate_laps(spec)
    for _ in range(6):
        layout = _layout(spec, total)
        changes, seq = _optimise(spec, layout, None)
        result = simulate(spec, layout, changes, seq)
        done = result["laps_completed"]
        if done is None:  # plan too short to reach the flag
            total += spec.max_stint_laps
            continue
        if done == total:
            break
        total = done
    else:
        raise InfeasiblePlan("Plan did not converge")

    # Reference: same driver logic, fresh tyres at every stop, allocation ignored.
    unlimited = RaceSpec(
        **{**spec.__dict__, "tyres": TyreModel(**{**spec.tyres.__dict__, "sets_available": 999})}
    )
    every = [True] * (len(layout) - 1)
    try:
        ref = simulate(unlimited, layout, every, _solve_drivers(unlimited, layout, every))
        result["reference_fresh_tyres_every_stop"] = {
            "description": "Fresh tyres at every stop, tyre allocation ignored",
            "total_time": ref["total_time"],
            "tyre_sets_used": ref["tyre_sets_used"],
            "plan_minus_reference_s": round(result["total_time"] - ref["total_time"], 2),
        }
    except InfeasiblePlan:
        result["reference_fresh_tyres_every_stop"] = None
    result["spec"] = asdict(spec)
    result["drivers"] = [
        {
            "name": d.name,
            "drive_s": round(result["drive_time"][d.name], 1),
            "min_s": d.min_drive_s,
            "max_s": None if math.isinf(d.max_drive_s) else d.max_drive_s,
        }
        for d in spec.drivers
    ]
    result["notes"] = [
        "Drive time counts time on track per stint; pit stationary time is excluded.",
        "Finish = first line crossing after the clock expires (laps_completed).",
        "All inputs are parameters: replace the example values with your own data.",
    ]
    return result


def spec_from_dict(data: dict) -> RaceSpec:
    drivers = tuple(
        Driver(
            name=d["name"],
            pace_offset_s=float(d.get("pace_offset_s", 0.0)),
            min_drive_s=float(d.get("min_drive_s") or 0.0),
            max_drive_s=float(d["max_drive_s"]) if d.get("max_drive_s") else math.inf,
        )
        for d in data["drivers"]
    )
    pit = PitModel(**data.get("pit", {}))
    tyres = TyreModel(**data.get("tyres", {}))
    kwargs = {k: data[k] for k in ("duration_s", "base_lap_s", "max_stint_laps") if k in data}
    if "max_consecutive_stints" in data:
        kwargs["max_consecutive_stints"] = int(data["max_consecutive_stints"])
    return RaceSpec(drivers=drivers, pit=pit, tyres=tyres, **kwargs)


__all__ = [
    "Driver",
    "InfeasiblePlan",
    "PitModel",
    "RaceSpec",
    "TyreModel",
    "plan",
    "simulate",
    "spec_from_dict",
]
