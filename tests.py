import unittest

from main import read_csv, simulated_annealing


class TestDinnerScheduler(unittest.TestCase):
    def test_all_groups_attend(self):
        groups = read_csv('input-3.csv')
        schedule = simulated_annealing(groups)
        for night, hosts in enumerate(schedule):
            for group in groups:
                if group.nights[night]:
                    self.assertTrue(any(group.email in attendees for attendees in hosts.values()),
                                    f"Group {group.email} wanted to attend on night {night} but did not.")

    def test_no_group_hosts_too_often(self):
        groups = read_csv('intput-3.csv')
        schedule = simulated_annealing(groups)
        host_counts = {}
        for night, hosts in enumerate(schedule):
            for host in hosts.keys():
                host_counts[host] = host_counts.get(host, 0) + 1
        max_hosts = max(host_counts.values())
        min_hosts = min(host_counts.values())
        self.assertLessEqual(max_hosts - min_hosts, 1,
                             f"The difference between the maximum and minimum number of times a group hosts is {max_hosts - min_hosts}, which is more than 1.")

    def test_no_group_hosts_more_than_capacity(self):
        groups = read_csv('intput-3.csv')
        schedule = simulated_annealing(groups)
        for night, hosts in enumerate(schedule):
            for host, attendees in hosts.items():
                host_group = next(group for group in groups if group.email == host)
                total_attendees = sum(group.attendees for group in groups if group.email in attendees)
                self.assertLessEqual(total_attendees, host_group.can_host,
                                     f"Host {host} has a capacity of {host_group.can_host} but is hosting {total_attendees} on night {night}.")

if __name__ == "__main__":
    unittest.main()
