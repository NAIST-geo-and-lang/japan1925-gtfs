#!/usr/bin/env python3
"""Write the derived tables (extras) to GTFS_DIR. The six GTFS files are not changed.

Outputs (all directly in GTFS_DIR, UTF-8, with headers):
  trip_attributes.csv   ... per-trip train type (急行 express / 特急 limited express), classes, sleeper, dining car,
                            parsed from rows 8/9 of the workbooks before train numbering
  service_frequency.csv ... per-trip sailing frequency for ships (daily / N days a month / odd or even days / days
                            without sailing), from 【運航頻度】 in the row-12 transcriber's notes of the workbooks
  line_region.csv       ... region per line (朝鮮, 滿洲, 支那, 臺灣, 樺太, 露領, 北海道, 内地), from
                            disambiguate_stations.classify_line()
  stop_time_system.csv  ... time system of stop_times rows outside the default (see build_stop_time_system)
  frequency_only.csv    ... sections with no timetable grid in the original, only frequency text (copy of the hand
                            transcription data/tables/frequency_only/frequency_only.csv)

Inputs:
  INTEGRATED_DIR/integrated_stop_times.csv ... gtfs_trip_key -> (source_sheet, trip_num)
  GTFS_DIR/routes.txt                      ... route_id -> line_name
  data/TRIPNUM_DIR/*.xlsx (default 2_timetable_with_tripnum_v1) ... columns located by trip_num in row 9
  data/RAW_XLSX_DIR/*.xlsx (default 1_timetable_xlsx_v1,1_timetable_xlsx_added_v1; comma-separated) ... original text
      of trip_label_header (row 8) and trip_label (row 9)

Environment variables (same conventions as the other scripts): GTFS_DIR, INTEGRATED_DIR, TRIPNUM_DIR, RAW_XLSX_DIR
(relative paths are under data/, absolute paths are used as is)
"""
import csv
import os
import re
import sys
import unicodedata
from collections import defaultdict

import openpyxl

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
import disambiguate_stations as ds  # noqa: E402

GTFS_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs'))
INT_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'))
TRIPNUM_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('TRIPNUM_DIR', '2_timetable_with_tripnum_v1'))
RAW_XLSX_DIRS = [os.path.join(BASE_DIR, 'data', d) for d in
            os.environ.get('RAW_XLSX_DIR', '1_timetable_xlsx_v1,1_timetable_xlsx_added_v1').split(',')]
FREQ_ONLY_SRC = os.path.join(BASE_DIR, 'data', 'tables', 'frequency_only', 'frequency_only.csv')

SHIP_LINE_RE = re.compile(r'航路|汽船|連絡船|聯絡船|連絡|商船')
# Also include in the sailing frequency table ship routes (route_type 4 in routes.txt) whose line names do not match
#   SHIP_LINE_RE, and pick up no-sailing notes (休航) from the transcriber's notes even in tables without frequency words.
#   Default ON. Previous behavior = EXTRAS_SHIP_BY_ROUTE_TYPE=0.
SHIP_BY_ROUTE_TYPE = os.environ.get('EXTRAS_SHIP_BY_ROUTE_TYPE', '1') != '0'
# Do not pick up no-sailing notes from the "【ページ全体】" (whole page) paragraph of the transcriber's notes, and classify
#   the frequency after removing the no-sailing proviso. Default ON. Previous behavior = EXTRAS_SHIP_FREQ_STRICT=0.
SHIP_FREQ_STRICT = os.environ.get('EXTRAS_SHIP_FREQ_STRICT', '1') != '0'
# Recognize tables with sailing dates printed per column not only by "型B" and "マス目が月日" in the transcriber's notes
#   but also by "マス目は月日" and "マス目に入るのは時刻でなく月日". Default ON. Previous behavior = EXTRAS_SHIP_DATE_GRID_WORDS=0.
SHIP_DATE_GRID_WORDS = os.environ.get('EXTRAS_SHIP_DATE_GRID_WORDS', '1') != '0'
_DATE_GRID_RE = re.compile(r'マス目(?:が|は|に入るのは時刻でなく)月日')


def ship_lines_by_route_type():
    """Line names (route_short_name) of routes with route_type 4 (ship) in routes.txt."""
    path = os.path.join(GTFS_DIR, 'routes.txt')
    if not os.path.exists(path):
        return set()
    with open(path, encoding='utf-8-sig') as f:
        return {r['route_short_name'] for r in csv.DictReader(f) if r.get('route_type') == '4'}


def nfc(s):
    return unicodedata.normalize('NFC', s)


def cell(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


# ---------------------------------------------------------------- reading the transcription sheets
class Sheet:
    __slots__ = ('title', 'file', 'line_name', 'table_name', 'direction_raw', 'direction',
                 'trip_ids', 'trip_nums', 'label_header', 'label_section', 'memo')


def load_sheets():
    """Read all sheets of the workbooks and overlay the original text of rows 8/9 from the workbooks before train
    numbering. title -> Sheet"""
    sheets = {}
    raw_files = {}
    for d in RAW_XLSX_DIRS:
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith('.xlsx') and not fn.startswith('~$'):
                    raw_files[nfc(fn)] = os.path.join(d, fn)
    n_raw_missing = 0
    for fn in sorted(os.listdir(TRIPNUM_DIR)):
        if not fn.endswith('.xlsx') or fn.startswith('~$'):
            continue
        wb = openpyxl.load_workbook(os.path.join(TRIPNUM_DIR, fn), read_only=True)
        raw_path = raw_files.get(nfc(fn))
        wb_raw = openpyxl.load_workbook(raw_path, read_only=True) if raw_path else None
        if wb_raw is None:
            n_raw_missing += 1
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(min_row=1, max_row=12, values_only=True))
            if len(rows) < 12 or cell(rows[0][0]) != 'table_id':
                continue
            s = Sheet()
            s.title = ws.title
            s.file = fn
            s.table_name = cell(rows[2][1])
            s.line_name = cell(rows[3][1])
            s.direction_raw = cell(rows[4][1])
            s.direction = cell(rows[5][1])
            s.trip_ids = [cell(c) for c in rows[6][1:]]
            s.trip_nums = [cell(c) for c in rows[8][1:]]
            hdr2 = [cell(c) for c in rows[7][1:]]
            s.memo = ' '.join(cell(c) for c in rows[11][1:] if cell(c))
            s.label_header = hdr2
            s.label_section = [''] * len(hdr2)
            if wb_raw is not None and ws.title in wb_raw.sheetnames:
                rr = list(wb_raw[ws.title].iter_rows(min_row=7, max_row=9, values_only=True))
                if len(rr) == 3:
                    tid_raw = [cell(c) for c in rr[0][1:]]
                    if [t for t in tid_raw if t] != [t for t in s.trip_ids if t]:
                        print(f'  WARN trip_id 行が番号を付ける前のワークブックとワークブックで食い違う: {ws.title}', file=sys.stderr)
                    else:
                        s.label_header = [cell(c) for c in rr[1][1:]]
                        s.label_section = [cell(c) for c in rr[2][1:]]
            # equalize the lengths
            n = max(len(s.trip_ids), len(s.trip_nums), len(s.label_header), len(s.label_section))
            for attr in ('trip_ids', 'trip_nums', 'label_header', 'label_section'):
                v = getattr(s, attr)
                setattr(s, attr, v + [''] * (n - len(v)))
            sheets[ws.title] = s
    if n_raw_missing:
        print(f'  番号を付ける前のワークブックが見つからないファイル {n_raw_missing}（行8／行9 はワークブックの行8 だけで代用）', file=sys.stderr)
    return sheets


def columns_for(sheet, trip_num):
    """Indices of the columns in the sheet that carry trip_num (possibly several). Up..._N keys are looked up by trip_id N."""
    m = re.fullmatch(r'Up\d{4}_tb\d{3}(?:-\d+)*_(\d+)', trip_num)
    if m:
        return [i for i, t in enumerate(sheet.trip_ids) if t == m.group(1)]
    base = re.sub(r'_[a-z]$', '', trip_num)   # fragments _b / _c are in the same column
    return [i for i, t in enumerate(sheet.trip_nums) if t == base]


# ---------------------------------------------------------------- 1. train type
CLASS_RE = re.compile(r'^(\d(?:\.\d)*)$')
CLASS_KYU_RE = re.compile(r'^(\d(?:\.\d)*)急$')
TOKU_RE = re.compile(r'^特\d*$')


def label_numbers(label):
    """Train numbers in a label (pure-number tokens and the N of 特N). The 3 of 3急 is a class, so it is not included."""
    nums = set()
    for tok in re.split(r'[/／]', label or ''):
        tok = tok.strip()
        if re.fullmatch(r'\d+', tok):
            nums.add(tok)
        m = re.fullmatch(r'[特急](\d+)', tok)
        if m:
            nums.add(m.group(1))
    return nums


def parse_label(label, acc, own=None):
    """Fold a train label (e.g. 3急/特/3・寝/食/1.2.3/7・特1・急) into acc.
    With own (the trip's number), a label whose train numbers do not include own is skipped, so that 特 / 急 in a
    two-tier header (upper tier = number of the connecting or upstream train) is not given to another train."""
    if not label:
        return
    nums = label_numbers(label)
    if own is not None and nums and own not in nums:
        acc['skipped'].add(label)
        return
    for tok in re.split(r'[/／]', label):
        tok = tok.strip()
        if not tok:
            continue
        m = CLASS_KYU_RE.match(tok)
        if m:
            acc['express'] = True
            acc['classes'].update(m.group(1).split('.'))
            continue
        if TOKU_RE.match(tok):
            acc['limited'] = True
            continue
        if tok in ('急', '急行') or re.fullmatch(r'急\d+', tok):   # 急4 = express train 4
            acc['express'] = True
            continue
        if tok in ('寝', '寢'):
            acc['sleeper'] = True
            continue
        if tok == '食':
            acc['diner'] = True
            continue
        m = CLASS_RE.match(tok)
        if m and '.' in tok:
            acc['classes'].update(tok.split('.'))
            continue
        if re.fullmatch(r'\d+', tok):
            continue   # the train number itself
        acc['other'].add(tok)


def _line_stem(line):
    return re.sub(r'(本線|線)$', '', line)


def other_sheets_for(sheets, line, direction, trip_num, exclude):
    """Sheets with the same line, direction and number that integration did not use (summary tables, connection tables,
    bands with combined line names). Type marks are sometimes printed only in a summary table's header, so these are read
    only when the used sheets have no label."""
    stem = _line_stem(line)
    out = []
    for title, s in sheets.items():
        if title in exclude or s.direction != direction:
            continue
        ln = s.line_name
        if ln == line:
            pass
        elif re.search(r'[及・、]', ln) and stem and stem in ln and not re.search(r'[及・、]', line):
            pass   # listed as a component of a band with a combined line name
        else:
            continue
        if columns_for(s, trip_num):
            out.append(title)
    return sorted(out)


def build_trip_attributes(sheets, trip_sources):
    out = []
    n_kind = 0
    n_other = 0
    for key in sorted(trip_sources):
        line, direction, trip_num = key.split('__', 2)
        acc = {'express': False, 'limited': False, 'sleeper': False, 'diner': False,
               'classes': set(), 'other': set(), 'skipped': set()}
        own = re.sub(r'_[a-z]$', '', trip_num)
        headers, sections, srcs, notes = [], [], [], []

        def take(s, cols):
            for c in cols:
                h, sec = s.label_header[c], s.label_section[c]
                if h and h not in headers:
                    headers.append(h)
                if sec and sec not in sections:
                    sections.append(sec)
                parse_label(h, acc, own)
                parse_label(sec, acc, own)

        for sheet_title, tn in sorted(trip_sources[key]):
            s = sheets.get(sheet_title)
            if s is None:
                notes.append(f'シート {sheet_title} がワークブックに無い')
                continue
            cols = columns_for(s, tn)
            if not cols:
                notes.append(f'{sheet_title} に trip_num {tn} の列が無い')
                continue
            if len(cols) > 1:
                notes.append(f'{sheet_title} に trip_num {tn} の列が {len(cols)} 本（同番号）')
            srcs.append(sheet_title)
            take(s, cols)
        if (not headers and not sections and not trip_num.startswith('Up')
                and not re.search(r'_[a-z]$', trip_num)):   # a _b fragment may be another train, so do not widen
            others = other_sheets_for(sheets, line, direction, trip_num, set(srcs))
            for title in others:
                take(sheets[title], columns_for(sheets[title], trip_num))
            if headers or sections:
                n_other += 1
                notes.append('表記は採用外シートから: ' + '|'.join(others))
        kind = '特急' if acc['limited'] else ('急行' if acc['express'] else '')
        if kind:
            n_kind += 1
        if acc['skipped']:
            notes.append('番号が合わないので読まなかった表記: ' + '|'.join(sorted(acc['skipped'])))
        out.append({
            'trip_key': key, 'line_name': line, 'direction': direction, 'trip_num': trip_num,
            'kind': kind,
            'classes': '.'.join(sorted(acc['classes'])),
            'sleeper': '1' if acc['sleeper'] else '',
            'diner': '1' if acc['diner'] else '',
            'label_header': '|'.join(headers),
            'label_section': '|'.join(sections),
            'other_tokens': '|'.join(sorted(acc['other'])),
            'source_sheets': '|'.join(srcs),
            'note': '；'.join(notes),
        })
    print(f'    採用外シートから表記を引いたトリップ {n_other}')
    return out, n_kind


# ---------------------------------------------------------------- 2. sailing frequency
FREQ_RE = re.compile(r'【運航頻度】([^【]*)')


def classify_frequency(text):
    if not text:
        return ''
    if SHIP_FREQ_STRICT:   # (2) do not classify by words inside a no-sailing proviso (e.g. "但　毎月十六日及月末日ハ休航")
        text = re.sub(r'[^。／「」]*休航[^。／」]*', '', text)
    if '奇數日' in text and '偶數日' in text:
        return '隔日（方向で奇數日／偶數日）'
    if '奇數日' in text:
        return '隔日（奇數日）'
    if '偶數日' in text:
        return '隔日（偶數日）'
    if '毎月' in text:
        return '毎月（指定日）'
    if '毎日' in text:
        return '毎日'
    if '毎週' in text or '曜' in text:
        return '曜日指定'
    return 'その他'


def pick_direction_part(text, direction_raw):
    """For the "門司行＝…／大阪（天保山）行＝…" type, keep only the part for this direction."""
    if '／' not in text or not direction_raw:
        return text
    parts = [p.strip() for p in text.split('／')]
    hit = [p for p in parts if direction_raw in p]
    if not hit:
        hit = [p for p in parts if direction_raw.split('（')[0] in p]
    return '／'.join(hit) if hit else text


def build_service_frequency(sheets, trip_sources):
    out = []
    ship_lines = ship_lines_by_route_type() if SHIP_BY_ROUTE_TYPE else set()
    for key in sorted(trip_sources):
        line, direction, trip_num = key.split('__', 2)
        if not SHIP_LINE_RE.search(line) and line not in ship_lines:
            continue
        for sheet_title, tn in sorted(trip_sources[key]):
            s = sheets.get(sheet_title)
            if s is None:
                continue
            m = FREQ_RE.search(s.memo)
            raw = m.group(1).strip() if m else ''
            raw = pick_direction_part(raw, s.direction_raw)
            kind = classify_frequency(raw)
            exceptions = ''
            if raw or (SHIP_BY_ROUTE_TYPE and '休航' in s.memo):   # when ON, no-sailing notes are picked up even without frequency words
                memo_ex = re.sub(r'【ページ全体】[^【]*', '', s.memo) if SHIP_FREQ_STRICT else s.memo   # (1)
                ex = re.findall(r'[^。「」]*休航[^。」]*', memo_ex)
                exceptions = '／'.join(dict.fromkeys(e.strip() for e in ex))
            if not raw:
                if '型B' in s.memo or 'マス目が月日' in s.memo or (SHIP_DATE_GRID_WORDS and _DATE_GRID_RE.search(s.memo)):
                    kind = '月に数便（列ごとに月日が刷られている・型B）'
                    raw = '（原本は「マス目が月日」の型＝列ごとに出航日が刷られており、頻度の語は無い）'
                else:
                    kind = '記載なし'
            out.append({
                'trip_key': key, 'line_name': line, 'direction': direction, 'trip_num': trip_num,
                'source_sheet': sheet_title, 'table_name': s.table_name,
                'direction_raw': s.direction_raw,
                'frequency_kind': kind, 'frequency_raw': raw, 'exceptions_raw': exceptions,
            })
    return out


# ---------------------------------------------------------------- 3. line -> region
def build_line_region():
    path = os.path.join(GTFS_DIR, 'routes.txt')
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            line = r['route_short_name']
            region = ds.classify_line(line)
            out.append({'route_id': r['route_id'], 'line_name': line,
                        'route_long_name': r.get('route_long_name', ''),
                        'region': region or '内地', 'region_source': 'classify_line'})
    return out


def build_stop_time_system():
    """Mark each stop_times row with the time system in which the original prints it.

    Columns = trip_key, stop_sequence, stop_name, source_sheet, line_name,
        arr_time_system / arr_offset_to_jst_min / dep_time_system / dep_offset_to_jst_min (the original's time system and
        the minutes to add to get Japan inland time; empty = not stated in the original, not applied), rule_id,
        converted_to_jst (1 = converted by extract with EXTRACT_TZ_TO_JST=1, so GTFS values are inland time; 0 = as printed).
    Rules: data/tables/time_system_rules.csv (looked up by scripts/time_system.py).
    Inland rows (default = 日本内地及朝鮮時刻, offset 0) are not written (only external and "no note" rows).
    """
    import json
    import time_system as ts
    flags_path = os.path.join(INT_DIR, '_extract_flags.json')
    converted = 0
    if os.path.exists(flags_path):
        try:
            converted = 1 if json.load(open(flags_path, encoding='utf-8')).get('EXTRACT_TZ_TO_JST') == 1 else 0
        except Exception:
            converted = 0
    out = []
    with open(os.path.join(INT_DIR, 'integrated_stop_times.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            arr_sys, arr_off, arr_rule = ts.lookup(r['source_sheet'], r['line_name'], r['stop_name'], 'arr')
            dep_sys, dep_off, dep_rule = ts.lookup(r['source_sheet'], r['line_name'], r['stop_name'], 'dep')
            if arr_sys == ts.DEFAULT_SYSTEM and dep_sys == ts.DEFAULT_SYSTEM and not (arr_rule or dep_rule):
                continue
            out.append({'trip_key': r['gtfs_trip_key'], 'stop_sequence': r['stop_sequence'],
                        'stop_name': r['stop_name'], 'source_sheet': r['source_sheet'],
                        'line_name': r['line_name'],
                        'arr_time_system': arr_sys if r.get('arr_time') else '',
                        'arr_offset_to_jst_min': ('' if arr_off is None else arr_off) if r.get('arr_time') else '',
                        'dep_time_system': dep_sys if r.get('dep_time') else '',
                        'dep_offset_to_jst_min': ('' if dep_off is None else dep_off) if r.get('dep_time') else '',
                        'rule_id': '/'.join(sorted({x for x in (arr_rule, dep_rule) if x})),
                        'converted_to_jst': converted})
    return out, converted


# ---------------------------------------------------------------- output
def write_csv(name, rows, fields):
    path = os.path.join(GTFS_DIR, name)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f'  {name}: {len(rows)} 行 → {path}')


def main():
    print(f'build_gtfs_extras: GTFS_DIR={GTFS_DIR}')
    trip_sources = defaultdict(set)
    with open(os.path.join(INT_DIR, 'integrated_stop_times.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            trip_sources[r['gtfs_trip_key']].add((r['source_sheet'], r['trip_num']))
    sheets = load_sheets()
    print(f'  転記シート {len(sheets)}・トリップ {len(trip_sources)}')

    attrs, n_kind = build_trip_attributes(sheets, trip_sources)
    write_csv('trip_attributes.csv', attrs,
              ['trip_key', 'line_name', 'direction', 'trip_num', 'kind', 'classes', 'sleeper', 'diner',
               'label_header', 'label_section', 'other_tokens', 'source_sheets', 'note'])
    print(f'    種別あり {n_kind}（特急 {sum(1 for a in attrs if a["kind"] == "特急")}・'
          f'急行 {sum(1 for a in attrs if a["kind"] == "急行")}）・'
          f'列が引けなかったトリップ {sum(1 for a in attrs if a["note"] and not a["source_sheets"])}')

    freq = build_service_frequency(sheets, trip_sources)
    write_csv('service_frequency.csv', freq,
              ['trip_key', 'line_name', 'direction', 'trip_num', 'source_sheet', 'table_name',
               'direction_raw', 'frequency_kind', 'frequency_raw', 'exceptions_raw'])
    kinds = defaultdict(int)
    for r in freq:
        kinds[r['frequency_kind']] += 1
    print('    ' + '・'.join(f'{k} {v}' for k, v in sorted(kinds.items(), key=lambda x: -x[1])))

    region = build_line_region()
    write_csv('line_region.csv', region,
              ['route_id', 'line_name', 'route_long_name', 'region', 'region_source'])
    regs = defaultdict(int)
    for r in region:
        regs[r['region']] += 1
    print('    ' + '・'.join(f'{k} {v}' for k, v in sorted(regs.items(), key=lambda x: -x[1])))

    tzrows, converted = build_stop_time_system()
    write_csv('stop_time_system.csv', tzrows,
              ['trip_key', 'stop_sequence', 'stop_name', 'source_sheet', 'line_name',
               'arr_time_system', 'arr_offset_to_jst_min', 'dep_time_system', 'dep_offset_to_jst_min',
               'rule_id', 'converted_to_jst'])
    syss = defaultdict(int)
    for r in tzrows:
        for k in (r['arr_time_system'], r['dep_time_system']):
            if k:
                syss[k] += 1
    print('    ' + '・'.join(f'{k} {v}' for k, v in sorted(syss.items(), key=lambda x: -x[1]))
          + f'（converted_to_jst={converted}）')

    if os.path.exists(FREQ_ONLY_SRC):
        with open(FREQ_ONLY_SRC, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
            fields = f.seek(0) or next(csv.reader(f))
        write_csv('frequency_only.csv', rows, [c.lstrip('﻿') for c in fields])
    else:
        print(f'  frequency_only.csv: 正本 {FREQ_ONLY_SRC} が無いので書かない')


if __name__ == '__main__':
    main()
