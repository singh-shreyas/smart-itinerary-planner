"""The itinerary pipeline: how the algorithms work together.

Once per city (or group of nearby cities; cached, see city_data.py):
    adjacency list -> Dijkstra from every place -> raw travel table
    -> planning table (each shortest time rounded UP to 10 minutes)

Once per trip:
    score every attraction (rating or neutral prior, popularity, interest match)
    trip-level rules: excluded by you / access that cannot be timed / "only
    matching interests" / food and shopping places only when you ask for them

Access: a trek, ferry or walk is part of the travel graph (city_data.py), so
the trek to Kedarnath is inside the travel minutes of that stop's legs. It
counts in the knapsack weight (cheapest exit), in the routing and in the
timeline, so a place behind an 8-hour trek can never be treated like a
30-minute stop. A place whose access has no known duration is never given a
guessed one: it is left out with its own reason.

For each day, in date order:
    1. FILTER    keep attractions not yet planned, open on this weekday,
                 reachable from and back to the start, and able to fit in the
                 day on their own (meals included).
                 Every rejection is recorded with its reason.
    2. SELECT    one 0/1 knapsack instance over the day's time, solved by the
                 chosen strategy:  dp (max total value, exact) or greedy (value
                 density, fast).
                 Each stop's time weight = visit + pace buffer + its cheapest
                 way to leave (a lower bound on real travel); the capacity is
                 the day minus the shortest first ride, the unavoidable extra
                 for the ride home, and the meal breaks. So no set that truly
                 fits is ever thrown away.
    3. ROUTE     travel-first:  Nearest Neighbour -> 2-opt
                 window-first:  closing-time order + cheapest feasible insertion -> 2-opt
                 keep the feasible branch with less travel.
    4. REPAIR    if no branch is feasible, the weakest selected stop
                 (min-heap, by the strategy's own value per estimated minute)
                 leaves today's pool and the same
                 selector runs again. The pool shrinks, so the loop always ends.
    5. FILL      leftover candidates are inserted at their cheapest feasible
                 position while they still fit, so a longer day is really used.
    6. GROUP     multi-city trips: steps 2-5 run on each city's candidates alone
                 and on all of them together; the day keeps the best result by
                 the strategy's objective (so you do not zig-zag between cities).
    7. COMMIT    build the timeline (visits, meals, legs), explain unused time.

Then the itinerary MODE spreads the chosen places over the trip
(services/distribution.py): the places of the plan above -- or the places the
traveller picked -- are re-assigned to days by Most Optimized (fewest days),
Evenly Distributed (closest to an even split) or Suggested (comfortable days).
A day keeps the route found above whenever its set of stops is unchanged.

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
from algorithms.nearest_neighbor import nearest_neighbor_route
from algorithms.scoring import attraction_score, matches_interests
from algorithms.sorting import merge_sort
from algorithms.tour import tour_cost
from algorithms.two_opt import two_opt
from services import versioning
from services.city_data import group_name
from services.distribution import distribute, explain as explain_mode
from services.i18n import gettext as _, ngettext
from services.models import DayPlan, Itinerary, Skipped
from services.scheduler import DayContext, simulate
from services.timeutil import WEEKDAY_LONG, WEEKDAY_SHORT, fmt_duration, fmt_hhmm

SCORE_WEIGHTS = (config.W_RATING, config.W_POPULARITY, config.W_INTEREST)
SELECTORS = {"dp": dp_select, "greedy": greedy_select}


@dataclass
class KnapsackInstance:
    """The integer knapsack handed to the selector for one day."""
    items: list                 # [Item(id, score, weight_units)]
    time_cap: int               # T, in time units
    time_unit: int              # minutes per time unit
    weight_minutes: dict        # id -> estimated minutes (visit + buffer + cheapest exit)
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
            blocked[aid] = ("excluded", _("You excluded it from this trip."))
        elif not a.timed:
            blocked[aid] = ("access_unknown", _("{note} Verify access locally before you go.",
                                                note=_(a.access_note) if a.access_note else
                                                _("How to reach it is not in our data.")))
        elif trip.interest_mode == "only" and trip.interests and not matches_interests(a.categories, trip.interests, parents):
            blocked[aid] = ("interest", _("Doesn't match your interests (you chose only matching places)."))
        elif a.is_food_or_shopping_only and not matches_interests(a.categories, opt_in_interests, parents):
            blocked[aid] = ("opt_in", _("Food and shopping places are planned only when you pick a matching "
                                        "food or shopping interest."))

    venues = []
    if trip.meals and trip.food_venues:
        styles = set(trip.venue_styles)
        for aid in sorted(city.attractions):
            a = city.attractions[aid]
            if not a.is_food or a.special_access or aid in excluded:
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
                    if a.timed and tctx.blocked.get(aid, ("",))[0] != "excluded"
                    and matches_interests(a.categories, [interest], tctx.parents)]
        label = _(names.get(interest, interest))
        if not matching:
            notes.append({"interest": interest, "count": 0,
                          "text": _("No “{label}” places in our data for {city}, so this interest cannot change "
                                    "your plan.", label=label, city=city.name)})
        elif len(matching) <= 2:
            listed = ", ".join(a.name for a in matching)
            notes.append({"interest": interest, "count": len(matching),
                          "text": ngettext("Only {n} “{label}” place in our data for {city}: {listed}.",
                                           "Only {n} “{label}” places in our data for {city}: {listed}.",
                                           len(matching), label=label, city=city.name, listed=listed)})
    return notes


# ------------------------------------------------------------------------------ step 1: filter

def day_context(city, trip, day_date, tctx=None, start_id=None, end_id=None):
    """The planning problem of one day. start_id / end_id: where the day starts and where the
    traveller sleeps that night (default: the trip's stay area, both ways)."""
    meals = tuple(sorted((m for m in trip.meals if m.needed(trip.day_start, trip.day_end)),
                         key=lambda m: (m.earliest, m.kind)))
    start = start_id if start_id is not None else city.place(trip.start).id
    return DayContext(city=city, weekday=day_date.weekday(), day_start=trip.day_start, day_end=trip.day_end,
                      start_id=start, buffer=config.PACES[trip.pace]["buffer"],
                      meals=meals, venues=tctx.venues if tctx else (),
                      durations=tctx.durations if tctx else {},
                      end_id=end_id if end_id not in (None, start) else None)


def filter_candidates(city, trip, ctx, unavailable, log, day_index):
    """Attractions that could be visited today on their own. Rejections go into `log`."""
    start = ctx.start_id
    weekday = _(WEEKDAY_LONG[ctx.weekday])
    candidates = []
    for aid in sorted(city.attractions):
        if aid in unavailable:
            continue
        attraction = city.attractions[aid]
        if city.dist[start][aid] == math.inf or city.dist[aid][ctx.end] == math.inf:
            log[aid].append((day_index, "unreachable", _("No route between it and your stay area")))
            continue
        if not attraction.windows_on(ctx.weekday):
            log[aid].append((day_index, "closed", _("Closed on {day}", day=weekday)))
            continue
        alone = simulate([aid], ctx)
        if not alone.feasible:
            meals = _(" and your meal breaks") if ctx.meals else ""
            trip_parts = city.segments(start, aid) + city.segments(aid, ctx.end)
            access = sum(p.minutes for p in trip_parts if not p.is_road)
            modes = "/".join(dict.fromkeys(p.mode for p in trip_parts if not p.is_road))
            modes = "/".join(_(m) for m in modes.split("/")) if modes else modes
            extra = _(" (the round trip includes {access} by {modes}, {total} in all)", access=fmt_duration(access),
                      modes=modes, total=fmt_duration(city.plan[start][aid] + city.plan[aid][ctx.end])) if access else ""
            log[aid].append((day_index, "does_not_fit",
                             _("Open {hours} on {day}; a {visit} visit plus the round trip{extra}{meals} doesn't fit "
                               "{start}–{end}", hours=attraction.hours_label(ctx.weekday),
                               day=_(WEEKDAY_SHORT[ctx.weekday]), visit=fmt_duration(ctx.duration(aid)), extra=extra,
                               meals=meals, start=fmt_hhmm(trip.day_start), end=fmt_hhmm(trip.day_end))))
            continue
        candidates.append(aid)
    return candidates


# ------------------------------------------------------------------------------ step 2: select

def knapsack_instance(city, trip, ctx, candidates, scores):
    """Turn today's candidates into an integer 0/1 knapsack over time units."""
    plan, start = city.plan, ctx.start_id
    nodes = candidates + [n for n in dict.fromkeys((start, ctx.end)) if n not in candidates]
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
    return_extra = max(0, min(plan[i][ctx.end] - cheapest_exit(plan, i) for i in candidates))
    reserved = {"first ride": first_ride, "ride home (extra)": return_extra, "meals": ctx.meal_minutes}
    time_cap = max(0, math.floor((ctx.day_end - ctx.day_start - sum(reserved.values())) / unit))

    items, weight_minutes = [], {}
    for i in candidates:
        # Every route leaves each stop exactly once, so its cheapest exit is a lower bound on real travel.
        weight_minutes[i] = ctx.duration(i) + ctx.buffer + cheapest_exit(plan, i)
        weight = math.ceil(weight_minutes[i] / unit)                    # rounded UP
        items.append(Item(id=i, score=scores[i], weight=weight))
    return KnapsackInstance(items, time_cap, unit, weight_minutes, reserved)


# ------------------------------------------------------------------------------ step 3: route

def route_branches(stops, ctx):
    """Both routing branches for a set of stops. Returns {branch: (route, feasible)}.

    Orders are compared on RAW travel minutes (finer than the 10-minute planning
    values); feasibility is always checked on the real, rounded timeline.
    """
    city, start, dist = ctx.city, ctx.start_id, ctx.route_dist

    def feasible(route):
        return simulate(route, ctx).feasible

    branches = {}
    # Travel-first: Nearest Neighbour, then 2-opt on travel time only.
    nn = nearest_neighbor_route(start, stops, dist)
    route, _gain = two_opt(start, nn, dist)
    if not feasible(route) and feasible(nn):
        route, _gain = two_opt(start, nn, dist, is_feasible=feasible)     # keep the windows NN already met
    branches["travel-first"] = (route, feasible(route))

    # Window-first: stops taken in closing-time order (Activity Selection rule), each inserted where it
    # keeps every window satisfied; then a 2-opt that only accepts feasible moves.
    closing = {s: city.attractions[s].closing_time_on(ctx.weekday) for s in stops}
    route, unplaced = deadline_insertion_route(start, stops, closing, dist, feasible)
    if unplaced:
        branches["window-first"] = (route + unplaced, False)
    else:
        route, _gain = two_opt(start, route, dist, is_feasible=feasible)
        branches["window-first"] = (route, True)
    return branches


def best_route(stops, ctx):
    """The feasible branch with less travel (ties go to travel-first), or None."""
    start, dist = ctx.start_id, ctx.route_dist
    options = [(name, route) for name, (route, ok) in route_branches(stops, ctx).items() if ok]
    if not options:
        return None
    name, route = min(options, key=lambda option: tour_cost(start, option[1], dist))
    return route, name


# ------------------------------------------------------------------------------ steps 2-5 on one pool

def objective_key(strategy, route, scores, travel):
    """Smaller is better: most value, then most stops, then less travel."""
    value = sum(scores[a] for a in route)
    return (-value, -len(route), travel)


def weakest_key(strategy, aid, scores, per_unit):
    """Repair key (min-heap): the stop giving the least value per estimated minute."""
    return (scores[aid] / per_unit, scores[aid], aid)


def fill_route(route, pool, ctx, scores, strategy):
    """Step 5: try every leftover candidate at its cheapest feasible position (deterministic order)."""
    start, dist = ctx.start_id, ctx.route_dist

    def feasible(candidate):
        return simulate(candidate, ctx).feasible

    leftovers = [a for a in pool if a not in route]
    leftovers = merge_sort(leftovers, key=lambda a: (-scores[a], a))      # most valuable first
    added = []
    for aid in leftovers:
        inserted = cheapest_feasible_insertion(start, route, aid, dist, feasible)
        if inserted is not None:
            route = inserted
            added.append(aid)
    if added:
        route, _gain = two_opt(start, route, dist, is_feasible=feasible)
    return route, added


def solve_pool(city, trip, ctx, pool, scores):
    """Select with the trip's strategy, route, repair, then fill. Returns a record dict."""
    selector = SELECTORS[trip.strategy]
    candidates = list(pool)
    dropped = []
    first_instance = first_selection = None
    route, branch = [], ""
    while candidates:
        instance = knapsack_instance(city, trip, ctx, candidates, scores)
        selection = selector(instance.items, instance.time_cap)
        if first_instance is None:
            first_instance, first_selection = instance, selection
        if not selection.chosen:
            break
        found = best_route(selection.chosen, ctx)
        if found is not None:
            route, branch = found
            break
        # Timeline failed: the weakest value per estimated minute leaves.
        heap = [weakest_key(trip.strategy, a, scores, instance.weight_minutes[a]) for a in selection.chosen]
        heapq.heapify(heap)                          # min-heap: weakest stop on top
        victim = heapq.heappop(heap)[-1]
        candidates.remove(victim)
        dropped.append(victim)
    added = []
    if config.FILL_STEP:
        route, added = fill_route(route, pool, ctx, scores, trip.strategy)
        if added and not branch:
            branch = "insertion"
    return {"route": route, "branch": branch, "instance": first_instance, "selection": first_selection,
            "dropped": [a for a in dropped if a not in route], "filled": added, "pool": list(pool)}


# ------------------------------------------------------------------------------ one day

def plan_day(city, trip, tctx, day_index, day_date, used, log, trace=None, ctx=None, allowed=None):
    """Steps 1-5 for one day. ctx: a given day (e.g. a transfer day between two stays);
    allowed: only these attractions may be chosen (one city of a multi-city journey)."""
    ctx = ctx or day_context(city, trip, day_date, tctx)
    blocked = set(tctx.blocked)
    outside = set(city.attractions) - set(allowed) if allowed is not None else set()
    candidates = filter_candidates(city, trip, ctx, used | blocked | outside, log, day_index)
    scores = tctx.scores

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
        record = solve_pool(city, trip, ctx, pool, scores)
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
                         _("Selected, then removed because the day's timeline did not work out")))
    for aid in candidates:
        if aid in chosen or aid in record["dropped"]:
            continue
        if aid in record["pool"]:
            log[aid].append((day_index, "not_selected",
                             _("Other stops gave more value for the time (score {score})", score=scores[aid])))
        else:
            log[aid].append((day_index, "not_selected", _("Day {n} was planned around {focus}", n=day_index, focus=focus)))

    if trace is not None:
        trace.append({"day": day_index, "ctx": ctx, "candidates": candidates, "order": order,
                      "branch": record["branch"], "instance": record.get("instance"),
                      "selection": record.get("selection"), "dropped": record["dropped"],
                      "filled": record["filled"], "focus": focus})

    if not order:
        reason, suggestions = explain_empty_day(city, trip, ctx, day_index, used | blocked,
                                                set(tctx.blocked), log, bool(candidates))
        return DayPlan(index=day_index, date=day_date, depart=trip.day_start, visits=[], return_leg=None,
                       empty_reason=reason, suggestions=suggestions,
                       day_start=trip.day_start, day_end=trip.day_end,
                       start_place=city.places[ctx.start_id], end_place=city.places[ctx.end])

    schedule = simulate(order, ctx, scores, detailed=True)
    day = DayPlan(index=day_index, date=day_date, depart=schedule.depart, visits=schedule.visits,
                  return_leg=schedule.return_leg, branch=record["branch"],
                  meals=schedule.meals, timeline=schedule.timeline, day_start=trip.day_start,
                  day_end=trip.day_end,
                  focus=focus if city.multi_city else "",
                  filled=record["filled"], start_place=city.places[ctx.start_id], end_place=city.places[ctx.end])
    day.free_time_notes = explain_free_time(city, trip, ctx, day, candidates, order, log, day_index)
    return day


def route_focus(city, order):
    """The city (or cities) a day's stops are in, in the trip's city order: "Mathura" or "Mathura & Vrindavan"."""
    visited = {city.city_of[a] for a in order}
    names = [c["name"] for c in city.cities if c["slug"] in visited]
    return group_name(names) if names else city.name


# ------------------------------------------------------------------------------ whole trip

def plan_trip(city, trip, trace=None, validate=True):
    """Plan every day of the trip. Deterministic: the same trip always gives the same plan."""
    started = time.perf_counter()
    tctx = trip_context(city, trip)
    log = defaultdict(list)                  # attraction id -> [(day, code, detail)]
    dates = trip.dates()

    from services import journey                               # imported here: journey builds on this module
    if journey.needs_journey(city, trip):
        return _plan_journey_trip(city, trip, tctx, log, started, validate)
    contexts = {i: day_context(city, trip, d, tctx) for i, d in enumerate(dates)}

    # 1. What to visit: the traveller's own list, or the strategy's day-by-day plan.
    picked = [city.attraction_by_slug(s).id for s in trip.places] if trip.places else None
    pipeline, known, seed = [], {}, None
    if picked is None:
        used = set()
        for index, day_date in enumerate(dates, start=1):
            day = plan_day(city, trip, tctx, index, day_date, used, log, trace)
            used.update(v.attraction.id for v in day.visits)
            pipeline.append(day)
        selected = [v.attraction.id for d in pipeline for v in d.visits]
        known = {(i, tuple(v.attraction.id for v in d.visits)): ([v.attraction.id for v in d.visits], d.branch)
                 for i, d in enumerate(pipeline) if d.visits}
        seed = {v.attraction.id: i for i, d in enumerate(pipeline) for v in d.visits}
        blocked = dict(tctx.blocked)
    else:
        # A place you pick is planned even if a filter would have left it out -- unless its
        # access cannot be timed. Everything you did not pick is simply "not picked".
        blocked = {a: r for a, r in tctx.blocked.items() if r[0] == "access_unknown" and a in picked}
        selected = [a for a in picked if a not in blocked]

    # 2. How to spread it: the itinerary mode.
    dist = distribute(trip, contexts, selected, tctx.scores, best_route, known, seed)
    days = []
    for i, day_date in enumerate(dates):
        order = dist.days[i]
        same = picked is None and tuple(v.attraction.id for v in pipeline[i].visits) == tuple(order)
        if same:
            days.append(pipeline[i])
        else:
            days.append(build_day(city, trip, tctx, contexts[i], i + 1, day_date, order, dist.branches[i],
                                  dist, len(selected), pipeline[i] if pipeline else None))
    used = {v.attraction.id for d in days for v in d.visits}
    for aid in dist.unplaced:
        log[aid].append((0, "unscheduled", dist.reasons.get(aid, _("could not be scheduled"))))

    if picked is not None:
        chosen = set(picked)
        for aid in city.attractions:
            if aid not in chosen:
                blocked.setdefault(aid, ("not_picked", _("Not one of the places you picked.")))

    itinerary = Itinerary(trip=trip, city_name=city.name, start_place=city.place(trip.start), days=days,
                          skipped=explain_skipped(city, used, blocked, log, days),
                          cities=[{"slug": c["slug"], "name": c["name"]} for c in city.cities],
                          estimated_links=list(city.estimated_links),
                          interest_notes=interest_notes(city, trip, tctx))
    itinerary.selected = list(picked) if picked is not None else selected
    itinerary.distribution = dist
    itinerary.mode_notes = explain_mode(dist, days, len(itinerary.selected), trip.days, picked is not None)
    itinerary.runtime_ms = (time.perf_counter() - started) * 1000
    if validate:
        from services.validator import check_itinerary          # imported here: the validator is independent
        itinerary.violations = check_itinerary(itinerary, city)
    itinerary.versions = versioning.versions(city, itinerary)
    return itinerary


def _plan_journey_trip(city, trip, tctx, log, started, validate):
    """A multi-city trip whose overnight stay moves with the traveller (services/journey.py)."""
    from services import journey
    days, selected, unplaced, summary, _stops = journey.plan_journey(
        city, trip, tctx, log, tctx.scores, best_route, day_context, plan_day, build_day)
    used = {v.attraction.id for d in days for v in d.visits}
    blocked = dict(tctx.blocked)
    if trip.places:
        picked = {city.attraction_by_slug(s).id for s in trip.places}
        blocked = {a: r for a, r in tctx.blocked.items() if r[0] == "access_unknown" and a in picked}
        for aid in city.attractions:
            if aid not in picked:
                blocked.setdefault(aid, ("not_picked", _("Not one of the places you picked.")))
        selected = sorted(picked)
    for aid, reason in unplaced.items():
        log[aid].append((0, "unscheduled", reason))
    itinerary = journey.build_itinerary(city, trip, days, explain_skipped(city, used, blocked, log, days), summary,
                                        journey.journey_notes(trip, summary, days, selected, unplaced))
    itinerary.selected = selected
    itinerary.interest_notes = interest_notes(city, trip, tctx)
    itinerary.runtime_ms = (time.perf_counter() - started) * 1000
    if validate:
        from services.validator import check_itinerary
        itinerary.violations = check_itinerary(itinerary, city)
    itinerary.versions = versioning.versions(city, itinerary)
    return itinerary


def build_day(city, trip, tctx, ctx, index, day_date, order, branch, dist, selected_count, pipeline_day=None):
    """A DayPlan for a day whose stops the itinerary mode chose."""
    active = sum(1 for d in dist.days if d)
    stays = {"start_place": city.places[ctx.start_id], "end_place": city.places[ctx.end]}
    if not order and ctx.moves:                                        # a transfer with nothing to see on the way
        schedule = simulate([], ctx, tctx.scores, detailed=True)
        return DayPlan(index=index, date=day_date, depart=schedule.depart, visits=[], return_leg=schedule.return_leg,
                       meals=schedule.meals, timeline=schedule.timeline, day_start=trip.day_start,
                       day_end=trip.day_end, **stays)
    if not order:
        if pipeline_day is not None and not pipeline_day.visits:      # nothing was plannable here before either
            return pipeline_day
        if dist.unplaced:
            reason = _("None of your remaining selected places can be scheduled on this day.")
        elif dist.mode == "optimized":
            reason = ngettext("Free day: Most Optimized completes your {places} places in {n} day.",
                              "Free day: Most Optimized completes your {places} places in {n} days.",
                              active, places=selected_count)
        elif dist.mode == "evenly":
            reason = _("Free day: {places} places over {days} days means one place on {places} of the days.",
                       places=selected_count, days=trip.days) if selected_count < trip.days else \
                _("Free day: no place could be scheduled here without breaking a constraint.")
        else:
            reason = ngettext("Free day: the suggested plan uses {n} day so that each one stays comfortable.",
                              "Free day: the suggested plan uses {n} days so that each one stays comfortable.",
                              active)
        return DayPlan(index=index, date=day_date, depart=trip.day_start, visits=[], return_leg=None,
                       empty_reason=reason, day_start=trip.day_start, day_end=trip.day_end, is_free=not dist.unplaced,
                       **stays)
    schedule = simulate(list(order), ctx, tctx.scores, detailed=True)
    day = DayPlan(index=index, date=day_date, depart=schedule.depart, visits=schedule.visits,
                  return_leg=schedule.return_leg, branch=branch, meals=schedule.meals, timeline=schedule.timeline,
                  day_start=trip.day_start, day_end=trip.day_end,
                  focus=route_focus(city, order) if city.multi_city else "", **stays)
    free = day.free_after_min
    if free >= config.EXPLAIN_FREE_MIN:
        notes = [_("{time} free after {end}.", time=fmt_duration(free), end=fmt_hhmm(day.end_time))]
        notes.append(_({"evenly": "Evenly Distributed keeps each day to its share of the places, so this one is not filled up.",
                        "suggested": "The suggested plan keeps days comfortable rather than filling every hour.",
                        "optimized": "Your other places are on other days; none of them fits here as well."}[dist.mode]))
        day.free_time_notes = notes
    return day


# ------------------------------------------------------------------------------ explanations

SKIP_PRIORITY = ["excluded", "access_unknown", "not_picked", "unscheduled", "opt_in", "interest", "unreachable", "dropped", "not_selected",
                 "does_not_fit", "closed"]


def roomiest_day(days):
    """The day with the most time left after its plan ends (for 'you could fit it here' hints)."""
    spare = [(d.free_after_min if d.visits else d.window_min, -d.index, d) for d in days]
    best = max(spare, default=None, key=lambda t: (t[0], t[1]))
    return best[2] if best and best[0] >= 60 else None


def explain_skipped(city, used, blocked, log, days=()):
    """One clear reason for every attraction that is not in the plan."""
    skipped = []
    room = roomiest_day(days)
    for aid in sorted(city.attractions):
        if aid in used:
            continue
        attraction = city.attractions[aid]
        if aid in blocked:
            code, reason = blocked[aid]
            details = []
            if code == "access_unknown" and room is not None:
                free = room.free_after_min if room.visits else room.window_min
                when = _("after {time}", time=fmt_hhmm(room.end_time)) if room.visits else _("(no stops planned)")
                details.append(_("Day {n} has {time} free {when} if you arrange it yourself", n=room.index,
                                 time=fmt_duration(free), when=when))
            skipped.append(Skipped(attraction, code, reason, details))
            continue
        entries = log.get(aid, [])
        codes = {code for _d, code, _detail in entries}
        details = [_("Day {n}: {detail}", n=day, detail=detail) for day, _c, detail in entries]
        code = next((c for c in SKIP_PRIORITY if c in codes), "not_selected")
        if code == "closed":
            closed_on = {_("Closed on {day}", day=_(w)): w for w in WEEKDAY_LONG}
            days = sorted({closed_on[detail] for _d, c, detail in entries if c == "closed"}, key=WEEKDAY_LONG.index)
            reason = _("Closed on {days} — every day of your trip.", days=", ".join(_(d) for d in days))
        elif code == "unreachable":
            reason = _("No route to it from your stay area in our travel graph.")
        elif code == "does_not_fit":
            reason = _("Its opening hours don't fit inside your daily time window.")
        elif code == "unscheduled":
            reason = _("You selected it, but it could not be scheduled: {why}.",
                       why=next(d for _d, c, d in entries if c == "unscheduled"))
            details = [_("Day {n}: {detail}", n=day, detail=detail) for day, _c, detail in entries if day != 0]
        elif code == "dropped":
            reason = _("Selected, but removed so the day's timeline could work.")
        else:
            reason = _("Other attractions gave more value for the time you had.")
        skipped.append(Skipped(attraction, code, reason, details))
    return skipped


def explain_free_time(city, trip, ctx, day, candidates, order, log, day_index):
    """Why does the day end early? Only said when at least EXPLAIN_FREE_MIN minutes are unused at the end."""
    free_end = day.free_after_min
    if free_end < config.EXPLAIN_FREE_MIN:
        return []
    notes = [_("{time} free after {end}.", time=fmt_duration(free_end), end=fmt_hhmm(day.end_time))]
    reasons = defaultdict(list)
    for aid in candidates:
        if aid in order:
            continue
        name = city.attractions[aid].name
        attempt = simulate(order + [aid], ctx)
        text = " ".join(attempt.violations)
        if "too late to fit" in text or "closed" in text:
            closes = city.attractions[aid].closing_time_on(ctx.weekday)
            reasons["closes"].append(_("{name} (closes {time})", name=name, time=fmt_hhmm(closes)))
        elif "cannot start by" in text:
            reasons["meal"].append(name)
        else:
            reasons["time"].append(name)
    for aid, entries in log.items():
        for d, code, _detail in entries:
            if d == day_index and code in ("closed", "does_not_fit"):
                reasons[code].append(city.attractions[aid].name)

    def listed(names, limit=3):
        return ", ".join(names[:limit]) + (_(" and {n} more", n=len(names) - limit) if len(names) > limit else "")

    if reasons["closes"]:
        notes.append(_("Too late for {names} after your other stops.", names=listed(reasons["closes"])))
    if reasons["time"]:
        notes.append(_("Adding {names} would bring you back after {time}.", names=listed(reasons["time"]),
                       time=fmt_hhmm(trip.day_end)))
    if reasons["meal"]:
        notes.append(_("{names} would clash with your meal breaks.", names=listed(reasons["meal"])))
    if reasons["closed"]:
        notes.append(_("Closed on {day}: {names}.", day=_(WEEKDAY_LONG[ctx.weekday]), names=listed(reasons["closed"])))
    if reasons["does_not_fit"]:
        notes.append(_("Opening hours don't fit your day: {names}.", names=listed(reasons["does_not_fit"])))
    if len(notes) == 1:
        remaining = [a for a in city.attractions if a not in order and a not in candidates]
        notes.append(_("Nothing else that fits your settings is left to plan — the rest is planned on other days, "
                       "excluded or filtered out.") if remaining else _("Nothing else that fits your settings is left to plan."))
    return notes


def explain_empty_day(city, trip, ctx, day_index, unavailable, blocked, log, had_candidates):
    """Specific reason + one-click suggestions for a day with no stops."""
    weekday = _(WEEKDAY_LONG[ctx.weekday])
    remaining = [aid for aid in city.attractions if aid not in unavailable]
    today = {aid: [code for d, code, _detail in log.get(aid, []) if d == day_index] for aid in remaining}
    # Places with no road route can never be planned, so they don't count as "remaining".
    unreachable = [aid for aid, codes in today.items() if codes and codes[0] == "unreachable"]
    remaining = [aid for aid in remaining if aid not in unreachable]
    suggestions = []
    if not remaining:
        reason = (_("Every reachable attraction in {city} is already in your plan or left out by your settings.",
                    city=city.name) if blocked else
                  _("Every reachable attraction in {city} is already in your plan.", city=city.name))
        if day_index > 1:
            suggestions.append({"label": _("Make it a {n}-day trip", n=day_index - 1),
                                "query": trip.to_query(days=day_index - 1)})
        return reason, suggestions

    codes = [today[aid][0] for aid in remaining if today[aid]]
    if had_candidates:
        reason = _("The selected stops could not be scheduled around their opening hours and meals.")
    elif codes and all(c == "closed" for c in codes):
        reason = _("All {n} remaining attractions are closed on {day}.", n=len(remaining), day=weekday)
    elif codes and all(c == "does_not_fit" for c in codes):
        reason = _("None of the remaining attractions fit inside {start}–{end} on {day}.",
                   start=fmt_hhmm(trip.day_start), end=fmt_hhmm(trip.day_end), day=weekday)
    else:
        parts = []
        if "closed" in codes:
            parts.append(_("{n} closed on {day}", n=codes.count("closed"), day=weekday))
        if "does_not_fit" in codes:
            parts.append(_("{n} can't fit in {start}–{end}", n=codes.count("does_not_fit"),
                           start=fmt_hhmm(trip.day_start), end=fmt_hhmm(trip.day_end)))
        reason = _("Of the {n} remaining attractions: {parts}.", n=len(remaining), parts="; ".join(parts))

    if "does_not_fit" in codes or had_candidates:
        later = min(trip.day_end + 120, 23 * 60 + 59)
        if later > trip.day_end:
            suggestions.append({"label": _("End the day at {time}", time=fmt_hhmm(later)),
                                "query": trip.to_query(day_end=later)})
    if "closed" in codes:
        suggestions.append({"label": _("Start one day later"),
                            "query": trip.to_query(start_date=trip.start_date + timedelta(days=1))})
    return reason, suggestions
