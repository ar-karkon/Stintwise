# Accuracy report

Every number below comes from `stintwise benchmark data/races`: a chronological backtest
on **56 real races** (Michelin Le Mans Cup 2022–2026, ELMS 2023–2026; 2,426 entries,
152,855 laps) with the official classification of each race.

**How it is scored.** Each race is predicted with what a pit wall could have known: rules
and costs are learned only from *earlier* races, and in-race facts only up to the moment
of each decision. Truth comes from the race's own timing and from the official results.

| What the pit wall says | Result | Target | Cases | Met |
|---|---:|---:|---:|:---:|
| Class order agrees with official results (pairs of cars, penalised cars excluded) | **99.9%** | ≥ 99% | 11,978 | yes |
| Laps match the official classification | **99.2%** | ≥ 99% | 2,108 | yes |
| Driver-change stops inside the predicted pit window | **96.0%** | ≥ 95% | 926 | yes |
| Stops per car (mandatory stop exact; fuel-limited races within one) | **90.9%** | ≥ 85% | 1,519 | yes |
| Minimum drive time predicted exactly | **100%** | ≥ 90% | 31 | yes |
| Drivers our drive-time count puts below the official minimum | **1.3%** | ≤ 2% | 1,257 | yes |
| Green stop: cost beyond pit-lane time, median error | **5.0 s** | ≤ 8 s | 2,757 | yes |
| Caution stop: probability of gaining time, calibration error | **0.034** | ≤ 0.10 | 93 | yes |
| Caution stop: outcome inside the stated 90% range | **83.9%** | ≥ 75% | 93 | yes |
| Service stops with a measured cost | **94.0%** | ≥ 90% | 4,999 | yes |
| Caution stop: gain, median error | 39.3 s | ≤ 30 s | 93 | no |
| Caution call right when the outcome was clear (> 10 s either way) | 72.9% | ≥ 85% | 85 | no |
| One car has stopped, the other not: who is ahead after the cycle | 77.0% | ≥ 80% | 1,219 | no |

## What changed during development

| Metric | First measurement | Now |
|---|---:|---:|
| Green stop cost error | 18.0 s | 5.0 s |
| Caution stop cost error | 58.2 s | 39.3 s |
| Caution calls on clear cases | 72.0% (uncalibrated) | 72.9%, calibrated to 0.034 |
| Pit window coverage | 94.1% | 96.0% |
| Stops per car | 68.9% | 90.9% |
| Minimum drive time | 76.2% | 100% |
| Net order, mixed pairs (timing screen: 73.7%) | 73.8% | 77.0% |

The main fixes: stop cost measured against neighbouring cars that stayed out instead of
the field's median lap; the mandatory stop counted only inside its window; rules learned
from races of the same length; red-flagged races left out of rule learning; the minimum
drive time read from the official classification; net order computed in a stop-free time
frame; caution calls learned from past stops made at the same point of a caution, with
calibrated probabilities and conformal ranges.

## The three targets not met, and why

**Caution calls (72.9% on clear cases, gain error 39 s).** Lap timing cannot see where a
car sits in the Safety Car queue or whether it gets caught behind it. Even when the caution
fully covered the stop, 16% of Safety Car stops still lost time. In every subgroup that
timing *can* see (flag type, how long the caution has run, stop length, position in the
field, how many cars pit together) stopping won 59–87% of the time, so "box" is the better
call in every subgroup and no timing-based rule can do better than the share of winning
stops. What the pit wall can do, and does, is state that share honestly: when it says
"84% of similar stops gained time", that comes true about 84% of the time (calibration
error 0.034). Adding the car's position in the field cut the gain error to 35 s, but its
weight would have been tuned on the test races, so it was left out.

**Net order during the stop cycle (77%).** Net order beats the timing screen where it
matters, on pairs where one car has stopped and the other has not: 74.8% vs 69.3% in Le Mans
Cup and 79.2% vs 78.1% in ELMS. The rest is variance nobody can see in advance: one crew's
stop takes 175 s instead of 162 s, a slow out-lap, a pass on track.

## Where the pit wall says "I don't know"

- **First race of a new length** (16 class entries, e.g. the first 3-hour Road to Le Mans in
  2026): stop count, window and minimum drive time are flagged as having no history instead
  of being scaled from other race lengths.
- **Red-flagged races**: left out of rule learning; whether the race clock stopped during the
  stoppage differs from race to race and is not in the timing data.
- **Post-race penalties** are not in lap timing. All of the remaining 3.4% of class-order
  differences against the official results are cars the stewards penalised.

## Reproduce

```bash
python scripts/fetch_alkamel.py lemanscup 2022 2023 2024 2025 2026
python scripts/fetch_alkamel.py elms 2023 2024 2025 2026
stintwise benchmark data/races
```
