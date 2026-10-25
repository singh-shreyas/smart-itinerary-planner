"""Requirement 3: five stay areas per city, kept apart from attractions and transport points."""

import csv
import os
import re

import pytest

from conftest import DATA_DIR, MONDAY
from database import queries
from database.db import connect
from services.city_data import clear_cache, get_city_data
from services.itinerary_generator import plan_trip
from services.models import TripRequest

DIRECTIONS = {"north", "south", "east", "west", "central"}


def rows(name):
    with open(os.path.join(DATA_DIR, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def stays_by_city(real_db):
    conn = connect(real_db)
    out = {}
    for r in queries.list_cities(conn):
        out[r["slug"]] = [p for p in queries.list_places_in(conn, [r["id"]]) if p["kind"] == "stay"]
    return out


def test_1_every_city_has_five_stay_areas(stays_by_city):
    assert len(stays_by_city) == 50
    for city, stays in stays_by_city.items():
        assert len(stays) == 5, city


def test_2_one_per_direction_and_no_duplicates(stays_by_city):
    for city, stays in stays_by_city.items():
        assert {s["direction"] for s in stays} == DIRECTIONS, city
        assert len({s["name"].lower() for s in stays}) == 5, city
        assert len({(round(s["lat"], 4), round(s["lng"], 4)) for s in stays}) == 5, city
        for s in stays:
            assert s["coord_source"] == "openstreetmap" and s["source_url"].startswith("https://www.openstreetmap.org/")


def test_3_no_attraction_is_a_stay_area(stays_by_city):
    names = {}
    for a in rows("attractions.csv"):
        names.setdefault(a["city"], set()).add(a["name"].lower())
    for city, stays in stays_by_city.items():
        assert not {s["name"].lower() for s in stays} & names.get(city, set()), city


def test_4_no_station_airport_or_placeholder(stays_by_city):
    bad = re.compile(r"station|railway|junction|airport|terminal|hotel area|city centre|town centre", re.I)
    for city, stays in stays_by_city.items():
        assert not [s["name"] for s in stays if bad.search(s["name"])], city
    transport = {r["slug"] for r in rows("transport_points.csv")}
    assert transport and not transport & {s["slug"] for ss in stays_by_city.values() for s in ss}


def test_unusual_directions_are_labelled(stays_by_city):
    """A stay area that is not really in its direction carries a note that says where it is."""
    for city, stays in stays_by_city.items():
        for s in stays:
            if s["direction"] == "central" or s["bearing"] is None:
                continue
            target = {"north": 0, "east": 90, "south": 180, "west": 270}[s["direction"]]
            gap = abs((s["bearing"] - target + 180) % 360 - 180)
            if gap > 45:
                assert s["direction_note"], (city, s["name"], s["bearing"])


def test_5_and_6_the_stay_area_is_the_origin_of_every_travel_time(real_cities):
    delhi = real_cities["delhi"]
    stays = delhi.stays
    base = dict(city="delhi", start_date=MONDAY, days=1, day_start=540, day_end=1140, interests=(), pace="balanced",
                strategy="dp", places=("red-fort", "qutub-minar"), mode="optimized")
    plans = {s.slug: plan_trip(delhi, TripRequest(start=s.slug, **base)) for s in stays}
    for slug, plan in plans.items():
        assert plan.violations == []
        day = plan.days[0]
        first = day.visits[0]
        here = delhi.place(slug).id
        assert first.leg.from_id == here and day.return_leg.to_id == here
        assert first.leg.minutes == delhi.plan[here][first.attraction.id]       # straight from the travel table
        assert first.leg.km == round(delhi.km[here][first.attraction.id], 2)
    travel = {slug: p.travel_min for slug, p in plans.items()}
    assert len(set(travel.values())) > 1                                       # different areas, different travel


def test_7_the_planner_form_offers_only_the_citys_stay_areas(client):
    import json
    html = client.get("/plan?city=agra").get_data(as_text=True)
    options = json.loads(html.split('<script id="city-options" type="application/json">')[1].split("</script>")[0])
    for slug, city in options.items():
        assert len(city["stays"]) == 5 and all(s["label"].endswith(")") or s["label"].endswith("*)") for s in city["stays"])
    agra = {s["slug"] for s in options["agra"]["stays"]}
    delhi = {s["slug"] for s in options["delhi"]["stays"]}
    assert not agra & delhi
    response = client.get(f"/itinerary?city=delhi&start={sorted(agra)[0]}&days=1")
    assert response.status_code == 400 and "stay areas in Delhi" in response.get_data(as_text=True)
    attraction = client.get("/itinerary?city=delhi&start=red-fort&days=1")
    assert attraction.status_code == 400                                      # a sight is never a stay


def test_8_attraction_data_is_intact():
    """Moving the old access columns out of attractions.csv changed no attraction row."""
    attractions = rows("attractions.csv")
    assert len(attractions) == 346 and len({(a["city"], a["slug"]) for a in attractions}) == 346
    assert "access" not in attractions[0] and "access_note" not in attractions[0]


def test_9_caches_follow_the_database(real_db, tmp_path):
    """The travel tables are cached per database file version: a rebuilt database is never served stale."""
    import shutil
    import time as _time
    copy = str(tmp_path / "copy.db")
    shutil.copy(real_db, copy)
    clear_cache()
    conn = connect(copy)
    first = get_city_data(conn, copy, "agra", 1.5)
    assert get_city_data(conn, copy, "agra", 1.5) is first                    # cached
    conn.close()
    _time.sleep(1.1)
    conn = sqlite3_touch(copy)
    second = get_city_data(conn, copy, "agra", 1.5)
    assert second is not first                                                 # new file version -> rebuilt
    conn.close()


def sqlite3_touch(path):
    """Change a row so the file's modification time moves on, as a rebuild would."""
    conn = connect(path)
    conn.execute("UPDATE meta SET value = value WHERE key = 'built_at'")
    conn.commit()
    os.utime(path, None)
    return conn


def test_no_old_start_points_remain(real_db):
    conn = connect(real_db)
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT kind FROM places")}
    assert kinds <= {"attraction", "stay", "transport", "access"}
    for old in ("cp-start", "tajganj-start", "colaba-hotel-area-start", "ayodhya-city-centre-start"):
        assert conn.execute("SELECT COUNT(*) FROM places WHERE slug = ?", (old,)).fetchone()[0] == 0
    assert not os.path.exists(os.path.join(DATA_DIR, "start_points.csv"))
    # Every stay area is a node of the road graph: it has road links in both directions.
    missing = conn.execute("""
        SELECT p.slug FROM places p WHERE p.kind = 'stay'
          AND (NOT EXISTS (SELECT 1 FROM travel_edges e WHERE e.from_id = p.id)
               OR NOT EXISTS (SELECT 1 FROM travel_edges e WHERE e.to_id = p.id))""").fetchall()
    assert missing == []
