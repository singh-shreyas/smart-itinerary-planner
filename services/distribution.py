"""The three itinerary modes: how a chosen set of places is spread over the trip.

What to visit and how to spread it are separate questions:

    what   the places you picked, or -- if you let the planner choose -- the
           set the day-by-day selection strategy (DP / Greedy) found
    how    the itinerary mode, which ranks every feasible day assignment of that
           set with its own objective:

    Most Optimized       finish in the fewest active days.
                         Priorities: 1 schedule every place, 2 fewest active days,
                         3 least travel. Search: for k = 1, 2, ... days and every
                         choice of k trip days (earliest first), pack the places into
                         those days (algorithms/day_partition.py); the first k that
                         fits everything is the minimum the search can find.

    Evenly Distributed   spread over all selected days.
                         Priorities: 1 schedule every place, 2 smallest deviation from
                         the quotient-and-remainder target (4 places, 3 days -> 2+1+1),
                         3 balanced busy time (to the nearest 30 min), 4 least travel,
                         5 extra places on the earliest days / places spread over the trip.

    Suggested            comfortable days without wasting the trip.
                         For every feasible k from the minimum up, the best k-day plan by
                             cost = 2 x (minutes beyond a comfortable day)
                                  + travel minutes
                                  + 0.25 x (minutes each day differs from the average day)
                                  + 60 x (active days beyond the minimum)
                         and the k with the lowest cost wins (ties: fewer days). A
                         comfortable day is out-and-about for at most 70% of your daily
                         window, and never more than 8 hours. One more day is used only
                         if it removes at least half an hour of over-long days (or the
                         equivalent travel). It can equal Most Optimized; nothing forces
                         a difference.

All three share the same feasibility check: a day is feasible only if the
planner's own router (Nearest Neighbour / closing-time insertion + 2-opt) finds
an order that the minute-by-minute scheduler accepts -- opening hours, meals,
treks and ferries, and the ride back included. So no mode ever breaks a real
constraint to reach its target. The search is a heuristic (the problem is
NP-hard); the tests check it against exhaustive search on small cases.
"""

from dataclasses import dataclass, field

import config
from algorithms.day_partition import day_subsets, deviation, search, target_counts
from services.i18n import gettext as _, ngettext
from services.scheduler import simulate
from services.timeutil import fmt_duration

MODES = ("evenly", "suggested", "optimized")


@dataclass
class DayEval:
    feasible: bool
    order: tuple = ()
    branch: str = ""
    travel: int = 0
    busy: int = 0                 # out and about: leave the stay -> back (meals inside included)
    sight: int = 0


@dataclass
class Distribution:
    mode: str
    days: list                    # per trip day: tuple of attraction ids in visiting order
    branches: list
    unplaced: list                # attraction ids that fit on no day
    reasons: dict                 # attraction id -> why it could not be placed
    target: list
    min_days: int | None = None   # fewest active days found for the same places (None: not all fit)
    suggested_trials: list = field(default_factory=list)   # Suggested: [{k, cost, overload, travel}]
    comfort_min: int = 0
    evaluations: int = 0          # distinct days routed during the search


class DayEvaluator:
    """Is this set of stops a feasible day, and how good is it? Memoised per (weekday, where the day
    starts and ends, set): two Mondays at the same stay are the same planning problem."""

    def __init__(self, contexts, best_route, known=None):
        self.contexts = contexts                   # trip day index -> DayContext
        self.best_route = best_route
        self.memo = {}
        self.calls = 0
        for (d, stops), (order, branch) in (known or {}).items():
            self.memo[self._key(d, stops)] = self._measure(d, tuple(order), branch)

    def _key(self, d, stops):
        ctx = self.contexts[d]
        return (ctx.weekday, ctx.start_id, ctx.end, frozenset(stops))

    def _measure(self, d, order, branch):
        sim = simulate(list(order), self.contexts[d])
        if not sim.feasible:
            return DayEval(False)
        return DayEval(True, order, branch, sim.travel_min, sim.return_time - sim.depart,
                       sum(self.contexts[d].duration(a) for a in order))

    def __call__(self, d, stops):
        if not stops:
            if self.contexts[d].moves:                # a pure transfer day still has to fit the ride
                key = self._key(d, ())
                if key not in self.memo:
                    self.memo[key] = self._measure(d, (), "")
                return self.memo[key]
            return DayEval(True)
        ctx = self.contexts[d]
        key = self._key(d, stops)
        if key not in self.memo:
            self.calls += 1
            lower_bound = sum(ctx.duration(a) + ctx.buffer for a in stops) + ctx.meal_minutes
            closed = any(not ctx.city.attractions[a].windows_on(ctx.weekday) for a in stops)
            too_long = lower_bound > ctx.day_end - ctx.day_start
            found = None if (closed or too_long) else self.best_route(list(sorted(stops)), ctx)
            self.memo[key] = DayEval(False) if found is None else self._measure(d, tuple(found[0]), found[1])
        return self.memo[key]

    def feasible(self, d, stops):
        return self(d, stops).feasible


def comfort_minutes(trip):
    return int(min(config.COMFORT_SHARE * (trip.day_end - trip.day_start), config.COMFORT_MAX_MIN))


def distribute(trip, contexts, places, scores, best_route, known=None, seed=None):
    """Assign `places` (attraction ids) to the trip's days according to trip.mode."""
    days = list(range(trip.days))
    ev = DayEvaluator(contexts, best_route, known)
    comfort = comfort_minutes(trip)

    # Places that fit on no day even alone can never be placed: say why, and leave them out of the search.
    reasons, usable, alone_days = {}, [], {}
    for p in places:
        ok = [d for d in days if ev.feasible(d, (p,))]
        if ok:
            usable.append(p)
            alone_days[p] = len(ok)
        else:
            reasons[p] = _("does not fit any day of the trip on its own (opening hours, travel, access or meals)")

    def order_key(p):                              # hardest first: fewest possible days, then the longest
        return (alone_days[p], -max(ev(d, (p,)).busy for d in days if ev.feasible(d, (p,))), p)

    def evals(a):
        return {d: ev(d, a.stops(d)) for d in a.days if a.stops(d)}

    def lost(a):
        un = a.unplaced()
        return (len(un), sum(scores[p] for p in un))

    def optimized_cost(a):
        e = evals(a)
        return lost(a) + (sum(x.travel for x in e.values()), sum(a.days.index(d) for d in e))

    target = target_counts(len(usable), len(days))

    def evenly_cost(a):
        e = evals(a)
        counts = a.counts()
        busy = [x.busy for x in e.values()]
        imbalance = round((max(busy) - min(busy)) / 30) if busy else 0
        positional = sum(abs(c - t) for c, t in zip(counts, target))
        return lost(a) + (deviation(counts, target), imbalance, sum(x.travel for x in e.values()), positional)

    def suggested_inner(a):
        e = evals(a)
        busy = [x.busy for x in e.values()]
        mean = sum(busy) / len(busy) if busy else 0
        overload = sum(max(0, b - comfort) for b in busy)
        travel = sum(x.travel for x in e.values())
        spread = sum(abs(b - mean) for b in busy)
        score = config.SUGGESTED_OVERLOAD_WEIGHT * overload + travel + config.SUGGESTED_IMBALANCE_WEIGHT * spread
        return lost(a) + (round(score, 1), travel, sum(a.days.index(d) for d in e))

    seeds = [seed] if seed else []

    def spent():
        """Effort cap: after MODE_SEARCH_BUDGET distinct days have been routed, each local search
        keeps the best plan it has (every plan it holds is feasible) instead of looking further."""
        return ev.calls >= config.MODE_SEARCH_BUDGET

    def best_over_subsets(k, cost):
        best, seen = None, set()
        for subset in day_subsets(days, k):
            # Two choices of days with the same weekdays and stays are the same problem: search it once
            # (on a 14-day trip, windows a week apart repeat). The earliest one is kept.
            shape = tuple((contexts[d].weekday, contexts[d].start_id, contexts[d].end) for d in subset)
            if shape in seen:
                continue
            seen.add(shape)
            found = search(usable, list(subset), ev.feasible, cost, seeds=seeds, order_key=order_key, stop=spent)
            if found and (best is None or found[1] < best[1]):
                best = found
        return best

    def minimum_days():
        """Smallest k (and its best plan) that fits every usable place; None if even D days cannot.
        No k below the lower bound (total visit + buffer time / the longest usable day) can work."""
        usable_day = max(c.day_end - c.day_start - c.meal_minutes for c in contexts.values())
        need = sum(contexts[0].duration(p) + contexts[0].buffer for p in usable)
        lower = max(1, -(-need // max(1, usable_day)))
        for k in range(lower, len(days) + 1):
            if k > len(usable) and usable:
                break
            found = best_over_subsets(k, optimized_cost)
            if found and not found[0].unplaced():
                return k, found
        return None, best_over_subsets(len(days), optimized_cost)

    result = Distribution(trip.mode, [], [], [], reasons, target, comfort_min=comfort)
    if not usable:
        chosen = None
    elif trip.mode == "evenly":
        chosen = search(usable, days, ev.feasible, evenly_cost, seeds=seeds, order_key=order_key, stop=spent)[0]
    else:
        k_min, found = minimum_days()
        result.min_days = k_min
        chosen = found[0]
        if trip.mode == "suggested" and k_min is not None:
            best = None
            for k in range(k_min, min(len(days), len(usable)) + 1):
                # Every extra day adds at least SUGGESTED_DAY_COST and nothing is negative: once that alone
                # reaches the best plan's cost, no longer plan can win, so the search stops (exact, not a guess).
                if best is not None and config.SUGGESTED_DAY_COST * (k - k_min) >= best[0]:
                    break
                candidate = best_over_subsets(k, suggested_inner)
                if candidate is None or candidate[0].unplaced():
                    continue
                e = evals(candidate[0])
                overload = sum(max(0, x.busy - comfort) for x in e.values())
                total = candidate[1][2] + config.SUGGESTED_DAY_COST * (k - k_min)
                result.suggested_trials.append({"k": k, "cost": round(total, 1), "overload": overload,
                                                "travel": sum(x.travel for x in e.values()),
                                                "longest": max(x.busy for x in e.values())})
                # Plans within SUGGESTED_TIE_MIN of each other count as equal: the one with fewer days, then
                # the one starting earlier, wins (so a trip does not open with empty days for a few minutes).
                key = (round(total / config.SUGGESTED_TIE_MIN), k, min(d for d in candidate[0].days))
                if best is None or key < best[2]:
                    best = (total, candidate[0], key)
            if best is not None:
                chosen = best[1]

    for d in days:
        stops = chosen.stops(d) if chosen else ()
        e = ev(d, stops)
        result.days.append(tuple(e.order) if stops else ())
        result.branches.append(e.branch)
    if chosen:
        for p in chosen.unplaced():
            result.unplaced.append(p)
            reasons.setdefault(p, "does not fit with your other selected places in the trip's days")
    result.unplaced = sorted(set(result.unplaced) | set(reasons))
    result.evaluations = ev.calls
    return result



# ------------------------------------------------------------------------------ plain-language summary

def _places_phrase(n, picked, remaining):
    """ "3 selected attractions", "1 remaining chosen attraction", ... (each form is its own text)."""
    forms = {(True, False): ("{n} selected attraction", "{n} selected attractions"),
             (True, True): ("{n} remaining selected attraction", "{n} remaining selected attractions"),
             (False, False): ("{n} chosen attraction", "{n} chosen attractions"),
             (False, True): ("{n} remaining chosen attraction", "{n} remaining chosen attractions")}
    return ngettext(*forms[(bool(picked), bool(remaining))], n)


def explain(dist, itinerary_days, selected_count, total_days, picked):
    """Sentences that describe the plan that was actually produced (never a canned claim)."""
    active = [d for d in itinerary_days if d.visits]
    scheduled = sum(len(d.visits) for d in active)
    counts = [len(d.visits) for d in itinerary_days]
    shape = " + ".join(str(c) for c in counts)
    lines = []
    missing = selected_count - scheduled
    if missing:
        lines.append(ngettext(
            "{missing} of your {total} selected attractions could not be scheduled in {n} day; each one is listed with "
            "the reason below." if picked else
            "{missing} of your {total} chosen attractions could not be scheduled in {n} day; each one is listed with "
            "the reason below.",
            "{missing} of your {total} selected attractions could not be scheduled in {n} days; each one is listed with "
            "the reason below." if picked else
            "{missing} of your {total} chosen attractions could not be scheduled in {n} days; each one is listed with "
            "the reason below.", total_days, missing=missing, total=selected_count))
    free = total_days - len(active)
    places = _places_phrase(scheduled, picked, missing)
    if not active:
        return lines
    if total_days == 1:
        lines.append(_("With a one-day trip, all {places} are on that day; the modes differ only on longer trips.",
                       places=places) if scheduled > 1 else
                     _("With a one-day trip, {places} is on that day; the modes differ only on longer trips.",
                       places=places))
        return lines
    if dist.mode == "optimized":
        if scheduled > 1:
            parts = [ngettext("All {places} can be completed in {n} active day.",
                              "All {places} can be completed in {n} active days.", len(active), places=places)]
        else:
            parts = [ngettext("{places} can be completed in {n} active day.",
                              "{places} can be completed in {n} active days.", len(active), places=places)]
        if free:
            parts.append(ngettext("The remaining {n} day is unscheduled, free for rest or optional activities.",
                                  "The remaining {n} days are unscheduled, free for rest or optional activities.", free))
        elif len(active) > 1:
            parts.append(_("No plan with fewer days was feasible (opening hours, travel and access time)."))
        lines.append(" ".join(parts))
    elif dist.mode == "evenly":
        ideal = " + ".join(str(c) for c in dist.target)
        if deviation(counts, dist.target) == 0:
            if scheduled >= total_days:
                lines.append(_("Your {places} are distributed across all {days} selected days ({shape}).",
                               places=places, days=total_days, shape=shape))
            else:
                lines.append(ngettext(
                    "Your {places} are on {scheduled} different days ({shape}); with fewer attractions than days, "
                    "{n} day stays free.",
                    "Your {places} are on {scheduled} different days ({shape}); with fewer attractions than days, "
                    "{n} days stay free.", free, places=places, scheduled=scheduled, shape=shape))
        else:
            lines.append(_("The even target was {ideal}, but the closest feasible distribution is {shape}: some places "
                           "cannot share a day or fit on certain days (opening hours, travel or access time).",
                           ideal=ideal, shape=shape))
    else:
        trials = {t["k"]: t for t in dist.suggested_trials}
        k = len(active)
        shortest = trials.get(dist.min_days)
        over = trials.get(k, {}).get("overload", 0)
        comfort = fmt_duration(dist.comfort_min)
        if dist.min_days is not None and k > dist.min_days and shortest:
            values = dict(n=k, min=dist.min_days, over=fmt_duration(shortest["overload"]), comfort=comfort)
            text = (_("The suggested itinerary uses {n} active days to avoid overly long sightseeing days: the "
                      "{min}-day plan would have {over} beyond a comfortable {comfort} day (this plan: {this}).",
                      this=fmt_duration(over), **values) if over else
                    _("The suggested itinerary uses {n} active days to avoid overly long sightseeing days: the "
                      "{min}-day plan would have {over} beyond a comfortable {comfort} day.", **values))
        elif not over:
            text = ngettext("The suggested itinerary uses {n} active day, the same as the fastest plan, because its "
                            "days are already comfortable (at most {comfort} out).",
                            "The suggested itinerary uses {n} active days, the same as the fastest plan, because its "
                            "days are already comfortable (at most {comfort} out).", k, comfort=comfort)
        elif k == total_days:
            text = ngettext("The suggested itinerary uses {n} active day; some days are long ({over} beyond a "
                            "comfortable {comfort} day in all), and the trip has no more days to spread them over.",
                            "The suggested itinerary uses {n} active days; some days are long ({over} beyond a "
                            "comfortable {comfort} day in all), and the trip has no more days to spread them over.",
                            k, over=fmt_duration(over), comfort=comfort)
        else:
            text = ngettext("The suggested itinerary uses {n} active day, the fewest feasible: one more day would not "
                            "shorten the long days enough to be worth it (it must remove at least 30 min beyond a "
                            "comfortable day).",
                            "The suggested itinerary uses {n} active days, the fewest feasible: one more day would not "
                            "shorten the long days enough to be worth it (it must remove at least 30 min beyond a "
                            "comfortable day).", k)
        if free:
            text += " " + ngettext("{n} day is left free.", "{n} days are left free.", free)
        lines.append(text)
    return lines
