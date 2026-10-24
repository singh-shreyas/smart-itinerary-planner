"""Requirements 8 and 10: interests change selection; food and shopping are optional and honest."""

from algorithms.scoring import attraction_score, expand_categories, matches_interests
from conftest import RATE, make_trip
from services.itinerary_generator import plan_trip, trip_context

PARENTS = {"street-food": "food", "cafes": "food", "trekking": "adventure"}
WEIGHTS = (0.5, 0.3, 0.2)


def skipped(plan):
    return {s.attraction.slug: s for s in plan.skipped}


def test_category_hierarchy_matches_upwards_only():
    assert expand_categories(["street-food"], PARENTS) == {"street-food", "food"}
    assert matches_interests(["street-food"], ["food"], PARENTS)        # a street-food place suits a food lover
    assert not matches_interests(["food"], ["street-food"], PARENTS)    # a generic food place is not street food
    assert matches_interests(["history", "trekking"], ["adventure"], PARENTS)


def test_unrated_places_use_the_neutral_prior():
    assert attraction_score(None, 0.5, ("nature",), (), WEIGHTS, prior=4.0) == attraction_score(4.0, 0.5, ("nature",), (), WEIGHTS)


def test_interests_change_the_score_for_multi_category_places():
    plain = attraction_score(4.0, 0.5, ("history", "architecture"), (), WEIGHTS)
    assert attraction_score(4.0, 0.5, ("history", "architecture"), ("architecture",), WEIGHTS) == plain + 20
    assert attraction_score(4.0, 0.5, ("history", "architecture"), ("history", "architecture"), WEIGHTS) == plain + 20


def test_food_places_are_opt_in(tiny_city):
    plan = plan_trip(tiny_city, make_trip(day_end=21 * 60), RATE)
    assert skipped(plan)["chaat-street"].code == "opt_in"
    with_food = plan_trip(tiny_city, make_trip(day_end=21 * 60, interests=("food",)), RATE)
    assert "chaat-street" not in skipped(with_food) or skipped(with_food)["chaat-street"].code != "opt_in"
    assert with_food.violations == []


def test_only_matching_interests_mode_removes_the_rest(tiny_city):
    plan = plan_trip(tiny_city, make_trip(day_end=21 * 60, interests=("spirituality",), interest_mode="only"), RATE)
    assert plan.violations == []
    assert {v.attraction.slug for v in plan.visits} <= {"temple", "aarti"}
    assert skipped(plan)["fort"].code == "interest"


def test_interest_with_no_or_little_data_is_reported(tiny_city):
    plan = plan_trip(tiny_city, make_trip(interests=("nightlife", "spirituality", "history")), RATE)
    notes = {n["interest"]: n for n in plan.interest_notes}
    assert notes["nightlife"]["count"] == 0 and "cannot change your plan" in notes["nightlife"]["text"]
    assert notes["spirituality"]["count"] == 2                       # temple and evening aarti: limited data
    assert notes["history"]["count"] == 2                            # fort and palace
    assert "Fort" in notes["history"]["text"]


def test_interest_with_enough_data_is_not_flagged(tiny_area):
    area = tiny_area("testville", "riverton")                       # fort, palace and river fort: 3 places
    plan = plan_trip(area, make_trip(extra_cities=("riverton",), interests=("history",)), RATE)
    assert plan.interest_notes == []


def test_shopping_time_and_spend_are_used(tiny_area):
    area = tiny_area("testville", "riverton")
    trip = make_trip(extra_cities=("riverton",), interests=("markets",), shop_minutes=90, shop_spend=300,
                     exclude=("fort", "museum", "temple", "garden", "aarti", "palace", "river-fort", "river-ghat"))
    plan = plan_trip(area, trip, RATE)
    assert plan.violations == []
    visit = next(v for v in plan.visits if v.attraction.slug == "spice-market")
    assert visit.end - visit.start == 90
    day = next(d for d in plan.days if visit in d.visits)
    assert day.shopping_spend == 300 and day.spend(False) == day.fees + 300
    over = plan_trip(area, trip.with_changes(budget=200), RATE)
    assert skipped(over)["spice-market"].code == "over_budget"       # the planned spend counts in the budget


def test_vegetarian_filter_uses_only_explicit_data(tiny_area):
    area = tiny_area("testville", "riverton")
    from conftest import LUNCH
    venues = dict((area.attractions[a].slug, r) for r, a in trip_context(area, make_trip(lunch=LUNCH, veg_only=True)).venues)
    assert "chaat-street" in venues and "river-cafe" not in venues    # the cafe's menu is unknown, so not "vegetarian"
    styled = dict((area.attractions[a].slug, r) for r, a in
                  trip_context(area, make_trip(lunch=LUNCH, venue_styles=("cafe-bakery",))).venues)
    assert styled["river-cafe"] == 0 and styled["chaat-street"] == 1  # preferred style ranks first
