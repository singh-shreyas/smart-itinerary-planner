"""Route construction: Nearest Neighbour, 2-opt, feasible insertion and Held-Karp."""

import itertools
import math
import random

from algorithms.held_karp import held_karp
from algorithms.insertion import deadline_insertion_route
from algorithms.nearest_neighbor import nearest_neighbor_route
from algorithms.tour import tour_cost
from algorithms.two_opt import two_opt


def euclid_table(points, asym=0.0, rng=None):
    dist = {}
    for i, (x1, y1) in enumerate(points):
        dist[i] = {}
        for j, (x2, y2) in enumerate(points):
            extra = (1 + asym * rng.random()) if rng else 1
            dist[i][j] = 0 if i == j else math.hypot(x1 - x2, y1 - y2) * extra
    return dist


def random_instance(seed, k, asym=0.1):
    rng = random.Random(seed)
    points = [(5, 5)] + [(rng.uniform(0, 10), rng.uniform(0, 10)) for _ in range(k)]
    return 0, list(range(1, k + 1)), euclid_table(points, asym, rng)


def brute_force_tour(start, stops, dist):
    return min(tour_cost(start, list(p), dist) for p in itertools.permutations(stops))


def test_tour_cost_counts_every_leg_once():
    dist = {0: {1: 2, 2: 9}, 1: {0: 3, 2: 4}, 2: {0: 5, 1: 1}}
    assert tour_cost(0, [1, 2], dist) == 2 + 4 + 5
    assert tour_cost(0, [], dist) == 0
    assert tour_cost(0, [1, 2], dist, closed=False) == 6


def test_nearest_neighbour_on_a_line_and_visits_each_stop_once():
    points = [(0, 0), (3, 0), (1, 0), (2, 0), (4, 0)]
    dist = euclid_table(points)
    assert nearest_neighbor_route(0, [1, 2, 3, 4], dist) == [2, 3, 1, 4]
    for seed in range(30):
        start, stops, dist = random_instance(seed, 8)
        route = nearest_neighbor_route(start, stops, dist)
        assert sorted(route) == stops


def test_nearest_neighbour_breaks_ties_by_id():
    dist = {0: {0: 0, 5: 1, 3: 1}, 5: {0: 1, 5: 0, 3: 2}, 3: {0: 1, 5: 2, 3: 0}}
    assert nearest_neighbor_route(0, [5, 3], dist)[0] == 3


def test_two_opt_never_increases_cost_and_keeps_all_stops():
    for seed in range(60):
        start, stops, dist = random_instance(seed, 9)
        nn = nearest_neighbor_route(start, stops, dist)
        route, cost = two_opt(start, nn, dist)
        assert sorted(route) == stops
        assert cost <= tour_cost(start, nn, dist) + 1e-9
        assert math.isclose(cost, tour_cost(start, route, dist))


def test_two_opt_removes_a_crossing():
    # Square corners visited in a "bow-tie" order cross; 2-opt untangles them.
    points = [(0, 0), (0, 10), (10, 0), (10, 10)]          # start at (0,0)
    dist = euclid_table(points)
    crossed = [3, 1, 2]                                      # (0,0)->(10,10)->(0,10)->(10,0)->back: crosses
    route, cost = two_opt(0, crossed, dist)
    assert math.isclose(cost, 40.0)                          # the perimeter
    assert cost < tour_cost(0, crossed, dist)


def test_two_opt_respects_a_feasibility_rule():
    start, stops, dist = random_instance(4, 7)

    def stop_7_before_stop_1(route):
        return route.index(7) < route.index(1)

    initial = sorted(stops, key=lambda s: (s != 7, s))       # feasible: 7 is first
    route, cost = two_opt(start, initial, dist, is_feasible=stop_7_before_stop_1)
    assert stop_7_before_stop_1(route)
    assert cost <= tour_cost(start, initial, dist)


def test_held_karp_matches_brute_force_and_bounds_heuristics():
    for seed in range(40):
        k = 1 + seed % 7
        start, stops, dist = random_instance(seed, k, asym=0.3)
        optimum, order = held_karp(start, stops, dist)
        assert sorted(order) == stops
        assert math.isclose(optimum, brute_force_tour(start, stops, dist))
        assert math.isclose(optimum, tour_cost(start, order, dist))
        nn = nearest_neighbor_route(start, stops, dist)
        assert tour_cost(start, nn, dist) >= optimum - 1e-9
        assert two_opt(start, nn, dist)[1] >= optimum - 1e-9
    assert held_karp(0, [], {0: {0: 0}}) == (0, [])


def test_deadline_insertion_keeps_routes_feasible():
    # Stop 3 may only be last (an "evening-only" place); deadlines would otherwise put it first.
    points = [(0, 0), (1, 0), (2, 0), (3, 0)]
    dist = euclid_table(points)
    closing = {1: 900, 2: 950, 3: 600}                        # stop 3 "closes" earliest

    def evening_last(route):
        return 3 not in route or route[-1] == 3

    route, unplaced = deadline_insertion_route(0, [1, 2, 3], closing, dist, evening_last)
    assert unplaced == [] and route[-1] == 3 and sorted(route) == [1, 2, 3]

    route, unplaced = deadline_insertion_route(0, [1, 2], closing, dist, lambda r: len(r) < 2)
    assert len(route) == 1 and len(unplaced) == 1
