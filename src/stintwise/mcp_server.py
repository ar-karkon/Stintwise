"""MCP server: use Stintwise from Claude Desktop or Claude Code.

The AI runs on the user's own Claude plan; this server only provides the
race-strategy tools. Register it with::

    claude mcp add stintwise -- stintwise mcp            # Claude Code
    # Claude Desktop: add {"command": "stintwise", "args": ["mcp"]} to
    # claude_desktop_config.json under "mcpServers".

Races are Al Kamel Analysis CSV files: pass a path, or the id of a file in
``$STINTWISE_DATA`` (default ``data/races``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import analysis, store
from .caution import CautionCall, evaluate
from .cli import parse_clock
from .debrief import debrief, to_markdown
from .fit import fit_rules, fit_spec
from .live import RaceContext, Rules, race_events, race_state
from .planner import InfeasiblePlan, plan, spec_from_dict
from .presets import PRESETS, preset
from .timing import Race, load_csv

INSTRUCTIONS = """\
You are the race engineer and strategist of an endurance racing team
(Le Mans Cup, ELMS, WEC, IMSA style races). Use the Stintwise tools for every
number: gaps, stop losses, drive times, gains. Never invent or estimate a
number the tools did not return. Answer like a calm pit wall: the call first,
then the reason with the key numbers, then the risk. Say which race time the
numbers refer to. Reply in the user's language."""

mcp = FastMCP("stintwise", instructions=INSTRUCTIONS)


def _race(race: str) -> Race:
    path = Path(race).expanduser()
    if path.suffix.lower() == ".csv" and path.is_file():
        return load_csv(path)
    try:
        return store.get_race(race)
    except KeyError as exc:
        known = ", ".join(r["id"] for r in store.list_races())
        raise ValueError(f"Unknown race {race!r}. Known races: {known}") from exc


def _rules(rules: dict | str | None) -> Rules:
    if isinstance(rules, str):
        rules = json.loads(rules) if rules.strip() else {}
    rules = rules or {}
    return Rules.from_dict(rules.get("rules", rules))


def _time(at: str | float) -> float:
    return float(at) if isinstance(at, (int, float)) else parse_clock(str(at))


@mcp.tool()
def list_races() -> list[dict]:
    """Races available to analyse (the synthetic demo plus CSV files in the data folder)."""
    return store.list_races()


@mcp.tool()
def race_overview(race: str, car_class: str | None = None) -> dict:
    """Classification, caution periods and pit-stop cost by flag for a race.

    race: race id from list_races, or a path to an Al Kamel Analysis CSV.
    car_class: e.g. "LMP3 Pro/Am", "GT3", "HYPERCAR"; omit for all classes.
    """
    return analysis.race_overview(_race(race), car_class)


@mcp.tool()
def race_state_at(race: str, at: str, car_class: str | None = None, focus: str | None = None,
                  rules: dict | None = None) -> dict:
    """Pit-wall view at a race time: positions, gaps, stints, stops owed, net order.

    at: race time such as "55m", "1h05m", "1:05:00" or seconds.
    focus: our car number, to get its drive-time status.
    rules: optional {required_service_stops, window_open_s, window_close_s,
      service_loss_s, max_stint_laps, duration_s, drivers: {name: {min_drive_s, max_drive_s}}}.
      Use fit_race_rules on earlier races to get them.
    """
    return race_state(_race(race), _time(at), car_class, focus, _rules(rules))


@mcp.tool()
def radio_feed(race: str, car_class: str | None = None, focus: str | None = None,
               rules: dict | None = None, until: str | None = None,
               only_focus: bool = False) -> list[dict]:
    """Time-ordered pit-wall events: cautions, stops, caution pit calls, drive-time,
    fuel-window and pace warnings for the focus car. `until` limits the replay time."""
    r = _race(race)
    rr = _rules(rules)
    events = race_events(r, car_class, focus, rr, _time(until) if until else None,
                         ctx=RaceContext(r, car_class, rr))
    if only_focus and focus:
        events = [e for e in events if e["car"] in (focus, None)]
    return events


@mcp.tool()
def car_debrief(race: str, car: str, markdown: bool = True) -> str | dict:
    """Post-race debrief of one car: driver pace ranks, stop losses vs class median,
    cautions that could have been used, and where the time went."""
    result = debrief(_race(race), car)
    return to_markdown(result) if markdown else result


@mcp.tool()
def car_report(race: str, car: str) -> dict:
    """All stints, pit stops and drive times of one car."""
    return analysis.car_report(_race(race), car)


@mcp.tool()
def fit_race_rules(races: list[str], car_class: str, with_planner_spec: bool = False) -> dict:
    """Infer rules from earlier races of the same championship: service stops per car,
    driver-change pit window, stop loss by flag. Use the result as `rules` elsewhere."""
    loaded = [_race(r) for r in races]
    return fit_spec(loaded, car_class) if with_planner_spec else fit_rules(loaded, car_class)


@mcp.tool()
def caution_pit_call(green_lap_s: float, caution_lap_s: float, pit_lane_transit_s: float,
                     track_equivalent_s: float, stationary_s: float, laps_into_stint: int,
                     max_stint_laps: int, race_time_left_s: float,
                     caution_time_left_s: float) -> dict:
    """Pit now under FCY / Safety Car or stay out? Fuel-window aware."""
    return evaluate(CautionCall(green_lap_s, caution_lap_s, pit_lane_transit_s,
                                track_equivalent_s, stationary_s, laps_into_stint,
                                max_stint_laps, race_time_left_s, caution_time_left_s))


@mcp.tool()
def plan_stints(preset_name: str | None = None, spec: dict | None = None) -> dict:
    """Optimise stints, tyre changes and driver order for a timed race.

    Give a preset name (see list_presets) or a full spec dict with duration_s,
    base_lap_s, max_stint_laps, drivers[], pit{}, tyres{}.
    """
    data: dict[str, Any] = spec if spec else preset(preset_name or "lmc-lmp3-proam-2h")
    try:
        return plan(spec_from_dict(data))
    except (InfeasiblePlan, ValueError) as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_presets() -> dict:
    """Example race set-ups for plan_stints."""
    return {k: v["label"] for k, v in PRESETS.items()}


@mcp.prompt()
def race_engineer(race: str, car: str, car_class: str) -> str:
    """Start a race-engineer session for one car."""
    return (f"{INSTRUCTIONS}\n\nWe are car #{car} in {car_class}. Race: {race}. "
            "Start with race_overview, then follow the race with race_state_at and radio_feed.")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
