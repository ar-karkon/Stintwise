// Runs the browser engine in Node for tests/test_js_parity.py.
// Usage: node run_engine.js <job.json>   (prints JSON results)
const fs = require("fs");
const path = require("path");
const S = require(path.join(__dirname, "../../src/stintwise/static/engine.js"));

const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const races = {};
for (const [id, file] of Object.entries(job.races)) {
  races[id] = S.parseCSV(fs.readFileSync(file, "utf8"), id);
}
const out = [];
for (const task of job.tasks) {
  const r = races[task.race];
  let value;
  try {
    switch (task.kind) {
      case "overview": value = S.raceOverview(r, task.cls); break;
      case "car_report": value = S.carReport(r, task.car); break;
      case "state": value = S.raceState(r, task.t, task.cls, task.focus, task.rules); break;
      case "events": value = S.raceEvents(r, task.cls, task.focus, task.rules, task.until); break;
      case "debrief": value = S.debrief(r, task.car, task.rules); break;
      case "fit": value = S.fitRules(task.races.map((id) => races[id]), task.cls, task.duration || null,
        task.caution_model === undefined ? null : task.caution_model); break;
      case "costs": value = S.stopCosts(r).map((c) => ({ car: c.stop.car, in_lap: c.stop.in_lap,
        cost_s: c.cost_s, method: c.method, refs: c.refs, known_at: c.known_at })); break;
      case "caution_model": value = S.fitCautionModel(task.races.map((id) => races[id])); break;
      case "plan": value = S.plan(task.spec); break;
      case "caution": value = S.evaluateCaution(task.call); break;
      case "round": value = task.values.map(([x, n]) => S.pyRound(x, n)); break;
      default: throw new Error("unknown task " + task.kind);
    }
  } catch (e) {
    value = { error: String(e.message || e) };
  }
  out.push(value);
}
process.stdout.write(JSON.stringify(out, (k, v) => (v === Infinity ? null : v)));
