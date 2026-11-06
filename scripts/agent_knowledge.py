"""
agent_knowledge.py — look up station coordinates in the coordinate tables (data/knowledge/places/).

The coordinates come from these tables:
  places.csv       places table: one row per coordinate value (place_id, lat, lon, source in fixed terms: point_kind,
                   source_type, source_id, source_rev, source_item, label, distance_m [terms and formats in
                   scripts/kb_sources.py], value check)
  stop_place.csv   stop-place table: one row per "station name + line name" printed in the timetable. Columns:
                     place_id      place number (empty = station without coordinates)
                     coord_source  source of the coordinates when assigned (agent_known / release_proxy = a place point
                                   substituted in the published dataset / wikidata = a Wikidata station item /
                                   legacy:wikipedia_ja = a value taken from a Wikipedia station article by an earlier
                                   method [2 stations: 五泉, 高橋])
                     coord_kind    kind of coordinate source (authority / proxy / place_unverified / derived / unknown;
                                   empty, with an empty place_id = station not registered in the coordinate tables)
                     tolerance_km  tolerance (km) allowed when checking the coordinates
                     use           how the point is used (self = the station's own position, adjacent = borrows another
                                   station's point, place = representative point of a place or port)
                     ref_stop      for use=adjacent, the station whose point is borrowed ("station|line"; it must point
                                   to the same place)
                     checked_within_km  range (km) used when the point was checked against non-public station positions
                     note          note for readers (not read by the code)
                     matched_by    record of how the mapping was decided
                   The columns of the published coordinate source table (extras/stop_coord_source.csv) are built by
                   scripts/kb_sources.py from the place's source and use.
  derived.csv      derived values: places placed by calculation (anchor stations and fraction)
Lookup: one stop-place row by station name + line name. No search by name (no silent fallback to old/new kanji forms,
〈region〉 tags or rows without a line name).
A query missing from the stop-place table returns None and is recorded (apply_agent_knowledge.py stops when a station in
the stop table is missing from the stop-place table).
With AGENT_KNOWN_STRICT=1 (set by scripts/kb_places_env.sh for rebuilds), a missing query raises UnmappedQuery, so steps
other than coordinate assignment (station name alignment, splitting, frequency-only sections, route search data) never
silently treat it as "no coordinates".

  lookup(station, line)        -> (lat, lon, tolerance_km, note). None for stations without coordinates or missing ones
  lookup_kind(station, line)   -> coord_kind. None for unregistered or missing stations
  coord_source(station, line)  -> coordinate source (stations with coordinates only; written to coord_source in stops_master)
  entry(station, line)         -> the stop-place row (dict), or None
  is_mapped(station, line)     -> whether it is in the stop-place table (stations without coordinates count too)
  AGENT_KNOWN                  -> {(station, normalized line): (lat, lon, tolerance_km, note)}: old-style dictionary of the
                                  stations with coordinates (for counting tools; not used for lookups)
  unmapped()                   -> list of queries missing from the stop-place table (as recorded)
AGENT_KNOWN_PLACES replaces the table folder (to try changes to the tables first).
"""

import csv
import math
import os
import sys
import unicodedata

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES_DIR = os.environ.get('AGENT_KNOWN_PLACES') or os.path.join(_BASE_DIR, 'data', 'knowledge', 'places')

try:
    from known_kanji_variants import normalize as _normalize_kanji
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from known_kanji_variants import normalize as _normalize_kanji

# coord_kind vocabulary
COORD_KINDS = {'authority', 'proxy', 'place_unverified', 'derived', 'unknown'}
COORD_SOURCES = {'agent_known', 'release_proxy', 'wikidata'}   # + legacy:wikipedia_ja (rules: COORD_SOURCES in scripts/kb_sources.py)
ENTRY_COLUMNS = ('stop_name', 'line_name', 'place_id', 'coord_source', 'coord_kind', 'tolerance_km', 'use', 'ref_stop',
                 'checked_within_km', 'note', 'matched_by')


def _norm_line(line):
    """Normalize variant characters in line_name (old forms -> new forms, as a key). Empty gives None."""
    if line is None or line == '':
        return None
    return _normalize_kanji(line, prefer_new=True)


def _read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def load_tables(tables=None):
    """Return (places table {place_id: row}, stop-place table {(station, line): row}). Stops on inconsistencies (rules in
    scripts/kb_sources.py). Checks: duplicate place numbers, lat/lon, the target of borrowing rows (not the row itself,
    not another borrowing row), unused places, use / point kind / coord_kind, coord_source combinations, tolerances,
    rows without a place, blanks in station and line names, and the derived values (derived.csv)."""
    import kb_sources as ks
    tables = tables or PLACES_DIR
    bad = []
    places = {}
    for p in _read(os.path.join(tables, 'places.csv')):
        if p['place_id'] in places:
            bad.append(f'場所の番号が 2 行: {p["place_id"]}')
        places[p['place_id']] = p
    entries = {}
    for e in _read(os.path.join(tables, 'stop_place.csv')):
        k = (e['stop_name'], e['line_name'])
        if k in entries:
            bad.append(f'同じ問い合わせが 2 行: {k}')
        entries[k] = e
        if not e['stop_name'] or not e['line_name'] or e['stop_name'] != e['stop_name'].strip() or e['line_name'] != e['line_name'].strip():
            bad.append(f'驛名か線名が空・前後に空白: {k}')
        # also stop on invisible characters (control, zero-width) and non-NFC forms (NFD with separate voicing marks,
        # which come in when copying macOS file names)
        for x in (e['stop_name'], e['line_name']):
            if x != unicodedata.normalize('NFC', x) or any(unicodedata.category(ch) in ('Cc', 'Cf') for ch in x):
                bad.append(f'驛名か線名に見えない字か NFC でない形がある: {k!r}')
                break
        pid, kind = e['place_id'], e['coord_kind']
        if pid and pid not in places:
            bad.append(f'場所の表に無い番号: {k} → {pid}')
        if kind and kind not in COORD_KINDS:
            bad.append(f'coord_kind が語彙の外: {k} → {kind}')
        if pid and not kind:
            bad.append(f'場所があるのに coord_kind が空: {k}')
        if not pid:
            bad += [f'{k}: {x}' for x in ks.check_unplaced(e)]
    used = {e['place_id'] for e in entries.values() if e['place_id']}
    for pid in sorted(places):
        if pid not in used:
            bad.append(f'場所 {pid}: どの問い合わせも使わない（使われない場所は外す）')
            continue
        bad += [f'場所 {pid}: {x}' for x in ks.check_place(places[pid])]
        if not places[pid].get('source_type'):
            bad.append(f'場所 {pid}: 出典が無い（source_type が空）')
    for k, e in entries.items():
        if not e['place_id'] or e['place_id'] not in places:
            continue
        bad += [f'{k}: {x}' for x in ks.check_entry(e, places[e['place_id']]) if x != '場所に出典が無い']
        if e.get('use') == 'adjacent' and '|' in e.get('ref_stop', ''):
            rk = tuple(e['ref_stop'].split('|', 1))
            r = entries.get(rk)
            if r is None:
                bad.append(f'{k}: 借りた先 {e["ref_stop"]} が対応の表に無い')
            elif rk == k:
                bad.append(f'{k}: 自分を借りている')
            elif r.get('use') not in ('self', 'place'):
                bad.append(f'{k}: 借りた先 {e["ref_stop"]} も借りる行（借りた先は自分の位置・代表点に使う行だけ）')
            elif r['place_id'] != e['place_id']:
                bad.append(f'{k}: 借りた先 {e["ref_stop"]} と違う点（{e["place_id"]}・{r["place_id"]}）＝借りるなら同じ場所に結ぶ')
    bad += check_derived(tables, places, entries)
    bad += check_readings(tables, places)
    if bad:
        raise ValueError(f'座標KB の表（{tables}）が食い違う: ' + '・'.join(bad[:10]) + ('…' if len(bad) > 10 else ''))
    return places, entries


def check_readings(tables, places):
    """Map-reading points (source_type = topo, gsi) must equal (within 1 m) the latest row of the map readings
    (readings.csv); to move a value, add a reading."""
    import math as _m
    path = os.path.join(tables, 'readings.csv')
    rs = {}
    if os.path.exists(path):
        for r in _read(path):
            rs.setdefault(r['place_id'], []).append(r)
    bad = []
    # Checks on the reading rows themselves: numbers not in the places table are kept as history of removed places, so
    # only their values are checked. Stop on non-numbers, out-of-range values and a kind differing from the place.
    # Latest row = last row in the file
    for pid, lst in rs.items():
        for r in lst:
            try:
                ra, ro = float(r['lat']), float(r['lon'])
                if not (_m.isfinite(ra) and _m.isfinite(ro) and -90 <= ra <= 90 and -180 <= ro <= 180):
                    raise ValueError
            except (TypeError, ValueError):
                bad.append(f'読み取りの記録: {pid} の値が数でないか範囲の外: {r.get("lat")!r},{r.get("lon")!r}')
            if pid in places and r.get('source_type') and r['source_type'] != places[pid].get('source_type') \
                    and places[pid].get('source_type') in ('topo', 'gsi'):
                bad.append(f'読み取りの記録: {pid} の種類（{r["source_type"]}）が場所の出典の種類（{places[pid]["source_type"]}）と違う')
    for pid, p in places.items():
        if p.get('source_type') not in ('topo', 'gsi'):
            continue
        r = (rs.get(pid) or [None])[-1]
        if r is None:
            bad.append(f'場所 {pid}: 地図の読み取りの点なのに読み取りの記録（readings.csv）が無い')
            continue
        try:
            la, lo, ra, ro = float(p['lat']), float(p['lon']), float(r['lat']), float(r['lon'])
        except ValueError:
            bad.append(f'場所 {pid}: 読み取りの記録の値が数でない')
            continue
        d = 6371008.8 * _m.hypot(_m.radians(lo - ro) * _m.cos(_m.radians((la + ra) / 2)), _m.radians(la - ra))
        if not _m.isfinite(d) or d > 1.0:
            bad.append(f'場所 {pid}: 値が読み取りの記録と {d:.0f} m 違う（値を動かすなら読み取りの記録を足す）')
    return bad


def check_derived(tables, places, entries):
    """Rules for derived values (derived.csv): one row per place placed by calculation (point_kind = estimated), method
    equal to the place's source type, anchors are stop-place queries ("station|line") that have a place, fraction is a number."""
    import kb_sources as ks
    path = os.path.join(tables, 'derived.csv')
    if not os.path.exists(path):
        return ['計算の記録 derived.csv が無い']
    bad, seen = [], set()
    for d in _read(path):
        pid = d.get('place_id', '')
        p = places.get(pid)
        if p is None:
            bad.append(f'計算の記録: 場所の表に無い番号 {pid}')
            continue
        if pid in seen:
            bad.append(f'計算の記録: 同じ場所が 2 行 {pid}')
        seen.add(pid)
        if p.get('point_kind') != 'estimated':
            bad.append(f'計算の記録: 計算の点でない場所 {pid}')
        if d.get('method') != p.get('source_type'):
            bad.append(f'計算の記録: {pid} の method（{d.get("method")}）が場所の出典の種類（{p.get("source_type")}）と違う')
        for c in ('anchor_a', 'anchor_b'):
            a = d.get(c, '')
            if not a:
                continue
            r = entries.get(tuple(a.split('|', 1))) if '|' in a else None
            if r is None or not r['place_id']:
                bad.append(f'計算の記録: {pid} の目印 {a} が対応の表に無いか座標が無い')
            elif r['place_id'] == pid:
                # the anchor is the derived point itself
                bad.append(f'計算の記録: {pid} の目印 {a} がこの計算の点そのもの')
        f = d.get('fraction', '')
        if f:
            # the fraction is finite and within 0-1 (between the anchors), and both anchors are required
            try:
                fv = float(f)
                if not (math.isfinite(fv) and 0.0 <= fv <= 1.0):
                    bad.append(f'計算の記録: {pid} の割合が 0〜1 の外か数でない: {f!r}')
            except ValueError:
                bad.append(f'計算の記録: {pid} の割合が数でない: {f!r}')
            if not (d.get('anchor_a') and d.get('anchor_b')):
                bad.append(f'計算の記録: {pid} に割合があるのに目印が 2 つ無い')
    for pid, p in places.items():
        if p.get('point_kind') == 'estimated' and pid not in seen:
            bad.append(f'計算の記録: 計算の点 {pid} の行が無い')
    return bad


_TABLES = None
_UNMAPPED = set()
STRICT = os.environ.get('AGENT_KNOWN_STRICT', '0') == '1'


class UnmappedQuery(LookupError):
    """Query missing from the stop-place table (with AGENT_KNOWN_STRICT=1)."""


def unmapped():
    return sorted(_UNMAPPED)


def _tables():
    """(places table, stop-place table). Read on first use, not on import (so the module imports even when the tables are inconsistent)."""
    global _TABLES
    if _TABLES is None:
        _TABLES = load_tables()
    return _TABLES


def __getattr__(name):
    if name == 'ENTRIES':
        return _tables()[1]
    if name == '_PLACES':
        return _tables()[0]
    if name == 'AGENT_KNOWN':
        return _old_style_dict()
    raise AttributeError(name)


def entry(stop_name, line_name):
    """The stop-place row (dict), or None (recorded)."""
    e = _tables()[1].get((stop_name, line_name or ''))
    if e is None:
        _UNMAPPED.add((stop_name, line_name or ''))
        if STRICT:
            raise UnmappedQuery(f'座標KB の対応の表（{PLACES_DIR}/stop_place.csv）に無い問い合わせ: {stop_name}|{line_name or ""}'
                                '（data/knowledge/places/stop_place.csv に行が要る）')
    return e


def is_mapped(stop_name, line_name):
    """Whether the stop-place table has a row for this station + line (stations without coordinates count too)."""
    return (stop_name, line_name or '') in _tables()[1]


def _value(e):
    if not e or not e['place_id']:
        return None
    p = _tables()[0][e['place_id']]
    return (float(p['lat']), float(p['lon']), float(e['tolerance_km']), e['note'])


def lookup(stop_name, line_name):
    """(lat, lon, tolerance_km, note) for (station, line). None for stations without coordinates or missing from the stop-place table."""
    return _value(entry(stop_name, line_name))


def lookup_kind(stop_name, line_name):
    """The station's coord_kind (None for unregistered stations or those missing from the stop-place table).
    Used to keep calculated values (derived) out of interpolation anchors (infer_coords.py) and to judge how reliable
    station groups are (generate_router_data.py)."""
    e = entry(stop_name, line_name)
    return (e['coord_kind'] or None) if e else None


def coord_source(stop_name, line_name):
    """Coordinate source of a station with coordinates (agent_known / release_proxy / wikidata). None otherwise."""
    e = entry(stop_name, line_name)
    return e['coord_source'] if e and e['place_id'] else None


def _old_style_dict():
    out = {}
    for (name, line), e in sorted(_tables()[1].items()):
        if e['place_id']:
            out[(name, _norm_line(line))] = _value(e)
    return out


if __name__ == '__main__':
    places, entries = _tables()
    print(f'座標KB の表: {PLACES_DIR}')
    print(f'場所 {len(places)}・対応 {len(entries)}（座標を当てる {sum(1 for e in entries.values() if e["place_id"])}）')
