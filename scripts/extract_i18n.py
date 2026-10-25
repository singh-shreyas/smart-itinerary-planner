"""List every interface text that can be translated, and check the language catalogues.

    python scripts/extract_i18n.py            # report missing / unused keys per language
    python scripts/extract_i18n.py --write    # also add missing keys (empty) to i18n/<lang>.json

Where texts come from:
    * templates:   {{ _('...') }} and {{ _("...") }}
    * Python:      _("..."), gettext("..."), ngettext("one", "many", n)  (read with the ast module,
                   so implicit string concatenation and `a if x else b` are handled)
    * JavaScript:  the JS_TEXTS list in app.py (scripts translate only what the page hands them)
    * data labels: config labels, category and region names, weekday and month names,
                   access and timing labels, sort names and the algorithm cards, which the
                   templates translate through a variable ({{ _(c.name) }}).

An empty value in a catalogue means "not translated yet": the English text is shown.
"""

import argparse
import ast
import glob
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config                                                   # noqa: E402
from services import algorithm_info, i18n, models, timeutil     # noqa: E402

TEMPLATE_CALL = re.compile(r"""\b_\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")
CALLS = {"_", "gettext", "ngettext"}


def template_keys():
    keys = set()
    for path in glob.glob(os.path.join(ROOT, "templates", "*.html")):
        text = open(path, encoding="utf-8").read()
        for single, double in TEMPLATE_CALL.findall(text):
            keys.add((single or double).replace("\\'", "'").replace('\\"', '"'))
    return keys


def _strings(node):
    """Every literal text an argument can evaluate to (dict keys are codes, not texts)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _strings(node.body) + _strings(node.orelse)
    if isinstance(node, ast.Subscript):
        return _strings(node.value)
    if isinstance(node, ast.Dict):
        return [s for v in node.values for s in _strings(v)]
    return []


def python_keys():
    keys = set()
    for path in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        if os.sep + "venv" + os.sep in path or os.sep + "tests" + os.sep in path:
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CALLS:
                count = 2 if node.func.id == "ngettext" else 1
                for arg in node.args[:count]:
                    keys.update(_strings(arg))
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "JS_TEXTS" for t in node.targets)):
                keys.update(_strings_list(node.value))
    return keys


def _strings_list(node):
    return [e.value for e in getattr(node, "elts", []) if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def data_keys():
    keys = set()
    keys.update(p[f] for p in config.PACES.values() for f in ("label", "hint"))
    keys.update(m[f] for m in config.MODES.values() for f in ("label", "text"))
    for table in (config.STRATEGIES, config.STRATEGY_SHORT, config.STRATEGY_OBJECTIVES, config.INTEREST_MODES,
                  config.VENUE_STYLES, models.ACCESS_LABELS):
        keys.update(table.values())
    keys.update(timeutil.WEEKDAY_SHORT + timeutil.WEEKDAY_LONG + timeutil.MONTHS + [m[:3] for m in timeutil.MONTHS])
    keys.update(["Central", "North", "South", "East", "West", "lunch", "dinner", "Lunch", "Dinner",
                 "road", "walk", "trek", "ferry", "boat", "ropeway", "helicopter",
                 "first ride", "ride home (extra)", "meals"])
    from routes.helpers import ALTERNATIVE_STATUS, TIMING_LABELS
    from routes.main_routes import SORTS, SOURCE_LABELS
    keys.update(SOURCE_LABELS.values())
    import csv
    with open(os.path.join(ROOT, "data", "estimate_defaults.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            keys.update([row["label"], row["basis"]])
    keys.update(TIMING_LABELS.values())
    keys.update(ALTERNATIVE_STATUS.values())
    keys.update(label for label, _order in SORTS.values())
    for a in algorithm_info.ALGORITHMS:
        keys.update([a["name"], a["summary"], a["role"]])
    db = os.path.join(ROOT, "instance", "itinerary.db")
    if os.path.exists(db):
        con = sqlite3.connect(db)
        keys.update(r[0] for r in con.execute("SELECT DISTINCT name FROM categories"))
        for column in ("grp", "group_name", "category_group"):
            try:
                keys.update(r[0] for r in con.execute(f"SELECT DISTINCT {column} FROM categories") if r[0])
                break
            except sqlite3.OperationalError:
                continue
        keys.update(r[0] for r in con.execute("SELECT DISTINCT region FROM cities") if r[0])
    return keys


def all_keys():
    return sorted(k for k in template_keys() | python_keys() | data_keys() if k and k.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="add missing keys (empty) to each catalogue")
    args = parser.parse_args()
    keys = all_keys()
    print(f"{len(keys)} translatable texts")
    for lang in i18n.LANGUAGES:
        if lang == i18n.DEFAULT:
            continue
        path = os.path.join(i18n.I18N_DIR, f"{lang}.json")
        data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        missing = [k for k in keys if not data.get(k)]
        unused = [k for k in data if not k.startswith("_") and k not in keys]
        bad = [k for k, v in data.items() if v and not k.startswith("_")
               and set(re.findall(r"{(\w+)}", k)) != set(re.findall(r"{(\w+)}", v))]
        print(f"{lang}: {len(keys) - len(missing)} translated, {len(missing)} missing, {len(unused)} unused, "
              f"{len(bad)} with wrong placeholders")
        for k in bad:
            print("   placeholder mismatch:", k)
        if args.write:
            for k in missing:
                data.setdefault(k, "")
            os.makedirs(i18n.I18N_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dict(sorted(data.items())), f, ensure_ascii=False, indent=1)
                f.write("\n")


if __name__ == "__main__":
    main()
