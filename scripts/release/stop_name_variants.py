#!/usr/bin/env python3
"""Station-name variants table of the published dataset, extras/stop_name_variants.csv (item 36 of build_release_gtfs.py).

GTFS stop_name has one spelling per station (the form chosen when integration unified old and new kanji, mostly the
1925 old forms), so a search in modern kanji misses it (下關, 龜山, 二日市驛前 …). For each station two columns are
listed; the six GTFS files are not changed.
  - name_shinjitai: stop_name with old kanji replaced by modern kanji (for search), using the per-character table
    scripts/release/shinjitai_map.csv (kyujipy's old-to-new mapping, reviewed for characters in station and line
    names). Same as stop_name if it has no old kanji.
  - printed_names: the spellings in the station-name column of the transcription (numbered workbooks) at the printed
    cells of the station's stops (arrival/departure sheet and row in extras/stop_time_source.csv), joined with "|"
    in descending order of cell count. Empty for stations with no printed cells (e.g. stops of frequency-only
    sections) and for parent stations (location_type=1): a parent groups nearby distinct stations, so its children's
    spellings would mix in names that are not variants (西大分 and 大分, 門司 and 關門). See the child rows instead.
The integration dictionary scripts/known_kanji_variants.py is not used to decide which form is old, because it also
contains misreading pairs.
"""
import csv
import os
import unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_CSV = os.path.join(HERE, 'shinjitai_map.csv')
FIELDS = ['stop_id', 'stop_name', 'location_type', 'name_shinjitai', 'printed_names']


def load_map(path=MAP_CSV):
    with open(path, encoding='utf-8', newline='') as f:
        return {r['old']: r['new'] for r in csv.DictReader(f)}


def to_shinjitai(s, m):
    return ''.join(m.get(ch, ch) for ch in unicodedata.normalize('NFC', s or ''))


def _read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def sheet_names(tripnum_dir):
    """For each sheet of the numbered workbooks, map column A stop_order to the column B station name
    (printed spelling, NFC-normalized only)."""
    import glob
    import openpyxl
    out = {}
    for fn in sorted(glob.glob(os.path.join(tripnum_dir, '*.xlsx'))):
        if os.path.basename(fn).startswith('~$'):
            continue
        wb = openpyxl.load_workbook(fn, read_only=True)
        for ws in wb.worksheets:
            d, body = {}, False
            for a, b in ws.iter_rows(max_col=2, values_only=True):
                if not body:
                    body = a == 'stop_order'
                    continue
                if not isinstance(b, str) or not b.strip():
                    continue
                try:
                    d[int(float(a))] = unicodedata.normalize('NFC', b.strip())
                except (TypeError, ValueError):
                    continue
            out[ws.title] = d
        wb.close()
    return out


def build(gtfs_dir, extras_dir, tripnum_dir):
    """Return the table rows, a summary (counts), and stations whose printed spelling differs from stop_name
    by more than glyph variants."""
    m = load_map()
    stops = _read(os.path.join(gtfs_dir, 'stops.txt'))
    sid_of = {(r['trip_id'], r['stop_sequence']): r['stop_id'] for r in _read(os.path.join(gtfs_dir, 'stop_times.txt'))}
    names = sheet_names(tripnum_dir)
    cells = defaultdict(set)        # stop_id -> {(sheet, row)}
    for r in _read(os.path.join(extras_dir, 'stop_time_source.csv')):
        sid = sid_of.get((r['trip_id'], r['stop_sequence']))
        if not sid:
            continue
        for g in ('arrival', 'departure'):
            if r.get(f'{g}_source') == 'printed' and r.get(f'{g}_sheet') and r.get(f'{g}_row'):
                cells[sid].add((r[f'{g}_sheet'], int(r[f'{g}_row'])))
    printed = defaultdict(Counter)  # stop_id -> spelling -> number of printed cells
    n_missing = 0
    for sid, cs in cells.items():
        for sheet, row in cs:
            nm = names.get(sheet, {}).get(row)
            if nm:
                printed[sid][nm] += 1
            else:
                n_missing += 1
    rows, odd = [], []
    for r in stops:
        sid = r['stop_id']
        cnt = Counter(printed.get(sid, {})) if r.get('location_type') != '1' else Counter()
        pn = [n for n, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))]
        base = to_shinjitai(r['stop_name'].split('〈')[0], m)
        if any(to_shinjitai(n, m) != base for n in pn):
            odd.append((sid, r['stop_name'], '|'.join(pn)))
        rows.append({'stop_id': sid, 'stop_name': r['stop_name'], 'location_type': r.get('location_type', ''),
                     'name_shinjitai': to_shinjitai(r['stop_name'], m), 'printed_names': '|'.join(pn)})
    summary = {
        'rows': len(rows),
        'name_shinjitai_differs': sum(1 for x in rows if x['name_shinjitai'] != x['stop_name']),
        'with_printed_names': sum(1 for x in rows if x['printed_names']),
        'two_or_more_printed_names': sum(1 for x in rows if '|' in x['printed_names']),
        'printed_cells_without_name': n_missing,
        'printed_differs_beyond_glyphs': len(odd),
    }
    return rows, summary, odd


def write(extras_dir, rows):
    with open(os.path.join(extras_dir, 'stop_name_variants.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


if __name__ == '__main__':   # try on a published-dataset folder (read-only; prints only the summary)
    import sys
    base = os.path.dirname(os.path.dirname(HERE))
    rel = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, 'data', 'gtfs_v1_release')
    rows, summary, odd = build(os.path.join(rel, 'gtfs'), os.path.join(rel, 'extras'),
                               os.path.join(base, 'data', '2_timetable_with_tripnum_v1'))
    print(summary)
    for o in odd[:40]:
        print('  ', *o)
