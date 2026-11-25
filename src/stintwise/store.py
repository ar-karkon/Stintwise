"""Local race store: Al Kamel CSV files in a data directory plus a synthetic demo."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from .sample import generate
from .timing import Race, load_csv, parse_text

SAMPLE_ID = "synthetic-demo-6h"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def data_dir() -> Path:
    return Path(os.environ.get("STINTWISE_DATA", "data/races"))


def race_id_for(name: str) -> str:
    stem = Path(name).stem
    cleaned = _SAFE.sub("-", stem).strip("-.")
    if not cleaned:
        raise ValueError("Invalid race name")
    return cleaned[:80]


def list_races() -> list[dict]:
    races = [{"id": SAMPLE_ID, "name": "Synthetic demo race (6h, invented data)",
              "synthetic": True}]
    folder = data_dir()
    if folder.is_dir():
        for path in sorted(folder.glob("*.[cC][sS][vV]")):
            races.append({"id": path.stem, "name": path.stem, "synthetic": False})
    return races


@lru_cache(maxsize=1)
def _sample() -> Race:
    return parse_text(generate(), SAMPLE_ID)


@lru_cache(maxsize=16)
def _load(path: str, mtime: float) -> Race:
    return load_csv(path)


def get_race(race_id: str) -> Race:
    if race_id == SAMPLE_ID:
        return _sample()
    if race_id != race_id_for(race_id):
        raise KeyError(race_id)
    for path in data_dir().glob(f"{race_id}.*"):
        if path.suffix.lower() == ".csv":
            return _load(str(path), path.stat().st_mtime)
    raise KeyError(race_id)


def save_race(name: str, text: str) -> str:
    race_id = race_id_for(name)
    if race_id == SAMPLE_ID:
        raise ValueError("Reserved name")
    parse_text(text, race_id)  # validate before writing
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{race_id}.csv").write_text(text, encoding="utf-8")
    return race_id
