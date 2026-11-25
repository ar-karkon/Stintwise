# Case study: pit-stop timing in the 2026 Michelin Le Mans Cup

**Data:** the official lap analysis files of all six 2026 Le Mans Cup races (five 2-hour
races and the 3-hour Road to Le Mans): 268 car entries, 11,908 laps, classes LMP3,
LMP3 Pro/Am and GT3. All figures below are derived with Stintwise from those files
(`stintwise fit`, `stintwise debrief`, `stintwise events`). The raw timing is not
redistributed.

## 1. What the mandatory stop costs

*Update:* measured over 2022–2026 with the neighbour method used by the live engine
(time lost against nearby cars that stayed out), the mandatory stop in a 2-hour Le Mans
Cup race costs **168 s under green** (669 stops) and **103 s under the Safety Car**
(19 stops). Under FCY it averages 169 s (8 stops), because most FCYs end before a
160-second stop is over. That is why the live call is a probability based on how long the
caution has already run (see [ACCURACY.md](ACCURACY.md)). The original 2026-only figures
follow.

Every car makes one driver-change stop with a minimum pit-lane time. Measured against
the class's median lap at the same moment and under the same flag (in-lap + out-lap
minus two class laps), a service stop cost:

| Class | Under green | Under Safety Car | Under FCY |
|---|---:|---:|---:|
| LMP3 Pro/Am | **174.7 s** (78 stops) | **105.7 s** (16 stops) | 1 stop only |
| LMP3 | **174.7 s** (146 stops) | **109.2 s** (27 stops) | **152.0 s** (19 stops) |
| GT3 | **182.7 s** (72 stops) | 34.5 s (9 stops, small sample) | 3 stops only |

The median pit-lane time of a service stop was **162 s** in every class: the minimum
stop time dominates the cost. A stop under the Safety Car saved about **65–70 s**, and a
stop under FCY about **20 s**, against the same stop under green.

## 2. The window

The driver-change stops of rounds 1, 2, 4 and 5 cluster in a clear window. Stintwise
infers it robustly (outliers removed): **50:56 to 1:00:37** of race time for LMP3 Pro/Am,
50:23 to 55:45 for GT3. The pit wall uses this window to decide whether a caution is
usable for the mandatory stop.

## 3. Race examples

**Algarve (round 6): 30 seconds.** An FCY came out at 55:02, inside the window. Four of
the eleven LMP3 Pro/Am cars (#71, #66, #98 and #49) had made their stop under green
between 14 and 30 seconds earlier; #34 and #48 stopped under the FCY. #71 still won the
class. The margin between a normal stop and a cheap one was a single lap.
Replayed with rules learned only from earlier races, the pit wall tells #34 "BOX BOX:
stopping under FCY saves ~86 s (84% of similar stops gained time)" at 55:02; the team
boxed at 56:49, still under the FCY.

**Silverstone (round 5): extra stops under the Safety Car.** The Safety Car from 1:08 to
1:34 came after the window. Several LMP3 Pro/Am cars made a second, short service stop
under it, at a cost of 77–113 s against the field instead of about 170 s under green.

**Spa (round 4): everybody at once.** All nine LMP3 Pro/Am cars still running took the
mandatory stop under the FCY that started at 48 min, eight of them between 51:24 and
52:54. When a whole class pits under the same caution there are no clean class laps left
to compare with, so Stintwise reports no loss figure for those stops rather than
guessing.

## 4. What this means on the pit wall

- With rules learned from earlier races, the live engine calls each caution in under a
  second: "BOX BOX: stopping under FCY saves ~86 s (84% of similar stops gained time)",
  or "stay out: window not open", or "stay out: a driver change now leaves our Bronze
  10 min short".
- The net order (positions once every car has made the stops it still owes) shows who is
  really ahead during the stop cycle.
- After the flag, the debrief shows each driver's rank on clean pace in the class, every
  stop against the class median and cautions that came while the stop was still owed.

## Method notes and limits

- Flags are read at each car's line crossing, so a caution's start and end are known to
  within about one lap.
- Drive time is the sum of a driver's lap times; the official figure uses pit-lane
  timing lines and can differ by a few seconds per stint.
- The window and stop counts are inferred from timing, not read from the Sporting
  Regulations. Check them against the current regulations.
