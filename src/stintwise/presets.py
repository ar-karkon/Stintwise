"""Example race set-ups for the planner.

These numbers are ILLUSTRATIVE starting points chosen to be in a plausible
range for each class. They are not official figures: lap times depend on
circuit and Balance of Performance, stint length on the energy/fuel
allocation, and drive-time limits and tyre allocations on the current
Sporting Regulations of each championship. Replace them with your own data.
"""
from __future__ import annotations

HOUR = 3600.0

PRESETS: dict[str, dict] = {
    "lmc-lmp3-proam-2h": {
        "label": "Le Mans Cup · LMP3 Pro/Am · 2 hours (fitted to 2026 timing)",
        "duration_s": 2 * HOUR,
        "base_lap_s": 102.5,
        "max_stint_laps": 35,  # driver-change window closes ~1h in
        "max_consecutive_stints": 1,
        "drivers": [
            {"name": "Bronze", "pace_offset_s": 1.5, "min_drive_s": 0.75 * HOUR},
            {"name": "Pro", "pace_offset_s": 0.0, "min_drive_s": 0.75 * HOUR},
        ],
        "pit": {"lane_loss_s": 30.0, "refuel_base_s": 0.0, "refuel_per_lap_s": 0.0,
                "tyre_change_s": 0.0, "driver_change_s": 0.0, "min_stop_loss_s": 170.0,
                "tyres_parallel": True, "driver_change_parallel": True},
        "tyres": {"deg_s_per_lap": 0.02, "deg_quad_s": 0.0, "warmup_s": 1.0,
                  "sets_available": 2, "max_stints_per_set": 2},
    },
    "example-lmgt3-6h": {
        "label": "LMGT3 · 6 hours · Pro/Silver/Bronze line-up (example)",
        "duration_s": 6 * HOUR,
        "base_lap_s": 138.0,
        "max_stint_laps": 22,
        "max_consecutive_stints": 3,
        "drivers": [
            {"name": "Pro", "pace_offset_s": 0.0, "min_drive_s": 0.75 * HOUR,
             "max_drive_s": 4 * HOUR},
            {"name": "Silver", "pace_offset_s": 0.6, "min_drive_s": 0.75 * HOUR,
             "max_drive_s": 4 * HOUR},
            {"name": "Bronze", "pace_offset_s": 1.8, "min_drive_s": 1.75 * HOUR,
             "max_drive_s": 4 * HOUR},
        ],
        "pit": {"lane_loss_s": 32.0, "refuel_base_s": 4.0, "refuel_per_lap_s": 1.1,
                "tyre_change_s": 18.0, "driver_change_s": 14.0,
                "tyres_parallel": False, "driver_change_parallel": True},
        "tyres": {"deg_s_per_lap": 0.035, "deg_quad_s": 0.0004, "warmup_s": 1.5,
                  "sets_available": 5, "max_stints_per_set": 3},
    },
    "example-hypercar-6h": {
        "label": "Hypercar · 6 hours · three pro drivers (example)",
        "duration_s": 6 * HOUR,
        "base_lap_s": 125.0,
        "max_stint_laps": 25,
        "max_consecutive_stints": 3,
        "drivers": [
            {"name": "Driver A", "pace_offset_s": 0.0, "min_drive_s": 1.0 * HOUR,
             "max_drive_s": 4 * HOUR},
            {"name": "Driver B", "pace_offset_s": 0.15, "min_drive_s": 1.0 * HOUR,
             "max_drive_s": 4 * HOUR},
            {"name": "Driver C", "pace_offset_s": 0.3, "min_drive_s": 1.0 * HOUR,
             "max_drive_s": 4 * HOUR},
        ],
        "pit": {"lane_loss_s": 30.0, "refuel_base_s": 3.0, "refuel_per_lap_s": 1.0,
                "tyre_change_s": 22.0, "driver_change_s": 14.0,
                "tyres_parallel": False, "driver_change_parallel": True},
        "tyres": {"deg_s_per_lap": 0.03, "deg_quad_s": 0.0003, "warmup_s": 2.0,
                  "sets_available": 5, "max_stints_per_set": 3},
    },
    "example-hypercar-24h": {
        "label": "Hypercar · 24 hours · three pro drivers (example)",
        "duration_s": 24 * HOUR,
        "base_lap_s": 210.0,
        "max_stint_laps": 14,
        "max_consecutive_stints": 4,
        "drivers": [
            {"name": "Driver A", "pace_offset_s": 0.0, "min_drive_s": 6 * HOUR,
             "max_drive_s": 14 * HOUR},
            {"name": "Driver B", "pace_offset_s": 0.2, "min_drive_s": 6 * HOUR,
             "max_drive_s": 14 * HOUR},
            {"name": "Driver C", "pace_offset_s": 0.4, "min_drive_s": 6 * HOUR,
             "max_drive_s": 14 * HOUR},
        ],
        "pit": {"lane_loss_s": 36.0, "refuel_base_s": 3.0, "refuel_per_lap_s": 2.0,
                "tyre_change_s": 22.0, "driver_change_s": 14.0,
                "tyres_parallel": False, "driver_change_parallel": True},
        "tyres": {"deg_s_per_lap": 0.04, "deg_quad_s": 0.0008, "warmup_s": 2.5,
                  "sets_available": 14, "max_stints_per_set": 3},
    },
    "example-lmp2-4h": {
        "label": "LMP2 · 4 hours · Pro/Am line-up (example)",
        "duration_s": 4 * HOUR,
        "base_lap_s": 100.0,
        "max_stint_laps": 36,
        "max_consecutive_stints": 2,
        "drivers": [
            {"name": "Pro", "pace_offset_s": 0.0},
            {"name": "Silver", "pace_offset_s": 0.5, "min_drive_s": 0.5 * HOUR},
            {"name": "Bronze", "pace_offset_s": 1.6, "min_drive_s": 1.0 * HOUR},
        ],
        "pit": {"lane_loss_s": 24.0, "refuel_base_s": 4.0, "refuel_per_lap_s": 0.8,
                "tyre_change_s": 16.0, "driver_change_s": 12.0,
                "tyres_parallel": False, "driver_change_parallel": True},
        "tyres": {"deg_s_per_lap": 0.03, "deg_quad_s": 0.0002, "warmup_s": 1.5,
                  "sets_available": 4, "max_stints_per_set": 2},
    },
}


def preset(name: str) -> dict:
    if name not in PRESETS:
        raise KeyError(f"Unknown preset {name!r}; choose from {', '.join(PRESETS)}")
    data = dict(PRESETS[name])
    data.pop("label", None)
    return data
