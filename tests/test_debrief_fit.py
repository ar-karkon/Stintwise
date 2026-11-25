import pytest

from stintwise.debrief import debrief, to_markdown
from stintwise.fit import fit_rules, fit_spec
from stintwise.planner import plan, spec_from_dict
from stintwise.sample import generate
from stintwise.timing import parse_text


@pytest.fixture(scope="module")
def races():
    return [parse_text(generate(seed=s), f"synthetic-{s}") for s in (1, 2, 3)]


def test_debrief_structure(races):
    race = races[0]
    car = race.cars_in_class("LMGT3")[0]
    d = debrief(race, car)
    assert d["car"] == car and d["class"] == "LMGT3"
    assert d["findings"] and d["drivers"] and d["stops"]
    assert all(v >= 0 for v in d["time_accounting_s"].values())
    assert sum(dr["laps"] for dr in d["drivers"]) == d["laps"]
    md = to_markdown(d)
    assert md.startswith("# Debrief") and "## Pit stops" in md


def test_fit_rules_and_spec(races):
    fitted = fit_rules(races, "LMGT3")
    assert fitted["rules"]["duration_s"] == 6 * 3600
    assert fitted["rules"]["service_loss_s"] > 0
    assert fitted["evidence"]["races"] == 3
    spec = fit_spec(races, "LMGT3")["spec"]
    result = plan(spec_from_dict(spec))
    assert result["laps_completed"] > 100
    with pytest.raises(ValueError):
        fit_rules(races, "NOPE")
