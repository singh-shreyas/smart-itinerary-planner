# Attraction value score, 0..100 (as in algorithms/scoring.py; weights and prior from config.py)
W_RATING, W_POPULARITY, W_INTEREST = 0.5, 0.3, 0.2
RATING_PRIOR = 4.0


def expand_categories(categories, parents):
    result = set()
    for category in categories:
        while category and category not in result:   # walk up: street-food -> food
            result.add(category)
            category = parents.get(category)
    return result


def attraction_score(rating, popularity, categories, interests, parents, prior=RATING_PRIOR):
    if rating is None:
        rating = prior                                # neutral prior, not an invented rating
    match = 1 if expand_categories(categories, parents) & set(interests) else 0
    value = W_RATING * (rating / 5) + W_POPULARITY * popularity + W_INTEREST * match
    return round(100 * value)


if __name__ == "__main__":
    parents = {"street-food": "food", "fort": "history"}
    print(attraction_score(4.6, 0.8, ["fort"], ["history"], parents))        # matches via parent
    print(attraction_score(4.6, 0.8, ["fort"], ["food"], parents))           # no match
    print(attraction_score(None, 0.5, ["street-food"], ["food"], parents))   # unrated -> prior 4.0
