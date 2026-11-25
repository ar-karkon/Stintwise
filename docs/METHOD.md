# Method and assumptions

## Stint planner (`stintwise.planner`)

**Objective:** minimise total race time for a timed race; report the laps
completed when the clock expires (finish = first line crossing after the
clock reaches zero).

**Stint layout.** Every stint runs the maximum laps allowed by the fuel or
energy allocation (`max_stint_laps`); the final stint is shortened to what is
needed to reach the flag. The planner iterates until the planned laps equal
the laps the plan actually completes.

**Lap time** = base lap + driver pace offset + tyre degradation
(`deg_s_per_lap · age + deg_quad_s · age²`) + a warm-up penalty on the first
lap of a new set.

**Pit stop** = pit lane loss + stationary time. Stationary time is refuel
(fixed + per lap of fuel added) and, depending on the championship rules you
configure, tyre change and driver change either in sequence or in parallel
with refuelling.

**Tyres (exact DP).** For a fixed driver sequence, choose at which stops to fit
a new set. State = (stints on current set, sets used, laps on set). Hard
limits: `sets_available` (including the starting set) and `max_stints_per_set`.

**Drivers (exact DP).** For fixed tyre decisions, choose the driver of each
stint. State = (last driver, consecutive stints, stints per driver). Hard
limits: minimum and maximum total drive time per driver and
`max_consecutive_stints`. Cost = driver pace offset × laps + extra stop time
caused by a driver change.

The two problems only interact through pit-stop time, so the planner
alternates the two solvers until neither changes. Both solvers are checked
against brute-force enumeration in the tests.

**Reference strategy.** Every plan is compared with "fresh tyres at every stop,
tyre allocation ignored", which shows what the allocation costs, or that
double stinting is faster anyway.

### Known limitations
- Rolling drive-time windows (e.g. "no more than X hours in any Y-hour
  window") are approximated with `max_consecutive_stints`.
- No traffic, no multi-class interaction, no fuel-saving or energy
  (Virtual Energy Tank) modelling beyond the fixed stint length.
- Deterministic: caution periods are evaluated separately (below).

## Caution pit call (`stintwise.caution`)

- Green stop loss = pit lane transit + stationary − the time the same stretch
  takes on track at racing speed.
- Caution stop loss = the same, with the track stretch at caution speed
  (scaled by caution lap / green lap). If the caution is expected to end
  before the stop is finished, only that fraction of the stop benefits.
- Remaining stops: counted from fuel laps left and laps still to run, for
  "pit now" and "stay out". Gain = difference in total pit time lost.

## Live engine (`stintwise.live`)

Everything is computed as of a race time `t` from crossings that had happened by `t`; a
pit stop's cost becomes known 150 s after the out-lap (when the field laps used to
measure it exist). Tests check that cutting the file at `t` does not change the state.

- **Class order and gaps:** laps completed, then crossing time. A car's gap is its
  crossing time minus the leader's crossing of the same lap.
- **Stops owed:** `required_service_stops` minus service stops completed; without that
  rule, from fuel laps left and laps to go when `max_stint_laps` is known.
- **Net order:** each car's last crossing minus a stop-free reference (the earliest
  crossing of that lap with every car's completed stops taken off at the standard cost),
  plus the stops it still owes. Cars owing the same number of stops keep their timing
  order. The standard cost is the pit-lane time measured in this race (after two stops)
  plus the learned extra.
- **Caution call** (`stintwise.caution_model`): the 25 past stops made at the most similar
  point of an earlier caution of the same kind (FCY or Safety Car), pooled over every
  class, give the chance the stop gains time, the median gain and the middle half, all
  as a share of our pit-lane time. A conformal 90% range is sized by the model's errors
  on races it had not seen. The call is "stay out" when no stop is owed, the window is
  not open, or a driver change would leave the current driver short of minimum drive
  time with no later stop to fix it.
- **Stop cost** (`stintwise.costs`): time lost against up to six cars on the same lap,
  within two minutes, that made no stop over the in-lap and out-lap (extended to the
  restart for a stop under a caution).
- **Drive-time watch:** latest change = race length − remaining minimums of the other
  drivers − 3 min pit allowance.

## Learned rules (`stintwise.fit`)

From earlier races of a class: the most common number of service stops per car, the
driver-change window (range of driver-change stop times, outliers beyond 1.5 × IQR
removed, only when one stop is required), and the median cost of a service stop under
green, FCY and Safety Car (at least three stops per flag).

## Debrief (`stintwise.debrief`)

Each driver's median clean pace is ranked among all drivers of the class; pace loss is
counted against the class median driver over the driver's clean laps. Every service
stop is compared with the class median stop under the same flag. Cautions inside the
window that came while the stop was still owed are listed with the saving the class saw
under that flag; cautions that came within two minutes after a green-flag stop are
listed as near misses.

## Race analysis (`stintwise.analysis`)

- **Stint**: laps between two pit entries (`CROSSING_FINISH_LINE_IN_PIT = B`).
- **Stop kind** from pit-lane time: short ≤ 60 s (splash or drive-through), garage
  ≥ 600 s, otherwise service.
- **Clean pace**: green-flag laps excluding the out-lap and in-lap and laps
  slower than 107 % of the stint median.
- **Degradation**: least-squares slope of clean lap time against lap in stint.
- **Pit loss vs field**: in-lap + out-lap − the class median lap time at the
  same moment (±150 s, widened to ±300 s if needed) under the same flag. When a whole
  class pits under the same caution there are no reference laps and no value is given.
  This is a relative measure: it shows how cheap stops under FCY or Safety Car
  were compared with green-flag stops.
- **Drive time**: sum of the lap times of the laps a driver set
  (approximation of the official drive time, which uses pit-lane timing lines).
