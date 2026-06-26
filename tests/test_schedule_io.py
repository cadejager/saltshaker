# tests/test_schedule_io.py
import pytest
from saltshaker.schedule_io import load_output_csv, OutputCsvError

INPUT = (
    "email,size,space,ht,al,ag,kn,rp,n1\n"
    "h@x,1,8,,,,,,Can Host\n"
    "g@x,2,8,,,,,,Can Attend\n"
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_loads_basic_schedule(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, g@x"\n')
    families, schedule, warnings = load_output_csv(inp, out)
    assert warnings == []
    assert len(schedule) == 1
    [(host, attendees)] = schedule[0].items()
    assert host.email == "h@x"
    assert {a.email for a in attendees} == {"h@x", "g@x"}


def test_host_capacity_comes_from_output_space(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,5,h@x,"h@x, g@x"\n')  # Space=5 differs from input 8
    _families, schedule, _ = load_output_csv(inp, out)
    [(host, _att)] = schedule[0].items()
    assert host.space == 5


def test_unknown_attendee_raises(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, ghost@x"\n')
    with pytest.raises(OutputCsvError):
        load_output_csv(inp, out)


def test_host_missing_from_attendees_warns_and_is_added(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,2,8,h@x,"g@x"\n')  # host omitted
    _families, schedule, warnings = load_output_csv(inp, out)
    [(host, attendees)] = schedule[0].items()
    assert host in attendees
    assert any("missing from own attendee" in w for w in warnings)
