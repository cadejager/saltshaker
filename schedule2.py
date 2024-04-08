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
                 attend_nights, host_nights, nights_count):
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
        self.nights_count = nights_count
    def __repr__(self):
        return "Family(%s,%d,%d,%d,%s,%s,%s,%s,%d)" % (self.email, self.size, self.space, self.host_limit, self.allergies, self.allergens, self.knows, self.repel, self.nights_count)
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
            host_limit = int(row[3]) if row[3] else None

            # allergies, allergens, knows, and repel are all space seperated lists
            allergies = frozenset(row[4].split())
            allergens = frozenset(row[5].split())
            knows = frozenset(row[6].split())
            repel = frozenset(row[7].split())

            host_nights = [night == 'Can Host' for night in row[8:]]
            attend_nights = [night == 'Can Attend' or night == 'Can Host' for night in row[8:]]

            nights_count = sum(attend_nights)

            families.append(Family(email, size, space, host_limit, allergies, allergens, knows,
                                   repel, attend_nights, host_nights, nights_count))

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
def score_host(schedule):
    score = 0

    # this will be a dictonary keyed by a family and with a value of the number of times they host
    host_counts = {}

    for night in range(len(schedule)):
        for host in schedule[night]:
            host_counts[host] = host_counts.get(host, 0) + 1
            # penlize repeat dinners
            if 0 < night and host in schedule[night-1]:
                score -= 16


    # the ratio of meals each host does
    host_ratios = {}
    for host in host_counts:
        host_ratios[host] = host_counts[host]/host.nights_count

    host_ratio_average = sum(host_ratios.values())/len(host_ratios)

    # penlized difference from ratiots
    for ratio in host_ratios.values():
        score -= 48**abs(ratio-host_ratio_average)

    # TODO: the Laura option

    return score

# Calculates a score for the result
def score_guest(schedule):
    score = 0

    # meets is a dictonary keyed by a family and the values are sets of the families they meet
    meets = {}

    # meals is the number of families that have eaten of the course of the entire series
    meals = 0

    for hosts in schedule:
        for host, attendees in hosts.items():
            meals += len(attendees)
            for family in attendees:
                if family not in meets:
                    meets[family] = set(attendees)
                else:
                    meets[family].update(attendees)

    # large score bonus for feeding everyone
    score += 128 * meals

    # small positive score for more meets
    for family in meets:
        score += len(meets[family])
        # small negitive score for familys that know each other meeting
        for match in meets[family]:
            if set(family.knows).intersection(match.knows):
                score -= 1

    return score

# This can be a scheduler that maybe generates an empy schedule only
# ? Should it have some kind of margen % or people ?
def generate_host_schedule(families):
    # this will be a dictonary keyed by a family and with a value of the number of times they host
    host_counts = dict.fromkeys(families, 0)

    schedule = [{} for _ in range(len(families[0].attend_nights))]  # Initialize schedule
    nights = list(range(len(families[0].attend_nights)))
    random.shuffle(nights)

    for night in nights:
        # loop through allergies and assign hosts that don't have those allergies
        # get a list of allergies
        allergies_tonight = {}
        hosts_tonight = {}
        for family in families:
            if family.attend_nights[night]:
                allergies_tonight[family.allergies] = allergies_tonight.get(family.allergies, 0) + family.size
                if family.host_nights[night] and (None == family.host_limit or host_counts[family] < family.host_limit):
                    hosts_tonight[family] = family.space - family.size

        # can't suffle a dictionay so need a list list for hosts tonight
        host_list_tonight = list(hosts_tonight.keys())
        random.shuffle(host_list_tonight)
        
        seats_before = sum(allergies_tonight.values())

        # find hosts for each allergy
        # TODO: sort allgesy by most restrictive first (allergies with the fewest hosts that can accomidate them)
        for allergy in sorted(allergies_tonight.keys(), key=lambda l: (len(l), l), reverse=True):
            for host in host_list_tonight:
                if (host in hosts_tonight) and (not allergy.intersection(host.allergens)):
                    if host not in schedule[night]:
                        allergies_tonight[host.allergies] -= host.size # Remove the host size from their allergy
                        schedule[night][host] = {host} # add the host to the schedule
                        host_counts[host] += 1

                    # recaculate required space for allergy as well as space requried for allergy set
                    host_space_remaining = hosts_tonight[host]
                    hosts_tonight[host] -= allergies_tonight[allergy]
                    allergies_tonight[allergy] -= host_space_remaining

                    # remove host if they are full, skip to next allergy if allrgy is full
                    if 0 >= hosts_tonight[host]:
                        del hosts_tonight[host]
                    if 0 >= allergies_tonight[allergy]:
                        break
            
    return schedule


# Orignally I was planning on useing simulating annealing it the generate_schedule function however
# does not support any way to choose where you are jumping so we are using the much simplier run
# for a while and keep the best match option.
def find_schedule(args, families):

    log = multiprocessing.get_logger()

    start_time = time.time()

    current_schedule = generate_host_schedule(families)
    current_score = score_host(current_schedule)

    # loop whatever number of times you would like
    # TODO: make this a bit more intellegent, maybe loop till you haven't found a better solution
    #           in 10k runs or something
    j = 0
    k = 0
    while True:
        j += 1
        k += 1

        new_schedule = generate_host_schedule(families)
        new_score = score_host(new_schedule)
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


    log.warning("runs: " + str(k))

    return current_schedule

# uses find_schedule in a thread
def find_schedule_process(args, families, schedules):
    schedule = find_schedule(args, families)
    schedules.put(schedule)

# fills an exisitng schedule with new guests
def fill_schedule(families, host_schedule):
    schedule = [{} for _ in range(len(families[0].attend_nights))]  # Initialize schedule
    nights = list(range(len(families[0].attend_nights)))

    for night in nights:
        # copy the host night schedule over
        #schedule[night] = host_schedule[night].copy()
        for host in host_schedule[night]:
            schedule[night][host] = {host}


        # Find all the families that need a dinner this night and count how many seats are needed
        families_tonight = []
        hosts_tonight = {}
        assigned = set()  # Keep track of families that have been assigned to a dinner
        for family in families:
            if family.attend_nights[night]:
                if family in schedule[night]:
                    hosts_tonight[family] = family.space-family.size # track host remaining seats
                else:
                    families_tonight.append(family)

        random.shuffle(families_tonight)  # Shuffle the list of families
        
        for guest in families_tonight:
            # generate a host_list that we can shuffle
            host_list = list(hosts_tonight.keys())
            random.shuffle(host_list)
            for host in host_list:

                # check if the guest is avaiable and not allergic to the host
                if      guest.allergies.intersection(host.allergens) or \
                        hosts_tonight[host] < guest.size:
                    continue

                # check for repels
                repel = False
                for other in schedule[night][host]:
                    if guest.repel.intersection(other.repel):
                        repel = True
                        break
                if repel:
                    continue

                schedule[night][host].add(guest)
                hosts_tonight[host] -= guest.size
                if(0 >= hosts_tonight[host]):
                    del hosts_tonight[host]

                break

    return schedule

# this takes an existing host schedule and iterates on it to find the best mixing of guests
def optimize_schedule(args, families, host_schedule, schedules):
    log = multiprocessing.get_logger()

    start_time = time.time()

    current_schedule = fill_schedule(families, host_schedule)
    current_score = score_guest(current_schedule)

    # loop whatever number of times you would like
    # TODO: make this a bit more intellegent, maybe loop till you haven't found a better solution
    #           in 10k runs or something
    j = 0
    k = 0
    while True:
        j += 1
        k += 1

        new_schedule = fill_schedule(families, host_schedule)
        new_score = score_guest(new_schedule)
        if current_score < new_score:
            current_schedule = new_schedule
            current_score = new_score

            # print out progress
            summery(current_schedule)
            log.info("Optimize runs: " + str(k))
            log.info("Optimize score: " + str(current_score))

        # keep reseting j till we have ran for the specified time
        if 1000 < j:
            if args.time < time.time() - start_time:
                break
            else:
                j = 0

    log.warning("Optimize runs: " + str(k))

    return current_schedule

# Optimizes a given schedule
def optimize_schedule_process(args, families, host_schedule, schedules):
    schedule = optimize_schedule(args, families, host_schedule, schedules)
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
    current_score = score_host(schedule)
    for new_schedule in schedules:
        new_score = score_host(new_schedule)
        if current_score < new_score:
            schedule = new_schedule
            current_score = new_score


    # TODO: Run a second pass to swap guests around for optimal matching
    processes.clear()
    for i in range(args.processes):
        p = multiprocessing.Process(target=optimize_schedule_process, args=(args, families, schedule, schedule_q,))
        processes.append(p)
        p.start()

    schedules.clear()
    for p in processes:
        schedules.append(schedule_q.get())
        p.join

    # find the best schedule from the threads
    schedule = schedules[0]
    current_score = score_guest(schedule)
    for new_schedule in schedules:
        new_score = score_guest(new_schedule)
        if current_score < new_score:
            schedule = new_schedule
            current_score = new_score
    
    summery(schedule)
         
    log.warning("Total Possible Meals: " + str(count_meals(families)))

    find_starved_family(families, schedule)

    write_csv(args.output, schedule)

if __name__ == "__main__":
    main()
