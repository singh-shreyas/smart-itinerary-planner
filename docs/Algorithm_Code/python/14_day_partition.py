# Spreading places over days: target counts, deviation, construct + improve
# (as in algorithms/day_partition.py). In the project, feasible(day, stops) routes the day
# with the real scheduler; this demo uses a stand-in: a day holds at most 300 minutes.
MINUTES = {"A": 120, "B": 90, "C": 150, "D": 60, "E": 90}
DAYS = (1, 2, 3)


def target_counts(n, days):
    base, extra = divmod(n, days)
    counts = [base] * days
    if base == 0:
        for k in range(extra):
            counts[0 if extra == 1 else round(k * (days - 1) / (extra - 1))] += 1
    else:
        for k in range(extra):
            counts[k] += 1
    return counts


def deviation(counts, target):
    return sum(abs(x - y) for x, y in zip(sorted(counts, reverse=True), sorted(target, reverse=True)))


def stops(mapping, day):
    return tuple(p for p, d in mapping.items() if d == day)


def feasible(day, day_stops):
    return sum(MINUTES[p] for p in day_stops) <= 300


def cost(mapping):          # "Evenly Distributed": unplaced first, then deviation from the target
    counts = [len(stops(mapping, d)) for d in DAYS]
    unplaced = sum(1 for d in mapping.values() if d is None)
    return (unplaced, deviation(counts, target_counts(len(mapping), len(DAYS))))


def construct(places):
    mapping = {p: None for p in places}
    for p in sorted(places, key=lambda p: (-MINUTES[p], p)):        # hardest (longest) first
        best = None
        for d in DAYS:
            if feasible(d, stops(mapping, d) + (p,)):
                option = dict(mapping, **{p: d})
                if best is None or cost(option) < best[0]:
                    best = (cost(option), option)
        if best:
            mapping = best[1]
    return mapping


def improve(mapping):
    places, current = sorted(mapping), dict(mapping)
    while True:
        moves = [{p: d} for p in places for d in DAYS if d != current[p]]
        moves += [{p: current[q], q: current[p]} for i, p in enumerate(places) for q in places[i + 1:]
                  if current[p] != current[q] and None not in (current[p], current[q])]
        for change in moves:                                   # first improvement
            option = dict(current, **change)
            if all(feasible(d, stops(option, d)) for d in DAYS) and cost(option) < cost(current):
                current = option
                break
        else:
            return current                                     # local optimum


if __name__ == "__main__":
    print("target for 5 places, 3 days:", target_counts(5, 3))
    plan = improve(construct(list(MINUTES)))
    for d in DAYS:
        print("day", d, stops(plan, d))
    print("cost:", cost(plan))
