/* Stintwise engine for the browser and Node.
 *
 * A line-by-line port of the Python package (timing, analysis, live, caution,
 * planner, debrief, fit). tests/test_js_parity.py checks that both give the
 * same numbers on the same timing files.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Stintwise = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---------------------------------------------------------------- helpers
  /** Python's round(): exact decimal value, ties to even. */
  function pyRound(x, n = 0) {
    if (x === null || x === undefined || !isFinite(x)) return x;
    const exact = Math.abs(x).toFixed(Math.min(100, n + 60));
    const dot = exact.indexOf(".");
    const tail = exact.slice(dot + 1 + n);
    const isTie = tail[0] === "5" && /^50*$/.test(tail);
    if (!isTie) {
      const r = Number(x.toFixed(n));
      return r === 0 ? 0 : r;
    }
    const kept = exact.slice(0, dot + 1 + n).replace(/\.$/, "");
    const lastDigit = Number(kept[kept.length - 1]);
    const up = lastDigit % 2 === 1;
    const step = Math.pow(10, -n);
    let v = Number(kept) + (up ? step : 0);
    v = Number(v.toFixed(n));
    return x < 0 ? -v : v;
  }
  const fmt = (x, n) => pyRound(x, n).toFixed(n);
  const fmtSigned = (x, n) => (x >= 0 ? "+" : "") + fmt(x, n);

  function median(values) {
    const v = Array.from(values).sort((a, b) => a - b);
    if (!v.length) throw new Error("median of empty list");
    const m = v.length >> 1;
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }
  const sum = (xs) => xs.reduce((a, b) => a + b, 0);

  function cmpTuple(a, b) {
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const x = a[i], y = b[i];
      if (x === y) continue;
      if (x === undefined) return -1;
      if (y === undefined) return 1;
      if (typeof x === "string" || typeof y === "string") return String(x) < String(y) ? -1 : 1;
      return x < y ? -1 : 1;
    }
    return 0;
  }
  const sortBy = (arr, key) => arr.slice().sort((a, b) => cmpTuple(key(a), key(b)));

  function bisectLeft(arr, x) {
    let lo = 0, hi = arr.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < x) lo = mid + 1; else hi = mid; }
    return lo;
  }
  function bisectRight(arr, x) {
    let lo = 0, hi = arr.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (x < arr[mid]) hi = mid; else lo = mid + 1; }
    return lo;
  }

  function mostCommon(values) {
    const counts = new Map();
    for (const v of values) counts.set(v, (counts.get(v) || 0) + 1);
    let best = null, bestN = -1;
    for (const [v, n] of counts) if (n > bestN) { best = v; bestN = n; }
    return best;
  }

  function clock(seconds) {
    if (seconds === null || seconds === undefined) return "-";
    const s = pyRound(seconds, 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
  }
  function lapStr(seconds) {
    if (seconds === null || seconds === undefined) return "-";
    const m = Math.floor(seconds / 60);
    return `${m}:${fmt(seconds - m * 60, 3).padStart(6, "0")}`;
  }

  // ----------------------------------------------------------------- timing
  const FLAG_MAP = { "": "GF", G: "GF", GF: "GF", GREEN: "GF", FF: "FF", CHEQUERED: "FF",
    SF: "SC", SC: "SC", FCY: "FCY", RF: "RED", RED: "RED" };
  const GREEN_FLAGS = new Set(["GF", "FF"]);
  const CAUTION_FLAGS = new Set(["FCY", "SC", "RED"]);

  function normalizeFlag(value) {
    const code = String(value || "").trim().toUpperCase();
    return Object.prototype.hasOwnProperty.call(FLAG_MAP, code) ? FLAG_MAP[code] : code;
  }

  function parseDuration(value) {
    if (value === null || value === undefined) return null;
    const text = String(value).trim().replace(/,/g, ".");
    if (!text) return null;
    let seconds = 0;
    for (const part of text.split(":")) {
      const p = part.trim();
      if (!p || !/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(p)) return null;
      seconds = seconds * 60 + Number(p);
    }
    return seconds;
  }

  function parseIntish(value) {
    if (value === null || value === undefined || !String(value).trim()) return null;
    const n = Number(String(value).trim());
    return Number.isFinite(n) ? Math.trunc(n) : null;
  }

  function carSortKey(car) {
    const digits = car.replace(/\D/g, "");
    return [digits ? Number(digits) : 1e9, car];
  }

  class Race {
    constructor(name, laps) {
      this.name = name;
      this.laps = sortBy(laps, (l) => [l.car, l.lap]);
      this.byCar = new Map();
      for (const lap of this.laps) {
        if (!this.byCar.has(lap.car)) this.byCar.set(lap.car, []);
        this.byCar.get(lap.car).push(lap);
      }
      this.cars = sortBy([...this.byCar.keys()], carSortKey);
      this.classes = [...new Set(this.laps.map((l) => l.car_class).filter(Boolean))].sort();
      this.duration = this.laps.length ? Math.max(...this.laps.map((l) => l.elapsed || 0)) : 0;
      const green = this.laps.filter((l) => GREEN_FLAGS.has(l.flag) && l.lap_time).map((l) => l.lap_time)
        .sort((a, b) => a - b);
      const typical = green.length ? green[green.length >> 1] : 0;
      this.scheduled_duration = Math.max(300, pyRound((this.duration - 1.5 * typical) / 300, 0) * 300);
      this.red_flagged = this.laps.some((l) => l.flag === "RED");
      this.cache = new Map();
    }
    carLaps(car) {
      if (!this.byCar.has(car)) throw new Error(`Unknown car '${car}'`);
      return this.byCar.get(car);
    }
    carsInClass(cls) {
      if (!cls) return this.cars;
      return this.cars.filter((c) => this.byCar.get(c)[0].car_class === cls);
    }
    carInfo(car) {
      const f = this.carLaps(car)[0];
      return { car, class: f.car_class, team: f.team, manufacturer: f.manufacturer };
    }
  }

  function splitCSVLine(line) {
    return line.split(";");
  }

  function parseCSV(text, name = "race") {
    text = String(text).replace(/^﻿/, "");
    const lines = text.split(/\r?\n/);
    const header = splitCSVLine(lines[0] || "").map((h) => h.trim().toUpperCase());
    for (const col of ["NUMBER", "LAP_NUMBER", "LAP_TIME"]) {
      if (!header.includes(col)) throw new Error(`Missing required columns: ${col}`);
    }
    const idx = Object.fromEntries(header.map((h, i) => [h, i]));
    const get = (cells, col) => (idx[col] === undefined ? "" : (cells[idx[col]] || "").trim());
    const laps = [];
    const elapsedByCar = new Map();
    for (let i = 1; i < lines.length; i++) {
      if (!lines[i].trim()) continue;
      const cells = splitCSVLine(lines[i]);
      const car = get(cells, "NUMBER");
      const lapNo = parseIntish(get(cells, "LAP_NUMBER"));
      if (!car || lapNo === null) continue;
      const lapTime = parseDuration(get(cells, "LAP_TIME"));
      let elapsed = parseDuration(get(cells, "ELAPSED"));
      if (elapsed === null && lapTime !== null) {
        elapsedByCar.set(car, (elapsedByCar.get(car) || 0) + lapTime);
        elapsed = elapsedByCar.get(car);
      }
      laps.push({
        car, lap: lapNo, lap_time: lapTime, elapsed,
        driver_number: parseIntish(get(cells, "DRIVER_NUMBER")),
        driver: get(cells, "DRIVER_NAME"),
        in_pit: get(cells, "CROSSING_FINISH_LINE_IN_PIT").toUpperCase() === "B",
        pit_time: parseDuration(get(cells, "PIT_TIME")),
        flag: normalizeFlag(get(cells, "FLAG_AT_FL")),
        car_class: get(cells, "CLASS"), team: get(cells, "TEAM"),
        manufacturer: get(cells, "MANUFACTURER"),
      });
    }
    if (!laps.length) throw new Error("No lap rows found; is this an Al Kamel Analysis CSV?");
    return new Race(name, laps);
  }

  const isGreen = (lap) => GREEN_FLAGS.has(lap.flag);

  // --------------------------------------------------------------- analysis
  const CLEAN_LAP_FACTOR = 1.07, SHORT_STOP_MAX_S = 60, GARAGE_STOP_MIN_S = 600;

  function stopKind(pitTime) {
    if (pitTime === null || pitTime === undefined) return "unknown";
    if (pitTime <= SHORT_STOP_MAX_S) return "short";
    if (pitTime >= GARAGE_STOP_MIN_S) return "garage";
    return "service";
  }
  const flagGroup = (flag) => (flag === "GF" || flag === "FF" ? "GREEN" : flag);
  function driverLabel(lap) {
    if (lap.driver) return lap.driver;
    return lap.driver_number !== null && lap.driver_number !== undefined
      ? `Driver ${lap.driver_number}` : "?";
  }
  function slope(points) {
    if (points.length < 5) return null;
    const n = points.length;
    const mx = sum(points.map((p) => p[0])) / n;
    const my = sum(points.map((p) => p[1])) / n;
    const sxx = sum(points.map((p) => (p[0] - mx) ** 2));
    if (sxx === 0) return null;
    return sum(points.map((p) => (p[0] - mx) * (p[1] - my))) / sxx;
  }
  function splitStints(laps) {
    const chunks = [[]];
    for (const lap of laps) {
      chunks[chunks.length - 1].push(lap);
      if (lap.in_pit) chunks.push([]);
    }
    return chunks.filter((c) => c.length);
  }
  function cleanLaps(chunk) {
    const body = chunk.length > 2 ? chunk.slice(1, -1) : [];
    const green = body.filter((l) => isGreen(l) && l.lap_time && l.pit_time === null);
    if (!green.length) return [];
    const med = median(green.map((l) => l.lap_time));
    return green.filter((l) => l.lap_time <= med * CLEAN_LAP_FACTOR);
  }
  function stints(race, car, until = null) {
    let laps = race.carLaps(car);
    if (until !== null) laps = laps.filter((l) => l.elapsed !== null && l.elapsed <= until);
    const out = [];
    let previousEnd = 0;
    splitStints(laps).forEach((chunk, i) => {
      const driver = mostCommon(chunk.map(driverLabel));
      const clean = cleanLaps(chunk);
      const start = previousEnd;
      const end = chunk[chunk.length - 1].elapsed || start;
      previousEnd = end;
      out.push({
        car, car_class: chunk[0].car_class, number: i + 1, driver,
        first_lap: chunk[0].lap, last_lap: chunk[chunk.length - 1].lap, laps: chunk.length,
        start_time: start, end_time: end, clean_laps: clean.length,
        median_clean: clean.length ? median(clean.map((l) => l.lap_time)) : null,
        best: clean.length ? Math.min(...clean.map((l) => l.lap_time)) : null,
        deg_per_lap: slope(clean.map((l, k) => [k, l.lap_time])),
        ended_in_pit: chunk[chunk.length - 1].in_pit,
        duration: end - start,
      });
    });
    return out;
  }

  class FieldPace {
    constructor(race, cls, window = 150) {
      this.window = window;
      const groups = new Map();
      for (const lap of race.laps) {
        if (lap.elapsed !== null && lap.lap_time && !lap.in_pit && lap.pit_time === null &&
            (!cls || lap.car_class === cls)) {
          const g = flagGroup(lap.flag);
          if (!groups.has(g)) groups.set(g, []);
          groups.get(g).push([lap.elapsed, lap.lap_time]);
        }
      }
      this.points = new Map();
      this.times = new Map();
      for (const [g, pts] of groups) {
        const sorted = sortBy(pts, (p) => p);
        this.points.set(g, sorted);
        this.times.set(g, sorted.map((p) => p[0]));
      }
    }
    at(t, flag = "GF") {
      const g = flagGroup(flag);
      const points = this.points.get(g) || [], times = this.times.get(g) || [];
      for (const w of [this.window, 2 * this.window]) {
        const lo = bisectLeft(times, t - w), hi = bisectRight(times, t + w);
        if (hi - lo >= 3) return median(points.slice(lo, hi).map((p) => p[1]));
      }
      return null;
    }
  }

  function pitStops(race, cls = null) {
    const key = `pit_stops|${cls}`;
    if (!race.cache) race.cache = new Map();
    if (!race.cache.has(key)) race.cache.set(key, computePitStops(race, cls));
    return race.cache.get(key).slice();
  }

  function computePitStops(race, cls) {
    const fields = new Map();
    const stops = [];
    for (const car of race.carsInClass(cls)) {
      const laps = race.carLaps(car);
      const c = laps[0].car_class;
      if (!fields.has(c)) fields.set(c, new FieldPace(race, c));
      const field = fields.get(c);
      for (let i = 0; i < laps.length - 1; i++) {
        const lap = laps[i];
        if (!lap.in_pit) continue;
        const out = laps[i + 1];
        const pitTime = out.pit_time !== null ? out.pit_time : lap.pit_time;
        const refIn = lap.elapsed !== null ? field.at(lap.elapsed, lap.flag) : null;
        const refOut = out.elapsed !== null ? field.at(out.elapsed, out.flag) : null;
        let loss = null;
        if (refIn && refOut && lap.lap_time && out.lap_time) {
          loss = lap.lap_time + out.lap_time - refIn - refOut;
        }
        stops.push({
          car, car_class: c, in_lap: lap.lap, race_time: lap.elapsed || 0,
          exit_time: out.elapsed, pit_time: pitTime, kind: stopKind(pitTime),
          driver_in: driverLabel(lap), driver_out: driverLabel(out),
          driver_change: driverLabel(lap) !== driverLabel(out), flag: lap.flag,
          in_lap_time: lap.lap_time, out_lap_time: out.lap_time, loss_vs_field: loss,
        });
      }
    }
    return sortBy(stops, (s) => [s.race_time]);
  }

  function driverTimes(race, car, until = null) {
    const totals = {};
    for (const lap of race.carLaps(car)) {
      if (until !== null && (lap.elapsed === null || lap.elapsed > until)) break;
      if (lap.lap_time) totals[driverLabel(lap)] = (totals[driverLabel(lap)] || 0) + lap.lap_time;
    }
    return totals;
  }

  function cautionPeriods(race, mergeGap = null) {
    if (mergeGap === null) {
      const green = race.laps.filter((l) => isGreen(l) && l.lap_time).map((l) => l.lap_time);
      mergeGap = green.length ? Math.max(150, 2 * median(green)) : 300;
    }
    const crossings = sortBy(race.laps.filter((l) => l.elapsed !== null)
      .map((l) => [l.elapsed, l.flag]), (x) => x);
    const periods = [];
    for (const [t, flag] of crossings) {
      if (!CAUTION_FLAGS.has(flag)) continue;
      const last = periods[periods.length - 1];
      if (last && last.flag === flag && t - last.end <= mergeGap) last.end = t;
      else periods.push({ flag, start: t, end: t });
    }
    for (const p of periods) p.duration = p.end - p.start;
    return periods;
  }

  function pitLossByFlag(stops, kind = "service") {
    const groups = new Map();
    for (const s of stops) {
      if (s.loss_vs_field === null || (kind && s.kind !== kind)) continue;
      const g = flagGroup(s.flag);
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(s.loss_vs_field);
    }
    const out = {};
    for (const k of [...groups.keys()].sort()) {
      out[k] = { stops: groups.get(k).length, median_loss_s: pyRound(median(groups.get(k)), 2) };
    }
    return out;
  }

  function carReport(race, car) {
    const st = stints(race, car);
    const carStops = pitStops(race, race.carInfo(car).class).filter((s) => s.car === car);
    const laps = race.carLaps(car);
    const clean = st.map((s) => s.median_clean).filter(Boolean);
    const times = laps.map((l) => l.lap_time).filter(Boolean);
    return {
      ...race.carInfo(car), laps: laps[laps.length - 1].lap,
      finish_time: laps[laps.length - 1].elapsed,
      best_lap: times.length ? Math.min(...times) : null,
      median_stint_pace: clean.length ? median(clean) : null,
      stints: st, pit_stops: carStops, driver_time: driverTimes(race, car),
    };
  }

  function classSummary(race, cls = null) {
    const rows = race.carsInClass(cls).map((car) => {
      const laps = race.carLaps(car);
      const st = stints(race, car);
      const paces = st.map((s) => s.median_clean).filter(Boolean);
      const times = laps.map((l) => l.lap_time).filter(Boolean);
      const service = laps.filter((l) => l.pit_time !== null && stopKind(l.pit_time) === "service").length;
      return {
        ...race.carInfo(car), laps: laps[laps.length - 1].lap,
        finish_time: laps[laps.length - 1].elapsed,
        best_lap: times.length ? Math.min(...times) : null,
        median_pace: paces.length ? median(paces) : null,
        stops: laps.slice(0, -1).filter((l) => l.in_pit).length,
        service_stops: service,
        avg_stint_laps: pyRound(sum(st.map((s) => s.laps)) / st.length, 1),
      };
    });
    const sorted = sortBy(rows, (r) => [-r.laps, r.finish_time || 0]);
    sorted.forEach((r, i) => { r.position = i + 1; });
    return sorted;
  }

  function raceOverview(race, cls = null) {
    const stops = pitStops(race, cls);
    const kinds = {};
    for (const s of stops) kinds[s.kind] = (kinds[s.kind] || 0) + 1;
    return {
      name: race.name, duration: race.duration, scheduled_duration: race.scheduled_duration,
      classes: race.classes, class: cls, cars: classSummary(race, cls),
      cautions: cautionPeriods(race), pit_loss_by_flag: pitLossByFlag(stops),
      stop_kinds: kinds, pit_stop_count: stops.length,
    };
  }

  // ------------------------------------------------------------------- live
  const DEFAULT_CAUTION_RATIO = { FCY: 1.6, SC: 1.8 };
  const MIN_USEFUL_GAIN_S = 5.0;
  const RULE_DEFAULTS = { duration_s: null, required_service_stops: null, max_stint_laps: null,
    max_stint_s: null, window_open_s: null, window_close_s: null, service_loss_s: null,
    pit_track_equivalent_s: 20.0, caution_loss_s: {}, pit_lane_s: null, cost_extra_s: {},
    caution_model: {}, min_drive_s: null, drivers: {} };
  const has = (v) => v !== null && v !== undefined;

  function makeRules(data) {
    const r = { ...RULE_DEFAULTS, drivers: {}, caution_loss_s: {}, cost_extra_s: {}, caution_model: {} };
    data = data || {};
    if (data.rules) data = data.rules;
    for (const k of Object.keys(RULE_DEFAULTS)) {
      if (data[k] !== undefined && data[k] !== "" && data[k] !== null) r[k] = data[k];
    }
    r.drivers = r.drivers || {};
    return r;
  }

  class RaceContext {
    constructor(race, cls, rules) {
      this.race = race;
      this.car_class = cls || null;
      this.rules = makeRules(rules);
      this.duration = this.rules.duration_s || race.scheduled_duration;
      this.cars = race.carsInClass(this.car_class);
      this.field = new FieldPace(race, this.car_class);
      this.stops = pitStops(race, this.car_class);
      this.cautions = cautionPeriods(race);
      this.lapTimeAt = new Map();
      for (const car of this.cars) {
        const m = new Map();
        for (const lap of race.carLaps(car)) if (lap.elapsed !== null) m.set(lap.lap, lap.elapsed);
        this.lapTimeAt.set(car, m);
      }
      this.crossings = sortBy(race.laps.filter((l) => l.elapsed !== null)
        .map((l) => [l.elapsed, l.flag]), (x) => x);
      this.memo = new Map();
    }
    entry(car) {
      const names = [];
      for (const lap of this.race.carLaps(car)) {
        const n = driverLabel(lap);
        if (!names.includes(n)) names.push(n);
      }
      return names;
    }
    completed(car, t) {
      return this.race.carLaps(car).filter((l) => l.elapsed !== null && l.elapsed <= t);
    }
    knownStops(t) {
      return this.stops.filter((s) => s.exit_time !== null && s.exit_time + this.field.window <= t);
    }
    flagAt(t) {
      let current = "GF";
      for (const [when, flag] of this.crossings) { if (when > t) break; current = flag; }
      return current;
    }
    pitLaneTime(t) {
      const times = this.stops.filter((s) => s.kind === "service" && s.pit_time && s.exit_time !== null &&
        s.exit_time <= t).map((s) => s.pit_time).sort((a, b) => a - b);
      if (times.length >= 2) {
        const m = median(times);
        return median(times.filter((x) => x <= 1.3 * m));
      }
      return this.rules.pit_lane_s;
    }
    serviceLoss(t, flag = "GF") {
      if (flagGroup(flag) !== "GREEN") {
        const losses = this.knownStops(t).filter((s) => s.kind === "service" && s.loss_vs_field !== null &&
          flagGroup(s.flag) === flagGroup(flag)).map((s) => s.loss_vs_field);
        return losses.length >= 2 ? median(losses) : null;
      }
      const extra = (this.rules.cost_extra_s || {}).GREEN;
      const pit = this.pitLaneTime(t);
      if (has(pit) && has(extra)) return pit + extra;
      if (has(this.rules.service_loss_s)) return this.rules.service_loss_s;
      const losses = this.knownStops(t).filter((s) => s.kind === "service" && s.loss_vs_field !== null &&
        flagGroup(s.flag) === "GREEN").map((s) => s.loss_vs_field);
      return losses.length >= 2 ? median(losses) : null;
    }
    cautionLap(t, flag) {
      const laps = this.race.laps.filter((l) => l.flag === flag && l.elapsed !== null &&
        t - 600 <= l.elapsed && l.elapsed <= t && l.lap_time && !l.in_pit && l.pit_time === null &&
        (!this.car_class || l.car_class === this.car_class)).map((l) => l.lap_time);
      return laps.length >= 3 ? median(laps) : null;
    }
  }

  function recentPace(laps, n = 5) {
    const clean = laps.filter((l) => isGreen(l) && l.lap_time && !l.in_pit && l.pit_time === null)
      .map((l) => l.lap_time);
    let recent = clean.slice(-n);
    if (!recent.length) return null;
    const med = median(recent);
    recent = recent.filter((x) => x <= med * 1.07);
    return median(recent);
  }

  function carState(ctx, car, t) {
    const laps = ctx.completed(car, t);
    const info = ctx.race.carInfo(car);
    if (!laps.length) return { ...info, laps: 0, last_elapsed: null, in_pit: false };
    const last = laps[laps.length - 1];
    let sincePit = 0;
    for (let i = laps.length - 1; i >= 0; i--) { if (laps[i].in_pit) break; sincePit++; }
    const stops = ctx.stops.filter((s) => s.car === car && s.exit_time !== null && s.exit_time <= t);
    const service = stops.filter((s) => s.kind === "service");
    const opened = ctx.rules.window_open_s;
    const counted = service.filter((s) => !has(opened) || s.race_time >= opened - 60).length;
    const lastServiceExit = service.length ? Math.max(...service.map((s) => s.exit_time)) : 0;
    const drive = {};
    for (const lap of laps) if (lap.lap_time) drive[driverLabel(lap)] = (drive[driverLabel(lap)] || 0) + lap.lap_time;
    const current = driverLabel(last);
    if (!last.in_pit) drive[current] = (drive[current] || 0) + Math.max(0, t - last.elapsed);
    const state = {
      ...info, laps: last.lap, last_elapsed: last.elapsed, last_lap_time: last.lap_time,
      in_pit: last.in_pit, driver: current, stint_laps: sincePit, stops: stops.length,
      service_stops: service.length, counted_stops: counted, stint_s: t - lastServiceExit,
      pace: recentPace(laps), drive_time: drive,
    };
    state.remaining_service = remainingService(ctx, state, t);
    if (ctx.rules.max_stint_laps) state.fuel_laps_left = Math.max(0, ctx.rules.max_stint_laps - sincePit);
    return state;
  }

  function remainingService(ctx, state, t) {
    const r = ctx.rules;
    if (has(r.required_service_stops)) return Math.max(0, r.required_service_stops - state.counted_stops);
    if (r.max_stint_laps && state.pace) {
      const lapsToGo = Math.max(0, (ctx.duration - t) / state.pace);
      const fuelLeft = state.in_pit ? 0 : r.max_stint_laps - state.stint_laps;
      return Math.max(0, Math.ceil((lapsToGo - fuelLeft) / r.max_stint_laps));
    }
    if (r.max_stint_s) {
      const timeLeft = Math.max(0, ctx.duration - t);
      const fuelLeft = state.in_pit ? 0 : Math.max(0, r.max_stint_s - state.stint_s);
      return Math.max(0, Math.ceil((timeLeft - fuelLeft) / r.max_stint_s));
    }
    return 0;
  }

  function driveTimeStatus(rules, drive, current, t, duration, pitAllowance = 180, entry = null) {
    let limitsBy = rules.drivers || {};
    if (!Object.keys(limitsBy).length && rules.min_drive_s && entry && entry.length) {
      limitsBy = {};
      for (const n of entry) limitsBy[n] = { min_drive_s: rules.min_drive_s };
    }
    const names = Object.keys(limitsBy);
    if (!names.length) return null;
    const rows = [];
    let otherDeficit = 0;
    for (const name of names) {
      const limits = limitsBy[name] || {};
      const driven = drive[name] || 0;
      const minimum = Number(limits.min_drive_s || 0);
      const maximum = limits.max_drive_s === undefined ? null : limits.max_drive_s;
      const deficit = Math.max(0, minimum - driven);
      if (name !== current) otherDeficit += deficit;
      rows.push({ name, driven_s: pyRound(driven, 1), min_s: minimum, max_s: maximum,
        deficit_s: pyRound(deficit, 1) });
    }
    const latestChange = duration - otherDeficit - pitAllowance;
    const margin = latestChange - t;
    let status = "ok";
    if (otherDeficit > 0) {
      if (margin < 0) status = "impossible";
      else if (margin < 300) status = "change_now";
      else if (margin < 900) status = "change_soon";
    }
    const cur = limitsBy[current || ""] || {};
    let timeToMax = null;
    if (cur.max_drive_s) {
      timeToMax = cur.max_drive_s - (drive[current || ""] || 0);
      if (timeToMax < 300 && status === "ok") status = "max_drive_soon";
    }
    return { current, drivers: rows, latest_change_time: pyRound(latestChange, 1),
      margin_s: pyRound(margin, 1), time_to_max_s: timeToMax, status };
  }

  /** Net order keeps the timing order between cars owing the same number of stops. */
  function netOrder(cars) {
    const ordered = [];
    for (const car of sortBy(cars, (c) => [c.position])) {
      let k = ordered.length;
      while (k > 0) {
        const ahead = ordered[k - 1];
        if (ahead.remaining_service !== car.remaining_service && car.net_time_s < ahead.net_time_s) k--;
        else break;
      }
      ordered.splice(k, 0, car);
    }
    return ordered;
  }

  /** Earliest crossing of a lap in the class with each car's counted stops removed. */
  function stopFreeReference(ctx, lap, t, loss) {
    const key = `ref|${lap}|${pyRound(t, 3)}|${loss}`;
    if (ctx.memo.has(key)) return ctx.memo.get(key);
    const opened = ctx.rules.window_open_s;
    let best = null;
    for (const car of ctx.cars) {
      const when = ctx.lapTimeAt.get(car).get(lap);
      if (when === undefined || when > t) continue;
      const done = ctx.stops.filter((s) => s.car === car && s.kind === "service" && s.exit_time !== null &&
        s.exit_time <= when && (!has(opened) || s.race_time >= opened - 60)).length;
      const value = when - done * loss;
      if (best === null || value < best) best = value;
    }
    ctx.memo.set(key, best);
    return best;
  }

  function raceState(race, t, cls = null, focus = null, rules = null, ctx = null) {
    ctx = ctx || new RaceContext(race, cls, rules);
    const states = ctx.cars.map((car) => carState(ctx, car, t));
    const running = sortBy(states.filter((s) => s.laps > 0), (s) => [-s.laps, s.last_elapsed]);
    const leader = running[0];
    const loss = ctx.serviceLoss(t);
    running.forEach((s, i) => {
      const pos = i + 1;
      s.position = pos;
      const leadT = ctx.lapTimeAt.get(leader.car).get(s.laps);
      s.gap_s = leadT !== undefined ? pyRound(s.last_elapsed - leadT, 3) : null;
      s.laps_down = leader.laps - s.laps;
      if (pos > 1) {
        const aheadT = ctx.lapTimeAt.get(running[i - 1].car).get(s.laps);
        s.interval_s = aheadT ? pyRound(s.last_elapsed - aheadT, 3) : null;
      } else s.interval_s = null;
      const ref = stopFreeReference(ctx, s.laps, t, loss || 0);
      const owed = s.remaining_service * (loss || 0);
      s.net_time_s = ref === null ? null : pyRound(s.last_elapsed + owed - ref, 3);
    });
    const netSorted = netOrder(running.filter((s) => s.net_time_s !== null));
    if (netSorted.length) {
      const base = netSorted[0].net_time_s;
      netSorted.forEach((s, i) => { s.net_position = i + 1; s.net_gap_s = pyRound(s.net_time_s - base, 3); });
    }
    const result = {
      t, race_time_left_s: Math.max(0, ctx.duration - t), duration_s: ctx.duration,
      flag: ctx.flagAt(t), class: cls, service_loss_s: loss, cars: running,
      not_started: states.filter((s) => s.laps === 0).map((s) => s.car),
    };
    if (focus) {
      const f = states.find((s) => s.car === focus);
      if (!f) throw new Error(`Car '${focus}' not in class`);
      result.focus = { ...f, drive_status: driveTimeStatus(ctx.rules, f.drive_time || {}, f.driver, t,
        ctx.duration, 180, ctx.entry(focus)) };
    }
    return result;
  }

  // Caution model: past stops at the same point of a caution (see caution_model.py).
  const KNN_K = 25, GAIN_THRESHOLD_S = 5.0;
  function cautionDistance(a, b) {
    a = Math.max(0, a); b = Math.max(0, b);
    return Math.abs(a - b) / (Math.min(a, b) + 60);
  }
  function cautionNeighbours(entry, elapsed, k = KNN_K) {
    return sortBy(entry.samples || [], (r) => [cautionDistance(r[0], elapsed), r[0], r[1]]).slice(0, k);
  }
  function assessCaution(entry, elapsed, pitTime) {
    const near = cautionNeighbours(entry, elapsed);
    if (near.length < 5) return null;
    const gains = near.map((r) => r[1] * pitTime);
    const mid = quantile(gains, 0.5);
    const q = entry.residual_q90 !== undefined ? entry.residual_q90 : entry.residual_q80;
    const rng = has(q) ? [mid - q * pitTime, mid + q * pitTime] : [quantile(gains, 0.1), quantile(gains, 0.9)];
    return { p_gain: gains.filter((g) => g > GAIN_THRESHOLD_S).length / gains.length, gain_s: mid,
      range_s: rng, middle_s: [quantile(gains, 0.25), quantile(gains, 0.75)], n: near.length };
  }
  const mins = (seconds) => `${fmt(Math.max(0, seconds) / 60, 0)} min`;

  function cautionOpportunity(ctx, state, flag, t) {
    const rules = ctx.rules;
    const greenLoss = ctx.serviceLoss(t, "GF");
    const pit = ctx.pitLaneTime(t);
    const per = ctx.cautions.find((p) => p.flag === flag && p.start - 1 <= t && t <= p.end + 1);
    const start = per ? per.start : t;
    const pace = state.pace;
    const lapNow = ctx.cautionLap(t, flag) || (pace ? pace * (DEFAULT_CAUTION_RATIO[flag] || 1.6) : null);
    const arrival = Math.max(t, (state.last_elapsed || t) + (lapNow || 0));
    const entry = (rules.caution_model || {})[flag];
    const assessed = entry && Object.keys(entry).length && pit ? assessCaution(entry, arrival - start, pit) : null;
    let cautionLoss, basis, gain, pGain = null, gainRange = null, gainMiddle = null;
    if (assessed) {
      gain = assessed.gain_s; pGain = assessed.p_gain; gainRange = assessed.range_s; gainMiddle = assessed.middle_s;
      cautionLoss = has(greenLoss) ? greenLoss - gain : null;
      basis = `${assessed.n} stops made ${mins(arrival - start)} into earlier ${flag} periods`;
    } else {
      const observed = ctx.serviceLoss(t, flag);
      const learnedMap = rules.caution_loss_s || {};
      const learned = Object.prototype.hasOwnProperty.call(learnedMap, flag) ? learnedMap[flag] : null;
      if (has(observed)) { cautionLoss = observed; basis = `measured on ${flag} stops earlier in this race`; }
      else if (has(learned)) { cautionLoss = learned; basis = `learned from ${flag} stops in earlier races`; }
      else if (has(greenLoss) && pace) {
        const cl = ctx.cautionLap(t, flag);
        const ratio = cl ? cl / pace : (DEFAULT_CAUTION_RATIO[flag] || 1.6);
        cautionLoss = greenLoss - (ratio - 1.0) * rules.pit_track_equivalent_s;
        basis = `estimated: field laps ${fmt(ratio, 2)}x slower under ${flag}`;
      } else { cautionLoss = null; basis = "no pit-stop loss measured yet"; }
      gain = !has(greenLoss) || cautionLoss === null ? null : greenLoss - cautionLoss;
    }
    const remaining = state.remaining_service || 0;
    const notes = [];
    if (has(rules.window_open_s) && t < rules.window_open_s) notes.push(`pit window opens at ${clock(rules.window_open_s)}`);
    if (has(rules.window_close_s) && t > rules.window_close_s) notes.push("pit window closed");
    const status = driveTimeStatus(rules, state.drive_time || {}, state.driver, t, ctx.duration, 180,
      ctx.entry(state.car));
    let shortDriver = null;
    if (status) {
      const cur = status.drivers.find((d) => d.name === state.driver);
      if (cur && cur.deficit_s > 0) {
        shortDriver = cur;
        notes.push(`${cur.name} still needs ${fmt(cur.deficit_s / 60, 0)} min of drive time`);
      }
    }
    const chance = pGain === null ? "" : ` (${fmt(pGain * 100, 0)}% of similar stops gained time)`;
    let verdict, action;
    if (state.in_pit) { verdict = "Car is already in the pit lane"; action = "none"; }
    else if (remaining <= 0) { verdict = "No stop owed: stay out"; action = "stay"; }
    else if (notes.some((n) => n.includes("closed") || n.includes("opens"))) { verdict = "Stay out: pit window not open"; action = "stay"; }
    else if (shortDriver && remaining < 2) {
      verdict = `Stay out: a driver change now leaves ${shortDriver.name} ${fmt(shortDriver.deficit_s / 60, 0)} min short`;
      action = "stay";
    } else if (gain === null || gain === undefined) { verdict = "Caution: consider pitting (no loss data yet)"; action = "consider"; }
    else if ((pGain === null || pGain >= 0.5) && gain > MIN_USEFUL_GAIN_S) {
      const keep = shortDriver ? `, keep ${shortDriver.name} in the car` : "";
      verdict = `BOX BOX: stopping under ${flag} saves ~${fmt(gain, 0)}s${chance}${keep}`; action = "pit";
    } else { verdict = `Stay out: ${flag} saves only ~${fmt(Math.max(gain, 0), 0)}s${chance}`; action = "stay"; }
    return { flag, action, verdict, gain_s: gain === undefined ? null : gain, p_gain: pGain,
      gain_range_s: gainRange ? [gainRange[0], gainRange[1]] : null,
      gain_middle_s: gainMiddle ? [gainMiddle[0], gainMiddle[1]] : null,
      green_loss_s: has(greenLoss) ? greenLoss : null, caution_loss_s: has(cautionLoss) ? cautionLoss : null,
      basis, remaining_service: remaining, notes };
  }

  function classPosition(ctx, car, t) {
    const rows = [];
    for (const c of ctx.cars) {
      let best = null;
      for (const [lap, when] of ctx.lapTimeAt.get(c)) {
        if (when <= t && (best === null || cmpTuple([lap, when], best) > 0)) best = [lap, when];
      }
      if (best) rows.push([-best[0], best[1], c]);
    }
    rows.sort(cmpTuple);
    const i = rows.findIndex((r) => r[2] === car);
    return i >= 0 ? i + 1 : null;
  }

  function raceEvents(race, cls = null, focus = null, rules = null, until = null, ctx = null) {
    ctx = ctx || new RaceContext(race, cls, rules);
    const end = until !== null && until !== undefined ? until : Infinity;
    const events = [];
    const add = (t, type, severity, text, car = null, data = {}) => {
      if (t <= end) events.push({ t: pyRound(t, 3), type, severity, car, text, data });
    };
    for (const p of ctx.cautions) {
      add(p.start, "caution", "warn", `${p.flag} deployed`, null, { flag: p.flag });
      add(p.end, "green", "info", `${p.flag} ending, green flag`, null, { flag: p.flag });
      if (focus) {
        const st = carState(ctx, focus, p.start);
        if (st.laps) {
          const opp = cautionOpportunity(ctx, st, p.flag, p.start);
          const sev = opp.action === "pit" ? "urgent" : "info";
          const text = opp.verdict + (opp.notes.length ? "; " + opp.notes.join("; ") : "");
          add(p.start + 0.001, "caution_call", sev, text, focus, opp);
        }
      }
    }
    for (const s of ctx.stops) {
      const who = s.car === focus ? "We" : `#${s.car}`;
      const under = s.flag !== "GF" && s.flag !== "FF" ? `, under ${s.flag}` : "";
      add(s.race_time, "pit_in", s.car !== focus ? "info" : "warn",
        `${who} in the pits (lap ${s.in_lap}${under})`, s.car, { lap: s.in_lap, flag: s.flag });
      if (s.exit_time !== null) {
        const pit = s.pit_time ? `${fmt(s.pit_time, 0)}s` : "?";
        const change = s.driver_change ? `, ${s.driver_in} -> ${s.driver_out}` : "";
        add(s.exit_time, "pit_out", "info", `#${s.car} out of the pits: ${s.kind} stop, pit lane ${pit}${change}`,
          s.car, { kind: s.kind, pit_time: s.pit_time, driver_change: s.driver_change });
      }
    }
    if (focus) focusEvents(ctx, focus, add);
    return sortBy(events, (e) => [e.t, e.type]);
  }

  function focusEvents(ctx, focus, add) {
    const rules = ctx.rules;
    let lastStatus = "ok", lastPosition = null, windowWarnedAt = -1, paceWarnedStint = -1, stintNo = 0;
    let stintTimes = [];
    for (const lap of ctx.race.carLaps(focus)) {
      if (lap.elapsed === null) continue;
      const t = lap.elapsed;
      const st = carState(ctx, focus, t);
      const status = driveTimeStatus(rules, st.drive_time, st.driver, t, ctx.duration, 180, ctx.entry(focus));
      if (status && status.status !== lastStatus && status.status !== "ok") {
        const sev = status.status === "change_now" || status.status === "impossible" ? "urgent" : "warn";
        const needers = status.drivers.filter((d) => d.deficit_s > 0 && d.name !== st.driver).map((d) => d.name).join(", ");
        const text = {
          change_soon: `Driver change needed by ${clock(status.latest_change_time)} so ${needers} can reach minimum drive time`,
          change_now: `Change driver NOW: ${needers} still short of minimum`,
          impossible: `Minimum drive time can no longer be met for ${needers}`,
          max_drive_soon: `${st.driver} close to maximum drive time`,
        }[status.status];
        add(t, "drive_time", sev, text, focus, status);
      }
      if (status) lastStatus = status.status;
      const pos = classPosition(ctx, focus, t);
      if (lastPosition !== null && pos && pos !== lastPosition) {
        add(t, "position", "info", `P${pos} in class (was P${lastPosition})`, focus, { position: pos });
      }
      lastPosition = pos || lastPosition;
      if (lap.in_pit) { stintNo++; stintTimes = []; continue; }
      if (rules.max_stint_laps && st.fuel_laps_left !== undefined) {
        const left = st.fuel_laps_left;
        if (left <= 3 && windowWarnedAt !== stintNo && st.remaining_service > 0) {
          windowWarnedAt = stintNo;
          add(t, "fuel_window", "warn", `Box in ${left} laps: end of fuel window`, focus, { laps_left: left });
        }
      }
      if (isGreen(lap) && lap.lap_time && lap.pit_time === null) {
        stintTimes.push(lap.lap_time);
        if (stintTimes.length >= 8 && paceWarnedStint !== stintNo) {
          const ref = median(stintTimes.slice(0, -3));
          const recent = stintTimes.slice(-3);
          if (recent.every((x) => x > ref + 1.5)) {
            paceWarnedStint = stintNo;
            const d = median(recent) - ref;
            add(t, "pace", "warn", `Pace drop: last 3 laps +${fmt(d, 1)}s on stint median`, focus, { delta_s: d });
          }
        }
      }
    }
  }

  // ---------------------------------------------------------------- caution
  function evaluateCaution(c) {
    if (!(0 < c.green_lap_s && c.green_lap_s <= c.caution_lap_s)) throw new Error("caution_lap_s must be >= green_lap_s > 0");
    if (!(0 <= c.laps_into_stint && c.laps_into_stint <= c.max_stint_laps)) throw new Error("laps_into_stint must be between 0 and max_stint_laps");
    if (c.track_equivalent_s >= c.pit_lane_transit_s + c.stationary_s) throw new Error("Track equivalent must be shorter than pit transit + stationary");
    if (Math.min(c.race_time_left_s, c.caution_time_left_s, c.stationary_s) < 0) throw new Error("Times must be non-negative");
    const stopDuration = c.pit_lane_transit_s + c.stationary_s;
    const greenLoss = stopDuration - c.track_equivalent_s;
    const slow = c.caution_lap_s / c.green_lap_s;
    const full = stopDuration - c.track_equivalent_s * slow;
    const covered = stopDuration ? Math.min(1, c.caution_time_left_s / stopDuration) : 1;
    let cautionLoss = covered * full + (1 - covered) * greenLoss;
    cautionLoss = Math.max(cautionLoss, 0);
    const lapsToGo = c.race_time_left_s / c.green_lap_s;
    const fuelLeft = c.max_stint_laps - c.laps_into_stint;
    const need = (togo, fuel, max) => (togo <= fuel ? 0 : Math.ceil((togo - fuel) / max));
    const stay = need(lapsToGo, fuelLeft, c.max_stint_laps);
    const pit = need(lapsToGo, c.max_stint_laps, c.max_stint_laps);
    const costStay = stay * greenLoss, costPit = cautionLoss + pit * greenLoss;
    const gain = costStay - costPit;
    let verdict;
    if (stay === 0 && lapsToGo <= fuelLeft) verdict = "STAY OUT: you can reach the flag without stopping again";
    else if (gain > 0) verdict = `PIT NOW: saves about ${fmt(gain, 1)}s over the rest of the race`;
    else verdict = `STAY OUT: pitting now costs about ${fmt(-gain, 1)}s over the rest of the race`;
    return {
      inputs: { ...c }, green_stop_loss_s: pyRound(greenLoss, 2), caution_stop_loss_s: pyRound(cautionLoss, 2),
      caution_coverage: pyRound(covered, 3), laps_to_go: pyRound(lapsToGo, 1), fuel_laps_left: fuelLeft,
      stay_out: { remaining_stops: stay, time_lost_s: pyRound(costStay, 2) },
      pit_now: { remaining_stops: pit + 1, time_lost_s: pyRound(costPit, 2) },
      gain_if_pit_now_s: pyRound(gain, 2), verdict,
      assumptions: [
        "Field speed under caution is uniform; FCY/SC bunching effects are ignored.",
        "Remaining green stops are assumed to cost the same green pit loss.",
        "Safety Car pit-lane rules and closures differ by championship: check them.",
      ],
    };
  }

  // ---------------------------------------------------------------- planner
  function specFromDict(data) {
    const pit = { lane_loss_s: 30, refuel_base_s: 4, refuel_per_lap_s: 1, tyre_change_s: 14,
      driver_change_s: 12, tyres_parallel: false, driver_change_parallel: true, min_stop_loss_s: 0, ...(data.pit || {}) };
    const tyres = { deg_s_per_lap: 0.03, deg_quad_s: 0, warmup_s: 1.5, sets_available: 99,
      max_stints_per_set: 3, ...(data.tyres || {}) };
    const drivers = (data.drivers || []).map((d) => ({ name: d.name, pace_offset_s: Number(d.pace_offset_s || 0),
      min_drive_s: Number(d.min_drive_s || 0), max_drive_s: d.max_drive_s ? Number(d.max_drive_s) : Infinity }));
    return { duration_s: data.duration_s, base_lap_s: data.base_lap_s, max_stint_laps: data.max_stint_laps,
      drivers, pit, tyres, max_consecutive_stints: data.max_consecutive_stints !== undefined ? Number(data.max_consecutive_stints) : 3 };
  }
  function validateSpec(s) {
    if (!(600 <= s.duration_s && s.duration_s <= 30 * 3600)) throw new Error("duration_s must be between 10 minutes and 30 hours");
    if (!(30 <= s.base_lap_s && s.base_lap_s <= 600)) throw new Error("base_lap_s must be between 30 and 600 seconds");
    if (!(1 <= s.max_stint_laps && s.max_stint_laps <= 200)) throw new Error("max_stint_laps must be between 1 and 200");
    if (!(1 <= s.drivers.length && s.drivers.length <= 4)) throw new Error("Between one and four drivers are supported");
    if (new Set(s.drivers.map((d) => d.name)).size !== s.drivers.length) throw new Error("Driver names must be unique");
    if (s.tyres.sets_available < 1 || s.tyres.max_stints_per_set < 1) throw new Error("Need at least one tyre set and one stint per set");
    if (s.max_consecutive_stints < 1) throw new Error("max_consecutive_stints must be at least 1");
    if (sum(s.drivers.map((d) => d.min_drive_s)) > s.duration_s) throw new Error("Minimum drive times exceed the race duration");
  }
  function stationary(pit, refuelLaps, tyres, dc) {
    const refuel = refuelLaps ? pit.refuel_base_s + pit.refuel_per_lap_s * refuelLaps : 0;
    let total = refuel;
    if (tyres) total = pit.tyres_parallel ? Math.max(total, pit.tyre_change_s) : total + pit.tyre_change_s;
    if (dc) total = pit.driver_change_parallel ? Math.max(total, pit.driver_change_s) : total + pit.driver_change_s;
    return { refuel_s: refuel, stationary_s: total, loss_s: Math.max(pit.lane_loss_s + total, pit.min_stop_loss_s) };
  }
  function stintCost(ty, startAge, laps, fresh) {
    let cost = fresh ? ty.warmup_s : 0;
    for (let a = startAge; a < startAge + laps; a++) cost += ty.deg_s_per_lap * a + ty.deg_quad_s * a * a;
    return cost;
  }
  function layout(s, total) {
    const full = Math.floor(total / s.max_stint_laps), rest = total % s.max_stint_laps;
    return Array(full).fill(s.max_stint_laps).concat(rest ? [rest] : []);
  }
  function estimateLaps(s) {
    const stop = stationary(s.pit, s.max_stint_laps, true, true).loss_s;
    let laps = 0, clk = 0;
    while (clk < s.duration_s) { laps++; clk += s.base_lap_s; if (laps % s.max_stint_laps === 0) clk += stop; }
    return laps + 1;
  }
  function tyreAges(stintLaps, changes) {
    const ages = []; let age = 0, setNo = 1;
    stintLaps.forEach((laps, i) => {
      const fresh = i === 0 || changes[i - 1];
      if (i > 0 && fresh) { age = 0; setNo++; }
      ages.push([age, fresh, setNo]); age += laps;
    });
    return ages;
  }
  class InfeasiblePlan extends Error {}
  function solveTyres(s, stintLaps, seq) {
    const t = s.tyres;
    let states = new Map([[`1|1|${stintLaps[0]}`, [stintCost(t, 0, stintLaps[0], true), [], [1, 1, stintLaps[0]]]]]);
    for (let i = 1; i < stintLaps.length; i++) {
      const dc = seq[i] !== seq[i - 1];
      const nxt = new Map();
      for (const [, [cost, path, [onSet, used, age]]] of states) {
        for (const change of [false, true]) {
          if (change && used >= t.sets_available) continue;
          if (!change && onSet >= t.max_stints_per_set) continue;
          const stop = stationary(s.pit, stintLaps[i], change, dc).loss_s;
          const c = cost + stop + stintCost(t, change ? 0 : age, stintLaps[i], change);
          const key = change ? [1, used + 1, stintLaps[i]] : [onSet + 1, used, age + stintLaps[i]];
          const k = key.join("|");
          if (!nxt.has(k) || c < nxt.get(k)[0]) nxt.set(k, [c, path.concat([change]), key]);
        }
      }
      states = nxt;
    }
    if (!states.size) throw new InfeasiblePlan("Not enough tyre sets for this race: increase sets_available or max_stints_per_set");
    let best = null;
    for (const v of states.values()) if (best === null || v[0] < best[0]) best = v;
    return best[1];
  }
  function solveDrivers(s, stintLaps, changes) {
    const drivers = s.drivers, nd = drivers.length;
    const ages = tyreAges(stintLaps, changes);
    const tyreCost = ages.map(([a, f], i) => stintCost(s.tyres, a, stintLaps[i], f));
    const secsOf = (i, d) => stintLaps[i] * (s.base_lap_s + drivers[d].pace_offset_s) + tyreCost[i];
    const stopExtra = (i, dc) => (i === 0 || !dc ? 0 :
      stationary(s.pit, stintLaps[i], changes[i - 1], true).loss_s - stationary(s.pit, stintLaps[i], changes[i - 1], false).loss_s);
    let states = new Map();
    for (let d = 0; d < nd; d++) {
      const secs = secsOf(0, d);
      if (secs > drivers[d].max_drive_s) continue;
      const counts = drivers.map((_, k) => (k === d ? 1 : 0));
      const times = drivers.map((_, k) => (k === d ? secs : 0));
      states.set(`${d}|1|${counts.join(",")}`, [stintLaps[0] * drivers[d].pace_offset_s, times, [d], d, 1, counts]);
    }
    for (let i = 1; i < stintLaps.length; i++) {
      const nxt = new Map();
      for (const [cost, times, path, last, run, counts] of states.values()) {
        for (let d = 0; d < nd; d++) {
          const same = d === last;
          if (same && run >= s.max_consecutive_stints) continue;
          const secs = secsOf(i, d);
          if (times[d] + secs > drivers[d].max_drive_s) continue;
          const c = cost + stintLaps[i] * drivers[d].pace_offset_s + stopExtra(i, !same);
          const nc = counts.map((n, k) => n + (k === d ? 1 : 0));
          const nt = times.map((x, k) => x + (k === d ? secs : 0));
          const nrun = same ? run + 1 : 1;
          const k = `${d}|${nrun}|${nc.join(",")}`;
          if (!nxt.has(k) || c < nxt.get(k)[0]) nxt.set(k, [c, nt, path.concat([d]), d, nrun, nc]);
        }
      }
      states = nxt;
    }
    let best = null;
    for (const v of states.values()) {
      if (!drivers.every((dr, k) => v[1][k] >= dr.min_drive_s)) continue;
      if (best === null || v[0] < best[0]) best = v;
    }
    if (!best) throw new InfeasiblePlan("No driver rotation satisfies the drive-time limits; relax min/max drive time or max consecutive stints");
    return best[2];
  }
  function simulatePlan(s, stintLaps, changes, seq) {
    const ages = tyreAges(stintLaps, changes);
    let clk = 0, lapsDone = 0, lapsAtFlag = null, finish = null;
    const rows = [], stops = [], drive = {};
    for (const d of s.drivers) drive[d.name] = 0;
    stintLaps.forEach((laps, i) => {
      const driver = s.drivers[seq[i]];
      const [age, fresh, setNo] = ages[i];
      if (i > 0) {
        const dc = seq[i] !== seq[i - 1];
        const st = stationary(s.pit, laps, changes[i - 1], dc);
        stops.push({ after_stint: i, race_time: clk, tyres: changes[i - 1], driver_change: dc, refuel_laps: laps,
          refuel_s: pyRound(st.refuel_s, 2), stationary_s: pyRound(st.stationary_s, 2), loss_s: pyRound(st.loss_s, 2) });
        clk += st.loss_s;
      }
      const start = clk;
      for (let k = 0; k < laps; k++) {
        let lt = s.base_lap_s + driver.pace_offset_s;
        const a = age + k;
        lt += s.tyres.deg_s_per_lap * a + s.tyres.deg_quad_s * a * a;
        if (fresh && k === 0) lt += s.tyres.warmup_s;
        clk += lt; lapsDone++;
        if (lapsAtFlag === null && clk >= s.duration_s) { lapsAtFlag = lapsDone; finish = clk; }
      }
      drive[driver.name] += clk - start;
      rows.push({ stint: i + 1, driver: driver.name, laps, start: pyRound(start, 2), end: pyRound(clk, 2),
        tyre_set: setNo, tyre_age_start: age, new_tyres: fresh });
    });
    return { stints: rows, stops, planned_laps: lapsDone, laps_completed: lapsAtFlag, finish_time: finish,
      total_time: clk, drive_time: drive, tyre_sets_used: ages.length ? ages[ages.length - 1][2] : 0 };
  }
  const sameArr = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
  function optimise(s, stintLaps) {
    let changes = Array(stintLaps.length - 1).fill(true);
    let seq = solveDrivers(s, stintLaps, changes);
    for (let k = 0; k < 4; k++) {
      const nc = solveTyres(s, stintLaps, seq);
      const ns = solveDrivers(s, stintLaps, nc);
      if (sameArr(nc, changes) && sameArr(ns, seq)) break;
      changes = nc; seq = ns;
    }
    return [changes, seq];
  }
  function plan(data) {
    const s = specFromDict(data);
    validateSpec(s);
    let total = estimateLaps(s), result = null, lay = null, converged = false;
    for (let k = 0; k < 6; k++) {
      lay = layout(s, total);
      const [changes, seq] = optimise(s, lay);
      result = simulatePlan(s, lay, changes, seq);
      const done = result.laps_completed;
      if (done === null) { total += s.max_stint_laps; continue; }
      if (done === total) { converged = true; break; }
      total = done;
    }
    if (!converged) throw new InfeasiblePlan("Plan did not converge");
    const unlimited = { ...s, tyres: { ...s.tyres, sets_available: 999 } };
    const every = Array(lay.length - 1).fill(true);
    try {
      const ref = simulatePlan(unlimited, lay, every, solveDrivers(unlimited, lay, every));
      result.reference_fresh_tyres_every_stop = { description: "Fresh tyres at every stop, tyre allocation ignored",
        total_time: ref.total_time, tyre_sets_used: ref.tyre_sets_used,
        plan_minus_reference_s: pyRound(result.total_time - ref.total_time, 2) };
    } catch (e) {
      if (!(e instanceof InfeasiblePlan)) throw e;
      result.reference_fresh_tyres_every_stop = null;
    }
    result.drivers = s.drivers.map((d) => ({ name: d.name, drive_s: pyRound(result.drive_time[d.name], 1),
      min_s: d.min_drive_s, max_s: Number.isFinite(d.max_drive_s) ? d.max_drive_s : null }));
    result.notes = [
      "Drive time counts time on track per stint; pit stationary time is excluded.",
      "Finish = first line crossing after the clock expires (laps_completed).",
      "All inputs are parameters: replace the example values with your own data.",
    ];
    return result;
  }

  // ---------------------------------------------------------------- stop costs
  const REF_WINDOW_S = 120, MAX_REFS = 6;
  function stopCosts(race, cls = null) {
    if (!race.cache) race.cache = new Map();
    if (!race.cache.has("stop_costs")) race.cache.set("stop_costs", computeStopCosts(race));
    return race.cache.get("stop_costs").filter((c) => !cls || c.stop.car_class === cls);
  }
  function computeStopCosts(race) {
    const all = pitStops(race, null);
    const byCar = new Map();
    for (const s of all) { if (!byCar.has(s.car)) byCar.set(s.car, []); byCar.get(s.car).push(s); }
    const lapsByCar = new Map();
    for (const c of race.cars) {
      const m = new Map();
      for (const l of race.carLaps(c)) m.set(l.lap, l);
      lapsByCar.set(c, m);
    }
    const cautions = cautionPeriods(race);
    const fieldAll = new FieldPace(race, null);
    const out = [];
    for (const s of all) {
      const mine = lapsByCar.get(s.car);
      const period = cautions.find((p) => p.start - 1 <= s.race_time && s.race_time <= p.end + 30);
      const na = s.in_lap - 1;
      let nb = s.in_lap + 1;
      if (period && flagGroup(s.flag) !== "GREEN") {
        const after = [...mine.values()].filter((l) => l.elapsed && l.elapsed > period.end).map((l) => l.lap);
        if (after.length) nb = Math.max(nb, Math.min(...after));
      }
      let cost = null, method = "none", nrefs = 0, known = s.exit_time || s.race_time;
      if (mine.has(na) && mine.has(nb) && mine.get(na).elapsed && mine.get(nb).elapsed) {
        const ta = mine.get(na).elapsed, tb = mine.get(nb).elapsed;
        let refs = [];
        for (const [other, laps] of lapsByCar) {
          if (other === s.car || !laps.has(na) || !laps.has(nb)) continue;
          const la = laps.get(na), lb = laps.get(nb);
          if (la.elapsed === null || lb.elapsed === null || Math.abs(la.elapsed - ta) > REF_WINDOW_S) continue;
          if ((byCar.get(other) || []).some((x) => na <= x.in_lap && x.in_lap <= nb)) continue;
          refs.push([la.car_class !== s.car_class ? 1 : 0, Math.abs(la.elapsed - ta), lb.elapsed - la.elapsed]);
        }
        refs = sortBy(refs, (r) => r).slice(0, MAX_REFS);
        if (refs.length) {
          cost = (tb - ta) - median(refs.map((r) => r[2]));
          method = "neighbours"; nrefs = refs.length; known = tb;
        }
      }
      if (cost === null) {
        cost = s.loss_vs_field;
        if (cost === null && flagGroup(s.flag) !== "GREEN" && s.exit_time !== null) {
          const ri = fieldAll.at(s.race_time, s.flag), ro = fieldAll.at(s.exit_time, s.flag);
          if (ri && ro && s.in_lap_time && s.out_lap_time) cost = s.in_lap_time + s.out_lap_time - ri - ro;
        }
        if (cost !== null) { method = "field"; known = (s.exit_time || s.race_time) + 150; }
      }
      out.push({ stop: s, cost_s: cost, method, refs: nrefs, known_at: known });
    }
    return out;
  }

  // ---------------------------------------------------------------- fit
  function quantile(values, q) {
    const v = values.slice().sort((a, b) => a - b);
    const pos = (v.length - 1) * q, lo = Math.floor(pos), hi = Math.min(lo + 1, v.length - 1);
    return v[lo] + (v[hi] - v[lo]) * (pos - lo);
  }
  function robustRange(values) {
    if (values.length < 4) return null;
    const q1 = quantile(values, 0.25), q3 = quantile(values, 0.75), spread = q3 - q1;
    const kept = values.filter((v) => q1 - 1.5 * spread <= v && v <= q3 + 1.5 * spread);
    return [Math.min(...kept), Math.max(...kept)];
  }
  function countValues(values) {
    const counts = new Map();
    for (const v of values) counts.set(v, (counts.get(v) || 0) + 1);
    return counts;
  }
  function mostCommonWithCount(values) {
    let best = null, bestN = -1;
    for (const [v, n] of countValues(values)) if (n > bestN) { best = v; bestN = n; }
    return [best, bestN];
  }

  function fitCautionModel(races, greenExtra = 5.5) {
    const samples = new Map(), durations = new Map();
    races.forEach((race, raceNo) => {
      const periods = cautionPeriods(race);
      for (const p of periods) { if (!durations.has(p.flag)) durations.set(p.flag, []); durations.get(p.flag).push(p.duration); }
      const costs = stopCosts(race);
      const normal = costs.filter((c) => c.stop.kind === "service" && c.stop.pit_time).map((c) => c.stop.pit_time);
      if (!normal.length) return;
      const limit = 1.3 * median(normal);
      for (const c of costs) {
        const st = c.stop, g = flagGroup(st.flag);
        if (st.kind !== "service" || g === "GREEN" || c.method !== "neighbours" || !st.pit_time ||
            st.pit_time > limit || c.cost_s === null) continue;
        const p = periods.find((p) => p.start - 1 <= st.race_time && st.race_time <= p.end + 30);
        if (p) {
          if (!samples.has(g)) samples.set(g, []);
          samples.get(g).push([pyRound(st.race_time - p.start, 1),
            pyRound((greenExtra - (c.cost_s - st.pit_time)) / st.pit_time, 3), raceNo]);
        }
      }
    });
    const model = {};
    for (const [flag, rows] of samples) {
      if (rows.length < 5) continue;
      const residuals = [];
      for (const row of rows) {
        const near = cautionNeighbours({ samples: rows.filter((r) => r[2] !== row[2]) }, row[0]).map((r) => r[1]);
        if (near.length >= 5) residuals.push(Math.abs(row[1] - median(near)));
      }
      const entry = { samples: sortBy(rows.map((r) => [r[0], r[1]]), (r) => r),
        periods: (durations.get(flag) || []).length };
      if (residuals.length >= 10) {
        entry.residual_q80 = pyRound(quantile(residuals, 0.8), 3);
        entry.residual_q90 = pyRound(quantile(residuals, 0.9), 3);
      }
      model[flag] = entry;
    }
    return model;
  }

  function fitRules(races, cls, duration = null, cautionModel = null) {
    let pairs = races.filter((r) => r.classes.includes(cls) && !r.red_flagged);
    if (!pairs.length) pairs = races.filter((r) => r.classes.includes(cls));
    if (!pairs.length) throw new Error(`Class '${cls}' not found in the given races`);
    const target = duration || mostCommon(pairs.map((r) => r.scheduled_duration));
    const anySame = pairs.some((r) => Math.abs(r.scheduled_duration - target) <= 300);
    const serviceCounts = [], changeFracs = [], stintLaps = [], stintSecs = [], pitTimes = [];
    const extras = new Map(), losses = new Map();
    const push = (m, k, v) => { if (!m.has(k)) m.set(k, []); m.get(k).push(v); };
    for (const race of pairs) {
      const sameLen = Math.abs(race.scheduled_duration - target) <= 300;
      const stops = pitStops(race, cls);
      const perCar = {};
      for (const s of stops) if (s.kind === "service") perCar[s.car] = (perCar[s.car] || 0) + 1;
      const carsIn = race.carsInClass(cls);
      const maxLaps = Math.max(...carsIn.map((c) => { const L = race.carLaps(c); return L[L.length - 1].lap; }));
      const finishers = carsIn.filter((c) => { const L = race.carLaps(c); return L[L.length - 1].lap >= 0.9 * maxLaps; });
      if (sameLen || !anySame) for (const car of finishers) serviceCounts.push(perCar[car] || 0);
      for (const s of stops) {
        if (s.kind === "service" && s.driver_change) changeFracs.push(s.race_time / race.scheduled_duration);
        if (s.kind === "service" && s.pit_time) pitTimes.push(s.pit_time);
      }
      for (const c of stopCosts(race, cls)) {
        const st = c.stop;
        if (st.kind !== "service" || c.cost_s === null) continue;
        const g = flagGroup(st.flag);
        push(losses, g, c.cost_s);
        if (c.method === "neighbours" && c.refs >= 2 && st.pit_time) push(extras, g, c.cost_s - st.pit_time);
      }
      for (const car of finishers) {
        for (const x of stints(race, car)) {
          stintLaps.push(x.laps);
          if (x.ended_in_pit && x.duration > 600) stintSecs.push(x.duration);
        }
      }
    }
    let required = null;
    if (serviceCounts.length) {
      const [mode, count] = mostCommonWithCount(serviceCounts);
      if (count >= 0.7 * serviceCounts.length) required = mode;
    }
    const pitLane = pitTimes.length ? median(pitTimes) : null;
    const extra = {}, spread = {};
    for (const [k, v] of extras) if (v.length >= 3) extra[k] = median(v);
    for (const [k, v] of extras) {
      if (!(k in extra)) continue;
      const res = v.map((x) => x - extra[k]);
      spread[k] = [pyRound(quantile(res, 0.2), 1), pyRound(quantile(res, 0.8), 1)];
    }
    const costExtra = {};
    for (const k of Object.keys(extra)) costExtra[k] = pyRound(extra[k], 1);
    const rules = {
      duration_s: target, required_service_stops: required,
      pit_lane_s: pitLane ? pyRound(pitLane, 1) : null,
      service_loss_s: pitLane && "GREEN" in extra ? pyRound(pitLane + extra.GREEN, 1)
        : (losses.get("GREEN") ? pyRound(median(losses.get("GREEN")), 1) : null),
      cost_extra_s: costExtra, cost_spread_s: spread,
    };
    const model = cautionModel !== null ? cautionModel : fitCautionModel(pairs);
    if (Object.keys(model).length) rules.caution_model = model;
    const cautions = {};
    for (const k of Object.keys(extra)) if (k !== "GREEN" && pitLane) cautions[k] = pyRound(pitLane + extra[k], 1);
    if (Object.keys(cautions).length) rules.caution_loss_s = cautions;
    if (required === null && stintSecs.length >= 5) rules.max_stint_s = pyRound(quantile(stintSecs, 0.9), 0);
    const window = required === 1 ? robustRange(changeFracs) : null;
    if (window) {
      rules.window_open_s = pyRound(window[0] * target, 0);
      rules.window_close_s = pyRound(window[1] * target, 0);
    }
    const perCount = {};
    for (const [n, c] of countValues(serviceCounts)) perCount[n] = c;
    const byFlag = {}, nByFlag = {}, nExtra = {};
    for (const [k, v] of losses) { byFlag[k] = pyRound(median(v), 1); nByFlag[k] = v.length; }
    for (const [k, v] of extras) nExtra[k] = v.length;
    return { class: cls, rules, evidence: {
      races: pairs.length, same_length_races: pairs.filter((r) => Math.abs(r.scheduled_duration - target) <= 300).length,
      service_stops_per_car: perCount, median_service_pit_lane_s: pitLane ? pyRound(pitLane, 1) : null,
      median_loss_by_flag_s: byFlag, stops_by_flag: nByFlag, neighbour_measured_by_flag: nExtra,
      longest_stint_laps: stintLaps.length ? Math.max(...stintLaps) : null, driver_change_stops: changeFracs.length } };
  }

  // ---------------------------------------------------------------- debrief
  function debrief(race, car, rules = null) {
    rules = makeRules(rules);
    const info = race.carInfo(car), cls = info.class;
    const table = classSummary(race, cls);
    const row = table.find((r) => r.car === car), winner = table[0];
    const classDrivers = new Map();
    for (const other of race.carsInClass(cls)) {
      for (const st of stints(race, other)) {
        if (!st.median_clean) continue;
        const k = `${other}\u0000${st.driver}`;
        if (!classDrivers.has(k)) classDrivers.set(k, []);
        for (let i = 0; i < st.clean_laps; i++) classDrivers.get(k).push(st.median_clean);
      }
    }
    const ranked = [...classDrivers.values()].filter((v) => v.length).map(median).sort((a, b) => a - b);
    const benchmark = ranked.length ? median(ranked) : null, fastest = ranked.length ? ranked[0] : null;
    const drivers = new Map();
    for (const st of stints(race, car)) {
      if (!drivers.has(st.driver)) drivers.set(st.driver, { name: st.driver, laps: 0, clean_laps: 0, drive_s: 0 });
      const d = drivers.get(st.driver);
      d.laps += st.laps; d.clean_laps += st.clean_laps; d.drive_s += st.duration;
    }
    let paceLoss = 0;
    for (const d of drivers.values()) {
      const laps = classDrivers.get(`${car}\u0000${d.name}`) || [];
      d.median_pace = laps.length ? median(laps) : null;
      d.class_rank = d.median_pace ? ranked.indexOf(d.median_pace) + 1 : null;
      d.class_drivers = ranked.length;
      d.delta_to_class_median_s = d.median_pace && benchmark ? pyRound(d.median_pace - benchmark, 3) : null;
      d.delta_to_fastest_s = d.median_pace && fastest ? pyRound(d.median_pace - fastest, 3) : null;
      d.pace_loss_s = pyRound(Math.max(0, d.delta_to_class_median_s || 0) * d.clean_laps, 1);
      paceLoss += d.pace_loss_s;
    }
    const classStops = pitStops(race, cls);
    const greenService = classStops.filter((s) => s.kind === "service" && flagGroup(s.flag) === "GREEN" && s.loss_vs_field !== null).map((s) => s.loss_vs_field);
    const refGreen = greenService.length ? median(greenService) : null;
    const byFlag = new Map();
    for (const s of classStops) {
      if (s.kind === "service" && s.loss_vs_field !== null) {
        const g = flagGroup(s.flag);
        if (!byFlag.has(g)) byFlag.set(g, []);
        byFlag.get(g).push(s.loss_vs_field);
      }
    }
    const refByFlag = new Map([...byFlag].map(([k, v]) => [k, median(v)]));
    const stops = [];
    let pitExcess = 0, otherStopLoss = 0;
    for (const s of classStops) {
      if (s.car !== car) continue;
      const ref = s.kind === "service" && refByFlag.has(flagGroup(s.flag)) ? refByFlag.get(flagGroup(s.flag)) : null;
      let excess = null;
      if (ref !== null && s.loss_vs_field !== null) { excess = pyRound(s.loss_vs_field - ref, 1); pitExcess += Math.max(0, excess); }
      else if (s.kind !== "service" && s.loss_vs_field !== null) otherStopLoss += s.loss_vs_field;
      stops.push({ lap: s.in_lap, race_time: s.race_time, kind: s.kind, flag: s.flag, pit_time: s.pit_time,
        loss_s: s.loss_vs_field, class_median_s: ref, excess_s: excess, driver_change: s.driver_change });
    }
    let window = null;
    if (rules.window_open_s !== null && rules.window_close_s !== null) window = [rules.window_open_s, rules.window_close_s];
    else window = robustRange(classStops.filter((s) => s.kind === "service" && s.driver_change).map((s) => s.race_time));
    const ownService = stops.filter((s) => s.kind === "service");
    const firstService = ownService.length ? ownService[0] : null;
    const missed = [], used = [];
    const periods = cautionPeriods(race);
    for (const p of periods) {
      const inside = window === null || (window[0] - 60 <= p.start && p.start <= window[1]);
      const pitted = ownService.filter((s) => p.start - 30 <= s.race_time && s.race_time <= p.end + 30);
      if (pitted.length) { used.push({ ...p, lap: pitted[0].lap }); continue; }
      const owed = firstService === null || firstService.race_time > p.start;
      const flagRef = refByFlag.has(p.flag) ? refByFlag.get(p.flag) : null;
      if (inside && owed && firstService && flagGroup(firstService.flag) === "GREEN" && flagRef !== null && refGreen !== null) {
        missed.push({ ...p, potential_gain_s: pyRound(refGreen - flagRef, 1) });
      }
    }
    const cautionGain = missed.length ? Math.max(...missed.map((m) => m.potential_gain_s)) : 0;
    const nearMisses = [];
    for (const p of periods) for (const s of ownService) {
      const gap = p.start - s.race_time;
      if (flagGroup(s.flag) === "GREEN" && 0 < gap && gap <= 120) nearMisses.push({ flag: p.flag, after_s: pyRound(gap, 1), lap: s.lap });
    }
    const findings = [];
    if (winner.car !== car) {
      if (winner.laps === row.laps && winner.finish_time && row.finish_time) {
        findings.push(`Finished P${row.position} in ${cls}, ${fmt(row.finish_time - winner.finish_time, 1)}s behind the winner`);
      } else findings.push(`Finished P${row.position} in ${cls}, ${winner.laps - row.laps} lap(s) behind the winner`);
    } else findings.push(`Won ${cls}`);
    const drv = sortBy([...drivers.values()], (d) => [-(d.pace_loss_s || 0)]);
    for (const d of drv) {
      if (d.delta_to_class_median_s === null) continue;
      let text = `${d.name}: ${lapStr(d.median_pace)} median pace, ${d.class_rank}/${d.class_drivers} in class, ${fmtSigned(d.delta_to_class_median_s, 2)}s/lap vs the class median driver`;
      if (d.pace_loss_s > 0) text += ` (${fmt(d.pace_loss_s, 0)}s over ${d.clean_laps} clean laps)`;
      if (d.clean_laps < 5) text += " [small sample: few clean green laps]";
      findings.push(text);
    }
    for (const s of stops) {
      if (s.excess_s !== null && Math.abs(s.excess_s) >= 3) {
        findings.push(`Lap ${s.lap} ${s.kind} stop under ${s.flag}: ${s.excess_s > 0 ? "lost" : "gained"} ${fmt(Math.abs(s.excess_s), 0)}s vs the class median stop`);
      }
    }
    for (const m of missed) findings.push(`${m.flag} at ${clock(m.start)} came while the stop was still owed: stopping then could have saved ~${fmt(m.potential_gain_s, 0)}s`);
    for (const n of nearMisses) findings.push(`Unlucky: ${n.flag} came ${fmt(n.after_s, 0)}s after the lap ${n.lap} stop under green`);
    if (otherStopLoss > 0) findings.push(`Extra (short/garage) stops cost ${fmt(otherStopLoss, 0)}s`);
    const stopLossByFlag = {};
    for (const [k, v] of refByFlag) stopLossByFlag[k] = pyRound(v, 1);
    return {
      car, class: cls, team: info.team, race: race.name, position: row.position, laps: row.laps,
      finish_time: row.finish_time,
      winner: { car: winner.car, team: winner.team, laps: winner.laps, finish_time: winner.finish_time },
      class_median_driver_pace: benchmark, class_fastest_driver_pace: fastest,
      drivers: [...drivers.values()], stops, class_stop_loss_by_flag: stopLossByFlag, pit_window: window,
      cautions_used: used, cautions_missed: missed, near_misses: nearMisses,
      time_accounting_s: { pace_vs_class_median_driver: pyRound(paceLoss, 1),
        pit_stops_vs_class_median: pyRound(pitExcess, 1), extra_stops: pyRound(otherStopLoss, 1),
        best_missed_caution: pyRound(cautionGain, 1) },
      findings,
    };
  }

  return {
    version: "0.2.0", pyRound, median, clock, lapStr, normalizeFlag, parseDuration, parseCSV, Race,
    stopKind, flagGroup, stints, FieldPace, pitStops, driverTimes, cautionPeriods, pitLossByFlag,
    carReport, classSummary, raceOverview, makeRules, RaceContext, carState, driveTimeStatus,
    raceState, cautionOpportunity, raceEvents, evaluateCaution, plan, specFromDict, fitRules, debrief,
    stopCosts, fitCautionModel, assessCaution, cautionNeighbours,
  };
});
