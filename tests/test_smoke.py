from tests._support import run_solver, mkfam


def test_run_solver_returns_schedule(examples_dir):
    families, schedule = run_solver(examples_dir / "a2_in.csv")
    assert isinstance(schedule, list)
    assert len(schedule) == len(families[0].attend_nights)
    # every dinner is a host -> set-of-attendees mapping that includes the host
    for night in schedule:
        for host, attendees in night.items():
            assert host in attendees


def test_mkfam_defaults():
    f = mkfam("a@x", nights=3)
    assert f.email == "a@x"
    assert f.attend_nights == [True, True, True]
    assert f.host_nights == [False, False, False]
    assert f.nights_count == 3
