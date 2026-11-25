import pytest

from stintwise.caution_model import assess, distance, neighbours
from stintwise.costs import stop_costs
from stintwise.evaluate import evaluate, load_dataset
from stintwise.fit import fit_caution_model, fit_rules
from stintwise.official import min_drive_time, parse_classification, penalised_cars
from stintwise.sample import generate_lmc, write_sample
from stintwise.timing import parse_text

CLASSIFICATION = (
    "POSITION;NUMBER;STATUS;LAPS;TOTAL_TIME;CLASS;DRIVER1_FIRSTNAME;DRIVER1_SECONDNAME;"
    "DRIVER1_LICENSE;DRIVER1_*Extra 4;DRIVER2_FIRSTNAME;DRIVER2_SECONDNAME;DRIVER2_LICENSE;"
    "DRIVER2_*Extra 4\n"
    "1;71;Classified;60;2:01:39.456;LMP3 Pro/Am;Stefan;AUST;B;00:50:00;Felipe;LASER;S;00:50:00\n"
    "2;34;Classified;60;2:01:46.662;LMP3 Pro/Am;Alex;BUK;B;00:50:00;George;KING;S;00:50:00\n"
    "3;62;Classified;60;2:02:30.000;LMP3 Pro/Am;Jacek;ZIEL;B;00:50:00;Leo;ROB;S;00:50:00\n"
    "4;9;Not classified;12;;LMP3 Pro/Am;A;B;S;00:50:00;C;D;S;00:50:00\n"
)


def test_official_classification():
    entries = parse_classification(CLASSIFICATION)
    assert entries["71"].classified and not entries["9"].classified
    assert entries["71"].drivers[0].name == "Stefan AUST"
    assert entries["71"].drivers[0].category == "B"
    assert min_drive_time(entries) == 3000
    finish = {"71": 7299.456, "34": 7306.662, "62": 7310.0}  # 62 got a ~40 s penalty
    assert penalised_cars(entries, finish) == {"62"}


@pytest.fixture(scope="module")
def lmc_races():
    return [parse_text(generate_lmc(seed), f"lmc-{seed}") for seed in (3, 4, 5, 6)]


def test_stop_costs_use_neighbours(lmc_races):
    costs = [c for c in stop_costs(lmc_races[0]) if c.stop.kind == "service"]
    assert costs
    measured = [c for c in costs if c.cost_s is not None]
    assert len(measured) / len(costs) > 0.8
    green = [c for c in measured if c.method == "neighbours" and c.stop.flag == "GF"]
    # a green stop costs about its pit-lane time
    for c in green:
        assert abs(c.cost_s - c.stop.pit_time) < 60


def test_caution_model_and_assessment(lmc_races):
    model = fit_caution_model(lmc_races)
    assert "SC" in model and len(model["SC"]["samples"]) >= 5
    a = assess(model["SC"], 120, 165)
    assert a and 0 <= a["p_gain"] <= 1
    assert a["middle_s"][0] <= a["gain_s"] <= a["middle_s"][1]
    assert distance(60, 120) == pytest.approx(60 / 120)
    near = neighbours({"samples": [[10, 0.1], [600, 0.5], [100, 0.2]]}, 90, k=2)
    assert [r[0] for r in near] == [100, 10]


def test_rules_learned_from_mandatory_stop_races(lmc_races):
    rules = fit_rules(lmc_races, "LMP3 Pro/Am", duration=7200)["rules"]
    assert rules["required_service_stops"] == 1
    assert 45 * 60 <= rules["window_open_s"] <= rules["window_close_s"] <= 70 * 60
    assert rules["pit_lane_s"] > 150 and "GREEN" in rules["cost_extra_s"]


def test_benchmark_runs_on_a_folder(tmp_path):
    for k, seed in enumerate((3, 4, 5, 6), start=1):
        path = write_sample(tmp_path / f"lmc-2030-r{k}-test.csv", seed=seed, profile="lmc")
        assert path.exists()
    items = load_dataset(tmp_path)
    assert [i.key[2] for i in items] == [1, 2, 3, 4]
    result = evaluate(items)
    assert result["green_cost_mae_s"]["n"] > 0
    assert result["window_coverage"]["value"] >= 0.8
