"""Attraction value score used by every selection strategy.

    score = round(100 * (w_rating * rating / 5 + w_popularity * popularity + w_interest * match))

rating is 0..5, popularity is 0..1, match is 1 if any of the attraction's
categories is among the user's interests (else 0). With weights that sum to 1
the score is an integer from 0 to 100, which the DP table can use directly.
The weights are a documented design choice (see config.py), not a fact.
"""


def attraction_score(rating, popularity, categories, interests, weights):
    """Return the integer score of one attraction.

    weights: (w_rating, w_popularity, w_interest)
    """
    w_rating, w_popularity, w_interest = weights
    match = 1 if set(categories) & set(interests) else 0
    value = w_rating * (rating / 5) + w_popularity * popularity + w_interest * match
    return round(100 * value)
