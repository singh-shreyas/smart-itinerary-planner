"""Requirement 1: attractions without road access (fixture city Hillview).

    hill-market    road
    cliff-temple   road, then a 900 m walk (last mile)
    summit-shrine  road to the trailhead, then a 300 min trek up / 200 min down; a helicopter alternative
    ferry-isle     road to the jetty, ferry 40 min (first 09:30, last 13:00) + 10 min walk
    mist-lake      boat, crossing time unknown -> never given a guessed time
"""

import copy
from datetime import date

import pytest

from conftest import make_trip
from routes.helpers import access_info
from services.itinerary_generator import knapsack_instance, plan_trip, trip_context, day_context
from services.validator import check_itinerary


@pytest.fixture(scope="module")
def hill(tiny_area):
    return tiny_area("hillview")


def trip(**overrides):
    values = dict(city="hillview", start="hill-stay", start_date=date(2026, 11, 2))
    values.update(overrides)
    return make_trip(**values)


def visit(plan, slug):
    return next(v for v in plan.visits if v.attraction.slug == slug)


def skip(plan, slug):
    return next(s for s in plan.skipped if s.attraction.slug == slug)


def test_road_attraction_has_one_road_segment(hill):
    plan = plan_trip(hill, trip(places=("hill-market",)))
    v = visit(plan, "hill-market")
    assert [s.mode for s in v.leg.segments] == ["road"] and v.leg.access_min == 0
    assert hill.attraction_by_slug("hill-market").access_timing == "road_data"
    assert plan.violations == []


def test_road_then_walk_counts_the_walk_both_ways(hill):
    plan = plan_trip(hill, trip(places=("cliff-temple",)))
    v = visit(plan, "cliff-temple")
    walk = round(0.9 * 1.35 / 4 * 60 + 0.5)                     # 900 m x detour 1.35 at 4 km/h, rounded up
    assert [s.mode for s in v.leg.segments] == ["road", "walk"]
    assert v.leg.segments[1].minutes == walk
    day = plan.days[0]
    assert [s.mode for s in day.return_leg.segments] == ["walk", "road"]
    assert day.access_min == 2 * walk                           # once in, once out: never twice, never zero
    assert v.arrive - day.depart == v.leg.minutes                # the walk is inside the planned travel time


def test_long_trek_is_part_of_the_timeline_and_the_day_total(hill):
    plan = plan_trip(hill, trip(places=("summit-shrine",), day_start=6 * 60, day_end=21 * 60))
    assert plan.violations == []
    v = visit(plan, "summit-shrine")
    assert [s.mode for s in v.leg.segments] == ["road", "trek"]
    day = plan.days[0]
    assert day.access_min == 300 + 200                          # trek up + trek down, each counted once
    assert v.arrive >= day.depart + 30 + 300                     # road to the trailhead + the climb
    assert day.return_time >= v.leave + 200 + 30
    assert day.travel_min >= 560 and day.road_travel_min >= 60


def test_access_time_counts_in_the_knapsack_weight(hill):
    t = trip(day_start=6 * 60, day_end=21 * 60)
    tctx = trip_context(hill, t)
    ctx = day_context(hill, t, t.start_date, tctx)
    ids = [hill.attraction_by_slug(s).id for s in ("hill-market", "summit-shrine")]
    instance = knapsack_instance(hill, t, ctx, ids, tctx.scores)
    shrine, market = ids[1], ids[0]
    assert instance.weight_minutes[shrine] >= 60 + 200          # visit + the shortest way out (the trek down)
    assert instance.weight_minutes[market] < 120


def test_alternatives_are_shown_but_never_used(hill):
    shrine = hill.attraction_by_slug("summit-shrine")
    info = access_info(shrine, hill)
    labels = [a["label"] for a in info["alternatives"]]
    assert labels == ["Helicopter", "Ropeway"]
    assert all("not verified" in a["status"] or "not operating" in a["status"] for a in info["alternatives"])
    plan = plan_trip(hill, trip(places=("summit-shrine",), day_start=6 * 60, day_end=21 * 60))
    modes = {s.mode for leg in plan.days[0].legs for s in leg.segments}
    assert "helicopter" not in modes and "ropeway" not in modes   # the 10-minute flight is never silently chosen


def test_unknown_access_is_never_assumed_to_be_road(hill):
    lake = hill.attraction_by_slug("mist-lake")
    assert lake.access_timing == "unknown" and not lake.timed and lake.road_access == "no"
    plan = plan_trip(hill, trip(days=2, day_start=6 * 60, day_end=21 * 60))
    assert "mist-lake" not in {v.attraction.slug for v in plan.visits}
    s = skip(plan, "mist-lake")
    assert s.code == "access_unknown" and "unknown" in s.reason and "Verify" in s.reason
    # Even when you pick it yourself it is reported, not silently dropped and not timed by a guess.
    picked = plan_trip(hill, trip(places=("mist-lake", "hill-market")))
    assert skip(picked, "mist-lake").code == "access_unknown"
    assert picked.violations == []


def test_access_that_makes_the_day_infeasible_is_not_scheduled(hill):
    plan = plan_trip(hill, trip(places=("summit-shrine",)))       # 09:00-19:00 is too short for 8+ hours of trek
    assert plan.stops == 0
    s = skip(plan, "summit-shrine")
    assert s.code == "unscheduled"
    auto = plan_trip(hill, trip())                                # left to the planner: explained with the trek time
    reason = skip(auto, "summit-shrine")
    assert reason.code == "does_not_fit"
    assert any("trek" in d for d in reason.details)


def test_ferry_departure_window_makes_you_wait_or_rules_the_trip_out(hill):
    early = plan_trip(hill, trip(places=("hill-market", "ferry-isle"), day_start=6 * 60, day_end=21 * 60))
    assert early.violations == []
    v = visit(early, "ferry-isle")
    ferry_at = v.leg.depart + v.leg.wait + v.leg.segments[0].minutes
    assert ferry_at >= 9 * 60 + 30                                  # nobody boards before the first ferry
    late = plan_trip(hill, trip(places=("ferry-isle",), day_start=13 * 60 + 30, day_end=21 * 60))
    assert late.stops == 0                                          # the last ferry (13:00) has gone


def test_validator_catches_a_ferry_boarded_before_it_runs(hill):
    plan = copy.deepcopy(plan_trip(hill, trip(places=("ferry-isle",))))
    v = visit(plan, "ferry-isle")
    v.leg.wait = 0
    v.leg.depart = 8 * 60                                           # would board at 08:15
    assert any("before" in p for p in check_itinerary(plan, hill))


def test_access_shows_in_the_api(client):
    data = client.get("/api/cities/kedarnath/attractions").get_json()
    temple = next(a for a in data if a["slug"] == "kedarnath-temple")
    assert temple["access"]["type"] == "trek" and temple["access"]["timed"]
    assert any(x["label"] == "Helicopter" for x in temple["access"]["alternatives"])
