"""Seeded scaling benchmarks for the algorithms -> results/benchmarks.json and .csv.

    python scripts/benchmark.py              # default seeds and sizes (~1 minute)
    python scripts/benchmark.py --quick      # fewer seeds, for a fast check

Synthetic instances are generated with random.Random(seed), so the QUALITY
numbers (scores, travel, gaps) are identical on every run; timings vary a little
by machine and load. Each timing is the median of several runs after a warm-up,
and the file records the machine, Python version and settings that produced it.
The comparison page charts this file; nothing on that page is typed in by hand.
"""

import argparse
import csv
import json
import math
import os
import platform
import random
import statistics
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import networkx                                                     # noqa: E402

from algorithms.dijkstra import all_pairs_shortest_paths             # noqa: E402
from algorithms.dynamic_programming import dp_select                 # noqa: E402
from algorithms.graph import build_graph                             # noqa: E402
from algorithms.greedy import greedy_select                          # noqa: E402
from algorithms.held_karp import held_karp                           # noqa: E402
from algorithms.knapsack_types import Item                           # noqa: E402
from algorithms.nearest_neighbor import nearest_neighbor_route       # noqa: E402
from algorithms.tour import tour_cost                                # noqa: E402
from algorithms.two_opt import two_opt                               # noqa: E402
from services.crosscheck import compare_all_pairs, to_networkx       # noqa: E402
from services.timing import median_ms                                # noqa: E402

RESULTS = os.path.join(ROOT, "results")


# ------------------------------------------------------------------ instance generators

def knapsack_instance(rng, n):
    """n attractions: score 30-100, 30-180 min visit + 5-30 min travel allowance, fees like real sites."""
    items = []
    for i in range(n):
        minutes = rng.randint(30, 180) + rng.randint(5, 30)
        fee = rng.choice([0, 0, 0, 20, 25, 40, 50, 100, 250, 500])
        items.append(Item(i, rng.randint(30, 100), math.ceil(minutes / 10), math.ceil(fee / 10)))
    return items, 54, 100          # 540 minutes in 10-min units; Rs 1000 in Rs 10 units


def route_instance(rng, k):
    """Start + k stops in a 15 x 15 km square; directed times (km at 25 km/h, up to +10% one way)."""
    points = [(7.5, 7.5)] + [(rng.uniform(0, 15), rng.uniform(0, 15)) for _ in range(k)]
    dist = {}
    for i, (x1, y1) in enumerate(points):
        dist[i] = {}
        for j, (x2, y2) in enumerate(points):
            km = math.hypot(x1 - x2, y1 - y2)
            dist[i][j] = 0.0 if i == j else km / 25 * 60 * (1 + 0.1 * rng.random())
    return 0, list(range(1, k + 1)), dist


def sparse_graph(rng, v, k=5):
    points = [(rng.uniform(0, 30), rng.uniform(0, 30)) for _ in range(v)]
    edges = {}                                     # (u, v) -> minutes; one directed edge per pair
    for i, (x1, y1) in enumerate(points):
        nearest = sorted((j for j in range(v) if j != i), key=lambda j: math.hypot(x1 - points[j][0], y1 - points[j][1]))[:k]
        for j in nearest:
            km = math.hypot(x1 - points[j][0], y1 - points[j][1])
            for a, b in ((i, j), (j, i)):
                edges.setdefault((a, b), round(km / 25 * 60 + rng.uniform(0, 2), 3))
    return build_graph(range(v), sorted((a, b, w) for (a, b), w in edges.items()))


# ------------------------------------------------------------------ experiments

def bench_selection(sizes, seeds, repeats):
    rows = []
    for n in sizes:
        greedy_ms, dp_ms, ratios, dp_better = [], [], [], 0
        for seed in seeds:
            items, T, M = knapsack_instance(random.Random(seed * 1000 + n), n)
            g, d = greedy_select(items, T, M), dp_select(items, T, M)
            assert d.score >= g.score, "DP must never score below Greedy on the same instance"
            ratios.append(g.score / d.score if d.score else 1.0)
            dp_better += d.score > g.score
            greedy_ms.append(median_ms(lambda: greedy_select(items, T, M), repeats))
            dp_ms.append(median_ms(lambda: dp_select(items, T, M), repeats))
        rows.append({"n": n, "instances": len(seeds), "greedy_ms": statistics.median(greedy_ms),
                     "dp_ms": statistics.median(dp_ms), "dp_cells": (n + 1) * 55 * 101,
                     "greedy_pct_of_dp": round(100 * statistics.mean(ratios), 2),
                     "dp_strictly_better_pct": round(100 * dp_better / len(seeds), 1)})
        print(f"selection n={n:3}: greedy {rows[-1]['greedy_ms']:.3f} ms, dp {rows[-1]['dp_ms']:.2f} ms, "
              f"greedy reaches {rows[-1]['greedy_pct_of_dp']}% of DP")
    return rows


def bench_routing(sizes, seeds, repeats):
    rows = []
    for k in sizes:
        acc = {"nn_ms": [], "two_opt_ms": [], "held_karp_ms": [], "nn_gap": [], "two_opt_gap": []}
        for seed in seeds:
            start, stops, dist = route_instance(random.Random(seed * 1000 + k), k)
            nn = nearest_neighbor_route(start, stops, dist)
            nn_cost = tour_cost(start, nn, dist)
            _, opt_cost = two_opt(start, nn, dist)
            hk_cost, _ = held_karp(start, stops, dist)
            assert opt_cost <= nn_cost + 1e-9 and hk_cost <= opt_cost + 1e-9
            acc["nn_gap"].append(100 * (nn_cost - hk_cost) / hk_cost)
            acc["two_opt_gap"].append(100 * (opt_cost - hk_cost) / hk_cost)
            acc["nn_ms"].append(median_ms(lambda: nearest_neighbor_route(start, stops, dist), repeats))
            acc["two_opt_ms"].append(median_ms(lambda: two_opt(start, nn, dist), repeats))
            acc["held_karp_ms"].append(median_ms(lambda: held_karp(start, stops, dist), repeats))
        row = {"k": k, "instances": len(seeds)}
        for key in ("nn_ms", "two_opt_ms", "held_karp_ms"):
            row[key] = statistics.median(acc[key])
        row["nn_gap_pct"] = round(statistics.mean(acc["nn_gap"]), 2)
        row["two_opt_gap_pct"] = round(statistics.mean(acc["two_opt_gap"]), 2)
        row["two_opt_optimal_pct"] = round(100 * sum(g < 1e-6 for g in acc["two_opt_gap"]) / len(seeds), 1)
        rows.append(row)
        print(f"routing k={k:2}: NN gap {row['nn_gap_pct']}%, 2-opt gap {row['two_opt_gap_pct']}%, "
              f"Held-Karp {row['held_karp_ms']:.2f} ms")
    return rows


def bench_dijkstra(sizes, seeds, repeats):
    rows = []
    for v in sizes:
        ours, theirs, mismatches, pairs = [], [], 0, 0
        for seed in seeds:
            graph = sparse_graph(random.Random(seed * 1000 + v), v)
            check = compare_all_pairs(graph)
            mismatches += check["mismatches"]
            pairs += check["pairs"]
            g = to_networkx(graph)
            ours.append(median_ms(lambda: all_pairs_shortest_paths(graph), repeats))
            theirs.append(median_ms(lambda: dict(networkx.all_pairs_dijkstra_path_length(g)), repeats))
        rows.append({"v": v, "instances": len(seeds), "ours_ms": statistics.median(ours),
                     "networkx_ms": statistics.median(theirs), "pairs_checked": pairs, "mismatches": mismatches})
        print(f"dijkstra V={v:3}: {pairs} pairs checked, {mismatches} mismatches, ours {rows[-1]['ours_ms']:.1f} ms")
    return rows


def bench_real_scenarios(quick=False):
    """DP vs Greedy on whole itineraries for a grid of real-data trips (all four cities).

    Unlike the knapsack comparison (where DP >= Greedy is guaranteed), the final
    itinerary has no guarantee: routing, repair and multi-day effects come after
    selection. This sweep measures how often each strategy actually ends up ahead.
    """
    import itertools
    import tempfile
    from datetime import date, timedelta

    from config import Config
    from database.db import connect
    from database.seed_data import seed_database
    from services.city_data import load_city
    from services.itinerary_generator import plan_trip
    from services.models import TripRequest

    path = os.path.join(tempfile.mkdtemp(), "bench.db")
    seed_database(path, Config.DATA_DIR)
    conn = connect(path)
    cities = {slug: load_city(conn, slug, Config.TRAFFIC_FACTOR) for slug in ("agra", "delhi", "jaipur", "varanasi")}
    conn.close()

    grid = itertools.product(sorted(cities), range(3 if quick else 7), [1, 2, 3], [None, 300, 600], [False, True],
                             [(), ("history",), ("spirituality",)], ["balanced", "relaxed"])
    dp_higher = greedy_higher = equal = 0
    gaps, best = [], None
    for slug, offset, days, budget, transport, interests, pace in grid:
        if budget is None and transport:
            continue
        city = cities[slug]
        base = dict(city=slug, start_date=date(2026, 11, 2) + timedelta(days=offset), days=days, day_start=540,
                    day_end=1140, budget=budget, include_transport=transport, interests=interests, pace=pace,
                    start=city.start_points[0].slug)
        dp = plan_trip(city, TripRequest(strategy="dp", **base), Config.TRANSPORT_COST_PER_KM)
        greedy = plan_trip(city, TripRequest(strategy="greedy", **base), Config.TRANSPORT_COST_PER_KM)
        assert not dp.violations and not greedy.violations
        if dp.score > greedy.score:
            dp_higher += 1
        elif dp.score < greedy.score:
            greedy_higher += 1
        else:
            equal += 1
        if greedy.score:
            gaps.append(100 * (dp.score - greedy.score) / greedy.score)
    total = dp_higher + greedy_higher + equal
    summary = {"scenarios": total, "dp_higher": dp_higher, "greedy_higher": greedy_higher, "equal": equal,
               "mean_dp_gain_pct": round(statistics.mean(gaps), 2),
               "grid": "4 cities x start dates Mon-Sun x 1-3 days x budget {none, 300, 600} (+/- transport) "
                       "x interests {none, history, spirituality} x pace {balanced, relaxed}; 09:00-19:00"}
    print(f"real scenarios: {total} trips, DP higher {dp_higher}, Greedy higher {greedy_higher}, equal {equal}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="fewer seeds and repeats")
    args = parser.parse_args()
    seeds = list(range(1, 4 if args.quick else 11))
    repeats = 3 if args.quick else 5

    result = {
        "meta": {
            "generated": datetime.now().isoformat(timespec="seconds"),
            "python": platform.python_version(), "networkx": networkx.__version__,
            "platform": platform.platform(), "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "seeds": seeds, "repeats": repeats, "timing": "median of repeats after one warm-up (perf_counter_ns)",
            "selection_instance": "time cap 540 min (10-min units), budget Rs 1000 (Rs 10 units)",
            "routing_instance": "start + k stops in a 15 x 15 km square, 25 km/h, up to 10% directional asymmetry",
            "graph_instance": "V points in a 30 x 30 km square, 5 nearest neighbours each, both directions",
        },
        "selection": bench_selection([10, 20, 30, 40, 60], seeds, repeats),
        "routing": bench_routing(list(range(4, 11)), seeds, repeats),
        "dijkstra": bench_dijkstra([25, 50, 100, 200], seeds, repeats),
        "real_scenarios": bench_real_scenarios(quick=args.quick),
    }
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "benchmarks.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    for name in ("selection", "routing", "dijkstra"):          # tables only; real_scenarios is a summary
        with open(os.path.join(RESULTS, f"benchmarks_{name}.csv"), "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(result[name][0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(result[name])
    print("wrote results/benchmarks.json and results/benchmarks_*.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
