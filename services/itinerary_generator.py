"""The itinerary pipeline: how the algorithms work together.

Once per city (or group of nearby cities; cached, see city_data.py):
    adjacency list -> Dijkstra from every place -> raw travel table
    -> planning table (each shortest time rounded UP to 10 minutes)

Once per trip:
    score every attraction (rating or neutral prior, popularity, interest match)
    trip-level rules: excluded by you / no road access / "only matching
    interests" / food and shopping places only when you ask for them

For each day, in date order:
    1. FILTER    keep attractions not yet planned, open on this weekday,
                 reachable from and back to the start, affordable on their own,
                 and able to fit in the day on their own (meals included).
                 Every rejection is recorded with its reason.
    2. SELECT    one 0/1 knapsack instance over (time, money), solved by the
                 chosen strategy:  dp (max total value, exact), greedy (value
                 density, fast), max_visits (max count then value, exact).
                 Each stop's time weight = visit + pace buffer + its cheapest
                 way to leave (a lower bound on real travel); the capacity is
                 the day minus the shortest first ride, the unavoidable extra
                 for the ride home, and the meal breaks. So no set that truly
                 fits is ever thrown away.
    3. ROUTE     travel-first:  Nearest Neighbour -> 2-opt
                 window-first:  closing-time order + cheapest feasible insertion -> 2-opt
                 keep the feasible branch with less travel.
    4. REPAIR    if no branch is feasible (or the day is over budget), the
                 weakest selected stop (min-heap, by the strategy's own value
                 per minute / per rupee) leaves today's pool and the same
                 selector runs again. The pool shrinks, so the loop always ends.
    5. FILL      leftover candidates are inserted at their cheapest feasible
                 position while they still fit, so a longer day is really used.
    6. GROUP     multi-city trips: steps 2-5 run on each city's candidates alone
                 and on all of them together; the day keeps the best result by
                 the strategy's objective (so you do not zig-zag between cities).
    7. COMMIT    build the timeline (visits, meals, legs), explain unused time.

After all days, services/validator.py re-checks every constraint independently.

Determinism: every choice above breaks ties by a fixed rule -- higher value,
then less travel, then the smaller place id (the row order of the dataset) --
and no step uses randomness or the iteration order of a set. The same trip on
the same data and settings therefore always gives the same plan; the plan's
fingerprint (services/versioning.py) makes that checkable.

This select-then-route decomposition is a heuristic: the full problem
(orienteering with time windows) is NP-hard, so the result is not claimed to
be globally optimal.
"""

import heapq
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

import config
from algorithms.dynamic_programming import dp_select
from algorithms.greedy import greedy_select
from algorithms.insertion import cheapest_feasible_insertion, deadline_insertion_route
from algorithms.knapsack_types import Item
from algorithms.max_visits import max_visits_select
from algorithms.nearest_neighbor import nearest_neighbor_route
from algorithms.scoring import attraction_score, matches_interests
from algorithms.sorting import merge_sort
from algorithms.tour import tour_cost
from algorithms.two_opt import two_opt
from services import versioning
from services.city_data import group_name
from services.models import DayPlan, Itinerary, Skipped
from services.scheduler import DayContext, simulate
from services.timeutil import WEEKDAY_LONG, WEEKDAY_SHORT, fmt_duration, fmt_hhmm

SCORE_WEIGHTS = (config.W_RATING, config.W_POPULARITY, config.W_INTEREST)
SELECTORS = {"dp": dp_select, "greedy": greedy_select, "max_visits": max_visits_select}


@dataclass
class KnapsackInstance:
    """The integer knapsack handed to the selector for one day."""
    items: list                 # [Item(id, score, weight_units, cost_units)]
    time_cap: int               # T, in time units
    money_cap: int | None       # M, in money units (None = no budget)
    time_unit: int              # minutes per time unit
    money_unit: int | None      # rupees per money unit
    weight_minutes: dict        # id -> estimated minutes (visit + buffer + cheapest exit)
    cost_rupees: dict           # id -> fee (+ shopping spend, + transport lower bound if included)
    reserved: dict = field(default_factory=dict)   # minutes taken off the day before selection


@dataclass
class TripContext:
    """Per-trip facts computed once and shared by every day."""
    scores: dict                # attraction id -> integer score
    blocked: dict               # attraction id -> (code, reason) for trip-level rules
    venues: tuple               # (preference rank, place id) usable as meal venues
    durations: dict             # attraction id -> visit minutes override (shopping time)
    parents: dict               # category -> parent category


# ------------------------------------------------------------------------------ per-trip set-up

def category_parents(city):
    return {slug: c["parent"] for slug, c in city.categories.items() if c.get("parent")}


def score_attractions(city, interests):
    parents = category_parents(city)
    return {aid: attraction_score(a.rating, a.popularity, a.categories, interests, SCORE_WEIGHTS,
                                  prior=config.RATING_PRIOR, parents=parents)
            for aid, a in city.attractions.items()}


def trip_context(city, trip):
    """Scores, trip-level exclusions, meal venues and duration overrides for this trip."""
    parents = category_parents(city)
    kinds = {slug: c["kind"] for slug, c in city.categories.items()}
    opt_in_interests = [i for i in trip.interests if kinds.get(i) in ("food", "shopping")]
    excluded = {city.attraction_by_slug(slug).id for slug in trip.exclude if city.attraction_by_slug(slug)}

    blocked = {}
    for aid in sorted(city.attractions):
        a = city.attractions[aid]
        if aid in excluded:
            blocked[aid] = ("excluded", "You excluded it from this trip.")
        elif a.access == "no_road":
            blocked[aid] = ("no_road", a.access_note or "No road access in our travel graph (reached on foot or by boat).")
        elif trip.interest_mode == "only" and trip.interests and not matches_interests(a.categories, trip.interests, parents):
            blocked[aid] = ("interest", "Doesn't match your interests (you chose only matching places).")
        elif a.is_food_or_shopping_only and not matches_interests(a.categories, opt_in_interests, parents):
            blocked[aid] = ("opt_in", "Food and shopping places are planned only when you pick a matching "
                                      "food or shopping interest.")

    venues = []
    if trip.meals and trip.food_venues:
        styles = set(trip.venue_styles)
        for aid in sorted(city.attractions):
            a = city.attractions[aid]
            if not a.is_food or a.access == "no_road" or aid in excluded:
                continue
            if trip.veg_only and a.vegetarian != "yes":
                continue
            rank = 0 if not styles or styles & set(a.cuisine) else 1
            venues.append((rank, aid))

    durations = {}
    if trip.shop_minutes:
        durations = {aid: trip.shop_minutes for aid, a in city.attractions.items() if a.is_shopping_only}
    return TripContext(score_attractions(city, trip.interests), blocked, tuple(venues), durations, parents)


def interest_notes(city, trip, tctx):
    """Tell the traveller when an interest has no (or very little) data in these cities."""
    notes = []
    names = {slug: c["name"] for slug, c in city.categories.items()}
    for interest in trip.interests:
        matching = [a for aid, a in city.attractions.items()
                    if a.access == "road" and tctx.blocked.get(aid, ("",))[0] != "excluded"
                    and matches_interests(a.categories, [interest], tctx.parents)]
        label = names.get(interest, interest)
        if not matching:
            notes.append({"interest": interest, "count": 0,
                          "text": f"No “{label}” places in our data for {city.name}, so this interest "
                                  f"cannot change your plan."})
        elif len(matching) <= 2:
            listed = ", ".join(a.name for a in matching)
            notes.append({"interest": interest, "count": len(matching),
                          "text": f"Only {len(matching)} “{label}” place{'s' if len(matching) > 1 else ''} "
                                  f"in our data for {city.name}: {listed}."})
    return notes


# ------------------------------------------------------------------------------ step 1: filter

def day_context(city, trip, day_date, tctx=None):
    meals = tuple(sorted((m for m in trip.meals if m.needed(trip.day_start, trip.day_end)),
                         key=lambda m: (m.earliest, m.kind)))
    return DayContext(city=city, weekday=day_date.weekday(), day_start=trip.day_start, day_end=trip.day_end,
                      start_id=city.place(trip.start).id, buffer=config.PACES[trip.pace]["buffer"],
                      meals=meals, venues=tctx.venues if tctx else (),
                      durations=tctx.durations if tctx else {})


def round_trip_transport(city, start_id, aid, rate):
    return rate * (city.km[start_id][aid] + city.km[aid][start_id])


def own_cost(city, trip, aid):
    """Entry fee plus the planned shopping spend (shopping places only)."""
    a = city.attractions[aid]
    return a.fee + (trip.shop_spend if a.is_shopping_only else 0)


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
            cost = own_cost(city, trip, aid)
            if cost + transport > trip.budget:
                extra = f" + ₹{transport:.0f} transport" if transport else ""
                log[aid].append((day_index, "over_budget",
                                 f"₹{cost} entry{' and shopping' if cost != attraction.fee else ''}{extra} "
                                 f"is more than your ₹{trip.budget} daily budget"))
                continue
        alone = simulate([aid], ctx)
        if not alone.feasible:
            meals = " and your meal breaks" if ctx.meals else ""
            log[aid].append((day_index, "does_not_fit",
                             f"Open {attraction.hours_label(ctx.weekday)} on {WEEKDAY_SHORT[ctx.weekday]}; "
                             f"a {fmt_duration(ctx.duration(aid))} visit plus the round trip{meals} doesn't fit "
                             f"{fmt_hhmm(trip.day_start)}–{fmt_hhmm(trip.day_end)}"))
            continue
        candidates.append(aid)
    return candidates


# ------------------------------------------------------------------------------ step 2: select

def knapsack_instance(city, trip, ctx, candidates, scores, rate):
    """Turn today's candidates into an integer 2-D knapsack (time units x money units)."""
    plan, km, start = city.plan, city.km, ctx.start_id
    nodes = candidates + ([start] if start not in candidates else [])
    unit = config.DP_TIME_UNIT_MIN

    def cheapest_exit(table, i):
        """Lower bound on the trip out of stop i. If i is the start point itself (the trip starts
        at an attraction), the route can leave it straight back to its own location: 0."""
        if i == start:
            return 0
        return min(table[i][j] for j in nodes if j != i)

    # Capacity = day length minus everything every route must spend outside the items' weights:
    #   the shortest possible first ride,
    #   the unavoidable extra of the ride home beyond the last stop's cheapest exit, and
    #   the meal breaks the day must contain.
    first_ride = min(plan[start][i] for i in candidates)
    return_extra = max(0, min(plan[i][start] - cheapest_exit(plan, i) for i in candidates))
    reserved = {"first ride": first_ride, "ride home (extra)": return_extra, "meals": ctx.meal_minutes}
    time_cap = max(0, math.floor((ctx.day_end - ctx.day_start - sum(reserved.values())) / unit))

    use_money = trip.budget is not None
    transport_rate = rate if trip.include_transport else 0
    money_unit = money_cap = None
    if use_money:
        money_unit = max(config.DP_MIN_MONEY_UNIT, math.ceil(trip.budget / config.DP_MAX_MONEY_CELLS))
        first_km = min(km[start][i] for i in candidates)
        money_cap = max(0, math.floor((trip.budget - transport_rate * first_km) / money_unit + 1e-9))

    items, weight_minutes, cost_rupees = [], {}, {}
    for i in candidates:
        # Every route leaves each stop exactly once, so its cheapest exit is a lower bound on real travel.
        weight_minutes[i] = ctx.duration(i) + ctx.buffer + cheapest_exit(plan, i)
        weight = math.ceil(weight_minutes[i] / unit)                    # rounded UP
        cost = 0
        if use_money:
            cost_rupees[i] = own_cost(city, trip, i) + transport_rate * cheapest_exit(km, i)
            cost = math.ceil(cost_rupees[i] / money_unit - 1e-9)        # rounded UP
        else:
            cost_rupees[i] = own_cost(city, trip, i)
        items.append(Item(id=i, score=scores[i], weight=weight, cost=cost))
    return KnapsackInstance(items, time_cap, money_cap, unit, money_unit, weight_minutes, cost_rupees, reserved)


# ------------------------------------------------------------------------------ step 3: route

def route_branches(stops, ctx):
    """Both routing branches for a set of stops. Returns {branch: (route, feasible)}.

    Orders are compared on RAW travel minutes (finer than the 10-minute planning
    values); feasibility is always checked on the real, rounded timeline.
    """
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


# ------------------------------------------------------------------------------ steps 2-5 on one pool

def objective_key(strategy, route, scores, travel):
    """Smaller is better. dp / greedy: most value; max_visits: most stops, then value. Then less travel."""
    value = sum(scores[a] for a in route)
    if strategy == "max_visits":
        return (-len(route), -value, travel)
    return (-value, -len(route), travel)


def weakest_key(strategy, aid, scores, per_unit):
    """Repair key (min-heap): the stop giving the least of the strategy's objective per minute / rupee."""
    worth = 1 if strategy == "max_visits" else scores[aid]
    return (worth / per_unit, scores[aid], aid)


def fill_route(route, pool, ctx, scores, strategy, spend_ok):
    """Step 5: try every leftover candidate at its cheapest feasible position (deterministic order)."""
    start, dist = ctx.start_id, ctx.city.dist

    def feasible(candidate):
        return simulate(candidate, ctx).feasible

    leftovers = [a for a in pool if a not in route]
    if strategy == "max_visits":       # shortest first fits the most
        leftovers = merge_sort(leftovers, key=lambda a: (ctx.duration(a), -scores[a], a))
    else:                              # most valuable first
        leftovers = merge_sort(leftovers, key=lambda a: (-scores[a], a))
    added = []
    for aid in leftovers:
        inserted = cheapest_feasible_insertion(start, route, aid, dist, feasible)
        if inserted is not None and spend_ok(inserted):
            route = inserted
            added.append(aid)
    if added:
        route, _ = two_opt(start, route, dist, is_feasible=feasible)
    return route, added


def solve_pool(city, trip, ctx, pool, scores, rate, spend_ok):
    """Select with the trip's strategy, route, repair, then fill. Returns a record dict."""
    selector = SELECTORS[trip.strategy]
    candidates = list(pool)
    dropped = []
    first_instance = first_selection = None
    route, branch = [], ""
    while candidates:
        instance = knapsack_instance(city, trip, ctx, candidates, scores, rate)
        selection = selector(instance.items, instance.time_cap, instance.money_cap)
        if first_instance is None:
            first_instance, first_selection = instance, selection
        if not selection.chosen:
            break
        found = best_route(selection.chosen, ctx)
        if found is not None and spend_ok(found[0]):
            route, branch = found
            break
        if found is None:       # timeline failed: weakest value per estimated minute leaves
            heap = [weakest_key(trip.strategy, a, scores, instance.weight_minutes[a]) for a in selection.chosen]
        else:                   # budget failed: weakest value per estimated rupee leaves
            heap = [weakest_key(trip.strategy, a, scores, instance.cost_rupees[a] + 1) for a in selection.chosen]
        heapq.heapify(heap)                          # min-heap: weakest stop on top
        victim = heapq.heappop(heap)[-1]
        candidates.remove(victim)
        dropped.append(victim)
    added = []
    if config.FILL_STEP:
        route, added = fill_route(route, pool, ctx, scores, trip.strategy, spend_ok)
        if added and not branch:
            branch = "insertion"
    return {"route": route, "branch": branch, "instance": first_instance, "selection": first_selection,
            "dropped": [a for a in dropped if a not in route], "filled": added, "pool": list(pool)}


# ------------------------------------------------------------------------------ one day

def plan_day(city, trip, tctx, day_index, day_date, used, log, rate, trace=None):
    ctx = day_context(city, trip, day_date, tctx)
    blocked = set(tctx.blocked)
    candidates = filter_candidates(city, trip, ctx, used | blocked, log, day_index, rate)
    scores = tctx.scores

    def spend(route):
        own = sum(own_cost(city, trip, a) for a in route)
        # Transport is priced on the real timeline's km, so meal detours are paid for too.
        transport = rate * simulate(route, ctx).travel_km if (trip.include_transport and route) else 0
        return own + transport

    def spend_ok(route):
        return trip.budget is None or spend(route) <= trip.budget + 1e-9

    # Pools: everything together, plus (multi-city) each city on its own.
    pools = [("all", candidates)]
    if city.multi_city:
        for slug in city.city_slugs:
            pool = [a for a in candidates if city.city_of[a] == slug]
            if pool and len(pool) < len(candidates):
                pools.append((slug, pool))

    best = None
    for index, (label, pool) in enumerate(pools):
        if not pool:
            continue
        record = solve_pool(city, trip, ctx, pool, scores, rate, spend_ok)
        travel = simulate(record["route"], ctx).travel_min if record["route"] else 0
        cities_used = len({city.city_of[a] for a in record["route"]})
        key = objective_key(trip.strategy, record["route"], scores, travel) + (cities_used, index)
        record["label"] = label
        if best is None or key < best[0]:
            best = (key, record)
    record = best[1] if best else {"route": [], "branch": "", "dropped": [], "filled": [], "pool": [], "label": "all"}
    order = record["route"]
    focus = route_focus(city, order)

    chosen = set(order)
    for aid in record["dropped"]:
        log[aid].append((day_index, "dropped",
                         "Selected, then removed because the day's timeline or budget did not work out"))
    for aid in candidates:
        if aid in chosen or aid in record["dropped"]:
            continue
        if aid in record["pool"]:
            log[aid].append((day_index, "not_selected",
                             f"Other stops gave more value for the time and budget (score {scores[aid]})"))
        else:
            log[aid].append((day_index, "not_selected", f"Day {day_index} was planned around {focus}"))

    if trace is not None:
        trace.append({"day": day_index, "ctx": ctx, "candidates": candidates, "order": order,
                      "branch": record["branch"], "instance": record.get("instance"),
                      "selection": record.get("selection"), "dropped": record["dropped"],
                      "filled": record["filled"], "focus": focus})

    if not order:
        reason, suggestions = explain_empty_day(city, trip, ctx, day_index, used | blocked,
                                                set(tctx.blocked), log, bool(candidates), rate)
        return DayPlan(index=day_index, date=day_date, depart=trip.day_start, visits=[], return_leg=None,
                       transport_rate=rate, empty_reason=reason, suggestions=suggestions,
                       day_start=trip.day_start, day_end=trip.day_end, shop_spend=trip.shop_spend)

    schedule = simulate(order, ctx, scores, detailed=True)
    day = DayPlan(index=day_index, date=day_date, depart=schedule.depart, visits=schedule.visits,
                  return_leg=schedule.return_leg, transport_rate=rate, branch=record["branch"],
                  meals=schedule.meals, timeline=schedule.timeline, day_start=trip.day_start,
                  day_end=trip.day_end, shop_spend=trip.shop_spend,
                  focus=focus if city.multi_city else "",
                  filled=record["filled"])
    day.free_time_notes = explain_free_time(city, trip, ctx, day, candidates, order, spend_ok, log, day_index)
    return day


def route_focus(city, order):
    """The city (or cities) a day's stops are in, in the trip's city order: "Mathura" or "Mathura & Vrindavan"."""
    visited = {city.city_of[a] for a in order}
    names = [c["name"] for c in city.cities if c["slug"] in visited]
    return group_name(names) if names else city.name


# ------------------------------------------------------------------------------ whole trip

def plan_trip(city, trip, transport_rate, trace=None, validate=True):
    """Plan every day of the trip. Deterministic: the same trip always gives the same plan."""
    started = time.perf_counter()
    tctx = trip_context(city, trip)
    used, days = set(), []
    log = defaultdict(list)                  # attraction id -> [(day, code, detail)]

    for index, day_date in enumerate(trip.dates(), start=1):
        day = plan_day(city, trip, tctx, index, day_date, used, log, transport_rate, trace)
        used.update(v.attraction.id for v in day.visits)
        days.append(day)

    itinerary = Itinerary(trip=trip, city_name=city.name, start_place=city.place(trip.start), days=days,
                          skipped=explain_skipped(city, used, tctx.blocked, log),
                          cities=[{"slug": c["slug"], "name": c["name"]} for c in city.cities],
                          estimated_links=list(city.estimated_links),
                          interest_notes=interest_notes(city, trip, tctx))
    itinerary.runtime_ms = (time.perf_counter() - started) * 1000
    if validate:
        from services.validator import check_itinerary          # imported here: the validator is independent
        itinerary.violations = check_itinerary(itinerary, city, transport_rate)
    itinerary.versions = versioning.versions(city, itinerary)
    return itinerary


# ------------------------------------------------------------------------------ explanations

SKIP_PRIORITY = ["excluded", "no_road", "opt_in", "interest", "unreachable", "dropped", "not_selected",
                 "does_not_fit", "over_budget", "closed"]


def explain_skipped(city, used, blocked, log):
    """One clear reason for every attraction that is not in the plan."""
    skipped = []
    for aid in sorted(city.attractions):
        if aid in used:
            continue
        attraction = city.attractions[aid]
        if aid in blocked:
            code, reason = blocked[aid]
            skipped.append(Skipped(attraction, code, reason))
            continue
        entries = log.get(aid, [])
        codes = {code for _, code, _ in entries}
        details = [f"Day {day}: {detail}" for day, _, detail in entries]
        code = next((c for c in SKIP_PRIORITY if c in codes), "not_selected")
        if code == "closed":
            days = sorted({detail.removeprefix("Closed on ") for _, c, detail in entries if c == "closed"},
                          key=WEEKDAY_LONG.index)
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


def explain_free_time(city, trip, ctx, day, candidates, order, spend_ok, log, day_index):
    """Why does the day end early? Only said when at least EXPLAIN_FREE_MIN minutes are unused at the end."""
    free_end = day.free_after_min
    if free_end < config.EXPLAIN_FREE_MIN:
        return []
    notes = [f"{fmt_duration(free_end)} free after {fmt_hhmm(day.end_time)}."]
    reasons = defaultdict(list)
    for aid in candidates:
        if aid in order:
            continue
        name = city.attractions[aid].name
        if not spend_ok(order + [aid]):
            reasons["budget"].append(name)
            continue
        attempt = simulate(order + [aid], ctx)
        text = " ".join(attempt.violations)
        if "too late to fit" in text or "closed" in text:
            closes = city.attractions[aid].closing_time_on(ctx.weekday)
            reasons["closes"].append(f"{name} (closes {fmt_hhmm(closes)})")
        elif "cannot start by" in text:
            reasons["meal"].append(name)
        else:
            reasons["time"].append(name)
    for aid, entries in log.items():
        for d, code, _ in entries:
            if d == day_index and code in ("closed", "over_budget", "does_not_fit"):
                reasons[code].append(city.attractions[aid].name)

    def listed(names, limit=3):
        return ", ".join(names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")

    if reasons["closes"]:
        notes.append(f"Too late for {listed(reasons['closes'])} after your other stops.")
    if reasons["time"]:
        notes.append(f"Adding {listed(reasons['time'])} would bring you back after {fmt_hhmm(trip.day_end)}.")
    if reasons["meal"]:
        notes.append(f"{listed(reasons['meal'])} would clash with your meal breaks.")
    if reasons["budget"] or reasons["over_budget"]:
        notes.append(f"Over your daily budget: {listed(reasons['budget'] + reasons['over_budget'])}.")
    if reasons["closed"]:
        notes.append(f"Closed on {WEEKDAY_LONG[ctx.weekday]}: {listed(reasons['closed'])}.")
    if reasons["does_not_fit"]:
        notes.append(f"Opening hours don't fit your day: {listed(reasons['does_not_fit'])}.")
    if len(notes) == 1:
        remaining = [a for a in city.attractions if a not in order and a not in candidates]
        notes.append("Nothing else that fits your settings is left to plan"
                     + (" — the rest is planned on other days, excluded or filtered out." if remaining else "."))
    return notes


def explain_empty_day(city, trip, ctx, day_index, unavailable, blocked, log, had_candidates, rate):
    """Specific reason + one-click suggestions for a day with no stops."""
    weekday = WEEKDAY_LONG[ctx.weekday]
    remaining = [aid for aid in city.attractions if aid not in unavailable]
    today = {aid: [code for d, code, _ in log.get(aid, []) if d == day_index] for aid in remaining}
    # Places with no road route can never be planned, so they don't count as "remaining".
    unreachable = [aid for aid, codes in today.items() if codes and codes[0] == "unreachable"]
    remaining = [aid for aid in remaining if aid not in unreachable]
    suggestions = []
    if not remaining:
        reason = f"Every reachable attraction in {city.name} is already in your plan" + \
                 (" or left out by your settings." if blocked else ".")
        if day_index > 1:
            suggestions.append({"label": f"Make it a {day_index - 1}-day trip",
                                "query": trip.to_query(days=day_index - 1)})
        return reason, suggestions

    codes = [today[aid][0] for aid in remaining if today[aid]]
    if had_candidates:
        reason = "The selected stops could not be scheduled around their opening hours, meals and your budget."
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
        blocked_costs = [own_cost(city, trip, a)
                         + (round_trip_transport(city, ctx.start_id, a, rate) if trip.include_transport else 0)
                         for a, c in today.items() if c and c[0] == "over_budget"]
        new_budget = int(math.ceil(min(blocked_costs) / 10) * 10)
        suggestions.append({"label": f"Raise budget to ₹{new_budget}", "query": trip.to_query(budget=new_budget)})
    if "does_not_fit" in codes or had_candidates:
        later = min(trip.day_end + 120, 23 * 60 + 59)
        if later > trip.day_end:
            suggestions.append({"label": f"End the day at {fmt_hhmm(later)}", "query": trip.to_query(day_end=later)})
    if "closed" in codes:
        suggestions.append({"label": "Start one day later",
                            "query": trip.to_query(start_date=trip.start_date + timedelta(days=1))})
    return reason, suggestions
