"""Run every strategy on identical input and measure them (the comparison page).

Rules that keep the comparison honest:
  * methods are compared only on the SAME input (same candidates, same travel
    table, same limits, same meals and settings);
  * quality is always shown next to speed, and speed never counts towards the score;
  * a plan that breaks any constraint can never be recommended (services/scorecard.py);
  * timings are medians of repeated runs after a warm-up (services/timing.py);
  * nothing is hard-coded: every number below is produced by running our code.

Sections:
  1. whole itineraries: DP vs Greedy -> raw metrics, subscores, overall, recommendation
  2. selection on each day's identical knapsack instance: both selectors
  3. routing each planned day: Nearest Neighbour vs NN + 2-opt vs Held-Karp optimum,
     plus the travel-first vs window-first branches (kept separate from section 1)
  4. Dijkstra vs NetworkX on every pair of places
  5. a textbook instance run live: the greedy trap
  6. saved scaling benchmarks (results/benchmarks.json), if the script has been run
  M. the three itinerary modes on the same places: how each spreads them over the days
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
from services import scorecard, versioning
from services.i18n import gettext as _
from services.crosscheck import crosscheck_city
from services.itinerary_generator import day_context, plan_trip, route_branches, trip_context
from services.scheduler import simulate
from services.timing import median_ms

STRATEGY_ORDER = ["dp", "greedy"]
SELECTOR_FUNCTIONS = {"dp": dp_select, "greedy": greedy_select}


def compare_itineraries(city, trip, repeats, trace=None):
    """Both strategies' whole plans. `trace` (a list) receives the DP run's per-day knapsack instances,
    so the selection comparison does not have to plan the trip again."""
    rows, plans = [], {}
    plan_repeats = min(repeats, config.PLAN_TIMING_REPEATS)
    for key in STRATEGY_ORDER:
        variant = trip.with_changes(strategy=key)
        itinerary = plan_trip(city, variant, trace=trace if key == "dp" else None)
        plans[key] = itinerary
        row = {"key": key, "label": config.STRATEGIES[key], "short": config.STRATEGY_SHORT[key],
               "objective": config.STRATEGY_OBJECTIVES[key], "metrics": scorecard.raw_metrics(itinerary),
               "plan_id": itinerary.versions["plan"],
               "per_day": [{"day": d.index, "stops": len(d.visits), "score": d.score, "travel_min": d.travel_min}
                           for d in itinerary.days],
               "stop_names": [[v.attraction.name for v in d.visits] for d in itinerary.days]}
        # The plan above was the warm-up (travel tables and caches are loaded), so only timed runs follow.
        row["runtime_ms"] = median_ms(lambda: plan_trip(city, variant, validate=False), plan_repeats, warm_up=False)
        rows.append(row)
    weights = scorecard.subscores(rows)
    recommendation = scorecard.recommend(rows, {r["key"]: r["plan_id"] for r in rows})
    return rows, plans, weights, recommendation


def compare_selection(city, trip, repeats, trace=None):
    """Both selectors on exactly the knapsack instance the DP pipeline built for each day."""
    if trace is None:
        trace = []
        plan_trip(city, trip.with_changes(strategy="dp"), trace=trace, validate=False)
    names = {aid: a.name for aid, a in city.attractions.items()}
    rows = []
    for record in trace:
        instance = record.get("instance")
        if instance is None:
            continue
        items, T = instance.items, instance.time_cap

        def describe(result):
            return {"score": result.score, "count": len(result.chosen),
                    "minutes": result.weight * instance.time_unit,
                    "names": [names[i] for i in result.chosen]}

        results = {key: SELECTOR_FUNCTIONS[key](items, T) for key in STRATEGY_ORDER}
        dp, greedy = results["dp"], results["greedy"]
        rows.append({
            "day": record["day"],
            "date": record["ctx"].weekday,
            "candidates": len(items),
            "time_cap_min": T * instance.time_unit,
            "reserved": instance.reserved,
            "cells": (len(items) + 1) * (T + 1),
            "greedy": describe(greedy),
            "dp": describe(dp),
            "gap": dp.score - greedy.score,
            "gap_pct": round(100 * (dp.score - greedy.score) / dp.score, 1) if dp.score else 0.0,
            "greedy_ms": median_ms(lambda: greedy_select(items, T), repeats),
            "dp_ms": median_ms(lambda: dp_select(items, T), repeats),
        })
    return rows


def _coords(city, start_id, route):
    points = [start_id] + list(route) + [start_id]
    return [[city.places[p].lat, city.places[p].lng] for p in points]


def compare_routing(city, trip, plan, repeats):
    """For each day of a plan: how good is each route-construction method on the same stops?

    Travel here is RAW road minutes (before the 10-minute rounding), because
    route optimisation works on the raw values.
    """
    rows = []
    tctx = trip_context(city, trip)
    for day in plan.days:
        stops = [v.attraction.id for v in day.visits]
        if not stops:
            continue
        ctx = day_context(city, trip, day.date, tctx)
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
            "improvement_pct": round(100 * (nn_cost - opt_cost) / nn_cost, 1) if nn_cost else 0.0,
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
            "direct_link": any(n == v for n, _w in city.graph[u])}


def _demo(items, capacity_units, note):
    results = {key: SELECTOR_FUNCTIONS[key](items, capacity_units) for key in STRATEGY_ORDER}
    return {"capacity_min": capacity_units * 10, "note": note,
            "attractions": [{"name": it.id, "minutes": it.weight * 10, "score": it.score,
                             "density": round(it.score / (it.weight * 10), 2)} for it in items],
            **{key: {"chosen": r.chosen, "score": r.score, "count": len(r.chosen)} for key, r in results.items()}}


def greedy_trap():
    """The textbook counter-example, solved live by both selectors (times in 10-minute units)."""
    items = [Item("X", 90, 18), Item("Y", 60, 15), Item("Z", 60, 15)]
    return _demo(items, 30, _("Greedy takes X (best value per minute) and then nothing else fits; "
                              "DP considers every combination and finds Y + Z."))


def load_benchmarks(results_dir):
    path = os.path.join(results_dir, "benchmarks.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compare_modes(city, trip, known=None):
    """The same trip with each itinerary mode. The places are fixed first (yours, or the strategy's
    choice), so the only difference is how the mode spreads them over the days."""
    from services.distribution import comfort_minutes
    comfort = comfort_minutes(trip)
    rows = []
    for key, info in config.MODES.items():
        it = known if (known is not None and key == trip.mode) else plan_trip(city, trip.with_changes(mode=key))
        busy = [d.return_time - d.depart for d in it.days if d.visits]
        rows.append({
            "key": key, "label": info["label"], "text": info["text"], "plan_id": it.versions["plan"],
            "per_day": [len(d.visits) for d in it.days], "active_days": len(busy), "stops": it.stops,
            "selected": len(it.selected), "travel_min": it.travel_min, "access_min": it.access_min,
            "longest_min": max(busy, default=0), "over_comfort_min": sum(max(0, b - comfort) for b in busy),
            "violations": len(it.violations), "notes": it.mode_notes,
        })
    return {"rows": rows, "comfort_min": comfort,
            "identical": [[a["key"], b["key"]] for i, a in enumerate(rows) for b in rows[i + 1:]
                          if a["plan_id"] == b["plan_id"]]}


_CACHE = {}          # (trip, data version, settings version, repeats) -> finished comparison


def run_comparison(city, trip, results_dir, repeats=None):
    """Everything the comparison page shows. A finished comparison is kept in memory, so opening the
    same scenario again (same trip, same data, same settings) is instant; a changed input recomputes."""
    repeats = repeats or config.TIMING_REPEATS
    cache_key = (repr(trip), city.data_version, versioning.settings_version(), repeats, results_dir)
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    result = _run_comparison(city, trip, results_dir, repeats)
    if len(_CACHE) >= config.COMPARISON_CACHE_SIZE:
        _CACHE.pop(next(iter(_CACHE)))            # drop the oldest entry
    _CACHE[cache_key] = result
    return result


def _run_comparison(city, trip, results_dir, repeats):
    trace = []
    strategies, plans, weights, recommendation = compare_itineraries(city, trip, repeats, trace)
    dijkstra = crosscheck_city(city, repeats)
    dijkstra["example"] = dijkstra_example(city)
    dijkstra["sources"] = city.edge_sources
    route_key = recommendation["keys"][0] if recommendation["keys"] else "dp"
    return {
        "modes": compare_modes(city, trip, plans.get(trip.strategy)),
        "strategies": strategies,
        "by_key": {row["key"]: row for row in strategies},
        "weights": weights,
        "recommendation": recommendation,
        "tradeoffs": scorecard.tradeoffs(strategies),
        "selection": compare_selection(city, trip, repeats, trace),
        "route_strategy": route_key,
        "routing": compare_routing(city, trip.with_changes(strategy=route_key), plans[route_key], repeats),
        "dijkstra": dijkstra,
        "trap": greedy_trap(),
        "benchmarks": load_benchmarks(results_dir),
        "lambda": config.QUALITY_LAMBDA,
        "repeats": repeats,
        "versions": {"data": (city.data_version or "")[:10], "settings": versioning.settings_version()},
    }
