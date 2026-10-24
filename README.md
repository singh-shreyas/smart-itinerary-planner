# Smart Itinerary Planner and Travel Optimization System

Plan realistic, day-by-day sightseeing itineraries for **50 Indian destinations** — on their own or combined with nearby
cities — and compare the algorithms behind them. Pick a base city (plus nearby cities if you like), dates, daily hours,
an optional budget, interests, meals and pace. The planner chooses the most valuable places for each day, schedules lunch
and dinner, orders the stops to cut travel, respects every opening hour and the budget, explains every place it leaves
out and every hour it leaves unused, and gives each plan a reproducibility fingerprint.

ADA (Analysis and Design of Algorithms) project, B.Tech CSE (Section B), Faculty of Technology, University of Delhi.
Team: **Shreyas Singh** and **Priyanshi Gupta**.

Stack (as in our synopsis): **Python · Flask · SQLite · HTML/CSS/JavaScript · Bootstrap 5 · Jinja2**, with
**NetworkX used only to cross-check** our Dijkstra. Maps use **Leaflet + OpenStreetMap** (free, no API key). No paid API is used.

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

* On start the SQLite database (`instance/itinerary.db`) is **built automatically** from the CSV files in `data/` — and
  **rebuilt safely** whenever the data or the schema changed (see *Safe database updates* below).
* Port **5001** is used because macOS AirPlay Receiver often occupies port 5000.
* Equivalent Flask command: `flask --app app run --debug --port 5001`.
* Everything except map tiles works offline: Bootstrap, Leaflet, Chart.js, icons and fonts are in `static/vendor/` and `static/fonts/`.

### Safe database updates

```bash
python -m database.seed_data --check   # schema version, data fingerprint, "up to date" or why a rebuild is needed
python -m database.seed_data           # validate data/*.csv and rebuild instance/itinerary.db
flask --app app init-db                # same, through the Flask CLI
python -m database.seed_data --strict  # also refuse rows marked "illustrative" and any warning
```

The database has a `meta` table with the **schema version** and a **SHA-256 fingerprint of the CSV files** it was built
from. A rebuild (automatic on start-up, or by hand) never loses data:

1. every CSV is validated first — a bad row stops the build and the old database is left untouched;
2. the new database is written to a temporary file;
3. every table that is *not* reference data (for example saved trips or settings added later) is copied across with its rows;
4. the old file is copied to `instance/backups/` (newest 5 kept);
5. the new file is swapped in atomically.

### Run the tests

```bash
python -m pytest            # all tests
python -m pytest -v         # one line per test
python -m pytest -k meals
```

Latest run: **223 passed** (about 8 seconds). Tests use temporary databases built from `tests/fixtures/tiny_city/` (four hand-made
cities whose answers can be worked out on paper) and from `data/`; they never touch `instance/itinerary.db`.

| File | What it checks |
|---|---|
| `test_dijkstra.py` | hand-worked shortest paths, unreachable nodes, directed edges, the 10-minute planning table, **equality with NetworkX** |
| `test_selection.py` | the greedy trap, **DP = brute force** on 200 instances, DP ≥ Greedy, limits, merge sort, score formula |
| `test_strategies.py` | value-vs-count and greedy-trap instances where the three strategies differ, a case where they coincide, **Max visits = brute-force count** on 150 instances, each selector best at its own objective on identical instances, scorecard normalisation, **infeasible plans never recommended**, honest ties |
| `test_routing.py` | Nearest Neighbour, 2-opt never worse than NN, Held–Karp = brute force, feasible insertion |
| `test_activity_selection.py` | textbook activity selection, closed weekdays, split hours, last entry, ride back by day end |
| `test_meals.py` | when a meal is needed, lunch inside its window, meal at a nearby listed food place (as its own travel leg), generic break when suggestions are off, meals near the base after returning, a long visit never swallows lunch, meal time reserved in the knapsack, the validator catches broken meals |
| `test_time_window.py` | a longer day gives more stops, a later end changes nothing when everything is closed (and the unused time is explained), stops never decrease as the day grows (12:00–23:00, all strategies), no special case for 23:00, the time breakdown adds up exactly |
| `test_multicity.py` | distances and nearby lists, **pairwise 100 km rule**, invalid groups refused, combined pool with intercity legs, **missing road link → labelled estimate (never zero)**, day grouping, Agra + Mathura + Vrindavan on real data |
| `test_categories.py` | category hierarchy, neutral prior for unrated places, interests change the score, food/shopping opt-in, "only matching interests", limited-data notes, shopping time and spend, vegetarian filter |
| `test_rounding.py` | the round-up rule, display format, every leg a multiple of 10 that agrees with the clock times, clock times not rounded |
| `test_determinism.py` | same trip twice → identical plan (all strategies, multi-city, meals), **same plan under three different `PYTHONHASHSEED`s**, tie-breaking by id, input order irrelevant, fingerprints separate data changes |
| `test_database.py`, `test_migrations.py` | schema constraints, invalid rows refused, unique slugs across cities, every value has a source, Top-50 list = database, **upgrade from an old database keeps user tables and makes a backup**, up-to-date database untouched, failed rebuild leaves the old file intact, backup rotation |
| `test_itinerary.py`, `test_validator.py`, `test_routes.py` | multi-day plans, budgets, unreachable places, random real-data trips that must pass the validator; the validator catches tampered plans; every page renders (incl. multi-city), bad input → HTTP 400 with a message, JSON API |

### Run the benchmarks

```bash
python scripts/benchmark.py            # about 30 seconds; writes results/benchmarks.json and .csv
python scripts/benchmark.py --quick    # fewer seeds
```

Seeded synthetic instances (`random.Random(seed)`) measure how runtime grows with input size; a sweep of 648 real-data
trips (the 12 highest-ranked plannable cities × 3 start days × 1–3 days × 2 budgets × 3 interest settings, with lunch)
counts how often each strategy ends up ahead. Latest run: DP's itinerary scored higher than Greedy's in 126 trips, Greedy's
in 3, equal in 519; Max visits never planned more stops than DP and planned fewer in 6 (selection-level guarantees do not
survive routing, meals and repair). The comparison page charts this file; nothing on it is typed in by hand.

---

## What the app does (pages)

| Page | URL | What you can do |
|---|---|---|
| Home | `/` | Hero with quick plan, featured destinations, destinations by region, how it works, the algorithms |
| Destinations | `/cities` | All 50 cities with search, region and data-level filters; nearby cities to combine; sights not plannable by road and why; the 200-destination catalog |
| Attractions | `/attractions?city=delhi` | Destination picker, search, interest / "open on" filters, sorting; details dialog with weekly hours and the **source of every value** |
| Trip planner | `/plan` | Base city, nearby cities (pairwise 100 km rule), start point, dates, daily hours, budget (± transport), 26 interests (prefer / only), lunch and dinner windows and lengths, meal-venue style, vegetarian only, shopping time and spend, pace, strategy, exclusions |
| Itinerary | `/itinerary?...` | Day tabs; timeline with travel legs (local / intercity / estimated), visits and **meal breaks**; time breakdown (sightseeing, local and intercity travel, meals, waiting, buffer, unused) and **why the day ends early**; costs; Leaflet map; strategy switch; reasons for every place left out; reproducibility fingerprints |
| Compare | `/compare?...` | Recommendation (or an honest tie), scorecard with raw values and subscores, time-use and value charts, trade-offs, each strategy's objective with live demos, the three selectors on identical knapsacks, routing vs the exact optimum, Dijkstra vs NetworkX, scaling charts |
| About | `/about` | Problem, pipeline, algorithms, strategies, meals, food and shopping, multi-city rule, scoring, reproducibility, architecture, data sources with counts, default values, limitations, credits |

Plans are a pure function of the URL (GET requests, deterministic), so any itinerary link can be refreshed or shared.

JSON API: `/api/health`, `/api/cities`, `/api/cities/<slug>/attractions`, `/api/itinerary?...`, `/api/compare?...`.

```bash
curl "http://127.0.0.1:5001/api/itinerary?city=agra&also=mathura,vrindavan&days=3&start_date=2026-11-02"
```

Trip parameters: `city` (base city), `also` (nearby cities, comma-separated), `start_date` (YYYY-MM-DD), `days` (1–5),
`day_start`/`day_end` (HH:MM, at least 2 h apart), `budget` (₹, empty = no limit), `transport=on`, `interests`
(repeatable), `interest_mode` (prefer/only), `lunch`/`dinner` (on/off) with `lunch_from`, `lunch_to`, `lunch_min` (and the
same for dinner), `venues` (on/off), `venue_style` (street-food, cafe-bakery, casual, fine-dining, local-specialty),
`veg=on`, `shop_min`, `shop_spend`, `pace` (relaxed/balanced/packed), `start`, `strategy` (dp/greedy/max_visits),
`exclude`. Missing optional values get sensible defaults (lunch and dinner on).

---

## The algorithms

All implemented by us in plain Python, one per file in `algorithms/`, with no Flask or SQLite imports. No optimisation
library is used. NetworkX appears only in `services/crosscheck.py`.

| Algorithm | File | Role in the system | Time | Space |
|---|---|---|---|---|
| Graph (adjacency list) | `graph.py` | Road network of a city or city group: each place links to its 5 nearest places, plus intercity links | O(V + E) | O(V + E) |
| Dijkstra (binary heap) | `dijkstra.py` | Shortest travel time between every pair of places | O((V+E) log V) per source | O(V²) table |
| Merge sort + priority queues | `sorting.py`, `heapq` | Ordering by score / closing time; heap inside Dijkstra; weakest-stop removal in repair | O(n log n) | O(n) |
| Greedy selection | `greedy.py` | Strategy: best value per unit of time (and money) first | O(n log n) | O(n) |
| Dynamic programming (0/1 knapsack, 2-D) | `dynamic_programming.py` | Default strategy: **maximum total value** within the day's minutes and budget | O(n·T·M) | O(n·T·M) |
| Max visits (DP on the count) | `max_visits.py` | Strategy: **maximum number of places**, ties by value — the same DP with values `B + score` | O(n·T·M) | O(n·T·M) |
| Nearest Neighbour | `nearest_neighbor.py` | First route: always go to the closest unvisited stop | O(k²) | O(k) |
| 2-opt local search | `two_opt.py` | Improve a route by reversing segments; optional feasibility check | O(k³) per pass | O(k) |
| Activity selection | `activity_selection.py` | Earliest-closing-time-first order for the window-first route; textbook version tested | O(n log n) | O(n) |
| Cheapest feasible insertion | `insertion.py` | Window-first route, and the **fill step** that uses extra time | O(k²) per insertion | O(k) |
| Held–Karp (bitmask DP) | `held_karp.py` | Comparison only: the exact shortest tour | O(2ᵏ·k²) | O(2ᵏ·k) |

### How they work together (the pipeline)

`services/itinerary_generator.py`:

1. **Once per city or city group (cached):** places, hours and road links (local + intercity) → adjacency list → Dijkstra
   from every place → raw travel table → **planning table** = each shortest time rounded **up** to 10 minutes.
2. **Once per trip:** score each place, `round(100 × (0.5·rating/5 + 0.3·popularity + 0.2·interest_match))` (unrated places
   use a neutral 4.0 prior); apply trip rules (excluded, no road access, food/shopping only when asked for, "only matching interests").
3. **For each day, in date order:** filter → **select** (one knapsack instance; DP, Greedy or Max visits) → **route** (travel-first
   NN → 2-opt, or window-first insertion → 2-opt) → **check** (`scheduler.py` simulates the day, meals included) → **repair**
   (weakest stop leaves, select again) → **fill** (leftovers inserted where they still fit). Multi-city: this runs for each city
   alone and for all together, and the day keeps the best by the strategy's objective.
4. **Validate:** `services/validator.py` re-checks every constraint from the raw data. Tests require zero violations.

**Knapsack capacity.** Each stop's weight is `visit + pace buffer + cheapest way out` (a lower bound on real travel); the
capacity is the day minus the shortest first ride, the unavoidable extra of the ride home and the meal breaks. So no set that
truly fits is ever thrown away. **What is optimal.** The full problem (multi-day orienteering with time windows) is NP-hard.
DP and Max visits are exact for each day's rounded knapsack model; 2-opt is a local optimum; Held–Karp is exact for travel only.

### The three strategies (requirement: meaningfully different objectives)

| Strategy | Objective | Guarantee |
|---|---|---|
| DP | maximum total value score | exact for the knapsack model |
| Greedy | value per unit of time and money, taken in order | fast heuristic, can miss better combinations |
| Max visits | maximum number of places, then maximum value | exact for the knapsack model |

They share candidates, weights, costs, capacity, routing, meals, repair and validation, so differences come only from the
objective. Live demos on `/compare`: the greedy trap (Greedy 90 vs DP 120) and value vs count (DP picks a valuable 2-hour place +
one short one; Max visits picks three short ones). On real data they often coincide — most newer cities have 4–8 plannable places,
which all fit — and the page says so instead of inventing differences.

### Scoring on the comparison page

Raw metrics come from the actual plans: places visited, value, travel per place, share of time sightseeing, value per
₹100 (smoothed with a ₹100 baseline), validator violations and runtime. Each metric is normalised against the best strategy on
the same trip (100 = best; `value ÷ best` for higher-is-better, `best ÷ value` for travel), then weighted: value 40%, coverage 20%,
travel efficiency 15%, time utilisation 15%, budget efficiency 10% (left out when nobody spends anything). **Feasibility is a gate**:
any validator violation makes a plan ineligible. Runtime is shown, not scored. Ties and identical timelines are reported as such.
Route-building methods are compared in their own section, never mixed into this score.

---

## Features added in the second iteration

* **Reproducibility.** No randomness, no set-order dependence; ties broken by value, then travel, then the place's row in the
  dataset. Interests and nearby cities are canonicalised. Every itinerary shows four fingerprints — inputs, data (CSV hash),
  settings (`config.fingerprint_settings()`), plan — so a changed plan is traceable to a changed input, dataset or setting.
* **Travel rounding.** Planned legs are the raw shortest path rounded **up** to 10 minutes (0 stays 0; ∞ stays "no route"); raw
  minutes are kept for route optimisation and shown on hover. Clock times, opening hours and the user's window are never rounded.
* **Using the whole day.** Longer windows raise the knapsack capacity; the fill step inserts leftovers; unused time is explained
  per day (closing times, budget, meals, nothing left).
* **Meals.** Lunch (12:00–14:30, 45 min) and dinner (19:00–21:30, 60 min) by default, adjustable or off. Planned only when the meal
  cannot be had before the day starts or after it ends. At a listed food place within 20 minutes, else a generic break — no venue claimed.
* **Multi-city trips.** Up to 3 nearby cities; every pair within 100 km straight line (haversine between centres). OSRM intercity
  links; a labelled straight-line estimate (km × 1.35 at 40 km/h) only if no link exists. One base for the whole trip.
* **26 interests** in 5 groups with a parent hierarchy (street food → food), "prefer" or "only" modes, limited-data notes.
* **Food and shopping.** Wikipedia-backed food streets, restaurants, cafés, markets and malls (47 places in 16 cities); opt-in as stops,
  also used as meal venues; venue style and vegetarian-only filters (vegetarian only when the source says so); shopping time and
  spend. `scripts/discover_food_shopping.py` documents open-data options; `scripts/import_osm_places.py` lists OSM places for review.
* **UI.** Redesigned footer (call to action, link groups by visitor task, live dataset numbers, data note, attribution row),
  destination filters, grouped pickers for 50 cities, meal entries in the timeline, time-use and scorecard charts (palette checked
  for colour-blind safety, every chart backed by a table), provenance marks (`est.`, `OSM`, "Not rated").

---

## Data: sources, assumptions and limitations

| Data | Source | Status |
|---|---|---|
| Destinations | The team's **Top-50** list (`data/catalog/top50.csv`, from `Top_50_Tourist_Destinations_India.xlsx`), a subset of the 200-destination catalog | Exactly the provided list |
| Attraction names | The catalog's famous attractions, mapped by hand to Wikipedia articles or OSM (`data/curation/attraction_titles.csv`); names with no reliable location are kept out and listed on the Destinations page with the reason | Reviewed mapping |
| Coordinates | Wikipedia, cross-checked against Wikidata and OpenStreetMap (Nominatim); disagreements > 2 km reviewed by hand (`data/curation/coordinate_review.csv`); 6 approximate in the original cities | Sourced (`coord_source`) |
| Road links | OSRM on OpenStreetMap roads: each place to its 5 nearest places, plus intercity links for city pairs within 100 km. A few unrouted pairs use labelled straight-line estimates | Real roads, free-flow |
| Road access | Places on treks, islands or reached by boat (16) are marked `no_road` with a note and never routed by road | Reviewed |
| Traffic | One assumed multiplier, `TRAFFIC_FACTOR = 1.5` | **Assumption** |
| Popularity | Newer cities: Wikipedia page views over 12 months, log-scaled with fixed bounds (1,000 → 0, 3,000,000 → 1). Original cities: hand-chosen | Sourced / illustrative |
| Ratings | No open source exists: newer places are **not rated** (neutral 4.0 prior in the score); the original 60 keep hand-chosen ratings | Never invented |
| Opening hours, fees, visit lengths | OpenStreetMap tags when present and readable; otherwise the documented default for that kind of place (`data/estimate_defaults.csv`). Original cities: hand-chosen | Labelled **estimate** / **illustrative** |
| Descriptions | Wikipedia lead sentences (CC BY-SA) for newer places; written for the project for the original 60 | Attributed |
| Photos | Wikimedia Commons, free licences only; author and licence in `data/image_credits.csv` and on the About page | Credited |

**Readiness.** A city is *ready* when at least 3 attractions are reachable by road from its start point; *limited* with 1–2;
*not plannable* with none. Current data: 45 ready, 4 limited (Katra, Alleppey, Sabarimala, Kanyakumari — sights on treks or
islands), 1 not plannable (Kedarnath, a 16 km trek). The interface says so wherever the city appears.

**Limitations**

* The full problem is NP-hard; select-then-route can miss a better combination, and DP can lose to Greedy on a whole trip.
* Days are planned in date order (myopic across days); one base for a multi-city trip (no overnight moves).
* Most hours, fees and visit times in the newer cities are category defaults; weekly closing days are unknown.
* Multi-city eligibility uses straight-line distance; road distance is shown where known.
* Treks, ferries, rope-ways, ceremonies with changing times and timetabled trains are not modelled.
* Food and shopping coverage follows Wikipedia and is thin in small towns; meal costs are not budgeted.
* Map lines are straight segments in visit order, not road geometry (the map says so).

### Rebuilding or extending the data (no algorithm changes)

```bash
python scripts/build_city_dataset.py fetch    # Wikipedia, Wikidata, page views, OSM -> data/curation/source_snapshot.json
python scripts/build_city_dataset.py report   # coordinates that disagree, places with no location
python scripts/build_city_dataset.py build    # snapshot + curation -> data/*.csv (original four cities untouched)
python scripts/build_city_dataset.py images   # free-licence photos + data/image_credits.csv
python scripts/build_travel_times.py          # OSRM road links for cities without any, and intercity links
python -m database.seed_data && python -m pytest
```

---

## Architecture and project structure

```
browser ──► Flask routes ──► services ──► algorithms (pure functions)
                              │
                              └──► database (all SQL in database/queries.py; migrations.py for safe updates)
```

```
ADA PROJECT FINAL/
├── app.py  config.py  requirements.txt  pytest.ini  .gitignore  README.md
├── algorithms/      graph, dijkstra, sorting, scoring, knapsack_types, greedy, dynamic_programming, max_visits,
│                    nearest_neighbor, two_opt, activity_selection, insertion, held_karp, tour
├── services/        models, trip_request, city_data (city groups), multicity, scheduler (meals), itinerary_generator,
│                    validator, scorecard, comparison, versioning, crosscheck, timing, timeutil, algorithm_info
├── database/        schema.sql, db.py, queries.py, seed_data.py, migrations.py
├── routes/          main_routes.py, itinerary_routes.py, api_routes.py, helpers.py
├── templates/       base (with footer), _macros, index, cities, attractions, planner, itinerary, compare, about, error
├── static/          css/style.css, js/ (site, attractions, planner, itinerary, compare), images/, fonts/, vendor/
├── data/            cities, start_points, attractions, opening_hours, categories, travel_times, intercity_times,
│                    image_credits, estimate_defaults (.csv); catalog/ (team lists); curation/ (reviewed mappings + source snapshot)
├── scripts/         build_city_dataset, build_travel_times, fetch_wikimedia, discover_food_shopping, import_osm_places,
│                    import_catalog, benchmark, net
├── results/         saved benchmark outputs (charted on /compare)
├── tests/           pytest suite + tests/fixtures/tiny_city
└── instance/        generated SQLite database and backups (git-ignored)
```

---

## Viva notes

* **Why Dijkstra if we have coordinates?** We store only local road links; Dijkstra composes them (and intercity links) into shortest travel times. Coordinates give straight lines, not roads.
* **Why round travel up to 10 minutes?** Road times are estimates; rounding up means a plan that fits on paper does not fail because a ride took 14 minutes. The whole path is rounded, not each link, so composing links does not inflate it.
* **Where is travel time in the knapsack?** Each stop's weight includes its cheapest way out (a lower bound); the capacity also removes the shortest first ride, the unavoidable extra of the ride home and the meals.
* **How is Max visits different from DP?** Same DP, different values: `B + score` with `B = Σ scores + 1` makes one extra place worth more than any score difference — count first, value second.
* **Show the strategies differing.** Greedy trap (90 vs 120) and value vs count (2 valuable stops vs 3 ordinary ones), both run live on `/compare`.
* **Is DP's itinerary always better?** No. On the identical knapsack it is guaranteed; on whole itineraries routing, meals, repair and multi-day effects can reverse it — in our 648-trip sweep DP was ahead in 126, Greedy in 3, equal in 519.
* **Why does a longer day sometimes change nothing?** Because everything still open is already planned; the day summary lists the closing times. The tests check that stops never decrease as the day grows.
* **How do you know plans are reproducible?** Same inputs + data + settings → same plan fingerprint, tested under three different hash seeds.
* **What is the 100 km rule exactly?** Every pair of cities in the trip, straight-line distance between city centres; a road estimate is labelled when no road link is stored.
* **How do you know Dijkstra is correct?** Unit tests plus 0 mismatches against NetworkX on every pair, in every city and on random graphs.

---

## Credits

Map tiles © OpenStreetMap contributors · Routing data © OpenStreetMap contributors (ODbL), computed with OSRM ·
Descriptions from Wikipedia (CC BY-SA) where marked · Wikidata (CC0) · Photos: Wikimedia Commons contributors (see
`data/image_credits.csv`) · Fonts: Fraunces and Inter (SIL OFL) · Bootstrap, Bootstrap Icons, Leaflet and Chart.js (MIT / BSD licences).
