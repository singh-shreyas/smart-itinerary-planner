"""Assigning places to days: the search behind the three itinerary modes.

The problem: N chosen places and D trip days. Each day's stops must form a
feasible day (a route that respects opening hours, meals, access time and the
day window); among feasible assignments we want the one that is best for the
mode's objective. That is a bin-packing / vehicle-routing hybrid, NP-hard, so
we use a standard construct-and-improve heuristic:

    1. CONSTRUCT  place the hardest places first (fewest days they could go on,
                  then the longest), each on the day where it costs least
                  ("best fit"); a second start packs each into the first day it
                  fits ("first fit decreasing", the classic bin-packing rule).
    2. IMPROVE    local search: move one place to another day (relocate) or
                  exchange two places between days (swap); keep any change that
                  lowers the mode's cost; stop when no move helps.

Nothing here knows about maps or clocks. The caller passes
    feasible(day, stops) -> bool          is this set of stops a valid day?
    cost(assignment)     -> comparable    the mode's objective (smaller is better)
and both are memoised by the caller, so each distinct day is routed only once.

Deterministic: places and days are always visited in a fixed order and ties
keep the earlier option, so the same input gives the same assignment.

Also here: the quotient-and-remainder target used by "Evenly Distributed"
and the deviation from it.
"""

from itertools import combinations


def target_counts(n, days):
    """Ideal stops per day: floor(n / D) each, the n % D extra stops one each on the first days.

    n=4, D=3 -> [2, 1, 1];  n=6, D=5 -> [2, 1, 1, 1, 1];  n=8, D=4 -> [2, 2, 2, 2].
    When n < D the extras are spread over the trip (n=3, D=5 -> [1, 0, 1, 0, 1]),
    so the places land on different, evenly spaced days.
    """
    if days <= 0:
        return []
    base, extra = divmod(n, days)
    counts = [base] * days
    if base == 0:
        for k in range(extra):                     # evenly spaced positions, first and last day included
            index = 0 if extra == 1 else round(k * (days - 1) / (extra - 1))
            counts[index] += 1
    else:
        for k in range(extra):
            counts[k] += 1
    return counts


def deviation(counts, target):
    """How far a distribution is from the target, ignoring which day is which:
    sum |a_i - b_i| over both lists sorted from largest to smallest. 0 = the ideal shape."""
    a, b = sorted(counts, reverse=True), sorted(target, reverse=True)
    return sum(abs(x - y) for x, y in zip(a, b))


def day_subsets(days, k):
    """All choices of k days out of `days`, earliest days first (lexicographic)."""
    return list(combinations(days, k))


class Assignment:
    """places -> day (or None = could not be placed). Small helper with copy-on-write moves."""

    def __init__(self, days, mapping):
        self.days = tuple(days)
        self.mapping = dict(mapping)

    def stops(self, day):
        return tuple(p for p, d in self.mapping.items() if d == day)

    def unplaced(self):
        return tuple(p for p, d in self.mapping.items() if d is None)

    def counts(self):
        return [len(self.stops(d)) for d in self.days]

    def moved(self, changes):
        m = dict(self.mapping)
        m.update(changes)
        return Assignment(self.days, m)

    def key(self):
        return tuple(sorted(self.mapping.items(), key=lambda kv: kv[0]))


def construct(places, days, feasible, cost, first_fit=False, order_key=None):
    """Greedy start. Places in `order_key` order; each goes to the cheapest feasible day
    (or, with first_fit, the earliest feasible day); a place that fits nowhere stays unplaced."""
    current = Assignment(days, {p: None for p in places})
    for p in sorted(places, key=order_key) if order_key else places:
        best = None
        for d in days:
            stops = current.stops(d) + (p,)
            if not feasible(d, stops):
                continue
            option = current.moved({p: d})
            if first_fit:
                best = option
                break
            c = cost(option)
            if best is None or c < best[0]:
                best = (c, option)
        if best is not None:
            current = best if first_fit else best[1]
    return current


def improve(start, feasible, cost, max_passes=40):
    """Relocate and swap moves until no move lowers the cost (best improvement per pass)."""
    current, current_cost = start, cost(start)
    places = sorted(current.mapping)
    for _ in range(max_passes):
        best = None
        # relocate: one place to another day (an unplaced place may be placed)
        for p in places:
            here = current.mapping[p]
            for d in current.days:
                if d == here or not feasible(d, current.stops(d) + (p,)):
                    continue
                if here is not None and not feasible(here, tuple(q for q in current.stops(here) if q != p)):
                    continue
                option = current.moved({p: d})
                c = cost(option)
                if c < current_cost and (best is None or c < best[0]):
                    best = (c, option)
        # swap: exchange two places on different days
        for i, p in enumerate(places):
            for q in places[i + 1:]:
                dp, dq = current.mapping[p], current.mapping[q]
                if dp == dq or dp is None or dq is None:
                    continue
                stops_p = tuple(x for x in current.stops(dp) if x != p) + (q,)
                stops_q = tuple(x for x in current.stops(dq) if x != q) + (p,)
                if not (feasible(dp, stops_p) and feasible(dq, stops_q)):
                    continue
                option = current.moved({p: dq, q: dp})
                c = cost(option)
                if c < current_cost and (best is None or c < best[0]):
                    best = (c, option)
        if best is None:
            break
        current_cost, current = best
    return current, current_cost


def search(places, days, feasible, cost, seeds=(), order_key=None):
    """Best assignment of `places` to `days` found from several starts. Returns (assignment, cost).

    seeds: extra starting assignments ({place: day}), e.g. the plan the day-by-day
    pipeline already found; places or days a seed does not cover start unplaced.
    """
    starts = [construct(places, days, feasible, cost, first_fit=False, order_key=order_key),
              construct(places, days, feasible, cost, first_fit=True, order_key=order_key)]
    for seed in seeds:
        mapping = {p: (seed.get(p) if seed.get(p) in days else None) for p in places}
        candidate = Assignment(days, mapping)
        if all(feasible(d, candidate.stops(d)) for d in days if candidate.stops(d)):
            starts.append(candidate)
    best, seen = None, set()
    for start in starts:
        if start.key() in seen:
            continue
        seen.add(start.key())
        result, c = improve(start, feasible, cost)
        if best is None or c < best[1]:
            best = (result, c)
    return best
