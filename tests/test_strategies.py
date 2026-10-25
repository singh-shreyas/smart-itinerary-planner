"""Requirement 5 and 7: three distinct objectives on one instance, and an honest scorecard."""

import itertools
import random

from algorithms.dynamic_programming import dp_select
from algorithms.greedy import greedy_select
from algorithms.knapsack_types import Item
from algorithms.max_visits import max_visits_select
from conftest import make_trip
from services import scorecard
from services.comparison import compare_selection, greedy_trap, run_comparison, value_vs_count

SELECTORS = {"dp": dp_select, "greedy": greedy_select, "max_visits": max_visits_select}


def best_count_then_value(items, T):
    best = (-1, -1)
    for r in range(len(items) + 1):
        for subset in itertools.combinations(items, r):
            if sum(i.weight for i in subset) <= T:
                best = max(best, (len(subset), sum(i.score for i in subset)))
    return best


def test_designed_instance_where_all_three_can_differ():
    """Greedy trap: X has the best value per minute but blocks Y + Z."""
    trap = greedy_trap()
    assert trap["greedy"]["chosen"] == ["X"] and trap["greedy"]["score"] == 90
    assert sorted(trap["dp"]["chosen"]) == ["Y", "Z"] and trap["dp"]["score"] == 120
    assert trap["max_visits"]["count"] == 2


def test_designed_instance_where_value_and_count_differ():
    """One valuable 2-hour place vs three short ordinary ones in 3 hours."""
    demo = value_vs_count()
    assert sorted(demo["dp"]["chosen"]) == ["A", "B"] and demo["dp"]["score"] == 120
    assert sorted(demo["max_visits"]["chosen"]) == ["B", "C", "D"] and demo["max_visits"]["count"] == 3
    assert demo["greedy"]["chosen"] == demo["dp"]["chosen"]          # Greedy happens to agree with DP here


def test_when_everything_fits_all_three_coincide():
    items = [Item(i, 10 + i, 3) for i in range(5)]
    results = {k: f(items, 100).chosen for k, f in SELECTORS.items()}
    assert results["dp"] == results["greedy"] == results["max_visits"] == [0, 1, 2, 3, 4]


def test_max_visits_is_exact_for_count_then_value():
    rng = random.Random(42)
    for _ in range(150):
        items = [Item(i, rng.randint(1, 100), rng.randint(1, 12)) for i in range(rng.randint(0, 9))]
        T = rng.randint(0, 40)
        result = max_visits_select(items, T)
        assert (len(result.chosen), result.score) == best_count_then_value(items, T)
        assert result.weight <= T


def test_on_identical_instances_each_selector_is_best_at_its_own_objective(tiny_city):
    rows = compare_selection(tiny_city, make_trip(days=2, day_end=20 * 60), repeats=1)
    assert rows
    for r in rows:
        assert r["dp"]["score"] >= r["greedy"]["score"] and r["dp"]["score"] >= r["max_visits"]["score"]
        assert r["max_visits"]["count"] >= r["dp"]["count"] and r["max_visits"]["count"] >= r["greedy"]["count"]


def test_full_comparison_on_the_same_trip(tiny_city, tmp_path):
    result = run_comparison(tiny_city, make_trip(days=2, day_end=20 * 60), str(tmp_path), repeats=1)
    rows = result["strategies"]
    assert [r["key"] for r in rows] == ["dp", "greedy", "max_visits"]
    assert all(r["feasible"] for r in rows)
    for r in rows:
        assert set(r["subscores"]) == {"value", "coverage", "travel", "utilisation"}
        assert all(0 <= v <= 100 for v in r["subscores"].values())
    best_value = max(r["metrics"]["value"] for r in rows)
    assert all(r["subscores"]["value"] == 100.0 for r in rows if r["metrics"]["value"] == best_value)
    assert result["recommendation"]["status"] in ("winner", "tie")
    assert result["routing"] and all(r["improvement_pct"] >= 0 for r in result["routing"])


def fake_row(key, stops, value, travel, util, violations=0):
    return {"key": key, "metrics": {"stops": stops, "value": value, "travel_per_stop": travel / stops if stops else None,
                                    "utilisation": util, "violations": violations,
                                    "travel_min": travel, "avg_value": value / stops if stops else 0}}


def test_infeasible_plans_are_never_recommended():
    rows = [fake_row("dp", 4, 300, 80, .5), fake_row("greedy", 3, 250, 60, .4),
            fake_row("max_visits", 9, 400, 90, .7, violations=2)]
    scorecard.subscores(rows)
    assert rows[2]["overall"] > rows[0]["overall"]                  # best on paper ...
    rec = scorecard.recommend(rows, {})
    assert rec["status"] == "winner" and rec["keys"] == ["dp"]     # ... but never recommended


def test_identical_plans_are_reported_as_a_tie():
    rows = [fake_row("dp", 4, 300, 80, .5), fake_row("greedy", 4, 300, 80, .5),
            fake_row("max_visits", 5, 250, 120, .45)]
    scorecard.subscores(rows)
    rec = scorecard.recommend(rows, {"dp": "abc", "greedy": "abc", "max_visits": "def"})
    assert rec["status"] == "tie" and set(rec["keys"]) == {"dp", "greedy"}
    assert ["dp", "greedy"] in rec["identical"] and "same itinerary" in rec["text"]


def test_overall_score_is_a_valid_weighted_sum():
    rows = [fake_row("dp", 4, 300, 80, .5), fake_row("greedy", 3, 250, 60, .4)]
    weights = scorecard.subscores(rows)
    assert set(weights) == {"value", "coverage", "travel", "utilisation"}
    assert abs(sum(weights.values()) - 1) < 1e-9
    for r in rows:
        assert r["overall"] == round(sum(weights[k] * r["subscores"][k] for k in weights), 1)
        assert 0 <= r["overall"] <= 100


def test_no_feasible_plan_means_no_recommendation():
    rows = [fake_row("dp", 0, 0, 0, 0), fake_row("greedy", 2, 100, 30, .2, violations=1)]
    scorecard.subscores(rows)
    assert scorecard.recommend(rows, {})["status"] == "none"
