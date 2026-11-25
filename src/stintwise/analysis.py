"""Strategy analysis of a real endurance race from lap timing.

Everything here is derived from the timing file only: stints, pit stops,
driver drive time, caution periods and how much a pit stop cost relative to
the field depending on whether it was taken under green, FCY or Safety Car.
"""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from statistics import median

from .timing import CAUTION_FLAGS, Lap, Race

CLEAN_LAP_FACTOR = 1.07  # laps slower than 107% of the stint median are traffic/incidents
SHORT_STOP_MAX_S = 60.0  # pit-lane time of a splash or drive-through
GARAGE_STOP_MIN_S = 600.0  # repairs in the garage


def stop_kind(pit_time: float | None) -> str:
    if pit_time is None:
        return "unknown"
    if pit_time <= SHORT_STOP_MAX_S:
        return "short"
    if pit_time >= GARAGE_STOP_MIN_S:
        return "garage"
    return "service"


def flag_group(flag: str) -> str:
    """GREEN for racing laps (incl. the chequered lap), otherwise the caution code."""
    return "GREEN" if flag in ("GF", "FF") else flag


@dataclass(frozen=True)
class PitStop:
    car: str
    car_class: str
    in_lap: int
    race_time: float  # elapsed time at the end of the in-lap
    exit_time: float | None  # elapsed time at the end of the out-lap
    pit_time: float | None  # pit-lane time as published by timing (on the out-lap)
    kind: str  # service | short | garage | unknown
    driver_in: str
    driver_out: str
    driver_change: bool
    flag: str  # flag at the in-lap crossing
    in_lap_time: float | None
    out_lap_time: float | None
    loss_vs_field: float | None  # in + out lap minus field median laps (same time, same flag)


@dataclass(frozen=True)
class Stint:
    car: str
    car_class: str
    number: int
    driver: str
    first_lap: int
    last_lap: int
    laps: int
    start_time: float
    end_time: float
    clean_laps: int
    median_clean: float | None
    best: float | None
    deg_per_lap: float | None  # least-squares slope over clean green laps (s/lap)
    ended_in_pit: bool

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


def driver_label(lap: Lap) -> str:
    if lap.driver:
        return lap.driver
    return f"Driver {lap.driver_number}" if lap.driver_number is not None else "?"


def slope(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 5:
        return None
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in points) / sxx


def split_stints(laps: list[Lap]) -> list[list[Lap]]:
    chunks: list[list[Lap]] = [[]]
    for lap in laps:
        chunks[-1].append(lap)
        if lap.in_pit:
            chunks.append([])
    return [c for c in chunks if c]


def clean_laps(chunk: list[Lap]) -> list[Lap]:
    """Green laps of a stint without out/in laps and without slow outliers."""
    body = chunk[1:-1] if len(chunk) > 2 else []
    green = [lap for lap in body if lap.green and lap.lap_time and lap.pit_time is None]
    if not green:
        return []
    med = median(lap.lap_time for lap in green)
    return [lap for lap in green if lap.lap_time <= med * CLEAN_LAP_FACTOR]


def stints(race: Race, car: str, until: float | None = None) -> list[Stint]:
    laps = race.car_laps(car)
    if until is not None:
        laps = [lap for lap in laps if lap.elapsed is not None and lap.elapsed <= until]
    result: list[Stint] = []
    previous_end = 0.0
    for number, chunk in enumerate(split_stints(laps), start=1):
        driver = Counter(driver_label(lap) for lap in chunk).most_common(1)[0][0]
        clean = clean_laps(chunk)
        start = previous_end
        end = chunk[-1].elapsed or start
        previous_end = end
        result.append(
            Stint(
                car=car,
                car_class=chunk[0].car_class,
                number=number,
                driver=driver,
                first_lap=chunk[0].lap,
                last_lap=chunk[-1].lap,
                laps=len(chunk),
                start_time=start,
                end_time=end,
                clean_laps=len(clean),
                median_clean=median(lap.lap_time for lap in clean) if clean else None,
                best=min(lap.lap_time for lap in clean) if clean else None,
                deg_per_lap=slope([(i, lap.lap_time) for i, lap in enumerate(clean)]),
                ended_in_pit=chunk[-1].in_pit,
            )
        )
    return result


class FieldPace:
    """Median lap time of a class around a given race time, under the same flag."""

    def __init__(self, race: Race, car_class: str | None, window: float = 150.0):
        self.window = window
        groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for lap in race.laps:
            if (
                lap.elapsed is not None
                and lap.lap_time
                and not lap.in_pit
                and lap.pit_time is None  # skip out-laps
                and (not car_class or lap.car_class == car_class)
            ):
                groups[flag_group(lap.flag)].append((lap.elapsed, lap.lap_time))
        self.points = {k: sorted(v) for k, v in groups.items()}
        self.times = {k: [p[0] for p in v] for k, v in self.points.items()}

    def at(self, t: float, flag: str = "GF") -> float | None:
        group = flag_group(flag)
        points, times = self.points.get(group, []), self.times.get(group, [])
        for window in (self.window, 2 * self.window):
            lo = bisect.bisect_left(times, t - window)
            hi = bisect.bisect_right(times, t + window)
            if hi - lo >= 3:
                return median(p[1] for p in points[lo:hi])
        return None


def pit_stops(race: Race, car_class: str | None = None) -> list[PitStop]:
    fields: dict[str, FieldPace] = {}
    stops: list[PitStop] = []
    for car in race.cars_in_class(car_class):
        laps = race.car_laps(car)
        cls = laps[0].car_class
        field = fields.setdefault(cls, FieldPace(race, cls))
        for i, lap in enumerate(laps[:-1]):
            if not lap.in_pit:
                continue
            out = laps[i + 1]
            pit_time = out.pit_time if out.pit_time is not None else lap.pit_time
            loss = None
            ref_in = field.at(lap.elapsed, lap.flag) if lap.elapsed is not None else None
            ref_out = field.at(out.elapsed, out.flag) if out.elapsed is not None else None
            if ref_in and ref_out and lap.lap_time and out.lap_time:
                loss = lap.lap_time + out.lap_time - ref_in - ref_out
            stops.append(
                PitStop(
                    car=car,
                    car_class=cls,
                    in_lap=lap.lap,
                    race_time=lap.elapsed or 0.0,
                    exit_time=out.elapsed,
                    pit_time=pit_time,
                    kind=stop_kind(pit_time),
                    driver_in=driver_label(lap),
                    driver_out=driver_label(out),
                    driver_change=driver_label(lap) != driver_label(out),
                    flag=lap.flag,
                    in_lap_time=lap.lap_time,
                    out_lap_time=out.lap_time,
                    loss_vs_field=loss,
                )
            )
    stops.sort(key=lambda s: s.race_time)
    return stops


def driver_times(race: Race, car: str, until: float | None = None) -> dict[str, float]:
    """Approximate drive time per driver: sum of the lap times each driver set."""
    totals: dict[str, float] = defaultdict(float)
    for lap in race.car_laps(car):
        if until is not None and (lap.elapsed is None or lap.elapsed > until):
            break
        if lap.lap_time:
            totals[driver_label(lap)] += lap.lap_time
    return dict(totals)


def caution_periods(race: Race, merge_gap: float | None = None) -> list[dict]:
    """Caution periods inferred from the flag recorded at each line crossing.

    Under a Safety Car the field crosses the line in one bunch, then nobody
    for a whole (slow) lap, so crossings of the same flag less than about two
    green laps apart belong to the same period.
    """
    if merge_gap is None:
        green = [lap.lap_time for lap in race.laps if lap.green and lap.lap_time]
        merge_gap = max(150.0, 2.0 * median(green)) if green else 300.0
    crossings = sorted(
        (lap.elapsed, lap.flag) for lap in race.laps if lap.elapsed is not None
    )
    periods: list[dict] = []
    for t, flag in crossings:
        if flag not in CAUTION_FLAGS:
            continue
        if periods and periods[-1]["flag"] == flag and t - periods[-1]["end"] <= merge_gap:
            periods[-1]["end"] = t
        else:
            periods.append({"flag": flag, "start": t, "end": t})
    for p in periods:
        p["duration"] = p["end"] - p["start"]
    return periods


def pit_loss_by_flag(stops: list[PitStop], kind: str | None = "service") -> dict[str, dict]:
    """Median time lost to the field per stop: green vs FCY vs Safety Car."""
    groups: dict[str, list[float]] = defaultdict(list)
    for stop in stops:
        if stop.loss_vs_field is None or (kind and stop.kind != kind):
            continue
        groups[flag_group(stop.flag)].append(stop.loss_vs_field)
    return {
        k: {"stops": len(v), "median_loss_s": round(median(v), 2)}
        for k, v in sorted(groups.items())
    }


def car_report(race: Race, car: str) -> dict:
    st = stints(race, car)
    car_stops = [s for s in pit_stops(race, race.car_info(car)["class"]) if s.car == car]
    laps = race.car_laps(car)
    clean = [s.median_clean for s in st if s.median_clean]
    return {
        **race.car_info(car),
        "laps": laps[-1].lap,
        "finish_time": laps[-1].elapsed,
        "best_lap": min((lap.lap_time for lap in laps if lap.lap_time), default=None),
        "median_stint_pace": median(clean) if clean else None,
        "stints": [asdict(s) | {"duration": s.duration} for s in st],
        "pit_stops": [asdict(s) for s in car_stops],
        "driver_time": driver_times(race, car),
    }


def class_summary(race: Race, car_class: str | None = None) -> list[dict]:
    rows = []
    for car in race.cars_in_class(car_class):
        laps = race.car_laps(car)
        st = stints(race, car)
        paces = [s.median_clean for s in st if s.median_clean]
        kinds = Counter(stop_kind(lap.pit_time) for lap in laps if lap.pit_time is not None)
        rows.append(
            {
                **race.car_info(car),
                "laps": laps[-1].lap,
                "finish_time": laps[-1].elapsed,
                "best_lap": min((lap.lap_time for lap in laps if lap.lap_time), default=None),
                "median_pace": median(paces) if paces else None,
                "stops": sum(1 for lap in laps[:-1] if lap.in_pit),
                "service_stops": kinds.get("service", 0),
                "avg_stint_laps": round(sum(s.laps for s in st) / len(st), 1),
            }
        )
    rows.sort(key=lambda r: (-r["laps"], r["finish_time"] or 0))
    for pos, row in enumerate(rows, start=1):
        row["position"] = pos
    return rows


def race_overview(race: Race, car_class: str | None = None) -> dict:
    stops = pit_stops(race, car_class)
    return {
        "name": race.name,
        "duration": race.duration,
        "scheduled_duration": race.scheduled_duration,
        "classes": race.classes,
        "class": car_class,
        "cars": class_summary(race, car_class),
        "cautions": caution_periods(race),
        "pit_loss_by_flag": pit_loss_by_flag(stops),
        "stop_kinds": dict(Counter(s.kind for s in stops)),
        "pit_stop_count": len(stops),
    }
