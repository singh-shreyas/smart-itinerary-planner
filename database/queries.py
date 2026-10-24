"""Every SQL query the application runs.

All values are passed as ? parameters (never formatted into the SQL string),
which prevents SQL injection. Functions take an open connection and return
sqlite3.Row objects or plain lists.
"""


def list_cities(conn):
    """Cities with their attraction and start-point counts."""
    return conn.execute(
        """
        SELECT c.*,
               SUM(CASE WHEN p.kind = 'attraction' THEN 1 ELSE 0 END) AS attraction_count,
               SUM(CASE WHEN p.kind = 'start' THEN 1 ELSE 0 END)      AS start_count
        FROM cities c
        LEFT JOIN places p ON p.city_id = c.id
        GROUP BY c.id
        ORDER BY c.name
        """
    ).fetchall()


def get_city(conn, slug):
    return conn.execute("SELECT * FROM cities WHERE slug = ?", (slug,)).fetchone()


def list_categories(conn):
    return conn.execute("SELECT * FROM categories ORDER BY id").fetchall()


def list_attractions(conn, city_id=None):
    """Attractions joined with their place row, city slug and category slugs.

    category_slugs is a comma-separated string (GROUP_CONCAT), split by the caller.
    """
    sql = """
        SELECT p.id, p.slug, p.name, p.lat, p.lng, p.city_id,
               c.slug AS city_slug, c.name AS city_name,
               a.rating, a.popularity, a.visit_minutes, a.fee_inr, a.description,
               a.image_path, a.image_credit, a.image_source_url, a.info_url,
               a.in_team_catalog, a.data_status,
               (SELECT GROUP_CONCAT(cat.slug, ',')
                  FROM attraction_categories ac
                  JOIN categories cat ON cat.id = ac.category_id
                 WHERE ac.place_id = p.id) AS category_slugs
        FROM places p
        JOIN attractions a ON a.place_id = p.id
        JOIN cities c ON c.id = p.city_id
    """
    params = ()
    if city_id is not None:
        sql += " WHERE p.city_id = ?"
        params = (city_id,)
    sql += " ORDER BY c.name, p.id"
    return conn.execute(sql, params).fetchall()


def list_opening_hours(conn, city_id=None):
    sql = """
        SELECT h.place_id, h.weekday, h.open_min, h.close_min, h.last_entry_min
        FROM opening_hours h
        JOIN places p ON p.id = h.place_id
    """
    params = ()
    if city_id is not None:
        sql += " WHERE p.city_id = ?"
        params = (city_id,)
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


def list_edges(conn, city_id):
    return conn.execute(
        """
        SELECT e.from_id, e.to_id, e.minutes, e.km, e.source
        FROM travel_edges e
        JOIN places p ON p.id = e.from_id
        WHERE p.city_id = ?
        ORDER BY e.from_id, e.to_id
        """,
        (city_id,),
    ).fetchall()


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
        WHERE p.city_id = ?
        GROUP BY e.source
        """,
        (city_id,),
    ).fetchall()
    return {row["source"]: row["n"] for row in rows}
