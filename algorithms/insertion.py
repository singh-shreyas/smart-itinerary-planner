"""Window-first route construction: deadline order + cheapest feasible insertion.

Plain "earliest closing time first" fails when some stop opens late (for
example an evening-only aarti): it would be visited before places that close
later and the day would overrun. So we use the closing-time order only as the
order in which stops are *considered* (the activity-selection rule), and put
each one at the position in the route that

    1. keeps every opening window and the end of the day satisfied, and
    2. adds the least travel time.

This is the standard insertion heuristic for routing with time windows.
Complexity: k stops x (k + 1) positions x O(k) feasibility check = O(k^3).
"""

from algorithms.activity_selection import earliest_deadline_order
from algorithms.tour import tour_cost


def deadline_insertion_route(start, stops, closing_time, dist, is_feasible):
    """Return (route, unplaced): unplaced lists stops that fit at no position."""
    route, unplaced = [], []
    for stop in earliest_deadline_order(stops, closing_time):
        best_cost, best_route = None, None
        for position in range(len(route) + 1):
            candidate = route[:position] + [stop] + route[position:]
            if not is_feasible(candidate):
                continue
            cost = tour_cost(start, candidate, dist)
            if best_cost is None or cost < best_cost:
                best_cost, best_route = cost, candidate
        if best_route is None:
            unplaced.append(stop)
        else:
            route = best_route
    return route, unplaced
