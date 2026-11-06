"""
build_line_skeleton.py

For each line, build an undirected graph from adjacent stop pairs in trips and
extract skeleton polylines.

Skip-stop test: if trips of the same line show both "B right after A" and
"A -> ... -> B (with other stations between)", A-B is an apparent adjacency caused
by an express skipping stations, and is dropped. This removes long express chords
without external data.

Input:
  data/4_integrated/stops_master.csv  # station coordinates
  data/4_integrated/trips_master.csv  # trip -> line_name
  data/gtfs/stop_times.txt            # stop_sequence within a trip
  data/gtfs/routes.txt                # route_id -> line_name

Output:
  data/track_geometry/line_skeletons.geojson # geometry per line
  data/track_geometry/stop_order.csv         # ordered stations per line
  data/track_geometry/quality_report.csv     # structure class and statistics
"""

import csv
import json
import math
import os
import heapq
from collections import defaultdict, deque

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOPS_MASTER = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'stops_master.csv')
TRIPS_MASTER = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'trips_master.csv')
STOP_TIMES = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs'), 'stop_times.txt')
ROUTES_TXT = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs'), 'routes.txt')

OUT_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('TRACK_GEOMETRY_DIR', 'track_geometry'))
OUT_GEOJSON = os.path.join(OUT_DIR, 'line_skeletons.geojson')
OUT_STOP_ORDER = os.path.join(OUT_DIR, 'stop_order.csv')
OUT_QUALITY = os.path.join(OUT_DIR, 'quality_report.csv')

# === Absolute edge-length limits (a safety net for cases the skip-stop test misses) ===
# Inland stations are mostly under 30 km apart (at most about 50 km); lines abroad have
# longer gaps. The limits guard against wrong coordinates or mixed-up same-name stations.
SANITY_MAX_KM_INLAND = 80.0     # mainland Japan
SANITY_MAX_KM_NEAR = 150.0      # Korea, Taiwan
SANITY_MAX_KM_FAR = 300.0       # Manchuria, China, Siberia
SANITY_MAX_KM_FERRY = 2000.0    # ferries and steamships (some long routes)

NEAR_KEYWORDS = ('朝鮮', '京釜', '京義', '京元', '咸鏡', '臺灣', '宜蘭', '屏東')
FAR_KEYWORDS = ('滿洲', '滿鐵', '安奉', '京奉', '京圖', '京白', '京敦', '京通',
                '支那', '東支', '京漢', '京綏', '湖南', '滬', '粤', '鳥蘇里', 'シベリア')
FERRY_KEYWORDS = ('汽船', '連絡船', '航路', '商船')


def sanity_max(line_name):
    if any(k in line_name for k in FERRY_KEYWORDS):
        return SANITY_MAX_KM_FERRY
    if any(k in line_name for k in FAR_KEYWORDS):
        return SANITY_MAX_KM_FAR
    if any(k in line_name for k in NEAR_KEYWORDS):
        return SANITY_MAX_KM_NEAR
    return SANITY_MAX_KM_INLAND


# === Numeric utilities ===

def hav(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# === Loading ===

def load_stops():
    stops = {}
    with open(STOPS_MASTER, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            try:
                lat = float(r['stop_lat']) if r['stop_lat'] else None
                lon = float(r['stop_lon']) if r['stop_lon'] else None
            except (ValueError, KeyError):
                lat = lon = None
            stops[r['stop_id']] = {
                'name': r['stop_name'],
                'line_name': r.get('line_name', ''),
                'lat': lat,
                'lon': lon,
            }
    return stops


def load_routes():
    routes = {}
    with open(ROUTES_TXT, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            routes[r['route_id']] = r['route_short_name']
    return routes


def load_trips_by_line():
    by_line = defaultdict(list)
    with open(TRIPS_MASTER, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            by_line[r['line_name']].append(r['gtfs_trip_id'])
    return by_line


def load_trip_stops():
    ts = defaultdict(list)
    with open(STOP_TIMES, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            ts[r['trip_id']].append((int(r['stop_sequence']), r['stop_id']))
    for tid in ts:
        ts[tid].sort()
    return ts


# === Graph algorithms ===

def find_components(adj, nodes):
    visited = set()
    components = []
    # Fixed traversal order (independent of set iteration order / hash seed)
    for n in sorted(nodes):
        if n in visited:
            continue
        comp = []
        queue = deque([n])
        visited.add(n)
        while queue:
            u = queue.popleft()
            comp.append(u)
            for v in sorted(adj.get(u, {})):
                if v not in visited:
                    visited.add(v)
                    queue.append(v)
        components.append(comp)
    return components


def bfs_path(start, adj, allowed):
    """Find the node farthest from start by BFS and return the path to it."""
    visited = {start}
    parent = {start: None}
    queue = deque([start])
    farthest = start
    while queue:
        u = queue.popleft()
        farthest = u
        for v in sorted(adj.get(u, {})):   # fixed traversal order
            if v in allowed and v not in visited:
                visited.add(v)
                parent[v] = u
                queue.append(v)
    # Rebuild the path start -> farthest
    path = []
    node = farthest
    while node is not None:
        path.append(node)
        node = parent[node]
    path.reverse()
    return farthest, path


def find_diameter_path(adj, nodes):
    """Return the diameter (longest path) of a tree; approximate if there are cycles.

    The start is fixed at `min(nodes)`: double BFS is exact only for trees, and with
    branches or cycles the result depends on the start (set order varies per run).
    """
    if not nodes:
        return []
    allowed = set(nodes)
    start = min(nodes)   # fixed start (next(iter(set)) depends on the hash seed)
    u, _ = bfs_path(start, adj, allowed)
    _, path = bfs_path(u, adj, allowed)
    return path


def trace_cycle(adj, nodes):
    """Walk a cycle made of degree-2 nodes in order."""
    if not nodes:
        return []
    start = min(nodes)   # fixed start
    path = [start]
    visited = {start}
    cur = start
    prev = None
    while True:
        nexts = [v for v in sorted(adj.get(cur, {})) if v != prev]
        if not nexts:
            break
        # Prefer closing the cycle
        nxt = None
        for n in nexts:
            if n == start and len(path) > 2:
                path.append(start)
                return path
        for n in nexts:
            if n not in visited:
                nxt = n
                break
        if nxt is None:
            break
        path.append(nxt)
        visited.add(nxt)
        prev = cur
        cur = nxt
    return path


def find_branches(adj, comp_set, main_path):
    """Extract branches that leave main_path at junctions."""
    main_set = set(main_path)
    branches = []
    visited_branch = set()
    for trunk_node in main_path:
        for nb in sorted(adj.get(trunk_node, {})):   # fixed traversal order
            if nb in main_set or nb in visited_branch:
                continue
            # DFS along the branch leaving main from nb
            branch = [trunk_node, nb]
            local_visited = {trunk_node, nb}
            visited_branch.add(nb)
            cur = nb
            while True:
                nexts = [v for v in sorted(adj.get(cur, {}))
                         if v not in local_visited and v not in main_set and v not in visited_branch]
                if not nexts:
                    break
                # A branch may fork again; take the first (secondary forks are ignored)
                nxt = nexts[0]
                branch.append(nxt)
                local_visited.add(nxt)
                visited_branch.add(nxt)
                cur = nxt
            if len(branch) >= 2:
                branches.append(branch)
    return branches


def drop_skipstop_chords(adj, ratio_max):
    """Drop chords created by expresses skipping stations. Default ON.

    Previous behavior = SKELETON_DROP_CHORDS=0.

    A chord is an edge (a,b) such that another path from a to b exists that has at
    least one station between and is at most ratio_max times the straight-line
    distance: the two stations are ends of the same section, and the direct edge is
    an apparent adjacency because an express did not list the stations between.

    Edges with a very long detour are kept (e.g. direct ship services: 三島-高松 of
    大阪商船 is 61.5 km straight vs. 522.5 km via ports, a real separate route).

    Deterministic: candidates are sorted by (straight distance desc, stop ID) and
    dropped one at a time against the current graph (dropping all at once can
    disconnect the graph).
    Returns the dropped edges [(a, b, straight_km, detour_km, n_stations_between)].
    """
    def shortest_without(a, b):
        """(km, hops) of the shortest path not using edge (a,b); (inf, 0) if unreachable."""
        dist = {a: 0.0}
        hops = {a: 0}
        pq = [(0.0, a)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == b:
                return d, hops[u]
            if d > dist.get(u, float('inf')) + 1e-9:
                continue
            for v, w in adj[u].items():
                if (u == a and v == b) or (u == b and v == a):
                    continue
                nd = d + w
                if nd < dist.get(v, float('inf')) - 1e-9:
                    dist[v] = nd
                    hops[v] = hops[u] + 1
                    heapq.heappush(pq, (nd, v))
        return float('inf'), 0

    cands = []
    seen = set()
    for u in sorted(adj):
        for v in sorted(adj[u]):
            key = (u, v) if u < v else (v, u)
            if key in seen:
                continue
            seen.add(key)
            cands.append((adj[u][v], key))
    cands.sort(key=lambda x: (-x[0], x[1]))   # longest edges (likeliest chords) first

    dropped = []
    for direct_km, (a, b) in cands:
        if b not in adj.get(a, {}):
            continue
        alt_km, alt_hops = shortest_without(a, b)
        if alt_hops >= 2 and alt_km <= direct_km * ratio_max:
            del adj[a][b]
            del adj[b][a]
            dropped.append((a, b, direct_km, alt_km, alt_hops - 1))
    return dropped


# === Main processing ===

def detect_spurs(trip_orders, stops, threshold=0.9, min_trips=3, max_distance_km=2.0):
    """Detect one-stop spur stations.
    Conditions:
      1. Station S has exactly one neighbor N that is its immediate neighbor in at
         least `threshold` of its trips
      2. N and S are close (haversine <= max_distance_km; only typical spurs)
    Mainline stations have frequent neighbors on both sides (excluded by 1);
    termini far from the next station are excluded by 2.
    Returns {spur_sid: parent_sid}.
    """
    trip_count = defaultdict(int)
    trips_with_n_immediate = defaultdict(lambda: defaultdict(int))
    for sids in trip_orders:
        seen = set()
        for s in sids:
            if s in seen:
                continue
            seen.add(s)
            trip_count[s] += 1
        s_to_neighbors = defaultdict(set)
        for i, s in enumerate(sids):
            if i > 0 and sids[i - 1] != s:
                s_to_neighbors[s].add(sids[i - 1])
            if i < len(sids) - 1 and sids[i + 1] != s:
                s_to_neighbors[s].add(sids[i + 1])
        for s, ns in s_to_neighbors.items():
            for n in ns:
                trips_with_n_immediate[s][n] += 1
    spurs = {}
    for s, tc in trip_count.items():
        if tc < min_trips:
            continue
        candidates = trips_with_n_immediate.get(s, {})
        if not candidates:
            continue
        high_ratio = [n for n, c in candidates.items() if c / tc >= threshold]
        if len(high_ratio) != 1:
            continue
        parent = high_ratio[0]
        s_info = stops.get(s)
        p_info = stops.get(parent)
        if not (s_info and p_info and s_info.get('lat') is not None and p_info.get('lat') is not None):
            continue
        d = hav(s_info['lat'], s_info['lon'], p_info['lat'], p_info['lon'])
        if d > max_distance_km:
            continue
        spurs[s] = parent
    return spurs


def build_skeleton_for_line(line_name, trip_ids, trip_stops, stops):
    """Build the skeleton of one line."""
    # 1. Collect the station sequence of each trip (drop consecutive duplicates: arrival
    #    and departure can be two rows with the same stop_id)
    trip_orders = []
    all_stops = set()
    for tid in trip_ids:
        seq = trip_stops.get(tid, [])
        raw_sids = [s[1] for s in seq if s[1]]
        sids = []
        for sid in raw_sids:
            if sids and sids[-1] == sid:
                continue
            sids.append(sid)
        if not sids:
            continue
        trip_orders.append(sids)
        all_stops.update(sids)

    # 2. Spur detection (disabled: real spurs are hard to tell from mainline stations;
    #    a few lines such as 富田/富田濱 keep small fragments, but main lines stay intact)
    spurs = {}  # detect_spurs(trip_orders, stops) is not used

    # 3. Skip-stop test
    #    - observed_consecutive: skip spur-to-non-parent pairs (apparent adjacency via a spur)
    #    - has_intermediate: if all stations between are spurs, treat as "nothing between"
    observed_consecutive = set()
    has_intermediate = set()
    for sids in trip_orders:
        for i in range(len(sids) - 1):
            a, b = sids[i], sids[i + 1]
            if a == b:
                continue
            if a in spurs and spurs[a] != b:
                continue
            if b in spurs and spurs[b] != a:
                continue
            observed_consecutive.add(frozenset([a, b]))
        # Limit the has_intermediate search: express skips are usually 2-5 stations;
        # larger gaps are likely abnormal trips (reversals, wrong joins) and are ignored.
        MAX_INTERMEDIATE_GAP = 5
        for i in range(len(sids)):
            for j in range(i + 2, min(i + MAX_INTERMEDIATE_GAP + 1, len(sids))):
                if sids[i] == sids[j]:
                    continue
                intermediates = sids[i + 1:j]
                # Reversal / double visit: if sids[i] or sids[j] appears between, this is a
                # repeat within the trip, not a skip-stop
                if sids[i] in intermediates or sids[j] in intermediates:
                    continue
                non_spur = [s for s in intermediates if s not in spurs]
                if non_spur:
                    has_intermediate.add(frozenset([sids[i], sids[j]]))
    true_adjacent = observed_consecutive - has_intermediate
    skip_stop_pairs = observed_consecutive & has_intermediate

    # 3. Build the adjacency graph from true_adjacent (coordinates + absolute limit)
    abs_max = sanity_max(line_name)
    adj = defaultdict(dict)
    edges_kept = 0
    edges_skipstop = len(skip_stop_pairs)
    edges_sanity_dropped = 0
    edges_nocoord = 0
    max_kept_km = 0.0
    # Sort first: set order varies per run, and adj insertion order affects BFS neighbor order
    for edge in sorted(true_adjacent, key=lambda e: tuple(sorted(e))):
        sid1, sid2 = sorted(edge)
        s1 = stops.get(sid1)
        s2 = stops.get(sid2)
        if not (s1 and s2 and s1.get('lat') is not None and s2.get('lat') is not None):
            edges_nocoord += 1
            continue
        d = hav(s1['lat'], s1['lon'], s2['lat'], s2['lon'])
        if d > abs_max:
            edges_sanity_dropped += 1
            continue
        edges_kept += 1
        max_kept_km = max(max_kept_km, d)
        adj[sid1][sid2] = d
        adj[sid2][sid1] = d

    # 3.5 Drop chords created by express skips. Default ON.
    #     Previous behavior = SKELETON_DROP_CHORDS=0.
    edges_chord_dropped = 0
    if os.environ.get('SKELETON_DROP_CHORDS', '1') == '1':
        ratio_max = float(os.environ.get('SKELETON_CHORD_RATIO', '1.5'))
        dropped = drop_skipstop_chords(adj, ratio_max)
        edges_chord_dropped = len(dropped)
        edges_kept -= edges_chord_dropped
        if dropped:
            max_kept_km = max((d for a, b, d, *_ in
                               [(a, b, adj[a][b]) for a in adj for b in adj[a]]), default=0.0)

    # 3. Connected components
    nodes_in_graph = set()
    for sid, nbs in adj.items():
        nodes_in_graph.add(sid)
        for nb in nbs:
            nodes_in_graph.add(nb)
    isolated = all_stops - nodes_in_graph
    components = find_components(adj, sorted(nodes_in_graph))

    # 4. Extract polylines from each component
    polylines = []
    structure_tags = []
    for comp in components:
        if len(comp) < 2:
            continue
        comp_set = set(comp)
        degrees = {n: sum(1 for v in adj[n] if v in comp_set) for n in comp}
        endpoints = [n for n, d in degrees.items() if d == 1]
        junctions = [n for n, d in degrees.items() if d >= 3]

        if junctions:
            main = find_diameter_path(adj, comp_set)
            polylines.append(main)
            structure_tags.append('branched_main')
            branches = find_branches(adj, comp_set, main)
            for br in branches:
                polylines.append(br)
                structure_tags.append('branched_extra')
        elif not endpoints:
            # All nodes have degree 2 -> cycle
            cycle = trace_cycle(adj, comp_set)
            if len(cycle) >= 3:
                polylines.append(cycle)
                structure_tags.append('cycle')
        else:
            # Linear
            main = find_diameter_path(adj, comp_set)
            polylines.append(main)
            structure_tags.append('path')

    # Overall structure
    if len(polylines) == 0:
        overall = 'empty'
    elif len(components) > 1:
        overall = 'disconnected'
    elif 'branched_main' in structure_tags:
        overall = 'branched'
    elif 'cycle' in structure_tags:
        overall = 'cycle'
    else:
        overall = 'path'

    return {
        'structure': overall,
        'polylines': polylines,
        'structure_tags': structure_tags,
        'n_stops_total': len(all_stops),
        'n_stops_in_graph': len(nodes_in_graph),
        'n_components': len(components),
        'n_isolated': len(isolated),
        'isolated_stops': sorted(isolated),
        'edges_kept': edges_kept,
        'edges_skipstop': edges_skipstop,
        'edges_sanity_dropped': edges_sanity_dropped,
        'edges_nocoord': edges_nocoord,
        'max_edge_km': round(max_kept_km, 2),
    }


def polyline_to_coords(polyline, stops):
    """[stop_id, ...] -> [[lon, lat], ...] (stops without coordinates are skipped)"""
    coords = []
    for sid in polyline:
        s = stops.get(sid)
        if s and s.get('lat') is not None and s.get('lon') is not None:
            coords.append([s['lon'], s['lat']])
    return coords


def polyline_length_km(polyline, stops):
    total = 0.0
    prev = None
    for sid in polyline:
        s = stops.get(sid)
        if not s or s.get('lat') is None:
            continue
        if prev is not None:
            total += hav(prev['lat'], prev['lon'], s['lat'], s['lon'])
        prev = s
    return total


def main():
    print('=== build_line_skeleton.py ===')
    stops = load_stops()
    routes = load_routes()
    trips_by_line = load_trips_by_line()
    trip_stops = load_trip_stops()
    print(f'  Stops: {len(stops)}')
    print(f'  Routes: {len(routes)}')
    print(f'  Lines (from trips_master): {len(trips_by_line)}')
    print(f'  Trips with stop_times: {len(trip_stops)}')

    # Line name -> route_id (the last route wins when a line name has several).
    # Routes of frequency-only sections (`RQ...`, GTFS_FREQ_SECTIONS=1 in generate_gtfs) are
    #   skipped so they do not take the shape of the regular route with the same line name.
    route_id_for = {v: k for k, v in routes.items() if not str(k).startswith('RQ')}
    os.makedirs(OUT_DIR, exist_ok=True)

    features = []
    quality_rows = []
    stop_order_rows = []
    structure_counts = defaultdict(int)

    for line_name in sorted(trips_by_line.keys()):
        trip_ids = trips_by_line[line_name]
        skel = build_skeleton_for_line(line_name, trip_ids, trip_stops, stops)
        structure_counts[skel['structure']] += 1

        # GeoJSON geometry
        polylines_coords = [polyline_to_coords(p, stops) for p in skel['polylines']]
        polylines_coords = [pc for pc in polylines_coords if len(pc) >= 2]
        if len(polylines_coords) == 0:
            geom = None
        elif len(polylines_coords) == 1:
            geom = {'type': 'LineString', 'coordinates': polylines_coords[0]}
        else:
            geom = {'type': 'MultiLineString', 'coordinates': polylines_coords}

        total_km = sum(polyline_length_km(p, stops) for p in skel['polylines'])

        features.append({
            'type': 'Feature',
            'properties': {
                'line_name': line_name,
                'route_id': route_id_for.get(line_name, ''),
                'structure': skel['structure'],
                'n_stops': skel['n_stops_total'],
                'n_in_graph': skel['n_stops_in_graph'],
                'n_components': skel['n_components'],
                'n_isolated': skel['n_isolated'],
                'edges_kept': skel['edges_kept'],
                'edges_skipstop': skel['edges_skipstop'],
                'edges_sanity_dropped': skel['edges_sanity_dropped'],
                'edges_nocoord': skel['edges_nocoord'],
                'max_edge_km': skel['max_edge_km'],
                'length_km': round(total_km, 2),
                'n_polylines': len(polylines_coords),
            },
            'geometry': geom,
        })

        # quality report
        iso_names = '|'.join(stops[sid]['name'] for sid in skel['isolated_stops'][:5])
        quality_rows.append({
            'line_name': line_name,
            'route_id': route_id_for.get(line_name, ''),
            'structure': skel['structure'],
            'n_stops': skel['n_stops_total'],
            'n_in_graph': skel['n_stops_in_graph'],
            'n_components': skel['n_components'],
            'n_isolated': skel['n_isolated'],
            'edges_kept': skel['edges_kept'],
            'edges_skipstop': skel['edges_skipstop'],
            'edges_sanity_dropped': skel['edges_sanity_dropped'],
            'edges_nocoord': skel['edges_nocoord'],
            'max_edge_km': skel['max_edge_km'],
            'length_km': round(total_km, 2),
            'n_polylines': len(polylines_coords),
            'isolated_sample': iso_names,
        })

        # stop order
        for poly_idx, polyline in enumerate(skel['polylines']):
            for seq, sid in enumerate(polyline):
                stop_order_rows.append({
                    'line_name': line_name,
                    'polyline_idx': poly_idx,
                    'seq': seq,
                    'stop_id': sid,
                    'stop_name': stops[sid]['name'] if sid in stops else '',
                })

    # Output
    with open(OUT_GEOJSON, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': features},
                  f, ensure_ascii=False)
    print(f'\nWrote {OUT_GEOJSON} ({len(features)} features)')

    with open(OUT_QUALITY, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(quality_rows[0].keys()) if quality_rows else [])
        w.writeheader()
        for r in quality_rows:
            w.writerow(r)
    print(f'Wrote {OUT_QUALITY}')

    with open(OUT_STOP_ORDER, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['line_name', 'polyline_idx', 'seq', 'stop_id', 'stop_name'])
        w.writeheader()
        for r in stop_order_rows:
            w.writerow(r)
    print(f'Wrote {OUT_STOP_ORDER}')

    print('\n=== 構造分布 ===')
    for k, v in sorted(structure_counts.items(), key=lambda x: -x[1]):
        print(f'  {k}: {v}')

    # Details of sample lines
    print('\n=== サンプル路線 ===')
    sample_names = ['東海道本線', '山陽本線', '中央本線', '東北本線', '七尾線', '山手線']
    for fname in sample_names:
        for feat in features:
            if feat['properties']['line_name'] == fname:
                p = feat['properties']
                print(f"  {fname}: {p['structure']}, 駅{p['n_stops']}, "
                      f"成分{p['n_components']}, 孤立{p['n_isolated']}, "
                      f"エッジ採用{p['edges_kept']}/skip-stop除外{p['edges_skipstop']}"
                      f"/上限除外{p['edges_sanity_dropped']}/座標欠{p['edges_nocoord']}, "
                      f"最長{p['max_edge_km']}km, 線路長{p['length_km']}km")
                break


if __name__ == '__main__':
    main()
