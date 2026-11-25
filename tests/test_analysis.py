import pytest

from stintwise import analysis
from stintwise.sample import generate
from stintwise.timing import Lap, Race


def build_race() -> Race:
    laps = []
    t = 0.0
    # Car 1: 3 stints (stop after lap 8 under green, after lap 15 under FCY).
    for n in range(1, 21):
        flag = "FCY" if 14 <= n <= 16 else "GF"
        lap_time = 100.0 + 0.1 * n
        if flag == "FCY":
            lap_time = 160.0
        pit_time = 90.0 if n in (9, 16) else None
        if pit_time:
            lap_time += 40.0
        t += lap_time
        driver = 1 if n <= 8 else 2
        laps.append(Lap(car="1", lap=n, lap_time=lap_time, elapsed=t, driver_number=driver,
                        driver=f"D{driver}", in_pit=n in (8, 15), pit_time=pit_time, flag=flag,
                        car_class="LMGT3", team="T1"))
    # Field cars that never pit, to provide a reference pace.
    for car in ("2", "3", "4"):
        t = 0.5 * int(car)
        for n in range(1, 21):
            lap_time = 160.0 if 14 <= n <= 16 else 100.0
            t += lap_time
            laps.append(Lap(car=car, lap=n, lap_time=lap_time, elapsed=t,
                            flag="FCY" if 14 <= n <= 16 else "GF", car_class="LMGT3"))
    return Race(name="unit", laps=laps)


def test_stints_split_at_pit_entry():
    st = analysis.stints(build_race(), "1")
    assert [(s.first_lap, s.last_lap) for s in st] == [(1, 8), (9, 15), (16, 20)]
    assert [s.driver for s in st] == ["D1", "D2", "D2"]
    assert st[0].deg_per_lap == pytest.approx(0.1)
    assert st[1].start_time == pytest.approx(st[0].end_time)


def test_pit_stops_driver_change_flag_and_loss():
    stops = [s for s in analysis.pit_stops(build_race()) if s.car == "1"]
    assert [s.in_lap for s in stops] == [8, 15]
    first, second = stops
    assert first.driver_change and not second.driver_change
    assert first.pit_time == 90.0 and first.flag == "GF" and first.kind == "service"
    assert second.flag == "FCY"
    # Green stop: in-lap 100.8 + out-lap 140.9 minus 2 x 100.
    assert first.loss_vs_field == pytest.approx(100.8 + 140.9 - 200.0)
    # FCY stop is measured against FCY laps of the field.
    assert second.loss_vs_field == pytest.approx(160.0 + 200.0 - 320.0)
    by_flag = analysis.pit_loss_by_flag(stops)
    assert set(by_flag) == {"GREEN", "FCY"}


def test_caution_periods_and_driver_time():
    race = build_race()
    periods = analysis.caution_periods(race)
    assert len(periods) == 1 and periods[0]["flag"] == "FCY"
    times = analysis.driver_times(race, "1")
    assert set(times) == {"D1", "D2"}
    assert sum(times.values()) == pytest.approx(race.car_laps("1")[-1].elapsed)


def test_overview_on_synthetic_race():
    from stintwise.timing import parse_text

    race = parse_text(generate(seed=3), "synthetic")
    overview = analysis.race_overview(race, "LMGT3")
    assert len(overview["cars"]) == 10
    assert [c["position"] for c in overview["cars"]] == list(range(1, 11))
    assert all(c["class"] == "LMGT3" for c in overview["cars"])
    assert overview["cautions"] and "GREEN" in overview["pit_loss_by_flag"]
    report = analysis.car_report(race, overview["cars"][0]["car"])
    assert len(report["stints"]) == len(report["pit_stops"]) + 1
