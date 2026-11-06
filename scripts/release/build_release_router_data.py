#!/usr/bin/env python3
"""
build_release_router_data.py — Build journey-planner data (router_data.json, .js) from the published GTFS (data/gtfs_v1_release) alone

    python3 scripts/release/build_release_router_data.py                     # data/gtfs_v1_release -> data/gtfs_v1_release_router/
    python3 scripts/release/build_release_router_data.py <published dataset folder> --out <output folder>

generate_router_data.py looks up stations in the internal station table (S… in stops_master.csv), so pointed at the
published dataset it finds no trips. This script reads only gtfs/ and extras/ of the published dataset (not the
internal tables or the coordinate tables) and writes nothing into that folder.

How it is built (trip assembly calls build_trips, load_freq_labels and build_router_params of generate_router_data.py
instead of copying them):
  - Station groups = parent stations of the published dataset (location_type=1 in stops.txt, PS…) and their
    coordinates; these are grouped by the same function as the journey planner (item 6 of
    scripts/build_release_gtfs.py). name_to_groups maps child station names to parent stations (so child names that
    differ from the group name also resolve).
  - Trips = trips.txt and stop_times.txt. Template trips in frequencies.txt expand into estimated trips (est:1).
    Trip key k = gtfs_trip_key in extras/trip_source.csv (line name__direction__number; trip_attributes.csv,
    service_frequency.csv and physical_trains.csv use the same key). For template trips it is
    line name__direction__original number (original_trip_short_name). Number n is also the original number.
    The published trip_id (TR…) is added as t (for estimated trips, the template's trip_id).
    Terminal arrivals added to departure-only trips are estimates (extras/estimated_stop_times.csv, timepoint=0 in
    stop_times.txt); router_data has no flag for them, so look them up by t.
  - Display names of estimated trips: extras/frequency_box.csv and frequency_sections.csv (template column = trip_id).
  - Through-train ID p: extras/physical_trains.csv.
  - Walking links walks = rows of transfers.txt between different parent stations (minutes = min_transfer_time / 60).
    Zero-minute transfers within a parent station are represented by the station group itself.
  - router_params = the same flags as the defaults of generate_router_data.py (same environment variables).
    meta = feed_version and counts (no paths or build time, so the same published dataset always gives
    byte-identical output).
  - tools/make_router_data.py of the published dataset (a standard-library-only copy) produces byte-identical output.
    If you change how the data is assembled, change it too.
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
import generate_router_data as grd  # noqa: E402  assemble trips with the journey planner's own functions


def rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def build(rel):
    G = os.path.join(rel, 'gtfs')
    X = os.path.join(rel, 'extras')
    feed_version = rows(os.path.join(G, 'feed_info.txt'))[0].get('feed_version', '')

    # 1. Stations and station groups (parent stations)
    stops = rows(os.path.join(G, 'stops.txt'))
    groups, group_of_stop, stops_info = {}, {}, {}
    name_to_groups = defaultdict(list)
    for r in stops:
        if r.get('location_type') == '1':
            groups[r['stop_id']] = {'name': r['stop_name'], 'lat': float(r['stop_lat']), 'lon': float(r['stop_lon']),
                                    'members': []}
    no_parent = []
    for r in stops:
        if r.get('location_type') == '1':
            continue
        sid = r['stop_id']
        stops_info[sid] = {'name': r['stop_name'], 'lat': float(r['stop_lat']), 'lon': float(r['stop_lon'])}
        pid = r.get('parent_station', '')
        if pid not in groups:
            no_parent.append(f"{r['stop_name']}（{sid}）")
            continue
        group_of_stop[sid] = pid
        groups[pid]['members'].append(sid)
        if pid not in name_to_groups[r['stop_name']]:
            name_to_groups[r['stop_name']].append(pid)
    if no_parent:
        raise SystemExit(f'親の驛の無い驛がある（公開版の stops.txt の parent_station）: {"・".join(no_parent[:10])}')

    # 2. Trips (key = internal key, gtfs_trip_key in trip_source.csv; template trips: line name__direction__original number)
    routes = {r['route_id']: r['route_short_name'] for r in rows(os.path.join(G, 'routes.txt'))}
    src = {r['trip_id']: r for r in rows(os.path.join(X, 'trip_source.csv'))}
    trip_info = {}
    for r in rows(os.path.join(G, 'trips.txt')):
        s = src.get(r['trip_id'], {})
        trip_info[r['trip_id']] = {
            'route_id': r['route_id'],
            'name': s.get('original_trip_short_name') or r.get('trip_short_name', ''),
            'direction': 'outbound' if r.get('direction_id') == '0' else 'inbound',
            'key': s.get('gtfs_trip_key') or None,
            't': r['trip_id'],
        }
    trip_stops = defaultdict(list)
    for r in rows(os.path.join(G, 'stop_times.txt')):
        trip_stops[r['trip_id']].append(r)
    freq_of = defaultdict(list)
    fp = os.path.join(G, 'frequencies.txt')
    if os.path.exists(fp):
        for r in rows(fp):
            freq_of[r['trip_id']].append(r)

    # 3. Display names of estimated trips (in the published tables the template column is named trip_id)
    def with_template(path):
        if not (freq_of and os.path.exists(path)):
            return None
        return [{**r, 'template_trip_id': r.get('trip_id', '')} for r in rows(path)]
    freq_label, listed_tf = grd.load_freq_labels(with_template(os.path.join(X, 'frequency_box.csv')),
                                                 with_template(os.path.join(X, 'frequency_sections.csv')))

    # 4. Through trains (the published table has a gtfs_trip_key column)
    phys = {}
    if grd.PHYSICAL_TRAINS:
        for r in rows(os.path.join(X, 'physical_trains.csv')):
            k = r['gtfs_trip_key']
            if k in phys and phys[k] != r['physical_train_id']:
                raise SystemExit(f'physical_trains.csv: {k} が 2 本の物理列車に入っている（{phys[k]} / {r["physical_train_id"]}）')
            phys[k] = r['physical_train_id']

    trips, n_phys, n_est, n_collapsed = grd.build_trips(trip_stops, trip_info, routes, group_of_stop, groups, stops_info,
                                                        freq_of, freq_label, listed_tf, phys)

    # 5. Walking links (rows of transfers.txt between different parent stations)
    walk = defaultdict(dict)
    odd = []
    tp = os.path.join(G, 'transfers.txt')
    if grd.WALK_EDGES and os.path.exists(tp):
        for r in rows(tp):
            a, b = group_of_stop.get(r['from_stop_id']), group_of_stop.get(r['to_stop_id'])
            if a is None or b is None or a == b:
                continue
            mins = int(r['min_transfer_time']) // 60
            if walk[a].get(b, mins) != mins:
                odd.append((a, b, walk[a][b], mins))
            walk[a][b] = mins
    if odd:
        raise SystemExit(f'transfers.txt で同じ親の驛どうしの分が揃わない: {odd[:5]}')
    walks = {g: sorted([[g2, m] for g2, m in d.items()]) for g, d in sorted(walk.items())}
    asym = [(a, b) for a, d in walk.items() for b in d if walk.get(b, {}).get(a) != d[b]]
    if asym:
        raise SystemExit(f'徒歩の乗換が片向きしか無い: {asym[:5]}')

    data = {
        'groups': {g: {'name': v['name'], 'lat': v['lat'], 'lon': v['lon']} for g, v in groups.items()},
        'name_to_groups': dict(name_to_groups),
        'trips': trips,
    }
    if walks:
        data['walks'] = walks
    rp = grd.build_router_params()
    if rp:
        data['router_params'] = rp
    # no build time, so the same published dataset always gives byte-identical output
    data['meta'] = {
        'source': 'Japan1925-GTFS dataset (gtfs/ and extras/)',
        'feed_version': feed_version,
        'groups': len(groups),
        'trips': len(trips),
    }
    stats = {'stops': len(stops_info), 'groups': len(groups), 'names': len(name_to_groups), 'trips': len(trips),
             'est': n_est, 'phys': n_phys, 'collapsed': n_collapsed, 'walk_pairs': sum(len(v) for v in walks.values()) // 2,
             'no_key': sum(1 for t in trip_info.values() if not t['key'] and t['t'] not in freq_of),
             'feed_version': feed_version}
    return data, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('release', nargs='?', default=os.path.join(BASE, 'data', 'gtfs_v1_release'))
    ap.add_argument('--out', default=os.path.join(BASE, 'data', 'gtfs_v1_release_router'))
    a = ap.parse_args()
    data, st = build(a.release)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'router_data.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(a.out, 'router_data.js'), 'w', encoding='utf-8') as f:
        f.write('var ROUTER_DATA = ')
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')
    print(f"公開版（feed_version {st['feed_version']}）→ {os.path.join(a.out, 'router_data.json')}")
    print(f"  驛 {st['stops']}・驛グループ（親の驛）{st['groups']}・名前 {st['names']}")
    print(f"  便 {st['trips']}（推定便 {st['est']}・物理列車の番号つき {st['phys']}・推定便の雛形でまとめた驛 {st['collapsed']}）")
    print(f"  徒歩の乗換 {st['walk_pairs']} 組・router_params {data.get('router_params', {})}")
    if st['no_key']:
        print(f"  ★WARN 内部の鍵（gtfs_trip_key）の無い刷られた便 {st['no_key']}（鍵を 線名__方向__番号 で作った）")


if __name__ == '__main__':
    main()
