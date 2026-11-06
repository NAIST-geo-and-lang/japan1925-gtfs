"""
generate_shapes.py

Write GTFS shapes.txt and add shape_id to trips.txt.

Takes one representative polyline per route from line_skeletons.geojson and writes
one shape_id per route. All trips of a route share that shape_id regardless of
direction (the track is physically shared).

Method:
  - Read each feature's geometry
  - LineString: use as is
  - MultiLineString: use the longest LineString (a GTFS shape is one linear sequence;
    branches are not represented here)
  - shape_dist_traveled: cumulative haversine distance in km

Prerequisite:
  Run scripts/build_line_skeleton.py first to create line_skeletons.geojson.

Output:
  data/gtfs/shapes.txt
  data/gtfs/trips.txt (rewritten with a shape_id column)
"""

import csv
import json
import math
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GTFS_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs'))
GEOJSON_PATH = os.path.join(BASE_DIR, 'data', os.environ.get('TRACK_GEOMETRY_DIR', 'track_geometry'), 'line_skeletons.geojson')
TRIPS_TXT = os.path.join(GTFS_DIR, 'trips.txt')
SHAPES_TXT = os.path.join(GTFS_DIR, 'shapes.txt')


def hav(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def line_length_km(coords):
    total = 0.0
    for i in range(len(coords) - 1):
        total += hav(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])
    return total


def select_main_polyline(geom):
    """Return a LineString as is, or the longest part of a MultiLineString."""
    if not geom:
        return None
    if geom['type'] == 'LineString':
        return geom['coordinates']
    if geom['type'] == 'MultiLineString':
        if not geom['coordinates']:
            return None
        return max(geom['coordinates'], key=line_length_km)
    return None


def main():
    print('=== generate_shapes.py ===')
    if not os.path.exists(GEOJSON_PATH):
        print(f'  ERROR: {GEOJSON_PATH} が存在しません。')
        print(f'  先に scripts/build_line_skeleton.py を実行してください。')
        sys.exit(1)

    with open(GEOJSON_PATH, encoding='utf-8') as f:
        geojson = json.load(f)

    shape_id_for_route = {}        # route_id -> shape_id
    shape_points = []              # (shape_id, seq, lat, lon, cum_km)
    n_main_from_multi = 0
    n_skipped_empty = 0

    for feat in geojson['features']:
        p = feat['properties']
        route_id = p.get('route_id', '')
        if not route_id:
            continue
        geom = feat.get('geometry')
        main_coords = select_main_polyline(geom)
        if not main_coords or len(main_coords) < 2:
            n_skipped_empty += 1
            continue
        if geom and geom['type'] == 'MultiLineString':
            n_main_from_multi += 1
        shape_id = f'SHP_{route_id}'
        shape_id_for_route[route_id] = shape_id
        cum = 0.0
        prev = None
        for seq, coord in enumerate(main_coords, start=1):
            lon, lat = coord[0], coord[1]
            if prev is not None:
                cum += hav(prev[1], prev[0], lat, lon)
            shape_points.append((shape_id, seq, lat, lon, cum))
            prev = (lon, lat)

    print(f'  Shapes: {len(shape_id_for_route)} routes')
    print(f'  Shape points: {len(shape_points)}')
    print(f'  MultiLineString → 最長採用: {n_main_from_multi} 路線')
    print(f'  geometry なしで skip: {n_skipped_empty} 路線')

    # Write shapes.txt
    with open(SHAPES_TXT, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence', 'shape_dist_traveled'])
        for sid, seq, lat, lon, cum in shape_points:
            w.writerow([sid, f'{lat:.6f}', f'{lon:.6f}', seq, f'{cum:.4f}'])
    print(f'  Wrote {SHAPES_TXT}')

    # Update shape_id in trips.txt
    with open(TRIPS_TXT, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        trip_fields = list(reader.fieldnames)
        trips = list(reader)
    if 'shape_id' not in trip_fields:
        trip_fields.append('shape_id')
    with open(TRIPS_TXT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=trip_fields)
        w.writeheader()
        for t in trips:
            t['shape_id'] = shape_id_for_route.get(t['route_id'], '')
            w.writerow(t)
    n_with_shape = sum(1 for t in trips if t.get('shape_id'))
    print(f'  Updated {TRIPS_TXT}: shape_id 付き {n_with_shape}/{len(trips)} trips')


if __name__ == '__main__':
    main()
