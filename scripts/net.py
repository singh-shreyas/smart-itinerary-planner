"""Tiny HTTP helper shared by the one-off data scripts (never used by the web app)."""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "SmartItineraryPlanner/1.0 (University of Delhi ADA student project; non-commercial)"


def _ssl_context():
    """Verified TLS context. The python.org macOS installer ships without CA
    certificates, so fall back to the system bundle at /etc/ssl/cert.pem."""
    if ssl.get_default_verify_paths().cafile is None and os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


SSL_CONTEXT = _ssl_context()


def fetch(url, attempts=6):
    """GET with polite retries (public APIs answer 429 when we go too fast)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < attempts - 1:
                wait = int(exc.headers.get("Retry-After") or 0) or 10 * (attempt + 1)
                print(f"  rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            raise


def get_json(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return json.loads(fetch(url))


def download(url, path):
    with open(path, "wb") as out:
        out.write(fetch(url))
