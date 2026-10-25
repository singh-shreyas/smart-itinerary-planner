"""Multi-city journeys where the overnight stay moves with the traveller.

A one-base trip (stay in Agra, day trips to Mathura) returns to the same stay
every night; that is still available ("overnight = base"). A journey instead
moves on: you sleep in one city, travel to the next, sleep there, and finish
wherever you chose to finish.

    1. STOPS   The sequence of stays: the starting stay, every other city of the
               trip (in the order with the least road time between their stays,
               found by trying every order -- at most 3 cities, so <= 6 orders),
               then the ending stay. A round trip ends where it started; a
               one-way trip ends in another city and never comes back.
    2. PLACES  Each city's places belong to that city's stop (the first stop in
               that city, for a round trip). A city is finished before the
               journey moves on, so nothing like A -> B -> A -> B can happen.
    3. DAYS    Every stop gets a block of consecutive days. Day 1 of a block (for
               every stop but the first) is the TRANSFER day: it starts at the
               previous stop's stay and ends at this stop's stay, so the road time
               between cities is a real part of that day's timeline (and of its
               feasibility) -- nobody "appears" in the next city.
               How many days each block gets depends on the itinerary mode:
                 Most Optimized   the fewest days that fit the stop's places;
                 Suggested        the stop's own Suggested choice (comfortable days),
                                  shortened if the trip has fewer days;
                 Evenly           the trip's days shared out in proportion to each
                                  stop's places (never fewer than it needs).
               Days left over are free days at the final stay.
    4. PLAN    Inside each block the itinerary mode places the stop's places on
               its days (services/distribution.py), with each day's real start and
               end stay; the validator then checks every day, every night's stay
               and that each day starts where the previous one ended.

When the planner chooses the places, each stop's block first runs the
day-by-day selection strategy (DP / Greedy / Max visits) on that city's
attractions alone, over a share of the trip proportional to how many it has.
"""

import itertools
import math
from collections import defaultdict

from services.distribution import distribute
from services.i18n import gettext as _, ngettext
from services.models import DayPlan, Itinerary
from services.timeutil import fmt_duration


def central_stay(city, slug):
    stays = [p for p in city.places.values() if p.kind == "stay" and p.city_slug == slug]
    central = [p for p in stays if p.direction == "central"]
    return min(central or stays, key=lambda p: p.id) if stays else None


def journey_stops(city, trip):
    """[(city slug, stay Place)] in travel order, start first, end last."""
    start = city.place(trip.start)
    end = city.place(trip.end_stay)
    others = [s for s in city.city_slugs if s not in (start.city_slug, end.city_slug)]
    hubs = {s: central_stay(city, s) for s in others}

    def cost(order):
        chain = [start] + [hubs[s] for s in order] + [end]
        return sum(city.plan[a.id][b.id] for a, b in zip(chain, chain[1:]))

    best = min(itertools.permutations(others), key=lambda order: (cost(order), order)) if others else ()
    stops = [(start.city_slug, start)] + [(s, hubs[s]) for s in best]
    if end.id != start.id or best:
        stops.append((end.city_slug, end))
    return stops


def needs_journey(city, trip):
    if trip.overnight != "move" or not (city.multi_city or trip.end_stay != trip.start):
        return False
    return trip.days >= len(journey_stops(city, trip)) - 1      # too short to move: one base (checked by the form)


def plan_journey(city, trip, tctx, log, scores, best_route, day_context, plan_day, build_day):
    """Returns (days, selected attraction ids, unplaced {id: reason}, stops summary, notes)."""
    dates = trip.dates()
    total = len(dates)
    stops = journey_stops(city, trip)
    first_stop = {}
    for i, (slug, _stay) in enumerate(stops):
        first_stop.setdefault(slug, i)

    def contexts(i, offset, k):
        """Day contexts of stop i's block: day 1 is the transfer from the previous stop's stay."""
        out = {}
        for j in range(k):
            begin = stops[i - 1][1].id if (j == 0 and i > 0) else stops[i][1].id
            out[j] = day_context(city, trip, dates[offset + j], tctx, start_id=begin, end_id=stops[i][1].id)
        return out

    def must(i):
        """Days stop i needs even with nothing to see: one for the move there (none for the start)."""
        return 1 if i > 0 else 0

    # --- what to visit at each stop -----------------------------------------------------------------
    places = defaultdict(list)
    seeds = {}
    unplaced = {}
    if trip.places:
        for slug in trip.places:
            a = city.attraction_by_slug(slug)
            if a.id in tctx.blocked and tctx.blocked[a.id][0] == "access_unknown":
                continue                                        # reported by the caller, with its reason
            places[first_stop[a.city_slug]].append(a.id)
    else:
        pools = {i: [a for a in city.attractions if city.city_of[a] == slug and a not in tctx.blocked]
                 for i, (slug, _stay) in enumerate(stops) if first_stop[slug] == i}
        weight = {i: len(pool) for i, pool in pools.items()}
        share = allocate(total, stops, {i: must(i) for i in range(len(stops))}, weight)
        offset, used = 0, set()
        for i in range(len(stops)):
            k = share[i]
            ctxs = contexts(i, offset, k)
            for j in range(k):
                if i not in pools:
                    break
                day = plan_day(city, trip, tctx, offset + j + 1, dates[offset + j], used, log,
                               ctx=ctxs[j], allowed=set(pools[i]))
                for v in day.visits:
                    used.add(v.attraction.id)
                    places[i].append(v.attraction.id)
                    seeds.setdefault(i, {})[v.attraction.id] = j
            offset += k

    # --- how many days each stop gets ----------------------------------------------------------------
    def fits(i, offset, k, mode="optimized"):
        if k < must(i) or offset + k > total:
            return None
        if not places[i]:
            ctxs = contexts(i, offset, k)
            if k and ctxs[0].moves and not _transfer_ok(ctxs[0], best_route):
                return None
            return True
        t = trip.with_changes(days=k, mode=mode)
        dist = distribute(t, contexts(i, offset, k), places[i], scores, best_route, seed=seeds.get(i))
        return dist if not dist.unplaced else None

    def minimum(i, offset, cap):
        for k in range(max(1, must(i)) if places[i] else must(i), cap + 1):
            if fits(i, offset, k):
                return k
        return None

    lengths, offset = {}, 0
    for i in range(len(stops)):
        later = sum(must(j) for j in range(i + 1, len(stops)))
        cap = max(must(i), total - offset - later)
        k = minimum(i, offset, cap)
        lengths[i] = k if k is not None else cap                 # not everything fits: give it all we can
        offset += lengths[i]
    if sum(lengths.values()) > total:                           # shrink the longest blocks back into the trip
        while sum(lengths.values()) > total:
            i = max(lengths, key=lambda j: (lengths[j] - must(j), -j))
            if lengths[i] <= must(i):
                break
            lengths[i] -= 1
    spare = total - sum(lengths.values())

    if trip.mode == "suggested" and spare > 0:
        offset = 0
        for i in range(len(stops)):
            if places[i] and spare > 0:
                dist = distribute(trip.with_changes(days=lengths[i] + spare), contexts(i, offset, lengths[i] + spare),
                                  places[i], scores, best_route, seed=seeds.get(i))
                active = [j for j, order in enumerate(dist.days) if order]
                want = max(active) + 1 if active and not dist.unplaced else lengths[i]
                extra = max(0, min(spare, want - lengths[i]))
                lengths[i] += extra
                spare -= extra
            offset += lengths[i]
    elif trip.mode == "evenly" and spare > 0:
        weight = {i: len(places[i]) for i in range(len(stops)) if places[i]}
        lengths = allocate(total, stops, lengths, weight)
        spare = total - sum(lengths.values())

    # --- plan each block ------------------------------------------------------------------------------
    days, selected, offset, summary = [], [], 0, []
    for i, (slug, stay) in enumerate(stops):
        k = lengths[i]
        selected += places[i]
        ctxs = contexts(i, offset, k)
        if k:
            dist = distribute(trip.with_changes(days=k), ctxs, places[i], scores, best_route, seed=seeds.get(i))
            for p in dist.unplaced:
                unplaced[p] = dist.reasons.get(p, _("could not be scheduled in this city's days"))
            for j in range(k):
                days.append(build_day(city, trip, tctx, ctxs[j], offset + j + 1, dates[offset + j], dist.days[j],
                                      dist.branches[j], dist, len(places[i])))
        else:
            for p in places[i]:
                unplaced[p] = _("there were no days left for this city")
        summary.append({"city": slug, "city_name": stay.city_name, "stay": stay, "first_day": offset + 1,
                        "last_day": offset + k, "nights": k, "places": len(places[i])})
        offset += k
    if spare:                                                 # free days at the final stay
        last = stops[-1][1]
        for j in range(spare):
            days.append(DayPlan(index=offset + j + 1, date=dates[offset + j], depart=trip.day_start, visits=[],
                                return_leg=None, day_start=trip.day_start, day_end=trip.day_end,
                                start_place=last, end_place=last, is_free=True,
                                empty_reason=_("Free day in {city}: every selected place is planned on earlier days, so "
                                               "this day is open for rest or your own plans.", city=last.city_name)))
        summary[-1]["last_day"] += spare
        summary[-1]["nights"] += spare
    return days, selected, unplaced, summary, stops


def _transfer_ok(ctx, best_route):
    from services.scheduler import simulate
    return simulate([], ctx).feasible


def allocate(total, stops, minimum, weight):
    """Share `total` days among stops: every stop keeps its minimum; the rest goes in proportion to
    `weight` (largest remainder, earliest stop first on ties)."""
    lengths = {i: minimum.get(i, 0) for i in range(len(stops))}
    left = total - sum(lengths.values())
    if left <= 0 or not weight or not sum(weight.values()):
        return lengths
    whole = sum(weight.values())
    want = {i: total * w / whole for i, w in weight.items()}
    extra = {i: max(0, math.floor(want[i]) - lengths[i]) for i in weight}
    while sum(extra.values()) > left:                         # minimums already used part of the share
        i = max(extra, key=lambda j: (extra[j], -j))
        extra[i] -= 1
    for i in extra:
        lengths[i] += extra[i]
    left -= sum(extra.values())
    order = sorted(weight, key=lambda i: (-(want[i] - math.floor(want[i])), i))
    for i in order:
        if left <= 0:
            break
        lengths[i] += 1
        left -= 1
    return lengths


def journey_notes(trip, summary, days, selected, unplaced):
    """Plain-language description of the journey actually produced."""
    route = " → ".join(_("{city} (days {first}–{last})", city=s["city_name"], first=s["first_day"], last=s["last_day"])
                       if s["nights"] > 1 else _("{city} (day {first})", city=s["city_name"], first=s["first_day"])
                       for s in summary if s["nights"])
    lines = [_("Your journey: {route}. You sleep where each day ends; the stay changes on the travel days.", route=route)]
    end, start = summary[-1]["stay"], summary[0]["stay"]
    if end.city_slug == start.city_slug and len(summary) > 1:
        lines.append(_("It is a round trip: the last day brings you back to {stay}.", stay=end.name))
    elif len(summary) > 1:
        lines.append(_("It is a one-way trip: it ends at {stay} ({city}) and never returns to {start}.",
                       stay=end.name, city=end.city_name, start=start.city_name))
    transfers = [d for d in days if d.moves]
    if transfers:
        minutes = sum(d.intercity_min for d in transfers)
        lines.append(ngettext("{n} travel day between cities; the drive to the next stay is part of that day's "
                              "timeline ({time} of travel between cities in all).",
                              "{n} travel days between cities; the drive to the next stay is part of that day's "
                              "timeline ({time} of travel between cities in all).", len(transfers),
                              time=fmt_duration(minutes)))
    if unplaced:
        lines.insert(0, _("{missing} of your {total} selected attractions could not be scheduled; each one is listed "
                          "with the reason below." if trip.places else
                          "{missing} of your {total} chosen attractions could not be scheduled; each one is listed "
                          "with the reason below.", missing=len(unplaced), total=len(selected)))
    free = [d for d in days if not d.visits and not d.moves]
    if free and trip.mode != "evenly":
        lines.append(ngettext("{n} day is free at the final stay.", "{n} days are free at the final stay.", len(free)))
    return lines


def build_itinerary(city, trip, days, skipped, summary, notes):
    it = Itinerary(trip=trip, city_name=city.name, start_place=city.place(trip.start), days=days, skipped=skipped,
                   cities=[{"slug": c["slug"], "name": c["name"]} for c in city.cities],
                   estimated_links=list(city.estimated_links))
    it.journey = summary
    it.mode_notes = notes
    return it
