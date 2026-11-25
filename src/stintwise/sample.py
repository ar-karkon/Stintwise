"""Generate a SYNTHETIC 6-hour race in Al Kamel Analysis CSV format.

Used for tests and for trying the dashboard before downloading real timing
files. Teams, cars and drivers are fictional and the numbers are invented;
nothing here describes a real event.
"""
from __future__ import annotations

import random
from pathlib import Path

COLUMNS = [
    "NUMBER", "DRIVER_NUMBER", "LAP_NUMBER", "LAP_TIME", "LAP_IMPROVEMENT",
    "CROSSING_FINISH_LINE_IN_PIT", "S1", "S2", "S3", "KPH", "ELAPSED", "HOUR",
    "TOP_SPEED", "DRIVER_NAME", "PIT_TIME", "CLASS", "GROUP", "TEAM",
    "MANUFACTURER", "FLAG_AT_FL",
]

CAUTIONS = [  # (start s, end s, flag)
    (1.7 * 3600, 1.7 * 3600 + 420, "FCY"),
    (3.4 * 3600, 3.4 * 3600 + 900, "SC"),
    (5.1 * 3600, 5.1 * 3600 + 300, "FCY"),
]

CLASSES = {
    "HYPERCAR": {"cars": 8, "base": 125.0, "stint": 25, "first": 1},
    "LMGT3": {"cars": 10, "base": 138.0, "stint": 22, "first": 50},
}


def _fmt(seconds: float) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:06.3f}" if h else f"{int(m)}:{s:06.3f}"


def _flag(t: float) -> str:
    for start, end, flag in CAUTIONS:
        if start <= t < end:
            return flag
    return "GF"


def generate(seed: int = 7, duration: float = 6 * 3600) -> str:
    rng = random.Random(seed)
    lines = [";".join(COLUMNS)]
    for cls, cfg in CLASSES.items():
        for k in range(cfg["cars"]):
            number = str(cfg["first"] + k * 3)
            car_pace = cfg["base"] + rng.uniform(-0.8, 1.2)
            drivers = [(i + 1, f"SYNTH {cls[:2]}{number}-{i + 1}", rng.uniform(0, 1.5))
                       for i in range(3)]
            team = f"Synthetic Racing {number}"
            maker = f"Marque {chr(65 + k % 4)}"
            clock, lap, laps_in_stint, d = 0.0, 0, 0, 0
            pit_next_lap = False
            pit_time_pending: float | None = None
            stint_len = cfg["stint"] - rng.randint(0, 2)
            while clock < duration:
                lap += 1
                laps_in_stint += 1
                driver_no, name, offset = drivers[d]
                deg = 0.03 * laps_in_stint
                lap_time = car_pace + offset + deg + rng.gauss(0, 0.35)
                if rng.random() < 0.08:
                    lap_time += rng.uniform(1.0, 5.0)  # traffic
                flag = _flag(clock + lap_time)
                if flag != "GF":
                    lap_time *= 1.6 if flag == "FCY" else 1.85
                pit_time = None
                if pit_time_pending is not None:
                    pit_time = pit_time_pending
                    lap_time += pit_time - 22.0  # pit lane replaces part of the lap
                    pit_time_pending = None
                in_pit = ""
                opportunistic = flag != "GF" and laps_in_stint >= stint_len - 5
                if pit_next_lap or laps_in_stint >= stint_len or opportunistic:
                    in_pit = "B"
                    lap_time += 9.0  # pit entry
                clock += lap_time
                s1 = lap_time * 0.33
                s2 = lap_time * 0.38
                lines.append(";".join([
                    number, str(driver_no), str(lap), _fmt(lap_time), "0", in_pit,
                    f"{s1:.3f}", f"{s2:.3f}", f"{lap_time - s1 - s2:.3f}", "180.0",
                    _fmt(clock), "", "280.0", name,
                    _fmt(pit_time) if pit_time else "", cls, "", team, maker, flag,
                ]))
                if in_pit:
                    driver_change = rng.random() < 0.7
                    stationary = 3 + 1.1 * stint_len + (20 if rng.random() < 0.6 else 0)
                    pit_time_pending = 36.0 + stationary
                    if driver_change:
                        d = (d + 1) % 3
                    laps_in_stint = 0
                    pit_next_lap = False
                    stint_len = cfg["stint"] - rng.randint(0, 2)
    return "\n".join(lines) + "\n"


LMC_CAUTIONS = [
    (18 * 60, 21 * 60, "FCY"),
    (56 * 60, 63 * 60, "SC"),
    (91 * 60, 93.5 * 60, "FCY"),
]
LMC_CLASSES = {
    "LMP3 Pro/Am": {"cars": 12, "base": 103.0, "first": 2},
    "GT3": {"cars": 8, "base": 108.5, "first": 60},
}


def generate_lmc(seed: int = 3, duration: float = 2 * 3600) -> str:
    """A 2-hour, two-driver race with one mandatory driver-change stop.

    The stop has a minimum pit-lane time (about 2:45) and must be taken in a
    window from 50 to 62 minutes; most teams take it under the Safety Car
    when one comes out inside the window.
    """
    rng = random.Random(seed)
    lines = [";".join(COLUMNS)]

    def flag_at(t: float) -> str:
        for start, end, flag in LMC_CAUTIONS:
            if start <= t < end:
                return flag
        return "GF"

    for cls, cfg in LMC_CLASSES.items():
        for k in range(cfg["cars"]):
            number = str(cfg["first"] + k * 3)
            car_pace = cfg["base"] + rng.uniform(-0.6, 1.4)
            drivers = [(1, f"SYNTH AM-{number}", rng.uniform(1.0, 3.2)),
                       (2, f"SYNTH PRO-{number}", rng.uniform(0.0, 0.6))]
            team = f"Synthetic Motorsport {number}"
            maker = "Prototype" if cls.startswith("LMP3") else f"GT Marque {chr(65 + k % 4)}"
            planned_stop = rng.uniform(51, 60) * 60
            takes_caution = rng.random() < 0.7
            clock, lap, d, stopped = 0.0, 0, 0, False
            pending: float | None = None
            while clock < duration:
                lap += 1
                driver_no, name, offset = drivers[d]
                lap_time = car_pace + offset + rng.gauss(0, 0.3)
                if rng.random() < 0.07:
                    lap_time += rng.uniform(1.0, 4.0)
                flag = flag_at(clock + lap_time)
                if flag != "GF":
                    lap_time *= 1.55 if flag == "FCY" else 1.75
                pit_time = None
                if pending is not None:
                    # The pit lane replaces ~20 s of track, which is slower under a caution.
                    pit_time, pending = pending, None
                    factor = {"FCY": 1.55, "SC": 1.75}.get(flag, 1.0)
                    lap_time += pit_time - 20.0 * factor
                in_pit = ""
                t_end = clock + lap_time
                window = 50 * 60 <= t_end <= 62 * 60
                caution_call = window and flag != "GF" and takes_caution
                if not stopped and (t_end >= planned_stop or caution_call):
                    in_pit, stopped = "B", True
                    lap_time += 8.0
                    pending = 162.0 + rng.uniform(0, 10)
                    d = 1
                clock += lap_time
                s1, s2 = lap_time * 0.31, lap_time * 0.37
                lines.append(";".join([
                    number, str(driver_no), str(lap), _fmt(lap_time), "0", in_pit,
                    f"{s1:.3f}", f"{s2:.3f}", f"{lap_time - s1 - s2:.3f}", "160.0",
                    _fmt(clock), "", "265.0", name,
                    _fmt(pit_time) if pit_time else "", cls, "", team, maker, flag,
                ]))
    return "\n".join(lines) + "\n"


def write_sample(path: str | Path, seed: int = 7, profile: str = "wec") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = generate_lmc(seed) if profile == "lmc" else generate(seed)
    path.write_text(text, encoding="utf-8")
    return path
