#!/usr/bin/env python3
"""
Ask a running OpenTripPlanner server for journeys on this feed (standard library only).

Run in examples/opentripplanner/ of the dataset:

    python3 plan_with_otp.py 東京 下關 08:00
    python3 plan_with_otp.py 東京 哈爾賓〈滿洲〉 08:00
    python3 plan_with_otp.py --list 高田      # stations whose name contains 高田

Start the server first (see README.md in this folder). Station names are looked up in the dataset's
gtfs/stops.txt (parent stations). A name that matches several stations (e.g. 高田) is tried for each
of them, and every journey shows the stations used, with their ids. Times are the printed timetable
times (Japan time); "(+1 day)" counts days from --date.

Options:
  --date 1925-04-01            service day (any day of calendar.txt: every service runs every day)
  --window PT24H               how long after TIME OpenTripPlanner looks for departures (ISO 8601)
  --first 3                    journeys to show: earliest arrival first, then fewer transfers, then later departure
  --url http://localhost:8080  the server
  --feed J1925                 feedId given in build-config.json
  --gtfs PATH                  the gtfs/ folder (default: the one of this dataset)
"""
import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))

QUERY = """
query($o: String!, $d: String!, $t: OffsetDateTime!, $w: Duration, $n: Int) {
  planConnection(
    origin: {location: {stopLocation: {stopLocationId: $o}}}
    destination: {location: {stopLocation: {stopLocationId: $d}}}
    dateTime: {earliestDeparture: $t}
    searchWindow: $w
    first: $n
    modes: {transitOnly: true}
  ) {
    routingErrors { code description }
    edges { node {
      start end numberOfTransfers
      legs { mode duration
             from { name } to { name }
             start { scheduledTime } end { scheduledTime }
             route { shortName } trip { tripShortName } }
    } }
  }
}
"""


def read_stations(gtfs_dir):
    """Parent stations {id: name} and, for each, the names of its stops."""
    stations, children = {}, {}
    with open(os.path.join(gtfs_dir, 'stops.txt'), encoding='utf-8-sig', newline='') as f:
        for s in csv.DictReader(f):
            if s.get('location_type') == '1':
                stations[s['stop_id']] = s['stop_name']
            elif s.get('parent_station'):
                children.setdefault(s['parent_station'], set()).add(s['stop_name'])
    return stations, children


def find(stations, children, name):
    """Station ids for a typed name: exact station name, else a stop of that name, else the name without its 〈region〉 tag."""
    exact = [g for g, n in stations.items() if n == name]
    if exact:
        return exact
    via_child = sorted(g for g, names in children.items() if name in names)
    if via_child:
        return via_child
    base = name.split('〈')[0]
    return sorted(g for g, n in stations.items() if n.split('〈')[0] == base)


def ask(url, variables):
    req = urllib.request.Request(url.rstrip('/') + '/otp/gtfs/v1',
                                 data=json.dumps({'query': QUERY, 'variables': variables}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def fmt(iso, day0):
    """'1925-04-02T08:05:00+09:00' -> '08:05 (+1 day)' counted from day0."""
    t = datetime.fromisoformat(iso)
    d = (t.date() - day0).days
    tag = '' if d == 0 else (' (+1 day)' if d == 1 else f' (+{d} days)')
    return f'{t:%H:%M}{tag}', t


def show(it, day0):
    dep, t0 = fmt(it['start'], day0)
    arr, t1 = fmt(it['end'], day0)
    mins = int((t1 - t0).total_seconds() // 60)
    lines = [f'{it["o_label"]} -> {it["d_label"]}  depart {dep}  arrive {arr}  '
             f'({mins // 60} h {mins % 60} min, {it["numberOfTransfers"]} transfer{"" if it["numberOfTransfers"] == 1 else "s"})']
    for leg in it['legs']:
        a, b = leg['from']['name'], leg['to']['name']
        if leg['mode'] == 'WALK':
            if a == b and leg['duration'] < 60:      # a change of stop inside one station
                continue
            lines.append(f'  walk {round(leg["duration"] / 60)} min: {a} -> {b}')
            continue
        number = (leg.get('trip') or {}).get('tripShortName') or ''
        number = f'{number}号' if number.isdigit() else (number or 'no number')
        lines.append(f'  ride: {leg["route"]["shortName"]} {number}  '
                     f'{a} {fmt(leg["start"]["scheduledTime"], day0)[0]} -> {b} {fmt(leg["end"]["scheduledTime"], day0)[0]}')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('origin', nargs='?')
    ap.add_argument('destination', nargs='?')
    ap.add_argument('time', nargs='?', default='08:00', help='departure time HH:MM')
    ap.add_argument('--date', default='1925-04-01', help='service day (default 1925-04-01)')
    ap.add_argument('--window', default='PT24H', help='search window after TIME (default PT24H)')
    ap.add_argument('--first', type=int, default=3, help='journeys to show (default 3)')
    ap.add_argument('--url', default='http://localhost:8080')
    ap.add_argument('--feed', default='J1925', help='feedId in build-config.json (default J1925)')
    ap.add_argument('--gtfs', default=os.path.join(HERE, '..', '..', 'gtfs'))
    ap.add_argument('--list', metavar='TEXT', help='list stations whose name contains TEXT')
    a = ap.parse_args()
    stations, children = read_stations(a.gtfs)
    if a.list:
        for g, n in sorted(stations.items(), key=lambda kv: kv[1]):
            if a.list in n or any(a.list in c for c in children.get(g, ())):
                print(g, n, '/', '・'.join(sorted(children.get(g, ()))))
        return 0
    if not (a.origin and a.destination):
        ap.error('origin and destination are required')
    o, d = find(stations, children, a.origin), find(stations, children, a.destination)
    for nm, gs in ((a.origin, o), (a.destination, d)):
        if not gs:
            sys.exit(f'no station named {nm} (try --list)')
    day0 = date.fromisoformat(a.date)
    t_iso = f'{a.date}T{a.time}:00+09:00'
    found, errors = [], []
    for go in o:
        for gd in d:
            try:
                r = ask(a.url, {'o': f'{a.feed}:{go}', 'd': f'{a.feed}:{gd}', 't': t_iso, 'w': a.window, 'n': a.first})
            except urllib.error.URLError as e:
                sys.exit(f'cannot reach {a.url} ({e.reason}): start the server first (see README.md)')
            if r.get('errors'):
                sys.exit('OpenTripPlanner answered with an error: ' + r['errors'][0].get('message', ''))
            plan = r['data']['planConnection']
            errors += [f'{e["code"]}: {e["description"]}' for e in plan['routingErrors']]
            for e in plan['edges']:
                it = e['node']
                it['o_label'] = f'{stations[go]} [{go}]'
                it['d_label'] = f'{stations[gd]} [{gd}]'
                found.append(it)
    if not found:
        print(f'{a.origin} -> {a.destination}: no journey found' + (' (' + '; '.join(sorted(set(errors))) + ')' if errors else ''))
        return 1
    # earliest arrival first; for the same arrival, fewer transfers, then the later departure
    found.sort(key=lambda it: (it['end'], it['numberOfTransfers'], -datetime.fromisoformat(it['start']).timestamp()))
    print('\n\n'.join(show(it, day0) for it in found[:a.first]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
