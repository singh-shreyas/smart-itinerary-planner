"""Requirement 11: lunch and dinner as their own schedule entries."""

import copy

import pytest

from conftest import DINNER, LUNCH, make_trip
from services.itinerary_generator import plan_trip
from services.models import MealBreak, MealSetting
from services.validator import check_itinerary

ALL_BUT_GARDEN = ("fort", "museum", "temple", "island", "aarti", "palace")


@pytest.mark.parametrize("start, end, lunch_needed, dinner_needed", [
    ("09:00", "19:00", True, False),     # day ends before dinner could not be had afterwards
    ("09:00", "23:00", True, True),
    ("13:00", "22:00", False, True),     # lunch could be had before 13:00
    ("09:00", "13:30", False, False),    # lunch could be had after 13:30
    ("12:30", "16:00", True, False),
    ("09:00", "20:30", True, False),     # dinner can still start at 20:30 after the day
    ("09:00", "20:31", True, True),
])
def test_meal_is_planned_only_when_it_cannot_be_had_outside_the_day(start, end, lunch_needed, dinner_needed):
    def minutes(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    assert LUNCH.needed(minutes(start), minutes(end)) is lunch_needed
    assert DINNER.needed(minutes(start), minutes(end)) is dinner_needed


def meals(day):
    return {m.kind: m for m in day.meals}


def test_lunch_is_a_separate_entry_inside_its_window(tiny_city):
    plan = plan_trip(tiny_city, make_trip(lunch=LUNCH, dinner=DINNER))
    assert plan.violations == []
    day = plan.days[0]
    lunch = meals(day)["lunch"]
    assert 12 * 60 <= lunch.start <= LUNCH.latest_start and lunch.end == lunch.start + 45 <= 14 * 60 + 30
    assert "dinner" not in meals(day)                                    # a 09:00-19:00 day gets no dinner
    entries = day.timeline
    for a, b in zip(entries, entries[1:]):
        assert b.start >= a.end                                         # nothing overlaps the meal
    assert isinstance(entries[[e is lunch for e in entries].index(True)], MealBreak)


def test_meal_goes_to_a_nearby_listed_food_place(tiny_city):
    """Garden ends 12:30 (+15 buffer); Chaat Street is 10 planned minutes away and open: lunch goes there."""
    trip = make_trip(day_start=11 * 60, day_end=15 * 60, exclude=ALL_BUT_GARDEN, lunch=LUNCH, veg_only=True)
    plan = plan_trip(tiny_city, trip)
    assert plan.violations == []
    lunch = meals(plan.days[0])["lunch"]
    assert lunch.venue is not None and lunch.venue.slug == "chaat-street"
    assert lunch.leg is not None and lunch.leg.purpose == "meal" and lunch.leg.minutes == 10
    assert lunch.start == lunch.leg.depart + lunch.leg.minutes          # the detour is a travel leg of its own
    assert plan.days[0].return_leg.from_id == lunch.venue.id            # and the day continues from there


def test_without_venue_suggestions_the_break_is_generic(tiny_city):
    trip = make_trip(day_start=11 * 60, day_end=15 * 60, exclude=ALL_BUT_GARDEN, lunch=LUNCH, food_venues=False)
    plan = plan_trip(tiny_city, trip)
    lunch = meals(plan.days[0])["lunch"]
    assert lunch.venue is None and lunch.leg is None and lunch.location_name == "Garden"
    assert plan.violations == []


def test_meals_after_returning_are_taken_near_the_base(tiny_city):
    """Only the fort is left: back at 10:35, so lunch and dinner are taken near the hotel later."""
    trip = make_trip(day_end=22 * 60, exclude=ALL_BUT_GARDEN[1:] + ("garden",), lunch=LUNCH, dinner=DINNER)
    plan = plan_trip(tiny_city, trip)
    assert plan.violations == []
    day = plan.days[0]
    assert [v.attraction.slug for v in day.visits] == ["fort"]
    by_kind = meals(day)
    assert by_kind["lunch"].at_base and by_kind["dinner"].at_base
    assert by_kind["lunch"].start == 12 * 60 and by_kind["dinner"].start == 19 * 60
    assert day.end_time == 20 * 60 and day.return_time < 12 * 60


def test_a_long_visit_never_swallows_lunch(tiny_city):
    """The 2-hour palace would run through a 12:00-13:00 lunch window, so lunch comes first."""
    short_lunch = MealSetting("lunch", 12 * 60, 13 * 60, 30)
    keep = ("fort", "museum", "temple", "island", "aarti", "garden")
    plan = plan_trip(tiny_city, make_trip(day_start=11 * 60 + 30, day_end=17 * 60, exclude=keep, lunch=short_lunch))
    assert plan.violations == []
    kinds = ["meal" if isinstance(e, MealBreak) else e.attraction.slug for e in plan.days[0].timeline]
    assert kinds == ["meal", "palace"]


def test_meal_time_is_reserved_in_the_knapsack(tiny_city):
    trace_without, trace_with = [], []
    plan_trip(tiny_city, make_trip(), trace=trace_without)
    plan_trip(tiny_city, make_trip(lunch=LUNCH), trace=trace_with)
    cap_without = trace_without[0]["instance"].time_cap
    cap_with = trace_with[0]["instance"].time_cap
    assert trace_with[0]["instance"].reserved["meals"] == 45
    assert cap_with < cap_without


def test_validator_catches_a_meal_outside_its_window(tiny_city):
    plan = copy.deepcopy(plan_trip(tiny_city, make_trip(lunch=LUNCH)))
    meal = meals(plan.days[0])["lunch"]
    meal.start, meal.end = 15 * 60, 15 * 60 + 45
    assert any("lunch" in p.lower() for p in check_itinerary(plan, tiny_city))


def test_validator_catches_a_missing_meal(tiny_city):
    plan = copy.deepcopy(plan_trip(tiny_city, make_trip(lunch=LUNCH)))
    day = plan.days[0]
    day.timeline = [e for e in day.timeline if not isinstance(e, MealBreak)]
    day.meals = []
    assert any("lunch appears 0 times" in p for p in check_itinerary(plan, tiny_city))
