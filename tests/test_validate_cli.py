# tests/test_validate_cli.py
from saltshaker.validate_cli import main

INPUT = (
    "email,size,space,ht,al,ag,kn,rp,n1\n"
    "h@x,1,8,,,,,,Can Host\n"
    "g@x,2,8,,,,,,Can Attend\n"
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_clean_schedule_exits_zero(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, g@x"\n')
    assert main([inp, out]) == 0


def test_capacity_violation_exits_one(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,2,h@x,"h@x, g@x"\n')  # 3 people, Space=2 -> H3
    assert main([inp, out]) == 1


def test_malformed_exits_two(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,nobody@x,"nobody@x"\n')  # unknown host
    assert main([inp, out]) == 2


def test_malformed_row_exits_two(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 'X,3,8,h@x,"h@x, g@x"\n')
    assert main([inp, out]) == 2


def test_metrics_flag_prints_json(tmp_path, capsys):
    import json
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, g@x"\n')
    main([inp, out, "--metrics"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["meals"] == 2
