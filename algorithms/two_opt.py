"""2-opt local search: improve a route by reversing segments.

A 2-opt move picks two positions i < j and reverses the stops between them:
    [a, b, c, d, e]  --reverse(1..3)-->  [a, d, c, b, e]
Geometrically this removes two "crossing" legs and reconnects the tour.

We keep a move only if it makes the closed tour strictly shorter (and, when an
`is_feasible` check is given, the new order still satisfies every opening-hours
window). Repeat until a full pass finds no improving move.

Directed costs: our travel times are directed (A->B may differ from B->A).
Reversing a segment also reverses the legs *inside* it, so the usual
"compare only the 4 changed edges" shortcut is only valid for symmetric costs.
We therefore recompute the whole tour cost for every candidate (O(k)).

Complexity: O(k^2) candidate moves per pass x O(k) to cost each = O(k^3) per pass.
It always terminates because every accepted move strictly lowers the cost.
The result is a LOCAL optimum, not a guaranteed global one.
"""

from algorithms.tour import tour_cost


def two_opt(start, route, dist, is_feasible=None):
    """Return (improved_route, cost).

    start:       hotel / start node (fixed; never moved)
    route:       list of stops to improve
    dist:        distance table dist[a][b]
    is_feasible: optional function(route) -> bool; moves that make the route
                 infeasible are rejected.
    """
    best = list(route)
    best_cost = tour_cost(start, best, dist)
    n = len(best)

    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 1, n):
                candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cost = tour_cost(start, candidate, dist)
                if cost < best_cost - 1e-9:
                    if is_feasible is not None and not is_feasible(candidate):
                        continue
                    best, best_cost = candidate, cost
                    improved = True
    return best, best_cost
