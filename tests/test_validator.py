"""The independent validator must catch every kind of broken itinerary."""

import copy

from conftest import RATE, make_trip
from services.itinerary_generator import plan_trip
from services.validator import check_itinerary


def valid_plan(tiny_city, **overrides):
    plan = plan_trip(tiny_city, make_trip(**overrides), RATE)
    assert plan.violations == []
    return plan


def test_valid_plan_passes(tiny_city):
    plan = valid_plan(tiny_city, days=2)
    assert check_itinerary(plan, tiny_city, RATE) == []


def test_visit_outside_opening_hours_is_caught(tiny_city):
    plan = copy.deepcopy(valid_plan(tiny_city))
    visit = plan.days[0].visits[0]
    visit.start -= 9 * 60                                   # move it into the early morning
    visit.end -= 9 * 60
    assert any("outside" in p for p in check_itinerary(plan, tiny_city, RATE))


def test_duplicate_visit_is_caught(tiny_city):
    plan = copy.deepcopy(valid_plan(tiny_city, days=2))
    plan.days[1].visits.insert(0, copy.deepcopy(plan.days[0].visits[0]))
    assert any("twice" in p for p in check_itinerary(plan, tiny_city, RATE))


def test_wrong_travel_time_is_caught(tiny_city):
    plan = copy.deepcopy(valid_plan(tiny_city))
    plan.days[0].visits[0].leg.minutes += 5
    assert any("travel table" in p for p in check_itinerary(plan, tiny_city, RATE))


def test_overrunning_the_day_is_caught(tiny_city):
    plan = copy.deepcopy(valid_plan(tiny_city))
    plan.trip = plan.trip.with_changes(day_end=plan.days[0].return_time - 1)
    assert any("after the day ends" in p for p in check_itinerary(plan, tiny_city, RATE))


def test_budget_overrun_is_caught(tiny_city):
    plan = copy.deepcopy(valid_plan(tiny_city))
    plan.trip = plan.trip.with_changes(budget=1)
    assert any("more than the" in p for p in check_itinerary(plan, tiny_city, RATE))


def test_unexplained_attraction_is_caught(tiny_city):
    plan = copy.deepcopy(valid_plan(tiny_city))
    plan.skipped = plan.skipped[1:]
    assert any("neither planned nor explained" in p for p in check_itinerary(plan, tiny_city, RATE))
