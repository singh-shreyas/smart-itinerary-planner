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
                  exchange two places between days (swap); take the first change
                  (in a fixed order) that lowers the mode's cost and look again;
                  stop when no move helps.

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


MAX_DAY_SUBSETS = 40


def day_subsets(days, k):
    """Choices of k days out of `days`, earliest first.

    For short trips this is every combination (5 days, k = 2: 10 choices). For long trips
    the number of combinations explodes (14 days, k = 7: 3432), so only a fixed, small family
    is tried: every block of k consecutive days, plus k days spread evenly over the trip.
    Days differ only by weekday (opening hours), so these cover the useful patterns.
    """
    days = list(days)
    n = len(days)
    if k <= 0 or k > n:
        return []
    total = 1
    for i in range(k):
        total = total * (n - i) // (i + 1)
    if total <= MAX_DAY_SUBSETS:
        return list(combinations(days, k))
    picks = [tuple(days[s:s + k]) for s in range(n - k + 1)]
    spread = tuple(days[round(i * (n - 1) / (k - 1))] for i in range(k)) if k > 1 else (days[0],)
    if len(set(spread)) == k:
        picks.append(spread)
    return list(dict.fromkeys(picks))


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


def _moves(current, places):
    """Every neighbour of the current assignment, in a fixed order: relocations, then swaps."""
    for p in places:                                          # relocate one place to another day
        for d in current.days:
            if d != current.mapping[p]:
                yield {p: d}
    for i, p in enumerate(places):                            # swap two places on different days
        for q in places[i + 1:]:
            dp, dq = current.mapping[p], current.mapping[q]
            if dp != dq and dp is not None and dq is not None:
                yield {p: dq, q: dp}


def improve(start, feasible, cost, max_moves=400, stop=None):
    """Local search with first improvement: scan the neighbours in a fixed order and take the first
    one that lowers the cost, then scan again; stop when none does (a local optimum), after
    max_moves accepted moves, or when stop() says the effort budget is used up."""
    current, current_cost = start, cost(start)
    places = sorted(current.mapping)
    for _ in range(max_moves):
        improved = False
        for change in _moves(current, places):
            if stop is not None and stop():
                return current, current_cost
            touched = {current.mapping[p] for p in change} | set(change.values())
            option = current.moved(change)
            if not all(feasible(d, option.stops(d)) for d in touched if d is not None and option.stops(d)):
                continue
            c = cost(option)
            if c < current_cost:
                current, current_cost, improved = option, c, True
                break
        if not improved:
            break
    return current, current_cost


def search(places, days, feasible, cost, seeds=(), order_key=None, stop=None):
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
        result, c = improve(start, feasible, cost, stop=stop)
        if best is None or c < best[1]:
            best = (result, c)
    return best
