#!/usr/bin/env python3
"""
Earliest-arrival journey search on the 1925 Japanese timetable GTFS (standard library only).

    python3 examples/route_1925.py 東京 下關 08:00
    python3 examples/route_1925.py 東京 哈爾賓〈滿洲〉 08:00 --days 5
    python3 examples/route_1925.py --list 高田          # show stations whose name contains 高田, with their lines

What it does (a minimal Connection Scan, Dibbelt et al. 2013):
  * Stations are the parent stations in stops.txt (location_type=1). A station name may match
    several stations far apart (e.g. 高田); all of them are used as origin/destination, and the
    one actually used is printed: each ride shows its line, and walks and --list show the lines of
    the stops (高田（信越本線）), so that stations of the same name can be told apart.
  * Transfers come from transfers.txt (0 min inside a station; 1-13 min on foot between nearby
    stations, and up to 39 min between stations of the same name that stand apart). There is no
    other walking, and two walks are never joined: a walk starts where a train (or the journey)
    arrives, including a later train than the first arrival at that stop.
  * A journey never comes back to a station where it has already got on or off (or walked to):
    a traveller would rather wait there. Stations that a train passes without the traveller
    getting off do not count, so riding an express past a station and coming back on a local
    train is allowed.
  * The timetable is treated as repeating every day (calendar.txt: every day of 1925-03-28 to
    1925-04-30); this script does not read the calendar. Times after 24:00 belong to trips that
    started on an earlier day, so each trip is also run as many days earlier as the longest trip
    lasts, and up to --days days later. Services printed with specific operating days
    (extras/operating_days.csv) are also run every day.
  * frequencies.txt ("此間N分毎ニ運轉" boxes and frequency-only services) is expanded into
    individual departures, as the GTFS specification defines. Those runs are marked "(estimated)".
    Arrival times listed in extras/estimated_stop_times.csv are marked the same way.
  * Consecutive legs listed under the same physical_train_id in extras/physical_trains.csv are one
    through train (the printed timetable shows a single train crossing a line boundary, but the feed
    has one trip per line) and are not counted as a transfer. The next trip of a through train usually
    leaves from another stop of the same station (each line has its own stop); boarding it there
    continues the train.
  * Among journeys that arrive at the same time, one with fewer transfers is preferred: a train is
    boarded again at a later stop when that saves a transfer (waiting at a station rather than riding
    out and back), a through train is continued rather than changed for another train that arrives at
    the same time, and at the destination an equally early arrival with fewer transfers is taken. The
    search keeps one way of reaching each stop, so it does not always find the fewest transfers.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

DAY = 1440
HERE = os.path.dirname(os.path.abspath(__file__))


def read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def to_min(t):
    if not t:
        return None
    h, m, _ = t.split(':')
    return int(h) * 60 + int(m)


def fmt(t):
    d, r = divmod(t, DAY)
    tag = '' if d == 0 else (f' (+{d} day)' if d == 1 else f' (+{d} days)' if d > 0 else f' ({d} day)')
    return f'{r // 60:02d}:{r % 60:02d}{tag}'


class Timetable:
    def __init__(self, gtfs_dir, extras_dir=None):
        stops = read(os.path.join(gtfs_dir, 'stops.txt'))
        self.name = {s['stop_id']: s['stop_name'] for s in stops}
        self.parent = {}
        self.children = defaultdict(list)
        self.stations = {}
        for s in stops:
            if s.get('location_type') == '1':
                self.stations[s['stop_id']] = s['stop_name']
            elif s.get('parent_station'):
                self.parent[s['stop_id']] = s['parent_station']
                self.children[s['parent_station']].append(s['stop_id'])
        self.transfers = defaultdict(list)
        tp = os.path.join(gtfs_dir, 'transfers.txt')
        if os.path.exists(tp):
            for r in read(tp):
                self.transfers[r['from_stop_id']].append((r['to_stop_id'], int(r['min_transfer_time'] or 0) // 60))
        routes = {r['route_id']: r['route_short_name'] for r in read(os.path.join(gtfs_dir, 'routes.txt'))}
        self.trip = {}
        for t in read(os.path.join(gtfs_dir, 'trips.txt')):
            self.trip[t['trip_id']] = {'line': routes[t['route_id']], 'number': t.get('trip_short_name', ''),
                                       'block': ''}
        if extras_dir and os.path.exists(os.path.join(extras_dir, 'physical_trains.csv')):
            for r in read(os.path.join(extras_dir, 'physical_trains.csv')):
                if r['trip_id'] in self.trip:
                    self.trip[r['trip_id']]['block'] = r['physical_train_id']
        rows = defaultdict(list)
        self.lines = defaultdict(set)          # stop_id -> names of the lines whose trips call there
        for r in read(os.path.join(gtfs_dir, 'stop_times.txt')):
            rows[r['trip_id']].append(r)
            if r['trip_id'] in self.trip:
                self.lines[r['stop_id']].add(self.trip[r['trip_id']]['line'])
        for v in rows.values():
            v.sort(key=lambda r: int(r['stop_sequence']))
        est = set()
        if extras_dir and os.path.exists(os.path.join(extras_dir, 'estimated_stop_times.csv')):
            for r in read(os.path.join(extras_dir, 'estimated_stop_times.csv')):
                est.add((r['trip_id'], r['stop_sequence']))
        freq = defaultdict(list)
        fp = os.path.join(gtfs_dir, 'frequencies.txt')
        if os.path.exists(fp):
            for r in read(fp):
                freq[r['trip_id']].append(r)
        # Some trips run for several days (some times are past 100:00); a trip that started k days
        # ago still serves today, so each trip is also run up to `span` days earlier.
        self.span = max((max(to_min(r['departure_time']) or 0, to_min(r['arrival_time']) or 0)
                         for v in rows.values() for r in v), default=0) // DAY
        # A "run" = one departure of one trip: (run_id, trip_id, offset_minutes, estimated)
        self.patterns = []       # (trip_id, [(stop_id, arr, dep, estimated_row)], estimated_run)
        for tid, rs in rows.items():
            timed = [(r['stop_id'], to_min(r['arrival_time']), to_min(r['departure_time']),
                      (tid, r['stop_sequence']) in est) for r in rs
                     if r['arrival_time'] or r['departure_time']]
            if len(timed) < 2:
                continue
            if tid in freq:
                base = timed[0][2] if timed[0][2] is not None else timed[0][1]
                for f in freq[tid]:
                    start, end, head = to_min(f['start_time']), to_min(f['end_time']), int(f['headway_secs']) // 60
                    t = start
                    while t < end and head > 0:
                        self.patterns.append((tid, [(s, a + t - base if a is not None else None,
                                                     d + t - base if d is not None else None, e)
                                                    for s, a, d, e in timed], True))
                        t += head
            else:
                self.patterns.append((tid, timed, False))

    def find(self, name):
        exact = [g for g, n in self.stations.items() if n == name]
        if exact:
            return exact
        # a child stop may carry the name (stations are named after one of their stops)
        via_child = sorted({self.parent[s] for s, n in self.name.items() if n == name and s in self.parent})
        if via_child:
            return via_child
        base = name.split('〈')[0]
        return sorted({self.parent.get(s, s) for s, n in self.name.items()
                       if n.split('〈')[0] == base and s in self.parent})

    def connections(self, days):
        if getattr(self, '_conns', (None,))[0] == days:      # reuse across searches
            return self._conns[1]
        conns = []
        for run, (tid, timed, est_run) in enumerate(self.patterns):
            for day in range(-self.span, days):
                off = day * DAY
                for (a, _, dep, _), (b, arr, _, e) in zip(timed, timed[1:]):
                    if dep is None or arr is None:
                        continue
                    conns.append((dep + off, arr + off, a, b, (run, day), tid, est_run or e))
        conns.sort(key=lambda c: (c[0], c[1]))
        self._conns = (days, conns)
        return conns

    def search(self, origins, destinations, t0, days=5):
        INF = float('inf')
        best = defaultdict(lambda: INF)       # earliest arrival by any means (a train may be boarded from here)
        how = {}
        # Walks are not chained, so they start from the earliest arrival *by train* (or the start), which is
        # kept apart: a station first reached on foot must still pass on a later train arrival to its
        # neighbours on foot.
        best_ride = defaultdict(lambda: INF)
        how_ride = {}
        on = {}                          # run -> the connection where it was boarded
        been = {}                        # run -> stations where that journey already got on or off
        # Transfers so far, used only to choose among journeys with the same arrival time: a run is boarded
        # again at a later stop when that saves a transfer, and at the destination an equally early arrival
        # with fewer transfers is preferred. Riding the first train counts 0; a through train (the same
        # physical_train_id) does not count.
        tr_at, blk_at, tr_ride, tr_board = {}, {}, {}, {}
        # Each line has its own stop, so a through train usually continues from another stop of the same
        # station: the train of the earliest ride arrival at each stop is kept, and a boarding that continues it
        # remembers that stop (via) so that the journey is traced back along the through train.
        blk_ride, via = {}, {}
        dest_stops = {s for g in destinations for s in self.children[g]}

        target = INF

        def station(s):
            return self.parent.get(s, s)

        def stations_of(s, by_ride=False):
            """Stations where the journey that reaches stop `s` got on or off (or walked to); with by_ride, the
            journey of the earliest ride arrival at `s`."""
            out, h = {station(s)}, ('arrive',) if by_ride else how[s]
            while True:
                if h[0] == 'walk':
                    s = h[1]
                    out.add(station(s))
                    h = ('arrive',)
                    continue
                h = how_ride[s]
                if h[0] == 'start':
                    return out
                if h[3] is not None:             # boarded where the through train arrived at another stop
                    s = h[3]
                    out.add(station(s))
                    h = ('arrive',)
                    continue
                s = h[1][2]
                out.add(station(s))
                h = how[s]

        def board_tr(a, tid, dep):
            """Transfers so far when trip `tid` is boarded at stop `a`, and the stop where the same through
            train arrived if the boarding continues it from another stop of the station (else None)."""
            blk, prev = self.trip[tid]['block'], blk_at.get(a)
            if prev == 'START':
                return 0, None
            if blk and prev == blk:
                return tr_at[a], None
            if blk:
                cont = sorted((tr_ride[k], k) for k in self.children.get(station(a)) or [a]
                              if k != a and blk_ride.get(k) == blk and best_ride[k] <= dep)
                if cont and cont[0][0] < tr_at[a] + 1:
                    return cont[0]
            return tr_at[a] + 1, None

        def reach(stop, t, via, seen, tr, blk):
            nonlocal target
            if t < best_ride[stop] or (stop in dest_stops and t == best_ride[stop] and tr < tr_ride[stop]):
                best_ride[stop] = t
                how_ride[stop] = via
                tr_ride[stop] = tr
                blk_ride[stop] = blk if blk != 'START' else None
                if t < best[stop] or (stop in dest_stops and t == best[stop] and tr < tr_at.get(stop, INF)):
                    best[stop] = t
                    how[stop] = ('arrive',)
                    tr_at[stop], blk_at[stop] = tr, blk
                    if stop in dest_stops:
                        target = min(target, t)
                for s2, mins in self.transfers.get(stop, []):
                    if station(s2) != station(stop) and station(s2) in seen:
                        continue                         # never walk back to a station already got on or off at
                    if t + mins < best[s2] or (s2 in dest_stops and t + mins == best[s2]
                                               and tr < tr_at.get(s2, INF)):
                        best[s2] = t + mins
                        how[s2] = ('walk', stop, t, mins)
                        tr_at[s2], blk_at[s2] = tr, None
                        if s2 in dest_stops:            # the journey may end with a short walk
                            target = min(target, t + mins)
        for g in origins:
            for s in self.children[g]:
                reach(s, t0, ('start',), {station(s)}, 0, 'START')
        for c in self.connections(days):
            dep, arr, a, b, run, tid, est = c
            if dep >= target:
                break
            if run in on or best[a] <= dep:
                if run not in on:
                    tr_board[run], via[run] = board_tr(a, tid, dep)
                    on[run] = c
                    been[run] = stations_of(via[run], True) if via[run] else stations_of(a)
                elif best[a] <= dep:
                    tr_a, via_a = board_tr(a, tid, dep)
                    if tr_a < tr_board[run]:
                        # the same run can be boarded here with fewer transfers (e.g. waiting at a station
                        # instead of riding out and back); only if no more stations become forbidden
                        been_a = stations_of(via_a, True) if via_a else stations_of(a)
                        if been_a <= been[run] | {station(a)}:
                            on[run], been[run], tr_board[run], via[run] = c, been_a, tr_a, via_a
                if (arr < best_ride[b] or (b in dest_stops and arr == best_ride[b])) \
                        and station(b) not in been[run]:   # never get off where already been
                    reach(b, arr, ('ride', on[run], c, via[run]), been[run] | {station(b)}, tr_board[run],
                          self.trip[tid]['block'] or None)
        if target == INF:
            return None
        end = min(dest_stops, key=lambda s: best[s])
        legs, s, h = [], end, how[end]
        while True:
            if h[0] == 'walk':                   # the walk left `h[1]` right after a train arrived there
                legs.append(('walk', h[1], s, h[2], h[3]))
                s = h[1]
                h = ('arrive',)
                continue
            h = how_ride[s]
            if h[0] == 'start':
                break
            c0, c1 = h[1], h[2]
            legs.append(('ride', c0, c1))
            s = c0[2]
            if h[3] is not None:                 # the through train arrived at another stop of this station
                legs.append(('walk', h[3], s, best_ride[h[3]], 0))
                s = h[3]
                h = ('arrive',)
                continue
            h = how[s]
        return list(reversed(legs)), best[end]

    def label(self, stop):
        """A stop's name with the line(s) it belongs to, so that stations of the same name can be told apart."""
        ls = '・'.join(sorted(self.lines.get(stop, ())))
        return f'{self.name[stop]}（{ls}）' if ls else self.name[stop]

    def show(self, legs):
        out, prev_block, n_transfer, first = [], None, 0, True
        for leg in legs:
            if leg[0] == 'walk':
                _, a, b, t, mins = leg
                if self.parent.get(a) != self.parent.get(b):
                    out.append(f'  walk {mins} min: {self.label(a)} -> {self.label(b)}')
                continue
            c0, c1 = leg[1], leg[2]
            info = self.trip[c0[5]]
            number = f'{info["number"]}号' if info['number'].isdigit() else (info['number'] or 'no number')
            est = ' (estimated)' if c0[6] or c1[6] else ''
            through = info['block'] and info['block'] == prev_block
            if not first and not through:
                n_transfer += 1
            label = 'through' if through else 'ride'
            out.append(f'  {label}: {info["line"]} {number}{est}  '
                       f'{self.name[c0[2]]} {fmt(c0[0])} -> {self.name[c1[3]]} {fmt(c1[1])}')
            prev_block, first = info['block'], False
        return out, n_transfer


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('origin', nargs='?')
    ap.add_argument('destination', nargs='?')
    ap.add_argument('time', nargs='?', default='08:00', help='departure time HH:MM (the timetable repeats every day)')
    ap.add_argument('--days', type=int, default=5, help='how many days the journey may take (default 5)')
    ap.add_argument('--gtfs', default=os.path.join(HERE, '..', 'gtfs'))
    ap.add_argument('--extras', default=os.path.join(HERE, '..', 'extras'))
    ap.add_argument('--list', metavar='TEXT', help='list stations whose name contains TEXT')
    a = ap.parse_args()
    tt = Timetable(a.gtfs, a.extras)
    if a.list:
        for g, n in sorted(tt.stations.items()):
            if a.list in n or any(a.list in tt.name[s] for s in tt.children[g]):
                print(g, n, '/', '・'.join(sorted({tt.label(s) for s in tt.children[g]})))
        return 0
    if not (a.origin and a.destination):
        ap.error('origin and destination are required')
    o, d = tt.find(a.origin), tt.find(a.destination)
    for nm, gs in ((a.origin, o), (a.destination, d)):
        if not gs:
            sys.exit(f'no station named {nm} (try --list)')
    h, m = a.time.split(':')
    res = tt.search(o, d, int(h) * 60 + int(m), a.days)
    if not res:
        print(f'{a.origin} -> {a.destination}: no journey within {a.days} days')
        return 1
    legs, arr = res
    lines, n_tr = tt.show(legs)
    first_dep = next(l[1][0] for l in legs if l[0] == 'ride')
    print(f'{a.origin} -> {a.destination}  depart {fmt(first_dep)}  arrive {fmt(arr)}  '
          f'({(arr - first_dep) // 60} h {(arr - first_dep) % 60} min, {n_tr} transfer{"" if n_tr == 1 else "s"})')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
