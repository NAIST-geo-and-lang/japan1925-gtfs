#!/usr/bin/env python3
"""kb_tables.py — read the coordinate tables (data/knowledge/places/) as one row per query.

The coordinate tables are places.csv (places table), stop_place.csv (stop-place table) and derived.csv (derived values);
scripts/agent_knowledge.py looks up coordinates through the stop-place table. For tools that read the tables as a whole
(such as the coordinate gate, step 4e of build_release_all.sh), this module returns the stop-place rows joined with the
place values (stop_name, line_name, lat, lon, tolerance_km, note, coord_kind, coord_source, place_id, use, and the columns
of the published coordinate source table, built by rule in scripts/kb_sources.py).
Unregistered queries (empty coord_kind) are left out. Stations without coordinates have empty lat and lon.

  python3 scripts/kb_tables.py export <output CSV> [table folder]   # CSV with one row per query (for readers and other tools)

As a module:
  rows(tables=None)   -> [dict] (the form above)
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
COLUMNS = ['stop_name', 'line_name', 'lat', 'lon', 'tolerance_km', 'note', 'coord_kind', 'coord_source', 'place_id', 'use', 'ref_stop',
           'source_type', 'source_id', 'coord_class', 'coord_method', 'reference', 'reference_id', 'reference_label',
           'reference_distance_m', 'checked_within_km', 'reference_note', 'source_rev', 'source_item', 'source_read', 'distance_m',
           'point_kind']


def _join(places, entries):
    """Attach to the stop-place rows the place values and the columns of the published coordinate source table
    (built by rule in scripts/kb_sources.py)."""
    import kb_sources as ks
    out = []
    for e in entries:
        if not e.get('coord_kind'):
            continue
        p = places.get(e['place_id']) if e['place_id'] else None
        r = {c: e.get(c, '') for c in COLUMNS}
        r['lat'], r['lon'] = (p['lat'], p['lon']) if p else ('', '')
        if p is not None:
            for c in ('source_type', 'source_id', 'source_rev', 'source_item', 'source_read', 'distance_m', 'point_kind'):
                r[c] = p.get(c, '')
            if e.get('use') == 'adjacent' or p.get('source_type'):
                r.update({k: v for k, v in ks.release_columns(p, e).items() if k != 'ref_key'})
        out.append(r)
    return out


def rows(tables=None):
    import agent_knowledge as ak
    places, entries = ak.load_tables(tables)
    return _join(places, [entries[k] for k in sorted(entries)])


def main():
    if len(sys.argv) < 3 or sys.argv[1] != 'export':
        sys.exit(__doc__)
    out = sys.argv[2]
    rs = rows(sys.argv[3] if len(sys.argv) > 3 else None)
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator='\r\n')
        w.writeheader()
        w.writerows(rs)
    print(f'{out}: {len(rs)} 行（登録のある問い合わせ・座標を当てる {sum(1 for r in rs if r["lat"])}）')


if __name__ == '__main__':
    main()
