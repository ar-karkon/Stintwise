"""Pit now under a caution (FCY / Safety Car) or stay out?

The classic endurance call: a Full Course Yellow comes out with the car part
way through its fuel stint. Pitting now costs less time relative to the
field, because everyone else is circulating slowly while you are in the pit
lane, but it cuts the current stint short, which can mean an extra stop
before the flag.

The model is deliberately transparent:

* ``green_loss``  = pit lane transit + stationary - the track time the field
  covers at racing speed over the same stretch (``track_equivalent_s``);
* ``caution_loss`` = the same, but the field covers that stretch at caution
  speed (``track_equivalent_s * caution_lap_s / green_lap_s``). If the caution
  is expected to end before the stop is complete, only that fraction of the
  stop benefits;
* remaining stops for each option are counted from the fuel/energy you would
  have left and the laps still to run.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CautionCall:
    green_lap_s: float  # lap time at racing speed
    caution_lap_s: float  # lap time under FCY / SC
    pit_lane_transit_s: float  # time from pit entry to pit exit at the speed limit (no stop)
    track_equivalent_s: float  # time the same stretch takes on track at racing speed
    stationary_s: float  # expected stationary time for this stop
    laps_into_stint: int  # laps already done on this tank / energy allocation
    max_stint_laps: int
    race_time_left_s: float
    caution_time_left_s: float  # expected remaining caution time

    def validate(self) -> None:
        if not 0 < self.green_lap_s <= self.caution_lap_s:
            raise ValueError("caution_lap_s must be >= green_lap_s > 0")
        if not 0 <= self.laps_into_stint <= self.max_stint_laps:
            raise ValueError("laps_into_stint must be between 0 and max_stint_laps")
        if self.track_equivalent_s >= self.pit_lane_transit_s + self.stationary_s:
            raise ValueError("Track equivalent must be shorter than pit transit + stationary")
        if min(self.race_time_left_s, self.caution_time_left_s, self.stationary_s) < 0:
            raise ValueError("Times must be non-negative")


def _stops_needed(laps_to_go: float, fuel_laps: float, max_stint: int) -> int:
    if laps_to_go <= fuel_laps:
        return 0
    return math.ceil((laps_to_go - fuel_laps) / max_stint)


def evaluate(call: CautionCall) -> dict:
    call.validate()
    stop_duration = call.pit_lane_transit_s + call.stationary_s
    green_loss = stop_duration - call.track_equivalent_s
    slow_factor = call.caution_lap_s / call.green_lap_s
    full_caution_loss = stop_duration - call.track_equivalent_s * slow_factor
    covered = min(1.0, call.caution_time_left_s / stop_duration) if stop_duration else 1.0
    caution_loss = covered * full_caution_loss + (1 - covered) * green_loss
    caution_loss = max(caution_loss, 0.0)

    laps_to_go = call.race_time_left_s / call.green_lap_s
    fuel_left = call.max_stint_laps - call.laps_into_stint

    stops_stay = _stops_needed(laps_to_go, fuel_left, call.max_stint_laps)
    stops_pit = _stops_needed(laps_to_go, call.max_stint_laps, call.max_stint_laps)

    cost_stay = stops_stay * green_loss
    cost_pit = caution_loss + stops_pit * green_loss
    gain = cost_stay - cost_pit
    if stops_stay == 0 and laps_to_go <= fuel_left:
        verdict = "STAY OUT: you can reach the flag without stopping again"
    elif gain > 0:
        verdict = f"PIT NOW: saves about {gain:.1f}s over the rest of the race"
    else:
        verdict = f"STAY OUT: pitting now costs about {-gain:.1f}s over the rest of the race"
    return {
        "inputs": asdict(call),
        "green_stop_loss_s": round(green_loss, 2),
        "caution_stop_loss_s": round(caution_loss, 2),
        "caution_coverage": round(covered, 3),
        "laps_to_go": round(laps_to_go, 1),
        "fuel_laps_left": fuel_left,
        "stay_out": {"remaining_stops": stops_stay, "time_lost_s": round(cost_stay, 2)},
        "pit_now": {"remaining_stops": stops_pit + 1, "time_lost_s": round(cost_pit, 2)},
        "gain_if_pit_now_s": round(gain, 2),
        "verdict": verdict,
        "assumptions": [
            "Field speed under caution is uniform; FCY/SC bunching effects are ignored.",
            "Remaining green stops are assumed to cost the same green pit loss.",
            "Safety Car pit-lane rules and closures differ by championship: check them.",
        ],
    }


def call_from_dict(data: dict) -> CautionCall:
    return CautionCall(**data)
