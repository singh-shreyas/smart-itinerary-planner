"""Selection: Greedy, dynamic programming, sorting and scoring."""

import random

import pytest

from algorithms.dynamic_programming import brute_force_select, dp_select
from algorithms.greedy import greedy_select
from algorithms.knapsack_types import Item
from algorithms.scoring import attraction_score
from algorithms.sorting import merge_sort, rank_by_score

WEIGHTS = (0.5, 0.3, 0.2)


def random_items(rng, n):
    return [Item(i, rng.randint(1, 100), rng.randint(1, 20)) for i in range(n)]


def test_greedy_trap():
    """The classic counter-example: Greedy takes X (best density) and gets stuck at 90; DP finds Y + Z = 120."""
    items = [Item("X", 90, 18), Item("Y", 60, 15), Item("Z", 60, 15)]
    greedy, dp = greedy_select(items, 30), dp_select(items, 30)
    assert greedy.chosen == ["X"] and greedy.score == 90
    assert sorted(dp.chosen) == ["Y", "Z"] and dp.score == 120


def test_dp_equals_brute_force():
    rng = random.Random(7)
    for _ in range(200):
        items = random_items(rng, rng.randint(0, 10))
        T = rng.randint(0, 60)
        assert dp_select(items, T).score == brute_force_select(items, T).score


def test_dp_never_below_greedy_and_both_respect_limits():
    rng = random.Random(11)
    for _ in range(300):
        items = random_items(rng, rng.randint(1, 14))
        T = rng.randint(1, 80)
        greedy, dp = greedy_select(items, T), dp_select(items, T)
        assert dp.score >= greedy.score
        for result in (greedy, dp):
            assert result.weight <= T
            assert len(set(result.chosen)) == len(result.chosen)


def test_empty_inputs():
    for select in (greedy_select, dp_select):
        assert select([], 10).chosen == []
        assert select([Item(1, 5, 1)], 0).chosen == []


def test_classic_one_dimensional_knapsack():
    items = [Item(1, 60, 1), Item(2, 100, 2), Item(3, 120, 3)]
    assert dp_select(items, 5).score == 220           # items 2 + 3


def test_greedy_is_optimal_when_all_weights_are_equal():
    rng = random.Random(3)
    for _ in range(50):
        items = [Item(i, rng.randint(1, 100), 4) for i in range(rng.randint(1, 10))]
        T = 4 * rng.randint(0, 6)
        assert greedy_select(items, T).score == dp_select(items, T).score


def test_merge_sort_matches_sorted_and_is_stable():
    rng = random.Random(5)
    for _ in range(100):
        data = [(rng.randint(0, 5), i) for i in range(rng.randint(0, 40))]
        assert merge_sort(data, key=lambda x: x[0]) == sorted(data, key=lambda x: x[0])   # sorted() is stable too
    assert rank_by_score([3, 1, 2], {1: 50, 2: 80, 3: 50}) == [2, 1, 3]                   # ties by smaller id


def test_score_formula():
    assert attraction_score(5.0, 1.0, ("history",), ("history",), WEIGHTS) == 100
    assert attraction_score(0.0, 0.0, ("history",), (), WEIGHTS) == 0
    assert attraction_score(4.0, 0.5, ("nature",), (), WEIGHTS) == round(100 * (0.5 * 0.8 + 0.3 * 0.5))
    # A higher rating never lowers the score; a matching interest always raises it.
    assert attraction_score(4.6, 0.5, ("nature",), (), WEIGHTS) > attraction_score(4.2, 0.5, ("nature",), (), WEIGHTS)
    assert attraction_score(4.0, 0.5, ("nature",), ("nature",), WEIGHTS) == attraction_score(4.0, 0.5, ("nature",), (), WEIGHTS) + 20


@pytest.mark.parametrize("select", [greedy_select, dp_select])
def test_selection_is_deterministic(select):
    items = random_items(random.Random(99), 12)
    assert select(items, 40) == select(items, 40)
