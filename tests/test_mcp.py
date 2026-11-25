import asyncio
import json

import pytest

pytest.importorskip("mcp")

from stintwise.mcp_server import mcp  # noqa: E402
from stintwise.store import SAMPLE_ID  # noqa: E402


def call(name, **args):
    result = asyncio.run(mcp.call_tool(name, args))
    if isinstance(result, tuple) and isinstance(result[1], dict):
        structured = result[1]
        return structured.get("result", structured)
    blocks = result[0] if isinstance(result, tuple) else result
    texts = [getattr(b, "text", "") for b in blocks]
    try:
        return json.loads(texts[0]) if len(texts) == 1 else [json.loads(t) for t in texts]
    except json.JSONDecodeError:
        return "".join(texts)


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"list_races", "race_overview", "race_state_at", "radio_feed", "car_debrief",
            "fit_race_rules", "caution_pit_call", "plan_stints"} <= names


def test_tool_calls_on_demo_race():
    assert any(r["id"] == SAMPLE_ID for r in call("list_races"))
    state = call("race_state_at", race=SAMPLE_ID, at="2h", car_class="LMGT3", focus="50")
    assert state["focus"]["car"] == "50"
    feed = call("radio_feed", race=SAMPLE_ID, car_class="LMGT3", focus="50", until="1h",
                only_focus=True)
    assert feed and all(e["t"] <= 3600 for e in feed)
    md = call("car_debrief", race=SAMPLE_ID, car="50")
    assert "# Debrief" in md
    plan = call("plan_stints", preset_name="lmc-lmp3-proam-2h")
    assert plan["laps_completed"] > 0
