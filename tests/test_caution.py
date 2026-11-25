import pytest

from stintwise.caution import CautionCall, evaluate

BASE = dict(green_lap_s=138, caution_lap_s=220, pit_lane_transit_s=58, track_equivalent_s=24,
            stationary_s=28, max_stint_laps=22, race_time_left_s=7000, caution_time_left_s=240)


def test_late_in_stint_pit_under_caution():
    r = evaluate(CautionCall(laps_into_stint=17, **BASE))
    assert r["gain_if_pit_now_s"] > 0 and r["verdict"].startswith("PIT NOW")
    assert r["caution_stop_loss_s"] < r["green_stop_loss_s"]


def test_early_in_stint_stay_out_when_it_adds_a_stop():
    r = evaluate(CautionCall(laps_into_stint=3, **BASE))
    assert r["pit_now"]["remaining_stops"] > r["stay_out"]["remaining_stops"]
    assert r["gain_if_pit_now_s"] < 0 and r["verdict"].startswith("STAY OUT")


def test_no_stop_needed_to_finish():
    r = evaluate(CautionCall(laps_into_stint=5, **{**BASE, "race_time_left_s": 1000}))
    assert r["stay_out"]["remaining_stops"] == 0
    assert "reach the flag" in r["verdict"]


def test_short_caution_only_partly_helps():
    full = evaluate(CautionCall(laps_into_stint=17, **BASE))
    short = evaluate(CautionCall(laps_into_stint=17, **{**BASE, "caution_time_left_s": 20}))
    assert short["caution_coverage"] < 1
    assert full["caution_stop_loss_s"] < short["caution_stop_loss_s"] <= full["green_stop_loss_s"]


def test_validation():
    with pytest.raises(ValueError):
        evaluate(CautionCall(laps_into_stint=30, **BASE))
    with pytest.raises(ValueError):
        evaluate(CautionCall(laps_into_stint=1, **{**BASE, "caution_lap_s": 100}))
