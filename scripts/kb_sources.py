#!/usr/bin/env python3
"""kb_sources.py — keep coordinate sources in fixed terms and build the columns of the published coordinate source table by rule.

The source is held once per point in the places table (data/knowledge/places/places.csv); how a station uses the point is
held in the stop-place table (stop_place.csv). Both use fixed terms. The columns of the published coordinate source table
(extras/stop_coord_source.csv) — coord_class, coord_method, reference, reference_id, reference_label, reference_distance_m,
checked_within_km, reference_stop_id — are built by this module by rule (not written by hand).

Source columns of the places table:
  point_kind    what the point is: station (the station's own position), place (representative point of a place or
                facility), estimated (calculated position)
  source_type   kind of source (a term in SOURCE_TYPES below)
  source_id     source identifier (format fixed per kind: ID_FORMS); empty for kinds without an identifier
  source_rev    Wikidata revision number (when citing the revision that holds the value; otherwise empty)
  source_item   what the source item is: station (a station item) or place (a place or facility item); decides the
                method for the Historical Place Names Data
  label         name of the source item (article title, "station (line, company)" in N02, 大字 name, etc.); for map
                readings, a description of the map
  distance_m    distance (m) between the published coordinate and the source's coordinate; empty if the source has none
Use columns of the stop-place table:
  use           self (the point is the station's own position), adjacent (borrows another station's point: a stop in
                front of a station, a station of another company), place (the point is the representative point of a place
                or port: a ship's port of call using a station point)
  ref_stop      for use=adjacent, the station whose point is borrowed ("station|line")
  checked_within_km  range (km, decimals allowed) used when the point was checked against non-public station positions
  coord_kind, coord_source  determined by use and point kind (KIND_RULES; combinations are checked in check_kinds)
source_read in the places table (how the source value was read): empty = the source's coordinate itself;
  corrected_typo = read from the source's coordinate field with a typo corrected; body_coordinate = a coordinate written in
  the article body (not the article's coordinate field); wikidata_display = the cited revision has no station coordinate in
  its text and the article displays the Wikidata coordinate (an empty {{Coord}} or an empty coordinate field in the station
  infobox). Output as a fixed English sentence in reference_note of the published dataset.
"""
import math
import os
import re

SOURCE_TYPES = {
    # term: (reference in the published dataset, template for reference_id [{id} = source_id, {rev} = source_rev])
    'wikipedia_ja': ('Wikipedia (ja)', 'https://ja.wikipedia.org/w/index.php?oldid={id}'),
    'wikipedia_zh': ('Wikipedia (zh)', 'https://zh.wikipedia.org/w/index.php?oldid={id}'),
    'wikipedia_ko': ('Wikipedia (ko)', 'https://ko.wikipedia.org/w/index.php?oldid={id}'),
    'wikipedia_ru': ('Wikipedia (ru)', 'https://ru.wikipedia.org/w/index.php?oldid={id}'),
    'wikipedia_en': ('Wikipedia (en)', 'https://en.wikipedia.org/w/index.php?oldid={id}'),
    'wikidata': ('Wikidata', 'https://www.wikidata.org/wiki/{id}'),
    'n02': ('MLIT National Land Numerical Information N02-25 (railway)', '{id}'),
    'isj': ('MLIT address points (大字・町丁目位置参照情報, 2025)', '{id}'),
    'isj_teishajo': ('MLIT address points (大字・町丁目位置参照情報, 2025); 大字 chosen from 鐵道停車場一覽 (1926, NDL pid 1020981)', '{id}'),
    'gazetteer': ('Historical Place Names Data (NIHU / H-GIS)', '{id}'),
    'geonames': ('GeoNames', 'https://www.geonames.org/{id}'),
    'topo': ('former topographic map (旧版地形図) read by the project on Konjaku Map on the Web', ''),
    'gsi': ('GSI Maps (地理院地図), present-day map, read by the project', 'https://maps.gsi.go.jp/'),
    'computed': ('computed from neighboring stations (1925 mileages)', ''),
    'computed_track': ('1925 timetable mileages along N02-25 railway lines', ''),
    'printed_order': ('stop order printed in the source', '{id}'),
}
WIKIDATA_REV_URL = 'https://www.wikidata.org/w/index.php?oldid={rev}'
ADJACENT_REFERENCE = 'station point in this dataset'
# format of source_id ('' also passes for kinds that allow it to be empty)
ID_FORMS = {
    'wikipedia_ja': r'\d+', 'wikipedia_zh': r'\d+', 'wikipedia_ko': r'\d+', 'wikipedia_ru': r'\d+', 'wikipedia_en': r'\d+',
    'wikidata': r'Q\d+', 'n02': r'\d+', 'isj': r'\d+', 'isj_teishajo': r'\d+', 'gazetteer': r'\d+', 'geonames': r'\d+',
    'topo': r'', 'gsi': r'', 'computed': r'', 'computed_track': r'', 'printed_order': r'FQ\d+',
}
POINT_KINDS = ('station', 'place', 'estimated')
SOURCE_ITEMS = ('station', 'place', '')
USES = ('self', 'adjacent', 'place')
ESTIMATED_TYPES = {'computed', 'computed_track', 'printed_order'}
# source type -> method (point is the station itself, point is a place). For the Historical Place Names Data, source_item decides
METHODS = {
    'wikidata': ('wikidata_station', 'wikidata_item'),
    'n02': ('n02_station', 'place_point'),
    'isj': ('place_point', 'place_point'), 'isj_teishajo': ('place_point', 'place_point'),
    'geonames': ('place_point', 'place_point'), 'gsi': ('place_point', 'place_point'),
    'topo': ('topographic_map_reading', 'topographic_map_reading'),
}
ESTIMATED_METHODS = {'computed': 'computed_position', 'computed_track': 'interpolated_track', 'printed_order': 'interpolated_order'}
PLACE_COLUMNS = ('point_kind', 'source_type', 'source_id', 'source_rev', 'source_item', 'label', 'distance_m', 'source_read')
SOURCE_READS = {'': '',
                'corrected_typo': 'read from the coordinate field of the cited source with an obvious typo corrected',
                'body_coordinate': 'a coordinate given in the body of the cited source, not its main coordinate',
                'wikidata_display': 'the cited revision shows this coordinate from Wikidata; it is not written in the revision text'}
# Outer bounds of lat/lon (extent of the 1925 timetable: inland Japan, external territories, China, Russian territory;
# the table values are lat 22.5-49.6, lon 110.0-145.6)
LAT_RANGE, LON_RANGE = (20.0, 55.0), (105.0, 150.0)
# use and point kind -> coord_kind in the stop-place table (read by interpolation anchors and station group reliability).
# Points spaced evenly by printed stop order are treated like proxy points
KIND_RULES = {('self', 'station'): {'authority'}, ('self', 'place'): {'proxy', 'place_unverified'},
              ('self', 'estimated'): {'derived'}, ('adjacent', None): {'proxy'}, ('place', None): {'proxy'}}
ESTIMATED_PROXY_TYPES = {'printed_order'}
# coord_source (source of assigned coordinates, written to stops_master); allowed combinations are checked in check_kinds
COORD_SOURCES = ('agent_known', 'release_proxy', 'wikidata', 'legacy:wikipedia_ja')
ENTRY_COLUMNS = ('use', 'ref_stop', 'checked_within_km')


def check_place(p):
    """Check the source columns of one places row: list of violations (empty = passes). Places without a source_type are skipped."""
    bad = []
    st = p.get('source_type', '')
    if not st:
        return bad
    if st not in SOURCE_TYPES:
        return [f'source_type が語の外: {st}']
    if p.get('point_kind') not in POINT_KINDS:
        bad.append(f'point_kind が語の外: {p.get("point_kind")}')
    if (st in ESTIMATED_TYPES) != (p.get('point_kind') == 'estimated'):
        bad.append(f'計算の出典（{st}）と point_kind（{p.get("point_kind")}）が合わない')
    if not re.fullmatch(ID_FORMS[st], p.get('source_id', '')):
        bad.append(f'source_id の形が違う（{st}）: {p.get("source_id")!r}')
    if p.get('source_rev') and not (st == 'wikidata' and re.fullmatch(r'\d+', p['source_rev'])):
        bad.append(f'source_rev は Wikidata の版の番号だけ: {p["source_rev"]!r}')
    if p.get('source_item', '') not in SOURCE_ITEMS:
        bad.append(f'source_item が語の外: {p.get("source_item")}')
    if st == 'gazetteer' and not p.get('source_item'):
        bad.append('歴史地名データは source_item（station／place）が要る')
    d = p.get('distance_m', '')
    if d and not re.fullmatch(r'\d+', d):
        bad.append(f'distance_m が整数でない: {d!r}')
    if p.get('source_read', '') not in SOURCE_READS:
        bad.append(f'source_read が語の外: {p.get("source_read")!r}')
    return bad + check_coords(p)


def check_coords(p):
    """Whether the place's lat/lon are numbers within the outer bounds (LAT_RANGE, LON_RANGE)."""
    try:
        la, lo = float(p.get('lat', '')), float(p.get('lon', ''))
    except ValueError:
        return [f'緯度・経度が数でない: {p.get("lat")!r},{p.get("lon")!r}']
    if not (math.isfinite(la) and math.isfinite(lo)):
        return [f'緯度・経度が有限の数でない: {p.get("lat")!r},{p.get("lon")!r}']
    if not (LAT_RANGE[0] <= la <= LAT_RANGE[1] and LON_RANGE[0] <= lo <= LON_RANGE[1]):
        return [f'緯度・経度が時刻表の範囲の外（緯度 {LAT_RANGE}・経度 {LON_RANGE}）: {la},{lo}']
    return []


def expected_kinds(use, point_kind, source_type):
    """Set of coord_kind values allowed for the use and point kind."""
    if use == 'self':
        if point_kind == 'estimated' and source_type in ESTIMATED_PROXY_TYPES:
            return {'proxy'}
        return KIND_RULES.get((use, point_kind), set())
    return KIND_RULES.get((use, None), set())


def check_kinds(e, place):
    """Whether coord_kind and coord_source of one stop-place row fit the rules for its use and point kind (rows with a place only)."""
    if not e.get('place_id') or place is None:
        return []
    bad = []
    want = expected_kinds(e.get('use'), place.get('point_kind'), place.get('source_type'))
    if e.get('coord_kind') not in want:
        bad.append(f'coord_kind（{e.get("coord_kind")}）が使い方 {e.get("use")}・点の種類 {place.get("point_kind")} の決まり（{"・".join(sorted(want))}）に合わない')
    src = e.get('coord_source', '')
    if src not in COORD_SOURCES:
        bad.append(f'coord_source が語の外: {src!r}')
    elif src == 'wikidata' and not (place.get('source_type') == 'wikidata' and e.get('use') == 'self' and place.get('point_kind') == 'station'):
        bad.append('coord_source＝wikidata は Wikidata の驛の項目を自分の位置に使う行だけ')
    elif src == 'legacy:wikipedia_ja' and not (place.get('source_type') == 'wikipedia_ja' and e.get('use') == 'self'):
        bad.append('coord_source＝legacy:wikipedia_ja は Wikipedia (ja) の点を自分の位置に使う行だけ')
    elif src == 'release_proxy' and e.get('coord_kind') != 'proxy':
        bad.append('coord_source＝release_proxy（代わりの点）は coord_kind＝proxy の行だけ')
    return bad


def check_entry(e, place):
    """Whether the use columns of one stop-place row follow the rules."""
    bad = []
    if not e.get('place_id'):
        return bad
    u = e.get('use', '')
    if u not in USES:
        bad.append(f'use が語の外: {u!r}')
    if (u == 'adjacent') != bool(e.get('ref_stop')):
        bad.append('use＝adjacent のときだけ ref_stop（驛名|線名）を書く')
    if e.get('ref_stop') and '|' not in e['ref_stop']:
        bad.append(f'ref_stop は「驛名|線名」: {e["ref_stop"]!r}')
    w = e.get('checked_within_km', '')
    if w and not re.fullmatch(r'\d+(\.\d+)?', w):
        bad.append(f'checked_within_km が数でない: {w!r}')
    if place is not None and not place.get('source_type'):
        bad.append('場所に出典が無い')
    try:
        t = float(e.get('tolerance_km', ''))
        if not (math.isfinite(t) and t > 0):
            bad.append(f'tolerance_km が正の数でない: {e.get("tolerance_km")!r}')
    except ValueError:
        bad.append(f'tolerance_km が数でない: {e.get("tolerance_km")!r}')
    return bad + check_kinds(e, place)


def check_unplaced(e):
    """Rules for rows without a place (stations without coordinates): use, ref_stop, coord_source and checked_within_km
    empty; coord_kind empty or unknown."""
    bad = []
    for c in ('use', 'ref_stop', 'coord_source', 'checked_within_km'):
        if e.get(c):
            bad.append(f'場所の無い行に {c} がある: {e[c]!r}')
    if e.get('coord_kind') not in ('', 'unknown'):
        bad.append(f'場所の無い行の coord_kind は空か unknown: {e.get("coord_kind")!r}')
    return bad


def method_of(place, cls):
    st = place['source_type']
    if st in ESTIMATED_METHODS:
        return ESTIMATED_METHODS[st]
    if st.startswith('wikipedia_'):
        if cls == 'station':
            return 'station_article' if place.get('label') else 'station_point'
        return 'place_point'
    if st == 'gazetteer':
        # Rows using the point as a representative point (use=place: a port of call using a station point) get
        # place_point even when the item is a station (as for Wikipedia and N02).
        # Default ON. Previous behavior = KB_GAZETTEER_METHOD_BY_USE=0
        by_use = os.environ.get('KB_GAZETTEER_METHOD_BY_USE', '1') == '1'
        return ('historical_gazetteer_station' if place.get('source_item') == 'station' and (cls == 'station' or not by_use)
                else 'place_point')
    return METHODS[st][0 if cls == 'station' else 1]


def release_columns(place, entry):
    """One row of the published coordinate source table (columns except stop_id, stop_name, reference_stop_id).
    The station|line for reference_stop_id is returned in 'ref_key'."""
    if entry['use'] == 'adjacent':
        name, line = entry['ref_stop'].split('|', 1)
        return {'coord_class': 'place', 'coord_method': 'adjacent_station', 'reference': ADJACENT_REFERENCE, 'reference_id': '',
                'reference_label': f'{name}（{line}）', 'reference_distance_m': '', 'checked_within_km': entry.get('checked_within_km', ''),
                'reference_note': '', 'ref_key': (name, line)}
    cls = place['point_kind'] if entry['use'] == 'self' else 'place'
    st = place['source_type']
    ref, tmpl = SOURCE_TYPES[st]
    rid = tmpl.format(id=place.get('source_id', ''))
    label = place.get('label', '')
    if st == 'wikidata' and place.get('source_rev'):
        rid = WIKIDATA_REV_URL.format(rev=place['source_rev'])
        label = f'{label} [{place["source_id"]}]' if label else f'[{place["source_id"]}]'
    return {'coord_class': cls, 'coord_method': method_of(place, cls), 'reference': ref, 'reference_id': rid,
            'reference_label': label, 'reference_distance_m': place.get('distance_m', ''),
            'checked_within_km': entry.get('checked_within_km', ''), 'reference_note': SOURCE_READS[place.get('source_read', '')],
            'ref_key': None}


def parse_release(reference, reference_id, reference_label):
    """Read (source_type, source_id, source_rev, label) from reference, reference_id and reference_label of the published
    coordinate source table (used to convert that table into fixed terms). None if unreadable."""
    for st, (ref, tmpl) in SOURCE_TYPES.items():
        if reference != ref:
            continue
        if st == 'wikidata':
            m = re.fullmatch(r'https://www\.wikidata\.org/w/index\.php\?oldid=(\d+)', reference_id)
            if m:
                q = re.search(r'\s*\[(Q\d+)\]$', reference_label)
                if q:
                    return st, q.group(1), m.group(1), reference_label[:q.start()].strip()
                q = re.fullmatch(r'(Q\d+) \((.*)\)', reference_label)       # the "Q... (title)" form
                return (st, q.group(1), m.group(1), q.group(2)) if q else None
            m = re.fullmatch(r'https://www\.wikidata\.org/wiki/(Q\d+)', reference_id)
            return (st, m.group(1), '', reference_label) if m else None
        if '{id}' in tmpl:
            pre, post = tmpl.split('{id}')
            if not (reference_id.startswith(pre) and reference_id.endswith(post)):
                return None
            sid = reference_id[len(pre):len(reference_id) - len(post)] if post else reference_id[len(pre):]
            return st, sid, '', reference_label
        if reference_id not in ('', tmpl):
            return None
        return st, '', '', reference_label
    return None
