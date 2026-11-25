import pytest

from stintwise.live import RaceContext, Rules, car_state, drive_time_status, race_events, race_state
from stintwise.sample import generate
from stintwise.timing import Lap, Race, parse_text


@pytest.fixture(scope="module")
def race():
    return parse_text(generate(seed=5), "synthetic")


def test_state_uses_only_past_crossings(race):
    t = 3 * 3600
    state = race_state(race, t, "LMGT3", focus="50")
    for c in state["cars"]:
        assert c["last_elapsed"] <= t
    # Positions are consistent with laps and crossing time.
    order = [(-c["laps"], c["last_elapsed"]) for c in state["cars"]]
    assert order == sorted(order)
    assert state["cars"][0]["gap_s"] == 0
    assert all(c["gap_s"] >= 0 for c in state["cars"])
    assert state["focus"]["car"] == "50"


def test_state_is_stable_against_future_data(race):
    """Changing laps after t must not change the state at t."""
    t = 2 * 3600
    before = race_state(race, t, "LMGT3")
    future_free = Race(name="cut", laps=[lap for lap in race.laps if lap.elapsed <= t])
    after = race_state(future_free, t, "LMGT3", rules={"duration_s": race.scheduled_duration})
    strip = lambda s: [(c["car"], c["laps"], c["gap_s"], c["stint_laps"]) for c in s["cars"]]  # noqa: E731
    assert strip(before) == strip(after)


def test_net_position_counts_owed_stops(race):
    t = 1.5 * 3600
    rules = Rules(required_service_stops=6, service_loss_s=60)
    state = race_state(race, t, "LMGT3", rules=rules)
    for c in state["cars"]:
        assert c["remaining_service"] == max(0, 6 - c["service_stops"])
        owed = c["remaining_service"] * state["service_loss_s"]
        assert c["net_time_s"] == pytest.approx(c["gap_s"] + owed)
    positions = sorted(c["net_position"] for c in state["cars"])
    assert positions == list(range(1, len(state["cars"]) + 1))


def test_drive_time_status_levels():
    rules = Rules(drivers={"A": {"min_drive_s": 1800}, "B": {"min_drive_s": 3600}})
    ok = drive_time_status(rules, {"A": 2000}, "A", 1000, 7200)
    assert ok["status"] == "ok" and ok["latest_change_time"] == 7200 - 3600 - 180
    soon = drive_time_status(rules, {"A": 3000}, "A", 3100, 7200)
    assert soon["status"] == "change_soon"
    now = drive_time_status(rules, {"A": 3300}, "A", 3300, 7200)
    assert now["status"] == "change_now"
    late = drive_time_status(rules, {"A": 4000}, "A", 4000, 7200)
    assert late["status"] == "impossible"


def _tiny_race(flags):
    laps = []
    for car, offset in (("1", 0.0), ("2", 1.0), ("3", 2.0)):
        t = offset
        for n, flag in enumerate(flags, start=1):
            lt = 100.0 if flag == "GF" else 160.0
            t += lt
            laps.append(Lap(car=car, lap=n, lap_time=lt, elapsed=t, flag=flag, car_class="C",
                            driver="A" if car == "1" else "X"))
    return Race(name="tiny", laps=laps)


def test_caution_call_respects_window_and_driver_minimum():
    race = _tiny_race(["GF"] * 10 + ["FCY"] * 3 + ["GF"] * 10)
    events = race_events(race, "C", "1", Rules(required_service_stops=1, service_loss_s=60,
                                               window_open_s=5000))
    call = next(e for e in events if e["type"] == "caution_call")
    assert call["data"]["action"] == "stay" and "window" in call["text"]

    events = race_events(race, "C", "1", Rules(required_service_stops=1, service_loss_s=60))
    call = next(e for e in events if e["type"] == "caution_call")
    assert call["data"]["action"] == "pit" and call["data"]["gain_s"] > 5

    rules = Rules(required_service_stops=1, service_loss_s=60,
                  drivers={"A": {"min_drive_s": 3000}, "B": {"min_drive_s": 0}})
    call = next(e for e in race_events(race, "C", "1", rules) if e["type"] == "caution_call")
    assert call["data"]["action"] == "stay" and "short" in call["text"]


def test_events_are_time_ordered_and_bounded(race):
    events = race_events(race, "LMGT3", "50", until=4 * 3600)
    times = [e["t"] for e in events]
    assert times == sorted(times) and max(times) <= 4 * 3600
    kinds = {e["type"] for e in events}
    assert {"caution", "pit_in", "pit_out", "caution_call"} <= kinds


def test_car_state_drive_time_includes_running_lap(race):
    ctx = RaceContext(race, "LMGT3")
    st = car_state(ctx, "50", 1000.0)
    assert sum(st["drive_time"].values()) == pytest.approx(1000.0)


def test_learned_caution_loss_is_used_before_estimate():
    race = _tiny_race(["GF"] * 10 + ["SC"] * 3 + ["GF"] * 10)
    rules = Rules(required_service_stops=1, service_loss_s=170, caution_loss_s={"SC": 100})
    call = next(e for e in race_events(race, "C", "1", rules) if e["type"] == "caution_call")
    assert call["data"]["gain_s"] == pytest.approx(70)
    assert "earlier races" in call["data"]["basis"]
