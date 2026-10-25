"""Interface languages: English, Hindi, Gujarati and Tamil.

How it works (gettext style, no extra library):
    * The English text IS the key. Templates write {{ _('Plan a trip') }}, Python writes
      _("Choose a destination city."), JavaScript writes I18N.t("Load more").
    * i18n/<lang>.json maps each English text to its translation. A text that is
      missing there simply stays in English (the fallback), so nothing ever breaks.
    * Placeholders use {name}: _("Plan between {low} and {high} days", low=1, high=30).
      The translation keeps the same {name} markers, in whatever word order the
      language needs.
    * The chosen language lives in a "lang" cookie (set by /lang/<code>), so it
      survives page changes, form submissions and new visits. Without a cookie the
      site is in English.

Only interface text is translated. Names of cities, monuments and temples, and
descriptions from Wikipedia, are shown as they are: they are official names or
sourced content, and an invented translation would be wrong.
"""

import contextvars
import json
import os

LANGUAGES = {"en": "English", "hi": "हिन्दी", "gu": "ગુજરાતી", "ta": "தமிழ்"}
DEFAULT = "en"
COOKIE = "lang"
I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")

_current = contextvars.ContextVar("lang", default=DEFAULT)
_catalogs = {}


def catalog(lang):
    """The translations of one language (loaded once; English has none: it is the source)."""
    if lang not in _catalogs:
        path = os.path.join(I18N_DIR, f"{lang}.json")
        data = {}
        if lang != DEFAULT and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = {k: v for k, v in json.load(f).items() if not k.startswith("_") and v}
        _catalogs[lang] = data
    return _catalogs[lang]


def clean(lang):
    return lang if lang in LANGUAGES else DEFAULT


def set_language(lang):
    return _current.set(clean(lang))


def current():
    return _current.get()


def gettext(text, **values):
    """Translate an English interface text into the current language, then fill {placeholders}."""
    translated = catalog(current()).get(text, text) if text else text
    if values:
        try:
            return translated.format(**values)
        except (KeyError, IndexError, ValueError):         # a broken translation never breaks the page
            return text.format(**values)
    return translated


def ngettext(singular, plural, n, **values):
    """One text for n == 1 and another for every other n (each translated on its own)."""
    return gettext(singular if n == 1 else plural, n=n, **values)


_ = gettext


def js_catalog(keys):
    """The translations a page's scripts need ({english: translated})."""
    data = catalog(current())
    return {k: data[k] for k in keys if k in data}
