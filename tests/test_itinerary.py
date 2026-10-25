"""The full planning pipeline: multi-day plans, opening hours, unreachable places, edge cases."""

import random
from datetime import date, timedelta

import pytest

from conftest import MONDAY, make_trip
from routes.helpers import itinerary_to_dict
from services.comparison import run_comparison
from services.itinerary_generator import plan_trip
from services.models import TripRequest


def slugs(day):
    return [v.attraction.slug for v in day.visits]


def skipped(itinerary):
    return {s.attraction.slug: s for s in itinerary.skipped}


def test_single_day_plan_is_valid(tiny_city):
    plan = plan_trip(tiny_city, make_trip())
    assert plan.violations == []
    assert plan.stops >= 3
    assert "island" not in slugs(plan.days[0])


def test_multi_day_plan_never_repeats_and_uses_each_weekday(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=3, day_end=20 * 60))
    assert plan.violations == []
    visited = [s for day in plan.days for s in slugs(day)]
    assert len(visited) == len(set(visited))
    assert [d.date.weekday() for d in plan.days] == [0, 1, 2]
    assert "museum" not in slugs(plan.days[0])                   # closed on Mondays


def test_closed_attraction_is_explained(tiny_city):
    plan = plan_trip(tiny_city, make_trip())                # Monday only
    reason = skipped(plan)["museum"]
    assert reason.code == "closed" and "Monday" in reason.reason


def test_unreachable_place_is_never_routed(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=3))
    assert all("island" not in slugs(d) for d in plan.days)
    assert skipped(plan)["island"].code == "unreachable"


def test_entry_fee_never_limits_the_plan(tiny_city):
    plan = plan_trip(tiny_city, make_trip())
    assert "palace" in slugs(plan.days[0])                        # Rs 600 entry: cost is not a constraint


def test_evening_only_stop_is_scheduled_last(tiny_city):
    plan = plan_trip(tiny_city, make_trip(day_end=20 * 60, interests=("spirituality",)))
    day = plan.days[0]
    assert "aarti" in slugs(day) and slugs(day)[-1] == "aarti"
    assert day.visits[-1].start >= 18 * 60
    assert plan.violations == []


def test_days_beyond_the_attractions_are_empty_with_a_reason(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=5, day_end=20 * 60))
    empty = [d for d in plan.days if not d.visits]
    assert empty, "6 reachable attractions cannot fill 5 days"
    assert all(d.empty_reason for d in empty)
    assert any("already in your plan" in d.empty_reason for d in empty)


def test_too_short_a_day_gives_an_empty_day_and_a_suggestion(tiny_city):
    plan = plan_trip(tiny_city, make_trip(day_start=20 * 60, day_end=22 * 60 + 30))
    day = plan.days[0]
    assert not day.visits and day.empty_reason
    assert any("End the day" in s["label"] for s in day.suggestions)


def test_excluded_attractions_are_left_out(tiny_city):
    plan = plan_trip(tiny_city, make_trip(exclude=("fort", "palace")))
    assert not {"fort", "palace"} & set(slugs(plan.days[0]))
    assert skipped(plan)["fort"].code == "excluded"


def test_every_attraction_is_planned_or_explained(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=2))
    planned = {v.attraction.id for v in plan.visits}
    explained = {s.attraction.id for s in plan.skipped}
    assert planned | explained == set(tiny_city.attractions)
    assert not planned & explained


def test_time_and_travel_add_up_without_double_counting(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=2, day_end=20 * 60))
    for day in plan.days:
        if not day.visits:
            continue
        assert day.travel_min == sum(v.leg.minutes for v in day.visits) + day.return_leg.minutes
        assert day.return_time - day.depart == day.travel_min + day.sight_min + day.wait_min + day.buffer_min


def test_plans_are_deterministic(real_cities):
    trip = TripRequest(city="delhi", start_date=MONDAY, days=3, day_start=540, day_end=1140,
                       interests=("history",), pace="relaxed", start="delhi-stay-central",
                       strategy="dp")
    first = itinerary_to_dict(plan_trip(real_cities["delhi"], trip))
    second = itinerary_to_dict(plan_trip(real_cities["delhi"], trip))
    first.pop("runtime_ms"), second.pop("runtime_ms")
    assert first == second


@pytest.mark.parametrize("strategy", ["dp", "greedy", "max_visits"])
def test_random_trips_on_real_data_always_validate(real_cities, strategy):
    """Stress test: random trips on the real cities (random stay area, mode and picked places)
    must never break any constraint."""
    rng = random.Random(2026)
    categories = ["history", "architecture", "spirituality", "nature", "museums", "markets"]
    for _ in range(40):
        slug = rng.choice(sorted(real_cities))
        city = real_cities[slug]
        start_hour = rng.randint(6, 12)
        trip = TripRequest(
            city=slug, start_date=date(2026, 11, 1) + timedelta(days=rng.randint(0, 6)), days=rng.randint(1, 5),
            day_start=start_hour * 60, day_end=min(23 * 60 + 59, (start_hour + rng.randint(2, 13)) * 60),
            interests=tuple(rng.sample(categories, rng.randint(0, 2))), pace=rng.choice(["relaxed", "balanced", "packed"]),
            start=rng.choice([p.slug for p in city.stays]), strategy=strategy,
            mode=rng.choice(["evenly", "suggested", "optimized"]),
            places=tuple(sorted(rng.sample([a.slug for a in city.attractions.values() if a.timed], 4)))
            if rng.random() < 0.4 else ())
        plan = plan_trip(city, trip)
        assert plan.violations == [], (trip, plan.violations)


def test_comparison_runs_on_identical_input(real_cities, tmp_path):
    trip = TripRequest(city="agra", start_date=MONDAY, days=2, day_start=540, day_end=1140,
                       interests=(), pace="balanced", start="agra-stay-east", strategy="dp")
    result = run_comparison(real_cities["agra"], trip, str(tmp_path), repeats=1)
    assert [s["key"] for s in result["strategies"]] == ["dp", "greedy", "max_visits"]
    assert all(s["metrics"]["violations"] == 0 for s in result["strategies"])
    for row in result["selection"]:
        assert row["dp"]["score"] >= row["greedy"]["score"]            # same instance: DP is never worse
    for row in result["routing"]:
        assert row["two_opt"]["travel"] <= row["nn"]["travel"]
        if row["held_karp"]:
            assert row["held_karp"]["travel"] <= row["two_opt"]["travel"]
    assert result["dijkstra"]["mismatches"] == 0
    assert result["trap"]["greedy"]["score"] == 90 and result["trap"]["dp"]["score"] == 120
    assert result["benchmarks"] is None                                 # empty results folder
