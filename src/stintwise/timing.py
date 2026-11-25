"""Parse lap-by-lap endurance timing exports (Al Kamel "Analysis" CSV format).

FIA WEC, ELMS, Asian Le Mans and IMSA publish per-session lap analysis files
produced by Al Kamel Systems. They are semicolon separated, one row per car
lap, with columns such as::

    NUMBER; DRIVER_NUMBER; LAP_NUMBER; LAP_TIME; CROSSING_FINISH_LINE_IN_PIT;
    S1; S2; S3; ELAPSED; HOUR; DRIVER_NAME; PIT_TIME; CLASS; TEAM;
    MANUFACTURER; FLAG_AT_FL; ...

Column names are matched case-insensitively and with surrounding whitespace
stripped, because header formatting differs slightly between seasons.
Only the columns needed for strategy analysis are required.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# Al Kamel flag codes at the finish line, normalised. "SF" is the Safety Car.
FLAG_MAP = {
    "": "GF", "G": "GF", "GF": "GF", "GREEN": "GF",
    "FF": "FF", "CHEQUERED": "FF",
    "SF": "SC", "SC": "SC",
    "FCY": "FCY",
    "RF": "RED", "RED": "RED",
}
GREEN_FLAGS = {"GF", "FF"}
CAUTION_FLAGS = {"FCY", "SC", "RED"}


def normalize_flag(value: str | None) -> str:
    code = (value or "").strip().upper()
    return FLAG_MAP.get(code, code)

REQUIRED = ("NUMBER", "LAP_NUMBER", "LAP_TIME")


def parse_duration(value: str | None) -> float | None:
    """Parse ``"1:47.123"``, ``"47.123"`` or ``"1:02:03.456"`` into seconds."""
    if value is None:
        return None
    text = value.strip().replace(",", ".")
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(float(value.strip()))
    except ValueError:
        return None


@dataclass(frozen=True)
class Lap:
    car: str
    lap: int
    lap_time: float | None
    elapsed: float | None
    driver_number: int | None = None
    driver: str = ""
    in_pit: bool = False
    pit_time: float | None = None
    flag: str = "GF"
    car_class: str = ""
    team: str = ""
    manufacturer: str = ""

    @property
    def green(self) -> bool:
        return self.flag in GREEN_FLAGS


@dataclass
class Race:
    name: str
    laps: list[Lap] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cache: dict = {}  # derived results (stops, costs), filled by analysis code
        self.laps.sort(key=lambda lap: (lap.car, lap.lap))
        self._by_car: dict[str, list[Lap]] = defaultdict(list)
        for lap in self.laps:
            self._by_car[lap.car].append(lap)

    @property
    def cars(self) -> list[str]:
        return sorted(self._by_car, key=_car_sort_key)

    def car_laps(self, car: str) -> list[Lap]:
        if car not in self._by_car:
            raise KeyError(f"Unknown car {car!r}")
        return self._by_car[car]

    @property
    def classes(self) -> list[str]:
        return sorted({lap.car_class for lap in self.laps if lap.car_class})

    def cars_in_class(self, car_class: str | None) -> list[str]:
        if not car_class:
            return self.cars
        return [c for c in self.cars if self._by_car[c][0].car_class == car_class]

    def car_info(self, car: str) -> dict[str, str]:
        first = self.car_laps(car)[0]
        return {"car": car, "class": first.car_class, "team": first.team,
                "manufacturer": first.manufacturer}

    @property
    def duration(self) -> float:
        """Race clock at the last line crossing."""
        return max((lap.elapsed or 0.0) for lap in self.laps) if self.laps else 0.0

    @property
    def scheduled_duration(self) -> float:
        """Best guess of the scheduled race length, to the nearest 5 minutes.

        The race ends at the leader's first crossing after the clock runs out, and the
        timing clock also includes the formation lap, so about 1.5 green laps are
        taken off the last crossing before rounding.
        """
        green = sorted(lap.lap_time for lap in self.laps if lap.green and lap.lap_time)
        typical = green[len(green) // 2] if green else 0.0
        return max(300.0, round((self.duration - 1.5 * typical) / 300) * 300)

    @property
    def red_flagged(self) -> bool:
        return any(lap.flag == "RED" for lap in self.laps)

    @property
    def red_flag_time(self) -> float:
        """Time the race was stopped under red flags (the race clock stops, the timing
        clock does not): the very long lap most cars share at a red flag."""
        if "red_flag_time" in self.cache:
            return self.cache["red_flag_time"]
        if not any(lap.flag == "RED" for lap in self.laps):
            self.cache["red_flag_time"] = 0.0
            return 0.0
        green = sorted(lap.lap_time for lap in self.laps if lap.green and lap.lap_time)
        typical = green[len(green) // 2] if green else 0.0
        stops = []
        for laps in self._by_car.values():
            # a stoppage the race resumed from (not a race that ended under red)
            long = [lap.lap_time for lap in laps[:-2] if lap.lap_time
                    and lap.lap_time > 5 * typical and lap.pit_time is None]
            if long:
                stops.append(max(long) - typical)
        stops.sort()
        value = stops[len(stops) // 2] if len(stops) >= max(3, len(self._by_car) // 2) else 0.0
        self.cache["red_flag_time"] = value
        return value


def _car_sort_key(car: str) -> tuple[int, str]:
    digits = "".join(ch for ch in car if ch.isdigit())
    return (int(digits) if digits else 10**9, car)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode timing file")


def parse_rows(rows: Iterable[dict[str, str]], name: str) -> Race:
    laps: list[Lap] = []
    elapsed_by_car: dict[str, float] = defaultdict(float)
    for raw in rows:
        row = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items()}
        car = row.get("NUMBER", "")
        lap_no = _int(row.get("LAP_NUMBER"))
        if not car or lap_no is None:
            continue
        lap_time = parse_duration(row.get("LAP_TIME"))
        elapsed = parse_duration(row.get("ELAPSED"))
        if elapsed is None and lap_time is not None:
            elapsed_by_car[car] += lap_time
            elapsed = elapsed_by_car[car]
        laps.append(
            Lap(
                car=car,
                lap=lap_no,
                lap_time=lap_time,
                elapsed=elapsed,
                driver_number=_int(row.get("DRIVER_NUMBER")),
                driver=row.get("DRIVER_NAME", ""),
                in_pit=row.get("CROSSING_FINISH_LINE_IN_PIT", "").upper() == "B",
                pit_time=parse_duration(row.get("PIT_TIME")),
                flag=normalize_flag(row.get("FLAG_AT_FL")),
                car_class=row.get("CLASS", ""),
                team=row.get("TEAM", ""),
                manufacturer=row.get("MANUFACTURER", ""),
            )
        )
    if not laps:
        raise ValueError("No lap rows found; is this an Al Kamel Analysis CSV?")
    return Race(name=name, laps=laps)


def parse_text(text: str, name: str = "race") -> Race:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter=";")
    header = {(h or "").strip().upper() for h in (reader.fieldnames or [])}
    missing = [col for col in REQUIRED if col not in header]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    return parse_rows(reader, name)


def load_csv(path: str | Path, name: str | None = None) -> Race:
    path = Path(path)
    return parse_text(_decode(path.read_bytes()), name or path.stem)
