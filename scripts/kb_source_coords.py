#!/usr/bin/env python3
"""kb_source_coords.py — look up the coordinates of the records cited (source_type, source_id) in the places table.

Even when a value equals a publishable point, the cited identifier may point to a different record, so the coordinates of
the cited record itself are looked up and the distance to the value can be measured (used by the coordinate gate, step 4e
of build_release_all.sh: scripts/release/check_coord_allowlist.py, and others).

  cited_points(place)  -> (list of points [(lat, lon, description)], status)
     status = 'ok' (record found), 'no_record' (data present but no record with that identifier), 'no_data' (source data
              not available locally, e.g. before scripts/release/fetch_external_sources.py has been run),
              'no_coords' (kinds without coordinates, i.e. calculated points; map readings are looked up in readings.csv)
  cited_distance_m(place, lat, lon) -> (m to the nearest point, or None, status)

Where each kind is looked up:
  wikipedia_*, wikidata  data/knowledge/release_reference_coords.json (coordinates fetched from the sources; the revision's
                         coordinates coords_rev are used first when present)
  n02          N02_005c (station code) in data/external/n02/N02-25_Station.geojson: vertices, midpoint of the two ends,
               midpoint along the line
  isj, isj_teishajo  大字町丁目コード in data/external/isj/<prefecture>000-19.0b.zip (trailing spaces stripped)
  gazetteer    ID in data/external/historic_gazetteer/historic_gazetteer.tsv (point and point 2)
  geonames     identifier in data/external/geonames/CN.zip
  topo, gsi    latest row for the place in data/knowledge/places/readings.csv (map readings)
"""
import csv
import io
import json
import math
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(BASE, 'data', 'external')
FETCHED = os.path.join(BASE, 'data', 'knowledge', 'release_reference_coords.json')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_sources as ks  # noqa: E402

_CACHE = {}


def dist_m(a, b, c, d):
    x = math.radians(d - b) * math.cos(math.radians((a + c) / 2))
    y = math.radians(c - a)
    return 6371008.8 * math.hypot(x, y)


def _fetched():
    if 'fetched' not in _CACHE:
        _CACHE['fetched'] = json.load(open(FETCHED, encoding='utf-8')) if os.path.exists(FETCHED) else None
    return _CACHE['fetched']


def _n02():
    if 'n02' not in _CACHE:
        p = os.path.join(EXT, 'n02', 'N02-25_Station.geojson')
        by = {}
        if os.path.exists(p):
            for f in json.load(open(p, encoding='utf-8'))['features']:
                cs = f['geometry']['coordinates']
                if f['geometry']['type'] == 'MultiLineString':
                    cs = [c for part in cs for c in part]
                pr = f['properties']
                lab = f"N02 {pr.get('N02_005')}（{pr.get('N02_003')}・{pr.get('N02_004')}）"
                pts = [(c[1], c[0], lab) for c in cs]
                pts.append(((cs[0][1] + cs[-1][1]) / 2, (cs[0][0] + cs[-1][0]) / 2, lab + '（両端の中点）'))
                seg = [dist_m(cs[i][1], cs[i][0], cs[i + 1][1], cs[i + 1][0]) for i in range(len(cs) - 1)]
                total, acc = sum(seg), 0.0
                for i, sg in enumerate(seg):
                    if acc + sg >= total / 2 and sg > 0:
                        fr = (total / 2 - acc) / sg
                        a, b = cs[i], cs[i + 1]
                        pts.append((a[1] + fr * (b[1] - a[1]), a[0] + fr * (b[0] - a[0]), lab + '（線の中点）'))
                        break
                    acc += sg
                by.setdefault(str(pr.get('N02_005c', '')), []).extend(pts)
            _CACHE['n02'] = by
        else:
            _CACHE['n02'] = None
    return _CACHE['n02']


def _isj(code):
    d = os.path.join(EXT, 'isj')
    if not os.path.isdir(d):
        return None
    pref = code[:2]
    key = 'isj' + pref
    if key not in _CACHE:
        by = {}
        p = os.path.join(d, f'{pref}000-19.0b.zip')
        if os.path.exists(p):
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.endswith('.csv'):
                        for r in csv.DictReader(io.StringIO(z.read(n).decode('cp932', errors='replace'))):
                            by.setdefault(r['大字町丁目コード'].strip(), []).append(
                                (float(r['緯度']), float(r['経度']), f"位置参照 {r['市区町村名']}{r['大字町丁目名']}"))
        _CACHE[key] = by
    return _CACHE[key]


def _gazetteer():
    if 'gaz' not in _CACHE:
        p = os.path.join(EXT, 'historic_gazetteer', 'historic_gazetteer.tsv')
        by = None
        if os.path.exists(p):
            by = {}
            with open(p, encoding='utf-8') as f:
                for r in csv.DictReader(f, delimiter='\t'):
                    pts = []
                    for la, lo, lab in ((r.get('緯度'), r.get('経度'), ''), (r.get('緯度2'), r.get('経度2'), '（点 2）')):
                        try:
                            pts.append((float(la), float(lo), f"歴史地名 {r['地名']}（{r.get('属性', '')}）{lab}"))
                        except (TypeError, ValueError):
                            continue
                    if pts:
                        by[r['ID']] = pts
        _CACHE['gaz'] = by
    return _CACHE['gaz']


def _geonames():
    if 'geo' not in _CACHE:
        p = os.path.join(EXT, 'geonames', 'CN.zip')
        by = None
        if os.path.exists(p):
            by = {}
            with zipfile.ZipFile(p) as z:
                with z.open('CN.txt') as f:
                    for line in io.TextIOWrapper(f, encoding='utf-8'):
                        q = line.rstrip('\n').split('\t')
                        if len(q) > 5:
                            by[q[0]] = [(float(q[4]), float(q[5]), f'GeoNames {q[0]} {q[1]}')]
        _CACHE['geo'] = by
    return _CACHE['geo']


def readings(tables=None):
    """Map readings (data/knowledge/places/readings.csv) = {place_id: [rows (oldest first)]}."""
    tables = tables or os.environ.get('AGENT_KNOWN_PLACES') or os.path.join(BASE, 'data', 'knowledge', 'places')
    key = 'readings' + tables
    if key not in _CACHE:
        by = {}
        p = os.path.join(tables, 'readings.csv')
        if os.path.exists(p):
            with open(p, encoding='utf-8-sig', newline='') as f:
                for r in csv.DictReader(f):
                    by.setdefault(r['place_id'], []).append(r)
        _CACHE[key] = by
    return _CACHE[key]


def cited_points(place, tables=None):
    st, sid = place.get('source_type', ''), (place.get('source_id') or '').strip()
    if st in ks.ESTIMATED_TYPES or not st:
        return [], 'no_coords'
    if st in ('topo', 'gsi'):
        rs = readings(tables).get(place.get('place_id', ''))
        if not rs:
            return [], 'no_record'
        r = rs[-1]
        return [(float(r['lat']), float(r['lon']), f"読み取りの記録 {r.get('label', '')}（{r.get('read_on', '')}）")], 'ok'
    if st.startswith('wikipedia_') or st == 'wikidata':
        f = _fetched()
        if f is None:
            return [], 'no_data'
        rid = ks.release_columns(place, {'use': 'self', 'checked_within_km': ''})['reference_id']
        keys = [rid] + ([f'https://www.wikidata.org/wiki/{sid}'] if st == 'wikidata' else [])
        for k in keys:
            v = f.get(k)
            if v:
                cs = (v.get('coords_rev') or []) or (v.get('coords') or [])
                pts = [(c[0], c[1], f"{v.get('title', '')} {k}") for c in cs]
                pts += [(c[0], c[1], c[2]) for c in (v.get('coords_articles') or [])]
                if pts:
                    return pts, 'ok'
        return [], 'no_record'
    table = {'n02': _n02, 'gazetteer': _gazetteer, 'geonames': _geonames}.get(st)
    if st in ('isj', 'isj_teishajo'):
        by = _isj(sid)
    elif table:
        by = table()
    else:
        return [], 'no_coords'
    if by is None:
        return [], 'no_data'
    pts = by.get(sid)
    return (pts, 'ok') if pts else ([], 'no_record')


def cited_distance_m(place, lat, lon, tables=None):
    pts, status = cited_points(place, tables)
    if not pts:
        return None, status
    return min(dist_m(lat, lon, a, b) for a, b, _ in pts), status


if __name__ == '__main__':
    # For every place in the places table, measure the distance from the value to the cited record, and print those
    # that differ from distance_m by more than 1 m (or 20 %)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import agent_knowledge as ak
    places, _ = ak.load_tables()
    from collections import Counter
    st = Counter()
    for pid, p in sorted(places.items()):
        d, s = cited_distance_m(p, float(p['lat']), float(p['lon']))
        st[(p['source_type'] if p['source_type'] in ('n02', 'isj', 'isj_teishajo', 'gazetteer', 'geonames', 'topo', 'gsi') else
            ('wikipedia' if p['source_type'].startswith('wikipedia') else p['source_type']), s)] += 1
        if d is not None and not p.get('source_read'):
            want = float(p['distance_m']) if p.get('distance_m') else 0.0
            if abs(d - want) > max(1.0, 0.2 * want):
                print(f"{pid} {p['names'][:20]} {p['source_type']} {p['source_id']}：記録と {d:.1f} m（表の distance_m＝{p.get('distance_m') or '空'}）")
    for k, v in sorted(st.items()):
        print(' ', k, v)
