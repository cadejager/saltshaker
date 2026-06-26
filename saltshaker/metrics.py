"""Clean quality metrics for saltshaker schedules (Stage-1 spec M1-M9).

These measure real-world quality and deliberately do NOT reproduce the scoring
bugs in schedule.py: no self-meetings, each unordered pair counted once, empty
seats accounted in persons.
"""
from dataclasses import dataclass, asdict
from itertools import combinations


@dataclass
class Metrics:
    meals: int
    dinners: int
    unfed_count: int
    unfed: list
    host_counts: dict
    host_balance: dict | None
    new_meetings: int
    repeat_meetings: int
    total_empty_seats: int
    empty_seats: list
    back_to_back_host_incidents: int

    def to_dict(self):
        return asdict(self)


def measure(families, schedule):
    nights = len(schedule)
    fam_by_email = {f.email: f for f in families}

    meals = 0
    dinners = 0
    empty_seats = []
    host_counts = {}
    seated_by_night = [set() for _ in range(nights)]
    pair_nights = {}  # (email_lo, email_hi) -> set of nights co-seated

    for night, night_dinners in enumerate(schedule):
        for host, attendees in night_dinners.items():
            dinners += 1
            host_counts[host.email] = host_counts.get(host.email, 0) + 1
            empty_seats.append(host.space - sum(a.size for a in attendees))
            for a in attendees:
                meals += 1
                seated_by_night[night].add(a.email)
            ordered = sorted(attendees, key=lambda f: f.email)
            for a, b in combinations(ordered, 2):
                pair_nights.setdefault((a.email, b.email), set()).add(night)

    # Meetings: distinct unordered pairs whose knows sets are disjoint.
    new_meetings = 0
    repeat_meetings = 0
    for (e1, e2), ns in pair_nights.items():
        if not (fam_by_email[e1].knows & fam_by_email[e2].knows):
            new_meetings += 1
            if len(ns) > 1:
                repeat_meetings += 1

    # Unfed: available on a night but seated nowhere.
    unfed = []
    for f in families:
        for night in range(nights):
            if f.attend_nights[night] and f.email not in seated_by_night[night]:
                unfed.append([f.email, night])

    # Host balance over flexible hosts that actually hosted.
    ratios = {
        f.email: host_counts[f.email] / f.nights_count
        for f in families
        if f.host_target is None and f.nights_count and f.email in host_counts
    }
    if ratios:
        average = sum(ratios.values()) / len(ratios)
        host_balance = {
            "average": average,
            "max_deviation": max(abs(r - average) for r in ratios.values()),
            "ratios": ratios,
        }
    else:
        host_balance = None

    # Back-to-back hosting incidents (per host-night, matching the penalty shape).
    back_to_back = 0
    for night in range(1, nights):
        prev = set(schedule[night - 1].keys())
        for host in schedule[night]:
            if host in prev:
                back_to_back += 1

    return Metrics(
        meals=meals,
        dinners=dinners,
        unfed_count=len(unfed),
        unfed=unfed,
        host_counts=host_counts,
        host_balance=host_balance,
        new_meetings=new_meetings,
        repeat_meetings=repeat_meetings,
        total_empty_seats=sum(empty_seats),
        empty_seats=empty_seats,
        back_to_back_host_incidents=back_to_back,
    )
