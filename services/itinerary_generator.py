"""The itinerary pipeline: how the algorithms work together.

Once per city (cached, see city_data.py):
    adjacency list -> Dijkstra from every place -> travel-time table

Once per trip:
    score every attraction (rating, popularity, interest match)

For each day, in date order:
    1. FILTER    keep attractions not yet planned, not excluded, open on this
                 weekday, reachable from and back to the start, affordable on
                 their own, and able to fit in the day on their own.
                 Every rejection is recorded with its reason.
    2. SELECT    0/1 knapsack (DP, default) or Greedy over (time, money).
                 Each stop's time weight = visit + pace buffer + its cheapest
                 way to leave (a lower bound on real travel), so no set that
                 truly fits is thrown away.
                 Alternative strategy: Activity Selection "max visits".
    3. ROUTE     travel-first:  Nearest Neighbour -> 2-opt
                 window-first:  stops taken in closing-time order (Activity
                                Selection rule), each inserted where it keeps
                                every opening window satisfied -> 2-opt that
                                only accepts feasible moves
                 keep the feasible branch with less travel.
    4. REPAIR    if no branch is feasible (or the day is over budget), the
                 weakest selected stop -- lowest score per minute (or per
                 rupee), taken from a min-heap -- leaves today's candidate pool
                 and the same selector runs again. The pool shrinks every
                 round, so the loop always ends; the worst case is an empty day
                 with a stated reason.
    5. COMMIT    build the timeline, mark the stops as used.

After all days, services/validator.py re-checks every constraint independently.

This select-then-route decomposition is a heuristic: the full problem
(orienteering with time windows) is NP-hard, so the result is not claimed to
be globally optimal.
"""

import heapq
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import config
from algorithms.activity_selection import max_visits_plan
from algorithms.dynamic_programming import dp_select
from algorithms.greedy import greedy_select
from algorithms.insertion import deadline_insertion_route
from algorithms.knapsack_types import Item
from algorithms.nearest_neighbor import nearest_neighbor_route
from algorithms.scoring import attraction_score
from algorithms.tour import tour_cost
from algorithms.two_opt import two_opt
from services.models import DayPlan, Itinerary, Skipped
from services.scheduler import DayContext, simulate
from services.timeutil import WEEKDAY_LONG, WEEKDAY_SHORT, fmt_hhmm
from services.validator import check_itinerary

SCORE_WEIGHTS = (config.W_RATING, config.W_POPULARITY, config.W_INTEREST)


@dataclass
class KnapsackInstance:
    """The integer knapsack handed to Greedy / DP for one day."""
    items: list                 # [Item(id, score, weight_units, cost_units)]
    time_cap: int               # T, in time units
    money_cap: int | None       # M, in money units (None = no budget)
    time_unit: int              # minutes per time unit
    money_unit: int | None      # rupees per money unit
    weight_minutes: dict        # id -> estimated minutes (visit + buffer + cheapest exit)
    cost_rupees: dict           # id -> fee (+ transport lower bound if included)


# ------------------------------------------------------------------------------ scoring

def score_attractions(city, interests):
    return {aid: attraction_score(a.rating, a.popularity, a.categories, interests, SCORE_WEIGHTS)
            for aid, a in city.attractions.items()}


# ------------------------------------------------------------------------------ step 1: filter

def day_context(city, trip, day_date):
    return DayContext(city=city, weekday=day_date.weekday(), day_start=trip.day_start, day_end=trip.day_end,
                      start_id=city.place(trip.start).id, buffer=config.PACES[trip.pace]["buffer"])


def round_trip_transport(city, start_id, aid, rate):
    return rate * (city.km[start_id][aid] + city.km[aid][start_id])


def filter_candidates(city, trip, ctx, unavailable, log, day_index, rate):
    """Attractions that could be visited today on their own. Rejections go into `log`."""
    start = ctx.start_id
    weekday = WEEKDAY_LONG[ctx.weekday]
    candidates = []
    for aid in sorted(city.attractions):
        if aid in unavailable:
            continue
        attraction = city.attractions[aid]
        if city.dist[start][aid] == math.inf or city.dist[aid][start] == math.inf:
            log[aid].append((day_index, "unreachable", "No road route between it and your start point"))
            continue
        if not attraction.windows_on(ctx.weekday):
            log[aid].append((day_index, "closed", f"Closed on {weekday}"))
            continue
        if trip.budget is not None:
            transport = round_trip_transport(city, start, aid, rate) if trip.include_transport else 0
            if attraction.fee + transport > trip.budget:
                extra = f" + ₹{transport:.0f} transport" if transport else ""
                log[aid].append((day_index, "over_budget",
                                 f"₹{attraction.fee} entry{extra} is more than your ₹{trip.budget} daily budget"))
                continue
        if not simulate([aid], ctx).feasible:
            log[aid].append((day_index, "does_not_fit",
                             f"Open {attraction.hours_label(ctx.weekday)} on {WEEKDAY_SHORT[ctx.weekday]}; "
                             f"a {attraction.visit_min}-min visit plus the round trip doesn't fit "
                             f"{fmt_hhmm(trip.day_start)}–{fmt_hhmm(trip.day_end)}"))
            continue
        candidates.append(aid)
    return candidates


# ------------------------------------------------------------------------------ step 2: select

def knapsack_instance(city, trip, ctx, candidates, scores, rate):
    """Turn today's candidates into an integer 2-D knapsack (time units x money units)."""
    dist, km, start = city.dist, city.km, ctx.start_id
    nodes = candidates + ([start] if start not in candidates else [])
    unit = config.DP_TIME_UNIT_MIN

    def cheapest_exit(table, i):
        """Lower bound on the trip out of stop i. If i is the start point itself (the trip starts
        at an attraction), the route can leave it straight back to its own location: 0."""
        if i == start:
            return 0
        return min(table[i][j] for j in nodes if j != i)

    # Capacity: the day length minus the shortest possible first ride (rounded DOWN).
    first_ride = min(dist[start][i] for i in candidates)
    time_cap = max(0, math.floor((ctx.day_end - ctx.day_start - first_ride) / unit))

    use_money = trip.budget is not None
    transport_rate = rate if trip.include_transport else 0
    money_unit = money_cap = None
    if use_money:
        money_unit = max(config.DP_MIN_MONEY_UNIT, math.ceil(trip.budget / config.DP_MAX_MONEY_CELLS))
        first_km = min(km[start][i] for i in candidates)
        money_cap = max(0, math.floor((trip.budget - transport_rate * first_km) / money_unit + 1e-9))

    items, weight_minutes, cost_rupees = [], {}, {}
    for i in candidates:
        attraction = city.attractions[i]
        # Every route leaves each stop exactly once, so its cheapest exit is a lower bound on real travel.
        weight_minutes[i] = attraction.visit_min + ctx.buffer + cheapest_exit(dist, i)
        weight = math.ceil(weight_minutes[i] / unit)                    # rounded UP
        cost = 0
        if use_money:
            cost_rupees[i] = attraction.fee + transport_rate * cheapest_exit(km, i)
            cost = math.ceil(cost_rupees[i] / money_unit - 1e-9)        # rounded UP
        else:
            cost_rupees[i] = attraction.fee
        items.append(Item(id=i, score=scores[i], weight=weight, cost=cost))
    return KnapsackInstance(items, time_cap, money_cap, unit, money_unit, weight_minutes, cost_rupees)


SELECTORS = {"dp": dp_select, "greedy": greedy_select}


# ------------------------------------------------------------------------------ step 3: route

def route_branches(stops, ctx):
    """Both routing branches for a set of stops. Returns {branch: (route, feasible)}."""
    city, start, dist = ctx.city, ctx.start_id, ctx.city.dist

    def feasible(route):
        return simulate(route, ctx).feasible

    branches = {}
    # Travel-first: Nearest Neighbour, then 2-opt on travel time only.
    nn = nearest_neighbor_route(start, stops, dist)
    route, _ = two_opt(start, nn, dist)
    if not feasible(route) and feasible(nn):
        route, _ = two_opt(start, nn, dist, is_feasible=feasible)     # keep the windows NN already met
    branches["travel-first"] = (route, feasible(route))

    # Window-first: stops taken in closing-time order (Activity Selection rule), each inserted where it
    # keeps every window satisfied; then a 2-opt that only accepts feasible moves.
    closing = {s: city.attractions[s].closing_time_on(ctx.weekday) for s in stops}
    route, unplaced = deadline_insertion_route(start, stops, closing, dist, feasible)
    if unplaced:
        branches["window-first"] = (route + unplaced, False)
    else:
        route, _ = two_opt(start, route, dist, is_feasible=feasible)
        branches["window-first"] = (route, True)
    return branches


def best_route(stops, ctx):
    """The feasible branch with less travel (ties go to travel-first), or None."""
    start, dist = ctx.start_id, ctx.city.dist
    options = [(name, route) for name, (route, ok) in route_branches(stops, ctx).items() if ok]
    if not options:
        return None
    name, route = min(options, key=lambda option: tour_cost(start, option[1], dist))
    return route, name


# ------------------------------------------------------------------------------ steps 2-4: select, route, repair

def select_route_repair(city, trip, ctx, candidates, scores, rate, selector, spend_ok):
    """Select with `selector`, route, and repair until the day works.

    Repair: if no branch gives a feasible day (or the day is over budget), the
    weakest selected stop leaves today's candidate pool and the SAME selector
    runs again, so DP (or Greedy) can re-optimise with the time that frees up.
    The weakest stop comes from a min-heap keyed by
        score per estimated minute   when the timeline failed, or
        score per estimated rupee    when the budget failed.
    The pool shrinks every round, so the loop always ends.

    Returns (route, branch, first_instance, first_selection, dropped).
    """
    pool = list(candidates)
    dropped = []
    first_instance = first_selection = None
    while pool:
        instance = knapsack_instance(city, trip, ctx, pool, scores, rate)
        selection = selector(instance.items, instance.time_cap, instance.money_cap)
        if first_instance is None:
            first_instance, first_selection = instance, selection
        if not selection.chosen:
            break
        found = best_route(selection.chosen, ctx)
        if found is not None and spend_ok(found[0]):
            return found[0], found[1], first_instance, first_selection, dropped
        if found is None:
            heap = [(scores[a] / instance.weight_minutes[a], a) for a in selection.chosen]
        else:
            heap = [(scores[a] / (instance.cost_rupees[a] + 1), a) for a in selection.chosen]
        heapq.heapify(heap)                          # min-heap: weakest stop on top
        _, victim = heapq.heappop(heap)
        pool.remove(victim)
        dropped.append(victim)
    return [], "", first_instance, first_selection, dropped


# ------------------------------------------------------------------------------ one day

def plan_day(city, trip, day_index, day_date, scores, used, excluded, log, rate, trace=None):
    ctx = day_context(city, trip, day_date)
    candidates = filter_candidates(city, trip, ctx, used | excluded, log, day_index, rate)

    def spend(route):
        fees = sum(city.attractions[a].fee for a in route)
        transport = rate * tour_cost(ctx.start_id, route, city.km) if trip.include_transport else 0
        return fees + transport

    def spend_ok(route):
        return trip.budget is None or spend(route) <= trip.budget + 1e-9

    record = {"day": day_index, "ctx": ctx, "candidates": candidates}
    order, branch = [], ""
    if candidates:
        if trip.strategy == "max_visits":
            closing = {a: city.attractions[a].closing_time_on(ctx.weekday) for a in candidates}
            order = max_visits_plan(candidates, closing,
                                    can_append=lambda route: simulate(route, ctx).feasible and spend_ok(route))
            branch = "activity-selection"
            chosen = set(order)
        else:
            order, branch, instance, selection, dropped = select_route_repair(
                city, trip, ctx, candidates, scores, rate, SELECTORS[trip.strategy], spend_ok)
            chosen = set(order)
            for aid in dropped:
                log[aid].append((day_index, "dropped",
                                 "Selected, then removed because the day's timeline or budget did not work out"))
            record.update(instance=instance, selection=selection, dropped=dropped)
        for aid in candidates:
            if aid not in chosen and (trip.strategy == "max_visits" or aid not in record.get("dropped", [])):
                log[aid].append((day_index, "not_selected",
                                 f"Other stops gave more value for the time and budget (score {scores[aid]})"))
    record.update(order=order, branch=branch)
    if trace is not None:
        trace.append(record)

    if not order:
        reason, suggestions = explain_empty_day(city, trip, ctx, day_index, used | excluded,
                                                excluded, log, bool(candidates), rate)
        return DayPlan(index=day_index, date=day_date, depart=trip.day_start, visits=[], return_leg=None,
                       transport_rate=rate, empty_reason=reason, suggestions=suggestions)

    schedule = simulate(order, ctx, scores, detailed=True)
    return DayPlan(index=day_index, date=day_date, depart=schedule.depart, visits=schedule.visits,
                   return_leg=schedule.return_leg, transport_rate=rate, branch=branch)


# ------------------------------------------------------------------------------ whole trip

def plan_trip(city, trip, transport_rate, trace=None, validate=True):
    """Plan every day of the trip. Deterministic: the same trip always gives the same plan."""
    started = time.perf_counter()
    scores = score_attractions(city, trip.interests)
    excluded = {city.attraction_by_slug(slug).id for slug in trip.exclude}
    used, days = set(), []
    log = defaultdict(list)                  # attraction id -> [(day, code, detail)]

    for index, day_date in enumerate(trip.dates(), start=1):
        day = plan_day(city, trip, index, day_date, scores, used, excluded, log, transport_rate, trace)
        used.update(v.attraction.id for v in day.visits)
        days.append(day)

    itinerary = Itinerary(trip=trip, city_name=city.name, start_place=city.place(trip.start), days=days,
                          skipped=explain_skipped(city, used, excluded, log))
    itinerary.runtime_ms = (time.perf_counter() - started) * 1000
    if validate:
        itinerary.violations = check_itinerary(itinerary, city, transport_rate)
    return itinerary


# ------------------------------------------------------------------------------ explanations

SKIP_PRIORITY = ["excluded", "unreachable", "dropped", "not_selected", "does_not_fit", "over_budget", "closed"]


def explain_skipped(city, used, excluded, log):
    """One clear reason for every attraction that is not in the plan."""
    skipped = []
    for aid in sorted(city.attractions):
        if aid in used:
            continue
        attraction = city.attractions[aid]
        if aid in excluded:
            skipped.append(Skipped(attraction, "excluded", "You excluded it from this trip."))
            continue
        entries = log.get(aid, [])
        codes = {code for _, code, _ in entries}
        details = [f"Day {day}: {detail}" for day, _, detail in entries]
        code = next((c for c in SKIP_PRIORITY if c in codes), "not_selected")
        if code == "closed":
            days = sorted({detail.removeprefix("Closed on ") for _, c, detail in entries if c == "closed"})
            reason = f"Closed on {', '.join(days)} — every day of your trip."
        elif code == "unreachable":
            reason = "No road route to it in our travel graph."
        elif code == "over_budget":
            reason = "Costs more than your daily budget allows."
        elif code == "does_not_fit":
            reason = "Its opening hours don't fit inside your daily time window."
        elif code == "dropped":
            reason = "Selected, but removed so the day's timeline and budget could work."
        else:
            reason = "Other attractions gave more value for the time and budget you had."
        skipped.append(Skipped(attraction, code, reason, details))
    return skipped


def explain_empty_day(city, trip, ctx, day_index, unavailable, excluded, log, had_candidates, rate):
    """Specific reason + one-click suggestions for a day with no stops."""
    weekday = WEEKDAY_LONG[ctx.weekday]
    remaining = [aid for aid in city.attractions if aid not in unavailable]
    today = {aid: [code for d, code, _ in log.get(aid, []) if d == day_index] for aid in remaining}
    # Places with no road route can never be planned, so they don't count as "remaining".
    unreachable = [aid for aid, codes in today.items() if codes and codes[0] == "unreachable"]
    remaining = [aid for aid in remaining if aid not in unreachable]
    suggestions = []
    if not remaining:
        reason = f"Every reachable attraction in {city.name} is already in your plan" + (" or excluded." if excluded else ".")
        if day_index > 1:
            suggestions.append({"label": f"Make it a {day_index - 1}-day trip",
                                "query": trip.to_query(days=day_index - 1)})
        return reason, suggestions

    codes = [today[aid][0] for aid in remaining if today[aid]]
    if had_candidates:
        reason = "The selected stops could not be scheduled around their opening hours and your budget."
    elif codes and all(c == "closed" for c in codes):
        reason = f"All {len(remaining)} remaining attractions are closed on {weekday}."
    elif codes and all(c == "over_budget" for c in codes):
        reason = f"A ₹{trip.budget} budget can't cover any remaining attraction on {weekday}."
    elif codes and all(c == "does_not_fit" for c in codes):
        reason = (f"None of the remaining attractions fit inside {fmt_hhmm(trip.day_start)}–"
                  f"{fmt_hhmm(trip.day_end)} on {weekday}.")
    else:
        labels = {"closed": "closed on " + weekday, "over_budget": "over your budget",
                  "does_not_fit": f"can't fit in {fmt_hhmm(trip.day_start)}–{fmt_hhmm(trip.day_end)}"}
        parts = [f"{codes.count(c)} {labels[c]}" for c in ("closed", "over_budget", "does_not_fit") if c in codes]
        reason = f"Of the {len(remaining)} remaining attractions: " + "; ".join(parts) + "."

    if "over_budget" in codes and trip.budget is not None:
        blocked = [city.attractions[a].fee
                   + (round_trip_transport(city, ctx.start_id, a, rate) if trip.include_transport else 0)
                   for a, c in today.items() if c and c[0] == "over_budget"]
        new_budget = int(math.ceil(min(blocked) / 10) * 10)
        suggestions.append({"label": f"Raise budget to ₹{new_budget}", "query": trip.to_query(budget=new_budget)})
    if "does_not_fit" in codes or had_candidates:
        later = min(trip.day_end + 120, 23 * 60 + 59)
        if later > trip.day_end:
            suggestions.append({"label": f"End the day at {fmt_hhmm(later)}", "query": trip.to_query(day_end=later)})
    if "closed" in codes:
        suggestions.append({"label": "Start one day later",
                            "query": trip.to_query(start_date=trip.start_date + timedelta(days=1))})
    return reason, suggestions
