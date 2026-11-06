#!/usr/bin/env python3
"""
Build a route-search network (router_data.json) from this feed alone (standard library only).

    python3 tools/make_router_data.py                      # writes router_data/router_data.json and .js
    python3 tools/make_router_data.py --out my_network
    python3 tools/make_router_data.py --feed path/to/feed  # the folder that holds gtfs/ and extras/

Only gtfs/ and extras/ of the feed are read. The same feed always gives byte-identical files.
router_data.js holds the same data as a script ("var ROUTER_DATA = ...;") for a web page.

Contents of router_data.json:
  groups          Stations: the parent stations of gtfs/stops.txt (location_type=1),
                  {stop_id: {"name", "lat", "lon"}}. Stops are grouped into stations exactly as in
                  the feed (see item 3 of "Notes on the feed" and "Route-search network" in DETAILS.md).
  name_to_groups  {name: [station stop_id, ...]} for every stop name, including names of stops that
                  differ from the name of their station. One name may belong to several stations.
  trips           One entry per trip of gtfs/trips.txt, and one per estimated run of a template trip
                  of gtfs/frequencies.txt:
                    k    trip key "line__direction__number" (gtfs_trip_key in extras/trip_source.csv;
                         for template trips the original trip_short_name is used as the number).
                         Estimated runs append "_freq<n>".
                    t    trip_id in this feed (for an estimated run, its template trip)
                    l    line name (route_short_name)
                    d    "outbound" (direction_id 0) or "inbound" (direction_id 1)
                    n    the train-number part of k (original_trip_short_name in extras/trip_source.csv:
                         usually the printed number; a provisional key beginning with U where none is
                         printed), or for an estimated run the printed frequency text (e.g. 此間12分毎)
                    s    stations in stop order (stations, not stops)
                    dep, arr  departure and arrival "HH:MM" for each entry of s (null if not given);
                         times of 24:00 and later continue from the day the trip started
                    est  1 for a run expanded from gtfs/frequencies.txt (its times are estimated)
                    sn   {index: stop name} where the stop's own name differs from its station's
                    p    physical_train_id (extras/physical_trains.csv): consecutive trips with the
                         same p are one through train, so changing between them is not a transfer
  walks           {station: [[station, minutes], ...]} walking transfers between stations
                  (the rows of gtfs/transfers.txt between stops of different stations)
  router_params   search rules to be applied by a program that searches this network (which
                  candidate trains and which partial journeys to keep)
  meta            feed_version of the feed and the numbers of stations and trips

Notes:
  * A template trip is repeated from start_time every headway_secs until (not including)
    end_time. In an estimated run, consecutive stops of the same station are merged into one,
    keeping the stop that has a time.
  * Arrival times at the last stop of departure-only trips are not printed in the source but
    computed from the printed running time (extras/estimated_stop_times.csv); they are not marked
    here. Use t and the timepoint column of gtfs/stop_times.txt to tell them apart.
"""
import argparse
import csv
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = 'Japan1925-GTFS dataset (gtfs/ and extras/)'
ROUTER_PARAMS = {'EXACT_CANDIDATES': True, 'PARETO_TRANSFERS': True,
                 'PREV_DAY_BOARDING': True, 'PARETO_CONTINUATION': True,
                 'TIE_FEWER_TRANSFERS': True, 'WALK_LABELS_SEPARATE': True, 'NO_REVISIT': True}


def rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def hhmm(t):
    if not t:
        return None
    parts = t.split(':')
    return f'{parts[0]}:{parts[1]}' if len(parts) >= 2 else t


def minutes(t):
    a = t.split(':')
    return int(a[0]) * 60 + int(a[1])


def frequency_labels(box_rows, section_rows):
    """Printed frequency text for each template trip, and the template trips of listed departures."""
    label, listed = {}, set()
    for r in box_rows or ():
        tid = r.get('trip_id')
        if not tid:
            continue
        if str(r.get('kind', '')).startswith('③'):
            label[tid] = (f"{r.get('service_kind', '')} "
                          f"{(r.get('note') or '').split('＝')[0].replace('原本の列挙 ', '')}（此間ノモノアリ）")
            listed.add(tid)
            continue
        if r.get('minute_of_hour') not in ('', None):
            lab = f"毎時{int(r['minute_of_hour'])}分發"
        elif r.get('interval_min_lo') == r.get('interval_min_hi'):
            lab = f"此間{r['interval_min_lo']}分毎"
        else:
            lab = f"此間{r['interval_min_lo']}分乃至{r['interval_min_hi']}分毎"
        if r.get('service_kind'):
            lab = f"{r['service_kind']} {lab}"
        label[tid] = lab
    for r in section_rows or ():
        tid = r.get('trip_id')
        if not tid:
            continue
        lo, hi = r.get('interval_min_lo'), r.get('interval_min_hi')
        label[tid] = f'{lo}分毎' if lo == hi else f'{lo}分乃至{hi}分毎'
    return label, listed


def build(feed):
    G = os.path.join(feed, 'gtfs')
    X = os.path.join(feed, 'extras')
    feed_version = rows(os.path.join(G, 'feed_info.txt'))[0].get('feed_version', '')

    # stations (parent stations) and the station of each stop
    stops = rows(os.path.join(G, 'stops.txt'))
    groups, station_of, stop_name = {}, {}, {}
    name_to_groups = defaultdict(list)
    for r in stops:
        if r.get('location_type') == '1':
            groups[r['stop_id']] = {'name': r['stop_name'], 'lat': float(r['stop_lat']), 'lon': float(r['stop_lon'])}
    for r in stops:
        if r.get('location_type') == '1':
            continue
        pid = r.get('parent_station', '')
        if pid not in groups:
            raise SystemExit(f"stop without a parent station: {r['stop_id']} {r['stop_name']}")
        station_of[r['stop_id']] = pid
        stop_name[r['stop_id']] = r['stop_name']
        if pid not in name_to_groups[r['stop_name']]:
            name_to_groups[r['stop_name']].append(pid)

    # trips
    routes = {r['route_id']: r['route_short_name'] for r in rows(os.path.join(G, 'routes.txt'))}
    source = {r['trip_id']: r for r in rows(os.path.join(X, 'trip_source.csv'))}
    trip_info = {}
    for r in rows(os.path.join(G, 'trips.txt')):
        s = source.get(r['trip_id'], {})
        trip_info[r['trip_id']] = {'route_id': r['route_id'],
                                   'name': s.get('original_trip_short_name') or r.get('trip_short_name', ''),
                                   'direction': 'outbound' if r.get('direction_id') == '0' else 'inbound',
                                   'key': s.get('gtfs_trip_key') or None}
    stop_times = defaultdict(list)
    for r in rows(os.path.join(G, 'stop_times.txt')):
        stop_times[r['trip_id']].append(r)
    freq = defaultdict(list)
    p = os.path.join(G, 'frequencies.txt')
    if os.path.exists(p):
        for r in rows(p):
            freq[r['trip_id']].append(r)

    def table(name):
        path = os.path.join(X, name)
        return rows(path) if freq and os.path.exists(path) else None
    label, listed = frequency_labels(table('frequency_box.csv'), table('frequency_sections.csv'))

    physical = {}
    for r in rows(os.path.join(X, 'physical_trains.csv')):
        k = r['gtfs_trip_key']
        if k in physical and physical[k] != r['physical_train_id']:
            raise SystemExit(f"{k} is in two physical trains ({physical[k]} / {r['physical_train_id']})")
        physical[k] = r['physical_train_id']

    trips = []
    for trip_id, st in stop_times.items():
        info = trip_info.get(trip_id)
        if not info:
            continue
        line = routes.get(info['route_id'], '')
        st.sort(key=lambda x: int(x['stop_sequence']))
        seq = [(station_of[r['stop_id']], r) for r in st if r['stop_id'] in station_of]
        if not seq:
            continue
        if trip_id in freq:
            # merge consecutive stops of the same station in a template trip, keeping the stop with a time
            kept = []
            for g, r in seq:
                timed = bool(r.get('departure_time') or r.get('arrival_time'))
                if kept and kept[-1][0] == g:
                    if timed and not bool(kept[-1][1].get('departure_time') or kept[-1][1].get('arrival_time')):
                        kept[-1] = (g, r)
                        continue
                    if not timed:
                        continue
                kept.append((g, r))
            seq = kept
        key = info['key'] or f"{line}__{info['direction']}__{info['name']}"
        sn = {str(i): stop_name[r['stop_id']] for i, (g, r) in enumerate(seq)
              if stop_name[r['stop_id']] != groups[g]['name']}
        if trip_id in freq:
            mins = [(minutes(r['departure_time']) if r.get('departure_time') else None,
                     minutes(r['arrival_time']) if r.get('arrival_time') else None) for _, r in seq]
            t0 = next(m for m in (d if d is not None else a for d, a in mins) if m is not None)
            for fr in freq[trip_id]:
                start, end, hw = minutes(fr['start_time']), minutes(fr['end_time']), int(fr['headway_secs']) // 60
                k, d = 0, start
                while d < end and hw > 0:
                    shift = d - t0
                    k += 1
                    trips.append({
                        'k': f'{key}_{trip_id}_freq{k}' if trip_id in listed else f'{key}_freq{k}',
                        'l': line, 'd': info['direction'], 'n': label.get(trip_id, '此間○分毎'),
                        's': [g for g, _ in seq],
                        'dep': [f'{(m + shift) // 60:02d}:{(m + shift) % 60:02d}' if m is not None else None for m, _ in mins],
                        'arr': [f'{(m + shift) // 60:02d}:{(m + shift) % 60:02d}' if m is not None else None for _, m in mins],
                        'est': 1,
                        **({'sn': sn} if sn else {}),
                        't': trip_id,
                    })
                    d += hw
            continue
        rec = {'k': key, 'l': line, 'd': info['direction'], 'n': info['name'], 's': [g for g, _ in seq],
               'dep': [hhmm(r.get('departure_time')) for _, r in seq],
               'arr': [hhmm(r.get('arrival_time')) for _, r in seq]}
        if key in physical:
            rec['p'] = physical[key]
        if sn:
            rec['sn'] = sn
        rec['t'] = trip_id
        trips.append(rec)

    # walking transfers between stations
    walk = defaultdict(dict)
    p = os.path.join(G, 'transfers.txt')
    if os.path.exists(p):
        for r in rows(p):
            a, b = station_of.get(r['from_stop_id']), station_of.get(r['to_stop_id'])
            if a is None or b is None or a == b:
                continue
            m = int(r['min_transfer_time']) // 60
            if walk[a].get(b, m) != m:
                raise SystemExit(f'transfers.txt gives two times between {a} and {b}')
            walk[a][b] = m
    walks = {g: sorted([[g2, m] for g2, m in d.items()]) for g, d in sorted(walk.items())}

    data = {'groups': groups, 'name_to_groups': dict(name_to_groups), 'trips': trips}
    if walks:
        data['walks'] = walks
    data['router_params'] = dict(ROUTER_PARAMS)
    data['meta'] = {'source': SOURCE, 'feed_version': feed_version, 'groups': len(groups), 'trips': len(trips)}
    return data


def main():
    ap = argparse.ArgumentParser(description='Build router_data.json (a route-search network) from the feed.')
    ap.add_argument('--feed', default=os.path.dirname(HERE), help='folder that holds gtfs/ and extras/')
    ap.add_argument('--out', default='router_data', help='output folder')
    a = ap.parse_args()
    data = build(a.feed)
    os.makedirs(a.out, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(a.out, 'router_data.json'), 'w', encoding='utf-8') as f:
        f.write(text)
    with open(os.path.join(a.out, 'router_data.js'), 'w', encoding='utf-8') as f:
        f.write('var ROUTER_DATA = ' + text + ';\n')
    m = data['meta']
    print(f"{a.out}/router_data.json: feed_version {m['feed_version']}, {m['groups']} stations, {m['trips']} trips")


if __name__ == '__main__':
    main()
