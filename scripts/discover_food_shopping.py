"""One-off data script: find candidate food and shopping places on Wikipedia (needs internet).

    python scripts/discover_food_shopping.py > data/curation/food_shopping_candidates.txt

For each city it asks Wikipedia for articles within 10 km of the city centre
(list=geosearch) and keeps those whose categories mention markets, bazaars,
shopping malls, restaurants, cafés or street food. The output is a list for a
PERSON to review: the chosen places go into data/curation/food_shopping.csv.

Why Wikipedia: every name, location and description is from a published,
openly licensed source, so nothing is invented. Coverage is uneven (big cities
have many notable markets and restaurants, small towns few or none), and the
planner tells the traveller when a food or shopping interest has little data.

Other open sources that could add listings later (not used automatically):
  * OpenStreetMap via the Overpass API -- ODbL licence (attribution, share-alike
    for the database); free; fair-use limits (about 10,000 queries/day and a
    couple of parallel requests on the public server); restaurants, cafés and
    markets are widely mapped, but opening hours and cuisine tags are often missing.
  * Wikidata -- CC0; free SPARQL endpoint with a 60-second query limit; good for
    notable places, few small eateries.
  * Foursquare Open Source Places -- Apache 2.0 bulk download (large files, no live
    API key needed); broad coverage, quality varies.
Commercial APIs (Google Places, Zomato) need paid keys or forbid storing data, so
they are not used.
"""

import json
import os
import re
import sys
import time

from net import get_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(ROOT, "data", "curation", "source_snapshot.json")
WIKI = "https://en.wikipedia.org/w/api.php"
PATTERN = re.compile(r"\b(markets?|bazaars?|shopping|malls?|restaurants?|cafés?|cafes?|street food|food|eateries|"
                     r"sweet shops?|bakeries|bakery|cuisine)\b", re.I)
CENTRES = {"delhi": (28.6139, 77.2090), "agra": (27.1767, 78.0081), "jaipur": (26.9124, 75.7873),
           "varanasi": (25.3176, 82.9739)}


def geosearch(lat, lng):
    data = get_json(WIKI, {"action": "query", "format": "json", "list": "geosearch", "gscoord": f"{lat}|{lng}",
                           "gsradius": 10000, "gslimit": 500})
    return [p["title"] for p in data["query"]["geosearch"]]


def categories(titles):
    out = {}
    for i in range(0, len(titles), 50):
        data = get_json(WIKI, {"action": "query", "format": "json", "formatversion": 2, "prop": "categories|description",
                               "clshow": "!hidden", "cllimit": "max", "titles": "|".join(titles[i:i + 50])})
        for page in data["query"]["pages"]:
            out[page["title"]] = ([c["title"].removeprefix("Category:") for c in page.get("categories", [])],
                                  page.get("description", ""))
        time.sleep(0.3)
    return out


def main():
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = json.load(f)
    centres = dict(CENTRES)
    centres.update({slug: (c["lat"], c["lng"]) for slug, c in snapshot["cities"].items()})
    for slug, (lat, lng) in sorted(centres.items()):
        titles = geosearch(lat, lng)
        cats = categories(titles)
        hits = [(t, c, d) for t, (c, d) in cats.items() if any(PATTERN.search(x) for x in c) or PATTERN.search(d)]
        print(f"## {slug} ({len(hits)} of {len(titles)} articles)")
        for title, cs, desc in sorted(hits):
            print(f"   {title} | {desc} | {'; '.join(x for x in cs if PATTERN.search(x))[:120]}")
        sys.stdout.flush()
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
