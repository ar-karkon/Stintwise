"""HTTP API and dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from . import __version__, analysis, store
from .caution import call_from_dict, evaluate
from .planner import InfeasiblePlan, plan, spec_from_dict
from .presets import PRESETS

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 25 * 1024 * 1024

app = FastAPI(
    title="Stintwise",
    version=__version__,
    description="Endurance race strategy: stint planning, caution pit calls, timing analysis.",
)


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/presets")
def presets() -> dict[str, Any]:
    return PRESETS


@app.post("/api/plan")
def make_plan(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return plan(spec_from_dict(spec))
    except (InfeasiblePlan, ValueError, TypeError, KeyError) as exc:
        raise _bad(exc) from exc


@app.post("/api/caution")
def caution(call: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return evaluate(call_from_dict(call))
    except (ValueError, TypeError) as exc:
        raise _bad(exc) from exc


@app.get("/api/races")
def races() -> list[dict]:
    return store.list_races()


def _race(race_id: str):
    try:
        return store.get_race(race_id)
    except KeyError as exc:
        raise HTTPException(404, f"Race {race_id!r} not found") from exc
    except ValueError as exc:
        raise _bad(exc) from exc


@app.get("/api/races/{race_id}")
def race_overview(race_id: str, car_class: str | None = None) -> dict[str, Any]:
    race = _race(race_id)
    if car_class and car_class not in race.classes:
        raise HTTPException(404, f"Class {car_class!r} not in race")
    return analysis.race_overview(race, car_class)


@app.get("/api/races/{race_id}/cars/{car}")
def car_report(race_id: str, car: str) -> dict[str, Any]:
    race = _race(race_id)
    if car not in race.cars:
        raise HTTPException(404, f"Car {car!r} not in race")
    return analysis.car_report(race, car)


@app.post("/api/races")
async def upload_race(request: Request, name: str) -> dict[str, str]:
    """Upload an Al Kamel Analysis CSV as the raw request body."""
    raw = await request.body()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "File too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        return {"id": store.save_race(name, text)}
    except ValueError as exc:
        raise _bad(exc) from exc
