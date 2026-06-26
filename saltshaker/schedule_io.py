"""Reconstruct an in-memory schedule from saltshaker's output CSV.

Used by the validator CLI to audit arbitrary / hand-edited output files. The
input CSV is parsed with schedule.read_csv to recover family attributes; the
output CSV supplies the per-night host->attendees assignment and the host
capacity (Space column), so an audit is self-contained.
"""
import csv
import sys

from schedule import read_csv


class OutputCsvError(Exception):
    pass


def load_output_csv(input_csv, output_csv):
    families = read_csv(input_csv, sys.maxsize)  # huge cap => no clamping
    by_email = {f.email: f for f in families}
    nights = len(families[0].attend_nights) if families else 0

    schedule = [{} for _ in range(nights)]
    warnings = []

    with open(output_csv, newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # skip header
        for row in reader:
            try:
                night = int(row[0])
                space = int(row[2])
                host_email = row[3]
                attendee_emails = [e.strip() for e in row[4].split(",") if e.strip()]
            except (IndexError, ValueError) as exc:
                raise OutputCsvError("malformed row %r: %s" % (row, exc))

            if night < 0 or night >= nights:
                raise OutputCsvError(
                    "row night %d out of range 0..%d" % (night, nights - 1))
            if host_email not in by_email:
                raise OutputCsvError("unknown host email: %s" % host_email)
            host = by_email[host_email]

            if host in schedule[night]:
                raise OutputCsvError(
                    "duplicate dinner for host %s on night %d"
                    % (host_email, night))

            attendees = set()
            for email in attendee_emails:
                if email not in by_email:
                    raise OutputCsvError("unknown attendee email: %s" % email)
                attendees.add(by_email[email])
            if host not in attendees:
                warnings.append(
                    "host %s missing from own attendee list (night %d)"
                    % (host_email, night))
                attendees.add(host)
            host.space = space  # trust the output CSV's recorded capacity
            schedule[night][host] = attendees

    return families, schedule, warnings
