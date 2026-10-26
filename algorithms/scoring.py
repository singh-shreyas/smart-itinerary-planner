"""Attraction value score used by every selection strategy.

    score = round(100 * (w_rating * rating / 5 + w_popularity * popularity + w_interest * match))

rating is 0..5, popularity is 0..1, match is 1 if any of the attraction's
categories (or their parent categories) is among the user's interests, else 0.
With weights that sum to 1 the score is an integer from 0 to 100, which the DP
table can use directly. The weights are a documented design choice (see
config.py), not a fact.

Unrated places: when no rating exists (rating is None) the neutral `prior` is
used instead. The place is shown as "not rated"; nothing is invented.

Category hierarchy: categories can have a parent (street-food -> food). A place
tagged "street-food" also matches the interest "food", but a place tagged only
"food" does NOT match the narrower interest "street-food".
"""


def expand_categories(categories, parents=None):
    """The categories plus every ancestor: {'street-food'} -> {'street-food', 'food'}."""
    parents = parents or {}
    result = set()
    for category in categories:
        while category and category not in result:
            result.add(category)
            category = parents.get(category)
    return result


def matches_interests(categories, interests, parents=None):
    """True if any (expanded) category of the place is one of the interests."""
    return bool(expand_categories(categories, parents) & set(interests))


def attraction_score(rating, popularity, categories, interests, weights, prior=None, parents=None):
    
    """Return the integer score of one attraction.

    weights: (w_rating, w_popularity, w_interest)
    prior:   rating used when `rating` is None (no rating data)
    parents: {category: parent category} for the hierarchy
    """

    w_rating, w_popularity, w_interest = weights
    if rating is None:
        rating = prior if prior is not None else 0
    match = 1 if matches_interests(categories, interests, parents) else 0
    value = w_rating * (rating / 5) + w_popularity * popularity + w_interest * match
    return round(100 * value)
