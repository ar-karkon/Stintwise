"""HTTP API and dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse

from . import __version__, analysis, store
from .caution import call_from_dict, evaluate
from .debrief import debrief, to_markdown
from .fit import fit_rules, fit_spec
from .live import RaceContext, Rules, race_events, race_state
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


PAGE_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    "<style>:root{padding-block:env(safe-area-inset-top,0px) env(safe-area-inset-bottom,0px)}"
    "body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}"
    "[hidden]{display:none!important}</style></head><body>"
)


@app.get("/pitwall", include_in_schema=False)
def pitwall_redirect() -> RedirectResponse:
    return RedirectResponse("/pitwall/")


@app.get("/pitwall/", include_in_schema=False)
def pitwall() -> HTMLResponse:
    """The pit-wall page, wrapped the same way claude.ai wraps a published artifact."""
    body = (STATIC / "pitwall.html").read_text(encoding="utf-8")
    return HTMLResponse(PAGE_HEAD + body + "</body></html>")


@app.get("/pitwall/engine.js", include_in_schema=False)
def pitwall_engine() -> FileResponse:
    return FileResponse(STATIC / "engine.js", media_type="text/javascript")


@app.get("/pitwall/demo.csv", include_in_schema=False)
def pitwall_demo() -> PlainTextResponse:
    return PlainTextResponse(store.race_csv(store.SAMPLE_LMC_ID), media_type="text/csv")


@app.get("/api/races/{race_id}/csv", include_in_schema=False)
def race_csv(race_id: str) -> PlainTextResponse:
    try:
        return PlainTextResponse(store.race_csv(race_id), media_type="text/csv")
    except KeyError as exc:
        raise HTTPException(404, f"Race {race_id!r} not found") from exc


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


def _rules(body: dict) -> Rules:
    try:
        return Rules.from_dict(body.get("rules"))
    except TypeError as exc:
        raise _bad(exc) from exc


@app.post("/api/races/{race_id}/state")
def live_state(race_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Race as seen from the pit wall at race time `t` (seconds)."""
    race = _race(race_id)
    try:
        return race_state(race, float(body["t"]), body.get("car_class"), body.get("focus"),
                          _rules(body))
    except (KeyError, ValueError, TypeError) as exc:
        raise _bad(exc) from exc


@app.post("/api/races/{race_id}/events")
def live_events(race_id: str, body: dict[str, Any] = Body(default={})) -> list[dict]:
    """Radio feed (cautions, stops, pit calls, drive-time warnings) up to `until`."""
    race = _race(race_id)
    rules = _rules(body)
    try:
        ctx = RaceContext(race, body.get("car_class"), rules)
        return race_events(race, body.get("car_class"), body.get("focus"), rules,
                           body.get("until"), ctx=ctx)
    except (KeyError, ValueError, TypeError) as exc:
        raise _bad(exc) from exc


@app.get("/api/races/{race_id}/debrief/{car}")
def car_debrief(race_id: str, car: str, format: str = "json"):
    race = _race(race_id)
    if car not in race.cars:
        raise HTTPException(404, f"Car {car!r} not in race")
    result = debrief(race, car)
    if format == "md":
        return PlainTextResponse(to_markdown(result), media_type="text/markdown")
    return result


@app.post("/api/fit")
def fit(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Infer rules and planner inputs for a class from earlier races."""
    races = [_race(r) for r in body.get("races", [])]
    if not races:
        raise HTTPException(422, "Give at least one race id")
    try:
        return fit_spec(races, body["car_class"])
    except (KeyError, ValueError) as exc:
        raise _bad(exc) from exc


@app.get("/api/fit/rules")
def fit_rules_endpoint(races: str, car_class: str) -> dict[str, Any]:
    try:
        return fit_rules([_race(r) for r in races.split(",") if r], car_class)
    except ValueError as exc:
        raise _bad(exc) from exc
