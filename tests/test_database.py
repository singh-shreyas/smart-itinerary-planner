"""SQLite schema, seeding (with validation) and queries."""

import os
import shutil
import sqlite3

import pytest

from conftest import DATA_DIR, FIXTURE_DIR
from database import queries
from database.db import connect, database_ready
from database.seed_data import SeedError, parse_days, seed_database


def test_fixture_seeds_with_expected_counts(tiny_db):
    conn = connect(tiny_db)
    counts = queries.summary_counts(conn)
    assert counts == {"cities": 6, "attractions": 33, "edges": 280, "categories": 26}
    city = queries.list_cities(conn)[0]                        # ordered by Top-50 rank
    assert (city["slug"], city["attraction_count"], city["stay_count"]) == ("testville", 8, 2)
    assert queries.get_city(conn, "nowhere") is None
    assert database_ready(tiny_db)


def test_queries_return_categories_and_hours(tiny_db):
    conn = connect(tiny_db)
    rows = {r["slug"]: r for r in queries.list_attractions(conn)}
    assert set(rows["fort"]["category_slugs"].split(",")) == {"history", "architecture"}
    museum_days = {h["weekday"] for h in queries.list_opening_hours(conn) if h["place_id"] == rows["museum"]["id"]}
    assert museum_days == {1, 2, 3, 4, 5, 6}                       # closed on Monday (0)
    temple_windows = [h for h in queries.list_opening_hours(conn) if h["place_id"] == rows["temple"]["id"] and h["weekday"] == 0]
    assert [(h["open_min"], h["close_min"]) for h in temple_windows] == [(360, 720), (960, 1200)]


def test_foreign_keys_and_checks_are_enforced(tiny_db):
    conn = connect(tiny_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO opening_hours (place_id, weekday, open_min, close_min) VALUES (9999, 0, 600, 700)")
    place = conn.execute("SELECT id FROM places WHERE slug = 'fort'").fetchone()["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO opening_hours (place_id, weekday, open_min, close_min) VALUES (?, 0, 700, 600)", (place,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE attractions SET fee_inr = -5 WHERE place_id = ?", (place,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO travel_edges (from_id, to_id, minutes, km, source) VALUES (?, ?, 5, 1, 'manual')", (place, place))
    conn.rollback()


def test_parse_days():
    assert parse_days("Daily") == [0, 1, 2, 3, 4, 5, 6]
    assert parse_days("Tue-Sun") == [1, 2, 3, 4, 5, 6]
    assert parse_days("Sat-Thu") == [0, 1, 2, 3, 5, 6]            # wraps past Sunday; Friday closed
    assert parse_days("Mon,Wed") == [0, 2]


def test_unreachable_place_is_reported_as_a_warning(tmp_path):
    summary = seed_database(str(tmp_path / "t.db"), FIXTURE_DIR)
    assert any("island" in w for w in summary["warnings"])
    with pytest.raises(SeedError):
        seed_database(str(tmp_path / "strict.db"), FIXTURE_DIR, strict=True)   # illustrative rows + warnings


@pytest.mark.parametrize("filename, bad_line, message", [
    ("opening_hours.csv", "testville,fort,Daily,17:00,09:00,\n", "opens at or after closing"),
    ("opening_hours.csv", "testville,ghost,Daily,09:00,17:00,\n", "unknown attraction"),
    ("travel_times.csv", "testville,fort,nowhere,5,1,manual\n", "unknown place"),
    ("travel_times.csv", "testville,fort,museum,-5,1,manual\n", "must be positive"),
    ("stay_areas.csv", "testville,far,Far away,south,20.0,20.0,approximate,\n", "km from the city centre"),
    ("stay_areas.csv", "testville,ns,New Stand,north,10.01,10.0,approximate,\n", "already has a north stay area"),
    ("stay_areas.csv", "testville,gx,Testville Junction,south,10.01,10.0,approximate,\n", "looks like a station"),
    ("stay_areas.csv", "testville,fx,Fort,south,10.01,10.0,approximate,\n", "is an attraction of testville"),
    ("access.csv", "testville,fort,teleport,no,,,,Beam me up.,\n", "access_type must be one of"),
    ("access_segments.csv", "hillview,hill-trailhead,summit-shrine,2,trek,-5,1,,estimate,Bad.,\n", "positive minutes"),
])
def test_invalid_rows_are_refused(tmp_path, filename, bad_line, message):
    data = tmp_path / "data"
    shutil.copytree(FIXTURE_DIR, data)
    with open(data / filename, "a", encoding="utf-8") as f:
        f.write(bad_line)
    with pytest.raises(SeedError) as excinfo:
        seed_database(str(tmp_path / "bad.db"), str(data))
    assert message in str(excinfo.value)
    assert not os.path.exists(tmp_path / "bad.db")                 # nothing half-built is left behind


def test_empty_database_is_not_ready(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    assert not database_ready(str(path))
    assert not database_ready(str(tmp_path / "missing.db"))


def test_real_data_is_valid_and_fully_connected(real_db, tmp_path):
    summary = seed_database(str(tmp_path / "again.db"), DATA_DIR)
    assert summary["cities"] == 50
    assert not [w for w in summary["warnings"] if "cannot be reached" in w]
    conn = connect(real_db)
    slugs = {r["slug"] for r in queries.list_cities(conn)}
    assert {"agra", "delhi", "jaipur", "varanasi", "mumbai", "pondicherry"} <= slugs
    # The original Delhi road graph is unchanged by the expansion: its 110 OSRM links between the original
    # attractions are all still there; new places (food, shopping, stay areas) only ADD links of their own.
    original = conn.execute("""
        SELECT COUNT(*) FROM travel_edges e
        JOIN places a ON a.id = e.from_id JOIN places b ON b.id = e.to_id
        LEFT JOIN attractions aa ON aa.place_id = a.id LEFT JOIN attractions ab ON ab.place_id = b.id
        WHERE a.city_id = (SELECT id FROM cities WHERE slug = 'delhi') AND e.scope = 'local' AND e.source = 'osrm'
          AND aa.description_source = 'project' AND ab.description_source = 'project'""").fetchone()[0]
    assert original == 110
    assert set(queries.edge_source_counts(conn, queries.get_city(conn, "delhi")["id"])) == {"osrm"}


def test_top50_list_matches_the_database(real_db):
    """Every destination in the team's Top-50 list is a city in the database (by catalog id)."""
    import csv
    with open(os.path.join(DATA_DIR, "catalog", "top50.csv"), encoding="utf-8") as f:
        top50 = {int(r["destination_id"]) for r in csv.DictReader(f)}
    conn = connect(real_db)
    assert {r["catalog_id"] for r in queries.list_cities(conn)} == top50


def test_every_value_has_a_source(real_db):
    conn = connect(real_db)
    for row in queries.list_attractions(conn):
        for column in ("rating_source", "popularity_source", "duration_source", "fee_source", "hours_source"):
            assert row[column], (row["slug"], column)
        assert (row["rating"] is None) == (row["rating_source"] == "none")      # no invented ratings
        if row["access_type"] != "road":
            assert row["access_note"], row["slug"]                             # every special access is explained


def test_slugs_are_unique_across_cities(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURE_DIR, data)
    with open(data / "stay_areas.csv", "a", encoding="utf-8") as f:
        f.write("riverton,hotel,Second Quarter,north,10.0,10.365,approximate,\n")
    with pytest.raises(SeedError) as excinfo:
        seed_database(str(tmp_path / "dup.db"), str(data))
    assert "duplicate slug hotel" in str(excinfo.value)
