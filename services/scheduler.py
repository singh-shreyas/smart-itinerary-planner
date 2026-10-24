"""Simulate one day's timeline for a given visiting order (meals included).

This is the "truth" check every candidate route goes through:

    leave the start point at day_start
    for each stop in order:
        (take any meal that is due -- see below)
        arrive = previous leave + planned travel (shortest path, rounded up to 10 min)
        start  = earliest moment >= arrive inside one of today's opening windows,
                 no later than the last entry, with start + visit <= closing time
        end    = start + visit duration
        leave  = end + pace buffer
    (take any meal still due before heading back)
    ride back to the start point
    (a meal whose window has not opened yet is taken near the start point)
    everything must be finished by day_end

Meals (lunch / dinner) are separate timeline entries, never sightseeing stops.
A meal is "due" before the next ride when its window is already open, or when
going on to the next stop would make it too late to start the meal. It is taken
at a listed food place within MEAL_VENUE_MAX_DETOUR_MIN planned minutes if
there is one (that detour is a travel leg of its own), otherwise as a generic
break where you are -- in which case no venue is claimed.

Each travel leg is counted exactly once (from the planning table) and each visit
and meal exactly once, so nothing is double-counted. If the first stop is not
open yet, the traveller simply leaves later instead of waiting there.

A route that breaks a rule is still simulated to the end (the visit is forced
to start on arrival) so we can count *how many* rules it breaks; that count is
the "constraint violations" metric on the comparison page.
"""

import math
from dataclasses import dataclass, field

import config
from services.models import MealBreak, Visit
from services.timeutil import WEEKDAY_LONG, fmt_hhmm


@dataclass
class DayContext:
    city: object               # CityData
    weekday: int
    day_start: int
    day_end: int
    start_id: int
    buffer: int
    meals: tuple = ()          # MealSetting objects needed today, earliest first
    venues: tuple = ()         # (preference rank, place id) of food places usable for meals
    durations: dict = field(default_factory=dict)   # attraction id -> visit minutes (shopping-time override)

    def duration(self, aid):
        return self.durations.get(aid) or self.city.attractions[aid].visit_min

    @property
    def meal_minutes(self):
        return sum(m.minutes for m in self.meals)


@dataclass
class Schedule:
    order: list
    feasible: bool
    depart: int
    end_time: int
    travel_min: int
    violations: list = field(default_factory=list)
    visits: list = field(default_factory=list)       # filled only when detailed=True
    return_leg: object = None
    meals: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    return_time: int | None = None
    travel_km: float = 0.0                           # road km of every leg (meal detours included)


def earliest_start(attraction, weekday, arrive, duration=None):
    """Earliest start time >= arrive that fits one of today's windows, or None."""
    duration = attraction.visit_min if duration is None else duration
    for window in attraction.windows_on(weekday):          # windows are sorted by opening time
        start = max(arrive, window.open_min)
        if start <= window.latest_start(duration):
            return start
    return None


def simulate(order, ctx, scores=None, detailed=False):
    """Run the day minute by minute. Returns a Schedule.

    detailed=True also builds Visit / MealBreak / Leg objects (slower; used for the final plan).
    """
    city = ctx.city
    plan = city.plan
    violations, visits, meals, timeline = [], [], [], []
    here, clock = ctx.start_id, ctx.day_start
    depart = None
    travel_total = 0
    travel_km = 0.0
    pending = list(ctx.meals)
    stops_today = set(order)

    def pick_venue(meal):
        """Best listed food place for this meal from `here`: preferred style first, then the shortest detour."""
        best = None
        for rank, venue_id in ctx.venues:
            if venue_id in stops_today and venue_id != here:
                continue                                      # visited as a stop at another time today
            detour = plan[here][venue_id]
            if detour > config.MEAL_VENUE_MAX_DETOUR_MIN:
                continue
            start = earliest_start(city.attractions[venue_id], ctx.weekday,
                                   max(clock + detour, meal.earliest), meal.minutes)
            if start is None or start > meal.latest_start:
                continue
            key = (rank, detour, start, venue_id)
            if best is None or key < best:
                best = key
        return best

    def take_meal(meal, at_base=False):
        nonlocal here, clock, travel_total, travel_km
        leg, venue, location = None, None, here
        arrive = clock
        choice = None if at_base else pick_venue(meal)
        if choice is not None:
            _, detour, _, venue_id = choice
            venue = city.attractions[venue_id]
            if detour > 0:
                if detailed:
                    leg = city.leg(here, venue_id, depart=clock, purpose="meal")
                travel_total += detour
                travel_km += city.km[here][venue_id]
                arrive = clock + detour
            location = venue_id
            start = earliest_start(venue, ctx.weekday, max(arrive, meal.earliest), meal.minutes)
        else:
            start = max(arrive, meal.earliest)
        end = start + meal.minutes
        if start > meal.latest_start:
            violations.append(f"{meal.label} cannot start by {fmt_hhmm(meal.latest_start)} "
                              f"(earliest possible {fmt_hhmm(start)})")
        if detailed:
            entry = MealBreak(kind=meal.kind, setting=meal, location_id=location,
                              location_name=city.places[location].name, arrive=arrive, start=start, end=end,
                              venue=venue, leg=leg, at_base=at_base)
            meals.append(entry)
            timeline.append(entry)
        here, clock = location, end

    for position, stop in enumerate(order):
        attraction = city.attractions[stop]
        duration = ctx.duration(stop)

        # Meals that must come before the next ride (in window order).
        while pending:
            meal = pending[0]
            travel = plan[here][stop]
            if travel == math.inf:
                break
            arrive = clock + travel
            start = earliest_start(attraction, ctx.weekday, arrive, duration)
            leave_next = (start if start is not None else arrive) + duration + ctx.buffer
            if clock >= meal.earliest or leave_next > meal.latest_start:
                take_meal(pending.pop(0))
            else:
                break

        travel = plan[here][stop]
        if travel == math.inf:
            violations.append(f"No road route to {attraction.name}")
            return Schedule(list(order), False, depart or ctx.day_start, math.inf, math.inf, violations,
                            visits, meals=meals, timeline=timeline)
        leave_at = clock
        arrive = clock + travel
        start = earliest_start(attraction, ctx.weekday, arrive, duration)
        if start is None:
            if not attraction.windows_on(ctx.weekday):
                violations.append(f"{attraction.name} is closed on {WEEKDAY_LONG[ctx.weekday]}")
            else:
                violations.append(f"Reaches {attraction.name} at {fmt_hhmm(arrive)}, too late to fit the visit "
                                  f"in its opening hours ({attraction.hours_label(ctx.weekday)})")
            start = arrive                                   # forced, so we can keep counting
        if position == 0 and here == ctx.start_id and start > arrive:
            leave_at += start - arrive                       # leave the hotel later instead of waiting
            arrive = start
        if depart is None:
            depart = leave_at
        end = start + duration
        leave = end + ctx.buffer
        travel_total += travel
        travel_km += city.km[here][stop]
        if detailed:
            visit = Visit(attraction=attraction, leg=city.leg(here, stop, depart=leave_at), arrive=arrive,
                          start=start, end=end, leave=leave, score=scores.get(stop, 0) if scores else 0)
            visits.append(visit)
            timeline.append(visit)
        here, clock = stop, leave

    if not order:
        return Schedule([], True, ctx.day_start, ctx.day_start, 0, [], return_time=ctx.day_start)

    # Meals still due before heading back.
    back = plan[here][ctx.start_id]
    while pending and back < math.inf:
        meal = pending[0]
        if clock >= meal.earliest or clock + back > meal.latest_start:
            take_meal(pending.pop(0))
            back = plan[here][ctx.start_id]
        else:
            break
    if back == math.inf:
        violations.append(f"No road route back to {city.places[ctx.start_id].name}")
        return Schedule(list(order), False, depart, math.inf, math.inf, violations, visits,
                        meals=meals, timeline=timeline)
    return_leg = city.leg(here, ctx.start_id, depart=clock) if detailed else None
    travel_total += back
    travel_km += city.km[here][ctx.start_id]
    return_time = clock + back
    here, clock = ctx.start_id, return_time
    if return_time > ctx.day_end:
        violations.append(f"Back at {city.places[ctx.start_id].name} at {fmt_hhmm(return_time)}, "
                          f"after your day ends at {fmt_hhmm(ctx.day_end)}")

    # A meal whose window opens after you are back is taken near the start point.
    for meal in pending:
        take_meal(meal, at_base=True)
    if clock > ctx.day_end and clock > return_time:
        violations.append(f"{meals[-1].label if detailed and meals else 'A meal'} near "
                          f"{city.places[ctx.start_id].name} ends at {fmt_hhmm(clock)}, "
                          f"after your day ends at {fmt_hhmm(ctx.day_end)}")

    return Schedule(list(order), not violations, depart, clock, travel_total, violations, visits, return_leg,
                    meals, timeline, return_time, travel_km)


def is_feasible(order, ctx):
    return simulate(order, ctx).feasible
