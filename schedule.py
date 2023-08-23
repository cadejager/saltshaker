#!/usr/bin/env python3

# This file is part of saltshaker.
#
# saltshaker is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# saltshaker is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with saltshaker. If not,
# see <https://www.gnu.org/licenses/>. 


# This is the scheduler the saltshaer project. It takes an input file as shown in examples/in and
# produces an output file like in examples/out.


import argparse, csv, logging, math, multiprocessing, os, sys, random, time


# The class family is basically just a row from the input file.
#
# The members represent the following
# email: The email (also the identifier) fo the family.
# size: The number of people in the family (that will be attending the dinners)
# space: The number of people the family can host (including themselves)
# host_limits: A soft limit on how many times they would like to host
# allergies: Allergies that families will not go into homes that contain
# allergens: Allergens that a family's home contains if they are hosting
# knows: Who the family knows and should be de prioritized in matching
# repel: Who the family should never share a dinner with
# attend_nights: The nights the family can attend
# host_nights: The nights the family can host
class Family:
    def __init__(self, email, size, space, host_limit, allergies, allergens, knows, repel,
                 attend_nights, host_nights):
        self.email = email
        self.size = size
        self.space = space
        self.host_limit = host_limit
        self.allergies = allergies
        self.allergens = allergens
        self.knows = knows
        self.repel = repel
        self.attend_nights = attend_nights
        self.host_nights = host_nights
    def __repr__(self):
        return "Family(%s,%d,%d,%d,%s,%s,%s,%s)" % (self.email, self.size, self.space, self.host_limit, self.allergies, self.allergens, self.knows, self.repel)
    def __str__(self):
        return "Family: %s" % (self.email)
    def __eq__(self, other):
        if isinstance(other, Family):
            return (self.email == other.email)
        else:
            return False
    def __ne__(self, other):
        return (not self.__eq__(other))
    def __hash__(self):
        return hash(self.email)

# Reads a csv file in and populates a list of families
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
            host_limit = int(row[3])

            # allergies, allergens, knows, and repel are all space seperated lists
            allergies = set(row[4].split())
            allergens = set(row[5].split())
            knows = set(row[6].split())
            repel = set(row[7].split())

            host_nights = [night == 'Can Host' for night in row[8:]]
            attend_nights = [night == 'Can Attend' or night == 'Can Host' for night in row[8:]]
            families.append(Family(email, size, space, host_limit, allergies, allergens, knows,
                                   repel, attend_nights, host_nights))

    return families

# writes the result CSV out
def write_csv(filename, schedule):
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Night', 'Size', 'Space', 'Host', 'Attendees'])
        for night, hosts in enumerate(schedule):
            for host, attendees in hosts.items():
                attendees_email = []
                for a in attendees:
                    attendees_email.append(a.email)
                writer.writerow([
                        night,
                        sum(g.size for g in attendees),
                        host.space,
                        host.email,
                        ', '.join(attendees_email)
                        ])

# writes a summery of the score of the finding
def summery(schedule):

    log = multiprocessing.get_logger()

    host_counts = {}

    meets = {}
    meals = 0

    for hosts in schedule:
        for host, attendees in hosts.items():
            host_counts[host] = host_counts.get(host, 0) + 1
            for family in attendees:
                meals += 1
                if family not in meets:
                    meets[family] = set()
                for a in attendees:
                    meets[family].add(a)

    max_hosts = max(host_counts.values())

    meets_count = 0
    for family in meets:
        meets_count += len(meets[family])

    log.info("meals: " + str(meals))
    log.info("max_hosts: " + str(max_hosts))
    hcstring = "Host Counts: "
    for host in host_counts:
        hcstring += str(host.email) + ": " + str(host_counts[host]) + ", "
    log.info(hcstring)
    log.info("meets_count: " + str(meets_count))

# Calculates a score for the result
def score(schedule):
    score = 0

    # this will be a dictonary keyed by a family and with a value of the number of times they host
    host_counts = {}

    # meets is a dictonary keyed by a family and the values are sets of the families they meet
    meets = {}

    # meals is the number of families that have eaten of the course of the entire series
    meals = 0

    for hosts in schedule:
        for host, attendees in hosts.items():

            # massive negivite score for only two families together
            if len(attendees) < 3:
                score -= 512

            host_counts[host] = host_counts.get(host, 0) + 1
            meals += len(attendees)
            for family in attendees:
                if family not in meets:
                    meets[family] = set(attendees)
                else:
                    meets[family].update(attendees)

    # large score bonus for feeding everyone
    score += 128 * meals
    # medium negitive score for having someone host a bunch of times
    score -= 32 * max(host_counts.values())
    # medium negitive score for hosts which are above their limit expentional as they go beyond it
    #for host in host_counts:
    #    if host_counts[host] > host.host_limit:
    #        score -= 16*(2^(host_counts[host]-host.host_limit))
    # small negitive score for each hosting
    score -= 8 * sum(host_counts.values())
    # small positive score for more meets
    for family in meets:
        score += len(meets[family])
        # small negitive score for familys that know each other meeting
        for match in meets[family]:
            if set(family.knows).intersection(match.knows):
                score -= 1

    return score

# Generates a schedule from the list families. This function gurentees that the repel families
# are not together and that guests are not assigned to a house with their alergies.
# it does not gurentee that all guests are given a host so... make sure that is a priority in
# the cost function
def generate_schedule(families):

    # this will be a dictonary keyed by a family and with a value of the number of times they host
    host_counts = dict.fromkeys(families, 0)

    schedule = [{} for _ in range(len(families[0].attend_nights))]  # Initialize schedule
    nights = list(range(len(families[0].attend_nights)))
    random.shuffle(nights)
    for night in nights:
        assigned = set()  # Keep track of families that have been assigned to a dinner
        random.shuffle(families)  # Shuffle the list of families
        for host in families:

            # check if host can host that night
            if host.host_nights[night] and host not in assigned and host_counts[host] < host.host_limit:

                # Try to find attendees for this host
                for family in families:
                    
                    if family.attend_nights[night] and family != host and family not in assigned:

                        # Calculate remaning capacity of host
                        if host not in schedule[night]:
                            # no entry just subract host's own size from space
                            host_capacity = host.space - host.size
                        else:
                            # see how much is already filled
                            host_capacity = host.space - sum(g.size for g in schedule[night][host])

                        # Check if adding this family would exceed the host's capacity
                        if host_capacity >= family.size:
                            
                            # check if the host has an allergen the famly is allergic to
                            if set(host.allergens).intersection(family.allergies):
                                break

                            # check if host repels family
                            if set(host.repel).intersection(family.repel):
                                break

                            if host not in schedule[night]:
                                # create entry with host at dinner if it doesn't exist
                                schedule[night][host] = {host}
                                # assign the host so they don't doin another dinner
                                assigned.add(host)
                                host_counts[host] += 1
                            else:
                                # check if the family is incompatable with any other members at the
                                # dinner
                                repel = False
                                for guest in schedule[night][host]:
                                    if family.repel.intersection(guest.repel):
                                        repel = True
                                        break
                                if repel:
                                    break

                            # add the new family to the dinner and set them to assigned
                            schedule[night][host].add(family)
                            assigned.add(family)

    # look though the schedule created and move parties around to try to fill small groups
    # full_dinners we can borrow from, fill_dinners need guests
    full_dinners = {}
    fill_dinners = {}
    for night in range(len(schedule)):
        full_dinners[night] = {}

        for host,dinner in schedule[night].items():
            dinner_size = sum(g.size for g in dinner)
            host_capacity = host.space - dinner_size

            if 0 == host_capacity:
                # find the full dinner
                full_dinners[night][host] = dinner

            elif 2 <= host_capacity:
                # find the dinenrs to add guests to
                fill_dinners[(night, host)] = dinner

    # try to fill the low dinners
    while fill_dinners:
        # get the next dinner to fill, pop it off so we don't get stuck in this loop forever
        (night, fill_host) = next(iter(fill_dinners))
        fill_dinner = fill_dinners.pop((night, fill_host))

        fill_dinner_size = sum(g.size for g in fill_dinner)
        fill_host_capacity = fill_host.space - fill_dinner_size

        full_hosts = list(full_dinners[night])
        random.shuffle(full_hosts)
        for full_host in full_hosts:
            full_dinner = full_dinners[night][full_host]
            full_dinner_size = sum(g.size for g in full_dinner)
            dinner_filled = False

            # only borrow from a dinner that is larger than the current dinner
            if fill_dinner_size < full_dinner_size:
                for full_guest in full_dinner:
                    # look for a guest that will get us within 1 of max capacity, and not the host of the other dinner
                    if fill_host_capacity - 1 == full_guest.size and full_guest != full_host:
                        # check if the family is incompatable with any other members at the
                        # dinner
                        repel = False
                        for guest in schedule[night][fill_host]:
                            if full_guest.repel.intersection(guest.repel):
                                repel = True
                                break
                        if repel:
                            break

                        fill_dinner.add(full_guest)
                        full_dinner.remove(full_guest)
                        del full_dinners[night][full_host]

                        # add full_dinner to fill_dinners if the guest removed was greater than 1
                        if 1 < full_guest.size:
                            fill_dinners[(night, full_host)] = full_dinner

                        dinner_filled = True
                        break

            if dinner_filled:
                break

    return schedule

# Orignally I was planning on useing simulating annealing it the generate_schedule function however
# does not support any way to choose where you are jumping so we are using the much simplier run
# for a while and keep the best match option.
def find_schedule(args, families):

    log = multiprocessing.get_logger()

    start_time = time.time()

    current_schedule = generate_schedule(families)
    current_score = score(current_schedule)

    # loop whatever number of times you would like
    # TODO: make this a bit more intellegent, maybe loop till you haven't found a better solution
    #           in 10k runs or something
    j = 0
    k = 0
    while True:
        j += 1
        k += 1

        new_schedule = generate_schedule(families)
        new_score = score(new_schedule)
        if current_score < new_score:
            current_schedule = new_schedule
            current_score = new_score

            # print out progress
            summery(current_schedule)
            log.info("runs: " + str(k))
            log.info("score: " + str(current_score))

        # keep reseting j till we have ran for the specified time
        if 1000 < j:
            if args.time < time.time() - start_time:
                break
            else:
                j = 0


    log.info("runs: " + str(k))

    return current_schedule

# uses find_schedule in a thread
def find_schedule_process(args, families, schedules):
    schedule = find_schedule(args, families)
    schedules.put(schedule)

# counts the number of requested meals
def count_meals(families):
    meals = 0
    for family in families:
        meals += family.attend_nights.count(True)
    return meals

def find_starved_family(families, schedule):

    log = multiprocessing.get_logger()

    starved_count = 0

    for family in families:
        for night in range(len(family.attend_nights)):
            if not family.attend_nights[night]:
                continue
            served = False
            for host in schedule[night]:
                if family in schedule[night][host]:
                    served = True
            if not served:
                log.warning(family.email + " not served night # " + str(night))
                starved_count += 1

    if 0 != starved_count:
        log.warning("%d Family-meals starved" % (starved_count))

def main():
    parser = argparse.ArgumentParser(
            description='Creates a Schedule for Salt shaker dinners'
            )
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("-t", "--time", default=120, type=int, help="The time to run in seconds")
    parser.add_argument("-p", "--processes", type=int)
    parser.add_argument("-l", "--log", dest="logLevel", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="Set the logging level", default='WARNING')
    args = parser.parse_args()

    # setup logger
    log = multiprocessing.log_to_stderr(level=getattr(logging, args.logLevel))

    # figure out number of processes to use
    cpu_count = os.cpu_count()
    if None == cpu_count:
        log.warning('OS not reporting cpu_count')
    if None == args.processes:
        if None == cpu_count:
            log.warning('please specifiy number of processes to use with -p')
            sys.exit(1)
        else:
            args.processes = cpu_count
    if None != cpu_count and cpu_count < args.processes:
        log.warning('%d processes requested, system only reports %d cpus' % (args.processes, cpu_count))

    families = read_csv(args.input)

    schedules = []
    processes = []

    schedule_q = multiprocessing.Queue()

    for i in range(args.processes):
        p = multiprocessing.Process(target=find_schedule_process, args=(args, families, schedule_q,))
        processes.append(p)
        p.start()

    for p in processes:
        schedules.append(schedule_q.get())
        p.join

    # find the best schedule from the threads
    schedule = schedules[0]
    current_score = score(schedule)
    for new_schedule in schedules:
        new_score = score(new_schedule)
        if current_score < new_score:
            schedule = new_schedule
            current_score = new_score

    
    summery(schedule)
         
    log.warning("Total Possible Meals: " + str(count_meals(families)))

    find_starved_family(families, schedule)

    write_csv(args.output, schedule)

if __name__ == "__main__":
    main()
