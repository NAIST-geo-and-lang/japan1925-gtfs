#!/usr/bin/env python3
"""drop_coordless_stops.py — in the published dataset, remove stops without coordinates from GTFS

The published dataset (CC BY 4.0) uses only coordinates from redistributable sources, so stations with neither a proxy
point nor an interpolated position have empty coordinates. GTFS stops require lat/lon, so they are removed, starting with what loses
the least information:
  (1) stops without times (intermediate stops of frequency-only sections, names only) ... that stop row is removed
  (2) intermediate stops of frequency-only template trips (trip_id TQ...) ... removed even with times, since those times
      are estimates apportioned by distance
  (3) frequency-only template trips whose end (first or last stop) has no coordinates ... the whole section is removed
      (template trip, its frequencies rows, and routes left without trips)
  (4) timed stops of ordinary trains ... not removed (times would be lost); listed in the report (to be read from
      topographic maps)
Stops without coordinates that no stop row uses any more are removed from stops.txt.

Usage (step 5.7 of run_pipeline.sh; runs only with RELEASE_DROP_COORDLESS=1, does nothing by default):
  RELEASE_DROP_COORDLESS=1  GTFS_DIR=<GTFS output folder>
Output: rewrites stops.txt, stop_times.txt, trips.txt, frequencies.txt and routes.txt in GTFS_DIR, and records what was
      removed and what could not be removed ((4)) in GTFS_DIR/coordless_stops_report.csv.
"""
import csv
import io
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_gd = os.environ.get('GTFS_DIR', 'gtfs_v1')
GTFS = _gd if os.path.isabs(_gd) else os.path.join(BASE, 'data', _gd)


def read(name):
    p = os.path.join(GTFS, name)
    if not os.path.exists(p):
        return None, []
    with open(p, encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames or []), list(rd)


def write(name, fields, rows):
    buf = io.StringIO(newline='')
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator='\n')
    w.writeheader()
    w.writerows(rows)
    with open(os.path.join(GTFS, name), 'w', encoding='utf-8', newline='') as f:
        f.write(buf.getvalue())


def main():
    if os.environ.get('RELEASE_DROP_COORDLESS', '0') != '1':
        return
    sf, stops = read('stops.txt')
    coordless = {s['stop_id']: s for s in stops
                 if (s.get('location_type') or '0') in ('', '0') and not (s.get('stop_lat') or '').strip()}
    tf, stop_times = read('stop_times.txt')
    by_trip = defaultdict(list)
    for i, r in enumerate(stop_times):
        by_trip[r['trip_id']].append(i)
    drop_rows, drop_trips = set(), set()
    report = []
    for trip, idxs in by_trip.items():
        idxs = sorted(idxs, key=lambda i: int(stop_times[i]['stop_sequence']))
        last = len(idxs) - 1
        for pos, i in enumerate(idxs):
            r = stop_times[i]
            if r['stop_id'] not in coordless:
                continue
            timed = bool((r.get('arrival_time') or '').strip() or (r.get('departure_time') or '').strip())
            endpoint = pos in (0, last)
            nm = coordless[r['stop_id']].get('stop_name', '')
            if trip.startswith('TQ'):
                if endpoint:
                    drop_trips.add(trip)
                    report.append([trip, r['stop_id'], nm, r['stop_sequence'], '区画ごと外した（端の座標が無い）'])
                else:
                    drop_rows.add(i)
                    report.append([trip, r['stop_id'], nm, r['stop_sequence'], '途中の停留場を外した' + ('（推定の時刻あり）' if timed else '')])
            elif not timed and not endpoint:
                drop_rows.add(i)
                report.append([trip, r['stop_id'], nm, r['stop_sequence'], '時刻の無い停車を外した'])
            else:
                report.append([trip, r['stop_id'], nm, r['stop_sequence'], '★外せない（時刻のある停車）＝地形図で読む'])
    kept = [r for i, r in enumerate(stop_times) if i not in drop_rows and r['trip_id'] not in drop_trips]
    write('stop_times.txt', tf, kept)
    trf, trips = read('trips.txt')
    trips2 = [t for t in trips if t['trip_id'] not in drop_trips]
    write('trips.txt', trf, trips2)
    ff, freqs = read('frequencies.txt')
    if ff is not None:
        write('frequencies.txt', ff, [x for x in freqs if x['trip_id'] not in drop_trips])
    used_routes = {t['route_id'] for t in trips2}
    rf, routes = read('routes.txt')
    removed_routes = [r['route_id'] for r in routes if r['route_id'] not in used_routes and r['route_id'].startswith('RQ')]
    write('routes.txt', rf, [r for r in routes if r['route_id'] not in removed_routes])
    used_stops = {r['stop_id'] for r in kept}
    removed_stops = [s['stop_id'] for s in stops if s['stop_id'] in coordless and s['stop_id'] not in used_stops]
    write('stops.txt', sf, [s for s in stops if s['stop_id'] not in removed_stops])
    buf = io.StringIO(newline='')
    w = csv.writer(buf, lineterminator='\r\n')
    w.writerow(['trip_id', 'stop_id', 'stop_name', 'stop_sequence', '処置'])
    w.writerows(report)
    with open(os.path.join(GTFS, 'coordless_stops_report.csv'), 'wb') as f:
        f.write(b'\xef\xbb\xbf' + buf.getvalue().encode('utf-8'))
    cannot = sum(1 for x in report if x[4].startswith('★'))
    print(f'drop_coordless_stops: 座標の無い停留場 {len(coordless)} → 停車の行を {len(drop_rows)} 外し・区画（雛形便）を {len(drop_trips)} 外し'
          f'（路線 {len(removed_routes)}）・stops.txt から {len(removed_stops)} 外した／★外せない時刻のある停車 {cannot}'
          f'（{os.path.join(GTFS, "coordless_stops_report.csv")}）')


if __name__ == '__main__':
    sys.exit(main())
