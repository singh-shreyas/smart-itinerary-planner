"""Every SQL query the application runs.

All values are passed as ? parameters (never formatted into the SQL string),
which prevents SQL injection. Functions take an open connection and return
sqlite3.Row objects or plain lists. Where a query takes several city ids, only
the right number of "?" placeholders is generated -- the ids themselves are
still passed as parameters.
"""

import sqlite3


def _ids(city_ids):
    """Normalise None / one id / a list of ids to a tuple (or None for 'all cities')."""
    if city_ids is None:
        return None
    if isinstance(city_ids, int):
        return (city_ids,)
    return tuple(city_ids)


def _in(ids):
    return "(" + ", ".join("?" for _ in ids) + ")"


def list_cities(conn):
    """Cities with their attraction and stay-area counts, in Top-50 order."""
    return conn.execute(
        """
        SELECT c.*,
               SUM(CASE WHEN p.kind = 'attraction' THEN 1 ELSE 0 END) AS attraction_count,
               SUM(CASE WHEN p.kind = 'stay' THEN 1 ELSE 0 END)       AS stay_count
        FROM cities c
        LEFT JOIN places p ON p.city_id = c.id
        GROUP BY c.id
        ORDER BY COALESCE(c.top_rank, 999), c.name
        """
    ).fetchall()


def get_city(conn, slug):
    return conn.execute("SELECT * FROM cities WHERE slug = ?", (slug,)).fetchone()


def list_categories(conn):
    return conn.execute("SELECT * FROM categories ORDER BY id").fetchall()


def list_attractions(conn, city_ids=None):
    """Attractions joined with their place row, city slug and category slugs.

    city_ids: None for every city, one id, or a list of ids.
    category_slugs is a comma-separated string (GROUP_CONCAT), split by the caller.
    """
    sql = """
        SELECT p.id, p.slug, p.name, p.lat, p.lng, p.city_id, p.coord_source,
               c.slug AS city_slug, c.name AS city_name,
               a.rating, a.rating_source, a.popularity, a.popularity_source, a.pageviews_12m,
               a.visit_minutes, a.duration_source, a.fee_inr, a.fee_source, a.hours_source,
               a.description, a.description_source,
               a.image_path, a.image_credit, a.image_source_url, a.info_url, a.wikidata, a.place_type,
               a.cuisine, a.vegetarian, a.in_team_catalog, a.data_status,
               a.access_type, a.road_access, a.access_point_id, a.access_modes, a.access_timing,
               a.last_mile_m, a.access_note, a.access_source_url,
               (SELECT GROUP_CONCAT(cat.slug, ',')
                  FROM attraction_categories ac
                  JOIN categories cat ON cat.id = ac.category_id
                 WHERE ac.place_id = p.id) AS category_slugs
        FROM places p
        JOIN attractions a ON a.place_id = p.id
        JOIN cities c ON c.id = p.city_id
    """
    ids = _ids(city_ids)
    params = ()
    if ids is not None:
        sql += f" WHERE p.city_id IN {_in(ids)}"
        params = ids
    sql += " ORDER BY COALESCE(c.top_rank, 999), c.name, p.id"
    return conn.execute(sql, params).fetchall()


def list_opening_hours(conn, city_ids=None):
    sql = """
        SELECT h.place_id, h.weekday, h.open_min, h.close_min, h.last_entry_min
        FROM opening_hours h
        JOIN places p ON p.id = h.place_id
    """
    ids = _ids(city_ids)
    params = ()
    if ids is not None:
        sql += f" WHERE p.city_id IN {_in(ids)}"
        params = ids
    sql += " ORDER BY h.place_id, h.weekday, h.open_min"
    return conn.execute(sql, params).fetchall()


def list_places(conn, city_id, kind=None):
    sql = "SELECT * FROM places WHERE city_id = ?"
    params = [city_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY id"
    return conn.execute(sql, params).fetchall()


def list_places_in(conn, city_ids):
    """Places of several cities, each with its city slug and name (and direction, for stay areas)."""
    ids = _ids(city_ids)
    return conn.execute(
        f"""
        SELECT p.*, c.slug AS city_slug, c.name AS city_name,
               s.direction, s.direction_note, s.osm_place, s.hotels_nearby, s.distance_km, s.bearing
        FROM places p JOIN cities c ON c.id = p.city_id
        LEFT JOIN stay_areas s ON s.place_id = p.id
        WHERE p.city_id IN {_in(ids)}
        ORDER BY p.id
        """,
        ids,
    ).fetchall()


def list_edges(conn, city_ids):
    """Road links whose two ends both lie in the given cities (local and intercity)."""
    ids = _ids(city_ids)
    return conn.execute(
        f"""
        SELECT e.from_id, e.to_id, e.minutes, e.km, e.source, e.scope
        FROM travel_edges e
        JOIN places a ON a.id = e.from_id
        JOIN places b ON b.id = e.to_id
        WHERE a.city_id IN {_in(ids)} AND b.city_id IN {_in(ids)}
        ORDER BY e.from_id, e.to_id
        """,
        ids + ids,
    ).fetchall()


def list_access_segments(conn, city_ids):
    """The parts of every non-road link in the given cities, in order."""
    ids = _ids(city_ids)
    return conn.execute(
        f"""
        SELECT g.* FROM access_segments g JOIN places p ON p.id = g.from_id
        WHERE p.city_id IN {_in(ids)}
        ORDER BY g.from_id, g.to_id, g.seq
        """,
        ids,
    ).fetchall()


def list_access_alternatives(conn, city_ids=None):
    sql = "SELECT x.* FROM access_alternatives x JOIN places p ON p.id = x.place_id"
    ids = _ids(city_ids)
    params = ()
    if ids is not None:
        sql += f" WHERE p.city_id IN {_in(ids)}"
        params = ids
    return conn.execute(sql + " ORDER BY x.place_id, x.id", params).fetchall()


def summary_counts(conn):
    """Totals for the landing and about pages."""
    row = conn.execute(
        """
        SELECT (SELECT COUNT(*) FROM cities)        AS cities,
               (SELECT COUNT(*) FROM attractions)   AS attractions,
               (SELECT COUNT(*) FROM travel_edges)  AS edges,
               (SELECT COUNT(*) FROM categories)    AS categories
        """
    ).fetchone()
    return dict(row)


def edge_source_counts(conn, city_id):
    rows = conn.execute(
        """
        SELECT e.source, COUNT(*) AS n
        FROM travel_edges e JOIN places p ON p.id = e.from_id
        WHERE p.city_id = ? AND e.scope = 'local'
        GROUP BY e.source
        """,
        (city_id,),
    ).fetchall()
    return {row["source"]: row["n"] for row in rows}


def get_meta(conn):
    try:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    except sqlite3.Error:                               # database built before meta existed
        return {}
