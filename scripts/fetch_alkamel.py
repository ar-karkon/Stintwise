"""Download race lap-analysis CSVs from an Al Kamel results site.

    python scripts/fetch_alkamel.py lemanscup 2025 2024
    python scripts/fetch_alkamel.py elms 2026

Files go to data/races/ (git-ignored) as <series>-<year>-r<n>-<event>[-race<k>].csv.
The script is polite: one request at a time with a pause between requests. Timing data
belongs to the championship and its timing provider; keep it local.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOSTS = {
    "lemanscup": ("https://lemanscup.alkamelsystems.com", "lmc"),
    "elms": ("https://elms.alkamelsystems.com", "elms"),
}
PAUSE_S = 1.0
UA = "stintwise-timing-fetch/0.1 (research)"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        data = res.read()
    time.sleep(PAUSE_S)
    return data


def options(page: str) -> list[str]:
    return [html.unescape(v) for v in re.findall(r'<option Value="([^"]+)"', page)]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def race_files(page: str, series_hint: str | None) -> list[str]:
    pattern = r'href="(Results/[^"]*_Race[^"/]*/(?:Hour[^"/]*/)?23_Analysis_[^"]*\.CSV)"'
    links = sorted(set(re.findall(pattern, page)))
    links = [html.unescape(link) for link in links]
    if series_hint:
        hint = series_hint.lower()
        links = [link for link in links if hint in urllib.parse.unquote(link).lower()]
    # keep the last hour folder of each race session
    best: dict[str, tuple[int, str]] = {}
    for link in links:
        decoded = urllib.parse.unquote(link)
        session = re.search(r"/(\d{12}_Race[^/]*)/", decoded).group(1)
        hour = re.search(r"/Hour (\d+)/", decoded)
        rank = int(hour.group(1)) if hour else 0
        if session not in best or rank > best[session][0]:
            best[session] = (rank, link)
    return [best[k][1] for k in sorted(best)]


def fetch(series: str, year: int, out: Path, series_hint: str | None) -> list[Path]:
    host, prefix = HOSTS[series]
    root = get(host + "/").decode("utf-8", "replace")
    season = next((s for s in options(root) if s.endswith(f"_{year}")), None)
    if not season:
        raise SystemExit(f"No season {year} on {host}")
    page = get(f"{host}/?season={urllib.parse.quote(season)}").decode("utf-8", "replace")
    events = [e for e in options(page) if re.match(r"\d\d_", e) and "TEST" not in e.upper()
              and not re.match(r"\d\d_\d{4}$", e)]
    saved = []
    for event in events:
        url = f"{host}/?season={urllib.parse.quote(season)}&evvent={urllib.parse.quote(event)}"
        ev_page = get(url).decode("utf-8", "replace")
        files = race_files(ev_page, series_hint)
        for k, link in enumerate(files, start=1):
            number, name = event.split("_", 1)
            suffix = f"-race{k}" if len(files) > 1 else ""
            path = out / f"{prefix}-{year}-r{int(number)}-{slug(name)}{suffix}.csv"
            if not path.exists():
                path.write_bytes(get(f"{host}/{link}"))
            saved.append(path)
            official = out / "official" / path.name
            if not official.exists():
                folder = link.rsplit("/", 1)[0]
                found = [html.unescape(m) for m in re.findall(
                    r'href="(' + re.escape(folder) + r'/\d\d_Classification_[^"/]*\.CSV)"', ev_page)
                    if "ByCategory" not in m]
                if found:
                    official.parent.mkdir(exist_ok=True)
                    official.write_bytes(get(f"{host}/{found[0]}"))
                else:
                    print(f"no classification for {path.name}", file=sys.stderr)
            print(path, file=sys.stderr)
    return saved


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("series", choices=sorted(HOSTS))
    ap.add_argument("years", nargs="+", type=int)
    ap.add_argument("--out", default="data/races")
    ap.add_argument("--series-hint", help="only folders containing this text (e.g. 'Le Mans Cup')")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hint = args.series_hint or {"elms": "European Le Mans Series"}.get(args.series)
    for year in args.years:
        fetch(args.series, year, out, hint)


if __name__ == "__main__":
    main()
