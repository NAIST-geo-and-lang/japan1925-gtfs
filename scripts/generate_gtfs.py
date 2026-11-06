"""
generate_gtfs.py

From integrated_stop_times.csv, write:
  1. 4_integrated/stops_master.csv  - station master (one entry per (stop_name, line_name), with stop_id)
  2. 4_integrated/trips_master.csv  - trip master (with gtfs_trip_id)
  3. the GTFS files under gtfs/
     - agency.txt, calendar.txt, stops.txt, routes.txt, trips.txt, stop_times.txt

The key of stops_master.csv is (stop_name, line_name): a station name on different
lines gives separate records (handles different stations with the same name).
"""

import os
import csv
import math
import re
from collections import defaultdict, OrderedDict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INT_DIR    = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'))
GTFS_DIR   = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs'))
INPUT_CSV  = os.path.join(INT_DIR, 'integrated_stop_times.csv')

os.makedirs(GTFS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_integrated():
    """Read integrated_stop_times.csv and return a list of rows."""
    with open(INPUT_CSV, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Step 3: stops_master (per (name, line) key)
# ---------------------------------------------------------------------------
def build_stops_master(rows):
    """
    List the unique (stop_name, line_name) pairs and number them with stop_id.
    Returns { (stop_name, line_name): {stop_id, stop_name, line_name, stop_type, ...} }
    """
    # (name, line) -> stop_type (the most frequent value)
    pair_types = defaultdict(list)
    for r in rows:
        key = (r['stop_name'], r['line_name'])
        stype = r.get('stop_type') or 'station'
        pair_types[key].append(stype)

    # Keep coordinates etc. from an existing stops_master.csv
    existing_data = {}  # (name, line) -> dict
    legacy_by_name = {}  # name -> dict (old format: per name only)
    existing_extra_fields = []
    existing_path = os.path.join(INT_DIR, 'stops_master.csv')
    # Whether to inherit coordinates etc. from the previous stops_master (GTFS_INHERIT_EXISTING).
    #   Default 0 = do not read it (same as building from an empty folder); run_pipeline.sh
    #   always sets 0 via scripts/kb_places_env.sh. Previous behavior = GTFS_INHERIT_EXISTING=1.
    if os.environ.get('GTFS_INHERIT_EXISTING', '0') == '1' and os.path.exists(existing_path):
        with open(existing_path, encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            existing_extra_fields = [k for k in fieldnames
                                     if k not in {'stop_id', 'stop_name', 'line_name', 'stop_type'}]
            has_line_name = 'line_name' in fieldnames
            for r in reader:
                if has_line_name:
                    key = (r['stop_name'], r.get('line_name', ''))
                    existing_data[key] = {k: r.get(k, '') for k in existing_extra_fields}
                else:
                    legacy_by_name[r['stop_name']] = {k: r.get(k, '') for k in existing_extra_fields}

    # Build the new stops_master
    stops = OrderedDict()
    sorted_keys = sorted(pair_types.keys())
    for i, (name, line) in enumerate(sorted_keys, start=1):
        types = pair_types[(name, line)]
        # Fixed tie-break (relying on set order would swap station/port between runs).
        #   Ties come from inconsistent transcription (e.g. 宮島棧橋 on 連絡汽船: port on p25/p26, station on p27/p28).
        most_common = max(sorted(set(types)), key=types.count)
        # Look up existing data: 1) new format, (name, line) match 2) old format, name match
        existing = existing_data.get((name, line))
        if existing is None:
            existing = legacy_by_name.get(name, {})
        stops[(name, line)] = {
            'stop_id':    f'S{i:05d}',
            'stop_name':  name,
            'line_name':  line,
            'stop_type':  most_common,
        }
        for k in existing_extra_fields:
            stops[(name, line)][k] = existing.get(k, '')

    stops['_extra_fields'] = existing_extra_fields
    return stops


def write_stops_master(stops):
    path = os.path.join(INT_DIR, 'stops_master.csv')
    extra_fields = stops.pop('_extra_fields', ['canonical_name', 'stop_lat', 'stop_lon', 'coord_source'])
    # Required columns
    if 'canonical_name' not in extra_fields:
        extra_fields = ['canonical_name'] + extra_fields
    if 'stop_lat' not in extra_fields:
        extra_fields = extra_fields + ['stop_lat']
    if 'stop_lon' not in extra_fields:
        extra_fields = extra_fields + ['stop_lon']
    if 'coord_source' not in extra_fields:
        extra_fields = extra_fields + ['coord_source']
    fields = ['stop_id', 'stop_name', 'line_name', 'canonical_name', 'stop_type'] + \
             [f for f in extra_fields if f not in {'canonical_name'}]
    seen = set()
    fields = [x for x in fields if not (x in seen or seen.add(x))]
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in stops.values():
            w.writerow({k: s.get(k, '') for k in fields})
    print(f'  stops_master: {len(stops)}駅 → {path}（fields: {fields}）')


# ---------------------------------------------------------------------------
# Step 4-0: sub-routes (Default ON. Previous behavior = GTFS_SPLIT_SUBROUTES=0.)
# ---------------------------------------------------------------------------
# One line_name can hold physically separate routes (尾西鐵道線, 温泉電軌線,
# 遠州電氣鐵道線, 連絡汽船 = 青函/關門/宮島/稚泊 ...). Each numbers its trips 1, 3, 5, ...
# on its own, so GTFS keys collide and integration splits them with `_b`.
#
# The transcribed line_name is left unchanged; only GTFS routes are split by physical route.
# Trips that share at least one adjacent station pair actually run are the same route.
#   - Through trips bridge consecutive sections, so these are not split
#   - Summary bands (which skip stations) share no edges; they are merged by station-set
#     containment or by sharing two or more stations
#   - Sharing only one junction station keeps routes separate
#
# Default ON. Previous behavior = `GTFS_SPLIT_SUBROUTES=0` (run_pipeline.sh --no-split-subroutes).
SPLIT_SUBROUTES = os.environ.get('GTFS_SPLIT_SUBROUTES', '1') == '1'

# Add a `region` column to routes.txt (朝鮮・滿洲・支那・臺灣・樺太・露領・北海道・内地) from
#   disambiguate_stations.classify_line(): the region of each route, separate from the station
#   name tag 〈region〉. GTFS allows extra columns. The same data is always written to
#   GTFS_DIR/line_region.csv (scripts/build_gtfs_extras.py). Default ON. No column = GTFS_ROUTE_REGION=0.
ROUTE_REGION = os.environ.get('GTFS_ROUTE_REGION', '1') == '1'

# Write frequency boxes ("此間○分毎ニ運轉") to the standard GTFS frequencies.txt.
#   Input = INTEGRATED_DIR/frequency_box.csv (scripts/build_frequency_box.py). Only when ON:
#   (1) append a template trip (trip_id `TF...`, a copy of the preceding trip) per box to
#   trips.txt / stop_times.txt (GTFS reads stop_times of frequency-based trips as relative
#   times, so referencing the printed trip would lose its printed times); (2) write
#   frequencies.txt; (3) write frequency_box.csv with template_trip_id to GTFS_DIR.
#   No times are created (only headway and service window).
#   Default ON. Previous behavior (no boxes, the 6 GTFS files unchanged) = `GTFS_FREQUENCIES=0`
#   (run_pipeline.sh --no-frequencies).
FREQUENCIES = os.environ.get('GTFS_FREQUENCIES', '1') == '1'

# Write frequency-only sections (no time grid; frequency_only.csv) to frequencies.txt.
#   Input = INTEGRATED_DIR/frequency_sections.csv (scripts/build_frequency_sections.py). Only
#   when ON: (1) a route `RQ...` per line name; (2) add the listed stations to stops_master /
#   stops.txt as `SQ...` (coordinates from the coordinate tables; sections without coordinates
#   at both ends are skipped); (3) a template trip `TQ...` with departure (發) = first departure
#   at the origin and arrival (著) = first departure + running time at the terminus (stations
#   between have names only); (4) append to frequencies.txt; (5) GTFS_DIR/frequency_sections.csv.
#   Default ON. Previous behavior = `GTFS_FREQ_SECTIONS=0` (run_pipeline.sh --no-freq-sections).
FREQ_SECTIONS = os.environ.get('GTFS_FREQ_SECTIONS', '1') == '1'

# Give estimated times to the stations between the ends of frequency-only template trips
#   (otherwise the journey planner cannot board or alight there). Times are apportioned by
#   distance measured from station coordinates (coordinate tables via agent_knowledge.lookup);
#   sections with a missing coordinate or zero length stay blank. The terminus arrival is also
#   computed (not printed) and is shown as est (estimated).
#   Default ON. Previous behavior (blank) = GTFS_FREQ_SECTION_INTERP=0.
FREQ_SECTION_INTERP = os.environ.get('GTFS_FREQ_SECTION_INTERP', '1') == '1'   # previous behavior = 0 (run_pipeline.sh --no-freq-section-interp)


def _freq_lookup(nm, line):
    """Coordinates of a frequency-only station from the coordinate tables (agent_knowledge.lookup).
    They decide whether a section is written, the apportioning, and which lines are not apportioned."""
    import agent_knowledge
    return agent_knowledge.lookup(nm, line)

# Fill the copied field at the boundary station with the value printed by the partner trip of
#   the same through train. The original often splits one train into two tables at a line
#   boundary, one printing only 著 (arrival) and the other only 發 (departure) at the boundary
#   station; write_stop_times_txt copies the opposite field into a blank one (e.g. 舞鶴線 30
#   arrival at 綾部 becomes 16:56, copied from the departure, while the same train as
#   山陰及東海道線 30 prints arrival 4.49 on p72).
#   When ON, for trips that the through-train table (data/tables/through_trains/physical_trains.csv,
#   path GTFS_PHYSICAL_TRAINS_PATH, read only) marks as the same train, write the partner's value
#   instead of copying if all of these hold (only blank fields; trips are never kept or dropped):
#     - the station has exactly one row in both trips (compared without 〈region〉 tags and
#       with old/new character forms unified)
#     - this trip has a time in the opposite field at that station
#     - no arrival on a trip's first row, no departure on its last row
#     - the day is aligned to the opposite field by multiples of 1440, and dwell is 0-60 min
#     - the time is not before the previous row or after the next row
#     - if the partner also prints the opposite field, it equals this trip's opposite field
#     - several partners must agree and all pass the conditions
#   Written only to GTFS stop_times.txt; integrated_stop_times.csv is not changed.
#   Written and refused fields go to INTEGRATED_DIR/partner_fill_report.csv (only when ON).
#   Default ON. Previous behavior = GTFS_FILL_FROM_PARTNER=0.
FILL_FROM_PARTNER = os.environ.get('GTFS_FILL_FROM_PARTNER', '1') != '0'   # default ON
PHYSICAL_TRAINS_PATH = os.environ.get('GTFS_PHYSICAL_TRAINS_PATH') or os.path.join(
    BASE_DIR, 'data', 'tables', 'through_trains', 'physical_trains.csv')


def _pf_min(s):
    """'HH:MM' (may exceed 24h) -> minutes. None if empty or invalid."""
    s = str(s or '')
    if ':' not in s:
        return None
    try:
        h, m = s.split(':')[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def partner_fill_plan(rows):
    """Plan for FILL_FROM_PARTNER. Returns ({(gtfs_trip_key, stop_sequence): {'arr_time'|'dep_time': 'HH:MM'}}, report rows).
    rows is not changed."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from known_kanji_variants import normalize as _kv

    def dn(name):
        return _kv((name or '').split('〈')[0], prefer_new=True)

    def hm(t):
        return '%02d:%02d' % (t // 60, t % 60)

    if not os.path.exists(PHYSICAL_TRAINS_PATH):
        print(f'  相手の便の値で埋める: 対応表が無い（{PHYSICAL_TRAINS_PATH}）→ 何もしない')
        return {}, []
    members = defaultdict(list)
    with open(PHYSICAL_TRAINS_PATH, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            members[r['physical_train_id']].append((int(r['seq']), r['trip_key']))
    by_key = defaultdict(list)
    for r in rows:
        by_key[r['gtfs_trip_key']].append(r)
    rows_of, idx_of = {}, {}
    for key, rs in by_key.items():
        rs = sorted(rs, key=lambda x: int(x['stop_sequence']))
        rows_of[key] = rs
        ix = defaultdict(list)
        for i, r in enumerate(rs):
            ix[dn(r['stop_name'])].append(i)
        idx_of[key] = ix

    plans = defaultdict(dict)    # (key, row index, field) -> {value: [partner keys]}
    refused = []                 # (key, row index, field, partner, reason)
    for pid in sorted(members):
        keys = [k for _, k in sorted(members[pid]) if k in rows_of]
        for a in keys:
            rs_a, ix_a = rows_of[a], idx_of[a]
            for b in keys:
                if b == a:
                    continue
                rs_b, ix_b = rows_of[b], idx_of[b]
                for s in ix_a:
                    if s not in ix_b:
                        continue
                    for fld, opp in (('arr', 'dep'), ('dep', 'arr')):
                        hits = [i for i in ix_a[s]
                                if _pf_min(rs_a[i].get(f'{fld}_time')) is None
                                and _pf_min(rs_a[i].get(f'{opp}_time')) is not None
                                and not (fld == 'arr' and i == 0)
                                and not (fld == 'dep' and i == len(rs_a) - 1)]
                        if not hits or not any(_pf_min(rs_b[j].get(f'{fld}_time')) is not None for j in ix_b[s]):
                            continue
                        if len(ix_a[s]) != 1 or len(ix_b[s]) != 1:
                            refused.append((a, hits[0], fld, b, '同じ驛がどちらかの便に 2 行以上ある'))
                            continue
                        i, j = ix_a[s][0], ix_b[s][0]
                        own = _pf_min(rs_a[i].get(f'{opp}_time'))
                        pv = _pf_min(rs_b[j].get(f'{fld}_time'))
                        po = _pf_min(rs_b[j].get(f'{opp}_time'))
                        if po is not None and (po - own) % 1440 != 0:
                            refused.append((a, i, fld, b, f'相手の{"發" if opp == "dep" else "著"} {hm(po)} が'
                                                          f'自分の {hm(own)} と違う（原本どうしの食い違い）'))
                            continue
                        if fld == 'arr':
                            d = (own - pv) % 1440
                            new = own - d
                        else:
                            d = (pv - own) % 1440
                            new = own + d
                        if d > 60:
                            refused.append((a, i, fld, b, f'停車が {d} 分（60 分を超える）'))
                            continue
                        if new < 0:
                            refused.append((a, i, fld, b, '日をそろえると負の時刻になる'))
                            continue
                        if fld == 'arr' and i > 0:
                            prev = [t for t in (_pf_min(rs_a[i - 1].get('arr_time')),
                                                _pf_min(rs_a[i - 1].get('dep_time'))) if t is not None]
                            if prev and new < max(prev):
                                refused.append((a, i, fld, b, f'前の驛 {rs_a[i - 1]["stop_name"]} の時刻より前になる'))
                                continue
                        if fld == 'dep' and i < len(rs_a) - 1:
                            nxt = [t for t in (_pf_min(rs_a[i + 1].get('arr_time')),
                                               _pf_min(rs_a[i + 1].get('dep_time'))) if t is not None]
                            if nxt and new > min(nxt):
                                refused.append((a, i, fld, b, f'次の驛 {rs_a[i + 1]["stop_name"]} の時刻より後になる'))
                                continue
                        plans[(a, i, fld)].setdefault(new, []).append(b)
    blocked = {(a, i, fld) for a, i, fld, _b, _w in refused}
    fills, report = {}, []
    for (a, i, fld) in sorted(plans):
        if (a, i, fld) in blocked:
            continue
        vals = plans[(a, i, fld)]
        if len(vals) != 1:
            refused.append((a, i, fld, '／'.join(sorted({b for bs in vals.values() for b in bs})),
                            '相手どうしで値が食い違う（' + '・'.join(hm(v) for v in sorted(vals)) + '）'))
            continue
        (new, bs), = vals.items()
        r = rows_of[a][i]
        opp_t = _pf_min(r.get(('dep' if fld == 'arr' else 'arr') + '_time'))
        fills.setdefault((a, r['stop_sequence']), {})[f'{fld}_time'] = hm(new)
        report.append({'trip_key': a, 'stop_sequence': r['stop_sequence'], 'stop_name': r['stop_name'],
                       'field': '著' if fld == 'arr' else '發', 'action': 'fill', 'value': hm(new),
                       'copied_before': hm(opp_t), 'dwell_min': str(abs(opp_t - new)),
                       'partner': '／'.join(sorted(bs)), 'reason': '同じ列車の相手の便が刷った値（物理列車の対応表）'})
    seen = set()
    for a, i, fld, b, why in sorted(refused):
        r = rows_of[a][i]
        k = (a, r['stop_sequence'], fld, why)
        if k in seen:
            continue
        seen.add(k)
        report.append({'trip_key': a, 'stop_sequence': r['stop_sequence'], 'stop_name': r['stop_name'],
                       'field': '著' if fld == 'arr' else '發', 'action': 'refused', 'value': '',
                       'copied_before': '', 'dwell_min': '', 'partner': b, 'reason': why})
    return fills, report


def write_partner_fill_report(report):
    path = os.path.join(INT_DIR, 'partner_fill_report.csv')
    flds = ['trip_key', 'stop_sequence', 'stop_name', 'field', 'action', 'value', 'copied_before', 'dwell_min',
            'partner', 'reason']
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=flds)
        w.writeheader()
        w.writerows(report)
    n_fill = sum(1 for x in report if x['action'] == 'fill')
    print(f'  相手の便の値で埋める（GTFS_FILL_FROM_PARTNER=1）: 書いた {n_fill} 欄・書かなかった {len(report) - n_fill} 所 → {path}')


def derive_subroutes(rows):
    """Split each line_name into physical routes. Returns {gtfs_trip_key: (line_name, idx)} and
    {line_name: [[trip_key, ...], ...]} (idx by trip count desc, ties by key; deterministic)."""
    seqs = defaultdict(list)
    line_of = {}
    for r in rows:
        seqs[r['gtfs_trip_key']].append((int(r['stop_sequence']), r['stop_name']))
        line_of[r['gtfs_trip_key']] = r['line_name']
    for v in seqs.values():
        v.sort()
    stops_of = {k: [n for _, n in v] for k, v in seqs.items()}

    by_line = defaultdict(list)
    for k in sorted(seqs):
        by_line[line_of[k]].append(k)

    comps_of_line = OrderedDict()
    route_of = {}
    for ln in sorted(by_line):
        keys = by_line[ln]
        big = [k for k in keys if len(set(stops_of[k])) >= 2]
        small = [k for k in keys if len(set(stops_of[k])) < 2]

        parent = {k: k for k in big}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        by_edge = defaultdict(list)
        for k in big:
            s = stops_of[k]
            for a, b in zip(s, s[1:]):
                if a != b:
                    by_edge[frozenset((a, b))].append(k)
        for _e, ks in sorted(by_edge.items(), key=lambda kv: sorted(kv[1])):
            r0 = find(ks[0])
            for k2 in ks[1:]:
                r2 = find(k2)
                if r2 != r0:
                    parent[r2] = r0

        buckets = defaultdict(list)
        for k in big:
            buckets[find(k)].append(k)
        comps = sorted(buckets.values(), key=lambda c: (-len(c), sorted(c)[0]))

        # Summary bands etc. share no edges and form separate components.
        # Merge into the same route if (1) the station set is contained in another component or
        # (2) two or more stations are shared (sharing one junction station stays separate).
        changed = True
        while changed and len(comps) > 1:
            changed = False
            sets = [set(n for k in c for n in stops_of[k]) for c in comps]
            for i in range(len(comps)):
                for j in range(len(comps)):
                    if i == j:
                        continue
                    if sets[i] and (sets[i] <= sets[j] or len(sets[i] & sets[j]) >= 2):
                        comps[j].extend(comps[i])
                        comps.pop(i)
                        changed = True
                        break
                if changed:
                    break
            comps = sorted(comps, key=lambda c: (-len(c), sorted(c)[0]))

        if not comps:
            comps = [small]
            small = []
        else:
            # One-station trips go to a component containing that station (else the largest)
            sets = [set(n for k in c for n in stops_of[k]) for c in comps]
            for k in small:
                st = set(stops_of[k])
                cand = [i for i, s in enumerate(sets) if st & s]
                comps[cand[0] if cand else 0].append(k)

        comps = [sorted(c) for c in comps]
        comps_of_line[ln] = comps
        for i, c in enumerate(comps):
            for k in c:
                route_of[k] = (ln, i)
    return route_of, comps_of_line, stops_of


def subroute_label(comp, stops_of, directions):
    """Label of a component, "<origin>・<terminus>間" (between origin and terminus), from the ends
    of its longest trip (outbound first)."""
    def rank(k):
        return (0 if directions.get(k) == 'outbound' else 1, -len(stops_of[k]), k)
    k = sorted(comp, key=rank)[0]
    s = stops_of[k]
    return f'{s[0]}・{s[-1]}間'


# ---------------------------------------------------------------------------
# Step 4: trips_master + routes
# ---------------------------------------------------------------------------
def build_trips_and_routes(rows, stops):
    trip_groups = defaultdict(list)
    for r in rows:
        key = r['gtfs_trip_key']
        trip_groups[key].append(r)

    route_lines = OrderedDict()
    for r in rows:
        ln = r['line_name']
        if ln not in route_lines:
            route_lines[ln] = None

    # OFF = one route per line_name. ON (default) = one route per physical route.
    if SPLIT_SUBROUTES:
        route_of, comps_of_line, stops_of = derive_subroutes(rows)
        directions = {r['gtfs_trip_key']: r['direction'] for r in rows}
        route_keys = []
        for ln in sorted(route_lines.keys()):
            for i in range(len(comps_of_line.get(ln, [[]]))):
                route_keys.append((ln, i))
    else:
        route_of, comps_of_line, stops_of, directions = None, None, None, None
        route_keys = [ln for ln in sorted(route_lines.keys())]

    routes = OrderedDict()
    for i, rk in enumerate(route_keys, start=1):
        ln = rk[0] if SPLIT_SUBROUTES else rk
        route_type = 2
        if '汽船' in ln or '連絡汽船' in ln:
            route_type = 4
        routes[rk] = {
            'route_id':         f'R{i:04d}',
            'route_short_name': ln,
            'route_type':       route_type,
        }
        if SPLIT_SUBROUTES:
            comps = comps_of_line.get(ln, [])
            # Lines with a single route get no label
            routes[rk]['route_long_name'] = (
                subroute_label(comps[rk[1]], stops_of, directions)
                if len(comps) > 1 and comps[rk[1]] else '')

    trips = OrderedDict()
    for i, key in enumerate(sorted(trip_groups.keys()), start=1):
        group = trip_groups[key]
        first = group[0]
        last  = group[-1]
        ln = first['line_name']
        rk = route_of[key] if SPLIT_SUBROUTES else ln

        has_port = any(r.get('stop_type') == 'port' for r in group)
        if has_port and routes[rk]['route_type'] == 2:
            routes[rk]['route_type'] = 4

        trips[key] = {
            'gtfs_trip_id': f'T{i:04d}',
            'gtfs_trip_key': key,
            'route_id':     routes[rk]['route_id'],
            'line_name':    ln,
            'direction':    first['direction'],
            'trip_num':     first['trip_num'],
            'first_stop':   first['stop_name'],
            'first_dep':    first.get('dep_time') or first.get('arr_time') or '',
            'last_stop':    last['stop_name'],
            'last_arr':     last.get('arr_time') or last.get('dep_time') or '',
        }

    if SPLIT_SUBROUTES:
        write_subroute_report(comps_of_line, routes, trips, stops_of, directions)
        write_b_suffix_check(trips, route_of, stops_of)

    return trips, routes


def write_b_suffix_check(trips, route_of, stops_of):
    """Check whether trip groups with `_b`/`_c` are explained by separate routes under one line name.
    Different routes = the split is correct; same route = possibly a real fragment."""
    groups = defaultdict(list)
    for key in trips:
        ln, d, num = key.split('__')
        groups[(ln, d, re.sub(r'_[b-z]$', '', num))].append(key)
    rows = [(k, v) for k, v in groups.items() if len(v) > 1]
    path = os.path.join(INT_DIR, 'subroute_b_check.csv')
    n_sep = 0
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['判定', 'line_name', 'direction', 'trip_num',
                    'n_trips', 'route_ids', 'trip_keys', 'endpoints'])
        for k, v in sorted(rows):
            rids = sorted({trips[x]['route_id'] for x in v})
            sep = len(rids) > 1
            n_sep += 1 if sep else 0
            ends = ' / '.join(f'{stops_of[x][0]}→{stops_of[x][-1]}' for x in sorted(v))
            w.writerow(['別ルート同居(分割は正しい)' if sep else '同ルート(断片の疑い)',
                        k[0], k[1], k[2], len(v), ' '.join(rids),
                        ' '.join(sorted(v)), ends])
    print(f'  subroute_b_check: `_b` 群 {len(rows)}（別ルートで説明 {n_sep} / '
          f'同ルートのまま {len(rows) - n_sep}） → {path}')


def write_subroute_report(comps_of_line, routes, trips, stops_of, directions):
    """Report of how each line name was split. Written only when ON."""
    path = os.path.join(INT_DIR, 'subroute_report.csv')
    fields = ['line_name', 'n_routes', 'route_id', 'route_long_name',
              'n_trips', 'n_stops', 'first_stop', 'last_stop', 'example_trip_key']
    n_split = 0
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for ln, comps in comps_of_line.items():
            if len(comps) > 1:
                n_split += 1
            for i, c in enumerate(comps):
                if not c:
                    continue
                rid = routes[(ln, i)]['route_id']
                st = []
                for k in sorted(c, key=lambda z: (-len(stops_of[z]), z)):
                    for n in stops_of[k]:
                        if n not in st:
                            st.append(n)
                lab = routes[(ln, i)].get('route_long_name', '')
                ends = sorted(c, key=lambda z: (0 if directions.get(z) == 'outbound' else 1,
                                                -len(stops_of[z]), z))[0]
                w.writerow({
                    'line_name': ln, 'n_routes': len(comps), 'route_id': rid,
                    'route_long_name': lab, 'n_trips': len(c), 'n_stops': len(st),
                    'first_stop': stops_of[ends][0], 'last_stop': stops_of[ends][-1],
                    'example_trip_key': ends,
                })
    print(f'  subroute_report: {len(comps_of_line)}線名 → {sum(len(c) for c in comps_of_line.values())}ルート'
          f'（分割された線名 {n_split}） → {path}')


def write_trips_master(trips):
    path = os.path.join(INT_DIR, 'trips_master.csv')
    fields = ['gtfs_trip_id', 'gtfs_trip_key', 'route_id', 'line_name',
              'direction', 'trip_num', 'first_stop', 'first_dep',
              'last_stop', 'last_arr']
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trips.values():
            w.writerow(t)
    print(f'  trips_master: {len(trips)}トリップ → {path}')


# ---------------------------------------------------------------------------
# Step 6: GTFS files
# ---------------------------------------------------------------------------
def hhmm_to_hhmmss(hhmm):
    if not hhmm:
        return ''
    return hhmm + ':00'


def write_agency():
    path = os.path.join(GTFS_DIR, 'agency.txt')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['agency_id', 'agency_name', 'agency_url', 'agency_timezone'])
        w.writerow(['HIST_1925', '1925年時刻表', 'https://example.com', 'Asia/Tokyo'])
    print(f'  agency.txt → {path}')


def write_calendar():
    path = os.path.join(GTFS_DIR, 'calendar.txt')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['service_id', 'monday', 'tuesday', 'wednesday',
                     'thursday', 'friday', 'saturday', 'sunday',
                     'start_date', 'end_date'])
        w.writerow(['SERVICE_1925', 1, 1, 1, 1, 1, 1, 1, '19250401', '19250401'])
    print(f'  calendar.txt → {path}')


def write_stops_txt(stops):
    path = os.path.join(GTFS_DIR, 'stops.txt')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['stop_id', 'stop_name', 'stop_lat', 'stop_lon'])
        for s in stops.values():
            display_name = s.get('canonical_name') or s['stop_name']
            w.writerow([s['stop_id'], display_name, s.get('stop_lat', ''), s.get('stop_lon', '')])
    print(f'  stops.txt: {len(stops)}駅 → {path}')


def write_routes_txt(routes):
    path = os.path.join(GTFS_DIR, 'routes.txt')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        region_of = None
        if ROUTE_REGION:
            import disambiguate_stations as _ds
            region_of = lambda name: _ds.classify_line(name) or '内地'  # noqa: E731
        if SPLIT_SUBROUTES:
            # route_short_name stays the line_name (the journey planner reads it as the line name).
            # Physical routes are told apart by route_id + route_long_name ("<origin>・<terminus>間").
            w.writerow(['route_id', 'agency_id', 'route_short_name',
                        'route_long_name', 'route_type'] + (['region'] if ROUTE_REGION else []))
            for r in routes.values():
                w.writerow([r['route_id'], 'HIST_1925', r['route_short_name'],
                            r.get('route_long_name', ''), r['route_type']]
                           + ([region_of(r['route_short_name'])] if ROUTE_REGION else []))
        else:
            w.writerow(['route_id', 'agency_id', 'route_short_name', 'route_type']
                       + (['region'] if ROUTE_REGION else []))
            for r in routes.values():
                w.writerow([r['route_id'], 'HIST_1925', r['route_short_name'], r['route_type']]
                           + ([region_of(r['route_short_name'])] if ROUTE_REGION else []))
    print(f'  routes.txt: {len(routes)}路線 → {path}')


def write_trips_txt(trips):
    path = os.path.join(GTFS_DIR, 'trips.txt')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['route_id', 'service_id', 'trip_id', 'trip_short_name', 'direction_id'])
        for t in trips.values():
            direction_id = 0 if t['direction'] == 'outbound' else 1
            w.writerow([t['route_id'], 'SERVICE_1925', t['gtfs_trip_id'],
                        t['trip_num'], direction_id])
    print(f'  trips.txt: {len(trips)}トリップ → {path}')


def write_stop_times_txt(rows, stops, trips, fills=None):
    path = os.path.join(GTFS_DIR, 'stop_times.txt')
    count = 0
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['trip_id', 'arrival_time', 'departure_time',
                     'stop_id', 'stop_sequence'])
        for r in rows:
            trip_key = r['gtfs_trip_key']
            trip_info = trips.get(trip_key)
            stop_info = stops.get((r['stop_name'], r['line_name']))
            if not trip_info or not stop_info:
                continue

            arr = hhmm_to_hhmmss(r.get('arr_time'))
            dep = hhmm_to_hhmmss(r.get('dep_time'))
            fl = fills.get((trip_key, r['stop_sequence'])) if fills else None
            if fl:   # GTFS_FILL_FROM_PARTNER (default ON): fill blanks with the partner trip's printed value before copying
                if not arr and fl.get('arr_time'):
                    arr = hhmm_to_hhmmss(fl['arr_time'])
                if not dep and fl.get('dep_time'):
                    dep = hhmm_to_hhmmss(fl['dep_time'])

            if arr and not dep:
                dep = arr
            elif dep and not arr:
                arr = dep

            w.writerow([trip_info['gtfs_trip_id'], arr, dep,
                        stop_info['stop_id'], r['stop_sequence']])
            count += 1
    print(f'  stop_times.txt: {count}レコード → {path}')


# ---------------------------------------------------------------------------
# Step 6.5: frequencies.txt + template trips (only when GTFS_FREQUENCIES=1)
# ---------------------------------------------------------------------------
def write_frequencies(rows, stops, trips, fills=None):
    """Turn each row of frequency_box.csv (template_trip_key, template_seq_from/to, gtfs_start/end,
    headway, exact) into a template trip `TFnnnn` and one frequencies.txt row. trips.txt and
    stop_times.txt are appended to (existing rows unchanged)."""
    src = os.path.join(INT_DIR, 'frequency_box.csv')
    if not os.path.exists(src):
        print(f'  frequencies: {src} が無い（scripts/build_frequency_box.py を先に回す）→ skip')
        return
    with open(src, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        box_fields = list(reader.fieldnames or [])
        boxes = list(reader)
    rows_by_key = defaultdict(list)
    for r in rows:
        rows_by_key[r['gtfs_trip_key']].append(r)
    trip_lines, st_lines, freq_lines = [], [], []
    n = 0
    for b in boxes:
        tkey = b.get('template_trip_key') or ''
        t = trips.get(tkey)
        if not t or not b.get('gtfs_start_time') or not b.get('template_seq_from'):
            b['template_trip_id'] = ''
            continue
        seq_from, seq_to = int(b['template_seq_from']), int(b['template_seq_to'])
        copied = []
        for r in rows_by_key[tkey]:
            seq = int(r['stop_sequence'])
            if not (seq_from <= seq <= seq_to):
                continue
            stop_info = stops.get((r['stop_name'], r['line_name']))
            if not stop_info:
                continue
            arr = hhmm_to_hhmmss(r.get('arr_time'))
            dep = hhmm_to_hhmmss(r.get('dep_time'))
            fl = fills.get((tkey, r['stop_sequence'])) if fills else None
            if fl:   # GTFS_FILL_FROM_PARTNER (default ON): template trips get the same values as the source trip
                if not arr and fl.get('arr_time'):
                    arr = hhmm_to_hhmmss(fl['arr_time'])
                if not dep and fl.get('dep_time'):
                    dep = hhmm_to_hhmmss(fl['dep_time'])
            if arr and not dep:
                dep = arr
            elif dep and not arr:
                arr = dep
            copied.append([arr, dep, stop_info['stop_id'], seq])
        if len(copied) < 2:
            b['template_trip_id'] = ''
            b['note'] = (b.get('note') or '') + '・雛形便の区間が 2 駅未満（generate_gtfs）'
            continue
        n += 1
        tid = f'TF{n:04d}'
        b['template_trip_id'] = tid
        direction_id = 0 if t['direction'] == 'outbound' else 1
        trip_lines.append([t['route_id'], 'SERVICE_1925', tid, t['trip_num'], direction_id])
        for arr, dep, sid, seq in copied:
            st_lines.append([tid, arr, dep, sid, seq])
        freq_lines.append([tid, b['gtfs_start_time'], b['gtfs_end_time'], b['headway_secs'], b['exact_times']])
    with open(os.path.join(GTFS_DIR, 'trips.txt'), 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(trip_lines)
    with open(os.path.join(GTFS_DIR, 'stop_times.txt'), 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(st_lines)
    path = os.path.join(GTFS_DIR, 'frequencies.txt')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['trip_id', 'start_time', 'end_time', 'headway_secs', 'exact_times'])
        w.writerows(freq_lines)
    with open(os.path.join(GTFS_DIR, 'frequency_box.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=box_fields)
        w.writeheader()
        for b in boxes:
            w.writerow({k: b.get(k, '') for k in box_fields})
    print(f'  frequencies.txt: {len(freq_lines)} 行・雛形便 {n} 本（trips.txt / stop_times.txt の末尾に '
          f'{len(trip_lines)} / {len(st_lines)} 行を追記）→ {path}')


# ---------------------------------------------------------------------------
# Step 6.6: frequency-only sections (only when GTFS_FREQ_SECTIONS=1)
# ---------------------------------------------------------------------------
def load_freq_sections():
    src = os.path.join(INT_DIR, 'frequency_sections.csv')
    if not os.path.exists(src):
        return None, []
    with open(src, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def add_freq_section_stops(stops, sections):
    """Add section stations to stops ((name, line) -> dict) as `SQnnnn`, only those with coordinates
    in the coordinate tables (GTFS stops require lat/lon).
    Returns the usable sections (each row gets 'seq' = list of station names)."""
    import disambiguate_stations as _ds
    extra = list(stops.get('_extra_fields', []))
    n = sum(1 for k in stops if isinstance(k, tuple) and str(stops[k].get('stop_id', '')).startswith('SQ'))
    # DISAMBIG_TAG_REGION_FIX: apply the 〈region〉 tag rule to section stops too, collecting the
    #   regions of the lines each name appears on (integrated stations + all sections). OFF = names unchanged.
    name_regions = {}
    if _ds.DISAMBIG_TAG_REGION_FIX:
        for k in stops:
            if isinstance(k, tuple):
                name_regions.setdefault(k[0].split('〈')[0], set()).add(_ds.classify_line(k[1]) or '内地')
        for b in sections:
            for nm in (b.get('stations') or '').split('・'):
                if nm:
                    name_regions.setdefault(nm, set()).add(_ds.classify_line(b['line_name']) or '内地')
    usable = []
    for b in sections:
        if not b.get('headway_secs'):
            continue
        line = b['line_name']
        names = [x for x in b['stations'].split('・') if x]
        have = []
        for nm in names:
            hit = _freq_lookup(nm, line)   # no retry without the line name (the tables have no such rows)
            if hit:
                have.append(nm)
        if len(have) < 2 or names[0] not in have or names[-1] not in have:
            b['template_trip_id'] = ''
            b['note'] = (b.get('note') or '') + '・両端の座標が無い（出さない）'
            continue
        for nm in have:
            key = (nm, line)
            if key not in stops:
                n += 1
                stops[key] = {'stop_id': f'SQ{n:04d}', 'stop_name': _ds.freq_section_stop_name(nm, line, name_regions),
                              'line_name': line, 'stop_type': 'station'}
                for k in extra:
                    stops[key][k] = ''
        b['seq'] = have
        usable.append(b)
    return usable


def _section_cum_km(seq, line):
    """Cumulative distance (km) along the section's stations. None if any coordinate is missing or length is 0."""
    pts = []
    for nm in seq:
        hit = _freq_lookup(nm, line)
        if not hit:
            return None
        pts.append((float(hit[0]), float(hit[1])))
    cum = [0.0]
    for (la, lo), (lb, lob) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot((la - lb) * 111.0,
                                        (lo - lob) * 111.0 * math.cos(math.radians((la + lb) / 2))))
    return cum if cum[-1] > 0 else None


def conflicting_freq_lines(sections):
    """Find, by measurement, the lines whose times must not be apportioned.

    The original prints several sections with different extents for one line (e.g. 玉川電氣鐵道線:
    天現寺橋→玉川 55 min, 澁谷→新町 30 min, ...). Most are consistent, but some are not; apportioning
    those would make estimates faster (or slower) than the printed running times.

    Method: apportion a long section, compute the running time between the ends of a shorter section
    nested in it, and compare with the printed time. Returns lines where the difference exceeds
    `printed * TOL_RATIO + TOL_MIN`.
    """
    tol_r = float(os.environ.get('FREQ_SECTION_INTERP_TOL_RATIO', '0.3'))
    tol_m = float(os.environ.get('FREQ_SECTION_INTERP_TOL_MIN', '3'))
    by = defaultdict(list)
    for b in sections:
        if 'seq' in b and not str(b.get('source', '')).startswith('estimate'):   # estimated sections are not used as a reference
            by[(b['line_name'], b['direction'])].append(b)
    bad, detail = set(), []
    for (line, _d), rs in sorted(by.items()):
        for a in rs:
            cum = _section_cum_km(a['seq'], line)
            if cum is None:
                continue
            for b in rs:
                if b is a or len(b['seq']) >= len(a['seq']) or len(b['seq']) < 2:
                    continue
                if not set(b['seq']) <= set(a['seq']):
                    continue
                o, d2 = b['origin'], b['destination']
                if o not in a['seq'] or d2 not in a['seq']:
                    continue
                got = (float(a['duration_min']) * abs(cum[a['seq'].index(d2)] - cum[a['seq'].index(o)]) / cum[-1])
                printed = float(b['duration_min'])
                if abs(got - printed) > printed * tol_r + tol_m:
                    bad.add(line)
                    detail.append((line, a['section_id'], b['section_id'], printed, round(got, 1)))
    return bad, detail


def _interp_section_times(seq, line, dep0, arr1, skip_names=()):
    """Apportion times of the stations between the ends of a frequency-only template trip by the
    distance ratio measured from station coordinates (called only when `FREQ_SECTION_INTERP=1`).

    Returns a list of minutes from 0:00, the same length as `seq`; `None` if any coordinate is
    missing or the length is 0 (the caller leaves the stations blank). The ends are always
    `dep0` / `arr1`, and values are made non-decreasing so rounding cannot reverse them.

    `skip_names` = stations that another section of the same line prints as an end with its own
    running time. They get no apportioned value (otherwise an estimate could be faster than the
    printed time, e.g. 玉川 on 玉川電氣鐵道線: 天現寺橋→玉川 is printed as 55 min, but apportioning
    the 天現寺橋→世田谷 37-min section gives 27 min). They stay reachable as ends of the other
    section. Their positions in the result are `None`.
    """
    cum = _section_cum_km(seq, line)
    if cum is None:
        return None
    out = [dep0] + [int(round(dep0 + (arr1 - dep0) * cum[i] / cum[-1]))
                    for i in range(1, len(seq) - 1)] + [arr1]
    for i in range(1, len(out)):          # rounding must not make a station earlier than the previous one
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    # No apportioned value at stations printed as ends of another section
    for i in range(1, len(seq) - 1):
        if seq[i] in skip_names:
            out[i] = None
    return out


def write_freq_sections(sections, box_fields, stops, routes, n_routes_before):
    """Template trips `TQnnnn` + routes `RQnnnn` + rows appended to frequencies.txt + GTFS_DIR/frequency_sections.csv."""
    route_of_line = {}
    n_interp_trip = n_interp_cell = n_interp_skip = 0
    # Stations printed as ends of another section of the same line get no apportioned value
    ends_of_line = defaultdict(set)
    for b in sections:
        if 'seq' in b and not str(b.get('source', '')).startswith('estimate'):   # ends of estimated sections are not printed times
            ends_of_line[b['line_name']].add(b['origin'])
            ends_of_line[b['line_name']].add(b['destination'])
    # Lines not apportioned = only lines measured as inconsistent (merely overlapping sections are apportioned).
    overlap_lines, conflict_detail = conflicting_freq_lines(sections)
    n_interp_line_skip = len(overlap_lines)
    trip_lines, st_lines, freq_lines = [], [], []
    n = 0
    for b in sections:
        if 'seq' not in b:
            continue
        line = b['line_name']
        if line not in route_of_line:
            rid = f'RQ{len(route_of_line) + 1:04d}'
            route_of_line[line] = rid
            routes[('freq', line)] = {'route_id': rid, 'route_short_name': line,
                                      'route_type': 4 if b.get('source') == 'estimate_ship' else 2,   # estimated ship (FREQ_SECTIONS_ESTIMATE)
                                      'route_long_name': ''}
        n += 1
        tid = f'TQ{n:04d}'
        b['template_trip_id'] = tid
        first = b['first_dep']
        h, m = int(first[:2]), int(first[3:])
        dep0 = h * 60 + m
        arr1 = dep0 + int(b['duration_min'])
        seq = b['seq']
        trip_lines.append([route_of_line[line], 'SERVICE_1925', tid, b['section_id'], 0 if b['direction'] == 'outbound' else 1])
        # Apportion stations between the ends (only when FREQ_SECTION_INTERP=1); None = leave blank
        interp = (_interp_section_times(seq, line, dep0, arr1, ends_of_line.get(line, set()))
                  if (FREQ_SECTION_INTERP and len(seq) > 2 and line not in overlap_lines) else None)
        if interp:
            n_filled = sum(1 for v in interp[1:-1] if v is not None)
            if n_filled:
                n_interp_trip += 1
            n_interp_cell += n_filled
            n_interp_skip += (len(seq) - 2) - n_filled
        for i, nm in enumerate(seq, start=1):
            sid = stops[(nm, line)]['stop_id']
            if i == 1:
                t = f'{dep0 // 60:02d}:{dep0 % 60:02d}:00'
                st_lines.append([tid, t, t, sid, i])
            elif i == len(seq):
                t = f'{arr1 // 60:02d}:{arr1 % 60:02d}:00'
                st_lines.append([tid, t, t, sid, i])
            elif interp and interp[i - 1] is not None:
                v = interp[i - 1]
                t = f'{v // 60:02d}:{v % 60:02d}:00'
                st_lines.append([tid, t, t, sid, i])     # apportioned estimate (not printed; shown as est)
            else:
                st_lines.append([tid, '', '', sid, i])   # station between the ends: name only, no time
        last = b['last_dep']
        lh, lm = int(last[:2]), int(last[3:])
        end = lh * 60 + lm + 1
        freq_lines.append([tid, f'{dep0 // 60:02d}:{dep0 % 60:02d}:00', f'{end // 60:02d}:{end % 60:02d}:00',
                           b['headway_secs'], 0])
    with open(os.path.join(GTFS_DIR, 'trips.txt'), 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(trip_lines)
    with open(os.path.join(GTFS_DIR, 'stop_times.txt'), 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(st_lines)
    path = os.path.join(GTFS_DIR, 'frequencies.txt')
    new_file = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(['trip_id', 'start_time', 'end_time', 'headway_secs', 'exact_times'])
        w.writerows(freq_lines)
    with open(os.path.join(GTFS_DIR, 'frequency_sections.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=box_fields)
        w.writeheader()
        for b in sections:
            w.writerow({k: b.get(k, '') for k in box_fields})
    print(f'  frequency_sections: route {len(route_of_line)}・雛形便 {n} 本（trips/stop_times の末尾に {len(trip_lines)}/{len(st_lines)} 行）・'
          f'frequencies.txt に {len(freq_lines)} 行追記')
    if FREQ_SECTION_INTERP:
        print(f'  途中駅の按分（FREQ_SECTION_INTERP=1）: 雛形便 {n_interp_trip} 本・{n_interp_cell} 駅に推定時刻'
              f'（別の区画が端点として直接の所要を刷っている {n_interp_skip} 駅は入れない・'
              f'原本の所要と食い違う {n_interp_line_skip} 線は按分しない: '
              f'{"・".join(sorted(overlap_lines)) or "なし"}）')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print('=== generate_gtfs.py ===')
    print()
    print('入力:', INPUT_CSV)
    rows = load_integrated()
    print(f'  レコード数: {len(rows)}')
    print()

    print('Step 3: stops_master 生成（per (name, line) key）')
    stops = build_stops_master(rows)
    sec_fields, sections = (None, [])
    if FREQ_SECTIONS:
        sec_fields, sections = load_freq_sections()
        if sec_fields is None:
            print('  frequency_sections.csv が無い（scripts/build_frequency_sections.py を先に回す）→ 区画は出さない')
            sections = []
        else:
            usable = add_freq_section_stops(stops, sections)
            print(f'  frequency_sections: 出せる区画×方向 {len(usable)}／読み込み {len(sections)}')
    write_stops_master(stops)
    print()

    print('Step 4: trips_master / routes 生成')
    trips, routes = build_trips_and_routes(rows, stops)
    write_trips_master(trips)
    print(f'  routes: {len(routes)}路線')
    rail = sum(1 for r in routes.values() if r['route_type'] == 2)
    ferry = sum(1 for r in routes.values() if r['route_type'] == 4)
    print(f'    Rail(2): {rail}, Ferry(4): {ferry}')
    print()

    print('Step 6: GTFS ファイル生成')
    write_agency()
    write_calendar()
    write_stops_txt(stops)
    write_routes_txt(routes)
    write_trips_txt(trips)
    fills = None
    if FILL_FROM_PARTNER:
        fills, pf_report = partner_fill_plan(rows)
        write_partner_fill_report(pf_report)
    write_stop_times_txt(rows, stops, trips, fills)
    if FREQUENCIES:
        print('Step 6.5: frequencies.txt（GTFS_FREQUENCIES=1）')
        write_frequencies(rows, stops, trips, fills)
    if FREQ_SECTIONS and sections:
        print('Step 6.6: 頻度だけの表（GTFS_FREQ_SECTIONS=1）')
        write_freq_sections(sections, sec_fields, stops, routes, len(routes))
        # Routes were added, so rewrite routes.txt (existing rows unchanged; RQ... appended)
        write_routes_txt(routes)
    else:
        stale = os.path.join(GTFS_DIR, 'frequency_sections.csv')
        if os.path.exists(stale):
            os.remove(stale)
            print('  frequency_sections.csv: GTFS_FREQ_SECTIONS=0 なので前回の生成物を削除')
    if not FREQUENCIES:
        # OFF: remove frequencies.txt / frequency_box.csv left from an earlier ON run, or
        # generate_router_data would read them and create estimated trips
        for name in ('frequencies.txt', 'frequency_box.csv'):
            stale = os.path.join(GTFS_DIR, name)
            if os.path.exists(stale):
                os.remove(stale)
                print(f'  {name}: GTFS_FREQUENCIES=0 なので前回の生成物を削除')
    print()
    print('完了')


if __name__ == '__main__':
    main()
