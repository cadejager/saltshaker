"""Hard-constraint checker for saltshaker schedules (Stage-1 spec H1-H8).

Pure and solver-independent: operates on a families list and an in-memory
schedule (list indexed by night; each entry a dict mapping a host Family to the
set of attendee Families, including the host). Returns a list of Violation; an
empty list means the schedule obeys every hard rule.
"""
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class Violation:
    rule: str          # "H1".."H8"
    night: int         # 0-based; -1 for whole-schedule rules (H6)
    emails: tuple      # families involved, by email
    message: str


def validate(families, schedule):
    violations = []

    # H6 is cross-night: tally host counts across the whole schedule first.
    host_counts = {}
    for night_dinners in schedule:
        for host in night_dinners:
            host_counts[host] = host_counts.get(host, 0) + 1
    for host, count in host_counts.items():
        if host.host_target is not None and count > host.host_target:
            violations.append(Violation(
                "H6", -1, (host.email,),
                "%s hosts %d times, exceeds host_target %d"
                % (host.email, count, host.host_target)))

    for night, night_dinners in enumerate(schedule):
        # H7: a family appears in at most one home per night.
        appearances = {}
        for attendees in night_dinners.values():
            for a in attendees:
                appearances[a.email] = appearances.get(a.email, 0) + 1
        for email, n in appearances.items():
            if n > 1:
                violations.append(Violation(
                    "H7", night, (email,),
                    "%s appears in %d homes on night %d" % (email, n, night)))

        for host, attendees in night_dinners.items():
            # H8: the host must attend their own home.
            if host not in attendees:
                violations.append(Violation(
                    "H8", night, (host.email,),
                    "host %s is not in their own home on night %d"
                    % (host.email, night)))

            # H4: host may only host on a Can-Host night.
            if not host.host_nights[night]:
                violations.append(Violation(
                    "H4", night, (host.email,),
                    "%s hosts on night %d but cannot host then"
                    % (host.email, night)))

            # H3: seated people must not exceed the host's capacity (persons).
            seated = sum(a.size for a in attendees)
            if seated > host.space:
                violations.append(Violation(
                    "H3", night, (host.email,),
                    "%s seats %d people, capacity %d on night %d"
                    % (host.email, seated, host.space, night)))

            for a in attendees:
                # H5: every attendee must be available that night.
                if not a.attend_nights[night]:
                    violations.append(Violation(
                        "H5", night, (a.email,),
                        "%s attends night %d but is unavailable"
                        % (a.email, night)))
                # H1: guests (not the host) must not be allergic to the home.
                if a != host and (a.allergies & host.allergens):
                    violations.append(Violation(
                        "H1", night, (a.email, host.email),
                        "%s is allergic to %s's home on night %d"
                        % (a.email, host.email, night)))

            # H2: no co-seated pair (host included) shares a repel token.
            ordered = sorted(attendees, key=lambda f: f.email)
            for a, b in combinations(ordered, 2):
                if a.repel & b.repel:
                    violations.append(Violation(
                        "H2", night, (a.email, b.email),
                        "%s and %s repel but are co-seated on night %d"
                        % (a.email, b.email, night)))

    return violations
