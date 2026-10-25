-- Smart Itinerary Planner: SQLite schema (schema version 3).
--
-- Every node of the travel graph is a row in `places`. Its kind keeps three
-- different ideas apart:
--     attraction  a sightseeing, food or shopping stop   (details in `attractions`)
--     stay        an area to stay in, one per direction  (details in `stay_areas`)
--     transport   a railway station or other interchange -- never offered as a stay
--     access      where the road ends and a trek / ferry begins (e.g. Gaurikund)
-- Times are stored as minutes after midnight (09:30 -> 570) so comparisons
-- are plain integer maths. A weekday with no opening_hours row = closed.
--
-- These tables hold REFERENCE data rebuilt from data/*.csv by
-- database/seed_data.py. Any other table found in an existing database (for
-- example user data added later) is copied across unchanged when the
-- reference data is rebuilt; see database/migrations.py.
--
-- Provenance columns (*_source) record where each value came from:
--   wikipedia / openstreetmap / osm / wikipedia_pageviews  -> an open data source
--   estimate      -> a documented default for that kind of place (data/estimate_defaults.csv)
--   illustrative  -> a plausible value chosen by hand for the four original cities
--   approximate   -> coordinates placed by hand where no source matched

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS meta;
DROP TABLE IF EXISTS access_alternatives;
DROP TABLE IF EXISTS access_segments;
DROP TABLE IF EXISTS stay_areas;
DROP TABLE IF EXISTS travel_edges;
DROP TABLE IF EXISTS opening_hours;
DROP TABLE IF EXISTS attraction_categories;
DROP TABLE IF EXISTS attractions;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS places;
DROP TABLE IF EXISTS cities;

CREATE TABLE meta (                          -- schema_version, dataset_fingerprint, built_at
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE cities (
    id            INTEGER PRIMARY KEY,
    slug          TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    state         TEXT    NOT NULL,
    region        TEXT,
    top_rank      INTEGER,                   -- position in the team's Top-50 list
    center_lat    REAL    NOT NULL CHECK (center_lat BETWEEN -90 AND 90),
    center_lng    REAL    NOT NULL CHECK (center_lng BETWEEN -180 AND 180),
    coord_source  TEXT,
    tagline       TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    hero_image    TEXT,
    hero_credit   TEXT,
    hero_source_url TEXT,
    catalog_id    INTEGER                    -- row in the team's destination catalog
);

CREATE TABLE places (                        -- every node of the travel graph
    id           INTEGER PRIMARY KEY,
    city_id      INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
    slug         TEXT    NOT NULL UNIQUE,    -- unique across ALL cities (multi-city trips mix them)
    name         TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('attraction', 'stay', 'transport', 'access')),
    lat          REAL    NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng          REAL    NOT NULL CHECK (lng BETWEEN -180 AND 180),
    coord_source TEXT,
    note         TEXT,                       -- access points: what the point stands for
    source_url   TEXT
);

CREATE TABLE stay_areas (                    -- one row per place with kind = 'stay'
    place_id       INTEGER PRIMARY KEY REFERENCES places(id) ON DELETE CASCADE,
    direction      TEXT    NOT NULL CHECK (direction IN ('north', 'south', 'east', 'west', 'central')),
    direction_note TEXT,                     -- set when the area is not really in that direction
    osm_place      TEXT,                     -- OpenStreetMap place type (suburb, town, ...)
    hotels_nearby  INTEGER,                  -- OSM places to stay within 1 km when it was chosen
    distance_km    REAL,                     -- straight line from the city centre
    bearing        REAL                      -- degrees from north, seen from the city centre
);

CREATE TABLE categories (
    id      INTEGER PRIMARY KEY,
    slug    TEXT NOT NULL UNIQUE,
    name    TEXT NOT NULL,
    icon    TEXT NOT NULL,                   -- Bootstrap Icons class name
    grp     TEXT NOT NULL,                   -- heading the interest is listed under
    parent  TEXT,                            -- e.g. street-food -> food (a match on the child also counts for the parent)
    kind    TEXT NOT NULL CHECK (kind IN ('sight', 'food', 'shopping'))
);

CREATE TABLE attractions (                   -- one row per place with kind = 'attraction'
    place_id          INTEGER PRIMARY KEY REFERENCES places(id) ON DELETE CASCADE,
    rating            REAL    CHECK (rating IS NULL OR rating BETWEEN 0 AND 5),   -- NULL = no rating data
    rating_source     TEXT    NOT NULL,
    popularity        REAL    NOT NULL CHECK (popularity BETWEEN 0 AND 1),
    popularity_source TEXT    NOT NULL,
    pageviews_12m     INTEGER,                                                     -- raw Wikipedia views, when used
    visit_minutes     INTEGER NOT NULL CHECK (visit_minutes BETWEEN 15 AND 480),
    duration_source   TEXT    NOT NULL,
    fee_inr           INTEGER NOT NULL DEFAULT 0 CHECK (fee_inr >= 0),
    fee_source        TEXT    NOT NULL,
    hours_source      TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    description_source TEXT,
    image_path        TEXT,
    image_credit      TEXT,
    image_source_url  TEXT,
    info_url          TEXT,
    wikidata          TEXT,
    place_type        TEXT,                  -- kind of place (temple, fort, market, ...) used for defaults
    cuisine           TEXT,                  -- food places only: venue styles separated by ';'
    vegetarian        TEXT    NOT NULL DEFAULT 'unknown' CHECK (vegetarian IN ('yes', 'unknown')),
    in_team_catalog   INTEGER NOT NULL CHECK (in_team_catalog IN (0, 1)),
    data_status       TEXT    NOT NULL CHECK (data_status IN ('verified', 'estimate', 'illustrative')),
    -- How you get there. 'road' = a road reaches it (OSRM); anything else is
    -- described by access_segments (the default route) and access_alternatives.
    access_type       TEXT    NOT NULL DEFAULT 'road'
                      CHECK (access_type IN ('road', 'road_walk', 'trek', 'ferry', 'boat', 'ropeway',
                                             'helicopter', 'public_transport_walk', 'restricted', 'unknown')),
    road_access       TEXT    NOT NULL DEFAULT 'yes' CHECK (road_access IN ('yes', 'no', 'unknown')),
    access_point_id   INTEGER REFERENCES places(id),   -- where the road ends (NULL = unknown or not needed)
    access_modes      TEXT,                  -- e.g. 'trek' or 'ferry;walk'
    access_timing     TEXT    NOT NULL DEFAULT 'road_data'
                      CHECK (access_timing IN ('road_data', 'sourced', 'estimated', 'unknown')),
    last_mile_m       INTEGER,               -- road_walk: straight-line metres from the nearest road
    access_note       TEXT,
    access_source_url TEXT
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
    source   TEXT    NOT NULL CHECK (source IN ('osrm', 'manual', 'haversine_estimate', 'access')),
    scope    TEXT    NOT NULL DEFAULT 'local' CHECK (scope IN ('local', 'intercity', 'access')),
    PRIMARY KEY (from_id, to_id),
    CHECK (from_id <> to_id)
);

-- The parts of a non-road link (source = 'access'), in order. A link from
-- Gateway of India to Elephanta Caves is: 1 ferry 60 min, 2 walk 15 min.
-- Its travel_edges row holds the totals, so Dijkstra sees one edge.
CREATE TABLE access_segments (
    from_id      INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    to_id        INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL CHECK (seq >= 1),
    mode         TEXT    NOT NULL CHECK (mode IN ('walk', 'trek', 'ferry', 'boat', 'ropeway')),
    minutes      INTEGER NOT NULL CHECK (minutes > 0),
    km           REAL    NOT NULL CHECK (km > 0),
    depart_open  INTEGER,                    -- this part can only start inside [open, close]
    depart_close INTEGER,                    --   (e.g. first and last ferry); NULL = no limit known
    basis        TEXT    NOT NULL CHECK (basis IN ('source', 'estimate')),
    note         TEXT    NOT NULL,
    source_url   TEXT,
    PRIMARY KEY (from_id, to_id, seq)
);

-- Other ways in (helicopter, ropeway, battery car, ...). Shown to the traveller,
-- never used in a plan: their schedules and availability are not verified.
CREATE TABLE access_alternatives (
    id           INTEGER PRIMARY KEY,
    place_id     INTEGER NOT NULL REFERENCES attractions(place_id) ON DELETE CASCADE,
    label        TEXT    NOT NULL,
    modes        TEXT    NOT NULL,
    starts_from  TEXT,
    minutes      INTEGER,                    -- as stated by the source, if it states one
    status       TEXT    NOT NULL CHECK (status IN ('operating_unverified', 'planned')),
    note         TEXT    NOT NULL,
    source_url   TEXT
);

CREATE INDEX idx_places_city ON places(city_id);
CREATE INDEX idx_hours_place ON opening_hours(place_id, weekday);
CREATE INDEX idx_edges_from ON travel_edges(from_id);
