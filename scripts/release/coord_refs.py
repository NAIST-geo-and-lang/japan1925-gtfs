#!/usr/bin/env python3
"""coord_refs.py — helpers for the coordinate gate (step 4e of build_release_all.sh, scripts/release/check_coord_allowlist.py).

  - public_grid(): public points near the published coordinates (data/knowledge/public_release/public_points.csv; the path can be
    given by RELEASE_PUBLIC_POINTS). Each row has lat, lon and a label naming the source (N02-25, Location Reference Information,
    historical place names, Wikipedia, Wikidata, GeoNames, coordinates fetched from the cited sources). Rows with an empty lat
    carry the name of a source that was read.
  - fetched_refs() / cited_distance(): coordinates fetched from the sources cited in the coordinate source table
    (data/knowledge/release_reference_coords.json), and the distance from a published value to them.
  - release_stops(): stops of the published dataset that carry coordinates.
  - OK_LIST: coordinates reviewed by hand (data/knowledge/public_release/verified_geocoder_coincidences.csv).
"""
import csv
import json
import math
import os
from collections import defaultdict
from decimal import Decimal

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBLIC_POINTS = os.path.join(BASE_DIR, 'data', 'knowledge', 'public_release', 'public_points.csv')
OK_LIST = os.environ.get('RELEASE_LEGACY_OK_LIST') or os.path.join(
    BASE_DIR, 'data', 'knowledge', 'public_release', 'verified_geocoder_coincidences.csv')


def dist_m(a, b, c, d):
    r = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, x)))


class Grid:
    """Looks up nearby points in cells of 0.001 degrees."""

    def __init__(self):
        self.g = defaultdict(list)
        self.loaded = []

    def add(self, la, lo, lab):
        try:
            la, lo = float(la), float(lo)
        except (TypeError, ValueError):
            return
        self.g[(round(la, 3), round(lo, 3))].append((la, lo, lab))

    def near(self, la, lo, tol=1.0):
        out = []
        for dx in (-0.001, 0.0, 0.001):
            for dy in (-0.001, 0.0, 0.001):
                for a, b, lab in self.g.get((round(la + dx, 3), round(lo + dy, 3)), []):
                    d = dist_m(la, lo, a, b)
                    if d <= tol:
                        out.append((d, a, b, lab))
        return sorted(out)

    def points(self):
        for v in self.g.values():
            yield from v


def _rows(path):
    try:
        with open(path, encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def _ndec(s):
    s = s.strip().rstrip('0')
    return len(s.split('.')[1]) if '.' in s else 0


def _rnd(x, d, mode):
    return str(Decimal(str(x)).quantize(Decimal(1).scaleb(-d), rounding=mode))


def release_stops(rel):
    """Stops of the published dataset with coordinates: child stops of stops.txt, and the stops of
    extras/single_stop_trips.csv that are not in stops.txt (one per stop_id)."""
    out, have = [], set()
    for s in csv.DictReader(open(os.path.join(rel, 'gtfs', 'stops.txt'), encoding='utf-8')):
        if s.get('location_type') == '1' or not s.get('stop_lat'):
            continue
        out.append(s)
        have.add(s['stop_id'])
    p = os.path.join(rel, 'extras', 'single_stop_trips.csv')
    if os.path.exists(p):
        for s in csv.DictReader(open(p, encoding='utf-8')):
            if s.get('stop_lat') and s['stop_id'] not in have:
                out.append({'stop_id': s['stop_id'], 'stop_name': s['stop_name'], 'stop_lat': s['stop_lat'], 'stop_lon': s['stop_lon']})
                have.add(s['stop_id'])
    return out


def public_grid():
    g = Grid()
    for r in _rows(os.environ.get('RELEASE_PUBLIC_POINTS') or PUBLIC_POINTS):
        if r.get('lat'):
            g.add(r['lat'], r['lon'], r['label'])
        else:
            g.loaded.append(r['label'])
    return g


FETCHED = os.path.join(BASE_DIR, 'data', 'knowledge', 'release_reference_coords.json')


def fetched_refs():
    """Coordinates fetched from the sources cited in the coordinate source table = {reference_id: {...}}."""
    return json.load(open(FETCHED, encoding='utf-8')) if os.path.exists(FETCHED) else {}


def cited_distance(c, la, lo, fetched):
    """Distance (m) from the published value (la, lo) to the coordinates of the source cited by row c of the coordinate
    source table, measured again from the fetched coordinates (the text of the cited revision, P625 of the Wikidata item and
    the coordinates of its articles). None if the source has no fetched coordinates."""
    f = fetched.get((c or {}).get('reference_id', ''))
    pts = [(x[0], x[1]) for x in ((f or {}).get('coords') or []) + ((f or {}).get('coords_articles') or [])]
    if not pts:
        return None
    return min(dist_m(la, lo, a, b) for a, b in pts)
