#!/usr/bin/python3

import argparse
import csv
import math
import random

class Family:
    def __init__(self, email, size, space, allergies, allergens, repel, attend_nights, host_nights):
        self.email = email
        self.size = size
        self.space = space
        self.allergies = allergies
        self.allergens = allergens
        self.repel = repel
        self.attend_nights = attend_nights
        self.host_nights = host_nights

def read_csv(filename):
    families = []
    with open(filename, 'r') as file:
        #reader = csv.DictReader(csvfile)

        reader = csv.reader(file)
        next(reader)  # Skip header
        for row in reader:
            email = row[0]
            size = int(row[1])
            space = int(row[2])
            allergies = row[3].split()
            allergens = row[4].split()
            repel = row[5].split()
            host_nights = [night == 'Can Host' for night in row[6:]]  # get host nights
            attend_nights = [night == 'Can Attend' or night == 'Can Host' for night in row[6:]]  # Get Attend Nights
            families.append(Family(email, size, space, allergies, allergens, repel, attend_nights, host_nights))

    return families

def write_csv(filename, schedule):
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Night', 'Host', 'Attendees'])
        for night, hosts in enumerate(schedule):
            for host, attendees in hosts.items():
                writer.writerow([night, host, ', '.join(attendees)])

def cost(schedule):
    host_counts = {}  # Number of times each family hosts
    unique_meets = {}  # Number of unique families each family meets
    for night, hosts in enumerate(schedule):
        for host, attendees in hosts.items():
            host_counts[host] = host_counts.get(host, 0) + 1
            unique_meets[host] = len(set(attendees))
    max_hosts = max(host_counts.values())
    cost = 0
    for family in host_counts:
        cost += 0.7 * host_counts[family]
        cost += 0.3 / unique_meets[family]
    cost += 1000 * max_hosts  # Add a large penalty based on the maximum number of times any family hosts
    return cost

def generate_schedule(families):
    nights = [{} for _ in range(len(families[0].attend_nights))]  # Initialize schedule
    for night in range(len(families[0].attend_nights)):
        assigned = set()  # Keep track of families that have been assigned to a dinner
        unassigned = set()  # Keep track of families that haven't been assigned to a dinner
        random.shuffle(families)  # Shuffle the list of families
        for host in families:
            # check if host can host that night
            if host.host_nights[night] and host.email not in assigned:
                # Try to find attendees for this host
                for family in families:
                    
                    if family.attend_nights[night] and family != host and family.email not in assigned:
                        if host.email not in nights[night]:
                            host_capacity = host.space - host.size  # Subtract host's own attendees from capacity
                        else:
                            host_capacity = host.space - sum(g.size for g in families if g.email in nights[night][host.email])
                        # Check if adding this family would exceed the host's capacity
                        if host_capacity >= family.size:
                            if host.email not in nights[night]:
                                nights[night][host.email] = [host.email]  # Host attends its own dinner

                            # check if the host has an allergen the famly is allergic to
                            if set(host.allergens).intersection(family.allergies):
                                break

                            # check if the host is incompatable with any other members at the dinner
                            repel = False
                            for guest_email in nights[night][host.email]:
                                guest = {}
                                for g in families:
                                    if guest_email == g.email:
                                        guest = g
                                        break
                                
                                if set(family.repel).intersection(guest.repel):
                                    repel = True
                            if repel:
                                break

                            nights[night][host.email].append(family.email)
                            assigned.add(family.email)
                            assigned.add(host.email)

    return nights

# TDOD: Fix as it runs 11001 times currently
def simulated_annealing(families):
    T = 1.0
    T_min = 0.00001
    alpha = 0.9
    current_schedule = generate_schedule(families)
    j = 1
    while T > T_min:
        i = 1
        while i <= 100:
            new_schedule = generate_schedule(families)
            cost_diff = cost(new_schedule) - cost(current_schedule)
            if cost_diff < 0 or random.uniform(0, 1) < math.exp(-cost_diff / T):
                current_schedule = new_schedule
            i += 1
            j += 1
        T = T*alpha
    return current_schedule

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    args = parser.parse_args()

    families = read_csv(args.input)
    schedule = simulated_annealing(families)
    write_csv('output.csv', schedule)

if __name__ == "__main__":
    main()
