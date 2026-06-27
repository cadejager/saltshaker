from saltshaker.cli import main


def test_cli_writes_output_and_lp(tmp_path, examples_dir):
    out = tmp_path / "out.csv"
    rc = main([str(examples_dir / "example_in.csv"), str(out), "--seed", "0"])
    assert rc == 0
    assert out.exists()
    assert (tmp_path / "out.csv.lp").exists()           # .lp dumped next to output by default
    lines = out.read_text().splitlines()
    assert lines[0] == "Night,Size,Space,Host,Attendees"
    assert len(lines) > 1                                 # at least one dinner row


def test_cli_custom_lp_path(tmp_path, examples_dir):
    out = tmp_path / "out.csv"
    lp = tmp_path / "audit.lp"
    rc = main([str(examples_dir / "example_in.csv"), str(out), "--lp", str(lp)])
    assert rc == 0
    assert lp.exists()
