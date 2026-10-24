"""Central configuration.

Every tunable number used by the planner lives here (score weights, pace
settings, DP discretisation, traffic factor, ...), so nothing is hidden inside
the algorithm code and each value can be explained in the viva.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # --- Flask / storage -------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secret")
    DATABASE = os.path.join(BASE_DIR, "instance", "itinerary.db")
    DATA_DIR = os.path.join(BASE_DIR, "data")
    RESULTS_DIR = os.path.join(BASE_DIR, "results")
    # Build the SQLite database from the CSV files on start-up if it is missing.
    AUTO_SEED = True

    # --- Travel model ----------------------------------------------------
    # OSRM gives free-flow driving minutes (no traffic). We multiply them by a
    # single assumed traffic factor. This is an ASSUMPTION, not a calibrated
    # value, and it is shown on the About page.
    TRAFFIC_FACTOR = 1.5
    # Estimated local transport cost (auto-rickshaw / cab), rupees per km.
    # Illustrative value used only when the user includes transport in the budget.
    TRANSPORT_COST_PER_KM = 12


# --- Trip input limits (used by server-side validation) -------------------
MAX_DAYS = 5
MIN_DAY_LENGTH_MIN = 120          # day end must be at least 2 hours after start
MAX_BUDGET_INR = 100_000
DEFAULT_DAY_START = "09:00"
DEFAULT_DAY_END = "19:00"
DEFAULT_PACE = "balanced"
DEFAULT_STRATEGY = "dp"

# --- Scoring ---------------------------------------------------------------
# score = round(100 * (W_RATING * rating/5 + W_POPULARITY * popularity + W_INTEREST * match))
# A documented design choice; the three weights sum to 1 so scores are 0..100.
W_RATING = 0.5
W_POPULARITY = 0.3
W_INTEREST = 0.2

# --- Pace --------------------------------------------------------------------
# Buffer minutes added after every visit (rest, photos, food, finding the exit).
PACES = {
    "relaxed": {"label": "Relaxed", "buffer": 30,
                "hint": "30 min breathing room after every stop"},
    "balanced": {"label": "Balanced", "buffer": 15,
                 "hint": "15 min after every stop"},
    "packed": {"label": "Packed", "buffer": 5,
               "hint": "Only 5 min between stops, fit in the most"},
}

# --- Selection strategies ---------------------------------------------------
STRATEGIES = {
    "dp": "Dynamic programming (0/1 knapsack)",
    "greedy": "Greedy (best value per minute)",
    "max_visits": "Activity selection (max visits)",
}

# --- Dynamic programming discretisation ------------------------------------
# Item weights are rounded UP to 10-minute units and the capacity rounded DOWN,
# so any set the DP accepts really fits. Money units are max(Rs 10, budget/100)
# so the money axis never has more than ~100 cells.
DP_TIME_UNIT_MIN = 10
DP_MIN_MONEY_UNIT = 10
DP_MAX_MONEY_CELLS = 100

# --- Comparison page ------------------------------------------------------
HELD_KARP_MAX_STOPS = 10          # 2^k * k^2 grows fast; exact tour only for small days
TIMING_REPEATS = 5                # median of N timed runs after one warm-up
QUALITY_LAMBDA = 0.2              # Q = total score - lambda * travel minutes
