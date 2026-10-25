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
    """n attractions: score 30-100, 30-180 min visit + 5-30 min travel allowance."""
    items = []
    for i in range(n):
        minutes = rng.randint(30, 180) + rng.randint(5, 30)
        items.append(Item(i, rng.randint(30, 100), math.ceil(minutes / 10)))
    return items, 54               # 540 minutes in 10-min units


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
            items, T = knapsack_instance(random.Random(seed * 1000 + n), n)
            g, d = greedy_select(items, T), dp_select(items, T)
            assert d.score >= g.score, "DP must never score below Greedy on the same instance"
            ratios.append(g.score / d.score if d.score else 1.0)
            dp_better += d.score > g.score
            greedy_ms.append(median_ms(lambda: greedy_select(items, T), repeats))
            dp_ms.append(median_ms(lambda: dp_select(items, T), repeats))
        rows.append({"n": n, "instances": len(seeds), "greedy_ms": statistics.median(greedy_ms),
                     "dp_ms": statistics.median(dp_ms), "dp_cells": (n + 1) * 55,
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
    """DP vs Greedy vs Max visits on whole itineraries for a grid of real-data trips.

    Unlike the knapsack comparison (where DP >= Greedy in value and Max visits >= both in
    count are guaranteed), the final itinerary has no guarantee: routing, meals, repair,
    the fill step and multi-day effects come after selection. This sweep measures how often
    each strategy actually ends up ahead. Cities: the 12 highest-ranked "ready" destinations
    (deterministic order by Top-50 rank), with the planner's default lunch break.
    """
    import itertools
    import tempfile
    from datetime import date, timedelta

    from config import Config
    from database import queries
    from database.db import connect
    from database.seed_data import seed_database
    from services.city_data import load_city
    from services.itinerary_generator import plan_trip
    from services.models import MealSetting, TripRequest

    path = os.path.join(tempfile.mkdtemp(), "bench.db")
    seed_database(path, Config.DATA_DIR)
    conn = connect(path)
    cities = {}
    for row in queries.list_cities(conn):                      # Top-50 rank order
        city = load_city(conn, row["slug"], Config.TRAFFIC_FACTOR)
        if city.readiness()["status"] == "ready":
            cities[row["slug"]] = city
        if len(cities) == (4 if quick else 12):
            break
    conn.close()

    lunch = MealSetting("lunch", 12 * 60, 14 * 60 + 30, 45)
    grid = itertools.product(cities, range(2 if quick else 3), [1, 2, 3], ["balanced", "relaxed"],
                             [(), ("history",), ("spirituality",)])
    dp_higher = greedy_higher = equal = mv_more_stops = mv_same_stops = 0
    gaps = []
    for slug, offset, days, pace, interests in grid:
        city = cities[slug]
        base = dict(city=slug, start_date=date(2026, 11, 2) + timedelta(days=offset), days=days, day_start=540,
                    day_end=1140, interests=interests, pace=pace,
                    start=city.stays[0].slug, lunch=lunch)
        plans = {key: plan_trip(city, TripRequest(strategy=key, **base))
                 for key in ("dp", "greedy", "max_visits")}
        assert not any(p.violations for p in plans.values()), slug
        dp, greedy, mv = plans["dp"], plans["greedy"], plans["max_visits"]
        if dp.score > greedy.score:
            dp_higher += 1
        elif dp.score < greedy.score:
            greedy_higher += 1
        else:
            equal += 1
        if mv.stops > dp.stops:
            mv_more_stops += 1
        elif mv.stops == dp.stops:
            mv_same_stops += 1
        if greedy.score:
            gaps.append(100 * (dp.score - greedy.score) / greedy.score)
    total = dp_higher + greedy_higher + equal
    summary = {"scenarios": total, "dp_higher": dp_higher, "greedy_higher": greedy_higher, "equal": equal,
               "mean_dp_gain_pct": round(statistics.mean(gaps), 2),
               "max_visits_more_stops": mv_more_stops, "max_visits_same_stops": mv_same_stops,
               "cities": list(cities),
               "grid": f"{len(cities)} highest-ranked ready cities x {2 if quick else 3} start days x 1-3 days x "
                       "pace {balanced, relaxed} x interests {none, history, spirituality}; 09:00-19:00 with lunch"}
    print(f"real scenarios: {total} trips, DP higher {dp_higher}, Greedy higher {greedy_higher}, equal {equal}; "
          f"Max visits more stops than DP in {mv_more_stops}")
    return summary


def bench_modes(quick=False):
    """Calibrate Suggested mode on real cities, and compare the three modes.

    Scenarios: the most popular timed places of each ready city (3, 4, 6 or 8 of them) over 3 or 5 days,
    09:00-19:00 with lunch, from the central stay. For each scenario the fewest feasible days (Most
    Optimized) and Suggested's choice under several "cost of one more day" values are recorded, with the
    longest day each plan needs. A good day cost adds days when one long day is clearly over-long and
    otherwise keeps the fastest plan.
    """
    import itertools
    import tempfile
    from datetime import date

    import config
    from config import Config
    from database import queries
    from database.db import connect
    from database.seed_data import seed_database
    from services.city_data import load_city
    from services.itinerary_generator import plan_trip
    from services.models import MealSetting, TripRequest

    path = os.path.join(tempfile.mkdtemp(), "modes.db")
    seed_database(path, Config.DATA_DIR)
    conn = connect(path)
    cities = []
    for row in queries.list_cities(conn):
        city = load_city(conn, row["slug"], Config.TRAFFIC_FACTOR)
        if city.readiness()["status"] == "ready":
            cities.append(city)
        if len(cities) == (4 if quick else 10):
            break
    conn.close()
    lunch = MealSetting("lunch", 12 * 60, 14 * 60 + 30, 45)
    day_costs = [0, 30, 60, 90, 120]
    saved = config.SUGGESTED_DAY_COST
    rows = []
    for city in cities:
        ranked = sorted((a for a in city.attractions.values() if a.timed and not a.is_food_or_shopping_only),
                        key=lambda a: (-a.popularity, a.id))
        for n, days in itertools.product([3, 4, 6, 8], [3, 5]):
            if len(ranked) < n:
                continue
            base = dict(city=city.slug, start_date=date(2026, 11, 3), days=days, day_start=540, day_end=1140,
                        interests=(), pace="balanced", start=city.stays[0].slug, strategy="dp", lunch=lunch,
                        places=tuple(a.slug for a in ranked[:n]))
            fast = plan_trip(city, TripRequest(mode="optimized", **base), validate=False)
            even = plan_trip(city, TripRequest(mode="evenly", **base), validate=False)

            def longest(it):
                return max((d.return_time - d.depart for d in it.days if d.visits), default=0)
            row = {"city": city.slug, "places": n, "days": days, "scheduled": fast.stops,
                   "optimized_days": len(fast.active_days), "optimized_longest": longest(fast),
                   "evenly_days": len(even.active_days), "evenly_longest": longest(even)}
            for cost in day_costs:
                config.SUGGESTED_DAY_COST = cost
                sug = plan_trip(city, TripRequest(mode="suggested", **base), validate=False)
                row[f"suggested_days_{cost}"] = len(sug.active_days)
                row[f"suggested_longest_{cost}"] = longest(sug)
            config.SUGGESTED_DAY_COST = saved
            rows.append(row)
    summary = {"scenarios": len(rows), "cities": [c.slug for c in cities], "day_costs": day_costs, "by_cost": {}}
    for cost in day_costs:
        more = [r for r in rows if r[f"suggested_days_{cost}"] > r["optimized_days"]]
        summary["by_cost"][cost] = {
            "suggested_uses_more_days_pct": round(100 * len(more) / len(rows), 1) if rows else 0.0,
            "mean_longest_day_saved_min": round(statistics.mean(
                r["optimized_longest"] - r[f"suggested_longest_{cost}"] for r in more), 1) if more else 0.0,
            "mean_extra_days": round(statistics.mean(
                r[f"suggested_days_{cost}"] - r["optimized_days"] for r in more), 2) if more else 0.0,
        }
    print(f"modes: {len(rows)} scenarios; Suggested uses more days than Most Optimized in "
          + ", ".join(f"{v['suggested_uses_more_days_pct']}% (cost {k})" for k, v in summary["by_cost"].items()))
    return {"summary": summary, "rows": rows}


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
            "selection_instance": "time cap 540 min (10-min units)",
            "routing_instance": "start + k stops in a 15 x 15 km square, 25 km/h, up to 10% directional asymmetry",
            "graph_instance": "V points in a 30 x 30 km square, 5 nearest neighbours each, both directions",
        },
        "selection": bench_selection([10, 20, 30, 40, 60], seeds, repeats),
        "routing": bench_routing(list(range(4, 11)), seeds, repeats),
        "dijkstra": bench_dijkstra([25, 50, 100, 200], seeds, repeats),
        "real_scenarios": bench_real_scenarios(quick=args.quick),
        "modes": bench_modes(quick=args.quick),
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
