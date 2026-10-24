"""Flask routes: every page renders, bad input gives 400 (never 500), unknown things give 404."""

import pytest

VALID = "/itinerary?city=delhi&days=2&start_date=2026-11-02&start=cp-start"


@pytest.mark.parametrize("url", [
    "/", "/cities", "/attractions", "/attractions?city=jaipur", "/attractions?city=agra&category=history&q=tomb&open_on=4&sort=fee",
    "/plan", "/plan?city=varanasi", "/about", "/compare", "/compare?city=agra&days=1&start_date=2026-11-06",
])
def test_pages_render(client, url):
    response = client.get(url)
    assert response.status_code == 200
    assert b"Smart Itinerary" in response.data


def test_city_shortcut_redirects_to_attractions(client):
    response = client.get("/cities/delhi")
    assert response.status_code == 302 and "/attractions?city=delhi" in response.headers["Location"]


@pytest.mark.parametrize("url", ["/cities/atlantis", "/attractions?city=atlantis", "/plan?city=atlantis", "/no-such-page"])
def test_unknown_things_are_404(client, url):
    response = client.get(url)
    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_valid_itinerary(client):
    response = client.get(VALID)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Day 1" in html and "Day 2" in html
    assert "All constraints verified" in html
    assert "straight lines, not the road path" in html


@pytest.mark.parametrize("query, field_message", [
    ("city=delhi&days=0", "Plan between 1 and 5 days"),
    ("city=delhi&days=6", "Plan between 1 and 5 days"),
    ("city=delhi&days=abc", "whole number"),
    ("city=delhi&day_start=18:00&day_end=17:00", "at least 2 hours"),
    ("city=delhi&day_start=25:00", "HH:MM"),
    ("city=delhi&budget=-50", "cannot be negative"),
    ("city=delhi&budget=lots", "whole number of rupees"),
    ("city=delhi&interests=shopping-malls", "Unknown interest"),
    ("city=delhi&start=godowlia-start", "starting point in this city"),
    ("city=delhi&start_date=2026-13-45", "YYYY-MM-DD"),
    ("city=delhi&pace=sprint", "relaxed, balanced or packed"),
    ("city=delhi&strategy=random", "Unknown selection strategy"),
    ("city=delhi&exclude=taj-mahal", "Not an attraction in Delhi"),
    ("city=atlantis", "have data for that city"),
    ("", "Choose a destination city"),
])
def test_invalid_input_is_a_400_with_a_message(client, query, field_message):
    response = client.get(f"/itinerary?{query}")
    assert response.status_code == 400
    assert field_message in response.get_data(as_text=True)


def test_invalid_form_keeps_the_users_values(client):
    response = client.get("/itinerary?city=jaipur&days=9&budget=750&pace=relaxed")
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert 'value="750"' in html
    assert 'id="pace-relaxed" value="relaxed" checked' in html


def test_excluding_everything_is_refused(client, app):
    with app.app_context():
        from routes.helpers import city_data
        everything = ",".join(a.slug for a in city_data("agra").attractions.values())
    response = client.get(f"/itinerary?city=agra&exclude={everything}")
    assert response.status_code == 400 and "Keep at least one attraction" in response.get_data(as_text=True)


def test_api_health_and_cities(client):
    assert client.get("/api/health").get_json() == {"status": "ok", "cities": 4}
    cities = client.get("/api/cities").get_json()
    assert {c["slug"] for c in cities} == {"agra", "delhi", "jaipur", "varanasi"}
    attractions = client.get("/api/cities/agra/attractions").get_json()
    taj = next(a for a in attractions if a["slug"] == "taj-mahal")
    assert "Fri" not in taj["hours"]                                   # closed on Fridays


def test_api_itinerary_shape(client):
    data = client.get("/api/itinerary?city=varanasi&days=2&start_date=2026-11-02").get_json()
    assert set(data) >= {"city", "strategy", "days", "totals", "skipped", "violations", "illustrative"}
    assert data["violations"] == []
    assert data["days"][0]["visits"] and set(data["days"][0]["visits"][0]) >= {"slug", "arrive", "start", "end", "leave", "travel_min"}


def test_api_errors_are_json(client):
    response = client.get("/api/itinerary?city=delhi&days=0")
    assert response.status_code == 400 and "days" in response.get_json()["errors"]
    missing = client.get("/api/cities/atlantis/attractions")
    assert missing.status_code == 404 and missing.get_json() == {"error": "not found"}


def test_api_compare(client):
    data = client.get("/api/compare?city=agra&days=1&start_date=2026-11-02").get_json()
    assert data["dijkstra"]["mismatches"] == 0
    assert {s["key"] for s in data["strategies"]} == {"dp", "greedy", "max_visits"}


def test_friday_plan_in_agra_skips_the_taj(client):
    data = client.get("/api/itinerary?city=agra&days=1&start_date=2026-11-06").get_json()   # a Friday
    assert all(v["slug"] != "taj-mahal" for v in data["days"][0]["visits"])
    assert any(s["slug"] == "taj-mahal" and s["reason"] == "closed" for s in data["skipped"])
