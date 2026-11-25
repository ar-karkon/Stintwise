import pytest

from stintwise.timing import load_csv, parse_duration, parse_text

HEADER = " NUMBER; DRIVER_NUMBER; LAP_NUMBER; LAP_TIME; CROSSING_FINISH_LINE_IN_PIT; ELAPSED;"
HEADER += " DRIVER_NAME; PIT_TIME; CLASS; TEAM; MANUFACTURER; FLAG_AT_FL"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("1:47.123", 107.123), ("47.5", 47.5), ("1:02:03.456", 3723.456), ("1:47,5", 107.5),
     ("", None), (None, None), ("abc", None)],
)
def test_parse_duration(text, seconds):
    result = parse_duration(text)
    assert result == pytest.approx(seconds) if seconds is not None else result is None


def test_parse_al_kamel_rows_with_padded_headers():
    text = "﻿" + HEADER + "\n" + "\n".join([
        "7;1;1;2:00.000;;2:00.000;A ONE;;HYPERCAR;Team X;Make;GF",
        "7;1;2;2:10.000;B;4:10.000;A ONE;;HYPERCAR;Team X;Make;FCY",
        "7;2;3;2:40.000;;6:50.000;B TWO;1:05.000;HYPERCAR;Team X;Make;GF",
    ])
    race = parse_text(text, "test")
    assert race.cars == ["7"]
    laps = race.car_laps("7")
    assert [lap.lap for lap in laps] == [1, 2, 3]
    assert laps[1].in_pit and not laps[0].in_pit
    assert laps[1].flag == "FCY" and not laps[1].green
    assert laps[2].pit_time == pytest.approx(65.0)
    assert race.car_info("7") == {"car": "7", "class": "HYPERCAR", "team": "Team X",
                                  "manufacturer": "Make"}
    assert race.duration == pytest.approx(410.0)


def test_elapsed_is_accumulated_when_missing():
    text = "NUMBER;LAP_NUMBER;LAP_TIME\n1;1;1:00.0\n1;2;1:01.0\n"
    race = parse_text(text)
    assert [lap.elapsed for lap in race.car_laps("1")] == [60.0, 121.0]


def test_missing_columns_are_reported():
    with pytest.raises(ValueError, match="LAP_TIME"):
        parse_text("NUMBER;LAP_NUMBER\n1;1\n")


def test_load_csv_handles_cp1252(tmp_path):
    path = tmp_path / "race.csv"
    path.write_bytes("NUMBER;LAP_NUMBER;LAP_TIME;DRIVER_NAME\n1;1;1:00.0;Jos\xe9\n".encode("cp1252"))
    assert load_csv(path).car_laps("1")[0].driver == "José"
