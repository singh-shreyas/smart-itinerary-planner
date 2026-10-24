"""Independent validator: re-check a finished itinerary from the raw data.

It does not reuse any of the planner's intermediate values (it even recomputes
the 10-minute travel rounding from the raw Dijkstra table). For every day it
walks the timeline again and checks that:
    - no attraction appears twice in the trip, none the user excluded, none blocked
      by the trip's rules (no road access, food/shopping not asked for, interests)
    - each leg starts where the previous activity ended, departs no earlier than
      that activity's end, and its minutes equal the shortest-path time rounded
      UP to 10 minutes (no leg is infinite, none is silently zero)
    - arrival = departure + travel (travel counted once, never skipped)
    - every visit starts inside an opening window for that date's weekday, no
      later than the last entry, lasts its planned duration, and ends by closing time
    - every needed meal (lunch / dinner) is there exactly once, inside its
      window, with its full duration, at an open venue or where you already are
    - activities never overlap and time never goes backwards
    - the ride back reaches the start point, and everything ends by the end of the day
    - the day's spend is within the budget (when a budget is set)
    - every attraction not in the plan has a stated reason

An empty list means the itinerary satisfies every constraint. A non-empty list
is a bug in the planner, never an acceptable plan.
"""

import math

import config
from services.models import MealBreak, Visit
from services.timeutil import WEEKDAY_SHORT, fmt_hhmm, round_up_travel


def _expected_minutes(city, u, v):
    return round_up_travel(city.dist[u][v])


def _open_for(attraction, weekday, start, minutes):
    return any(w.open_min <= start <= w.latest_start(minutes) for w in attraction.windows_on(weekday))


def check_itinerary(itinerary, city, transport_rate):
    trip = itinerary.trip
    buffer = config.PACES[trip.pace]["buffer"]
    start_id = city.place(trip.start).id
    problems, seen = [], set()
    blocked = {s.attraction.id: s.code for s in itinerary.skipped
               if s.code in ("excluded", "no_road", "opt_in", "interest")}

    def check_leg(label, leg, here, clock):
        """Returns the arrival time (or None if the leg is unusable)."""
        if leg is None:
            problems.append(f"{label}: missing travel leg")
            return None
        if leg.from_id != here:
            problems.append(f"{label}: leg starts at the wrong place")
        travel = city.dist[here][leg.to_id]
        if travel == math.inf:
            problems.append(f"{label}: no road route from the previous place")
            return None
        expected = _expected_minutes(city, here, leg.to_id)
        if leg.minutes != expected:
            problems.append(f"{label}: leg says {leg.minutes} min, travel table says {expected} min "
                            f"(raw {travel} min rounded up to {config.TRAVEL_ROUNDING_MIN})")
        if leg.depart is None or leg.depart < clock:
            problems.append(f"{label}: leaves before the previous activity ends")
            return None
        return leg.depart + leg.minutes

    for day in itinerary.days:
        label = f"Day {day.index}"
        weekday = day.date.weekday()
        if not day.visits:
            if day.meals:
                problems.append(f"{label}: has meals but no stops")
            continue
        if day.depart < trip.day_start:
            problems.append(f"{label}: leaves at {fmt_hhmm(day.depart)}, before the day starts")

        clock, here, previous_end, returned = trip.day_start, start_id, None, False
        needed = {m.kind: m for m in trip.meals if m.needed(trip.day_start, trip.day_end)}
        meals_seen = []
        legs_km = 0.0

        def do_return():
            nonlocal clock, here, returned, legs_km
            leg = day.return_leg
            if leg is not None and leg.to_id != start_id:
                problems.append(f"{label}: return leg does not end at the start point")
            arrive = check_leg(f"{label} (return)", leg, here, clock)
            if arrive is None:
                return
            if day.return_time != arrive:
                problems.append(f"{label}: return time does not match the return leg")
            legs_km += city.km[here][start_id]
            clock, here, returned = arrive, start_id, True

        for entry in day.timeline:
            if isinstance(entry, Visit):
                a = entry.attraction
                name = f"{label}: {a.name}"
                if returned:
                    problems.append(f"{name} comes after the ride back")
                if a.id in seen:
                    problems.append(f"{name} is visited twice in the trip")
                seen.add(a.id)
                if a.slug in trip.exclude:
                    problems.append(f"{name} was excluded by the user")
                if a.id in blocked:
                    problems.append(f"{name} is blocked by the trip's rules ({blocked[a.id]})")
                arrive = check_leg(name, entry.leg, here, clock)
                if arrive is None:
                    break
                legs_km += city.km[here][a.id]
                if entry.arrive != arrive:
                    problems.append(f"{name}: arrival {fmt_hhmm(entry.arrive)} != departure + travel")
                if entry.start < entry.arrive:
                    problems.append(f"{name}: starts before arriving")
                if previous_end is not None and entry.start < previous_end:
                    problems.append(f"{name}: overlaps the previous activity")
                minutes = trip.shop_minutes if (trip.shop_minutes and a.is_shopping_only) else a.visit_min
                if entry.end != entry.start + minutes:
                    problems.append(f"{name}: visit length is not {minutes} min")
                if not _open_for(a, weekday, entry.start, minutes):
                    problems.append(f"{name}: {fmt_hhmm(entry.start)}–{fmt_hhmm(entry.end)} is outside its "
                                    f"{WEEKDAY_SHORT[weekday]} opening hours ({a.hours_label(weekday)})")
                if entry.leave != entry.end + buffer:
                    problems.append(f"{name}: buffer after the visit is not {buffer} min")
                clock, here, previous_end = entry.leave, a.id, entry.end
            elif isinstance(entry, MealBreak):
                meal = needed.get(entry.kind)
                name = f"{label}: {entry.label}"
                if meal is None:
                    problems.append(f"{name} was not asked for, or is not needed on this day")
                    continue
                meals_seen.append(entry.kind)
                if entry.at_base and not returned:
                    do_return()
                if entry.leg is not None:
                    arrive = check_leg(name, entry.leg, here, clock)
                    if arrive is None:
                        break
                    legs_km += city.km[here][entry.leg.to_id]
                    here = entry.leg.to_id
                else:
                    arrive = clock
                if entry.location_id != here:
                    problems.append(f"{name} is not where you are")
                if entry.arrive != arrive:
                    problems.append(f"{name}: arrival {fmt_hhmm(entry.arrive)} does not follow the timeline")
                if entry.start < entry.arrive or entry.start < meal.earliest:
                    problems.append(f"{name} starts before you arrive or before {fmt_hhmm(meal.earliest)}")
                if previous_end is not None and entry.start < previous_end:
                    problems.append(f"{name}: overlaps the previous activity")
                if entry.end != entry.start + meal.minutes:
                    problems.append(f"{name}: lasts {entry.end - entry.start} min, not {meal.minutes}")
                if entry.end > meal.latest_end:
                    problems.append(f"{name} ends at {fmt_hhmm(entry.end)}, after {fmt_hhmm(meal.latest_end)}")
                if entry.venue is not None:
                    if entry.venue.id != entry.location_id:
                        problems.append(f"{name}: venue and location disagree")
                    if not _open_for(entry.venue, weekday, entry.start, meal.minutes):
                        problems.append(f"{name}: {entry.venue.name} is not open {fmt_hhmm(entry.start)}–"
                                        f"{fmt_hhmm(entry.end)}")
                    if trip.veg_only and entry.venue.vegetarian != "yes":
                        problems.append(f"{name}: {entry.venue.name} is not a verified vegetarian place")
                clock, previous_end = entry.end, entry.end
            else:
                problems.append(f"{label}: unknown timeline entry")

        if not returned:
            do_return()
        if clock > trip.day_end:
            problems.append(f"{label}: back at {fmt_hhmm(clock)}, after the day ends at {fmt_hhmm(trip.day_end)}")
        for kind in needed:
            if meals_seen.count(kind) != 1:
                problems.append(f"{label}: {kind} appears {meals_seen.count(kind)} times (expected once)")
        if [e for e in day.timeline if isinstance(e, Visit)] != day.visits:
            problems.append(f"{label}: visits and timeline disagree")
        if abs(day.km - legs_km) > 0.1 * (len(day.legs) + 1):
            problems.append(f"{label}: distance {day.km} km does not match the road graph ({legs_km:.1f} km)")

        if trip.budget is not None:
            shopping = trip.shop_spend * sum(1 for v in day.visits if v.attraction.is_shopping_only)
            spend = day.fees + shopping + (round(legs_km * transport_rate) if trip.include_transport else 0)
            # Allow Rs 1 for rounding the transport estimate to whole rupees.
            if spend > trip.budget + 1:
                problems.append(f"{label}: spends ₹{spend}, more than the ₹{trip.budget} budget")

    explained = {s.attraction.id for s in itinerary.skipped if s.reason}
    for aid, attraction in city.attractions.items():
        if aid not in seen and aid not in explained:
            problems.append(f"{attraction.name} is neither planned nor explained")
    return problems
