#!/usr/bin/env python3
"""
Make a GTFS feed in which services run only on the days printed in the source (standard library only).

    python3 tools/make_printed_days_gtfs.py --out gtfs_printed_days
    python3 tools/make_printed_days_gtfs.py --out gtfs_printed_days --irregular drop --include-after-period

The default feed in gtfs/ treats the April 1925 timetable as operating every day of the calendar period
(calendar.txt), because most services were printed without operating days and many tools route on a single,
freely chosen date. Services printed with specific operating days are listed in extras/ instead:

  extras/printed_sailings.csv  one row per sailing of the dated shipping tables (pp. 189-192): printed dates per port,
                               the service date, and the trip (trip_id + stop_sequences) that carries its times.
                               Sailings of different ships or companies that share the same printed times were merged
                               into one trip in gtfs/; this table keeps every sailing.
  extras/operating_days.csv    trips that do not run daily: printed_dates / monthly / alternate_days / daily_except /
                               monthly_days_not_printed / irregular.

This script rewrites the calendar accordingly:
  * printed_dates: each sailing becomes its own trip running only on its service date (calendar_dates.txt).
    A sailing of a company that has no route in gtfs/ gets a new route.
  * monthly / alternate_days / daily_except: the trip runs on the matching days of the calendar period.
  * irregular trains and sailings whose days are not printed: --irregular keep (default: every day, as in gtfs/),
    representative (the first day of April 1925 only) or drop.
  * Sailings whose service date is after the calendar period are dropped unless --include-after-period.
    Sailings without printed times (printed_sailings.csv how=no_printed_times) cannot become trips.
Everything else is copied unchanged. "Printed days" means the days printed in the source, not evidence that
a service actually ran on those days.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))


def read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def write(path, fields, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fields})


def d8(s):
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def days_of(kind, rule, start, end):
    """The dates in [start, end] on which a trip with this operating_days rule runs."""
    out, d = [], start
    while d <= end:
        last = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        ok = False
        if kind == 'monthly' and rule.startswith('day:'):
            ok = d.day in {int(x) for x in rule[4:].split(',')}
        elif kind == 'alternate_days':
            ok = (d.day % 2 == 1) if rule == 'odd' else (d.day % 2 == 0)
        elif kind == 'daily_except' and rule.startswith('except_day:'):
            skip = rule[len('except_day:'):].split(',')
            ok = not (str(d.day) in skip or ('last' in skip and d == last))
        elif kind == 'daily_except' and rule.startswith('except_weekday:'):
            ok = d.strftime('%a') not in rule[len('except_weekday:'):].split(',')
        if ok:
            out.append(d)
        d += timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--release', default=os.path.join(HERE, '..'), help='folder that holds gtfs/ and extras/')
    ap.add_argument('--out', required=True, help='folder for the new GTFS feed')
    ap.add_argument('--irregular', choices=['keep', 'representative', 'drop'], default='keep',
                    help='irregular trains and sailings whose operating days are not printed')
    ap.add_argument('--include-after-period', action='store_true',
                    help='keep sailings whose printed service date is after the calendar period')
    a = ap.parse_args()
    G, X = os.path.join(a.release, 'gtfs'), os.path.join(a.release, 'extras')
    os.makedirs(a.out, exist_ok=True)

    c_fields, cal = read(os.path.join(G, 'calendar.txt'))
    if len(cal) != 1:
        sys.exit('expected a single service in calendar.txt')
    daily = cal[0]
    start, end = d8(daily['start_date']), d8(daily['end_date'])
    t_fields, trips = read(os.path.join(G, 'trips.txt'))
    st_fields, sts = read(os.path.join(G, 'stop_times.txt'))
    r_fields, routes = read(os.path.join(G, 'routes.txt'))
    _, sailings = read(os.path.join(X, 'printed_sailings.csv'))
    _, opdays = read(os.path.join(X, 'operating_days.csv'))
    st_of = defaultdict(list)
    for r in sts:
        st_of[r['trip_id']].append(r)
    trip_of = {t['trip_id']: t for t in trips}
    route_of = {r['route_id']: r for r in routes}
    route_by_name = {}
    for r in routes:
        route_by_name.setdefault(r['route_short_name'], r['route_id'])
    kind_of = {r['trip_id']: r for r in opdays}

    new_trips, new_st, cal_dates, new_routes, dropped, notes = [], [], [], [], set(), defaultdict(int)
    services = {}

    def service(dates, tag):
        key = tuple(sorted(dates))
        if key not in services:
            sid = f'{daily["service_id"]}_{tag}' if tag else f'{daily["service_id"]}_{len(services) + 1}'
            services[key] = sid
            cal_dates.extend({'service_id': sid, 'date': f'{d:%Y%m%d}', 'exception_type': '1'} for d in key)
        return services[key]

    # printed_dates: one trip per sailing, on its own service date
    by_rep = defaultdict(list)
    for s in sailings:
        if s['trip_id'] and s['service_date']:
            by_rep[s['trip_id']].append(s)
        else:
            notes[f"sailing not made into a trip ({s['how']})"] += 1
    for rep, ss in by_rep.items():
        if rep not in trip_of:
            notes['trip carrying the printed times missing'] += len(ss)
            continue
        dropped.add(rep)
        base = trip_of[rep]
        rows = {r['stop_sequence']: r for r in st_of[rep]}
        for s in ss:
            sd = date.fromisoformat(s['service_date'])
            if sd > end and not a.include_after_period:
                notes['sailing after the calendar period (dropped)'] += 1
                continue
            rid = base['route_id']
            if route_of[rid]['route_short_name'] != s['line_name']:
                rid = route_by_name.get(s['line_name'])
                if not rid:
                    rid = f'PS{len(new_routes) + 1:03d}'
                    nr = dict(route_of[base['route_id']], route_id=rid, route_short_name=s['line_name'],
                              route_long_name='')
                    new_routes.append(nr)
                    route_by_name[s['line_name']] = rid
                    route_of[rid] = nr
            tid = f"{rep}_{s['sailing_id'].replace('#', '_')}"
            new_trips.append(dict(base, trip_id=tid, route_id=rid, trip_short_name=s['ship'],
                                  service_id=service([sd], f'{sd:%Y%m%d}')))
            for q in s['stop_sequences'].split(';'):
                new_st.append(dict(rows[q], trip_id=tid))
            notes['sailing made into a trip'] += 1

    # monthly / alternate days / daily except / irregular
    for t in trips:
        k = kind_of.get(t['trip_id'])
        if not k or k['kind'] == 'printed_dates':
            continue
        if k['kind'] in ('monthly', 'alternate_days', 'daily_except'):
            t['service_id'] = service(days_of(k['kind'], k['operating_days'], start, end), '')
            notes[f"{k['kind']} (rule applied)"] += 1
        elif a.irregular == 'drop':
            dropped.add(t['trip_id'])
            notes[f"{k['kind']} (dropped)"] += 1
        elif a.irregular == 'representative':
            t['service_id'] = service([date(1925, 4, 1)], '19250401')
            notes[f"{k['kind']} (1925-04-01 only)"] += 1
        else:
            notes[f"{k['kind']} (kept every day)"] += 1

    out_trips = [t for t in trips if t['trip_id'] not in dropped] + new_trips
    out_st = [r for r in sts if r['trip_id'] not in dropped] + new_st
    used = {t['service_id'] for t in out_trips}
    write(os.path.join(a.out, 'trips.txt'), t_fields, out_trips)
    write(os.path.join(a.out, 'stop_times.txt'), st_fields, out_st)
    write(os.path.join(a.out, 'routes.txt'), r_fields, routes + new_routes)
    write(os.path.join(a.out, 'calendar.txt'), c_fields, [daily] if daily['service_id'] in used else [])
    write(os.path.join(a.out, 'calendar_dates.txt'), ['service_id', 'date', 'exception_type'],
          [r for r in cal_dates if r['service_id'] in used])
    all_days = [d8(r['date']) for r in cal_dates if r['service_id'] in used] + ([start, end] if daily['service_id'] in used else [])
    f_fields, fi = read(os.path.join(G, 'feed_info.txt'))
    for r in fi:
        r['feed_start_date'], r['feed_end_date'] = f'{min(all_days):%Y%m%d}', f'{max(all_days):%Y%m%d}'
        r['feed_version'] = r['feed_version'] + '-printed-days'
    write(os.path.join(a.out, 'feed_info.txt'), f_fields, fi)
    # stops no longer served (e.g. a port only reached by sailings after the period) and transfers that use them
    served = {r['stop_id'] for r in out_st}
    s_fields, stops = read(os.path.join(G, 'stops.txt'))
    children = [r for r in stops if r.get('location_type', '0') in ('', '0') and r['stop_id'] in served]
    parents = {r['parent_station'] for r in children if r.get('parent_station')}
    kept_stops = children + [r for r in stops if r.get('location_type') == '1' and r['stop_id'] in parents]
    write(os.path.join(a.out, 'stops.txt'), s_fields, kept_stops)
    ids = {r['stop_id'] for r in kept_stops}
    if os.path.exists(os.path.join(G, 'transfers.txt')):
        x_fields, xs = read(os.path.join(G, 'transfers.txt'))
        write(os.path.join(a.out, 'transfers.txt'), x_fields,
              [r for r in xs if r['from_stop_id'] in ids and r['to_stop_id'] in ids])
    if os.path.exists(os.path.join(G, 'frequencies.txt')):
        q_fields, qs = read(os.path.join(G, 'frequencies.txt'))
        kept_trip_ids = {t['trip_id'] for t in out_trips}
        write(os.path.join(a.out, 'frequencies.txt'), q_fields, [r for r in qs if r['trip_id'] in kept_trip_ids])
    for name in sorted(os.listdir(G)):
        if name.endswith('.txt') and name not in ('trips.txt', 'stop_times.txt', 'routes.txt', 'calendar.txt',
                                                   'calendar_dates.txt', 'feed_info.txt', 'stops.txt',
                                                   'transfers.txt', 'frequencies.txt'):
            with open(os.path.join(G, name), 'rb') as fi_, open(os.path.join(a.out, name), 'wb') as fo:
                fo.write(fi_.read())
    if len(kept_stops) != len(stops):
        notes['stops no longer served (removed with their transfers)'] += len(stops) - len(kept_stops)
    print(f'{a.out}: trips {len(trips)} -> {len(out_trips)}, stop_times {len(sts)} -> {len(out_st)}, '
          f'new routes {len(new_routes)}, dated services {len(services)}')
    for k, v in sorted(notes.items()):
        print(f'  {v:5d}  {k}')


if __name__ == '__main__':
    main()
