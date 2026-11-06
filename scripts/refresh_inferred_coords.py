"""refresh_inferred_coords.py — clear only interpolated coordinates so that they are computed again

Clears the coordinates in `stops_master.csv` that come from interpolation (coord_source = inferred / legacy:inferred).
Coordinates from other sources (agent_known and the legacy:* labels) and intentionally dropped `nullified_*` values
are not touched.

## Why

`generate_gtfs.build_stops_master` carries over the coordinates of the existing stops_master, and `infer_coords` fills
only stations without coordinates. Without clearing, interpolated coordinates keep their old positions even after the
distance lookup or the coordinate tables change.

## Usage

    python3 scripts/refresh_inferred_coords.py            # clear
    python3 scripts/refresh_inferred_coords.py --dry-run  # count only

Normally not run on its own: `run_pipeline.sh` calls it before generate_gtfs (default ON; previous behavior =
`--no-refresh-coords`).

Environment variables:
  INTEGRATED_DIR   directory holding stops_master.csv (default 4_integrated; absolute paths allowed)
"""

import csv
import os
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOPS_MASTER = os.path.join(
    BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'stops_master.csv')

# Clear only coordinates made by interpolation; authoritative ones cannot be reproduced, so they are kept.
REFRESH_SOURCES = ('inferred', 'legacy:inferred')


def main():
    dry_run = '--dry-run' in sys.argv[1:]
    for a in sys.argv[1:]:
        if a != '--dry-run':
            print(f'Unknown option: {a}', file=sys.stderr)
            return 1

    if not os.path.exists(STOPS_MASTER):
        # first run (no stops_master yet): nothing to clear, no-op
        print(f'refresh_inferred_coords: {STOPS_MASTER} が無い — skip')
        return 0

    with open(STOPS_MASTER, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if 'coord_source' not in fieldnames:
        print('refresh_inferred_coords: coord_source 列が無い — skip')
        return 0

    hit = Counter()
    for r in rows:
        if (r.get('coord_source') or '').strip() in REFRESH_SOURCES:
            hit[r['coord_source']] += 1
            if not dry_run:
                r['stop_lat'] = ''
                r['stop_lon'] = ''
                r['coord_source'] = ''

    n = sum(hit.values())
    detail = '・'.join(f'{k} {v}' for k, v in sorted(hit.items())) or 'なし'
    if dry_run:
        print(f'refresh_inferred_coords [dry-run]: 対象 {n} 駅 / 全 {len(rows)} 駅（{detail}）')
        return 0

    with open(STOPS_MASTER, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f'内挿座標を消去: {n} 駅 / 全 {len(rows)} 駅（{detail}）'
          f' → 距離 lookup と座標KB から引き直す')
    print(f'更新: {STOPS_MASTER}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
