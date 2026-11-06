"""Convert the published 1925 GTFS into a GTFS that pyraptor can read, aligned with the journey planner of
demo/route_planner so the two can be compared.

Handles pyraptor's (1.3.10) loading rules and the particulars of this GTFS.
Reference: demo/route_planner (the search core embedded in demo/route_planner/index.html). Two principles:

  - Which stops count as the same station is a definition, so the grouping is not reimplemented: station groups
    and walking links come from the same function that builds the published router data
    (scripts/release/build_release_router_data.py: parent stations and transfers.txt).
  - Expansion of frequency boxes ("此間N分毎") etc. is written here separately, following the GTFS rules
    (frequencies.txt). compare_route_planner.py matches it trip by trip against the journey planner data,
    which also checks the expansion.

Steps:
  1. Stations = station groups. pyraptor merges stops with the same stop_name into one station, so stop_name holds
     the group ID (the parent station). Transfers within a station take 0 minutes (build_timetable.py changes
     pyraptor's default 2 minutes to 0; the journey planner also uses 0).
  2. Trips in frequencies.txt (template trips of frequency boxes and frequency-only sections) are not used as is but
     expanded into time-shifted trips from start_time every headway_secs until before end_time (estimated trips).
     All stations are shifted by the same amount so the template's first time (departure at its first timed
     station) falls on start_time and so on.
  3. Stations without times (intermediate stations of frequency-only templates, names only) are dropped;
     the journey planner does not board or alight there either.
  4. pyraptor uses one day of trips only (after arriving overnight it cannot board next-day trips). The timetable
     repeats daily, so copies shifted by +24 h, +48 h, ... extend it to --days days.
     Copies for the previous day are made too (--days-before, default 1): stations written with times after 24:00
     (the second half of trips crossing midnight, or trips written a whole day later) are served "today" by trips
     that left the previous day. From the -24 h copy only stations departing after 0:00 of the search day are kept
     (earlier stations are dropped; trips with fewer than 2 stations are skipped).
     Without this, pyraptor would miss the same itineraries as the journey planner and the comparison would report
     a match (a blind spot of the comparison).
  5. pyraptor stops (assert) when times go backwards within a trip. Only those rows are raised to the previous
     station's departure; counts and original values go to _clamped.csv in the output folder. The journey planner
     reads such a time as the next day, so results may differ here.
  6. Fill in required columns (calendar_dates.txt, parent_station, integer trip_short_name, route_long_name,
     platform_code).
  7. pyraptor (RAPTOR) groups trips with the same stop sequence into one route and only checks the earliest
     departing trip at the boarding station (assuming no overtaking within a route), so it misses a trip that leaves
     later but arrives earlier. Overtaking trips are moved to another stop of the same station group (stop_id with
     #1, #2, ... appended) to form a separate route. Transfers between these stops take 0 minutes, so the stations
     and times one can board and alight do not change.

Times are not changed except in step 5. The source GTFS is never modified.

Usage (in tests/pyraptor):
  venv/bin/python make_pyraptor_gtfs.py --release ../../data/gtfs_v1_release   # writes ./gtfs_for_pyraptor/
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
import generate_router_data as grd  # noqa: E402  same functions as the journey planner data

DAY = 86400


def parse_args():
    ap = argparse.ArgumentParser(description='1925年 GTFS → pyraptor 用 GTFS（demo/route_planner とそろえる）')
    ap.add_argument('--out', default=os.path.join(HERE, 'gtfs_for_pyraptor'), help='出力先')
    # Default 7 days: the journey planner allows waits up to 48 hours, and journeys via overseas lines and ships can take 4-7 days.
    ap.add_argument('--days', type=int, default=7, help='便を何日ぶん広げるか（既定 7）')
    # Default 1 day: today's run of trips that left the previous day. 0 makes no previous-day copies.
    ap.add_argument('--days-before', type=int, default=1,
                    help='前の日の写しを何日ぶん作るか（既定 1。0 で作らない）')
    # --release <published dataset folder>. Station groups and walking links are taken as is from the function that builds
    #   the published router data (build in scripts/release/build_release_router_data.py: parent stations and transfers.txt);
    #   trip keys are gtfs_trip_key of extras/trip_source.csv (else line__direction__original number), the same as the
    #   published network (data/gtfs_v1_release_router).
    ap.add_argument('--release', required=True, help='公開版のフォルダ（gtfs/ と extras/ を読む）')
    return ap.parse_args()


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def to_sec(t):
    if not t:
        return None
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def to_hms(v):
    return f'{v // 3600:02d}:{v % 3600 // 60:02d}:{v % 60:02d}'


def main():
    a = parse_args()
    t_start = time.time()
    out = os.path.abspath(a.out)
    rel = os.path.abspath(a.release)
    gtfs = os.path.join(rel, 'gtfs')
    master = os.path.join(gtfs, 'stops.txt')     # recorded in the input md5s (stations are grouped by parent station)
    os.makedirs(out, exist_ok=True)

    agency = read_csv(os.path.join(gtfs, 'agency.txt'))
    routes = read_csv(os.path.join(gtfs, 'routes.txt'))
    trips = read_csv(os.path.join(gtfs, 'trips.txt'))
    calendar = read_csv(os.path.join(gtfs, 'calendar.txt'))
    stop_times = read_csv(os.path.join(gtfs, 'stop_times.txt'))
    freq_path = os.path.join(gtfs, 'frequencies.txt')
    freqs = read_csv(freq_path) if os.path.exists(freq_path) else []
    dates = {c['start_date'] for c in calendar}
    if len(dates) != 1:
        raise SystemExit(f'calendar.txt の start_date が 1 つではありません: {sorted(dates)}')

    rows_of_trip = defaultdict(list)
    for r in stop_times:
        rows_of_trip[r['trip_id']].append(r)
    # ---- 1. Station groups = parent stations, walking links = transfers.txt (taken as is from the published network builder) ----
    sys.path.insert(0, os.path.join(REPO, 'scripts', 'release'))
    import build_release_router_data as brd
    rdata, _rstats = brd.build(rel)
    groups = {g: {'name': v['name'], 'lat': v['lat'], 'lon': v['lon']} for g, v in rdata['groups'].items()}
    name_to_groups = rdata['name_to_groups']
    walks = rdata.get('walks', {})
    stops_info, group_of_stop = {}, {}
    for r in read_csv(master):
        if r.get('location_type') == '1':
            continue
        stops_info[r['stop_id']] = {'name': r['stop_name'], 'lat': float(r['stop_lat']), 'lon': float(r['stop_lon'])}
        group_of_stop[r['stop_id']] = r['parent_station']
    src = {r['trip_id']: r for r in read_csv(os.path.join(rel, 'extras', 'trip_source.csv'))}
    n_near = 0

    # ---- 2-3. List the timed stations of each trip; expand trips in frequencies.txt into estimated trips ----
    line_of_route = {r['route_id']: r['route_short_name'] for r in routes}
    trip_by_id = {t['trip_id']: t for t in trips}
    freq_of = defaultdict(list)
    for fr in freqs:
        freq_of[fr['trip_id']].append(fr)
    # For template trips of boxes that list only departure times at the first station (FREQ_BOX_LISTED), the journey
    #   planner puts the trip_id into the key (there is one template per trip with the same line, direction and number).
    #   Identify them with the same function and build the same key; otherwise matching stops on "day-1 trips differ"
    #   (a difference in names only).
    # In the published extras the template trip column is named trip_id (read as with_template in build_release_router_data.py)
    def _tpl(p):
        return [{**r, 'template_trip_id': r.get('trip_id', '')} for r in read_csv(p)] if os.path.exists(p) else None
    _lab, listed_tf = grd.load_freq_labels(_tpl(os.path.join(rel, 'extras', 'frequency_box.csv')),
                                           _tpl(os.path.join(rel, 'extras', 'frequency_sections.csv')))
    cnt = defaultdict(int)
    day1 = []
    for tid, rows in rows_of_trip.items():
        t = trip_by_id.get(tid)
        if t is None:
            cnt['trips.txt に無い便'] += 1
            continue
        line = line_of_route.get(t['route_id'], '')
        direction = 'outbound' if t.get('direction_id') == '0' else 'inbound'
        s = src.get(tid, {})    # trip_short_name holds only printed numbers, so take the original number and the key from extras
        num = s.get('original_trip_short_name') or t.get('trip_short_name', '')
        key = s.get('gtfs_trip_key') or f'{line}__{direction}__{num}'   # built like the journey planner's k (used for matching in compare_route_planner.py)
        timed = []
        for r in sorted(rows, key=lambda x: int(x['stop_sequence'])):
            if r['stop_id'] not in group_of_stop:
                cnt['駅グループに無い乗り場の行（落とした）'] += 1
                continue
            arr, dep = to_sec(r['arrival_time']), to_sec(r['departure_time'])
            if arr is None and dep is None:
                cnt['時刻の無い行（落とした）'] += 1
                continue
            timed.append([r['stop_id'], arr if arr is not None else dep, dep if dep is not None else arr])
        if not timed:
            continue
        base = {'route_id': t['route_id'], 'service_id': t['service_id'],
                'line': line, 'direction': direction, 'num': num}
        if tid not in freq_of:
            day1.append({**base, 'id': tid, 'key': key, 'est': 0, 'label': f'{line} {num}', 'stops': timed})
            continue
        cnt['雛形便（そのままは使わない）'] += 1
        t0 = timed[0][2]
        k = 0
        for fr in freq_of[tid]:
            start, end, hw = to_sec(fr['start_time']), to_sec(fr['end_time']), int(fr['headway_secs'])
            d = start
            while d < end and hw > 0:
                k += 1
                shift = d - t0
                day1.append({**base, 'id': f'{tid}_f{k}',
                             'key': f'{key}_{tid}_freq{k}' if tid in listed_tf else f'{key}_freq{k}', 'est': 1,
                             'label': f'{line} {hw // 60}分毎（推定）',
                             'stops': [[s, x + shift, y + shift] for s, x, y in timed]})
                cnt['推定便'] += 1
                d += hw

    # ---- 5. Raise rows whose time goes backwards within a trip to the previous departure (avoids pyraptor's assert) ----
    clamped = []
    for tr in day1:
        prev = None
        for i, st in enumerate(tr['stops']):
            sid, arr, dep = st
            na = prev if prev is not None and arr < prev else arr
            nd = na if dep < na else dep
            if (na, nd) != (arr, dep):
                clamped.append([tr['id'], tr['key'], i + 1, sid, stops_info[sid]['name'],
                                to_hms(arr), to_hms(dep), to_hms(na), to_hms(nd)])
                st[1], st[2] = na, nd
            prev = nd
    usable = [tr for tr in day1 if len(tr['stops']) >= 2]
    cnt['駅が 1 つだけの便（pyraptor に入れない）'] = len(day1) - len(usable)
    cnt['同じ乗り場を 2 回通る便'] = sum(1 for tr in usable if len({s for s, _, _ in tr['stops']}) < len(tr['stops']))

    # ---- 4. Copy for --days days (plus --days-before days of previous-day copies) ----
    #   Previous-day copies (d < 0) keep only stations departing after 0:00 of the search day (an arrival before 0:00
    #   is moved to 0:00). Trips with fewer than 2 stations are skipped.
    copies = []   # [trip_id, trip, day (..., -1, 0, 1, ...), [[stop, arrival, departure], ...]]
    n_prev, n_prev_dropped = 0, 0
    for d in range(-a.days_before, a.days):
        for tr in usable:
            stops = [[s, x + d * DAY, y + d * DAY] for s, x, y in tr['stops']]
            if d < 0:
                stops = [[s, max(x, 0), y] for s, x, y in stops if y >= 0]
                if len(stops) < 2:
                    n_prev_dropped += 1
                    continue
                n_prev += 1
            tid = tr['id'] + ('' if d == 0 else (f'_d{d + 1}' if d > 0 else f'_dm{-d}'))
            copies.append([tid, tr, d, stops])
    cnt['前の日の写しに入れた便（0 時より後に 2 駅以上）'] = n_prev
    cnt['前の日の写しで入れなかった便'] = n_prev_dropped

    # ---- 7. Remove overtaking within a stop sequence by moving trips to other stops (all day copies together) ----
    #   Per sequence, sort by first departure and put each trip into the first route whose last trip it does not
    #   precede at any station (arrival and departure); otherwise start a new route (#1, #2, ...).
    #   Within every route, consecutive trips are then in order at all stations (no overtaking).
    by_pattern = defaultdict(list)
    for c in copies:
        by_pattern[tuple(s for s, _, _ in c[3])].append(c)
    n_split_patterns = n_platform_trips = 0
    extra_stops = set()
    for cs in by_pattern.values():
        cs.sort(key=lambda c: (c[3][0][2], c[3][-1][1]))
        lasts = []
        for c in cs:
            times = [(x, y) for _, x, y in c[3]]
            b = next((i for i, last in enumerate(lasts)
                      if all(la <= x and ld <= y for (la, ld), (x, y) in zip(last, times))), len(lasts))
            if b == len(lasts):
                lasts.append(times)
            else:
                lasts[b] = times
            if b:
                for st in c[3]:
                    st[0] = f'{st[0]}#{b}'
                    extra_stops.add(st[0])
                n_platform_trips += 1
        if len(lasts) > 1:
            n_split_patterns += 1

    # ---- 6. Write the files ----
    write_csv(os.path.join(out, 'agency.txt'), list(agency[0].keys()), [list(r.values()) for r in agency])
    write_csv(os.path.join(out, 'routes.txt'),
              ['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_type'],
              [[r['route_id'], r['agency_id'], r['route_short_name'],
                r.get('route_long_name') or r['route_short_name'], r['route_type']] for r in routes])
    write_csv(os.path.join(out, 'calendar_dates.txt'), ['service_id', 'date', 'exception_type'],
              [[c['service_id'], c['start_date'], 1] for c in calendar])
    trip_rows, st_rows = [], []
    for tid, tr, d, stops in copies:
        m = re.match(r'^(\d+)', tr['num'])
        # pyraptor's Trip does not keep the GTFS trip_id, so put the trip ID into trip_long_name for displaying itineraries
        trip_rows.append([tr['route_id'], tr['service_id'], tid, m.group(1) if m else '', tid,
                          tr['key'], tr['line'], tr['direction'], tr['num'], tr['est'], tr['label'], d + 1])
        for i, (sid, x, y) in enumerate(stops):
            st_rows.append([tid, to_hms(x), to_hms(y), sid, i + 1])
    write_csv(os.path.join(out, 'trips.txt'),
              ['route_id', 'service_id', 'trip_id', 'trip_short_name', 'trip_long_name',
               'router_key', 'line_name', 'direction', 'num', 'est', 'label', 'day'], trip_rows)
    write_csv(os.path.join(out, 'stop_times.txt'),
              ['trip_id', 'arrival_time', 'departure_time', 'stop_id', 'stop_sequence'], st_rows)
    all_stops = sorted({s for tr in usable for s, _, _ in tr['stops']}) + sorted(extra_stops)
    stop_rows = []
    for s in all_stops:
        info, g = stops_info[s.split('#')[0]], group_of_stop[s.split('#')[0]]
        stop_rows.append([s, s, g, '' if info['lat'] is None else info['lat'],
                          '' if info['lon'] is None else info['lon'], g, s])
    write_csv(os.path.join(out, 'stops.txt'),
              ['stop_id', 'stop_code', 'stop_name', 'stop_lat', 'stop_lon', 'parent_station', 'platform_code'],
              stop_rows)
    write_csv(os.path.join(out, '_clamped.csv'),
              ['trip_id', 'router_key', 'stop_sequence', 'stop_id', 'stop_name',
               'arrival_before', 'departure_before', 'arrival_after', 'departure_after'], clamped)

    md5s = {n: md5(os.path.join(gtfs, n)) for n in
            ('agency.txt', 'calendar.txt', 'routes.txt', 'trips.txt', 'stop_times.txt', 'stops.txt', 'frequencies.txt')
            if os.path.exists(os.path.join(gtfs, n))}
    md5s['stops_master.csv'] = md5(master)
    meta = {
        'created': time.strftime('%Y-%m-%d %H:%M:%S'),
        'inputs': {'gtfs': gtfs, 'stops_master': master, 'md5': md5s},
        'days': a.days,
        'days_before': a.days_before,
        'date': dates.pop(),
        'agency_names': sorted({r['agency_name'] for r in agency}),
        # journey planner rules (generate_router_data.py) in effect for this conversion (set by environment variables)
        'router_rules': {'ROUTER_GROUP_NORMALIZE': grd.GROUP_NORMALIZE, 'ROUTER_GROUP_NEAR': grd.GROUP_NEAR,
                         'ROUTER_GROUP_NEAR_M': grd.GROUP_NEAR_M,
                         'ROUTER_EST_SAME_GROUP_COLLAPSE': grd.EST_SAME_GROUP_COLLAPSE},
        'counts': {'1日目の便': len(usable), '1日目の停車': sum(len(tr['stops']) for tr in usable),
                   '駅グループ': len(groups), '近接で併合した組': n_near,
                   '徒歩の辺（片方向の対）': sum(len(v) for v in walks.values()) // 2,
                   '繰り上げた行': len(clamped), **cnt,
                   '追い越しがあって分けた乗り場の並び': n_split_patterns,
                   '別の乗り場へ移した便（全日ぶん）': n_platform_trips},
        'groups': {g: [v['name'], v['lat'], v['lon']] for g, v in groups.items()},
        'walks': walks,
        'name_to_groups': name_to_groups,
        'stop_names': {s: stops_info[s.split('#')[0]]['name'] for s in all_stops},
    }
    with open(os.path.join(out, '_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    print(f'入力: {gtfs}')
    print(f'      {master}')
    for k, v in meta['counts'].items():
        print(f'  {k}: {v}')
    print(f'出力: {out}（{a.days} 日ぶん＋前の日 {a.days_before} 日・便 {len(trip_rows)}・停車 {len(st_rows)}）  '
          f'{time.time() - t_start:.0f} 秒')


if __name__ == '__main__':
    main()
