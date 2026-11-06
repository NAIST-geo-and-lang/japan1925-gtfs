"""Search journeys in the 1925 GTFS with pyraptor (run after make_pyraptor_gtfs.py and build_timetable.py).

Usage (in tests/pyraptor):
  venv/bin/python query_pyraptor.py                              # the fixed set of queries
  venv/bin/python query_pyraptor.py 大阪 京城〈朝鮮〉 09:00      # one query (time as HH:MM)

Station names are resolved as in demo/route_planner: stations whose name matches exactly (all of them as candidates
when several share the name), otherwise the first of the sorted names that contain the query.
Prints the earliest arrival and its itinerary. pyraptor's search resets later rounds to empty (inf) once it has
converged, so the earliest arrival over all rounds is taken. "+1日" means the day after the search day.
compare_route_planner.py also calls search().
"""
import csv
import json
import os
import re
import sys

from loguru import logger

HERE = os.path.dirname(os.path.abspath(__file__))
GTFS_DIR = os.path.join(HERE, 'gtfs_for_pyraptor')
OUT_DIR = os.path.join(HERE, 'pyraptor_out')

logger.remove()                        # pyraptor logs INFO every round; show warnings only
logger.add(sys.stderr, level='WARNING')

import pyraptor.model.raptor as _raptor             # noqa: E402
from pyraptor.dao.timetable import read_timetable  # noqa: E402
from pyraptor.model.raptor import RaptorAlgorithm  # noqa: E402
from pyraptor.util import LARGE_NUMBER             # noqa: E402


def _copy_labels(bag):
    """Replacement for the deepcopy that pyraptor/model/raptor.py runs every round (for speed; same search steps).
    deepcopy also copies the trips and stations the labels point to (stop time lists etc.), about 20 s per search.
    The search only modifies labels (arrival time, trip, boarding stop) and only reads trips and stations,
    so only the labels are copied. Previous behavior (deepcopy) = environment variable PYRAPTOR_DEEPCOPY=1."""
    first = next(iter(bag.values()), None)
    if isinstance(first, dict):
        return {k: _copy_labels(v) for k, v in bag.items()}
    return {p: _raptor.Label(l.earliest_arrival_time, l.trip, l.from_stop) for p, l in bag.items()}


if os.environ.get('PYRAPTOR_DEEPCOPY') != '1':
    _raptor.deepcopy = _copy_labels

_accumulate_routes = RaptorAlgorithm.accumulate_routes


def _accumulate_routes_in_order(self, marked_stops):
    if not hasattr(self, '_origin_stops'):
        self._origin_stops = list(marked_stops)   # first call: stops of the origin (used by the walking initialization below)
    # pyraptor keeps marked stops in a set and scans routes in set order, which depends on Python's string hash
    # seed, so long itineraries that need more boardings than --rounds may or may not be found from run to run.
    # Sorting by stop index makes results reproducible (same work, same steps).
    return _accumulate_routes(self, sorted(marked_stops, key=lambda s: s.index))


RaptorAlgorithm.accumulate_routes = _accumulate_routes_in_order

# ------------------------------------------------------------------
# Pass the walking links (ROUTER_WALK_EDGES) to pyraptor as well
# ------------------------------------------------------------------
# pyraptor's footpath relaxation (RaptorAlgorithm.add_transfer_time) only links stops within the same station
# (that is how pyraptor.gtfs.timetable builds Transfers). The journey planner can walk to another station within
# 1 km, so without these links pyraptor cannot find itineraries that walk and the comparison would not cover them.
# Only the set of links is changed; RAPTOR's footpath relaxation itself is untouched.
#   The links come from the same function as the journey planner (generate_router_data.build_walk_edges);
#   make_pyraptor_gtfs.py puts them in `walks` of `_meta.json` (not reimplemented).
_WALK_ADJ = {}      # stop -> [(stop, seconds), ...]
_WALK_FOR = None    # timetable the links were installed for


def _set_walk_label(lbl, t, frm):
    """Record a walking arrival in the label.
    pyraptor's `Label.update()` reads `trip=None` as "unchanged", so the previously boarded trip would stay in the
    label and the reconstructed itinerary would ride that trip between the two stations
    (e.g. `關西本線 505: 難波 → 湊町`, although 505 does not stop at 難波). Clear it explicitly.
    pyraptor's own `add_transfer_time` does the same, but transfers within a station are dropped from itineraries,
    so it only shows up with walks between stations."""
    lbl.update(t, None, frm)
    lbl.trip = None


def install_walks(tt, meta):
    """Expand `walks` of `_meta.json` (station group -> [[other group, minutes], ...]) into stop-to-stop links."""
    global _WALK_ADJ, _WALK_FOR
    adj = {}
    for g, vs in (meta.get('walks') or {}).items():
        sa = tt.stations.get(g)
        if sa is None:
            continue
        for h, minutes in vs:
            sb = tt.stations.get(h)
            if sb is None:
                continue
            sec = int(minutes) * 60
            for a in sa.stops:
                adj.setdefault(a, []).extend((b, sec) for b in sb.stops)
    _WALK_ADJ, _WALK_FOR = adj, id(tt)
    return sum(len(v) for v in adj.values())


_add_transfer_time = RaptorAlgorithm.add_transfer_time


def _add_transfer_time_with_walks(self, bag_round_stop, k, marked_stops):
    """Follow the walking links first, then apply pyraptor's own within-station relaxation.
    Stops at the station walked to are also linked at 0 s (the journey planner treats a station group as one point).
    Walks are not chained (the search core embedded in demo/route_planner/index.html also forbids it via `cur.walked`)."""
    walked = []
    if _WALK_ADJ and _WALK_FOR == id(self.timetable):
        for cur in marked_stops:
            edges = _WALK_ADJ.get(cur)
            if not edges:
                continue
            t0 = bag_round_stop[k][cur].earliest_arrival_time
            for dst, sec in edges:
                t = t0 + sec
                if t < self.bag_star[dst].earliest_arrival_time:
                    _set_walk_label(bag_round_stop[k][dst], t, cur)
                    _set_walk_label(self.bag_star[dst], t, cur)
                    walked.append(dst)
    bag_round_stop, new_stops = _add_transfer_time(self, bag_round_stop, k,
                                                   list(marked_stops) + walked)
    return bag_round_stop, walked + list(new_stops)


RaptorAlgorithm.add_transfer_time = _add_transfer_time_with_walks

_traverse_routes = RaptorAlgorithm.traverse_routes


def _traverse_routes_with_origin_walks(self, bag_round_stop, k, route_marked_stops):
    """Walking from the origin. pyraptor relaxes footpaths only after a ride (`run()` applies `add_transfer_time`
    only to `marked_trip_stops`), so itineraries that start with a walk are missed
    (`鹿兒島 → 徒歩 1 分 → 停車場前 → 谷山`). Add the equivalent of RAPTOR's initial footpath step once."""
    if k == 1 and _WALK_ADJ and _WALK_FOR == id(self.timetable):
        extra = []
        for cur in getattr(self, '_origin_stops', []):
            t0 = bag_round_stop[0][cur].earliest_arrival_time
            for dst, sec in _WALK_ADJ.get(cur, ()):
                t = t0 + sec
                if t < self.bag_star[dst].earliest_arrival_time:
                    _set_walk_label(bag_round_stop[0][dst], t, cur)
                    _set_walk_label(bag_round_stop[1][dst], t, cur)
                    _set_walk_label(self.bag_star[dst], t, cur)
                    extra.append(dst)
        if extra:
            route_marked_stops = list(route_marked_stops) + list(self.accumulate_routes(extra))
    return _traverse_routes(self, bag_round_stop, k, route_marked_stops)


RaptorAlgorithm.traverse_routes = _traverse_routes_with_origin_walks

# Fixed queries: main routes, plus routes using frequency boxes ("此間N分毎") and frequency-only sections
CASES = [
    ('大阪', '京城〈朝鮮〉', '09:00'),
    ('東京', '京都', '08:00'),
    ('東京', '下關', '08:00'),
    ('東京', '青森', '08:00'),
    ('新宿', '松本', '08:00'),
    ('京都', '奈良', '09:00'),
    ('釜山〈朝鮮〉', '長春〈滿洲〉', '08:00'),
    ('東京', '札幌', '08:00'),
    ('青森', '東京', '08:00'),
    ('天現寺橋', '玉川', '09:00'),
    ('東京', '三軒茶屋', '09:00'),
    ('福岡', '久留米', '09:00'),
    ('難波', '和歌山市', '20:30'),
    ('鹿兒島', '谷山', '09:00'),
]


def load(gtfs_dir=GTFS_DIR, out_dir=OUT_DIR):
    with open(os.path.join(gtfs_dir, '_meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    return read_timetable(out_dir), meta, load_trips(gtfs_dir)


def load_trips(gtfs_dir=GTFS_DIR):
    """Display information for day-1 trips (columns added to trips.txt by make_pyraptor_gtfs.py)."""
    trips = {}
    with open(os.path.join(gtfs_dir, 'trips.txt'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['day'] == '1':
                trips[r['trip_id']] = r
    return trips


def to_min(hhmm):
    h, m = hhmm.split(':')[:2]
    return int(h) * 60 + int(m)


def fmt_min(m):
    if m is None:
        return '?'
    s = f'{m % 1440 // 60:02d}:{m % 60:02d}'
    return s + (f'（+{m // 1440}日）' if m >= 1440 else '')


def resolve(meta, name):
    """Same lookup as resolveGroupIds in demo/route_planner."""
    n2g = meta['name_to_groups']
    if name in n2g:
        return n2g[name]
    cands = sorted(n for n in n2g if name in n)
    return n2g[cands[0]] if cands else None


def _stops_of(tt, gids):
    out = []
    for g in gids:
        st = tt.stations.get(g)
        if st is not None:
            out.extend(st.stops)
    return out


def _journey(dest, bag):
    """Rebuild the itinerary by following from_stop back from the destination (like pyraptor's reconstruct_journey,
    with a cap on the number of steps)."""
    legs = []
    to_stop = dest
    for _ in range(1000):
        lbl = bag[to_stop]
        if lbl.from_stop is None:
            break
        legs.insert(0, (lbl.from_stop, to_stop, lbl.trip))
        to_stop = lbl.from_stop
    # Keep legs with a trip. A leg without a trip (trip=None) between different stations is a walk, so keep it too
    #   (transfers within a station are dropped as before).
    return [(a, b, t) for a, b, t in legs if a.station != b.station]


def _leg_times(trip, from_stop, to_stop):
    st = trip.stop_times
    i = next((k for k, x in enumerate(st) if x.stop == from_stop), None)
    if i is None:
        return None, None
    j = next((k for k in range(i + 1, len(st)) if st[k].stop == to_stop), None)
    return st[i].dts_dep, (st[j].dts_arr if j is not None else None)


def search(tt, meta, trips, from_gids, to_gids, dep_min, rounds=10):
    """Returns {found, arr_min (minutes since 0:00 of the search day), round, legs, valid, note}."""
    res = {'found': False, 'arr_min': None, 'round': None, 'legs': [], 'valid': None, 'note': ''}
    if _WALK_FOR != id(tt):
        install_walks(tt, meta)
    from_stops, to_stops = _stops_of(tt, from_gids), _stops_of(tt, to_gids)
    if not from_stops or not to_stops:
        res['note'] = '便の止まらない駅'
        return res
    bag = RaptorAlgorithm(tt).run(from_stops, dep_min * 60, rounds)
    best = None
    for k in sorted(bag):
        if k == 0:
            continue
        for s in to_stops:
            lbl = bag[k].get(s)
            if lbl is None or lbl.earliest_arrival_time >= LARGE_NUMBER:
                continue
            if best is None or lbl.earliest_arrival_time < best[0]:
                best = (lbl.earliest_arrival_time, k, s)
    if best is None:
        return res
    arr, k, stop = best
    res.update(found=True, arr_min=arr // 60, round=k)
    legs = []
    for a, b, trip in _journey(stop, bag[k]):
        if trip is None:   # walking leg; times come from the labels (arrival time at each stop)
            d_s = bag[k][a].earliest_arrival_time
            a_s = bag[k][b].earliest_arrival_time
            legs.append({
                'trip': '徒歩', 'key': '', 'label': f'徒歩 {max(0, (a_s - d_s)) // 60} 分',
                'est': False, 'walk': True, 'walk_min': max(0, (a_s - d_s)) // 60,
                'from': meta['stop_names'].get(a.id, a.id), 'from_gid': a.station.name,
                'to': meta['stop_names'].get(b.id, b.id), 'to_gid': b.station.name,
                'dep_min': d_s // 60, 'arr_min': a_s // 60,
            })
            continue
        dep_s, arr_s = _leg_times(trip, a, b)
        tid = trip.long_name
        if legs and legs[-1]['trip'] == tid and legs[-1]['to_gid'] == a.station.name:
            legs[-1].update(to=meta['stop_names'].get(b.id, b.id), to_gid=b.station.name,
                            arr_min=None if arr_s is None else arr_s // 60)
            continue
        info = trips.get(re.sub(r'_dm?\d+$', '', tid), {})   # _d2...: copies for later days; _dm1: copy for the previous day
        legs.append({
            'trip': tid, 'key': info.get('router_key', ''), 'label': info.get('label', tid),
            'est': info.get('est') == '1',
            'from': meta['stop_names'].get(a.id, a.id), 'from_gid': a.station.name,
            'to': meta['stop_names'].get(b.id, b.id), 'to_gid': b.station.name,
            'dep_min': None if dep_s is None else dep_s // 60,
            'arr_min': None if arr_s is None else arr_s // 60,
        })
    res['legs'] = legs
    res['valid'] = (bool(legs)
                    and all(x['dep_min'] is not None and x['arr_min'] is not None for x in legs)
                    and all(legs[i]['arr_min'] <= legs[i + 1]['dep_min'] for i in range(len(legs) - 1))
                    and legs[0]['dep_min'] >= dep_min and legs[-1]['arr_min'] == res['arr_min'])
    return res


def describe(res):
    if not res['found']:
        return '経路なし' + (f'（{res["note"]}）' if res['note'] else '')
    head = f'到着 {fmt_min(res["arr_min"])}  乗車 {len(res["legs"])} 本（探索 {res["round"]} 回目）'
    if not res['valid']:
        head += '  ※行程のたどり直しが不完全（到着時刻は有効）'
    lines = [head]
    for x in res['legs']:
        lines.append(f'   {x["label"]}: {x["from"]} {fmt_min(x["dep_min"])} → {x["to"]} {fmt_min(x["arr_min"])}')
    return '\n'.join(lines)


def main():
    tt, meta, trips = load()
    print(f'データ: {meta["inputs"]["gtfs"]}（{meta["created"]} に変換・{meta["days"]} 日ぶん）\n')
    if len(sys.argv) > 2:
        cases = [(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else '08:00')]
    else:
        cases = CASES
    for org, dst, dep in cases:
        fg, tg = resolve(meta, org), resolve(meta, dst)
        if not fg or not tg:
            print(f'{org} → {dst}: 駅名が見つかりません\n')
            continue
        print(f'{org} → {dst}  {dep} 発: ' + describe(search(tt, meta, trips, fg, tg, to_min(dep))))
        print()


if __name__ == '__main__':
    main()
