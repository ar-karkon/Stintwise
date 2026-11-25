import itertools
import math

import pytest

from stintwise.planner import (
    Driver,
    InfeasiblePlan,
    PitModel,
    RaceSpec,
    TyreModel,
    _solve_drivers,
    _solve_tyres,
    plan,
    simulate,
    spec_from_dict,
)
from stintwise.presets import PRESETS, preset

H = 3600.0


def small_spec(**kw) -> RaceSpec:
    base = dict(
        duration_s=2 * H, base_lap_s=100.0, max_stint_laps=15,
        drivers=(Driver("A"), Driver("B", pace_offset_s=1.0, min_drive_s=1800)),
        pit=PitModel(lane_loss_s=25, refuel_base_s=3, refuel_per_lap_s=1, tyre_change_s=15,
                     driver_change_s=10),
        tyres=TyreModel(deg_s_per_lap=0.08, deg_quad_s=0.002, warmup_s=1.0,
                        sets_available=4, max_stints_per_set=3),
        max_consecutive_stints=3,
    )
    base.update(kw)
    return RaceSpec(**base)


def test_pit_model_parallel_rules():
    seq = PitModel(refuel_base_s=0, refuel_per_lap_s=1, tyre_change_s=15, driver_change_s=10,
                   tyres_parallel=False, driver_change_parallel=True, lane_loss_s=20)
    assert seq.stationary(20, True, True)["stationary_s"] == 35  # 20 fuel + 15 tyres
    assert seq.stationary(5, False, True)["stationary_s"] == 10  # driver swap dominates
    par = PitModel(refuel_base_s=0, refuel_per_lap_s=1, tyre_change_s=15, driver_change_s=10,
                   tyres_parallel=True, driver_change_parallel=False, lane_loss_s=20)
    assert par.stationary(20, True, True)["loss_s"] == 20 + 20 + 10


def test_plan_reaches_flag_and_respects_limits():
    spec = small_spec()
    r = plan(spec)
    assert r["finish_time"] >= spec.duration_s
    assert r["laps_completed"] == r["planned_laps"]
    # The lap before the last one must still be inside the clock.
    last = r["stints"][-1]
    assert last["end"] == pytest.approx(r["total_time"])
    assert all(s["laps"] <= spec.max_stint_laps for s in r["stints"])
    drive = {d["name"]: d["drive_s"] for d in r["drivers"]}
    assert drive["B"] >= 1800
    assert r["tyre_sets_used"] <= spec.tyres.sets_available
    per_set = {}
    for s in r["stints"]:
        per_set[s["tyre_set"]] = per_set.get(s["tyre_set"], 0) + 1
    assert max(per_set.values()) <= spec.tyres.max_stints_per_set


def _total(spec, layout, changes, seq):
    return simulate(spec, layout, changes, seq)["total_time"]


def test_tyre_dp_matches_brute_force():
    spec = small_spec()
    layout = [15, 15, 15, 15, 10]
    seq = [0, 0, 1, 1, 0]
    best = min(
        (_total(spec, layout, list(c), seq), list(c))
        for c in itertools.product([False, True], repeat=len(layout) - 1)
        if sum(c) + 1 <= spec.tyres.sets_available
        and all(len(list(g)) < spec.tyres.max_stints_per_set
                for k, g in itertools.groupby(c) if not k)
    )
    chosen = _solve_tyres(spec, layout, seq)
    assert _total(spec, layout, chosen, seq) == pytest.approx(best[0])


def test_driver_dp_matches_brute_force():
    spec = small_spec(drivers=(Driver("A"), Driver("B", 0.5, min_drive_s=3000),
                               Driver("C", 1.5, min_drive_s=1400)),
                      max_consecutive_stints=2)
    layout = [15, 15, 15, 15, 10]
    changes = [True, False, True, False]

    def feasible(seq):
        times = simulate(spec, layout, changes, list(seq))["drive_time"]
        runs = [len(list(g)) for _, g in itertools.groupby(seq)]
        return (max(runs) <= 2 and times["B"] >= 3000 and times["C"] >= 1400)

    candidates = [s for s in itertools.product(range(3), repeat=5) if feasible(s)]
    best = min(_total(spec, layout, changes, list(s)) for s in candidates)
    chosen = _solve_drivers(spec, layout, changes)
    assert feasible(chosen)
    assert _total(spec, layout, changes, chosen) == pytest.approx(best)


def test_max_consecutive_stints_enforced():
    spec = small_spec(drivers=(Driver("A"), Driver("B", 3.0)), max_consecutive_stints=1)
    r = plan(spec)
    names = [s["driver"] for s in r["stints"]]
    assert all(a != b for a, b in zip(names, names[1:], strict=False))


def test_infeasible_limits_are_reported():
    with pytest.raises(InfeasiblePlan):
        plan(small_spec(drivers=(Driver("A", max_drive_s=1800), Driver("B", max_drive_s=1800))))
    with pytest.raises(InfeasiblePlan):
        plan(small_spec(tyres=TyreModel(sets_available=1, max_stints_per_set=1)))
    with pytest.raises(ValueError):
        plan(small_spec(drivers=(Driver("A", min_drive_s=3 * H),)))


def test_double_stinting_when_tyre_change_is_expensive():
    cheap_deg = small_spec(tyres=TyreModel(deg_s_per_lap=0.0, deg_quad_s=0.0, warmup_s=0,
                                           sets_available=10, max_stints_per_set=3))
    r = plan(cheap_deg)
    assert r["tyre_sets_used"] < len(r["stints"])
    heavy_deg = small_spec(tyres=TyreModel(deg_s_per_lap=0.5, sets_available=10,
                                           max_stints_per_set=3))
    r = plan(heavy_deg)
    assert all(s["new_tyres"] for s in r["stints"])


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_presets_produce_valid_plans(name):
    data = preset(name)
    spec = spec_from_dict(data)
    r = plan(spec)
    assert r["laps_completed"] > 0
    for d, drv in zip(r["drivers"], spec.drivers, strict=True):
        assert d["drive_s"] >= drv.min_drive_s
        if not math.isinf(drv.max_drive_s):
            assert d["drive_s"] <= drv.max_drive_s
