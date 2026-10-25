"""Requirement 6: the plan responds to the available time window, and explains unused time."""

from datetime import date

import pytest

from conftest import DINNER, LUNCH, MONDAY, make_trip
from services.itinerary_generator import plan_trip


def stops(plan):
    return [v.attraction.slug for d in plan.days for v in d.visits]


def test_longer_window_allows_more_visits(tiny_city):
    short = plan_trip(tiny_city, make_trip(day_end=13 * 60))
    long = plan_trip(tiny_city, make_trip(day_end=20 * 60))
    assert short.violations == [] and long.violations == []
    assert len(stops(long)) > len(stops(short))
    assert "aarti" in stops(long)                                   # evening-only stop now fits


def test_extra_evening_legitimately_changes_nothing_when_everything_is_closed(tiny_city):
    """On a Monday every Testville sight closes by 20:00 and all of them already fit by 21:00."""
    by_21 = plan_trip(tiny_city, make_trip(day_end=21 * 60))
    by_2330 = plan_trip(tiny_city, make_trip(day_end=23 * 60 + 30))
    assert stops(by_21) == stops(by_2330)
    notes = by_2330.days[0].free_time_notes
    assert notes and "free after" in notes[0]                        # the unused evening is explained


@pytest.mark.parametrize("strategy", ["dp", "greedy", "max_visits"])
def test_stops_never_decrease_as_the_day_gets_longer(tiny_city, strategy):
    counts = []
    for end_hour in range(12, 24):
        plan = plan_trip(tiny_city, make_trip(day_end=end_hour * 60, strategy=strategy))
        assert plan.violations == []
        counts.append(len(stops(plan)))
    assert counts == sorted(counts), counts


def test_no_special_case_for_eleven_pm(tiny_city):
    """22:59, 23:00 and 23:01 behave the same way: the rule is general, not a hard-coded time."""
    plans = [plan_trip(tiny_city, make_trip(day_end=m)) for m in (22 * 60 + 59, 23 * 60, 23 * 60 + 1)]
    assert stops(plans[0]) == stops(plans[1]) == stops(plans[2])


def test_time_breakdown_adds_up_to_the_window(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=2, day_end=22 * 60, lunch=LUNCH, dinner=DINNER))
    assert plan.violations == []
    for day in plan.days:
        if not day.visits:
            continue
        parts = day.travel_min + day.sight_min + day.meal_min + day.wait_min + day.buffer_min + day.free_min
        assert parts == day.window_min and day.free_min >= 0
        assert day.free_after_min == day.day_end - day.end_time


def test_real_delhi_uses_a_longer_day(real_cities):
    city = real_cities["delhi"]
    trip = make_trip(city="delhi", start="delhi-stay-central", start_date=date(2026, 11, 3), day_start=10 * 60, lunch=LUNCH)
    short = plan_trip(city, trip.with_changes(day_end=19 * 60))
    long = plan_trip(city, trip.with_changes(day_end=23 * 60, dinner=DINNER))
    assert short.violations == [] and long.violations == []
    assert len(stops(long)) >= len(stops(short))
    assert long.days[0].end_time > short.days[0].end_time
