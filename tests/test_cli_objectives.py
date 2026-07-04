# tests/test_cli_objectives.py
from saltshaker.cli import main


def test_cli_runs_objectives_and_writes_outputs(tmp_path, examples_dir):
    out = tmp_path / "out.csv"
    rc = main([str(examples_dir / "example_in.csv"), str(out), "--seed", "0", "--time-limit", "5"])
    assert rc == 0
    assert out.exists()
    assert (tmp_path / "out.csv.lp").exists()
    lines = out.read_text().splitlines()
    assert lines[0] == "Night,Size,Space,Host,Attendees"
    assert len(lines) > 1
