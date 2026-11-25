"""Official classification files (Al Kamel ``03_Classification`` / ``05_Classification``).

Used to check the parser against official results and to learn the minimum drive
time per driver and each driver's category (Platinum / Gold / Silver / Bronze).
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from .timing import parse_duration


@dataclass
class OfficialDriver:
    name: str  # "First LAST", as DRIVER_NAME in the lap analysis
    category: str  # P, G, S, B (or "" when not published)
    min_drive_s: float | None


@dataclass
class OfficialEntry:
    car: str
    position: int | None  # overall
    status: str
    laps: int | None
    car_class: str
    total_time: float | None = None
    drivers: list[OfficialDriver] = field(default_factory=list)

    @property
    def classified(self) -> bool:
        return self.status.lower().startswith("classified")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode classification")


def parse_classification(text: str) -> dict[str, OfficialEntry]:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    if not rows:
        return {}
    header = [h.strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    def cell(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    entries: dict[str, OfficialEntry] = {}
    for row in rows[1:]:
        car = cell(row, "NUMBER")
        if not car:
            continue
        pos = cell(row, "POSITION")
        laps = cell(row, "LAPS")
        entry = OfficialEntry(
            car=car,
            position=int(pos) if pos.isdigit() else None,
            status=cell(row, "STATUS"),
            laps=int(laps) if laps.isdigit() else None,
            car_class=cell(row, "CLASS"),
            total_time=parse_duration(cell(row, "TOTAL_TIME").replace("'", ":")),
        )
        for k in range(1, 7):
            last = cell(row, f"DRIVER{k}_SECONDNAME")
            if not last:
                continue
            first = cell(row, f"DRIVER{k}_FIRSTNAME")
            min_drive = parse_duration(cell(row, f"DRIVER{k}_*Extra 4"))
            entry.drivers.append(OfficialDriver(
                name=f"{first} {last}".strip(),
                category=cell(row, f"DRIVER{k}_LICENSE").upper(),
                min_drive_s=min_drive if min_drive else None,
            ))
        entries[car] = entry
    return entries


def load_classification(path: str | Path) -> dict[str, OfficialEntry]:
    return parse_classification(_decode(Path(path).read_bytes()))


def official_for(race_path: str | Path) -> dict[str, OfficialEntry] | None:
    """The classification stored next to a race file (``official/<same name>``)."""
    race_path = Path(race_path)
    path = race_path.parent / "official" / race_path.name
    return load_classification(path) if path.is_file() else None


def min_drive_time(entries: dict[str, OfficialEntry]) -> float | None:
    """The minimum drive time per driver published for this race (most common value)."""
    from collections import Counter

    values = Counter(d.min_drive_s for e in entries.values() for d in e.drivers if d.min_drive_s)
    return values.most_common(1)[0][0] if values else None


def penalised_cars(entries: dict[str, OfficialEntry], finish_times: dict[str, float],
                   tolerance: float = 2.0) -> set[str]:
    """Cars whose official total time is longer than their timing shows: time penalties.

    The timing clock and the official race clock differ by a constant (formation lap),
    taken as the median difference over all cars.
    """
    diffs = {car: e.total_time - finish_times[car] for car, e in entries.items()
             if e.total_time and car in finish_times}
    if len(diffs) < 3:
        return set()
    values = sorted(diffs.values())
    offset = values[len(values) // 2]
    return {car for car, d in diffs.items() if d - offset > tolerance}
