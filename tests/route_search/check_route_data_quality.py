#!/usr/bin/env python3
"""check_route_data_quality.py — measure the quality of the journey planner data (RQ4, RQ8)

Reports two measures that need no search. The only input is `router_data.json`
(the data the journey planner actually uses; stations are station groups, so same-name stations are already resolved).

RQ4 physically impossible segments
    For consecutive timed stops within a trip, compute straight-line distance / travel time.
    Track is never straighter than the chord, so the speed is a lower bound; above the threshold it is impossible
    for 1925 (no false positives, but errors in the 60 km/h range are missed).
    Also a fingerprint of transcription errors and dropped `/N日目` (day offsets).
    Some cases are consistent within a page: the too-short segment only appears once a band (on another page) and
    the detailed table are merged into one trip, so checks that look at one sheet at a time cannot find them.

RQ8 reachability (where one cannot go)
    (a) stations where one cannot board or alight: groups with no time in any trip (offered as station names on the
        page but never reachable)
    (b) stations not connected to the mainland: the component built from timed stops only differs from that of 東京
    (c) stations reachable on foot: those in (b) close to the nearest station of the mainland component
    Only timed stops are linked. Linking all stops of a trip in order would let the intermediate stations of
    frequency-only template trips (names only) bridge components that are not connected.

Usage:
    python3 tests/route_search/check_route_data_quality.py                       # default: data/gtfs_v1_release_router/router_data.json
    python3 tests/route_search/check_route_data_quality.py --data <router_data.json>
    python3 tests/route_search/check_route_data_quality.py --rq4-only / --rq8-only
    python3 tests/route_search/check_route_data_quality.py --write               # rewrite the RQ8 list CSV

Exit code: 1 if RQ4 has segments above the threshold that are not in the suppression list
(tests/route_search/rq4_exemptions.csv)
"""
import argparse
import collections
import csv
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, 'tests', 'route_search')
DEFAULT_DATA = os.path.join(BASE, 'data', 'gtfs_v1_release_router', 'router_data.json')
SUPPRESS = os.path.join(OUT_DIR, 'rq4_exemptions.csv')
RQ8_CSV = os.path.join(OUT_DIR, 'rq8_unreachable_stops.csv')

SPEED_LIMIT = 100.0   # km/h. Scheduled speeds of 1925 expresses were about 60 km/h, at most about 95 km/h
MIN_KM = 5.0          # shorter segments are skipped (rounding to minutes gives spurious speeds)
WALK_M = 1000.0       # RQ8 (c): distance regarded as reachable on foot


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.0,
                      (a[1] - b[1]) * 111.0 * math.cos(math.radians((a[0] + b[0]) / 2)))


def tomin(s):
    if not s:
        return None
    h, m = s.split(':')
    return int(h) * 60 + int(m)


def load_suppress():
    """RQ4 suppression list (segments checked by hand and found to match the printed timetable). Empty if absent."""
    if not os.path.exists(SUPPRESS):
        return []
    with open(SUPPRESS, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def rq4(D, sup):
    G, T = D['groups'], D['trips']
    rows, n_seg, n_skip = [], 0, 0
    fastest = None   # fastest segment of at least MIN_KM (reported in the paper's cross-checks)
    for t in T:
        s, dep, arr = t['s'], t['dep'], t['arr']
        prev = None
        for i, g in enumerate(s):
            a, d = tomin(arr[i]), tomin(dep[i])
            cur = a if a is not None else d
            if cur is None:
                continue
            p = G[g]
            if prev is not None:
                pg, pt = prev
                dt = cur - pt
                while dt < 0:
                    dt += 1440
                q = G[pg]
                if p.get('lat') is None or q.get('lat') is None:
                    n_skip += 1
                elif dt > 0:
                    n_seg += 1
                    dist = km((q['lat'], q['lon']), (p['lat'], p['lon']))
                    v = dist / (dt / 60.0)
                    if dist >= MIN_KM and (fastest is None or v > fastest['速度']):
                        fastest = {'速度': v, '距離km': round(dist, 1), '所要分': dt, 'line_name': t['l'],
                                   'trip_num': t['n'], 'from': q['name'], 'to': p['name']}
                    if v > SPEED_LIMIT and dist >= MIN_KM:
                        rows.append({'速度': round(v), '距離km': round(dist, 1), '所要分': dt,
                                     'line_name': t['l'], 'trip_num': t['n'],
                                     'from': q['name'], 'to': p['name'],
                                     'est': '推定便' if t.get('est') else '刷られた便'})
            prev = (g, d if d is not None else cur)

    # match the suppression list (also report entries that match nothing: no longer needed, or the key changed)
    hit = collections.Counter()
    kept = []
    for r in rows:
        m = None
        for i, x in enumerate(sup):
            if (x['line_name'] == r['line_name'] and str(x['trip_num']) == str(r['trip_num'])
                    and x['from_stop'] == r['from'] and x['to_stop'] == r['to']):
                m = i
                break
        if m is None:
            kept.append(r)
        else:
            hit[m] += 1
    stale = [x for i, x in enumerate(sup) if hit[i] == 0]
    return rows, kept, stale, n_seg, n_skip, fastest


def usable_and_components(D):
    """Link timed stops only. Returns (groups where one can board or alight, find(), mainland root)."""
    G, T = D['groups'], D['trips']
    par = {g: g for g in G}

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    for t in T:
        u = [g for i, g in enumerate(t['s']) if t['dep'][i] or t['arr'][i]]
        for x, y in zip(u, u[1:]):
            uni(x, y)
    # walking links, if any, also connect
    for g, vs in (D.get('walks') or {}).items():
        for h, _m in vs:
            uni(g, h)
    has = collections.Counter()
    for t in T:
        for i, g in enumerate(t['s']):
            if t['dep'][i] or t['arr'][i]:
                has[g] += 1
    U = {g for g in G if has[g]}
    main = find(D['name_to_groups']['東京'][0])
    return U, find, main


def rq8(D):
    G = D['groups']
    U, find, main = usable_and_components(D)
    notime = [g for g in G if g not in U]
    outside = [g for g in U if find(g) != main]
    mainpts = [(G[g]['lat'], G[g]['lon'], g) for g in U if find(g) == main and G[g].get('lat') is not None]
    rows = []
    for g in sorted(notime):
        rows.append({'種別': '乗り降りできない', 'group': g, 'name': G[g]['name'],
                     '本土までの距離m': '', '最寄り': ''})
    for g in sorted(outside):
        v = G[g]
        near, d = '', ''
        if v.get('lat') is not None and mainpts:
            b = min(mainpts, key=lambda q: km((v['lat'], v['lon']), (q[0], q[1])))
            d = round(km((v['lat'], v['lon']), (b[0], b[1])) * 1000)
            near = G[b[2]]['name']
        rows.append({'種別': '本土からつながっていない', 'group': g, 'name': v['name'],
                     '本土までの距離m': d, '最寄り': near})
    names_bad = sorted({G[g]['name'] for g in notime
                        if all(x in set(notime) for x in D['name_to_groups'].get(G[g]['name'], [g]))})
    walkable = [r for r in rows if r['種別'] == '本土からつながっていない'
                and r['本土までの距離m'] != '' and r['本土までの距離m'] <= WALK_M]
    return rows, len(U), len(notime), len(outside), names_bad, walkable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DEFAULT_DATA)
    ap.add_argument('--rq4-only', action='store_true')
    ap.add_argument('--rq8-only', action='store_true')
    ap.add_argument('--write', action='store_true', help='RQ8 の一覧 CSV を書き直す')
    a = ap.parse_args()
    path = a.data
    if path.endswith('.json') or os.path.exists(path):
        raw = open(path, encoding='utf-8').read()
    else:                                   # read .js when there is no .json
        path = path.replace('.json', '.js')
        raw = open(path, encoding='utf-8').read()
    raw = raw.lstrip()
    if not raw.startswith('{'):             # the form `var ROUTER_DATA = {...};`
        raw = raw[raw.index('{'):raw.rindex('}') + 1]
    D = json.loads(raw)
    print(f'データ {os.path.relpath(path, BASE)}'
          + (f"（{D['meta'].get('gtfs_dir') or D['meta'].get('source', '?')} / "
             f"GTFS {D['meta'].get('gtfs_stop_times_mtime') or D['meta'].get('feed_version', '?')}）"
             if D.get('meta') else '（素性の記録なし）'))   # the published network (build_release_router_data.py) has source and feed_version instead of gtfs_dir
    fails = 0

    if not a.rq8_only:
        sup = load_suppress()
        rows, kept, stale, n_seg, n_skip, fastest = rq4(D, sup)
        print(f'\n■ RQ4 物理的に不可能な区間（{SPEED_LIMIT:.0f}km/h 超かつ {MIN_KM:.0f}km 以上）')
        print(f'   母数＝隣り合う「時刻のある停車」 {n_seg:,}（座標が引けず測れない {n_skip}）')
        if fastest:
            print(f"   {MIN_KM:.0f}km 以上の区間の直線の速さの最大＝{fastest['速度']:.1f} km/h（{fastest['line_name']} "
                  f"{fastest['trip_num']} {fastest['from']}→{fastest['to']} {fastest['距離km']}km / {fastest['所要分']}分）")
        print(f'   閾値超え {len(rows)}（うち抑制 {len(rows) - len(kept)}）→ ★要対応 {len(kept)}')
        for r in sorted(kept, key=lambda r: -r['速度']):
            print(f"   ★ {r['速度']:>6} km/h  {r['line_name']} {r['trip_num']}（{r['est']}）"
                  f"  {r['from']}→{r['to']}  {r['距離km']}km / {r['所要分']}分")
        if stale:
            print(f'   ⚠ 当たらなかった抑制 {len(stale)} 行（もう出ない／鍵がずれた。理由を確かめて消すか直す）')
            for x in stale:
                print(f"      {x['line_name']} {x['trip_num']} {x['from_stop']}→{x['to_stop']}")
        fails += len(kept)

    if not a.rq4_only:
        rows, n_usable, n_notime, n_outside, names_bad, walkable = rq8(D)
        print(f'\n■ RQ8 到達可能性')
        print(f'   (a) 乗り降りできない group {n_notime}／どの group も時刻を持たない駅名 {len(names_bad)}')
        print(f'   (b) 本土からつながっていない駅 {n_outside} / 乗り降りできる {n_usable}')
        print(f'   (c) そのうち本土成分まで {WALK_M:.0f}m 以内 {len(walkable)}')
        for r in sorted(walkable, key=lambda r: r['本土までの距離m'])[:10]:
            print(f"      {r['本土までの距離m']:>5}m  {r['name']} ←→ {r['最寄り']}")
        if names_bad:
            print(f"   (a) の駅名: {'、'.join(names_bad[:20])}" + (' …' if len(names_bad) > 20 else ''))
        if a.write:
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(RQ8_CSV, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, fieldnames=['種別', 'group', 'name', '本土までの距離m', '最寄り'],
                                   lineterminator='\r\n')
                w.writeheader()
                w.writerows(rows)
            print(f'   → {os.path.relpath(RQ8_CSV, BASE)}（{len(rows)} 行。git の差分が「前回からの増減」）')

    print(f'\n★要対応 {fails} 件' if fails else '\n✅ 要対応なし')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
