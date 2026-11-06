#!/usr/bin/env python3
"""
extras/route_lines.geojson of the published dataset: route lines for drawing maps.
Called from item 20 of scripts/build_release_gtfs.py (RELEASE_ROUTE_LINES = path of the skeleton file; empty = no file).

Content: the line skeletons of scripts/build_line_skeleton.py (one per line name, built from adjacent station pairs
of printed trips, with the straight chords of express trips that skip stations removed).
They are not track shapes, only straight segments between stations. They are kept out of GTFS shapes.txt; in a
separate file GTFS software does not read them, so trip distances are not distorted.
  - The skeleton must be built from the published coordinates (build_release_all.sh passes
    track_geometry/line_skeletons.geojson of its work folder). Every vertex must match a station coordinate in the
    published stops.txt; otherwise stop.
  - Line names without a shape (structure=empty) are left out (with FILL_EMPTY, they are built from adjacent station
    pairs of the published trips; item 32).
  - route_ids: space-separated routes of the line name (excluding frequency-only routes RQ…, which the skeleton
    does not use). relabel_stable_ids rewrites them to published IDs (it also reads route_ids in the .geojson).
"""
import json
import os

KEEP = ('structure', 'n_stops', 'length_km')
# Add line names without a skeleton shape (structure=empty), built from adjacent station pairs of the published trips
#   (item 32). The skeleton is built from the integrated output, before estimated terminal arrivals are added to
#   departure-only tables, so lines such as those of departure-only tables have no shape. Initial value False =
#   previous behavior (left out); build_release_gtfs.py sets it from RELEASE_ROUTE_LINES_FILL_EMPTY.
FILL_EMPTY = False


def _haversine_km(lon1, lat1, lon2, lat2):
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _from_trips(seqs, xy):
    """Build lines whose edges are adjacent station pairs of trip stop sequences (lists of stop_id).
    Return (geometry, structure, n_stops, length_km) or None."""
    from collections import defaultdict
    edges = set()
    for seq in seqs:
        for a, b in zip(seq, seq[1:]):
            pa, pb = xy.get(a), xy.get(b)
            if pa and pb and pa != pb:
                edges.add(tuple(sorted((pa, pb))))
    if not edges:
        return None
    adj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    # split each connected component into lines, walking edges from degree-1 nodes (else the smallest node)
    seen_e, parts = set(), []
    for start in sorted(adj, key=lambda q: (len(adj[q]) != 1, q)):
        for nb in sorted(adj[start]):
            e = tuple(sorted((start, nb)))
            if e in seen_e:
                continue
            line, cur, prev = [start], start, None
            nxt = nb
            while True:
                seen_e.add(tuple(sorted((cur, nxt))))
                line.append(nxt)
                prev, cur = cur, nxt
                cand = [q for q in sorted(adj[cur]) if q != prev and tuple(sorted((cur, q))) not in seen_e]
                if len(adj[cur]) != 2 or not cand:
                    break
                nxt = cand[0]
            parts.append(line)
    comps, seen_n = 0, set()
    for s in sorted(adj):
        if s in seen_n:
            continue
        comps += 1
        stack = [s]
        while stack:
            q = stack.pop()
            if q in seen_n:
                continue
            seen_n.add(q)
            stack.extend(adj[q] - seen_n)
    n_edges, n_nodes = len(edges), len(adj)
    structure = ('disconnected' if comps > 1 else 'cycle' if n_edges >= n_nodes
                 else 'branched' if any(len(v) > 2 for v in adj.values()) else 'path')
    length = sum(_haversine_km(a[0], a[1], b[0], b[1]) for a, b in edges)
    coords = [[list(q) for q in line] for line in parts]
    geom = ({'type': 'LineString', 'coordinates': coords[0]} if len(coords) == 1
            else {'type': 'MultiLineString', 'coordinates': coords})
    return geom, structure, n_nodes, round(length, 3)


def build(src, routes_rows, stops_rows, out_path, trip_seqs=None):
    """Write out_path from the skeleton src and return a summary.
    trip_seqs = {line name: [stop_id sequence of a trip, …]} (with FILL_EMPTY, used to build line names without a shape)."""
    with open(src, encoding='utf-8') as f:
        sk = json.load(f)
    ids_of = {}
    for r in routes_rows:
        if r['route_id'].startswith('RQ'):
            continue
        ids_of.setdefault(r['route_short_name'], []).append(r['route_id'])
    pub = {(round(float(r['stop_lon']), 6), round(float(r['stop_lat']), 6))
           for r in stops_rows if r.get('stop_lat') and r.get('stop_lon')}
    feats, n_empty, n_vert, bad = [], 0, 0, []
    xy = {r['stop_id']: (round(float(r['stop_lon']), 6), round(float(r['stop_lat']), 6))
          for r in stops_rows if r.get('stop_lat') and r.get('stop_lon')}
    n_filled = []
    for ft in sk['features']:
        g = ft.get('geometry')
        p = ft['properties']
        if not g and FILL_EMPTY and trip_seqs and trip_seqs.get(p['line_name']):
            made = _from_trips(trip_seqs[p['line_name']], xy)
            if made:
                g = made[0]
                ft = {'type': 'Feature', 'geometry': g,
                      'properties': dict(p, structure=made[1], n_stops=made[2], length_km=made[3])}
                p = ft['properties']
                n_filled.append(p['line_name'])
        if not g:
            n_empty += 1
            continue
        pts = g['coordinates'] if g['type'] == 'LineString' else [q for line in g['coordinates'] for q in line]
        for x, y in pts:
            n_vert += 1
            if (round(x, 6), round(y, 6)) not in pub:
                bad.append((p['line_name'], x, y))
        props = {'route_short_name': p['line_name'],
                 'route_ids': ' '.join(sorted(ids_of.get(p['line_name'], [])))}
        for k in KEEP:
            props[k] = p.get(k, '')
        feats.append({'type': 'Feature', 'properties': props, 'geometry': g})
    if bad:
        raise SystemExit(f'路線の線: 公開版の駅の座標に無い頂点がある（公開できない座標の疑い）: {bad[:5]}')
    no_route = [f['properties']['route_short_name'] for f in feats if not f['properties']['route_ids']]
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    return {'lines': len(feats), 'empty_skipped': n_empty, 'vertices': n_vert, 'no_route': no_route,
            'filled_from_trips': n_filled}


def relabel(path, m_route):
    """Rewrite each ID in route_ids to its published ID (called from relabel_stable_ids)."""
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    for ft in d['features']:
        ids = ft['properties'].get('route_ids', '')
        ft['properties']['route_ids'] = ' '.join(sorted(m_route.get(x, x) for x in ids.split()))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')


def check_public_ids(path):
    import re
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    left = [x for ft in d['features'] for x in ft['properties'].get('route_ids', '').split() if not re.match(r'RT\d', x)]
    if left:
        raise SystemExit(f'路線の線に内部の番号が残っている: {left[:5]}')
