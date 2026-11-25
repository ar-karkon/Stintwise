"""Live race state and pit-wall alerts from lap timing.

Everything is computed *as of* a race time ``t`` using only crossings that
had happened by then, so a recorded race can be replayed exactly as it would
have looked on the pit wall. The same code runs on a live feed.

Main entry points:

* :func:`race_state` - class table with gaps, stints, stops still owed and
  the *net* order once everybody's remaining stops are counted, plus the
  focus car's drive-time status.
* :func:`race_events` - the radio feed: cautions, rival stops, caution pit
  opportunities, drive-time and fuel-window warnings for the focus car.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from .analysis import (
    FieldPace,
    PitStop,
    caution_periods,
    driver_label,
    flag_group,
    pit_stops,
)
from .timing import Lap, Race

DEFAULT_CAUTION_RATIO = {"FCY": 1.6, "SC": 1.8}
MIN_USEFUL_GAIN_S = 5.0


@dataclass
class Rules:
    """What the pit wall knows about the race. All fields are optional."""

    duration_s: float | None = None  # scheduled race length (default: inferred)
    required_service_stops: int | None = None  # e.g. 1 mandatory driver-change stop
    max_stint_laps: int | None = None  # fuel / energy window in laps
    max_stint_s: float | None = None  # fuel / energy window in time (learned)
    window_open_s: float | None = None  # race time the pit window opens
    window_close_s: float | None = None
    service_loss_s: float | None = None  # fallback green service-stop loss
    pit_track_equivalent_s: float = 20.0  # track time the pit lane bypasses at racing speed
    caution_loss_s: dict[str, float] = field(default_factory=dict)  # learned: {"SC": 106, ...}
    pit_lane_s: float | None = None  # typical service-stop pit-lane time (learned)
    cost_extra_s: dict[str, float] = field(default_factory=dict)  # cost beyond pit-lane time
    caution_model: dict = field(default_factory=dict)  # see stintwise.caution_model
    min_drive_s: float | None = None  # minimum drive time per driver (official)
    drivers: dict[str, dict] = field(default_factory=dict)  # focus car: name -> limits

    @classmethod
    def from_dict(cls, data: dict | None) -> Rules:
        data = dict(data or {})
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


class RaceContext:
    """Pre-computed, time-indexed facts about a race (stops, cautions, field pace)."""

    def __init__(self, race: Race, car_class: str | None, rules: Rules | None = None):
        self.race = race
        self.car_class = car_class
        self.rules = rules or Rules()
        self.duration = self.rules.duration_s or race.scheduled_duration
        self.cars = race.cars_in_class(car_class)
        self.field = FieldPace(race, car_class)
        self.stops = pit_stops(race, car_class)
        self.cautions = caution_periods(race)
        self.lap_time_at: dict[str, dict[int, float]] = {
            car: {lap.lap: lap.elapsed for lap in race.car_laps(car) if lap.elapsed is not None}
            for car in self.cars
        }
        self.crossings = sorted(
            (lap.elapsed, lap.flag) for lap in race.laps if lap.elapsed is not None
        )
        self.memo: dict = {}

    def entry(self, car: str) -> list[str]:
        """Drivers on a car's entry (every driver who appears in its timing)."""
        names: list[str] = []
        for lap in self.race.car_laps(car):
            name = driver_label(lap)
            if name not in names:
                names.append(name)
        return names

    # --- facts known at time t -------------------------------------------------
    def completed(self, car: str, t: float) -> list[Lap]:
        return [lap for lap in self.race.car_laps(car) if lap.elapsed is not None
                and lap.elapsed <= t]

    def known_stops(self, t: float) -> list[PitStop]:
        """Stops whose out-lap and loss measurement were complete by t."""
        return [s for s in self.stops
                if s.exit_time is not None and s.exit_time + self.field.window <= t]

    def flag_at(self, t: float) -> str:
        current = "GF"
        for when, flag in self.crossings:
            if when > t:
                break
            current = flag
        return current

    def pit_lane_time(self, t: float) -> float | None:
        """Typical service-stop pit-lane time: measured in this race once two stops are
        done (it depends on the pit lane's length), else learned from earlier races."""
        times = sorted(s.pit_time for s in self.stops if s.kind == "service" and s.pit_time
                       and s.exit_time is not None and s.exit_time <= t)
        if len(times) >= 2:
            normal = [x for x in times if x <= 1.3 * median(times)]
            return median(normal)
        return self.rules.pit_lane_s

    def service_loss(self, t: float, flag: str = "GF") -> float | None:
        """What a green-flag service stop costs against cars that stay out."""
        if flag_group(flag) != "GREEN":
            losses = [s.loss_vs_field for s in self.known_stops(t)
                      if s.kind == "service" and s.loss_vs_field is not None
                      and flag_group(s.flag) == flag_group(flag)]
            return median(losses) if len(losses) >= 2 else None
        extra = (self.rules.cost_extra_s or {}).get("GREEN")
        pit = self.pit_lane_time(t)
        if pit is not None and extra is not None:
            return pit + extra
        if self.rules.service_loss_s is not None:
            return self.rules.service_loss_s
        losses = [s.loss_vs_field for s in self.known_stops(t)
                  if s.kind == "service" and s.loss_vs_field is not None
                  and flag_group(s.flag) == "GREEN"]
        return median(losses) if len(losses) >= 2 else None

    def caution_lap(self, t: float, flag: str) -> float | None:
        laps = [lap.lap_time for lap in self.race.laps
                if lap.flag == flag and lap.elapsed is not None and t - 600 <= lap.elapsed <= t
                and lap.lap_time and not lap.in_pit and lap.pit_time is None
                and (not self.car_class or lap.car_class == self.car_class)]
        return median(laps) if len(laps) >= 3 else None


def _pace(laps: list[Lap], n: int = 5) -> float | None:
    clean = [lap.lap_time for lap in laps if lap.green and lap.lap_time and not lap.in_pit
             and lap.pit_time is None]
    recent = clean[-n:]
    if not recent:
        return None
    med = median(recent)
    recent = [x for x in recent if x <= med * 1.07]
    return median(recent)


def car_state(ctx: RaceContext, car: str, t: float) -> dict:
    laps = ctx.completed(car, t)
    info = ctx.race.car_info(car)
    if not laps:
        return {**info, "laps": 0, "last_elapsed": None, "in_pit": False}
    last = laps[-1]
    since_pit = 0
    for lap in reversed(laps):
        if lap.in_pit:
            break
        since_pit += 1
    stops = [s for s in ctx.stops if s.car == car and s.exit_time is not None
             and s.exit_time <= t]
    service_done = sum(1 for s in stops if s.kind == "service")
    # A mandatory stop only counts once its window has opened.
    opened = ctx.rules.window_open_s
    counted = sum(1 for s in stops if s.kind == "service"
                  and (opened is None or s.race_time >= opened - 60))
    last_service_exit = max((s.exit_time for s in stops if s.kind == "service"), default=0.0)
    drive: dict[str, float] = defaultdict(float)
    for lap in laps:
        if lap.lap_time:
            drive[driver_label(lap)] += lap.lap_time
    current = driver_label(last)
    if not last.in_pit:
        drive[current] += max(0.0, t - last.elapsed)
    pace = _pace(laps)
    state = {
        **info,
        "laps": last.lap,
        "last_elapsed": last.elapsed,
        "last_lap_time": last.lap_time,
        "in_pit": last.in_pit,
        "driver": current,
        "stint_laps": since_pit,
        "stops": len(stops),
        "service_stops": service_done,
        "counted_stops": counted,
        "stint_s": t - last_service_exit,
        "pace": pace,
        "drive_time": dict(drive),
    }
    state["remaining_service"] = _remaining_service(ctx, state, t)
    if ctx.rules.max_stint_laps:
        state["fuel_laps_left"] = max(0, ctx.rules.max_stint_laps - since_pit)
    return state


def _remaining_service(ctx: RaceContext, state: dict, t: float) -> int:
    rules = ctx.rules
    if rules.required_service_stops is not None:
        return max(0, rules.required_service_stops - state["counted_stops"])
    if rules.max_stint_laps and state.get("pace"):
        laps_to_go = max(0.0, (ctx.duration - t) / state["pace"])
        fuel_left = 0 if state["in_pit"] else rules.max_stint_laps - state["stint_laps"]
        return max(0, math.ceil((laps_to_go - fuel_left) / rules.max_stint_laps))
    if rules.max_stint_s:
        time_left = max(0.0, ctx.duration - t)
        fuel_left = 0.0 if state["in_pit"] else max(0.0, rules.max_stint_s - state["stint_s"])
        return max(0, math.ceil((time_left - fuel_left) / rules.max_stint_s))
    return 0


def drive_time_status(rules: Rules, drive: dict[str, float], current: str | None,
                      t: float, duration: float, pit_allowance: float = 180.0,
                      entry: list[str] | None = None) -> dict | None:
    """Can every driver still reach their minimum? When must we change?

    Limits come from ``rules.drivers``; without them, the learned minimum drive time
    (``rules.min_drive_s``) applies to every driver on the car's entry.
    """
    limits_by_driver = rules.drivers
    if not limits_by_driver and rules.min_drive_s and entry:
        limits_by_driver = {name: {"min_drive_s": rules.min_drive_s} for name in entry}
    if not limits_by_driver:
        return None
    rows = []
    other_deficit = 0.0
    for name, limits in limits_by_driver.items():
        driven = drive.get(name, 0.0)
        minimum = float(limits.get("min_drive_s") or 0.0)
        maximum = limits.get("max_drive_s")
        deficit = max(0.0, minimum - driven)
        if name != current:
            other_deficit += deficit
        rows.append({"name": name, "driven_s": round(driven, 1), "min_s": minimum,
                     "max_s": maximum, "deficit_s": round(deficit, 1)})
    latest_change = duration - other_deficit - pit_allowance
    margin = latest_change - t
    status = "ok"
    if other_deficit > 0:
        if margin < 0:
            status = "impossible"
        elif margin < 300:
            status = "change_now"
        elif margin < 900:
            status = "change_soon"
    cur = limits_by_driver.get(current or "", {})
    time_to_max = None
    if cur.get("max_drive_s"):
        time_to_max = cur["max_drive_s"] - drive.get(current or "", 0.0)
        if time_to_max < 300 and status == "ok":
            status = "max_drive_soon"
    return {"current": current, "drivers": rows, "latest_change_time": round(latest_change, 1),
            "margin_s": round(margin, 1), "time_to_max_s": time_to_max, "status": status}


def _net_order(cars: list[dict]) -> list[dict]:
    """Order by net time, but keep the timing order between cars that owe the same
    number of stops (net time only adds information when the stops owed differ).

    Insertion into a list kept in timing order: a car moves ahead of the cars before
    it only if it owes fewer stops and its net time is smaller.
    """
    ordered: list[dict] = []
    for car in sorted(cars, key=lambda c: c["position"]):
        k = len(ordered)
        while k > 0:
            ahead = ordered[k - 1]
            if (ahead["remaining_service"] != car["remaining_service"]
                    and car["net_time_s"] < ahead["net_time_s"]):
                k -= 1
            else:
                break
        ordered.insert(k, car)
    return ordered


def stop_free_reference(ctx: RaceContext, lap: int, t: float, loss: float) -> float | None:
    """Earliest crossing of ``lap`` in the class with each car's counted stops removed."""
    key = ("ref", lap, round(t, 3), loss)
    if key in ctx.memo:
        return ctx.memo[key]
    opened = ctx.rules.window_open_s
    best = None
    for car in ctx.cars:
        when = ctx.lap_time_at[car].get(lap)
        if when is None or when > t:
            continue
        done = sum(1 for s in ctx.stops if s.car == car and s.kind == "service"
                   and s.exit_time is not None and s.exit_time <= when
                   and (opened is None or s.race_time >= opened - 60))
        value = when - done * loss
        if best is None or value < best:
            best = value
    ctx.memo[key] = best
    return best


def race_state(race: Race, t: float, car_class: str | None = None, focus: str | None = None,
               rules: Rules | dict | None = None, ctx: RaceContext | None = None) -> dict:
    if not isinstance(rules, Rules):
        rules = Rules.from_dict(rules)
    ctx = ctx or RaceContext(race, car_class, rules)
    states = [car_state(ctx, car, t) for car in ctx.cars]
    running = [s for s in states if s["laps"] > 0]
    running.sort(key=lambda s: (-s["laps"], s["last_elapsed"]))
    leader = running[0] if running else None
    loss = ctx.service_loss(t)
    for pos, s in enumerate(running, start=1):
        s["position"] = pos
        lead_t = ctx.lap_time_at[leader["car"]].get(s["laps"])
        s["gap_s"] = round(s["last_elapsed"] - lead_t, 3) if lead_t is not None else None
        s["laps_down"] = leader["laps"] - s["laps"]
        if pos > 1:
            ahead = running[pos - 2]
            ahead_t = ctx.lap_time_at[ahead["car"]].get(s["laps"])
            s["interval_s"] = round(s["last_elapsed"] - ahead_t, 3) if ahead_t else None
        else:
            s["interval_s"] = None
        # Net time: compare cars in a stop-free frame (each completed stop taken off at
        # the standard cost), so a reference car's own stop never leaks into a gap,
        # then add the stops each car still owes.
        ref = stop_free_reference(ctx, s["laps"], t, loss or 0.0)
        owed = s["remaining_service"] * (loss or 0.0)
        s["net_time_s"] = None if ref is None else round(s["last_elapsed"] + owed - ref, 3)
    net_sorted = _net_order([s for s in running if s["net_time_s"] is not None])
    if net_sorted:
        base = net_sorted[0]["net_time_s"]
        for pos, s in enumerate(net_sorted, start=1):
            s["net_position"] = pos
            s["net_gap_s"] = round(s["net_time_s"] - base, 3)
    flag = ctx.flag_at(t)
    result = {
        "t": t,
        "race_time_left_s": max(0.0, ctx.duration - t),
        "duration_s": ctx.duration,
        "flag": flag,
        "class": car_class,
        "service_loss_s": loss,
        "cars": running,
        "not_started": [s["car"] for s in states if s["laps"] == 0],
    }
    if focus:
        f = next((s for s in states if s["car"] == focus), None)
        if f is None:
            raise KeyError(f"Car {focus!r} not in class")
        result["focus"] = {
            **f,
            "drive_status": drive_time_status(ctx.rules, f.get("drive_time", {}),
                                              f.get("driver"), t, ctx.duration,
                                              entry=ctx.entry(focus)),
        }
    return result


def caution_opportunity(ctx: RaceContext, state: dict, flag: str, t: float) -> dict:
    """Should the focus car pit now that a caution is out?

    With a learned caution model (see :mod:`stintwise.caution_model`): the chance a stop
    made at this point of the caution gains time, the typical gain and a range, from
    stops at the same point of earlier cautions. Without one: the measured or learned
    cost of a caution stop against a green stop.
    """
    from .caution_model import assess

    rules = ctx.rules
    green_loss = ctx.service_loss(t, "GF")
    pit = ctx.pit_lane_time(t)
    start = next((p["start"] for p in ctx.cautions if p["flag"] == flag
                  and p["start"] - 1 <= t <= p["end"] + 1), t)
    pace = state.get("pace")
    lap_now = (ctx.caution_lap(t, flag) or (pace * DEFAULT_CAUTION_RATIO.get(flag, 1.6)
                                             if pace else None))
    # the car reaches pit entry at about its next line crossing
    arrival = max(t, (state.get("last_elapsed") or t) + (lap_now or 0.0))
    entry = (rules.caution_model or {}).get(flag)
    assessed = assess(entry, arrival - start, pit) if entry and pit else None
    p_gain = None
    gain_range = None
    gain_middle = None
    if assessed:
        gain = assessed["gain_s"]
        p_gain = assessed["p_gain"]
        gain_range = assessed["range_s"]
        gain_middle = assessed["middle_s"]
        caution_loss = None if green_loss is None else green_loss - gain
        basis = (f"{assessed['n']} stops made {_mins(arrival - start)} into earlier "
                 f"{flag} periods")
    else:
        observed = ctx.service_loss(t, flag)
        learned = (rules.caution_loss_s or {}).get(flag)
        if observed is not None:
            caution_loss, basis = observed, f"measured on {flag} stops earlier in this race"
        elif learned is not None:
            caution_loss, basis = learned, f"learned from {flag} stops in earlier races"
        elif green_loss is not None and pace:
            caution_lap = ctx.caution_lap(t, flag)
            ratio = (caution_lap / pace) if caution_lap else DEFAULT_CAUTION_RATIO.get(flag, 1.6)
            caution_loss = green_loss - (ratio - 1.0) * rules.pit_track_equivalent_s
            basis = f"estimated: field laps {ratio:.2f}x slower under {flag}"
        else:
            caution_loss, basis = None, "no pit-stop loss measured yet"
        gain = None if green_loss is None or caution_loss is None else green_loss - caution_loss
    remaining = state.get("remaining_service", 0)
    notes = []
    if rules.window_open_s is not None and t < rules.window_open_s:
        notes.append(f"pit window opens at {_clock(rules.window_open_s)}")
    if rules.window_close_s is not None and t > rules.window_close_s:
        notes.append("pit window closed")
    status = drive_time_status(rules, state.get("drive_time", {}), state.get("driver"), t,
                               ctx.duration, entry=ctx.entry(state["car"]))
    short_driver = None
    if status:
        cur = next((d for d in status["drivers"] if d["name"] == state.get("driver")), None)
        if cur and cur["deficit_s"] > 0:
            short_driver = cur
            notes.append(f"{cur['name']} still needs {cur['deficit_s'] / 60:.0f} min of drive time")
    chance = "" if p_gain is None else f" ({p_gain * 100:.0f}% of similar stops gained time)"
    if state.get("in_pit"):
        verdict, action = "Car is already in the pit lane", "none"
    elif remaining <= 0:
        verdict, action = "No stop owed: stay out", "stay"
    elif any("closed" in n or "opens" in n for n in notes):
        verdict, action = "Stay out: pit window not open", "stay"
    elif short_driver and remaining < 2:
        verdict = (f"Stay out: a driver change now leaves {short_driver['name']} "
                   f"{short_driver['deficit_s'] / 60:.0f} min short")
        action = "stay"
    elif gain is None:
        verdict, action = "Caution: consider pitting (no loss data yet)", "consider"
    elif (p_gain is None or p_gain >= 0.5) and gain > MIN_USEFUL_GAIN_S:
        keep = f", keep {short_driver['name']} in the car" if short_driver else ""
        verdict, action = f"BOX BOX: stopping under {flag} saves ~{gain:.0f}s{chance}{keep}", "pit"
    else:
        verdict, action = f"Stay out: {flag} saves only ~{max(gain, 0):.0f}s{chance}", "stay"
    return {"flag": flag, "action": action, "verdict": verdict, "gain_s": gain,
            "p_gain": p_gain, "gain_range_s": list(gain_range) if gain_range else None,
            "gain_middle_s": list(gain_middle) if gain_middle else None,
            "green_loss_s": green_loss, "caution_loss_s": caution_loss, "basis": basis,
            "remaining_service": remaining, "notes": notes}


def _mins(seconds: float) -> str:
    return f"{max(0.0, seconds) / 60:.0f} min"


def _clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def race_events(race: Race, car_class: str | None = None, focus: str | None = None,
                rules: Rules | dict | None = None, until: float | None = None,
                ctx: RaceContext | None = None) -> list[dict]:
    """Radio feed for a replay or a live race, in time order."""
    if not isinstance(rules, Rules):
        rules = Rules.from_dict(rules)
    ctx = ctx or RaceContext(race, car_class, rules)
    end = until if until is not None else math.inf
    events: list[dict] = []

    def add(t, etype, severity, text, car=None, **data):
        if t <= end:
            events.append({"t": round(t, 3), "type": etype, "severity": severity,
                           "car": car, "text": text, "data": data})

    for period in ctx.cautions:
        add(period["start"], "caution", "warn", f"{period['flag']} deployed",
            flag=period["flag"])
        add(period["end"], "green", "info", f"{period['flag']} ending, green flag",
            flag=period["flag"])
        if focus:
            st = car_state(ctx, focus, period["start"])
            if st["laps"]:
                opp = caution_opportunity(ctx, st, period["flag"], period["start"])
                sev = "urgent" if opp["action"] == "pit" else "info"
                text = opp["verdict"] + ("; " + "; ".join(opp["notes"]) if opp["notes"] else "")
                add(period["start"] + 0.001, "caution_call", sev, text, focus, **opp)

    for stop in ctx.stops:
        who = "We" if stop.car == focus else f"#{stop.car}"
        under = f", under {stop.flag}" if stop.flag not in ("GF", "FF") else ""
        add(stop.race_time, "pit_in", "info" if stop.car != focus else "warn",
            f"{who} in the pits (lap {stop.in_lap}{under})",
            stop.car, lap=stop.in_lap, flag=stop.flag)
        if stop.exit_time is not None:
            pit = f"{stop.pit_time:.0f}s" if stop.pit_time else "?"
            change = f", {stop.driver_in} -> {stop.driver_out}" if stop.driver_change else ""
            add(stop.exit_time, "pit_out", "info",
                f"#{stop.car} out of the pits: {stop.kind} stop, pit lane {pit}{change}",
                stop.car, kind=stop.kind, pit_time=stop.pit_time,
                driver_change=stop.driver_change)

    if focus:
        _focus_events(ctx, focus, add)
    events.sort(key=lambda e: (e["t"], e["type"]))
    return events


def _focus_events(ctx: RaceContext, focus: str, add) -> None:
    rules = ctx.rules
    laps = ctx.race.car_laps(focus)
    last_status = "ok"
    last_position = None
    window_warned_at = -1
    pace_warned_stint = -1
    stint_no = 0
    stint_times: list[float] = []
    for lap in laps:
        if lap.elapsed is None:
            continue
        t = lap.elapsed
        st = car_state(ctx, focus, t)
        status = drive_time_status(rules, st["drive_time"], st["driver"], t, ctx.duration,
                                   entry=ctx.entry(focus))
        if status and status["status"] != last_status and status["status"] != "ok":
            sev = "urgent" if status["status"] in ("change_now", "impossible") else "warn"
            needers = [d["name"] for d in status["drivers"]
                       if d["deficit_s"] > 0 and d["name"] != st["driver"]]
            text = {
                "change_soon": f"Driver change needed by {_clock(status['latest_change_time'])}"
                               f" so {', '.join(needers)} can reach minimum drive time",
                "change_now": f"Change driver NOW: {', '.join(needers)} still short of minimum",
                "impossible": f"Minimum drive time can no longer be met for {', '.join(needers)}",
                "max_drive_soon": f"{st['driver']} close to maximum drive time",
            }[status["status"]]
            add(t, "drive_time", sev, text, focus, **status)
        if status:
            last_status = status["status"]

        pos = _class_position(ctx, focus, t)
        if last_position is not None and pos and pos != last_position:
            add(t, "position", "info", f"P{pos} in class (was P{last_position})", focus,
                position=pos)
        last_position = pos or last_position

        if lap.in_pit:
            stint_no += 1
            stint_times = []
            continue
        if rules.max_stint_laps and st.get("fuel_laps_left") is not None:
            left = st["fuel_laps_left"]
            if left <= 3 and window_warned_at != stint_no and st["remaining_service"] > 0:
                window_warned_at = stint_no
                add(t, "fuel_window", "warn", f"Box in {left} laps: end of fuel window", focus,
                    laps_left=left)
        if lap.green and lap.lap_time and lap.pit_time is None:
            stint_times.append(lap.lap_time)
            if len(stint_times) >= 8 and pace_warned_stint != stint_no:
                ref = median(stint_times[:-3])
                recent = stint_times[-3:]
                if all(x > ref + 1.5 for x in recent):
                    pace_warned_stint = stint_no
                    add(t, "pace", "warn",
                        f"Pace drop: last 3 laps +{median(recent) - ref:.1f}s on stint median",
                        focus, delta_s=median(recent) - ref)


def _class_position(ctx: RaceContext, car: str, t: float) -> int | None:
    rows = []
    for c in ctx.cars:
        times = ctx.lap_time_at[c]
        done = [(lap, when) for lap, when in times.items() if when <= t]
        if done:
            lap, when = max(done)
            rows.append((-lap, when, c))
    rows.sort()
    for pos, (_, _, c) in enumerate(rows, start=1):
        if c == car:
            return pos
    return None
