"""Requirement 2: three itinerary modes with different objectives (fixture city Gridville).

    g1..g6       close together, 60 min visits (5 min apart, 10 min from the stay)
    long1..3     360 min visits, 15 min from everything
    far1, far2   90 min from everything else, 20 min from each other
    sw1..sw3     open only 10:00-11:00 (45 min visits): no two fit on one day
"""

import itertools
from datetime import date

import pytest

from algorithms.day_partition import deviation, target_counts
from conftest import make_trip
from services.distribution import DayEvaluator, comfort_minutes
from services.itinerary_generator import best_route, day_context, plan_trip, trip_context


@pytest.fixture(scope="module")
def grid(tiny_area):
    return tiny_area("gridville")


def trip(places, days, mode, **overrides):
    values = dict(city="gridville", start="grid-stay", start_date=date(2026, 11, 2), days=days, mode=mode,
                  places=tuple(places))
    values.update(overrides)
    return make_trip(**values)


def counts(plan):
    return [len(d.visits) for d in plan.days]


def active(plan):
    return sum(1 for d in plan.days if d.visits)


def plans(grid, places, days, **overrides):
    out = {m: plan_trip(grid, trip(places, days, m, **overrides)) for m in ("evenly", "suggested", "optimized")}
    for m, p in out.items():
        assert p.violations == [], (m, p.violations)
    return out


CLOSE = [f"g{i}" for i in range(1, 7)]


def test_targets_follow_quotient_and_remainder():
    assert target_counts(4, 3) == [2, 1, 1]
    assert target_counts(6, 5) == [2, 1, 1, 1, 1]
    assert target_counts(8, 4) == [2, 2, 2, 2]
    assert target_counts(3, 5) == [1, 0, 1, 0, 1]                # fewer places than days: different, spread-out days
    assert deviation([1, 2, 1], [2, 1, 1]) == 0 and deviation([4, 0, 0], [2, 1, 1]) == 4


def test_a_four_places_three_days(grid):
    p = plans(grid, CLOSE[:4], 3)
    assert sorted(counts(p["evenly"]), reverse=True) == [2, 1, 1]
    assert active(p["optimized"]) == 1                            # all four genuinely fit in one day
    comfort = comfort_minutes(p["suggested"].trip)
    assert all(d.return_time - d.depart <= comfort for d in p["suggested"].days if d.visits)
    assert p["suggested"].stops == 4


def test_b_six_places_five_days(grid):
    p = plans(grid, CLOSE, 5)
    assert sorted(counts(p["evenly"]), reverse=True) == [2, 1, 1, 1, 1]
    assert active(p["optimized"]) == 1
    assert active(p["suggested"]) in (2, 3)                       # one 8-hour-plus day is not comfortable
    assert all(m.stops == 6 for m in p.values())
    assert "remaining 4 days are unscheduled" in " ".join(p["optimized"].mode_notes)


def test_c_long_visits_need_more_days(grid):
    places = ["long1", "long2", "long3", "g1", "g2", "g3"]
    p = plans(grid, places, 5)
    assert active(p["optimized"]) == 3                            # two 6-hour visits never share a 10-hour day
    longest = {m: max(d.return_time - d.depart for d in plan.days if d.visits) for m, plan in p.items()}
    assert longest["suggested"] < longest["optimized"]           # Suggested avoids the most demanding day
    assert active(p["suggested"]) >= active(p["optimized"])


def test_d_far_places_are_grouped(grid):
    p = plans(grid, ["g1", "g2", "g3", "far1", "far2"], 2, day_start=8 * 60, day_end=20 * 60)
    for mode in ("evenly", "suggested"):
        kinds = [{"far" if v.attraction.slug.startswith("far") else "close" for v in d.visits} for d in p[mode].days]
        assert sorted(map(sorted, kinds)) == [["close"], ["far"]]  # the two far places share a day; never one on each
    assert active(p["optimized"]) == 1


def test_e_opening_hours_are_never_broken_to_meet_a_target(grid):
    p = plans(grid, ["sw1", "sw2", "g1", "g2"], 2)
    for plan in p.values():
        for v in plan.visits:
            if v.attraction.slug.startswith("sw"):
                assert 10 * 60 <= v.start and v.end <= 11 * 60
        assert plan.stops == 4
        assert sorted(len([v for v in d.visits if v.attraction.slug.startswith("sw")]) for d in plan.days) == [1, 1]
    assert active(p["optimized"]) == 2                            # the two 10:00-11:00 places need two days


def test_f_long_access_changes_feasibility_and_distribution(tiny_area):
    hill = tiny_area("hillview")
    base = dict(city="hillview", start="hill-stay", start_date=date(2026, 11, 2), day_start=6 * 60, day_end=21 * 60)
    places = ("summit-shrine", "hill-market", "cliff-temple", "ferry-isle")
    opt = plan_trip(hill, make_trip(days=3, mode="optimized", places=places, **base))
    assert opt.violations == [] and opt.stops == 4
    shrine_day = next(d for d in opt.days if any(v.attraction.slug == "summit-shrine" for v in d.visits))
    assert shrine_day.access_min >= 500                          # 8+ hours of trekking are inside that day
    assert active(opt) == 2
    without = plan_trip(hill, make_trip(days=3, mode="optimized", places=places[1:], **base))
    assert active(without) == 1                                  # the same places minus the trek fit in one day
    short = plan_trip(hill, make_trip(days=3, mode="optimized", places=places,
                                      **dict(base, day_start=9 * 60, day_end=19 * 60)))
    assert "summit-shrine" not in {v.attraction.slug for v in short.visits}     # too long for 09:00-19:00


def test_g_fewer_places_than_days(grid):
    p = plans(grid, ["g1", "g2", "g3"], 5)
    assert counts(p["evenly"]) == [1, 0, 1, 0, 1]                 # three different days, spread over the trip
    assert active(p["optimized"]) == 1
    assert 1 <= active(p["suggested"]) <= 3


def test_h_suggested_may_equal_optimized(grid):
    p = plans(grid, ["g1", "g2"], 3)
    assert active(p["optimized"]) == active(p["suggested"]) == 1
    assert [[v.attraction.slug for v in d.visits] for d in p["suggested"].days] == \
           [[v.attraction.slug for v in d.visits] for d in p["optimized"].days]
    assert "same as the fastest plan" in " ".join(p["suggested"].mode_notes)


def test_i_infeasible_trip_is_reported_not_hidden(grid):
    p = plans(grid, ["long1", "long2", "long3"], 2)
    for plan in p.values():
        assert plan.stops == 2
        missing = [s for s in plan.skipped if s.code == "unscheduled"]
        assert len(missing) == 1 and missing[0].attraction.slug.startswith("long")
        assert "1 of your 3 selected attractions could not be scheduled" in plan.mode_notes[0]


def test_the_three_modes_rank_the_same_input_differently(grid):
    p = plans(grid, CLOSE[:4], 3)
    shapes = {m: tuple(counts(plan)) for m, plan in p.items()}
    assert shapes["evenly"] != shapes["optimized"]


def test_minimum_days_matches_exhaustive_search(grid):
    """Most Optimized's day count equals the true minimum found by trying every assignment."""
    for places, days in ([["long1", "long2", "g1", "g2", "g3"], 3], [["sw1", "sw2", "g1", "far1"], 3],
                         [["g1", "g2", "g3", "g4", "far1", "far2"], 2]):
        t = trip(places, days, "optimized")
        tctx = trip_context(grid, t)
        contexts = {i: day_context(grid, t, d, tctx) for i, d in enumerate(t.dates())}
        ev = DayEvaluator(contexts, best_route)
        ids = [grid.attraction_by_slug(s).id for s in places]
        best = None
        for assignment in itertools.product(range(days), repeat=len(ids)):
            groups = {d: tuple(i for i, a in zip(ids, assignment) if a == d) for d in range(days)}
            if all(ev.feasible(d, g) for d, g in groups.items() if g):
                used = sum(1 for g in groups.values() if g)
                best = used if best is None else min(best, used)
        plan = plan_trip(grid, t)
        assert plan.stops == len(places) and active(plan) == best, (places, best)


def test_modes_are_deterministic(grid):
    a = plan_trip(grid, trip(["g1", "g2", "g3", "long1", "far1"], 4, "suggested"))
    b = plan_trip(grid, trip(["far1", "long1", "g3", "g2", "g1"], 4, "suggested"))
    assert a.versions["plan"] == plan_trip(grid, trip(["g1", "g2", "g3", "long1", "far1"], 4, "suggested")).versions["plan"]
    assert [[v.attraction.slug for v in d.visits] for d in a.days] == [[v.attraction.slug for v in d.visits] for d in b.days]
