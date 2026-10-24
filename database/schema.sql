-- Smart Itinerary Planner: SQLite schema.
--
-- Every node of the travel graph (attraction or start point) is a row in
-- `places`; attraction-only fields live in the 1:1 `attractions` table.
-- Times are stored as minutes after midnight (09:30 -> 570) so comparisons
-- are plain integer maths. A weekday with no opening_hours row = closed.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS travel_edges;
DROP TABLE IF EXISTS opening_hours;
DROP TABLE IF EXISTS attraction_categories;
DROP TABLE IF EXISTS attractions;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS places;
DROP TABLE IF EXISTS cities;

CREATE TABLE cities (
    id            INTEGER PRIMARY KEY,
    slug          TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    state         TEXT    NOT NULL,
    center_lat    REAL    NOT NULL CHECK (center_lat BETWEEN -90 AND 90),
    center_lng    REAL    NOT NULL CHECK (center_lng BETWEEN -180 AND 180),
    tagline       TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    hero_image    TEXT,
    hero_credit   TEXT,
    hero_source_url TEXT,
    catalog_id    INTEGER                    -- row in the team's destination catalog
);

CREATE TABLE places (                        -- every node of the travel graph
    id       INTEGER PRIMARY KEY,
    city_id  INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
    slug     TEXT    NOT NULL,
    name     TEXT    NOT NULL,
    kind     TEXT    NOT NULL CHECK (kind IN ('attraction', 'start')),
    lat      REAL    NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng      REAL    NOT NULL CHECK (lng BETWEEN -180 AND 180),
    UNIQUE (city_id, slug)
);

CREATE TABLE categories (
    id    INTEGER PRIMARY KEY,
    slug  TEXT NOT NULL UNIQUE,
    name  TEXT NOT NULL,
    icon  TEXT NOT NULL                      -- Bootstrap Icons class name
);

CREATE TABLE attractions (                   -- one row per place with kind = 'attraction'
    place_id         INTEGER PRIMARY KEY REFERENCES places(id) ON DELETE CASCADE,
    rating           REAL    NOT NULL CHECK (rating BETWEEN 0 AND 5),
    popularity       REAL    NOT NULL CHECK (popularity BETWEEN 0 AND 1),
    visit_minutes    INTEGER NOT NULL CHECK (visit_minutes BETWEEN 15 AND 480),
    fee_inr          INTEGER NOT NULL DEFAULT 0 CHECK (fee_inr >= 0),
    description      TEXT    NOT NULL,
    image_path       TEXT,
    image_credit     TEXT,
    image_source_url TEXT,
    info_url         TEXT,
    in_team_catalog  INTEGER NOT NULL CHECK (in_team_catalog IN (0, 1)),
    data_status      TEXT    NOT NULL CHECK (data_status IN ('verified', 'estimate', 'illustrative'))
);

CREATE TABLE attraction_categories (
    place_id     INTEGER NOT NULL REFERENCES attractions(place_id) ON DELETE CASCADE,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    PRIMARY KEY (place_id, category_id)
);

CREATE TABLE opening_hours (                 -- no row for a weekday = closed that day
    id              INTEGER PRIMARY KEY,
    place_id        INTEGER NOT NULL REFERENCES attractions(place_id) ON DELETE CASCADE,
    weekday         INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),   -- 0 = Monday
    open_min        INTEGER NOT NULL CHECK (open_min BETWEEN 0 AND 1439),
    close_min       INTEGER NOT NULL CHECK (close_min BETWEEN 1 AND 1440),
    last_entry_min  INTEGER,                                            -- NULL = no separate last entry
    CHECK (open_min < close_min),
    CHECK (last_entry_min IS NULL OR (last_entry_min BETWEEN open_min AND close_min))
);

CREATE TABLE travel_edges (                  -- directed: A->B and B->A are separate rows
    from_id  INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    to_id    INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    minutes  REAL    NOT NULL CHECK (minutes > 0),   -- free-flow minutes (traffic factor applied in code)
    km       REAL    NOT NULL CHECK (km > 0),
    source   TEXT    NOT NULL CHECK (source IN ('osrm', 'manual', 'haversine_estimate')),
    PRIMARY KEY (from_id, to_id),
    CHECK (from_id <> to_id)
);

CREATE INDEX idx_places_city ON places(city_id);
CREATE INDEX idx_hours_place ON opening_hours(place_id, weekday);
CREATE INDEX idx_edges_from ON travel_edges(from_id);
