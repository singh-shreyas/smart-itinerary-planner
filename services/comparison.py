"""Run every strategy on identical input and measure them (the comparison page).

Rules that keep the comparison honest:
  * methods are compared only on the SAME input (same candidates, same travel
    table, same limits);
  * quality is always shown next to speed;
  * timings are medians of repeated runs after a warm-up (services/timing.py);
  * nothing is hard-coded: every number below is produced by running our code.

Sections:
  1. whole itineraries: DP vs Greedy vs Activity-Selection "max visits"
  2. selection on each day's identical knapsack instance: Greedy vs DP
  3. routing each planned day: Nearest Neighbour vs NN + 2-opt vs Held-Karp optimum,
     plus the travel-first vs window-first branches
  4. Dijkstra vs NetworkX on every pair of places
  5. the textbook "greedy trap" instance, run live
  6. saved scaling benchmarks (results/benchmarks.json), if the script has been run
"""

import json
import os

import config
from algorithms.activity_selection import earliest_deadline_order
from algorithms.dynamic_programming import dp_select
from algorithms.greedy import greedy_select
from algorithms.held_karp import held_karp
from algorithms.knapsack_types import Item
from algorithms.nearest_neighbor import nearest_neighbor_route
from algorithms.tour import tour_cost
from algorithms.two_opt import two_opt
from services.crosscheck import crosscheck_city
from services.itinerary_generator import day_context, plan_trip, route_branches
from services.scheduler import simulate
from services.timing import median_ms

STRATEGY_ORDER = ["dp", "greedy", "max_visits"]


def _plan_metrics(itinerary):
    return {
        "stops": itinerary.stops,
        "score": itinerary.score,
        "travel_min": itinerary.travel_min,
        "km": itinerary.km,
        "sight_min": itinerary.sight_min,
        "wait_min": itinerary.wait_min,
        "fees": itinerary.fees,
        "transport": itinerary.transport_cost,
        "spend": itinerary.spend,
        "violations": len(itinerary.violations),
        "empty_days": sum(1 for d in itinerary.days if not d.visits),
        "quality": round(itinerary.score - config.QUALITY_LAMBDA * itinerary.travel_min, 1),
        "per_day": [{"day": d.index, "stops": len(d.visits), "score": d.score, "travel_min": d.travel_min}
                    for d in itinerary.days],
    }


def compare_itineraries(city, trip, rate, repeats):
    rows, plans = [], {}
    for key in STRATEGY_ORDER:
        variant = trip.with_changes(strategy=key)
        itinerary = plan_trip(city, variant, rate)
        plans[key] = itinerary
        row = {"key": key, "label": config.STRATEGIES[key]}
        row.update(_plan_metrics(itinerary))
        row["runtime_ms"] = median_ms(lambda: plan_trip(city, variant, rate, validate=False), repeats)
        rows.append(row)
    return rows, plans


def compare_selection(city, trip, rate, repeats):
    """Greedy and DP on exactly the knapsack instance the DP pipeline built for each day."""
    trace = []
    plan_trip(city, trip.with_changes(strategy="dp"), rate, trace=trace, validate=False)
    names = {aid: a.name for aid, a in city.attractions.items()}
    rows = []
    for record in trace:
        instance = record.get("instance")
        if instance is None:
            continue
        items, T, M = instance.items, instance.time_cap, instance.money_cap
        greedy = greedy_select(items, T, M)
        dp = dp_select(items, T, M)

        def describe(result):
            return {"score": result.score, "count": len(result.chosen),
                    "minutes": result.weight * instance.time_unit,
                    "rupees": result.cost * instance.money_unit if instance.money_unit else None,
                    "names": [names[i] for i in result.chosen]}

        rows.append({
            "day": record["day"],
            "date": record["ctx"].weekday,
            "candidates": len(items),
            "time_cap_min": T * instance.time_unit,
            "money_cap": M * instance.money_unit if M is not None else None,
            "cells": (len(items) + 1) * (T + 1) * ((M + 1) if M is not None else 1),
            "greedy": describe(greedy),
            "dp": describe(dp),
            "gap": dp.score - greedy.score,
            "gap_pct": round(100 * (dp.score - greedy.score) / dp.score, 1) if dp.score else 0.0,
            "greedy_ms": median_ms(lambda: greedy_select(items, T, M), repeats),
            "dp_ms": median_ms(lambda: dp_select(items, T, M), repeats),
        })
    return rows


def _coords(city, start_id, route):
    points = [start_id] + list(route) + [start_id]
    return [[city.places[p].lat, city.places[p].lng] for p in points]


def compare_routing(city, trip, plan, repeats):
    """For each day of the DP plan: how good is each route-construction method on the same stops?"""
    rows = []
    for day in plan.days:
        stops = [v.attraction.id for v in day.visits]
        if not stops:
            continue
        ctx = day_context(city, trip, day.date)
        start, dist = ctx.start_id, city.dist

        nn = nearest_neighbor_route(start, stops, dist)
        nn_cost = tour_cost(start, nn, dist)
        opt, opt_cost = two_opt(start, nn, dist)
        row = {
            "day": day.index, "weekday": day.date.weekday(), "k": len(stops),
            "nn": {"travel": nn_cost, "violations": len(simulate(nn, ctx).violations),
                   "ms": median_ms(lambda: nearest_neighbor_route(start, stops, dist), repeats)},
            "two_opt": {"travel": opt_cost, "violations": len(simulate(opt, ctx).violations),
                        "ms": median_ms(lambda: two_opt(start, nn, dist), repeats)},
            "final": {"travel": tour_cost(start, stops, dist), "branch": day.branch},
            "routes": {"nn": _coords(city, start, nn), "two_opt": _coords(city, start, opt),
                       "final": _coords(city, start, stops)},
            "names": {"nn": [city.places[s].name for s in nn], "two_opt": [city.places[s].name for s in opt]},
        }
        closing = {s: city.attractions[s].closing_time_on(ctx.weekday) for s in stops}
        edf = earliest_deadline_order(stops, closing)
        row["edf"] = {"travel": tour_cost(start, edf, dist), "violations": len(simulate(edf, ctx).violations)}

        if len(stops) <= config.HELD_KARP_MAX_STOPS:
            hk_cost, hk_order = held_karp(start, stops, dist)
            row["held_karp"] = {"travel": hk_cost,
                                "violations": len(simulate(hk_order, ctx).violations),
                                "ms": median_ms(lambda: held_karp(start, stops, dist), repeats)}
            row["routes"]["held_karp"] = _coords(city, start, hk_order)
            for key in ("nn", "two_opt", "final"):
                travel = row[key]["travel"]
                row[key]["gap_pct"] = round(100 * (travel - hk_cost) / hk_cost, 1) if hk_cost else 0.0
        else:
            row["held_karp"] = None

        branches = route_branches(stops, ctx)
        row["branches"] = {name: {"travel": tour_cost(start, route, dist), "feasible": ok}
                           for name, (route, ok) in branches.items()}
        rows.append(row)
    return rows


def dijkstra_example(city):
    """The pair of attractions whose shortest path chains the most local links."""
    best = None
    ids = sorted(city.attractions)
    for u in ids:
        for v in ids:
            if u == v:
                continue
            path = city.path(u, v)
            if path and (best is None or len(path) > len(best)):
                best = path
    if not best:
        return None
    u, v = best[0], best[-1]
    return {"from": city.places[u].name, "to": city.places[v].name,
            "minutes": city.dist[u][v], "km": round(city.km[u][v], 1),
            "path": [city.places[p].name for p in best],
            "direct_link": any(n == v for n, _ in city.graph[u])}


def greedy_trap():
    """The textbook counter-example, solved live by both selectors (times in 10-minute units)."""
    items = [Item("X", 90, 18, 0), Item("Y", 60, 15, 0), Item("Z", 60, 15, 0)]
    greedy = greedy_select(items, 30)
    dp = dp_select(items, 30)
    return {"capacity_min": 300,
            "attractions": [{"name": it.id, "minutes": it.weight * 10, "score": it.score,
                             "density": round(it.score / (it.weight * 10), 2)} for it in items],
            "greedy": {"chosen": greedy.chosen, "score": greedy.score},
            "dp": {"chosen": dp.chosen, "score": dp.score}}


def load_benchmarks(results_dir):
    path = os.path.join(results_dir, "benchmarks.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_comparison(city, trip, rate, results_dir, repeats=None):
    repeats = repeats or config.TIMING_REPEATS
    strategies, plans = compare_itineraries(city, trip, rate, repeats)
    dijkstra = crosscheck_city(city, repeats)
    dijkstra["example"] = dijkstra_example(city)
    dijkstra["sources"] = city.edge_sources
    return {
        "strategies": strategies,
        "by_key": {row["key"]: row for row in strategies},
        "selection": compare_selection(city, trip, rate, repeats),
        "routing": compare_routing(city, trip.with_changes(strategy="dp"), plans["dp"], repeats),
        "dijkstra": dijkstra,
        "trap": greedy_trap(),
        "benchmarks": load_benchmarks(results_dir),
        "lambda": config.QUALITY_LAMBDA,
        "repeats": repeats,
    }
