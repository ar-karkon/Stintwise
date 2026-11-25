# Getting real timing data

Stintwise reads the lap-by-lap **Analysis CSV** published after each session
by Al Kamel Systems, the timing provider of FIA WEC, ELMS, Asian Le Mans
Series and IMSA.

1. Open the championship results site (for WEC: `fiawec.alkamelsystems.com`).
   The site may ask for a browser check: download the files by hand.
2. Choose season → event → **Race** session.
3. Download the lap **Analysis** CSV for the full race (in multi-hour races
   pick the file for the final hour, which contains every lap of the race).
4. Copy it into `data/races/`, or upload it from the **Race analysis** tab.

```bash
stintwise analyze data/races/wec-2025-spa-race.csv --class LMGT3
stintwise analyze data/races/wec-2025-spa-race.csv --car 92
```

## Columns used

| Column | Used for |
|---|---|
| `NUMBER`, `LAP_NUMBER`, `LAP_TIME` | required |
| `ELAPSED` | race clock (otherwise lap times are summed) |
| `CROSSING_FINISH_LINE_IN_PIT` = `B` | lap ends in the pit lane → pit stop |
| `PIT_TIME` | pit lane time, read from the out-lap |
| `DRIVER_NUMBER`, `DRIVER_NAME` | stints, driver changes, drive time |
| `FLAG_AT_FL` | green / FCY / SC periods and stop types |
| `CLASS`, `TEAM`, `MANUFACTURER` | grouping |

Headers are matched case-insensitively with whitespace stripped. Files in
UTF-8, UTF-8 with BOM or Windows-1252 are accepted.

## Rights

Timing data belongs to the championship and its timing provider. The
repository never commits real timing files (`data/races/` is git-ignored);
publish only your own derived analysis.
