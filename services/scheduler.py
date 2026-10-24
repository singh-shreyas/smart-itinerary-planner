"""Simulate one day's timeline for a given visiting order.

This is the "truth" check every candidate route goes through:

    leave the start point at day_start
    for each stop in order:
        arrive = previous leave + travel time (shortest path from Dijkstra)
        start  = earliest moment >= arrive inside one of today's opening windows,
                 no later than the last entry, with start + visit <= closing time
        end    = start + visit duration
        leave  = end + pace buffer
    ride back to the start point; it must be reached by day_end

Each travel leg is counted exactly once (from the travel table) and each visit
exactly once (its duration), so nothing is double-counted. If the first stop
is not open yet, the traveller simply leaves later instead of waiting there.

A route that breaks a rule is still simulated to the end (the visit is forced
to start on arrival) so we can count *how many* rules it breaks; that count is
the "constraint violations" metric on the comparison page.
"""

import math
from dataclasses import dataclass, field

from services.models import Visit
from services.timeutil import WEEKDAY_LONG, fmt_hhmm


@dataclass
class DayContext:
    city: object               # CityData
    weekday: int
    day_start: int
    day_end: int
    start_id: int
    buffer: int


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


def earliest_start(attraction, weekday, arrive):
    """Earliest start time >= arrive that fits one of today's windows, or None."""
    for window in attraction.windows_on(weekday):          # windows are sorted by opening time
        start = max(arrive, window.open_min)
        if start <= window.latest_start(attraction.visit_min):
            return start
    return None


def simulate(order, ctx, scores=None, detailed=False):
    """Run the day minute by minute. Returns a Schedule.

    detailed=True also builds Visit / Leg objects (slower; used for the final plan).
    """
    city = ctx.city
    dist = city.dist
    violations, visits = [], []
    here, clock, depart, travel_total = ctx.start_id, ctx.day_start, ctx.day_start, 0

    for position, stop in enumerate(order):
        attraction = city.attractions[stop]
        travel = dist[here][stop]
        if travel == math.inf:
            violations.append(f"No road route to {attraction.name}")
            return Schedule(list(order), False, depart, math.inf, math.inf, violations)
        arrive = clock + travel
        start = earliest_start(attraction, ctx.weekday, arrive)
        if start is None:
            if not attraction.windows_on(ctx.weekday):
                violations.append(f"{attraction.name} is closed on {WEEKDAY_LONG[ctx.weekday]}")
            else:
                violations.append(f"Reaches {attraction.name} at {fmt_hhmm(arrive)}, too late to fit the visit "
                                  f"in its opening hours ({attraction.hours_label(ctx.weekday)})")
            start = arrive                                   # forced, so we can keep counting
        if position == 0 and start > arrive:
            depart += start - arrive                         # leave the hotel later instead of waiting
            arrive = start
        end = start + attraction.visit_min
        leave = end + ctx.buffer
        travel_total += travel
        if detailed:
            visits.append(Visit(attraction=attraction, leg=city.leg(here, stop), arrive=arrive,
                                start=start, end=end, leave=leave,
                                score=scores.get(stop, 0) if scores else 0))
        here, clock = stop, leave

    back = dist[here][ctx.start_id] if order else 0
    if back == math.inf:
        violations.append(f"No road route back to {city.places[ctx.start_id].name}")
        return Schedule(list(order), False, depart, math.inf, math.inf, violations, visits)
    end_time = clock + back
    travel_total += back
    if end_time > ctx.day_end:
        violations.append(f"Back at {city.places[ctx.start_id].name} at {fmt_hhmm(end_time)}, "
                          f"after your day ends at {fmt_hhmm(ctx.day_end)}")

    return_leg = city.leg(here, ctx.start_id) if detailed and order else None
    return Schedule(list(order), not violations, depart, end_time, travel_total, violations, visits, return_leg)


def is_feasible(order, ctx):
    return simulate(order, ctx).feasible
