"""The browser engine (static/engine.js) must give the same results as Python."""
import json
import math
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pytest

from stintwise import analysis
from stintwise.caution import CautionCall, evaluate
from stintwise.costs import stop_costs
from stintwise.debrief import debrief
from stintwise.fit import fit_caution_model, fit_rules
from stintwise.live import race_events, race_state
from stintwise.planner import plan, spec_from_dict
from stintwise.presets import PRESETS, preset
from stintwise.sample import write_sample
from stintwise.timing import load_csv

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def normalise(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(k): normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalise(v) for v in value]
    if isinstance(value, float) and math.isinf(value):
        return None
    return value


def same(py, js, where="root"):
    """Every key Python returns must exist in JS with an equal value."""
    if isinstance(py, dict):
        assert isinstance(js, dict), f"{where}: expected dict, got {js!r}"
        for k, v in py.items():
            assert k in js, f"{where}: missing key {k!r}"
            same(v, js[k], f"{where}.{k}")
    elif isinstance(py, list):
        assert isinstance(js, list) and len(py) == len(js), f"{where}: list length"
        for i, (a, b) in enumerate(zip(py, js, strict=True)):
            same(a, b, f"{where}[{i}]")
    elif isinstance(py, bool) or py is None or isinstance(py, str):
        assert py == js, f"{where}: {py!r} != {js!r}"
    elif isinstance(py, (int, float)):
        assert isinstance(js, (int, float)) and not isinstance(js, bool), f"{where}: {js!r}"
        assert math.isclose(py, js, rel_tol=1e-9, abs_tol=1e-6), f"{where}: {py} != {js}"
    else:
        raise AssertionError(f"{where}: unexpected type {type(py)}")


def run_js(job, tmp_path):
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job))
    proc = subprocess.run([NODE, str(ROOT / "tests/js/run_engine.js"), str(path)],
                          capture_output=True, text=True, check=True, timeout=300)
    return json.loads(proc.stdout)


def datasets(tmp_path):
    files = {"synthetic": write_sample(tmp_path / "synthetic.csv", seed=11)}
    wanted = ["lmc-2026-r6-autodromo-do-algarve", "lmc-2025-r6-autodromo-do-algarve",
              "elms-2026-r5-silverstone", "lmc-2023-r5-spa-francorchamps"]
    for name in wanted:
        path = ROOT / "data/races" / f"{name}.csv"
        if path.is_file():
            files[name] = path
    return files


def test_python_round_semantics(tmp_path):
    values = [[2.5, 0], [3.5, 0], [0.125, 2], [2.675, 2], [-2.5, 0], [101.125, 2],
              [1234.5, 0], [0.35, 1], [7.45, 1]]
    js = run_js({"races": {}, "tasks": [{"kind": "round", "values": values}]}, tmp_path)[0]
    assert js == [round(x, n) if n else float(round(x)) for x, n in values]


def test_engine_parity(tmp_path):
    files = datasets(tmp_path)
    races = {k: load_csv(v, k) for k, v in files.items()}
    tasks, expected = [], []

    def add(task, value):
        tasks.append(task)
        expected.append(normalise(value))

    for rid, race in races.items():
        classes = race.classes
        cls = "LMP3 Pro/Am" if "LMP3 Pro/Am" in classes else classes[-1]
        cars = race.cars_in_class(cls)
        focus = cars[0]
        drivers = sorted({lap.driver for lap in race.car_laps(focus)})
        rules = {"required_service_stops": 1, "service_loss_s": 120.0,
                 "caution_loss_s": {"SC": 70.0},
                 "window_open_s": race.scheduled_duration * 0.3,
                 "window_close_s": race.scheduled_duration * 0.7,
                 "drivers": {d: {"min_drive_s": 1800} for d in drivers}}
        add({"kind": "overview", "race": rid, "cls": None}, analysis.race_overview(race, None))
        add({"kind": "overview", "race": rid, "cls": cls}, analysis.race_overview(race, cls))
        for car in cars[:3]:
            add({"kind": "car_report", "race": rid, "car": car}, analysis.car_report(race, car))
            add({"kind": "debrief", "race": rid, "car": car}, debrief(race, car))
        for frac in (0.1, 0.45, 0.8):
            t = race.duration * frac
            add({"kind": "state", "race": rid, "t": t, "cls": cls, "focus": focus,
                 "rules": rules}, race_state(race, t, cls, focus, rules))
        add({"kind": "state", "race": rid, "t": race.duration / 2, "cls": cls, "focus": None,
             "rules": {"max_stint_laps": 20}},
            race_state(race, race.duration / 2, cls, None, {"max_stint_laps": 20}))
        add({"kind": "events", "race": rid, "cls": cls, "focus": focus, "rules": rules,
             "until": None}, race_events(race, cls, focus, rules))
        add({"kind": "events", "race": rid, "cls": cls, "focus": focus,
             "rules": {"max_stint_laps": 15}, "until": race.duration / 2},
            race_events(race, cls, focus, {"max_stint_laps": 15}, race.duration / 2))
    ids = list(races)
    for rid, race in races.items():
        add({"kind": "costs", "race": rid},
            [{"car": c.stop.car, "in_lap": c.stop.in_lap, "cost_s": c.cost_s, "method": c.method,
              "refs": c.refs, "known_at": c.known_at} for c in stop_costs(race)])
    model = fit_caution_model([races[i] for i in ids])
    add({"kind": "caution_model", "races": ids}, model)
    cls0 = races[ids[-1]].classes[-1]
    usable = [i for i in ids if cls0 in races[i].classes]
    add({"kind": "fit", "races": usable, "cls": cls0},
        fit_rules([races[i] for i in usable], cls0))
    learned = fit_rules([races[i] for i in usable], cls0, caution_model=model)
    add({"kind": "fit", "races": usable, "cls": cls0, "caution_model": model}, learned)
    # live engine with learned rules (caution model, pit-lane time, fuel window ...)
    for rid in usable:
        race = races[rid]
        focus = race.cars_in_class(cls0)[0]
        rules = {**learned["rules"], "window_open_s": race.scheduled_duration * 0.35,
                 "window_close_s": race.scheduled_duration * 0.65}
        for frac in (0.3, 0.5, 0.75):
            t = race.duration * frac
            add({"kind": "state", "race": rid, "t": t, "cls": cls0, "focus": focus, "rules": rules},
                race_state(race, t, cls0, focus, rules))
        add({"kind": "events", "race": rid, "cls": cls0, "focus": focus, "rules": rules,
             "until": None}, race_events(race, cls0, focus, rules))
        fuel = {k: v for k, v in learned["rules"].items() if k != "required_service_stops"}
        fuel["max_stint_s"] = 2400
        add({"kind": "state", "race": rid, "t": race.duration / 2, "cls": cls0, "focus": focus,
             "rules": fuel}, race_state(race, race.duration / 2, cls0, focus, fuel))
    for name in PRESETS:
        add({"kind": "plan", "spec": preset(name)}, plan(spec_from_dict(preset(name))))
    for into in (2, 12, 19):
        call = dict(green_lap_s=138, caution_lap_s=220, pit_lane_transit_s=58,
                    track_equivalent_s=24, stationary_s=28, laps_into_stint=into,
                    max_stint_laps=22, race_time_left_s=7000, caution_time_left_s=40)
        add({"kind": "caution", "call": call}, evaluate(CautionCall(**call)))

    results = run_js({"races": {k: str(v) for k, v in files.items()}, "tasks": tasks}, tmp_path)
    for task, py, js in zip(tasks, expected, results, strict=True):
        assert not (isinstance(js, dict) and "error" in js and "error" not in py), (task, js)
        if task["kind"] == "plan":
            py = {k: v for k, v in py.items() if k != "spec"}
        same(py, js, where=f"{task['kind']}:{task.get('race', '')}:{task.get('car', '')}")
