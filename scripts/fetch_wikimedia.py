"""One-off data script: photos and a coordinate cross-check from Wikipedia/Wikimedia.

    python scripts/fetch_wikimedia.py --coords    # compare data/attractions.csv lat/lng with Wikipedia
    python scripts/fetch_wikimedia.py --images    # download free-licensed photos + write data/image_credits.csv
    python scripts/fetch_wikimedia.py --wikidata-images   # fill gaps: the Wikidata image (P18) of each place
                                                          # still without a photo, free licences only

Only images Wikipedia marks as freely licensed are used (pilicense=free). Each
photo's author and licence are recorded in data/image_credits.csv and shown in
the app. Photos are downloaded once (never hot-linked at runtime).
This script is run by hand; the web app never calls the internet for data.
"""

import argparse
import csv
import html
import math
import os
import re
import sys
import time
import urllib.parse

from net import download, get_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
STATIC = os.path.join(ROOT, "static")
CARD_WIDTH = 960
HERO_WIDTH = 1920
# Which attraction photo represents each city on the cities page and hero banners.
CITY_HERO = {"delhi": "humayuns-tomb", "agra": "taj-mahal", "jaipur": "amber-fort", "varanasi": "dashashwamedh-ghat"}


def read_attractions():
    with open(os.path.join(DATA, "attractions.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def wiki_pages(titles):
    """Coordinates and free page image for up to 50 Wikipedia titles."""
    data = get_json("https://en.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2, "redirects": 1,
        "prop": "coordinates|pageimages", "piprop": "name", "pilicense": "free",
        "colimit": "max", "pilimit": "max",
        "titles": "|".join(titles),
    })
    query = data["query"]
    rename = {}
    for step in query.get("normalized", []) + query.get("redirects", []):
        rename[step["from"]] = step["to"]
    pages = {p["title"]: p for p in query["pages"]}
    result = {}
    for title in titles:
        final = title
        while final in rename:
            final = rename[final]
        result[title] = pages.get(final, {})
    return result


def image_info(file_name, width):
    """URL of a resized copy plus author / licence metadata (Commons first, then en.wikipedia)."""
    for api in ("https://commons.wikimedia.org/w/api.php", "https://en.wikipedia.org/w/api.php"):
        data = get_json(api, {
            "action": "query", "format": "json", "formatversion": 2,
            "titles": f"File:{file_name}", "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime", "iiurlwidth": width,
        })
        page = data["query"]["pages"][0]
        if "imageinfo" in page:
            info = page["imageinfo"][0]
            meta = info.get("extmetadata", {})
            artist = re.sub(r"<[^>]+>", "", html.unescape(meta.get("Artist", {}).get("value", "Unknown"))).strip()
            licence = meta.get("LicenseShortName", {}).get("value", "see source")
            return {"url": info.get("thumburl") or info["url"], "page": info["descriptionurl"],
                    "artist": " ".join(artist.split())[:120], "license": licence, "mime": info.get("mime", "")}
    return None


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def check_coordinates(rows):
    titles = [r["wiki_title"] for r in rows]
    pages = {}
    for i in range(0, len(titles), 50):
        pages.update(wiki_pages(titles[i:i + 50]))
    print(f"{'slug':28} {'ours':>22} {'wikipedia':>22} {'km':>6}")
    for r in rows:
        page = pages.get(r["wiki_title"], {})
        coords = page.get("coordinates")
        if not coords:
            print(f"{r['slug']:28} {'':>22} {'(no coordinates)':>22}")
            continue
        lat, lng = coords[0]["lat"], coords[0]["lon"]
        km = haversine_km(float(r["lat"]), float(r["lng"]), lat, lng)
        flag = "  <-- check" if km > 0.6 else ""
        print(f"{r['slug']:28} {r['lat']+','+r['lng']:>22} {f'{lat:.4f},{lng:.4f}':>22} {km:6.2f}{flag}")


def fetch_images(rows):
    pages = {}
    titles = [r["wiki_title"] for r in rows]
    for i in range(0, len(titles), 50):
        pages.update(wiki_pages(titles[i:i + 50]))

    credits = []
    for r in rows:
        page = pages.get(r["wiki_title"], {})
        file_name = page.get("pageimage")
        if not file_name:
            print(f"no free image for {r['slug']} ({r['wiki_title']})")
            continue
        jobs = [("attraction", CARD_WIDTH)]
        if CITY_HERO.get(r["city"]) == r["slug"]:
            jobs.append(("hero", HERO_WIDTH))
        for kind, width in jobs:
            info = image_info(file_name, width)
            if info is None or not info["mime"].startswith("image/"):
                print(f"no usable file for {r['slug']} ({file_name})")
                break
            ext = os.path.splitext(urllib.parse.urlparse(info["url"]).path)[1].lower() or ".jpg"
            if kind == "hero":
                rel = f"images/cities/{r['city']}{ext}"
                slug = "hero"
            else:
                rel = f"images/attractions/{r['city']}/{r['slug']}{ext}"
                slug = r["slug"]
            target = os.path.join(STATIC, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if not os.path.exists(target):            # re-runs only fetch what is missing
                download(info["url"], target)
                time.sleep(1.5)
            credits.append({"city": r["city"], "slug": slug, "image_path": rel,
                            "credit": info["artist"], "license": info["license"], "source_url": info["page"]})
            print(f"saved {rel}  ({info['license']}, {info['artist'][:40]})")
            time.sleep(0.5)

    with open(os.path.join(DATA, "image_credits.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "slug", "image_path", "credit", "license", "source_url"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(credits)
    print(f"wrote {len(credits)} credits to data/image_credits.csv")


FREE_LICENCE = re.compile(r"^(CC[ -]?(BY|BY-SA|0|Zero)|Public domain|PD|CC0)", re.I)


def wikidata_images():
    """Photos for attractions that still have none: the image property (P18) of the place's own Wikidata
    item. P18 is a Commons file chosen to depict exactly that item, so it is never a guess or a lookalike,
    and only freely licensed (CC BY / BY-SA / CC0 / public domain) files are used. Credits are appended to
    data/image_credits.csv; the app shows a neutral placeholder for anything still missing."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_city_dataset import shrink
    path = os.path.join(DATA, "image_credits.csv")
    with open(path, newline="", encoding="utf-8") as f:
        credits = list(csv.DictReader(f))
    have = {(r["city"], r["slug"]) for r in credits if os.path.exists(os.path.join(STATIC, r["image_path"]))}
    with open(os.path.join(DATA, "attractions.csv"), newline="", encoding="utf-8") as f:
        todo = [r for r in csv.DictReader(f) if (r["city"], r["slug"]) not in have and r.get("wikidata")]
    print(f"{len(todo)} places without a photo have a Wikidata item")
    added = []
    for r in todo:
        try:
            claims = get_json("https://www.wikidata.org/w/api.php", {"action": "wbgetclaims", "format": "json",
                                                                      "entity": r["wikidata"], "property": "P18"})
        except Exception as exc:
            print(f"  {r['city']}/{r['slug']}: Wikidata unavailable ({exc})")
            continue
        values = [c["mainsnak"].get("datavalue", {}).get("value") for c in claims.get("claims", {}).get("P18", [])]
        values = [v for v in values if v]
        if not values:
            print(f"  {r['city']}/{r['slug']}: no image on Wikidata")
            continue
        info = image_info(values[0], CARD_WIDTH)
        if not info or not info["mime"].startswith("image/") or info["mime"] == "image/svg+xml":
            print(f"  {r['city']}/{r['slug']}: no usable raster image")
            continue
        if not FREE_LICENCE.match(info["license"] or ""):
            print(f"  {r['city']}/{r['slug']}: licence '{info['license']}' is not free, skipped")
            continue
        ext = os.path.splitext(urllib.parse.urlparse(info["url"]).path)[1].lower() or ".jpg"
        rel = f"images/attractions/{r['city']}/{r['slug']}{ext}"
        target = os.path.join(STATIC, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        download(info["url"], target)
        shrink(target, 640)
        added.append({"city": r["city"], "slug": r["slug"], "image_path": rel, "credit": info["artist"],
                      "license": info["license"], "source_url": info["page"]})
        print(f"  {rel}  ({info['license']})")
        time.sleep(1.0)
    if added:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["city", "slug", "image_path", "credit", "license", "source_url"],
                                    lineterminator="\n")
            writer.writerows(added)
    print(f"{len(added)} photos added")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--coords", action="store_true")
    parser.add_argument("--images", action="store_true")
    parser.add_argument("--wikidata-images", action="store_true")
    args = parser.parse_args()
    if args.wikidata_images:
        wikidata_images()
        return 0
    rows = read_attractions()
    if args.coords:
        check_coordinates(rows)
    if args.images:
        fetch_images(rows)
    if not (args.coords or args.images):
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
