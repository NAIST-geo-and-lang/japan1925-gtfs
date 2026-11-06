"""
apply_agent_knowledge.py

Apply the coordinates of the coordinate tables (data/knowledge/places/, scripts/agent_knowledge.py) to stops_master.csv.
coord_source is written as given in the stop-place table (agent_known / release_proxy / wikidata / legacy:wikipedia_ja).
Stops if a station in the stop table is missing from the stop-place table (stop_place.csv), instead of falling back by
name to another station.

Also prints a WARN when stops_master has stations on external lines without a 〈region〉 tag
(to detect a skipped disambiguate_stations.py).
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_knowledge as _ak
from disambiguate_stations import detect_untagged_foreign

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOPS_MASTER = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'stops_master.csv')


def warn_untagged_foreign(rows):
    """Print a WARN for stations on external lines that are still untagged.
    Only UNIQUE_FOREIGN / FERRY matches are reported (external_line is too noisy).
    """
    issues = detect_untagged_foreign(rows)
    targeted = [(n, l, r) for (n, l, r) in issues
                if r in ('unique_foreign', 'ferry_foreign')]
    if not targeted:
        return
    print()
    print('=' * 70)
    print('WARN: 外地駅が untagged のまま残っています')
    print('  → scripts/disambiguate_stations.py を実行してから再度 apply してください')
    print('  → または scripts/run_pipeline.sh で一括処理可能')
    print('=' * 70)
    by_reason = {}
    for n, l, r in targeted:
        by_reason.setdefault(r, []).append((n, l))
    for r, items in by_reason.items():
        print(f'  [{r}] {len(items)} 件:')
        for n, l in items[:10]:
            print(f'    {n} on {l}')
        if len(items) > 10:
            print(f'    ... 他 {len(items) - 10} 件')


def main():
    print(f'座標KB の表: 対応 {len(_ak.ENTRIES)}（座標を当てる {sum(1 for e in _ak.ENTRIES.values() if e["place_id"])}）')

    with open(STOPS_MASTER, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    # Every station in the stop table must be in the stop-place table (stations without coordinates are allowed). Missing
    # stations are not matched to another row by name, so stop rather than silently leave them without coordinates
    # (the fix is to add them to the stop-place table)
    missing = sorted({(r['stop_name'], r['line_name']) for r in rows if not _ak.is_mapped(r['stop_name'], r['line_name'])})
    if missing:
        print(f'★★ 対応の表に無い驛 {len(missing)}（{_ak.PLACES_DIR}/stop_place.csv に行が要る）: '
              + '・'.join(f'{a}〔{b}〕' for a, b in missing[:20]) + ('…' if len(missing) > 20 else ''), file=sys.stderr)
        sys.exit(1)

    n = 0
    cleared = 0
    for r in rows:
        result = _ak.lookup(r['stop_name'], r['line_name'])
        if result:
            lat, lon, _tol, _note = result
            r['stop_lat'] = f'{lat:.6f}'
            r['stop_lon'] = f'{lon:.6f}'
            r['coord_source'] = _ak.coord_source(r['stop_name'], r['line_name'])
            n += 1
        elif r.get('coord_source') in _ak.COORD_SOURCES or r.get('coord_source', '').startswith('legacy:'):
            r['stop_lat'] = ''
            r['stop_lon'] = ''
            r['coord_source'] = 'none'
            cleared += 1

    print(f'適用: {n} 駅 / クリア: {cleared} 駅 (旧 agent_known で lookup miss)')

    with open(STOPS_MASTER, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f'更新: {STOPS_MASTER}')

    warn_untagged_foreign(rows)


if __name__ == '__main__':
    main()
