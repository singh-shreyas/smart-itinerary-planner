"""Independent validator: re-check a finished itinerary from the raw data.

It does not reuse any of the planner's intermediate values. For every day it
walks the timeline again and checks that:
    - no attraction appears twice in the trip, and none the user excluded
    - each leg's minutes equal the shortest-path travel time (no leg is infinite)
    - arrival = previous departure + travel (travel counted once, never skipped)
    - every visit starts inside an opening window for that date's weekday,
      no later than the last entry, and ends by closing time
    - visits never overlap and time never goes backwards
    - the ride back reaches the start point by the end of the day
    - the day's spend is within the budget (when a budget is set)
    - every attraction not in the plan has a stated reason

An empty list means the itinerary satisfies every constraint. A non-empty list
is a bug in the planner, never an acceptable plan.
"""

import math

import config
from algorithms.tour import tour_cost
from services.timeutil import WEEKDAY_SHORT, fmt_hhmm


def check_itinerary(itinerary, city, transport_rate):
    trip = itinerary.trip
    buffer = config.PACES[trip.pace]["buffer"]
    start_id = city.place(trip.start).id
    problems, seen = [], set()

    for day in itinerary.days:
        label = f"Day {day.index}"
        weekday = day.date.weekday()
        if day.depart < trip.day_start:
            problems.append(f"{label}: leaves at {fmt_hhmm(day.depart)}, before the day starts")
        clock, here, previous_end = day.depart, start_id, None

        for visit in day.visits:
            a = visit.attraction
            name = f"{label}: {a.name}"
            if a.id in seen:
                problems.append(f"{name} is visited twice in the trip")
            seen.add(a.id)
            if a.slug in trip.exclude:
                problems.append(f"{name} was excluded by the user")

            travel = city.dist[here][a.id]
            if travel == math.inf:
                problems.append(f"{name} has no road route from the previous stop")
                break
            if visit.leg.minutes != travel:
                problems.append(f"{name}: leg says {visit.leg.minutes} min, travel table says {travel} min")
            if visit.arrive != clock + travel:
                problems.append(f"{name}: arrival {fmt_hhmm(visit.arrive)} != departure + travel")
            if visit.start < visit.arrive:
                problems.append(f"{name}: starts before arriving")
            if previous_end is not None and visit.start < previous_end:
                problems.append(f"{name}: overlaps the previous visit")
            inside = any(w.open_min <= visit.start <= w.latest_start(a.visit_min) for w in a.windows_on(weekday))
            if not inside:
                problems.append(f"{name}: {fmt_hhmm(visit.start)}–{fmt_hhmm(visit.end)} is outside its "
                                f"{WEEKDAY_SHORT[weekday]} opening hours ({a.hours_label(weekday)})")
            if visit.end != visit.start + a.visit_min:
                problems.append(f"{name}: visit length is not {a.visit_min} min")
            if visit.leave != visit.end + buffer:
                problems.append(f"{name}: buffer after the visit is not {buffer} min")
            clock, here, previous_end = visit.leave, a.id, visit.end

        if day.visits:
            back = city.dist[here][start_id]
            if back == math.inf:
                problems.append(f"{label}: no road route back to the start point")
            elif day.return_leg is None or day.return_leg.minutes != back:
                problems.append(f"{label}: return leg does not match the travel table")
            elif clock + back > trip.day_end:
                problems.append(f"{label}: back at {fmt_hhmm(clock + back)}, after the day ends "
                                f"at {fmt_hhmm(trip.day_end)}")

            order = [v.attraction.id for v in day.visits]
            expected_km = tour_cost(start_id, order, city.km)
            if abs(day.km - expected_km) > 0.1 * (len(order) + 1):
                problems.append(f"{label}: distance {day.km} km does not match the road graph ({expected_km:.1f} km)")

        if trip.budget is not None:
            spend = day.fees + (round(day.km * transport_rate) if trip.include_transport else 0)
            # Allow Rs 1 for rounding the transport estimate to whole rupees.
            if spend > trip.budget + 1:
                problems.append(f"{label}: spends ₹{spend}, more than the ₹{trip.budget} budget")

    explained = {s.attraction.id for s in itinerary.skipped if s.reason}
    for aid, attraction in city.attractions.items():
        if aid not in seen and aid not in explained:
            problems.append(f"{attraction.name} is neither planned nor explained")
    return problems
