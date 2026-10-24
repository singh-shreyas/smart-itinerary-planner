# Smart Itinerary Planner and Travel Optimization System

Plan realistic, day-by-day sightseeing itineraries for Indian cities, and compare the algorithms behind them.
Pick a city, dates, daily hours, an optional budget, interests and pace. The planner chooses the most valuable
attractions for each day, orders them to cut travel, respects every opening hour and the budget, and explains every
attraction it leaves out.

ADA (Analysis and Design of Algorithms) project, B.Tech CSE (Section B), Faculty of Technology, University of Delhi.
Team: **Shreyas Singh** and **Priyanshi Gupta**.

Stack (as in our synopsis): **Python · Flask · SQLite · HTML/CSS/JavaScript · Bootstrap 5 · Jinja2**, with
**NetworkX used only to cross-check** our Dijkstra. Maps use **Leaflet + OpenStreetMap** (free, no API key).

---

## Quick start (macOS)

You need Python 3.10 or newer (`python3 --version`). Tested with Python 3.11.

```bash
cd "ADA PROJECT FINAL"                 # the project folder
python3 -m venv .venv                  # create a private Python environment (once)
source .venv/bin/activate              # use it in this terminal; the prompt shows (.venv)
pip install -r requirements.txt        # Flask, NetworkX, pytest
python app.py                          # start the app
```

Open **http://127.0.0.1:5001** in your browser. Stop the server with `Ctrl+C`.

* On first start the SQLite database (`instance/itinerary.db`) is **built automatically** from the CSV files in `data/`.
* Port **5001** is used because macOS AirPlay Receiver often occupies port 5000.
* Equivalent Flask command: `flask --app app run --debug --port 5001`.
* Everything except map tiles works offline: Bootstrap, Leaflet, Chart.js, icons and fonts are stored in `static/vendor/` and `static/fonts/`.

### Rebuild the database

```bash
python -m database.seed_data           # validates data/*.csv and rebuilds instance/itinerary.db
flask --app app init-db                # same, through the Flask CLI
python -m database.seed_data --strict  # also refuses rows marked "illustrative" (for when data is verified)
```

The seed script refuses to build the database if a row is invalid (closing before opening, a visit that never fits its
hours, an edge between two cities, coordinates far from the city, unknown categories, ...), and lists every problem.

### Run the tests

```bash
python -m pytest            # all tests (about 10 seconds)
python -m pytest -v         # one line per test
python -m pytest -k dijkstra
```

Latest run: **116 passed**. The tests cover:

| File | What it checks |
|---|---|
| `tests/test_dijkstra.py` | hand-worked shortest paths, unreachable nodes, directed edges, negative weights rejected, **equality with NetworkX** on 60 random graphs and on every real city |
| `tests/test_selection.py` | the **greedy trap** (Greedy 90 vs DP 120), **DP = brute force** on 200 random instances, DP ≥ Greedy on 300 instances, limits respected, zero budget, merge sort, score formula |
| `tests/test_routing.py` | Nearest Neighbour, **2-opt never worse than NN**, 2-opt untangles a crossing, 2-opt with a feasibility rule, **Held–Karp = brute force** over all permutations, feasible insertion |
| `tests/test_activity_selection.py` | the textbook 11-activity example, closed weekdays, split opening hours, last entry, ride back by day end, no overlapping visits |
| `tests/test_database.py` | schema constraints and foreign keys, seeding counts, invalid CSV rows refused, unreachable places reported, real data fully connected |
| `tests/test_itinerary.py` | multi-day plans with no repeats, budgets (₹0, small, none), unreachable places, evening-only stops, empty days with reasons, determinism, **120 random real-data trips that must pass the validator** |
| `tests/test_routes.py` | every page renders, invalid input → HTTP 400 with a field message (never 500), unknown pages → 404, JSON API |
| `tests/test_validator.py` | the independent validator catches tampered plans (outside hours, duplicates, wrong travel, overrun, budget) |

Tests use a temporary database built from `tests/fixtures/tiny_city/` (a hand-made city whose answers can be worked out
on paper) and from `data/`; they never touch `instance/itinerary.db`.

### Run the benchmarks

```bash
python scripts/benchmark.py            # about 3 minutes; writes results/benchmarks.json and .csv
python scripts/benchmark.py --quick    # fewer seeds
```

Seeded synthetic instances (`random.Random(seed)`) measure how runtime grows with input size, and a sweep of 2,520
real-data trips counts how often DP or Greedy produces the better final itinerary. Quality numbers are identical on
every run; timings vary with the machine and its load. The comparison page charts this file, and nothing on that page
is typed in by hand.

---

## What the app does (pages)

| Page | URL | What you can do |
|---|---|---|
| Home | `/` | Hero, quick plan form, destinations, how it works, the algorithms |
| Cities | `/cities` | The four modelled cities + the searchable 200-destination team catalog |
| Attractions | `/attractions?city=delhi` | Search, category and "open on" filters, sorting, details dialog with weekly hours |
| Trip planner | `/plan` | City, start point, dates, daily hours, budget (± local transport), interests, pace, strategy, exclusions |
| Itinerary | `/itinerary?...` | Day tabs, timeline with arrive/start/end/leave, travel legs (with Dijkstra "via" places), fees, daily time and budget breakdown, Leaflet map, DP / Greedy / Max-visits switch, "not included" reasons |
| Compare | `/compare?...` | The same trip through every algorithm: whole itineraries, knapsack selection, routing vs the exact optimum, Dijkstra vs NetworkX, scaling charts |
| About | `/about` | Problem, pipeline, algorithms with complexities, architecture, data sources, limitations, photo credits |

Plans are a pure function of the URL (GET requests, deterministic), so any itinerary link can be refreshed or shared.

JSON API: `/api/health`, `/api/cities`, `/api/cities/<slug>/attractions`, `/api/itinerary?...`, `/api/compare?...`.

```bash
curl "http://127.0.0.1:5001/api/itinerary?city=delhi&days=2&start_date=2026-11-02&budget=600&transport=on"
```

Trip parameters: `city`, `start_date` (YYYY-MM-DD), `days` (1–5), `day_start`/`day_end` (HH:MM, at least 2 h apart),
`budget` (₹, empty = no limit), `transport=on` (count local transport in the budget), `interests` (repeatable),
`pace` (relaxed/balanced/packed), `start` (start point or attraction slug), `strategy` (dp/greedy/max_visits),
`exclude` (comma-separated slugs). Missing optional values get sensible defaults.

---

## The algorithms

All implemented by us in plain Python, one per file in `algorithms/`, with no Flask or SQLite imports, so each one can be
tested on plain lists and dicts. No optimisation library is used. NetworkX appears only in `services/crosscheck.py`.

| Algorithm | File | Role in the system | Time | Space |
|---|---|---|---|---|
| Graph (adjacency list) | `algorithms/graph.py` | City road network: each place links to its 5 nearest places | O(V + E) | O(V + E) |
| Dijkstra (binary heap) | `algorithms/dijkstra.py` | Shortest travel time between every pair of places (chains local links) | O((V+E) log V) per source; O(V(V+E) log V) all pairs | O(V²) table |
| Merge sort + priority queues | `algorithms/sorting.py`, `heapq` | Ordering by score / closing time; heap inside Dijkstra; weakest-stop removal in repair | O(n log n); O(log n) per heap op | O(n) |
| Greedy selection | `algorithms/greedy.py` | Strategy / baseline: best value per unit of time (and money) first | O(n log n) | O(n) |
| Dynamic programming (0/1 knapsack, 2-D) | `algorithms/dynamic_programming.py` | Default strategy: best-value set within the day's minutes **and** budget | O(n·T·M) (pseudo-polynomial) | O(n·T·M) |
| Nearest Neighbour | `algorithms/nearest_neighbor.py` | First route: always go to the closest unvisited stop | O(k²) | O(k) |
| 2-opt local search | `algorithms/two_opt.py` | Improve a route by reversing segments; optional feasibility check | O(k³) per pass | O(k) |
| Activity selection | `algorithms/activity_selection.py` | Earliest-closing-time-first ordering; "max visits" baseline; textbook version tested | O(n log n) | O(n) |
| Feasible insertion | `algorithms/insertion.py` | Window-first route: insert stops (in closing-time order) where every opening window still holds | O(k³) | O(k) |
| Held–Karp (bitmask DP) | `algorithms/held_karp.py` | Comparison only: the exact shortest tour, to measure NN and 2-opt gaps | O(2ᵏ·k²) | O(2ᵏ·k) |

V = places, E = road links, n = candidate attractions, k = stops in a day, T and M = time and money units in the DP table.

### How they work together (the pipeline)

`services/itinerary_generator.py`:

1. **Once per city (cached):** load places, hours and road links from SQLite → adjacency list → Dijkstra from every place
   → travel-time table (∞ when there is no path). Edge minutes are OSRM free-flow times × the traffic factor, rounded up.
2. **Once per trip:** score each attraction: `score = round(100 × (0.5·rating/5 + 0.3·popularity + 0.2·interest_match))`.
3. **For each day, in date order:**
   1. **Filter:** keep attractions not yet planned, not excluded, open on that weekday, reachable both ways,
      affordable on their own, and able to fit in the day on their own. Each rejection is recorded with its reason.
   2. **Select:** 0/1 knapsack with DP (default) or Greedy. Each stop's time weight is
      `visit + pace buffer + its cheapest trip out`, a **lower bound** on real travel, because every route leaves each stop once.
      So no set that truly fits is thrown away. The money weight is the entry fee (+ a transport lower bound if transport counts).
      Weights are rounded **up** to 10-minute / money units and capacities **down**, so whatever the DP accepts really fits.
      Greedy and DP receive the identical integer instance.
   3. **Route, two branches:** *travel-first* = Nearest Neighbour → 2-opt; *window-first* = closing-time order
      (the activity-selection rule) with feasible insertion → 2-opt that only accepts feasible moves. Keep the feasible branch with less travel.
   4. **Check:** `services/scheduler.py` simulates the day minute by minute (arrive = leave + travel; start inside an opening
      window and before last entry; end = start + visit; leave = end + buffer; back at the start by day end).
   5. **Repair:** if no branch works (or the day is over budget), the weakest selected stop (lowest score per minute, or per
      rupee, from a min-heap) leaves today's pool and **the selector runs again**. The pool shrinks every round, so the loop always ends.
4. **Validate:** `services/validator.py` re-checks every constraint from the raw data, independently of the planner. Tests require zero violations.

**What is (and is not) optimal.** The full problem, the multi-day *Orienteering Problem with Time Windows*, is NP-hard, so
select-then-route is a decomposition heuristic. DP is optimal for each day's rounded knapsack model; 2-opt reaches a local
optimum; Held–Karp is exact for travel only (it ignores opening hours). No itinerary is claimed to be globally optimal.

---

## Architecture and project structure

```
browser ──► Flask routes ──► services ──► algorithms (pure functions)
                              │
                              └──► database (all SQL in database/queries.py)
```

```
ADA PROJECT FINAL/
├── app.py                      # create_app(): config, database, blueprints, error pages; `python app.py`
├── config.py                   # every tunable number: weights, pace buffers, DP units, traffic factor, ...
├── requirements.txt  pytest.ini  .gitignore  README.md
├── algorithms/                 # our ADA implementations (no Flask / SQLite)
│   ├── graph.py  dijkstra.py  sorting.py  scoring.py  knapsack_types.py
│   ├── greedy.py  dynamic_programming.py
│   ├── nearest_neighbor.py  two_opt.py  activity_selection.py  insertion.py  held_karp.py  tour.py
├── services/                   # business logic between routes and algorithms
│   ├── models.py               # dataclasses: Attraction, Window, TripRequest, Visit, Leg, DayPlan, Itinerary
│   ├── trip_request.py         # server-side validation of every trip parameter
│   ├── city_data.py            # load a city, build the graph, run Dijkstra (cached per city)
│   ├── scheduler.py            # minute-by-minute day simulation
│   ├── itinerary_generator.py  # the planning pipeline
│   ├── validator.py            # independent constraint checker
│   ├── comparison.py           # runs all strategies on identical input; crosscheck.py (NetworkX); timing.py
│   └── timeutil.py  algorithm_info.py
├── database/
│   ├── schema.sql              # cities, places, attractions, categories, opening_hours, travel_edges (+ CHECKs, FKs)
│   ├── db.py                   # one connection per request, foreign keys ON, init-db command
│   ├── queries.py              # every SQL query, ? parameters only
│   └── seed_data.py            # CSV → SQLite with validation (python -m database.seed_data)
├── routes/
│   ├── main_routes.py          # /, /cities, /attractions, /about
│   ├── itinerary_routes.py     # /plan, /itinerary, /compare
│   ├── api_routes.py           # /api/...
│   └── helpers.py
├── templates/                  # Jinja2: base.html, _macros.html, index, cities, attractions, planner, itinerary, compare, about, error
├── static/
│   ├── css/style.css           # the design system (Bootstrap themed through CSS variables)
│   ├── js/                     # site.js, attractions.js, planner.js, itinerary.js (Leaflet), compare.js (Chart.js)
│   ├── images/                 # city banners, attraction photos (Wikimedia Commons), placeholder
│   ├── fonts/                  # Fraunces + Inter (SIL OFL)
│   └── vendor/                 # Bootstrap 5.3.3, Bootstrap Icons 1.11.3, Leaflet 1.9.4, Chart.js 4.4.4
├── data/                       # the source of truth (CSV)
│   ├── cities.csv  start_points.csv  attractions.csv  opening_hours.csv  categories.csv
│   ├── travel_times.csv        # 482 directed road links (OSRM)
│   ├── image_credits.csv       # author + licence of every photo
│   └── catalog/destinations.csv  # the team's 200-destination catalog (names only)
├── scripts/                    # one-off data scripts, never run by the web app
│   ├── build_travel_times.py   # OSRM road times → data/travel_times.csv (or --offline estimates)
│   ├── fetch_wikimedia.py      # free-licensed photos + coordinate cross-check
│   ├── import_catalog.py       # team spreadsheet (.xlsx) → data/catalog/destinations.csv
│   └── benchmark.py            # → results/benchmarks.json
├── results/                    # saved benchmark outputs (charted on /compare)
├── tests/                      # pytest suite + tests/fixtures/tiny_city
└── instance/                   # generated SQLite database (git-ignored)
```

---

## Data: sources, assumptions and limitations

| Data | Source | Status |
|---|---|---|
| City and attraction names | Our team catalog `India_200_Tourist_Destinations_Attractions.xlsx` (200 destinations, 1,053 attraction names). Delhi, Agra, Jaipur and Varanasi were modelled in full: their catalog attractions plus well-known additions to fill multi-day trips (`in_team_catalog` column) | Names from the catalog |
| Coordinates | 45 from Wikipedia article coordinates, 9 from OpenStreetMap Nominatim, 6 approximate (`coord_source` column) | Cross-checked |
| Road links (482) | Each place to its 5 nearest places; driving time and distance from the public **OSRM** server on **OpenStreetMap** roads, fetched once offline | Real road network, free-flow (no traffic) |
| Traffic | One assumed multiplier, `TRAFFIC_FACTOR = 1.5` in `config.py` | **Assumption**, not calibrated |
| Opening hours, entry fees (Indian adult), ratings, popularity, visit durations | Plausible values chosen for this project | **Illustrative**: not verified, labelled in the UI |
| Local transport cost | ₹12/km (`TRANSPORT_COST_PER_KM`) | **Illustrative** |
| Photos | Wikimedia Commons, free licences only; author and licence in `data/image_credits.csv` and on the About page | Credited; 5 attractions use a placeholder |

**Limitations**

* The full problem is NP-hard; select-then-route can miss a better combination.
* Days are planned in date order, so the plan is myopic across days.
* Composing local links can make a long trip slightly slower than the true direct road time.
* One mode of transport; free-flow road times × one traffic factor; no live traffic.
* Fixed visit durations; no queues, security checks, lunch break or ticket booking.
* Activity selection's optimality proof does not transfer to flexible windows with travel; here it is a heuristic.
* Map lines are straight segments in visit order, not road geometry (the map says so).
* Hours, fees, ratings and durations are illustrative until verified (`python -m database.seed_data --strict` refuses them).

### Adding a city (no algorithm changes)

1. Add rows to `data/cities.csv`, `data/start_points.csv`, `data/attractions.csv` and `data/opening_hours.csv`
   (days like `Daily`, `Tue-Sun`, `Sat-Thu`; two rows on one day = split hours; no row = closed).
2. `python scripts/build_travel_times.py` (road links from OSRM; `--offline` for straight-line estimates).
3. Optional: `python scripts/fetch_wikimedia.py --coords --images` for coordinates check and photos.
4. `python -m database.seed_data`, then `python -m pytest`.

---

## Viva notes

* **Why Dijkstra if we have coordinates?** We store only local road links; Dijkstra composes them into shortest travel
  times between every pair. Coordinates give straight lines, not roads. (The compare page shows a 5-link composed path.)
* **Why not Floyd–Warshall?** O(V³). Dijkstra from every node is O(V(V+E) log V), cheaper on a sparse graph.
* **Negative weights?** Not possible: travel minutes are positive; `build_graph` and the schema reject them.
* **Why is the DP pseudo-polynomial?** Its cost depends on the numeric capacities T and M, not only on n.
* **Where is travel time in the knapsack?** Each stop's weight includes its cheapest trip out, a lower bound; the scheduler checks the real timeline.
* **Show Greedy failing.** 300 min; X = 180 min, score 90; Y = Z = 150 min, score 60. Greedy 90, DP 120 (compare page, run live).
* **Is DP's itinerary always better?** No. On the identical knapsack DP ≥ Greedy is guaranteed; on whole itineraries
  (after routing, repair and multi-day effects) our 2,520-trip sweep found DP ahead in 989, Greedy in 361 and ties in 1,170.
* **Is 2-opt optimal?** No, it is a local optimum; Held–Karp gives the exact tour for ≤ 10 stops so we can report the gap.
* **Why recompute the whole route cost in 2-opt?** Travel times are directed; reversing a segment reverses its inner legs.
* **How do you know Dijkstra is correct?** Unit tests plus 0 mismatches against NetworkX on every pair, in every city and on random graphs.
* **What if no plan is possible?** We return the days that work, mark the rest empty with a specific reason, and offer one-click fixes. We never invent stops.

---

## Credits

Map tiles © OpenStreetMap contributors · Routing data © OpenStreetMap contributors (ODbL), computed with OSRM ·
Photos: Wikimedia Commons contributors (see `data/image_credits.csv`) · Fonts: Fraunces and Inter (SIL OFL) ·
Bootstrap, Bootstrap Icons, Leaflet and Chart.js (MIT / BSD licences).
