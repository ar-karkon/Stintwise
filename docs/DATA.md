# Getting real timing data

Stintwise reads the lap-by-lap **Analysis CSV** published after each session
by Al Kamel Systems, the timing provider of FIA WEC, ELMS, Asian Le Mans
Series and IMSA.

1. Open the championship results site: `lemanscup.alkamelsystems.com` (Michelin Le Mans
   Cup), `elms.alkamelsystems.com` (ELMS) or `fiawec.alkamelsystems.com` (WEC; this one
   may ask for a browser check, so download by hand).
2. Choose season → event → **Race** session.
3. Download `23_Analysis_Race.CSV` (in multi-hour races, the file in the last hour's
   folder contains every lap of the race).
4. Copy it into `data/races/`, or add it with **+ Add timing CSV** on the pit wall. On the
   pit wall the file is read in your browser and never uploaded.

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
| `PIT_TIME` | pit-lane time; Al Kamel writes it on the out-lap |
| `DRIVER_NUMBER`, `DRIVER_NAME` | stints, driver changes, drive time |
| `FLAG_AT_FL` | green (`GF`), FCY, Safety Car (`SF`), finish (`FF`), red (`RF`) |
| `CLASS`, `TEAM`, `MANUFACTURER` | grouping |

Headers are matched case-insensitively with whitespace stripped. Files in
UTF-8, UTF-8 with BOM or Windows-1252 are accepted.

## Rights

Timing data belongs to the championship and its timing provider. The
repository never commits real timing files (`data/races/` is git-ignored);
publish only your own derived analysis.
