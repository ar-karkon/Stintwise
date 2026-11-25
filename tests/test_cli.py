import json

from stintwise.cli import main


def test_plan_cli(capsys):
    assert main(["plan", "--preset", "example-lmp2-4h"]) == 0
    assert "Laps at the flag" in capsys.readouterr().out
    assert main(["plan", "--preset", "example-lmp2-4h", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stints"]


def test_sample_and_analyze(tmp_path, capsys):
    path = tmp_path / "s.csv"
    assert main(["sample", str(path)]) == 0
    capsys.readouterr()
    assert main(["analyze", str(path), "--class", "LMGT3"]) == 0
    out = capsys.readouterr().out
    assert "Cautions" in out and "Median time lost" in out
    assert main(["analyze", str(path), "--car", "50"]) == 0
    assert "Drive time" in capsys.readouterr().out


def test_caution_cli(capsys):
    args = ["caution", "--green-lap", "138", "--caution-lap", "220", "--pit-transit", "58",
            "--track-equivalent", "24", "--stationary", "28", "--laps-into-stint", "17",
            "--max-stint-laps", "22", "--race-left", "7000", "--caution-left", "240"]
    assert main(args) == 0
    assert "PIT NOW" in capsys.readouterr().out


def test_live_cli(tmp_path, capsys):
    from stintwise.cli import parse_clock

    assert parse_clock("55m") == 3300 and parse_clock("1h05m") == 3900
    assert parse_clock("1:00:30") == 3630 and parse_clock("120") == 120
    path = tmp_path / "s.csv"
    main(["sample", str(path)])
    rules = tmp_path / "rules.json"
    capsys.readouterr()
    assert main(["fit", str(path), "--class", "LMGT3"]) == 0
    rules.write_text(capsys.readouterr().out)
    assert main(["replay", str(path), "--at", "2h", "--class", "LMGT3", "--car", "50",
                 "--rules", str(rules)]) == 0
    assert "Net gap" in capsys.readouterr().out
    assert main(["events", str(path), "--class", "LMGT3", "--car", "50", "--only-focus"]) == 0
    assert "deployed" in capsys.readouterr().out
    assert main(["debrief", str(path), "--car", "50"]) == 0
    assert "# Debrief" in capsys.readouterr().out
