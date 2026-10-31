"""Attraction value score used by every selection strategy.

    score = round(100 * (w_rating * rating / 5 + w_popularity * popularity + w_interest * match))

Inputs
------
rating      0..5, the average user rating (or None if the place is unrated).
popularity  0..1, how popular the place is, already normalised.
match       1 if any of the attraction's categories (or their parent
            categories) is among the user's interests, else 0.

Why the score is an integer from 0 to 100:

Each of the three parts is first scaled to 0..1 (rating / 5, popularity,
match). They are then combined with weights that sum to 1, so the weighted
sum is also between 0 and 1. Multiplying by 100 and rounding gives an integer
from 0 to 100. Integer scores matter because the selection DP (knapsack-style)
table can use the score directly as a value, with no floating-point issues.
The weights are a documented design choice (see config.py), not a fact.

Unrated places:

When no rating exists (rating is None), a neutral `prior` rating is used
instead, so the place is neither rewarded nor punished for missing data. The
place is still displayed as "not rated"; no rating is invented.

Category hierarchy:

Categories can have a parent (street-food -> food).
  - A place tagged "street-food" ALSO matches the broader interest "food".
  - A place tagged only "food" does NOT match the narrower interest
    "street-food".
In other words, matching flows upward (specific -> general), never downward.
"""


def expand_categories(categories, parents=None):
    """Return the categories plus every ancestor.

    Example: {'street-food'} -> {'street-food', 'food'}

    `parents` maps a category to its parent, e.g. {'street-food': 'food'}.
    """
    parents = parents or {}          # no hierarchy supplied -> empty mapping
    result = set()
    for category in categories:
        # Walk up the parent chain until we run out of parents (None) or hit
        # a category we've already added. The `not in result` check also
        # protects against infinite loops if the data contains a cycle
        # (a -> b -> a) and avoids repeating work for shared ancestors.
        while category and category not in result:
            result.add(category)
            category = parents.get(category)
    return result


def matches_interests(categories, interests, parents=None):
    """True if any (expanded) category of the place is one of the interests.

    The place's categories are expanded to include their ancestors, then
    intersected with the user's interests. A non-empty intersection means
    at least one interest matches.
    """
    return bool(expand_categories(categories, parents) & set(interests))


def attraction_score(rating, popularity, categories, interests, weights, prior=None, parents=None):
    """Return the integer score of one attraction.

    rating:     0..5, or None if the place has no rating data
    popularity: 0..1
    categories: the place's own category tags
    interests:  the categories the user said they care about
    weights:    (w_rating, w_popularity, w_interest), should sum to 1
    prior:      rating used when `rating` is None (no rating data)
    parents:    {category: parent category} for the hierarchy
    """

    w_rating, w_popularity, w_interest = weights

    # Step 1: handle a missing rating. Use the neutral prior if one was given,
    # otherwise fall back to 0 (the lowest possible rating).
    if rating is None:
        rating = prior if prior is not None else 0

    # Step 2: interest match is binary: 1 if any category (or ancestor)
    # matches a user interest, else 0.
    match = 1 if matches_interests(categories, interests, parents) else 0

    # Step 3: weighted sum of three values, each on a 0..1 scale.
    #   rating / 5 converts the 0..5 rating to 0..1.
    value = w_rating * (rating / 5) + w_popularity * popularity + w_interest * match

    # Step 4: scale to 0..100 and round to an integer for the DP table.
    return round(100 * value)