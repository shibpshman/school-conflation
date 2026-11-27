"""Pinned downloads. Every file is checked against sources.lock.json before it is used.

NCES and the Census county file are national, one file each. OSM comes per state from Geofabrik's
dated extracts; the January 1 extract of each year is kept on Geofabrik's server for good, which is
why it is the default. A state not yet in the lock file is checked against Geofabrik's published
.md5 on first download, and its sha256 is then added to the lock.
"""

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LOCK = ROOT / "sources.lock.json"

NCES_URL = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_2425.zip"
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip"
OSM_DATE = "260101"
GEOFABRIK_URL = "https://download.geofabrik.de/north-america/us/{slug}/{slug}-{date}.osm.pbf"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "school-conflation"})
    with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
        while block := r.read(1 << 20):
            f.write(block)
    tmp.rename(dest)


def get(url, md5_url=None):
    """Download url into data/raw (once) and verify it. Returns the local path."""
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / url.rsplit("/", 1)[1]
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    if not dest.exists():
        _fetch(url, dest)
    digest = _sha256(dest)
    if dest.name in lock:
        if digest != lock[dest.name]:
            raise SystemExit(f"{dest.name}: sha256 {digest} does not match the lock file. "
                             f"Delete it and download again.")
        return dest
    if md5_url is None:
        raise SystemExit(f"{dest.name} is not in {LOCK.name} and has no published checksum.")
    with urllib.request.urlopen(md5_url) as r:
        published = r.read().decode().split()[0]
    if _md5(dest) != published:
        dest.unlink()
        raise SystemExit(f"{dest.name}: md5 does not match {md5_url}; deleted, run again.")
    lock[dest.name] = digest
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    print(f"{dest.name}: md5 matches Geofabrik; sha256 added to {LOCK.name}")
    return dest


def geofabrik_url(state_name, date=OSM_DATE):
    slug = state_name.lower().replace(" ", "-")
    return GEOFABRIK_URL.format(slug=slug, date=date)

