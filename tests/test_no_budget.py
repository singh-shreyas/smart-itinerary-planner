"""Requirement 4: the budget feature is gone -- form, validation, planner, objectives and scores.

The planner optimises travel and time. These tests make sure no control,
parameter, constraint or score still depends on money.
"""

import inspect
from dataclasses import fields

import config
from algorithms.dynamic_programming import dp_select
from algorithms.greedy import greedy_select
from algorithms.knapsack_types import Item, SelectionResult
from conftest import make_trip
from services import scorecard
from services.itinerary_generator import plan_trip
from services.models import DayPlan, Itinerary, TripRequest
from services.trip_request import parse_trip


def test_budget_controls_are_not_in_the_ui(client):
    for page in ("/plan", "/plan?city=delhi", "/compare?city=agra&days=1&start_date=2026-11-02", "/"):
        html = client.get(page).get_data(as_text=True).lower()
        assert 'name="budget"' not in html and 'name="transport"' not in html and 'name="shop_spend"' not in html
        assert "daily budget" not in html and "budget efficiency" not in html


def test_requests_do_not_need_a_budget(client):
    response = client.get("/itinerary?city=jaipur&days=1&start_date=2026-11-02")
    assert response.status_code == 200
    api = client.get("/api/itinerary?city=jaipur&days=1&start_date=2026-11-02").get_json()
    assert "spend_inr" not in api["totals"] and all("spend_inr" not in d["totals"] for d in api["days"])


def test_an_old_url_with_a_budget_is_accepted_and_ignored(client):
    """Bookmarked links from before the change must keep working; the old value just has no effect."""
    plain = client.get("/api/itinerary?city=jaipur&days=1&start_date=2026-11-02").get_json()
    old = client.get("/api/itinerary?city=jaipur&days=1&start_date=2026-11-02&budget=0&transport=on&shop_spend=500").get_json()
    assert [d["visits"] for d in old["days"]] == [d["visits"] for d in plain["days"]]


def test_generation_works_without_any_budget_input(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=2, day_end=20 * 60))
    assert plan.violations == [] and plan.stops > 0


def test_trip_and_plan_models_have_no_money_fields():
    names = {f.name for f in fields(TripRequest)} | {f.name for f in fields(DayPlan)}
    assert not names & {"budget", "include_transport", "shop_spend", "transport_rate"}
    for cls in (DayPlan, Itinerary):
        assert not hasattr(cls, "spend") and not hasattr(cls, "transport_cost")
    assert "budget" not in parse_trip.__code__.co_names


def test_no_selector_takes_a_money_capacity():
    assert Item._fields == ("id", "score", "weight") and "cost" not in SelectionResult._fields
    for select in (dp_select, greedy_select):
        assert list(inspect.signature(select).parameters) == ["items", "time_cap"]
    assert list(inspect.signature(plan_trip).parameters) == ["city", "trip", "trace", "validate"]


def test_entry_fees_never_change_the_plan(tiny_city):
    """Make every place very expensive: the plan must be identical, because cost is not a constraint."""
    import copy
    pricey = copy.deepcopy(tiny_city)
    for a in pricey.attractions.values():
        a.fee = 99_999
    normal, expensive = plan_trip(tiny_city, make_trip()), plan_trip(pricey, make_trip())
    assert [[v.attraction.slug for v in d.visits] for d in normal.days] == \
           [[v.attraction.slug for v in d.visits] for d in expensive.days]


def test_scorecard_weights_are_valid_and_money_free():
    weights = config.SCORECARD_WEIGHTS
    assert set(weights) == {"value", "coverage", "travel", "utilisation"}
    assert abs(sum(weights.values()) - 1) < 1e-9 and all(w > 0 for w in weights.values())
    assert set(scorecard.METRIC_DIRECTIONS) == set(weights)


def test_unrelated_features_still_work(client):
    """Meals, nearby cities, interests and the comparison page are untouched by the removal."""
    response = client.get("/itinerary?city=agra&also=mathura&days=2&start_date=2026-11-02&interests=history"
                          "&lunch=on&dinner=on&day_end=21:00")
    assert response.status_code == 200
    assert "Lunch" in response.get_data(as_text=True)
    assert client.get("/compare?city=agra&days=1&start_date=2026-11-02").status_code == 200
