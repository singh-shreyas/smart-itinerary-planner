"""Graph construction and Dijkstra's shortest paths."""

import math
import random

import pytest

from algorithms.dijkstra import all_pairs_shortest_paths, dijkstra, reconstruct_path
from algorithms.graph import build_graph, edge_count, reverse_graph
from services.crosscheck import compare_all_pairs, crosscheck_city


def test_adjacency_list_shape():
    graph = build_graph(["A", "B", "C"], [("A", "B", 4), ("B", "C", 1)])
    assert graph == {"A": [("B", 4)], "B": [("C", 1)], "C": []}
    assert edge_count(graph) == 2
    assert reverse_graph(graph) == {"A": [], "B": [("A", 4)], "C": [("B", 1)]}


@pytest.mark.parametrize("edge", [("A", "Z", 1), ("A", "A", 1), ("A", "B", -1)])
def test_bad_edges_are_rejected(edge):
    with pytest.raises(ValueError):
        build_graph(["A", "B"], [edge])


def test_shortest_path_composes_local_links():
    # A->C directly costs 30, but A->B->C costs 10 + 15 = 25.
    graph = build_graph("ABCD", [("A", "B", 10), ("B", "C", 15), ("A", "C", 30), ("C", "D", 5)])
    dist, prev = dijkstra(graph, "A")
    assert dist == {"A": 0, "B": 10, "C": 25, "D": 30}
    path = reconstruct_path(prev, "A", "D")
    assert path == ["A", "B", "C", "D"]
    legs = {("A", "B"): 10, ("B", "C"): 15, ("C", "D"): 5}
    assert sum(legs[(a, b)] for a, b in zip(path, path[1:])) == dist["D"]


def test_unreachable_and_directed_edges():
    graph = build_graph("ABC", [("A", "B", 3)])          # one-way link, C is isolated
    dist, prev = dijkstra(graph, "B")
    assert dist["A"] == math.inf                          # no B->A link
    assert dist["C"] == math.inf
    assert reconstruct_path(prev, "B", "C") == []
    assert dijkstra(graph, "A")[0]["B"] == 3


def test_unknown_source():
    with pytest.raises(KeyError):
        dijkstra(build_graph("A", []), "Z")


def test_parallel_edges_use_the_cheapest():
    graph = build_graph("AB", [("A", "B", 9), ("A", "B", 4)])
    assert dijkstra(graph, "A")[0]["B"] == 4
    assert compare_all_pairs(graph)["mismatches"] == 0


def test_matches_networkx_on_random_graphs():
    for seed in range(60):
        rng = random.Random(seed)
        n = rng.randint(2, 25)
        edges = [(u, v, round(rng.uniform(0.5, 40), 2))
                 for u in range(n) for v in range(n) if u != v and rng.random() < 0.15]
        graph = build_graph(range(n), edges)
        result = compare_all_pairs(graph)
        assert result["pairs"] == n * n
        assert result["mismatches"] == 0, f"seed {seed}"


def test_fixture_city_travel_table(tiny_city):
    by = tiny_city.place
    hotel, garden, aarti, island = by("hotel").id, by("garden").id, by("aarti").id, by("island").id
    # No direct hotel-garden link: hotel->museum->garden = 15 + 10 = 25 beats hotel->temple->garden = 30.
    assert tiny_city.dist[hotel][garden] == 25
    assert [tiny_city.places[p].slug for p in tiny_city.path(hotel, garden)] == ["hotel", "museum", "garden"]
    assert tiny_city.km[hotel][garden] == pytest.approx(8.0)
    assert tiny_city.dist[hotel][aarti] == 30
    assert tiny_city.dist[hotel][island] == math.inf
    leg = tiny_city.leg(hotel, garden)
    assert leg.minutes == 25 and leg.via == ["Museum"]


def test_real_cities_agree_with_networkx(real_cities):
    for city in real_cities.values():
        result = crosscheck_city(city, repeats=1)
        assert result["mismatches"] == 0, city.name
        assert result["pairs"] == city.vertex_count ** 2


def test_all_pairs_returns_a_table_per_source():
    graph = build_graph("AB", [("A", "B", 2), ("B", "A", 3)])
    dist, prev = all_pairs_shortest_paths(graph)
    assert dist == {"A": {"A": 0, "B": 2}, "B": {"A": 3, "B": 0}}
    assert prev["A"]["B"] == "A"
