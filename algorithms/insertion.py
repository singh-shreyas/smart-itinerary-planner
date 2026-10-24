"""Cheapest feasible insertion, and the window-first route built from it.

Cheapest feasible insertion (one stop):
    try the new stop at every position of the current route and keep the
    position that (1) keeps every opening window, meal and the end of the day
    satisfied and (2) adds the least travel time. Ties go to the earlier
    position, so the result is deterministic.

Window-first route construction:
    Plain "earliest closing time first" fails when some stop opens late (for
    example an evening-only aarti): it would be visited before places that close
    later and the day would overrun. So we use the closing-time order only as the
    order in which stops are *considered* (the activity-selection rule), and
    insert each one at its cheapest feasible position.

The same insertion step is also the planner's "fill" step: after a day's route
is fixed, leftover candidates are tried one by one, so extra hours in a longer
day are actually used when something still fits.

Complexity: one insertion tries k + 1 positions x an O(k) feasibility check = O(k^2);
building a whole route of k stops is O(k^3).
"""

from algorithms.activity_selection import earliest_deadline_order
from algorithms.tour import tour_cost


def cheapest_feasible_insertion(start, route, stop, dist, is_feasible):
    """Return the new route with `stop` at its cheapest feasible position, or None if it fits nowhere."""
    best_cost, best_route = None, None
    for position in range(len(route) + 1):
        candidate = route[:position] + [stop] + route[position:]
        if not is_feasible(candidate):
            continue
        cost = tour_cost(start, candidate, dist)
        if best_cost is None or cost < best_cost:
            best_cost, best_route = cost, candidate
    return best_route


def deadline_insertion_route(start, stops, closing_time, dist, is_feasible):
    """Return (route, unplaced): unplaced lists stops that fit at no position."""
    route, unplaced = [], []
    for stop in earliest_deadline_order(stops, closing_time):
        inserted = cheapest_feasible_insertion(start, route, stop, dist, is_feasible)
        if inserted is None:
            unplaced.append(stop)
        else:
            route = inserted
    return route, unplaced
