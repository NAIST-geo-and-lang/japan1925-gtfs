"""
build_frequency_box.py — make the frequency boxes "此間○分毎ニ運轉" machine-readable as headway tables

Input
  All sheets in TRIPNUM_DIR (default data/2_timetable_with_tripnum_v1): row 7 trip_id, row 8 trip_label_header,
      row 9 trip_num, row 12 transcriber's note, times from row 14 (converted to HH:MM by extract_stop_times.to_hhmm)
  INTEGRATED_DIR/integrated_stop_times.csv: gtfs_trip_key of the trips before and after a box (source_sheet × trip_num)
  data/tables/frequency_box_overrides.csv (optional): boxes declared by hand where the note gives no headway (R8)
      or the note sits in the neighboring column (p63)

Output
  INTEGRATED_DIR/frequency_box.csv: one row per box (per destination/service kind when type 2 splits them).
      With GTFS_FREQUENCIES=1, generate_gtfs.py reads it, writes frequencies.txt and template trips, and puts a copy
      with template_trip_id filled in at GTFS_DIR/frequency_box.csv.

The transcription is not changed and no new times are made (only the printed headway/minutes and the times of
  the trips before and after the box, already in the transcription, are used).
"""

import csv
import glob
import os
import re
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_stop_times import to_hhmm, hhmm_to_minutes, minutes_to_hhmm  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INT_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'))
TRIPNUM_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('TRIPNUM_DIR', '2_timetable_with_tripnum_v1'))
OVERRIDES = os.path.join(BASE_DIR, 'data', 'tables', 'frequency_box_overrides.csv')
OUT_CSV = os.path.join(INT_DIR, 'frequency_box.csv')

# Type 3 "此間 X發 Y行 12.25・2.10・4.00 ノモノアリ" (trips in the box listed only by departure time at the first station)
#   is output as estimated trips copying the running of the preceding trip (one row per time). Default ON.
#   OFF (previous behavior): only one "対象外" (out of scope) row.
#   ON: that row stays, and one row per listed time is appended at the end (existing box_id and template trip TF...
#      numbers do not change).
#      Template trip = the nearest preceding trip with the same "X發Y行" (R3, R5). The listed times are departures (發)
#      from X; a.m./p.m. is not printed, so the reading that falls between the X times of the trips before and after
#      the box is used (if both or neither fit, the time is not output and a note is written).
#      frequencies.txt gets start = that time (shifted to the template trip's first station), end = start + 1 minute,
#      headway 60 seconds, exact_times=1, i.e. exactly one trip. Times at later stations are estimated (running times of
#      the preceding trip). The transcription is not changed.
LISTED = os.environ.get('FREQ_BOX_LISTED', '1') == '1'   # previous behavior = 0 (--no-freq-box-listed in run_pipeline.sh)

# When choosing the template trip (X and Y of the "X發Y行" mark vs. a trip's first and last stations) and when looking
#   up times at the anchor station (sheet names vs. integrated output names), both sides are normalized to new kanji
#   forms before comparing (integration aligns old/new spellings to the more common one [INTEGRATE_CANON_STOP_GLOBAL],
#   so an exact comparison can fail). The dictionary is scripts/known_kanji_variants.py, as in integration and route search.
#   Default ON. Previous behavior (exact comparison) = FREQ_BOX_NAME_VARIANTS=0 (--no-freq-box-name-variants in run_pipeline.sh).
NAME_VARIANTS = os.environ.get('FREQ_BOX_NAME_VARIANTS', '1') != '0'
if NAME_VARIANTS:
    import known_kanji_variants as _kv  # noqa: E402


def _nv(s):
    return _kv.normalize(s, prefer_new=True) if (NAME_VARIANTS and s) else s
_RE_LISTED = re.compile(r'([^\s　]+?)發\s*([^\s　]+?)行\s*([0-9.・ ]+?)\s*ノモノアリ')

FIELDS = ['box_id', 'page', 'sheet', 'columns', 'line_name', 'direction', 'direction_raw',
          'kind', 'service_kind', 'interval_min_lo', 'interval_min_hi', 'minute_of_hour',
          'anchor_stop', 'window_start', 'window_end',
          'prev_trip_id', 'next_trip_id', 'prev_trip_key', 'next_trip_key',
          'template_trip_key', 'template_seq_from', 'template_seq_to', 'template_trip_id',
          'gtfs_start_time', 'gtfs_end_time', 'headway_secs', 'exact_times', 'est_trips',
          'memo_raw', 'source', 'note']

KANJI_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6}


def nfc(s):
    return unicodedata.normalize('NFC', s) if isinstance(s, str) else s


def _num(s):
    return KANJI_NUM[s] if s in KANJI_NUM else int(s)


# ---------------------------------------------------------------------------
# Reading the notes (R2, R4, R5)
# ---------------------------------------------------------------------------
_RE_INTERVAL = re.compile(
    r'(?:約)?(?:(\d+|[一二三四五六])時間)?(?:(\d+)分)?(?:乃至(?:(\d+|[一二三四五六])時間)?(?:(\d+)分)?)?毎')
_RE_HOURLY = re.compile(r'(?:\(([^)]+)\)|([^\s・、（）()]+行))?\s*(?:毎時|〃)\s*([0-9〇]+|各)分')


def parse_memo(memo):
    """Return (kind, [entries]) from one transcriber's note. entries = {service_kind, lo, hi, minute}.
    Type 1 = headway only / type 2 = 毎時○分 (every hour at minute ○; one entry per destination or service kind) /
    type 3 = ノモノアリ (listed trips) / None = unreadable."""
    m = nfc(memo)
    if 'ノモノアリ' in m:
        return '③ノモノアリ', []
    if '毎時' in m:
        entries = []
        last_label = None
        for mm in _RE_HOURLY.finditer(m):
            label = mm.group(1) or mm.group(2) or last_label or ''
            last_label = label
            minute = mm.group(3)
            if minute == '各':
                entries.append({'service_kind': label, 'lo': 60, 'hi': 60, 'minute': '',
                                'kind': '②毎時各分'})
            else:
                minute = int(minute.replace('〇', '0'))
                entries.append({'service_kind': label, 'lo': 60, 'hi': 60, 'minute': minute,
                                'kind': '②毎時○分'})
        if entries:
            return '②', entries
    mm = _RE_INTERVAL.search(m)
    if mm and (mm.group(1) or mm.group(2)):
        lo = (_num(mm.group(1)) if mm.group(1) else 0) * 60 + int(mm.group(2) or 0)
        if mm.group(3) or mm.group(4):
            hi = (_num(mm.group(3)) if mm.group(3) else 0) * 60 + int(mm.group(4) or 0)
        else:
            hi = lo
        return '①間隔', [{'service_kind': '', 'lo': lo, 'hi': hi, 'minute': '', 'kind': '①間隔'}]
    return None, []


# ---------------------------------------------------------------------------
# Reading the sheets
# ---------------------------------------------------------------------------
def load_sheets():
    """{sheet_title: dict(page, line, direction, direction_raw, blocks=[block...])}
    block = {col, trip_id, label, trip_num, memo, times={row_idx: (stop, dep, arr)}, stops=[(row_idx, stop)...]}"""
    sheets = {}
    files = sorted(glob.glob(os.path.join(TRIPNUM_DIR, '*.xlsx')), key=lambda p: nfc(os.path.basename(p)))
    import openpyxl
    for path in files:
        if os.path.basename(path).startswith('~$'):
            continue
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            vals = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
            if len(vals) < 14 or not vals[0] or vals[0][0] != 'table_id':
                continue
            width = max(len(r) for r in vals)

            def cell(r, c):
                row = vals[r]
                return row[c] if c < len(row) else None

            stops = []
            for r in range(13, len(vals)):
                st = cell(r, 1)
                if st is not None and str(st).strip():
                    stops.append((r, nfc(str(st)).strip()))
            blocks = []
            for c in range(1, width):
                tid = cell(6, c)
                if tid is None:
                    continue
                times = {}
                for r, st in stops:
                    dep, dpm, arr, apm = cell(r, c), cell(r, c + 1), cell(r, c + 2), cell(r, c + 3)
                    d = to_hhmm(dep, dpm or 0) if dep not in (None, '') else None
                    a = to_hhmm(arr, apm or 0) if arr not in (None, '') else None
                    if isinstance(d, str) and d.startswith('ERR'):
                        d = None
                    if isinstance(a, str) and a.startswith('ERR'):
                        a = None
                    if d or a:
                        times[r] = (st, d, a)
                blocks.append({
                    'col': c + 1,  # 1-based (Excel column number)
                    'trip_id': tid,
                    'label': nfc(str(cell(7, c))) if cell(7, c) is not None else '',
                    'trip_num': nfc(str(cell(8, c))).strip() if cell(8, c) not in (None, '') else '',
                    'memo': nfc(str(cell(11, c))).replace('\n', ' ') if cell(11, c) is not None else '',
                    'times': times,
                })
            sheets[nfc(ws.title)] = {
                'page': cell(1, 1), 'line': nfc(str(cell(3, 1) or '')),
                'direction': nfc(str(cell(5, 1) or '')), 'direction_raw': nfc(str(cell(4, 1) or '')),
                'blocks': blocks, 'stops': stops,
            }
    return sheets


def load_overrides():
    """{(sheet, trip_id_str): [entry...]} with notes. Columns = sheet,trip_id,kind,service_kind,interval_min_lo,
    interval_min_hi,minute_of_hour,memo_raw,note. Several rows for one (sheet, trip_id) = one per destination/service kind."""
    out = defaultdict(list)
    if not os.path.exists(OVERRIDES):
        return out
    with open(OVERRIDES, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            key = (nfc(r['sheet']).strip(), str(r['trip_id']).strip())
            out[key].append(r)
    return out


def load_integrated_keys():
    """(source_sheet, trip_num) -> gtfs_trip_key, and gtfs_trip_key -> [rows]."""
    path = os.path.join(INT_DIR, 'integrated_stop_times.csv')
    by_sheet_num = defaultdict(set)
    rows_of = defaultdict(list)
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            by_sheet_num[(nfc(r['source_sheet']), nfc(r['trip_num']))].add(r['gtfs_trip_key'])
            rows_of[r['gtfs_trip_key']].append(r)
    for v in rows_of.values():
        v.sort(key=lambda x: int(x['stop_sequence']))
    return by_sheet_num, rows_of


def resolve_key(by_sheet_num, sheet, block):
    """The gtfs_trip_key that a sheet column (block) became after integration, or None."""
    num = block['trip_num'] or f'U{sheet}_{block["trip_id"]}'
    keys = by_sheet_num.get((sheet, num))
    if not keys:
        # allow keys with a suffix such as `_b` (starting with the same number)
        cands = set()
        for (s, n), ks in by_sheet_num.items():
            if s == sheet and (n == num or n.startswith(num + '_')):
                cands |= ks
        keys = cands
    if not keys:
        return None
    return sorted(keys)[0]


# ---------------------------------------------------------------------------
# Detecting boxes and the trips before and after them (R1, R3, R6)
# ---------------------------------------------------------------------------
def detect_boxes(sheet_name, sh, overrides):
    """A box = a column with no times whose note contains "此間" or that is declared in overrides.
    Adjacent boxes with the same trips on the left and right are merged into one (R6)."""
    blocks = sh['blocks']
    boxes = []
    for i, b in enumerate(blocks):
        if b['times']:
            continue
        ov = overrides.get((sheet_name, str(b['trip_id'])))
        if '此間' not in b['memo'] and not ov:
            continue
        left = next((x for x in reversed(blocks[:i]) if x['times']), None)
        right = next((x for x in blocks[i + 1:] if x['times']), None)
        boxes.append({'blocks': [b], 'left': left, 'right': right, 'override': ov})
    merged = []
    for bx in boxes:
        if merged and merged[-1]['left'] is bx['left'] and merged[-1]['right'] is bx['right']:
            merged[-1]['blocks'].append(bx['blocks'][0])
            merged[-1]['override'] = merged[-1]['override'] or bx['override']
        else:
            merged.append(bx)
    return merged


def anchor_of(left, right):
    """First station (in stop_order) where both the preceding and the following trip have a time. (row, stop, t_left, t_right)."""
    if not left or not right:
        return None
    for r in sorted(set(left['times']) & set(right['times'])):
        st, dl, al = left['times'][r]
        _, dr, ar = right['times'][r]
        tl, tr = dl or al, dr or ar
        if tl and tr:
            return r, st, tl, tr
    return None


# The window's anchor station is the one the template trip passes first among the stations where all three trips
#   (preceding, following, template) have times (with "the first row", an up table anchors at the terminus, and the
#   window's last estimated trip can coincide with the following printed trip).
#   Default ON. Previous behavior (first row where all three have times) = FREQ_BOX_ANCHOR_ORIGIN=0.
ANCHOR_ORIGIN = os.environ.get('FREQ_BOX_ANCHOR_ORIGIN', '1') != '0'


def anchor_with_template(left, right, tpl):
    """First station where the preceding, following and template trips all have times (R1). Same as anchor_of when the
    template is the preceding trip. With ANCHOR_ORIGIN, the one among them with the earliest template-trip time."""
    if not left or not right or not tpl:
        return None
    rows = sorted(set(left['times']) & set(right['times']) & set(tpl['times']))
    if ANCHOR_ORIGIN:
        # Place the template trip's times (0-24 h as transcribed) on a 24-hour circle, take the time right after the
        # largest gap as the start, and sort by minutes from it (stations near the start come first even across midnight)
        mins = {}
        for r in rows:
            _, d, a = tpl['times'][r]
            if d or a:
                mins[r] = hhmm_to_minutes(d or a) % 1440
        if mins:
            vs = sorted(set(mins.values()))
            gaps = [((vs[i] - vs[i - 1]) % 1440 or 1440, vs[i]) for i in range(len(vs))]
            start = max(gaps)[1]
            rows = sorted(rows, key=lambda r: ((mins[r] - start) % 1440 if r in mins else 1440, r))
    for r in rows:
        st, dl, al = left['times'][r]
        _, dr, ar = right['times'][r]
        tl, tr = dl or al, dr or ar
        if tl and tr:
            return r, st, tl, tr
    return None


def pick_template(sh, box, entry):
    """Template trip = the preceding trip (R3); with a destination/service-kind mark, the nearest trip with the same mark (R5).
    Returns (block, reason)."""
    label = entry.get('service_kind') or ''
    blocks = sh['blocks']
    i_left = blocks.index(box['left']) if box['left'] else -1
    order = [x for x in reversed(blocks[:i_left + 1]) if x['times']]
    if box['right']:
        i_right = blocks.index(box['right'])
        order += [x for x in blocks[i_right:] if x['times']]
    if not order:
        return None, '前後に時刻を持つ便が無い'
    if not label:
        return order[0], ''
    # Reading the mark: "X發Y行" or "Y行" (origin/destination station names); others (直, 普, 急) are service-kind words in row 8
    origin = dest = None
    if '發' in label:
        origin, rest = label.split('發', 1)
        dest = rest[:-1] if rest.endswith('行') else (rest or None)
    elif label.endswith('行'):
        dest = label[:-1]
    for b in order:
        seq = [v[0] for _, v in sorted(b['times'].items())]
        if origin is not None or dest is not None:
            ok = True
            if origin and not (_nv(seq[0]) == _nv(origin) or _nv(seq[0]).startswith(_nv(origin))):
                ok = False
            if dest and not (_nv(seq[-1]) == _nv(dest) or _nv(seq[-1]).startswith(_nv(dest))):
                ok = False
            if ok:
                return b, ''
        elif label in (b['label'] or ''):
            return b, ''
    return None, f'印「{label}」と同じ便がシートに無い'


# ---------------------------------------------------------------------------
# GTFS values (R1, R2, R4)
# ---------------------------------------------------------------------------
def gtfs_values(entry, anchor, tpl_rows, anchor_stop):
    """(start, end, headway_secs, exact_times, est_trips, note). Times are at the template trip's first station (minutes)."""
    _, _, t_prev, t_next = anchor
    w0, w1 = hhmm_to_minutes(t_prev), hhmm_to_minutes(t_next)
    if w1 <= w0:
        w1 += 1440
    # running time from the template trip's first station to the anchor station (R1: shift to the first station's time)
    first = tpl_rows[0]
    t_first = hhmm_to_minutes(first.get('dep_time') or first.get('arr_time'))
    t_anchor = None
    for r in tpl_rows:
        if _nv(r['stop_name']) == _nv(anchor_stop) or _nv(r['stop_name']).startswith(_nv(anchor_stop)):
            t_anchor = hhmm_to_minutes(r.get('dep_time') or r.get('arr_time'))
            break
    if t_first is None or t_anchor is None:
        return None, None, None, None, None, '雛形便に基準駅の時刻が無い'
    off = t_anchor - t_first
    hi = int(entry['hi'])
    if entry.get('minute') != '' and entry.get('minute') is not None:
        # Type 2 = every hour at minute MM (exact_times=1): from the first :MM after the preceding trip's departure
        # to the last :MM before the following trip's departure
        mm = int(entry['minute'])
        first_dep = ((w0 - mm) // 60 + 1) * 60 + mm
        last_dep = ((w1 - 1 - mm) // 60) * 60 + mm
        if last_dep < first_dep:
            return None, None, None, None, None, '有効時間帯に毎時○分の便が入らない'
        n = (last_dep - first_dep) // 60 + 1
        return first_dep - off, last_dep - off + 1, 3600, 1, n, ''
    # Type 1 = from the preceding trip's departure + headway (upper bound) until before the following trip's departure (exact_times=0)
    first_dep = w0 + hi
    if first_dep >= w1:
        return None, None, None, None, None, '前後の便の間隔が箱の間隔以下'
    n = (w1 - 1 - first_dep) // hi + 1
    return first_dep - off, w1 - off, hi * 60, 0, n, ''


def section_rows(rows_of, tkey, sheet_name, sh):
    """Integrated rows of the template trip within this sheet's section (cut the same way as types 1 and 2 in build())."""
    allrows = rows_of[tkey]
    idx = [i for i, r in enumerate(allrows) if nfc(r['source_sheet']) == sheet_name]
    if not idx:
        return []
    lo_i, hi_i = idx[0], idx[-1]
    sheet_stop_names = {st for _, st in sh['stops']}
    base_name = lambda x: re.sub(r'〈[^〉]*〉', '', x)  # noqa: E731
    while lo_i > 0 and base_name(allrows[lo_i - 1]['stop_name']) in sheet_stop_names:
        lo_i -= 1
    while hi_i + 1 < len(allrows) and base_name(allrows[hi_i + 1]['stop_name']) in sheet_stop_names:
        hi_i += 1
    return allrows[lo_i:hi_i + 1]


def listed_rows(base, memo, sh, sheet_name, box, by_sheet_num, rows_of):
    """Type 3 listed times -> frequency_box.csv rows (one per time). Called only with LISTED=1."""
    m = _RE_LISTED.search(memo)
    if not m:
        return [{**base, 'kind': '③ノモノアリ（列挙）', 'note': 'メモから「X發Y行 時刻・時刻 ノモノアリ」が読めない'}]
    origin, dest = m.group(1), m.group(2)
    times = [t for t in re.split(r'[・\s]+', m.group(3).strip()) if t]
    label = f'{origin}發{dest}行'
    out = []
    tpl, reason = pick_template(sh, box, {'service_kind': label})
    tkey = resolve_key(by_sheet_num, sheet_name, tpl) if tpl else None
    trows = section_rows(rows_of, tkey, sheet_name, sh) if tkey else []
    seqs = [int(r['stop_sequence']) for r in trows]

    def at_origin(block):
        for r in sorted(block['times']) if block else []:
            st, d, a = block['times'][r]
            if _nv(st) == _nv(origin) or _nv(st).startswith(_nv(origin)):
                return hhmm_to_minutes(d or a)
        return None
    # Window that settles a.m./p.m.: the nearest trips before and after the box with a time at the first station X
    # (a neighboring trip may start at an intermediate station; on p114, train 8 to 高崎 starts at 上州富岡)
    blocks = sh['blocks']
    i_box = blocks.index(box['blocks'][0])
    w0 = next((t for t in (at_origin(x) for x in reversed(blocks[:i_box])) if t is not None), None)
    w1 = next((t for t in (at_origin(x) for x in blocks[i_box + 1:]) if t is not None), None)
    if w0 is not None and w1 is not None and w1 <= w0:
        w1 += 1440
    t_first = t_org = None
    if trows:
        t_first = hhmm_to_minutes(trows[0].get('dep_time') or trows[0].get('arr_time'))
        for r in trows:
            if _nv(r['stop_name']) == _nv(origin) or _nv(r['stop_name']).startswith(_nv(origin)):
                t_org = hhmm_to_minutes(r.get('dep_time') or r.get('arr_time'))
                break
    for t in times:
        row = {**base, 'kind': '③ノモノアリ（列挙）', 'service_kind': label, 'anchor_stop': origin,
               'window_start': minutes_to_hhmm(w0) if w0 is not None else '',
               'window_end': minutes_to_hhmm(w1) if w1 is not None else ''}
        why = []
        if tpl is None:
            why.append(reason)
        elif not tkey:
            why.append(f'雛形便（trip_id {tpl["trip_id"]}）が統合出力に無い（シートが落選）')
        elif len(trows) < 2 or seqs != list(range(seqs[0], seqs[0] + len(seqs))):
            why.append(f'雛形便 {tkey} のこのシートの区間が 2 駅未満か連続していない')
        elif t_first is None or t_org is None:
            why.append('雛形便に始発駅の時刻が無い')
        elif w0 is None or w1 is None:
            why.append('前後の便に始発駅の時刻が無い（午前／午後を決められない）')
        hh, mm = (t.split('.') + ['0'])[:2]
        base_min = int(hh) * 60 + int(mm)
        cands = [base_min] if int(hh) == 12 else [base_min, base_min + 720]
        cands += [c + 1440 for c in cands]
        hit = [c for c in cands if w0 is not None and w1 is not None and w0 < c < w1]
        if not why and len(hit) != 1:
            why.append(f'時刻 {t} が前後の便のあいだに {len(hit)} 通りに読める（午前／午後が決まらない）')
        if why:
            row['note'] = '・'.join(why) + f'（原本の列挙 {t}）'
            out.append(row)
            continue
        start = hit[0] - (t_org - t_first)
        row.update({'template_trip_key': tkey, 'template_seq_from': seqs[0], 'template_seq_to': seqs[-1],
                    'gtfs_start_time': fmt_hms(start), 'gtfs_end_time': fmt_hms(start + 1),
                    'headway_secs': 60, 'exact_times': 1, 'est_trips': 1,
                    'note': f'原本の列挙 {t}＝{minutes_to_hhmm(hit[0])}（前後の便の{origin}の時刻のあいだ）。'
                            f'途中駅・終点は雛形便の所要を写した推定'})
        out.append(row)
    return out


def fmt_hms(m):
    return '' if m is None else f'{m // 60:02d}:{m % 60:02d}:00'


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build():
    sheets = load_sheets()
    overrides = load_overrides()
    by_sheet_num, rows_of = load_integrated_keys()
    out = []
    extra = []     # type 3 listed times with LISTED=1 (appended at the end, so existing box_ids do not change)
    def page_key(v):
        m = re.match(r'\d+', str(v or ''))
        return int(m.group()) if m else 0
    order = sorted(sheets.items(), key=lambda kv: (page_key(kv[1]['page']), kv[0]))
    for sheet_name, sh in order:
        for box in detect_boxes(sheet_name, sh, overrides):
            memo = ' ／ '.join(b['memo'] for b in box['blocks'] if b['memo'])
            if box['override']:
                kind = None
                entries = []
                for r in box['override']:
                    entries.append({'service_kind': r.get('service_kind', '') or '',
                                    'lo': int(r['interval_min_lo']) if r.get('interval_min_lo') else 60,
                                    'hi': int(r['interval_min_hi']) if r.get('interval_min_hi') else
                                          (int(r['interval_min_lo']) if r.get('interval_min_lo') else 60),
                                    'minute': int(r['minute_of_hour']) if r.get('minute_of_hour') else '',
                                    'kind': r.get('kind') or '①間隔',
                                    'note': r.get('note', ''),
                                    'memo': r.get('memo_raw', '')})
                source = 'override'
                if not memo:
                    memo = ' ／ '.join(e['memo'] for e in entries if e.get('memo'))
            else:
                kind, entries = parse_memo(memo)
                source = 'memo'
            anchor = anchor_of(box['left'], box['right'])
            base = {
                'page': sh['page'], 'sheet': sheet_name,
                'columns': ';'.join(str(b['col']) for b in box['blocks']),
                'line_name': sh['line'], 'direction': sh['direction'], 'direction_raw': sh['direction_raw'],
                'anchor_stop': anchor[1] if anchor else '',
                'window_start': anchor[2] if anchor else '', 'window_end': anchor[3] if anchor else '',
                'prev_trip_id': box['left']['trip_id'] if box['left'] else '',
                'next_trip_id': box['right']['trip_id'] if box['right'] else '',
                'prev_trip_key': resolve_key(by_sheet_num, sheet_name, box['left']) or '' if box['left'] else '',
                'next_trip_key': resolve_key(by_sheet_num, sheet_name, box['right']) or '' if box['right'] else '',
                'memo_raw': memo, 'source': source,
            }
            if any(str(e.get('kind', '')).startswith('対象外') for e in entries):
                out.append({**base, 'kind': '対象外', 'note': '・'.join(e.get('note', '') for e in entries if e.get('note'))})
                continue
            if kind == '③ノモノアリ':
                out.append({**base, 'kind': '③ノモノアリ', 'note': '対象外（書き起こしの側で区間ごとに分けて写している）'})
                if LISTED:
                    extra += listed_rows(base, memo, sh, sheet_name, box, by_sheet_num, rows_of)
                continue
            if not entries:
                out.append({**base, 'kind': '?', 'note': 'メモから間隔が読めない（R8＝overrides で宣言する）'})
                continue
            for e in entries:
                row = {**base, 'kind': e['kind'], 'service_kind': e['service_kind'],
                       'interval_min_lo': e['lo'], 'interval_min_hi': e['hi'],
                       'minute_of_hour': e['minute'], 'note': e.get('note', '')}
                notes = [row['note']] if row['note'] else []
                if not anchor:
                    notes.append('前後の便が共通して時刻を持つ駅が無い')
                    row['note'] = '・'.join(notes)
                    out.append(row)
                    continue
                tpl, reason = pick_template(sh, box, e)
                if tpl is None:
                    notes.append(reason)
                    row['note'] = '・'.join(notes)
                    out.append(row)
                    continue
                tkey = resolve_key(by_sheet_num, sheet_name, tpl)
                if not tkey:
                    notes.append(f'雛形便（trip_id {tpl["trip_id"]}）が統合出力に無い（シートが落選）')
                    row['note'] = '・'.join(notes)
                    out.append(row)
                    continue
                # Use only this sheet's section of the template trip (a through trip may be joined with other section
                # pages, but the box headway applies only to this section). The section's stop_sequence must be consecutive.
                allrows = rows_of[tkey]
                idx = [i for i, r in enumerate(allrows) if nfc(r['source_sheet']) == sheet_name]
                if idx:
                    lo_i, hi_i = idx[0], idx[-1]
                    # A boundary station (where sections meet) may belong to the neighboring sheet after integration,
                    # so extend one row at a time in each direction while the station is in this sheet's station column
                    sheet_stop_names = {st for _, st in sh['stops']}
                    base_name = lambda x: re.sub(r'〈[^〉]*〉', '', x)  # noqa: E731 (strips the 〈region〉 tag from disambiguate)
                    while lo_i > 0 and base_name(allrows[lo_i - 1]['stop_name']) in sheet_stop_names:
                        lo_i -= 1
                    while hi_i + 1 < len(allrows) and base_name(allrows[hi_i + 1]['stop_name']) in sheet_stop_names:
                        hi_i += 1
                    trows = allrows[lo_i:hi_i + 1]
                else:
                    trows = []
                seqs = [int(r['stop_sequence']) for r in trows]
                if len(trows) < 2 or seqs != list(range(seqs[0], seqs[0] + len(seqs))):
                    notes.append(f'雛形便 {tkey} のこのシートの区間が 2 駅未満か連続していない')
                    row['note'] = '・'.join(notes)
                    out.append(row)
                    continue
                anchor_t = anchor_with_template(box['left'], box['right'], tpl) or anchor
                row['anchor_stop'], row['window_start'], row['window_end'] = anchor_t[1], anchor_t[2], anchor_t[3]
                s, t, hw, ex, n, why = gtfs_values(e, anchor_t, trows, anchor_t[1])
                if why:
                    notes.append(why)
                    row['note'] = '・'.join(notes)
                    out.append(row)
                    continue
                row.update({'template_trip_key': tkey, 'template_seq_from': seqs[0], 'template_seq_to': seqs[-1],
                            'gtfs_start_time': fmt_hms(s), 'gtfs_end_time': fmt_hms(t),
                            'headway_secs': hw, 'exact_times': ex, 'est_trips': n, 'note': '・'.join(notes)})
                out.append(row)
    out += extra
    for i, r in enumerate(out, start=1):
        r['box_id'] = f'FB{i:03d}'
    return out


def main():
    rows = build()
    os.makedirs(INT_DIR, exist_ok=True)
    with open(OUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in FIELDS})
    n_tpl = sum(1 for r in rows if r.get('template_trip_key'))
    kinds = defaultdict(int)
    for r in rows:
        kinds[r.get('kind', '?')] += 1
    print(f'build_frequency_box: 箱 {len(rows)} 行（' + '・'.join(f'{k} {v}' for k, v in sorted(kinds.items()))
          + f'）／frequencies.txt に出せる {n_tpl}・出せない {len(rows) - n_tpl} → {OUT_CSV}')
    for r in rows:
        if not r.get('template_trip_key'):
            print(f'  - {r["box_id"]} {r["sheet"]} 列{r["columns"]} {r.get("kind")} {r.get("service_kind", "")}: {r.get("note", "")}')


if __name__ == '__main__':
    main()
