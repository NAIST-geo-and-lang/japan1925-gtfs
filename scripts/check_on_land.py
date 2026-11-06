"""
check_on_land.py

Check with the Natural Earth 10m land polygons whether each station's coordinates are on land,
and report the stations located at sea.

Dependency:
  shapely (point-in-polygon)

External data (downloaded on the first run):
  data/external/coastline/ne_10m_land.geojson  # Natural Earth 10m land
  data/external/coastline/ne_10m_minor_islands.geojson  # supplement (minor islands)

Input:
  data/4_integrated/stops_master.csv

Output:
  data/4_integrated/on_land_report.csv  # stations at sea (CSV)
  data/4_integrated/on_land_summary.md  # summary by line

Rules:
  - stop_type='port' is skipped (landing places are naturally next to the sea)
  - a station is judged to be at sea when it is not inside a land polygon
  - tolerance for small offsets: a station less than about 0.5 km from land counts as on land
"""

import csv
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from collections import defaultdict

from shapely.geometry import Point, shape
from shapely.prepared import prep
from shapely.ops import unary_union

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOPS_MASTER = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'stops_master.csv')
LAND_DIR = os.path.join(BASE_DIR, 'data', 'external', 'coastline')
LAND_FILE = os.path.join(LAND_DIR, 'ne_10m_land.geojson')
ISLANDS_FILE = os.path.join(LAND_DIR, 'ne_10m_minor_islands.geojson')

# Version pinned to v5.1.2; the md5 sums are the ones recorded in scripts/release/external_sources.csv.
LAND_URL = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_land.geojson'
LAND_MD5 = '24846ec719e08158ef49593f8b97ca21'
ISLANDS_URL = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_minor_islands.geojson'
ISLANDS_MD5 = 'daedaf5e6fdd7d85285e0066ee20e94d'

REPORT_CSV = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'on_land_report.csv')
REPORT_MD = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'on_land_summary.md')

# Allow small offsets: a station within TOLERANCE_DEG of the land polygon boundary counts as on land
# about 0.005 degrees ≈ 500 m
TOLERANCE_DEG = 0.005


def _md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fetch_if_missing(url, path, md5):
    """Download url to path when it is missing, and check its md5. The download goes to a temporary name first
    (with a timeout) and is renamed only when the md5 matches. An existing file is not overwritten; if its md5
    differs, the run stops (remove the file and run again to download it)."""
    if os.path.exists(path):
        got = _md5(path)
        if got != md5:
            sys.exit(f'md5 が記録と違うので使わない: {path} 記録 {md5} 手元 {got}（消して回し直すとダウンロードし直す）')
        return
    print(f'  ダウンロード: {url}')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.part'
    req = urllib.request.Request(url, headers={'User-Agent': 'japan1925-gtfs check_on_land'})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, 'wb') as f:
        shutil.copyfileobj(r, f, 1 << 20)
    got = _md5(tmp)
    if got != md5:
        sys.exit(f'ダウンロードしたファイルの md5 が記録と違う（使わない）: {url} 記録 {md5} 手元 {got}（{tmp}）')
    os.replace(tmp, path)
    size_mb = os.path.getsize(path) / 1_000_000
    print(f'  保存: {path} ({size_mb:.1f} MB)')


def load_land():
    fetch_if_missing(LAND_URL, LAND_FILE, LAND_MD5)
    fetch_if_missing(ISLANDS_URL, ISLANDS_FILE, ISLANDS_MD5)
    geoms = []
    for path in (LAND_FILE, ISLANDS_FILE):
        with open(path, encoding='utf-8') as f:
            gj = json.load(f)
        for feat in gj['features']:
            geoms.append(shape(feat['geometry']))
    merged = unary_union(geoms)
    # land area expanded by the tolerance (buffer)
    expanded = merged.buffer(TOLERANCE_DEG)
    return prep(expanded), merged


def main():
    print('=== check_on_land.py ===')
    print(f'  陸上 polygon を準備 (10m, tolerance={TOLERANCE_DEG} deg ≒ 500m)')
    land_prepared, land_raw = load_land()
    print('  陸上判定準備 OK')

    issues = []
    n_checked = 0
    n_port_skipped = 0
    with open(STOPS_MASTER, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if not r.get('stop_lat') or not r.get('stop_lon'):
                continue
            try:
                lat = float(r['stop_lat'])
                lon = float(r['stop_lon'])
            except ValueError:
                continue
            if (r.get('stop_type') or '').lower() == 'port':
                n_port_skipped += 1
                continue
            n_checked += 1
            pt = Point(lon, lat)
            if not land_prepared.contains(pt):
                # at sea or beyond the tolerance; measure the distance to the raw land (degrees) to judge false positives
                dist_deg = pt.distance(land_raw)
                issues.append({
                    'stop_id': r['stop_id'],
                    'stop_name': r['stop_name'],
                    'line_name': r['line_name'],
                    'lat': lat,
                    'lon': lon,
                    'coord_source': r.get('coord_source', ''),
                    'dist_to_land_deg': round(dist_deg, 5),
                    'dist_to_land_km_approx': round(dist_deg * 111.0, 2),
                })

    print(f'  検査駅数: {n_checked} (port {n_port_skipped} 駅は対象外)')
    print(f'  海上判定駅: {len(issues)}')

    # CSV output
    with open(REPORT_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'stop_id', 'stop_name', 'line_name', 'lat', 'lon',
            'coord_source', 'dist_to_land_deg', 'dist_to_land_km_approx',
        ])
        w.writeheader()
        for r in sorted(issues, key=lambda x: -x['dist_to_land_km_approx']):
            w.writerow(r)
    print(f'  CSV: {REPORT_CSV}')

    # Markdown summary
    by_line = defaultdict(list)
    for r in issues:
        by_line[r['line_name']].append(r)
    with open(REPORT_MD, 'w', encoding='utf-8') as f:
        f.write('# 海上駅検出レポート\n\n')
        f.write(f'検査対象: {n_checked} 駅（port {n_port_skipped} 駅は除外）\n\n')
        f.write(f'海上判定: **{len(issues)} 駅** / {len(by_line)} 路線\n\n')
        f.write(f'許容距離: {TOLERANCE_DEG} 度 ≒ {TOLERANCE_DEG * 111:.1f} km\n\n')
        f.write('## 路線別\n\n')
        for ln in sorted(by_line.keys(), key=lambda l: -len(by_line[l])):
            rs = by_line[ln]
            f.write(f'### {ln} ({len(rs)} 駅)\n\n')
            f.write('| 駅 | 緯度 | 経度 | 陸への距離 (km) | 座標出典 |\n')
            f.write('|---|---|---|---|---|\n')
            for r in sorted(rs, key=lambda x: -x['dist_to_land_km_approx']):
                f.write(f'| {r["stop_name"]} | {r["lat"]:.4f} | {r["lon"]:.4f} | '
                        f'{r["dist_to_land_km_approx"]} | {r["coord_source"]} |\n')
            f.write('\n')
    print(f'  サマリ: {REPORT_MD}')

    if issues:
        print('\n海上駅 (先頭 10、陸からの距離降順):')
        for r in sorted(issues, key=lambda x: -x['dist_to_land_km_approx'])[:10]:
            print(f'  {r["stop_name"]:>10} ({r["line_name"]:<20}) '
                  f'{r["lat"]:.4f},{r["lon"]:.4f}  '
                  f'{r["dist_to_land_km_approx"]:>6} km from land  '
                  f'[{r["coord_source"]}]')


if __name__ == '__main__':
    main()
