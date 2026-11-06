#!/usr/bin/env python3
"""check_coord_allowlist.py — Check that every coordinate of the published dataset is explained by an openly licensed
source (the coordinate gate, step 4e of scripts/release/build_release_all.sh).

A denylist check (looking for the same values as known restricted sources) misses copies it does not list (rounded
copies, older values, values used as interpolation anchors). This check works the other way: each published value
must be explained by a point from an openly licensed source (an allowlist). A value that cannot be explained is not
proven restricted, but there is also no basis for saying it can be published.

Explained (allowed):
  A. Within 1 m of an open point (coord_refs.public_grid: N02, location reference information, historical
     place-name data, Wikipedia, Wikidata, GeoNames, the source table), or a value with 3-5 decimals that equals
     such a point rounded or truncated to the same digits (points within 15 m).
  B. Within 1 m of the source coordinate cited in the source table (extras/stop_coord_source.csv). The table's
     reference_distance_m is not trusted; the distance between the coordinate fetched from the source
     (data/knowledge/release_reference_coords.json) and the stops.txt value is measured again (the source table is
     written by the same build, so a mismatch with stops.txt would go unnoticed).
  C. A reading of an old topographic map (coord_method = topographic_map_reading) within 1 m of the map readings
     (data/knowledge/places/readings.csv).
  D. In a verified list (data/knowledge/public_release/verified_geocoder_coincidences.csv and
     verified_coordinates.csv = RELEASE_ALLOWLIST_EXCEPTIONS; same station name, within 1 m).
  E. A value interpolated for the published dataset (coord_method = interpolated_*) where every non-interpolated
     station of the line is explained and the value can be recomputed (mileage interpolation: within 15 m using
     the anchors' published values and the printed mileages; stations placed by order: within 1 m using the anchors
     and fractions in derived values (data/knowledge/places/derived.csv); along-track N02 computation: explained
     by A).
  F. A derived value of the coordinate tables (computed_position) whose anchor stations are all explained and whose
     value, recomputed from the anchors' published values and the fractions, agrees within 15 m (derived values
     that cannot be recomputed get ★).
  Previous behavior for checking C and E values (allowed by the method label alone) = RELEASE_ALLOWLIST_VALUE_CE=0.
Even when explained, a value gets ★ if its distance to the source record cited by the places table (N02 station
code, ōaza code of location reference information, historical place-name ID, GeoNames ID, coordinate in the cited
Wikipedia revision = scripts/kb_source_coords.py) does not match distance_m in the table (a mistaken source ID).
With RELEASE_ALLOWLIST_CITED_STRICT (on by default), also:
  - Check more sources: Wikidata (fetched coordinates) and every Wikipedia revision with a fetched coordinate.
    Places with a source_read are checked too (wikidata_display: within 1 m of the article's displayed coordinate;
    body_coordinate: the coordinate in the revision text; corrected_typo: within 1 m of an entry with the same
    station name in the verified coordinates list).
  - A borrowed row (use = adjacent) gets ★ unless within 1 m of the published value of the station it borrows from
    (reference_stop_id in the source table).
  - ★ if the cited ID is not in the source data, or the source data is not available locally (data/external
    missing, i.e. not fetched).
  - ★ if the source table's reference/reference_id differs from the place's source in the coordinate tables.
  - Parent stations (location_type = 1) are checked too: the child cited in the source table must be a child of
    this parent with the same value, and that child must be explained.
  Previous behavior (fewer sources; pass when nothing can be checked) = RELEASE_ALLOWLIST_CITED_STRICT=0.
Not explained (★): anything else, with one reason (differs from the source coordinate by X m / differs from the
  source's current coordinate (the fetched coordinate) / source has no coordinate / source coordinate not fetched /
  no provenance record / derived value with unreadable anchors / an anchor station is not explained, etc.).

Usage: python3 scripts/release/check_coord_allowlist.py <published dataset folder> <4_integrated of the work folder> <output CSV> [--gate]
The last line gives the number of ★. Exit code 0 (report only); with --gate, 1 if there is any ★
(build_release_all.sh uses --gate by default).
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from decimal import ROUND_DOWN, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coord_refs  # noqa: E402
from coord_refs import OK_LIST, _ndec, _rnd, release_stops  # noqa: E402

# Read the coordinate tables one row per query (scripts/kb_tables.py).
#   The table folder can be overridden with AGENT_KNOWN_PLACES, as in agent_knowledge
sys.path.insert(0, os.path.join(coord_refs.BASE_DIR, 'scripts'))
import kb_tables  # noqa: E402
ID_MAP = os.path.join(os.environ.get('RELEASE_ID_REGISTRY_DIR') or os.path.join(coord_refs.BASE_DIR, 'data', 'knowledge', 'public_release', 'id_registry'),
                      'internal_id_map.csv')   # for trials, another location via the same variable as stable_ids.py
FETCHED = os.path.join(coord_refs.BASE_DIR, 'data', 'knowledge', 'release_reference_coords.json')
# values checked by hand against openly licensed sources (those a machine cannot check, e.g. corrected typos in an
# article's coordinate; each row gives the source and the reason)
EXCEPTIONS = os.environ.get('RELEASE_ALLOWLIST_EXCEPTIONS') or os.path.join(
    coord_refs.BASE_DIR, 'data', 'knowledge', 'public_release', 'verified_coordinates.csv')
TOL_M = 1.0
# tolerance for recomputing F = 15 m (relative tolerance F_TOL_REL is 0: fractions in derived.csv have 6 decimals)
F_TOL_M, F_TOL_REL = 15.0, 0.0
# Check C and E by value (with only the coord_method label in extras/stop_coord_source.csv, a changed stops.txt
#   value would still pass):
#     C = within 1 m of the latest row for the place in the map readings (data/knowledge/places/readings.csv)
#     E (interpolated_mileage) = within E_TOL_M of the value re-interpolated by printed mileage between anchors
#       (published values) along the trips' station sequences in the work folder (anchors = stations whose
#       coord_source in the work folder's stops_master is agent_known, release_proxy or wikidata, the same set as
#       infer_coords with INFER_COORDS_RELIABLE_ONLY and INFER_COORDS_EXTRA_ANCHORS=release_proxy)
#     E (interpolated_order) = within 1 m of the value recomputed from the anchors and fractions in derived.csv
#     E (interpolated_track) = ★ unless explained by A (open points = saved along-track N02 computations)
#   ★ on mismatch. On by default. Previous behavior (label alone) = RELEASE_ALLOWLIST_VALUE_CE=0.
VALUE_CE = os.environ.get('RELEASE_ALLOWLIST_VALUE_CE', '1') == '1'
E_TOL_M = 15.0
# Check values against cited source records more widely (see main below). On by default.
#   Previous behavior = RELEASE_ALLOWLIST_CITED_STRICT=0.
CITED_STRICT = os.environ.get('RELEASE_ALLOWLIST_CITED_STRICT', '1') == '1'
CITED_TYPES = ('n02', 'isj', 'isj_teishajo', 'gazetteer', 'geonames', 'wikidata')


def recompute_inferred(work, rel_coord):
    """Independently recompute mileage interpolation (infer_coords.py); return {(stop_name, line_name): mean (lat, lon)}.
    rel_coord: (stop_name, line_name) -> published stops.txt value (used for anchors, to check that the published
    values reproduce the result). Per trip, interpolate between anchors by summed segment distances from the
    distance table (equal spacing by stop order if not found); extrapolate beyond the ends from the two nearest
    anchors; trips with a single anchor give provisional values (0.005 degree steps) used only for stations with
    no other value (INFER_COORDS_LONE_ANCHOR_LAST); average over trips."""
    sys.path.insert(0, os.path.join(coord_refs.BASE_DIR, 'scripts'))
    import known_kanji_variants as kv
    sm = {(r['stop_name'], r['line_name']): r for r in csv.DictReader(open(os.path.join(work, 'stops_master.csv'), encoding='utf-8-sig'))}
    anch_src = {'agent_known', 'release_proxy', 'wikidata'}
    seg = {}
    for r in csv.DictReader(open(os.path.join(DIST_DIR, 'lookup_segments_summary.csv'), encoding='utf-8')):
        try:
            seg[(r['line_name'], frozenset([r['stop_a'], r['stop_b']]))] = (float(r['min_km']) + float(r['max_km'])) / 2
        except ValueError:
            pass
    nseg = {}
    for (ln, pr), v in seg.items():
        nseg.setdefault((kv.normalize(ln, prefer_new=True), frozenset(kv.normalize(x, prefer_new=True) for x in pr)), v)

    def segkm(k1, k2):
        a, b = k1[0].split('〈')[0], k2[0].split('〈')[0]
        for ln in (k1[1], k2[1]):
            v = seg.get((ln, frozenset([a, b])))
            if v is not None:
                return v
        for ln in (k1[1], k2[1]):
            v = nseg.get((kv.normalize(ln, prefer_new=True),
                          frozenset([kv.normalize(a, prefer_new=True), kv.normalize(b, prefer_new=True)])))
            if v is not None:
                return v
        return None

    def anchor_ll(k):
        if k in rel_coord:
            return rel_coord[k]
        s = sm.get(k, {})
        return (float(s['stop_lat']), float(s['stop_lon'])) if s.get('stop_lat') else None

    trips = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(work, 'integrated_stop_times.csv'), encoding='utf-8-sig')):
        trips[r['gtfs_trip_key']].append((int(r['stop_sequence']), (r['stop_name'], r['line_name'])))
    target = {k for k, s in sm.items() if s['coord_source'] == 'inferred'}
    acc, weak = defaultdict(list), defaultdict(list)
    for _, lst in sorted(trips.items()):
        keys = [k for _, k in sorted(lst)]
        if not any(k in target for k in keys):
            continue
        pos = [0.0] + [None] * (len(keys) - 1)
        for i in range(1, len(keys)):
            v = segkm(keys[i - 1], keys[i])
            pos[i] = None if (v is None or pos[i - 1] is None) else pos[i - 1] + v
        anc = []
        for i, k in enumerate(keys):
            if k in sm and sm[k]['coord_source'] in anch_src:
                ll = anchor_ll(k)
                if ll:
                    anc.append((i, ll[0], ll[1]))
        if not anc:
            continue
        acc_t = weak if len(anc) == 1 else acc

        def put(j, la, lo):
            if keys[j] in target and 21 <= la <= 54 and 110 <= lo <= 146:
                acc_t[keys[j]].append((la, lo))

        def frac(ai, bi, j):
            if pos[ai] is not None and pos[bi] is not None and pos[j] is not None and pos[bi] - pos[ai] != 0:
                return (pos[j] - pos[ai]) / (pos[bi] - pos[ai])
            return (j - ai) / (bi - ai)
        for (ai, al, ao), (bi, bl, bo) in zip(anc, anc[1:]):
            for j in range(ai + 1, bi):
                f = frac(ai, bi, j)
                put(j, al + (bl - al) * f, ao + (bo - ao) * f)
        for end in ('head', 'tail'):
            if end == 'head' and anc[0][0] > 0:
                (ai, al, ao), js, other = anc[0], range(anc[0][0]), (anc[1] if len(anc) > 1 else None)
            elif end == 'tail' and anc[-1][0] < len(keys) - 1:
                (ai, al, ao), js, other = anc[-1], range(anc[-1][0] + 1, len(keys)), (anc[-2] if len(anc) > 1 else None)
            else:
                continue
            for j in js:
                if other:
                    bi, bl, bo = other
                    t = frac(ai, bi, j)
                    put(j, al + (bl - al) * t, ao + (bo - ao) * t)
                else:
                    s = j - ai
                    put(j, al + 0.005 * s, ao + 0.005 * s)
    for k, v in weak.items():
        if k not in acc:
            acc[k] = v
    return {k: (sum(x[0] for x in v) / len(v), sum(x[1] for x in v) / len(v)) for k, v in acc.items() if v}
DIST_DIR = os.path.join(coord_refs.BASE_DIR, 'data', 'distance')
FIELDS =['stop_id', 'stop_name', 'line_name', 'stop_lat', 'stop_lon', '内部の出どころ', 'coord_class', 'coord_method', 'reference',
          'reference_id', 'reference_distance_m', '判定', '詳細', '座標KB の note']


def same_name(a, b):
    """Whether two station names are the same, ignoring 〈region〉 tags and old/new kanji (the lists use the
    coordinate-table key name; the published name may carry a tag)."""
    import re as _re
    sys.path.insert(0, os.path.join(coord_refs.BASE_DIR, 'scripts'))
    import agent_knowledge as ak
    f = lambda n: ak._normalize_kanji(_re.sub(r'〈[^〉]*〉', '', n or '').strip(), prefer_new=True)
    return f(a) == f(b)


def _nk(n):
    """Comparison form of a station name (〈region〉 tag removed, old/new kanji unified)."""
    import re as _re
    sys.path.insert(0, os.path.join(coord_refs.BASE_DIR, 'scripts'))
    import agent_knowledge as ak
    return ak._normalize_kanji(_re.sub(r'〈[^〉]*〉', '', n or '').strip(), prefer_new=True)


def public_match(pub, s_lat, s_lon):
    la, lo = float(s_lat), float(s_lon)
    near = pub.near(la, lo, TOL_M)
    if near:
        return near[0][3]
    d = max(_ndec(s_lat), _ndec(s_lon))
    if 3 <= d <= 5:
        want = (_rnd(s_lat, d, ROUND_HALF_UP), _rnd(s_lon, d, ROUND_HALF_UP))
        for p in pub.near(la, lo, 15.0):
            if any((_rnd(p[1], d, md), _rnd(p[2], d, md)) == want for md in (ROUND_HALF_UP, ROUND_DOWN)):
                return f'{p[3]}（小数 {d} 桁に丸めた値）'
    return None


def main():
    args = [a for a in sys.argv[1:] if a != '--gate']
    gate = '--gate' in sys.argv[1:]
    if len(args) != 3:
        sys.exit(__doc__)
    rel, work, out = args
    pub = coord_refs.public_grid()
    src = {r['stop_id']: r for r in csv.DictReader(open(os.path.join(rel, 'extras', 'stop_coord_source.csv'), encoding='utf-8'))}
    ok = [r for r in csv.DictReader(open(OK_LIST, encoding='utf-8-sig')) if r.get('lat')] if os.path.exists(OK_LIST) else []
    if os.path.exists(EXCEPTIONS):
        ok += [r for r in csv.DictReader(open(EXCEPTIONS, encoding='utf-8-sig')) if r.get('lat')]
    sm = {r['stop_id']: r for r in csv.DictReader(open(os.path.join(work, 'stops_master.csv'), encoding='utf-8-sig'))}
    pub2int = {}
    if os.path.exists(ID_MAP):
        pub2int = {r['public_id']: r['internal_id'] for r in csv.DictReader(open(ID_MAP, encoding='utf-8-sig')) if r['kind'] == 'stop'}
    fetched = {}
    if os.path.exists(FETCHED):
        fetched = json.load(open(FETCHED, encoding='utf-8'))
    import agent_knowledge as _akm
    import kb_source_coords as _sc
    kb_places, kb_entries = _akm.load_tables()
    derived_by = {}
    _dp = os.path.join(_akm.PLACES_DIR, 'derived.csv')
    if os.path.exists(_dp):
        derived_by = {d['place_id']: d for d in csv.DictReader(open(_dp, encoding='utf-8-sig'))}
    readings_by = _sc.readings(_akm.PLACES_DIR)

    def place_of(name, line):
        e = kb_entries.get((name, line))
        return (e, kb_places.get(e['place_id'])) if e and e['place_id'] else (e, None)

    kb_val = defaultdict(list)
    for k in kb_tables.rows():
        try:
            kb_val[(round(float(k['lat']), 6), round(float(k['lon']), 6))].append(k)
        except ValueError:
            continue

    if VALUE_CE:
        # inputs for checking C and E by value (see VALUE_CE above)
        rel_coord = {}
        for s in release_stops(rel):
            ir = sm.get(pub2int.get(s['stop_id'], s['stop_id']))
            if ir:
                rel_coord[(ir['stop_name'], ir['line_name'])] = (float(s['stop_lat']), float(s['stop_lon']))
        inferred = recompute_inferred(work, rel_coord)


    rows, status = [], {}
    rel_ll = {s['stop_id']: (float(s['stop_lat']), float(s['stop_lon'])) for s in release_stops(rel)}   # for checking borrowed rows
    no_source_data = Counter()           # source type with no local data -> number of stations
    f_head = {}                          # stop_id -> (derived row, station name), for recomputing F
    by_line = defaultdict(list)          # line_name -> [stop_id]
    by_name_line = {}                    # (stop_name, line_name) -> stop_id
    by_key = {}                          # (internal station name, line name) -> stop_id (looked up by anchor keys of derived values)
    for s in release_stops(rel):
        sid = s['stop_id']
        ir = sm.get(pub2int.get(sid, sid), {})
        line = ir.get('line_name', '')
        c = src.get(sid, {})
        method = c.get('coord_method', '')
        rd = c.get('reference_distance_m', '')
        kbn = ''
        ks = [k for k in kb_val.get((round(float(s['stop_lat']), 6), round(float(s['stop_lon']), 6)), []) if k['line_name'] in (line, '')]
        if ks:
            kbn = ks[0]['note']
        row = {'stop_id': sid, 'stop_name': s['stop_name'], 'line_name': line, 'stop_lat': s['stop_lat'], 'stop_lon': s['stop_lon'],
               '内部の出どころ': ir.get('coord_source', ''), 'coord_class': c.get('coord_class', ''), 'coord_method': method,
               'reference': c.get('reference', ''), 'reference_id': c.get('reference_id', ''), 'reference_distance_m': rd,
               '判定': '', '詳細': '', '座標KB の note': kbn[:160]}
        hit = public_match(pub, s['stop_lat'], s['stop_lon'])
        la, lo = float(s['stop_lat']), float(s['stop_lon'])
        ke_, kp_ = place_of(ir.get('stop_name', ''), line)
        # B does not trust reference_distance_m; it re-measures the distance from the fetched source coordinate to stops.txt
        d_cited = coord_refs.cited_distance(c, la, lo, fetched)
        if hit:
            row['判定'], row['詳細'] = '説明できる：A 公開できる点と同じ値', hit
        elif d_cited is not None and d_cited <= TOL_M:
            row['判定'], row['詳細'] = ('説明できる：B 出典の表の出典と 1 m 以内（取り寄せた出典の座標で測り直した）',
                                      f"{c.get('reference', '')} {c.get('reference_id', '')} と {d_cited:.2f} m")
        elif method == 'topographic_map_reading' and not VALUE_CE:
            row['判定'], row['詳細'] = '説明できる：C 旧版地形図の読み取り', c.get('reference_label', '')
        elif method == 'topographic_map_reading' or (kp_ and kp_.get('source_type') == 'gsi' and ke_ and ke_.get('use') != 'adjacent'):
            rd_ = (readings_by.get(kp_['place_id']) or [None])[-1] if kp_ else None
            dd = coord_refs.dist_m(la, lo, float(rd_['lat']), float(rd_['lon'])) if rd_ else None
            if dd is not None and dd <= TOL_M:
                row['判定'], row['詳細'] = ('説明できる：C 地図の読み取り（読み取りの記録と 1 m 以内）',
                                          f"{c.get('reference_label', '')}（{rd_.get('read_by', '')}・{rd_.get('read_on', '')}・{dd:.2f} m）")
            else:
                row['判定'], row['詳細'] = ('★説明できない：地図の読み取りの印だが、読み取りの記録の値と合わない',
                                          f'{dd:.0f} m' if dd is not None else '読み取りの記録（readings.csv）が無い')
        elif any(same_name(o['stop_name'], s['stop_name']) and coord_refs.dist_m(la, lo, float(o['lat']), float(o['lon'])) <= TOL_M for o in ok):
            row['判定'], row['詳細'] = '説明できる：D 確かめ済みの一覧', ''
        elif method.startswith('interpolated') and not VALUE_CE:
            row['判定'] = '保留：E 公開版で内挿'
        elif method.startswith('interpolated'):
            # check the value here; whether the line's anchors are explained is checked below (as in the old E)
            if method == 'interpolated_mileage':
                ik = (ir.get('stop_name', ''), line)
                rc = inferred.get(ik)
                if rc is None:
                    row['判定'], row['詳細'] = '★説明できない：哩程の内挿の印だが、目印から計算し直せない', ''
                else:
                    d = coord_refs.dist_m(la, lo, rc[0], rc[1])
                    if d <= E_TOL_M:
                        row['判定'], row['詳細'] = '保留：E 公開版で内挿', f'目印の公開版の値と哩程で計算し直して {d:.1f} m'
                    else:
                        row['判定'], row['詳細'] = ('★説明できない：哩程の内挿の印だが、目印の公開版の値と哩程から計算し直した値と合わない',
                                                  f'{d:.0f} m（計算し直した値 {rc[0]:.6f},{rc[1]:.6f}）')
            elif method == 'interpolated_order':
                dr = derived_by.get(kp_['place_id']) if kp_ else None
                got = None
                if dr and dr.get('fraction') and dr.get('anchor_a') and dr.get('anchor_b'):
                    pa = place_of(*dr['anchor_a'].split('|', 1))[1]
                    pb = place_of(*dr['anchor_b'].split('|', 1))[1]
                    if pa and pb:
                        f_ = float(dr['fraction'])
                        got = (float(pa['lat']) + (float(pb['lat']) - float(pa['lat'])) * f_,
                               float(pa['lon']) + (float(pb['lon']) - float(pa['lon'])) * f_)
                d = coord_refs.dist_m(la, lo, got[0], got[1]) if got else None
                if d is not None and d <= TOL_M:
                    row['判定'], row['詳細'] = ('保留：E 公開版で内挿',
                                              f"計算の記録の目印 {dr['anchor_a']}・{dr['anchor_b']} の {float(dr['fraction']):.4f} で計算し直して {d:.2f} m")
                else:
                    row['判定'], row['詳細'] = ('★説明できない：並びで置いた印だが、計算の記録の目印から計算し直した値と合わない',
                                              f'{d:.0f} m' if d is not None else '計算の記録（derived.csv）に目印と割合が無い')
            else:
                # an along-track computation (a point placed on the N02 track by mileage ratio) is explained only if it
                # equals an open point of A (saved along-track N02 computations); comparing with the coordinate tables
                # would be circular
                row['判定'], row['詳細'] = ('★説明できない：線路沿いの計算の印だが、公開できる点（N02 の線路沿いの計算の控え）と同じ値でない', '')
        elif method == 'computed_position' or any(k['coord_kind'] == 'derived' for k in ks):
            row['判定'] = '保留：F 座標KB の derived'
            # anchors and fraction come from derived values (derived.csv)
            dr = derived_by.get(kp_['place_id']) if kp_ else None
            row['詳細'] = '・'.join(x.split('|', 1)[0] for x in ((dr or {}).get('anchor_a', ''), (dr or {}).get('anchor_b', '')) if x)
            f_head[sid] = (dr, s['stop_name'])
        elif c.get('reference_id', '') in fetched:
            f = fetched[c['reference_id']]
            said = f"（出典の表は {rd} m と書く）" if rd != '' else ''
            if d_cited is None:
                row['判定'], row['詳細'] = '★説明できない：出典に座標が無い', f"{c.get('reference', '')} {c['reference_id']}（{f.get('title', '')}）{said}"
            else:
                row['判定'], row['詳細'] = ('★説明できない：出典のいまの座標と違う',
                                          f"{c.get('reference', '')} {c['reference_id']}（{f.get('title', '')}）と {d_cited:.0f} m{said}")
        elif rd != '':
            # the source coordinate was not fetched, so the table's distance (rd) cannot be re-measured and is not trusted
            row['判定'], row['詳細'] = ('★説明できない：出典の座標を取り寄せていない（出典の表の距離は測り直せない）',
                                      f"{c.get('reference', '')} {c.get('reference_id', '')}（出典の表は {rd} m と書く）")
        elif c.get('reference', '') not in ('', 'not recorded'):
            row['判定'], row['詳細'] = '★説明できない：出典の座標を取り寄せていない', f"{c.get('reference', '')} {c.get('reference_id', '')}"
        else:
            row['判定'], row['詳細'] = '★説明できない：出どころの記録なし', ''
        rows.append(row)
        status[sid] = row['判定']
        if line:
            by_line[line].append(sid)
            by_name_line[(s['stop_name'], line)] = sid
            by_key[(ir.get('stop_name', ''), line)] = sid
        # distance to the cited source record: even an explained value gets ★ if it disagrees with the places table's source
        # With CITED_STRICT, more sources are checked and nothing passes silently when it cannot be checked:
        #   - Wikidata too (fetched coordinates, release_reference_coords.json)
        #   - every Wikipedia revision with a fetched coordinate, not only those with a saved body coordinate
        #   - places with a source_read: wikidata_display within 1 m of the article's displayed coordinate (fetched
        #     coords); body_coordinate = the revision's body coordinate; corrected_typo within 1 m of an entry with the
        #     same station name in the verified coordinates list (D)
        #   - borrowed rows (use = adjacent) within 1 m of the published value of the station borrowed from (reference_stop_id)
        #   - ★ also when the cited ID is not in the source data (no_record) or the data is missing (no_data, no data/external)
        #   Previous behavior (fewer sources; pass when nothing can be checked) = RELEASE_ALLOWLIST_CITED_STRICT=0
        if CITED_STRICT and kp_ and ke_ and c:
            # the source table's reference/reference_id must equal the place's source in the coordinate tables (the
            # source table is built from them by rule: release_columns in scripts/kb_sources.py)
            want_ = _sc.ks.release_columns(kp_, ke_)
            if (c.get('reference', ''), c.get('reference_id', '')) != (want_['reference'], want_['reference_id']):
                row['判定'] = '★説明できない：出典の表の出典が、座標KB の場所の出典と違う'
                row['詳細'] = f"出典の表＝{c.get('reference', '')} {c.get('reference_id', '')}・座標KB＝{want_['reference']} {want_['reference_id']}"
                status[sid] = row['判定']
        if CITED_STRICT and kp_ and ke_ and ke_.get('use') == 'adjacent':
            ref_ = c.get('reference_stop_id', '')
            ll_ = rel_ll.get(ref_)
            dd = coord_refs.dist_m(la, lo, ll_[0], ll_[1]) if ll_ else None
            if dd is None or dd > TOL_M:
                row['判定'] = '★説明できない：借りる行だが、借りた先の驛の公開版の値と合わない'
                row['詳細'] = f"借りた先 {ref_ or '（reference_stop_id が空）'}" + (f' と {dd:.1f} m' if dd is not None else '・公開版に無い')
                status[sid] = row['判定']
        elif row['判定'].startswith('説明できる') and kp_ and ke_ and ke_.get('use') != 'adjacent' and (CITED_STRICT or not kp_.get('source_read')):
            sr_ = kp_.get('source_read', '')
            if sr_ == 'wikidata_display':
                # the cited revision has no body coordinate and the article displays the Wikidata coordinate, so compare
                # with the displayed coordinate (fetched coords); the revision ID comes from the places table because
                # stations of single-stop trips (extras/single_stop_trips.csv) have no row in the source table
                rid_ = c.get('reference_id') or _sc.ks.release_columns(kp_, ke_)['reference_id']
                cs_ = (fetched.get(rid_) or {}).get('coords') or []
                dd = min((coord_refs.dist_m(la, lo, x[0], x[1]) for x in cs_), default=None)
                if dd is None or dd > TOL_M:
                    row['判定'] = '★説明できない：Wikidata から表示される座標の印だが、記事の表示の座標と合わない'
                    row['詳細'] = (f"{rid_} の表示の座標と {dd:.1f} m" if dd is not None
                                  else f"{rid_} の表示の座標を取り寄せていない（data/knowledge/release_reference_coords.json に無い）")
                    status[sid] = row['判定']
            elif sr_ == 'corrected_typo':
                if not any(same_name(o['stop_name'], s['stop_name']) and coord_refs.dist_m(la, lo, float(o['lat']), float(o['lon'])) <= TOL_M
                           for o in ok):
                    row['判定'] = '★説明できない：出典の誤記を直した値の印だが、人が確かめた座標の一覧に無い'
                    row['詳細'] = f"{kp_['source_type']} {kp_['source_id']}（{EXCEPTIONS} に理由つきで足す）"
                    status[sid] = row['判定']
            else:
                dd, st_ = _sc.cited_distance_m(kp_, la, lo, _akm.PLACES_DIR)
                if CITED_STRICT:
                    checkable = kp_['source_type'] in CITED_TYPES or kp_['source_type'].startswith('wikipedia_')
                else:
                    checkable = (kp_['source_type'] in ('n02', 'isj', 'isj_teishajo', 'gazetteer', 'geonames')
                                 or (kp_['source_type'].startswith('wikipedia_') and
                                     (fetched.get(c.get('reference_id', '')) or {}).get('rev_status') == 'coords'))
                if dd is not None and checkable:
                    want = float(kp_['distance_m']) if kp_.get('distance_m') else 0.0
                    if abs(dd - want) > max(TOL_M, 0.2 * want):
                        row['判定'] = '★説明できない：出典の表が挙げる記録と値が合わない'
                        row['詳細'] = (f"{kp_['source_type']} {kp_['source_id']} の記録と {dd:.1f} m（表の distance_m＝{kp_.get('distance_m') or '空'}）"
                                      f"・値は {row['詳細'][:60]}")
                        status[sid] = row['判定']
                elif dd is None and checkable and CITED_STRICT and st_ in ('no_record', 'no_data'):
                    row['判定'] = ('★説明できない：挙げた出典の番号の記録が資料に無い' if st_ == 'no_record' else
                                  '★説明できない：挙げた出典の記録を照らす資料が手元に無い（data/external・release_reference_coords.json）')
                    row['詳細'] = f"{kp_['source_type']} {kp_['source_id']}"
                    status[sid] = row['判定']
                    no_source_data[kp_['source_type']] += st_ == 'no_data'

    def explained(sid):
        return status.get(sid, '').startswith('説明できる')

    coord = {r['stop_id']: (float(r['stop_lat']), float(r['stop_lon'])) for r in rows}

    def resolve(a, line):
        """Anchor station name -> published stop (same name on the same line, without 〈region〉 tag, or prefix match;
        then the same name on another line, explained stops first)."""
        sid = by_name_line.get((a, line))
        if sid is None:
            sid = next((v for (n, ln), v in by_name_line.items()
                        if ln == line and (n.split('〈')[0] == a or (a.startswith(n) and len(n) >= 2))), None)
        if sid is None:
            # an anchor not on the same line (interpolated with another line's printed mileage; e.g. the anchor 眞玉橋 of
            # 古波藏〈嘉手納線〉 is on 糸滿線 and 與那原線): look for the same name on other lines, explained stops first
            cands = sorted((v for (n, ln), v in by_name_line.items() if n == a or n.split('〈')[0] == a),
                           key=lambda v: (not explained(v), v))
            sid = cands[0] if cands else None
        if sid is None:
            # an anchor missed only because of old/new kanji (spelling differs between the record and the published name):
            # compare as same_name()/_nk() do, same line first, then other lines (earlier matches are kept)
            ka = _nk(a)
            sid = next((v for (n, ln), v in by_name_line.items() if ln == line and _nk(n) == ka), None)
            if sid is None:
                cands = sorted((v for (n, ln), v in by_name_line.items() if _nk(n) == ka),
                               key=lambda v: (not explained(v), v))
                sid = cands[0] if cands else None
        return sid

    def f_check(row):
        """Recompute a derived value from the published values of anchors A and B and the printed-mileage fraction,
        and compare. Return (agrees, explanation), or None if unreadable."""
        dr, _ = f_head.get(row['stop_id'], (None, row['stop_name']))
        if not dr or not dr.get('fraction') or not dr.get('anchor_a') or not dr.get('anchor_b'):
            return None
        A, B, f, how = dr['anchor_a'], dr['anchor_b'], float(dr['fraction']), f"計算の記録＝{dr.get('how', '')}"
        sa = by_key.get(tuple(A.split('|', 1))) or resolve(A.split('|', 1)[0], row['line_name'])
        sb = by_key.get(tuple(B.split('|', 1))) or resolve(B.split('|', 1)[0], row['line_name'])
        if not sa or not sb:
            return None
        (a0, a1), (b0, b1) = coord[sa], coord[sb]
        px = (a0 + (b0 - a0) * f, a1 + (b1 - a1) * f)
        la, lo = coord[row['stop_id']]
        d = coord_refs.dist_m(la, lo, px[0], px[1])
        tol = max(F_TOL_M, F_TOL_REL * coord_refs.dist_m(a0, a1, b0, b1))
        return d <= tol, (f'{A}—{B} の {f:.4f}（{how}）で計算し直すと {d:.1f} m（許す {tol:.1f} m）・'
                          f'計算し直した値 {px[0]:.6f},{px[1]:.6f}')

    # resolve E and F (anchors depend on each other, so iterate until stable)
    for _ in range(10):
        changed = False
        for row in rows:
            j = row['判定']
            if not j.startswith('保留'):
                continue
            if j.startswith('保留：E'):
                bad = [x for x in by_line.get(row['line_name'], []) if not status[x].startswith(('説明できる', '保留：E'))]
                if not bad and row['line_name']:
                    new = ('説明できる：E 公開版で内挿（同じ線の内挿でない驛はすべて説明できる）', '')
                elif any(status[x].startswith('★') for x in bad):
                    names = sorted({next(r['stop_name'] for r in rows if r['stop_id'] == x) for x in bad if status[x].startswith('★')})
                    new = ('★説明できない：内挿の目印に説明できない驛がある線', '・'.join(names[:8]))
                else:
                    continue
            else:
                names = [a for a in row['詳細'].split('・') if a]
                if not names:
                    new = ('★説明できない：目印を読めない derived', '')
                else:
                    ids, missing = [], []
                    for a in names:
                        sid = resolve(a, row['line_name'])
                        (ids if sid else missing).append(sid or a)
                    if missing:
                        new = ('★説明できない：目印を公開版に見つけられない derived', '・'.join(missing))
                    elif all(explained(x) for x in ids):
                        # besides explained anchors, the value must be recomputable from the anchors' published values
                        # and the printed mileage (catches derived values left stale after an anchor moved)
                        chk = f_check(row)
                        if chk is None:
                            new = ('★説明できない：derived を計算し直せない（note から目印と割合を読めない・哩程が無い）', row['詳細'])
                        elif chk[0]:
                            new = ('説明できる：F 座標KB の derived（目印はすべて説明できる・目印の公開版の値と哩程で計算し直して合う）',
                                   f"{row['詳細']}（{chk[1]}）")
                        else:
                            new = ('★説明できない：derived の値が、目印の公開版の値と哩程から計算し直した値と合わない', chk[1])
                    elif any(status[x].startswith('★') for x in ids):
                        new = ('★説明できない：目印に説明できない驛がある derived',
                               '・'.join(next(r['stop_name'] for r in rows if r['stop_id'] == x) for x in ids if status[x].startswith('★')))
                    else:
                        continue
            row['判定'], row['詳細'] = new
            status[row['stop_id']] = new[0]
            changed = True
        if not changed:
            break
    for row in rows:
        if row['判定'].startswith('保留'):
            row['判定'] = '★説明できない：目印が循環して決まらない'
            status[row['stop_id']] = row['判定']

    if CITED_STRICT:
        # check parent stations (location_type = 1) too: the value must equal the published value of the child cited
        #   in the source table (reference_stop_id), that child must belong to this parent and be explained
        st_all = {s['stop_id']: s for s in csv.DictReader(open(os.path.join(rel, 'gtfs', 'stops.txt'), encoding='utf-8'))}
        for pid, p in st_all.items():
            if p.get('location_type') != '1':
                continue
            c = src.get(pid, {})
            ref_ = c.get('reference_stop_id', '')
            ch = st_all.get(ref_)
            row = {'stop_id': pid, 'stop_name': p['stop_name'], 'line_name': '', 'stop_lat': p['stop_lat'], 'stop_lon': p['stop_lon'],
                   '内部の出どころ': '', 'coord_class': c.get('coord_class', ''), 'coord_method': c.get('coord_method', ''),
                   'reference': c.get('reference', ''), 'reference_id': c.get('reference_id', ''),
                   'reference_distance_m': c.get('reference_distance_m', ''), '判定': '', '詳細': '', '座標KB の note': ''}
            if not ch or ch.get('location_type') == '1' or ch.get('parent_station') != pid:
                row['判定'], row['詳細'] = '★説明できない：親の驛だが、出典の表が挙げる子の驛がこの親の子でない', ref_ or '（reference_stop_id が空）'
            elif coord_refs.dist_m(float(p['stop_lat']), float(p['stop_lon']), float(ch['stop_lat']), float(ch['stop_lon'])) > 0.01:
                row['判定'], row['詳細'] = '★説明できない：親の驛だが、子の驛の値と違う', ref_
            elif not status.get(ref_, '').startswith('説明できる'):
                row['判定'], row['詳細'] = '★説明できない：親の驛だが、値を借りた子の驛が説明できない', ref_
            else:
                row['判定'], row['詳細'] = '説明できる：親の驛（出典の表が挙げる子の驛と同じ値）', ref_
            rows.append(row)
            status[pid] = row['判定']
        if no_source_data:
            print('  ★ 4e：挙げた出典の記録を照らす資料が手元に無い＝' + '・'.join(f'{k} {v} 驛' for k, v in sorted(no_source_data.items()))
                  + '（data/external の資料を scripts/release/fetch_external_sources.py で取り寄せてから回す）')

    rows.sort(key=lambda r: (not r['判定'].startswith('★'), r['判定'], r['line_name'], r['stop_name']))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\r\n')
        w.writeheader()
        w.writerows(rows)
    cnt = Counter(r['判定'] for r in rows)
    n = sum(v for k, v in cnt.items() if k.startswith('★'))
    print(f'  4e: 公開版の座標 {len(rows)}（公開できる点の資料 {"・".join(pub.loaded)}）→ {out}')
    for k, v in sorted(cnt.items(), key=lambda kv: (kv[0].startswith('★'), kv[0])):
        print(f'    {k} {v}')
    print(f'  4e: ★説明できない {n}')
    if gate and n:
        print('  ★★ 4e の関門：公開できる出典で説明できない座標が残っている＝この版は公開しない'
              '（座標KB を出典の点にそろえるか、公開できる出典で確かめて公開用_人が確かめた座標に理由つきで足す）')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
