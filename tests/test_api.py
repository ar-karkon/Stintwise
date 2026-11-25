import pytest
from fastapi.testclient import TestClient

from stintwise.api import app
from stintwise.presets import PRESETS
from stintwise.sample import generate
from stintwise.store import SAMPLE_ID


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STINTWISE_DATA", str(tmp_path))
    return TestClient(app)


def test_dashboard_and_health(client):
    assert "STINT" in client.get("/").text
    assert client.get("/api/health").json()["status"] == "ok"


def test_plan_and_errors(client):
    spec = {k: v for k, v in PRESETS["example-lmgt3-6h"].items() if k != "label"}
    r = client.post("/api/plan", json=spec)
    assert r.status_code == 200 and r.json()["laps_completed"] > 100
    bad = {**spec, "base_lap_s": 5}
    assert client.post("/api/plan", json=bad).status_code == 422


def test_caution_endpoint(client):
    body = dict(green_lap_s=138, caution_lap_s=220, pit_lane_transit_s=58, track_equivalent_s=24,
                stationary_s=28, laps_into_stint=17, max_stint_laps=22, race_time_left_s=7000,
                caution_time_left_s=240)
    assert "verdict" in client.post("/api/caution", json=body).json()
    assert client.post("/api/caution", json={"x": 1}).status_code == 422


def test_sample_race_and_upload(client):
    races = client.get("/api/races").json()
    assert races[0]["id"] == SAMPLE_ID
    overview = client.get(f"/api/races/{SAMPLE_ID}", params={"car_class": "HYPERCAR"}).json()
    car = overview["cars"][0]["car"]
    assert client.get(f"/api/races/{SAMPLE_ID}/cars/{car}").json()["car"] == car
    assert client.get(f"/api/races/{SAMPLE_ID}/cars/999").status_code == 404
    assert client.get("/api/races/nope").status_code == 404

    up = client.post("/api/races", params={"name": "My Race 2025.CSV"},
                     content=generate(seed=1).encode(), headers={"Content-Type": "text/csv"})
    assert up.status_code == 200
    race_id = up.json()["id"]
    assert race_id == "My-Race-2025"
    assert any(r["id"] == race_id for r in client.get("/api/races").json())
    assert client.get(f"/api/races/{race_id}").status_code == 200
    bad = client.post("/api/races", params={"name": "x"}, content=b"hello;world\n")
    assert bad.status_code == 422
    assert client.get("/api/races/..%2Fetc").status_code == 404


def test_live_endpoints(client):
    state = client.post(f"/api/races/{SAMPLE_ID}/state",
                        json={"t": 7200, "car_class": "LMGT3", "focus": "50",
                              "rules": {"required_service_stops": 6}}).json()
    assert state["focus"]["car"] == "50" and state["cars"]
    assert client.post(f"/api/races/{SAMPLE_ID}/state", json={"t": 1, "focus": "999"}
                       ).status_code == 422
    events = client.post(f"/api/races/{SAMPLE_ID}/events",
                         json={"car_class": "LMGT3", "focus": "50", "until": 7200}).json()
    assert events and all(e["t"] <= 7200 for e in events)
    d = client.get(f"/api/races/{SAMPLE_ID}/debrief/50").json()
    assert d["findings"]
    md = client.get(f"/api/races/{SAMPLE_ID}/debrief/50", params={"format": "md"})
    assert md.text.startswith("# Debrief")
    fit = client.post("/api/fit", json={"races": [SAMPLE_ID], "car_class": "LMGT3"}).json()
    assert fit["spec"]["duration_s"] == 21600
    rules = client.get("/api/fit/rules", params={"races": SAMPLE_ID, "car_class": "LMGT3"})
    learned = rules.json()["rules"]
    assert learned["required_service_stops"] or learned.get("max_stint_s")
