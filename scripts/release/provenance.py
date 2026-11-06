#!/usr/bin/env python3
"""provenance.py — Provenance tables of the published dataset

Called from scripts/build_release_gtfs.py (not run on its own). Writes nothing outside the published dataset.

  1. Two columns in trip_source.csv: trip_num_source (the strongest number source among the transcription columns
     that supplied times to the trip) and trip_num_sources (all of them, strongest first, joined with "|").
     Strength: explicit_section > explicit_header > inherited_same_line > inherited_diff_line > uncertain.
     Empty for template trips (TF, TQ), which are not printed trains.
  2. stop_time_source.csv (one row per stop_times.txt row, same order): source of each arrival and departure
     (printed/copied/computed/template) and, for printed values, the transcription cell (page, sheet,
     column = trip_id in row 7, row = stop_order). For times converted to Japan standard time, the original time
     system and the minutes added.
  3. timepoint in stop_times.txt (GTFS standard): 1 for stops with at least one printed time, otherwise 0
     (computed times, template trips, no time).
  4. stop_coord_source.csv (one row per stops.txt row): coordinate class (station/place/estimated/unrecorded),
     method, reference (dataset name, ID, label), distance to the reference coordinate, and the range (km) checked
     against independent station positions. For stations whose coordinates come from the coordinate tables, the
     source columns of the stop-place table (data/knowledge/places/stop_place.csv) are output as they are
     (interpolated stations: "1925 timetable mileages").

Matching for 2: arrivals and departures of integrated records (integrated_stop_times.csv) are matched to cells of
  the intermediate transcription files (STOP_TIMES_DIR, extracted from the workbooks with time-system conversion,
  weekdays and within-sheet midnight crossing already applied) by (sheet, station name, field, time mod 24h).
  Station names drop the 〈region〉 tag and are normalized from old to modern kanji. Search order: (1) the record's
  own sheet, (2) the trip's other sheets, (3) columns with the same number on any sheet (values printed only in a
  band or summary table and woven into blank cells of the detailed trip). Ties go to the smallest sheet name,
  column, row.
"""
import glob
import os
import re
import sys
import unicodedata
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
from known_kanji_variants import normalize as _kv_normalize  # noqa: E402

INTER_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('STOP_TIMES_DIR', '3_stop_times_intermediate_v1'))
TRIPNUM_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('TRIPNUM_DIR', '2_timetable_with_tripnum_v1'))


TNS_ORDER = ['explicit_section', 'explicit_header', 'inherited_same_line', 'inherited_diff_line', 'uncertain']

STOP_TIME_FIELDS = ['trip_id', 'stop_sequence', 'stop_name',
                    'arrival_source', 'arrival_page', 'arrival_sheet', 'arrival_column', 'arrival_row',
                    'departure_source', 'departure_page', 'departure_sheet', 'departure_column', 'departure_row',
                    'arrival_time_system', 'arrival_jst_offset_min', 'departure_time_system', 'departure_jst_offset_min',
                    'basis']
COORD_FIELDS = ['stop_id', 'stop_name', 'coord_class', 'coord_method', 'reference', 'reference_id',
                'reference_label', 'reference_distance_m', 'checked_within_km', 'reference_stop_id', 'reference_note']


def _nname(s):
    s = unicodedata.normalize('NFC', s or '')
    s = re.sub(r'〈[^〉]*〉', '', s).strip()
    return _kv_normalize(s, prefer_new=True)


def _tmin(s):
    if not s:
        return None
    h, m = str(s).split(':')[:2]
    return int(h) * 60 + int(m)


def _base_num(n):
    return re.sub(r'_[a-z]$', '', n or '')


def _want_col(num):
    """For the key Up…_N of a trip without a printed number, return (sheet, N)."""
    m = re.fullmatch(r'U(p\d{4}_tb\d{3}(?:-\d+)*)_(\d+)', _base_num(num))
    return (m.group(1), int(m.group(2))) if m else None


def _page(sheet):
    m = re.match(r'p(\d{4})_', sheet or '')
    return str(int(m.group(1))) if m else ''


# ============================================================ 1-3. Stop provenance
def _sheet_station_rows(tripnum_dir):
    """For each workbook sheet, map column A stop_order to the (normalized) station name."""
    import openpyxl
    out = {}
    for fn in sorted(glob.glob(os.path.join(tripnum_dir, '*.xlsx'))):
        if os.path.basename(fn).startswith('~$'):
            continue
        wb = openpyxl.load_workbook(fn, read_only=True)
        for ws in wb.worksheets:
            d, body = {}, False
            for r in ws.iter_rows(max_col=2, values_only=True):
                if not body:
                    body = r[0] == 'stop_order'
                    continue
                try:
                    d[int(float(r[0]))] = _nname(r[1])
                except (TypeError, ValueError):
                    continue
            out[ws.title] = d
        wb.close()
    return out


class Cells:
    """Cells of the intermediate transcription files (one record = one sheet x one column x one station).

    The row (order) is mapped back to column A stop_order of the workbook. For trips on sheets whose station names
      run in down order (e.g. up tables of private railways), extract renumbers stop_order per trip
      (reverse_stop_order: reversed within the trip's set of stop_order values) without leaving a mark.
      So for each trip, check whether the intermediate (stop_order, station name) matches workbook columns A and B
      as is or reversed, and map back accordingly. Trips matching neither (workbook edited later, sheet missing)
      keep the intermediate values and are counted in row_unverified."""

    def __init__(self, inter_dir=INTER_DIR, tripnum_dir=TRIPNUM_DIR):
        import openpyxl
        self.by_sheet = defaultdict(list)     # (sheet, station name) -> [cell]
        self.by_time = defaultdict(list)      # (station name, field, minutes mod 1440) -> [cell]
        groups = defaultdict(list)
        n = 0
        for fn in sorted(glob.glob(os.path.join(inter_dir, '*.xlsx'))):
            wb = openpyxl.load_workbook(fn, read_only=True)
            ws = wb['stop_times']
            it = ws.iter_rows(values_only=True)
            ix = {h: i for i, h in enumerate(next(it))}
            for row in it:
                sheet = row[ix['source_sheet']]
                if not sheet:
                    continue
                c = {'sheet': sheet, 'col': int(row[ix['trip_id']]), 'order': int(row[ix['stop_order']]),
                     'num': str(row[ix['trip_num']] or ''), 'tns': row[ix['trip_num_source']] or '',
                     'arr': _tmin(row[ix['arr_time']]), 'dep': _tmin(row[ix['dep_time']]),
                     'name': _nname(row[ix['stop_name']])}
                self.by_sheet[(sheet, c['name'])].append(c)
                for f in ('arr', 'dep'):
                    if c[f] is not None:
                        self.by_time[(c['name'], f, c[f] % 1440)].append(c)
                groups[(sheet, c['col'])].append(c)
                n += 1
            wb.close()
        self.n = n
        # map rows back to workbook column A
        rows = _sheet_station_rows(tripnum_dir)
        self.n_reversed = self.n_unverified = 0
        self.unverified = []
        for (sheet, _), cs in groups.items():
            names = rows.get(sheet, {})
            orders = sorted({c['order'] for c in cs})
            rev = dict(zip(orders, reversed(orders)))
            if all(names.get(c['order']) == c['name'] for c in cs):
                continue
            if all(names.get(rev[c['order']]) == c['name'] for c in cs):
                for c in cs:
                    c['order'] = rev[c['order']]
                self.n_reversed += 1
                continue
            self.n_unverified += 1
            self.unverified.append((sheet, cs[0]['col']))

    @staticmethod
    def _pick(cands, num, wc, allow_any):
        if not cands:
            return None
        got = [c for c in cands if (c['sheet'], c['col']) == wc] if wc else []
        if not got:
            got = [c for c in cands if _base_num(c['num']) == num]
        if not got and allow_any:
            got = cands
        return min(got, key=lambda c: (c['sheet'], c['col'], c['order'])) if got else None

    def trace(self, rec, f, trip_sheets):
        """The cell where field f ('arr'/'dep') of integrated record rec is printed. Return (cell, stage), or None."""
        v = rec['arr_time'] if f == 'arr' else rec['dep_time']
        if not v:
            return None, ''
        nn, mm = _nname(rec['stop_name']), _tmin(v) % 1440
        num, wc = _base_num(rec['trip_num']), _want_col(rec['trip_num'])

        def hits(sheet):
            return [c for c in self.by_sheet.get((sheet, nn), ()) if c[f] is not None and c[f] % 1440 == mm]
        c = self._pick(hits(rec['source_sheet']), num, wc, allow_any=True)
        if c:
            return c, 'same_sheet'
        for sh in trip_sheets:
            if sh != rec['source_sheet']:
                c = self._pick(hits(sh), num, wc, allow_any=False)
                if c:
                    return c, 'trip_sheet'
        c = self._pick(self.by_time.get((nn, f, mm), ()), num, wc, allow_any=False)
        return (c, 'same_number') if c else (None, '')


def build_stop_time_source(st_of, kept, key_of, integ, stop_name, tz_rows, box_rows, section_rows,
                           computed_rows, cells=None):
    """Return (stop_time_source rows, {(trip_id, stop_sequence): '0'/'1'}, {trip_id: (strongest, all)}, counts).

    st_of: trip_id -> stop_times rows (published order, including computed rows); kept: trip_ids kept in the
    published dataset; key_of: trip_id -> gtfs_trip_key; integ: integrated_stop_times rows; stop_name: stop_id ->
    station name; tz_rows: rows of stop_time_system.csv; box_rows: rows of frequency_box.csv; section_rows: rows of
    frequency_sections.csv; computed_rows: {(trip_id, stop_sequence): {'page','sheet','basis'}} = rows computed by
    build_release_gtfs (terminals of departure-only tables).
    """
    cells = cells or Cells()
    rec_of = {(r['gtfs_trip_key'], r['stop_sequence']): r for r in integ}
    sheets_of = defaultdict(list)
    for r in integ:
        if r['source_sheet'] not in sheets_of[r['gtfs_trip_key']]:
            sheets_of[r['gtfs_trip_key']].append(r['source_sheet'])
    tz = {(r['trip_key'], r['stop_sequence']): r for r in tz_rows}
    box_of = {r['template_trip_id']: r for r in box_rows if r.get('template_trip_id')}
    sec_of = {r['template_trip_id']: r for r in section_rows if r.get('template_trip_id')}
    rows, tp, tns_of = [], {}, {}
    n = defaultdict(int)
    for tid, sts in st_of.items():
        if tid not in kept:
            continue
        tns = set()
        for s in sts:
            seq = s['stop_sequence']
            out = {'trip_id': tid, 'stop_sequence': seq, 'stop_name': stop_name.get(s['stop_id'], '')}
            src = {}
            if tid.startswith('TQ'):              # template trip of a frequency-only section (the original gives first/last trip, running time, interval in text)
                sec = sec_of.get(tid, {})
                for f, g in (('arr', 'arrival'), ('dep', 'departure')):
                    if s[f'{g}_time']:
                        src[f] = 'template'
                        out[f'{g}_page'] = sec.get('page', '')
                out['basis'] = (f"{sec.get('section_id', '')}（頻度だけの区画・{sec.get('line_name', '')} "
                                f"{sec.get('origin', '')}—{sec.get('destination', '')}"
                                + ('・所要は推定' if sec.get('source') == 'estimate' else '') + '）')
            elif tid.startswith('TF'):            # template trip of a frequency box: copies the times of the trip before the box
                box = box_of.get(tid, {})
                rec = rec_of.get((box.get('template_trip_key', ''), seq))
                for f, g in (('arr', 'arrival'), ('dep', 'departure')):
                    if not s[f'{g}_time']:
                        continue
                    src[f] = 'template'
                    c, _ = cells.trace(rec, f, sheets_of[rec['gtfs_trip_key']]) if rec else (None, '')
                    if c:
                        out.update({f'{g}_page': _page(c['sheet']), f'{g}_sheet': c['sheet'],
                                    f'{g}_column': c['col'], f'{g}_row': c['order']})
                    else:
                        out[f'{g}_page'] = box.get('page', '')
                out['basis'] = f"{box.get('box_id', '')}（{box.get('memo_raw', '')}・p{box.get('page', '')} {box.get('sheet', '')}）"
            elif (tid, seq) in computed_rows:     # value computed for the published dataset (terminal arrival of a departure-only table)
                cr = computed_rows[(tid, seq)]
                for f, g in (('arr', 'arrival'), ('dep', 'departure')):
                    if s[f'{g}_time']:
                        src[f] = 'computed'
                        out[f'{g}_page'] = cr.get('page', '')
                        out[f'{g}_sheet'] = cr.get('sheet', '')
                out['basis'] = cr.get('basis', '')
            else:                                 # printed trip
                key = key_of.get(tid, '')
                rec = rec_of.get((key, seq))
                for f, g in (('arr', 'arrival'), ('dep', 'departure')):
                    if not s[f'{g}_time']:
                        continue
                    if rec is None:
                        src[f] = 'unmatched'
                        n['unmatched'] += 1
                        continue
                    c, how = cells.trace(rec, f, sheets_of[key])
                    if c:
                        src[f] = 'printed'
                        n[how] += 1
                        tns.add(c['tns'])
                        out.update({f'{g}_page': _page(c['sheet']), f'{g}_sheet': c['sheet'],
                                    f'{g}_column': c['col'], f'{g}_row': c['order']})
                    elif not (rec['arr_time'] if f == 'arr' else rec['dep_time']):
                        # GTFS_FILL_FROM_PARTNER fills a blank field with the value printed by the partner trip of the
                        # same through train, so the GTFS value differs from the opposite field. Then look up the
                        # partner's cell and write printed (if equal to the opposite field, it is a copy = copied).
                        other = rec['dep_time'] if f == 'arr' else rec['arr_time']
                        c2, how2 = None, ''
                        if other and _tmin(s[f'{g}_time']) != _tmin(other):
                            hh, mm2 = s[f'{g}_time'].split(':')[:2]
                            c2, how2 = cells.trace(dict(rec, **{f'{f}_time': f'{hh}:{mm2}'}), f, sheets_of[key])
                        if c2:
                            src[f] = 'printed'
                            n['partner_' + how2] += 1
                            tns.add(c2['tns'])
                            out.update({f'{g}_page': _page(c2['sheet']), f'{g}_sheet': c2['sheet'],
                                        f'{g}_column': c2['col'], f'{g}_row': c2['order']})
                        else:
                            src[f] = 'copied'             # the original prints only one; GTFS needs both, so the same value is used
                    else:
                        src[f] = 'unmatched'
                        n['unmatched'] += 1
                t = tz.get((key, seq))
                if t and str(t.get('converted_to_jst', '')) == '1':
                    for f, g in (('arr', 'arrival'), ('dep', 'departure')):
                        if t.get(f'{f}_time_system') and src.get(f) == 'printed':
                            out[f'{g}_time_system'] = t[f'{f}_time_system']
                            out[f'{g}_jst_offset_min'] = t.get(f'{f}_offset_to_jst_min', '')
            out['arrival_source'] = src.get('arr', '')
            out['departure_source'] = src.get('dep', '')
            tp[(tid, seq)] = '1' if 'printed' in src.values() else '0'
            n['timepoint_' + tp[(tid, seq)]] += 1
            rows.append(out)
        if tns:
            srt = sorted(tns, key=lambda x: TNS_ORDER.index(x) if x in TNS_ORDER else len(TNS_ORDER))
            tns_of[tid] = (srt[0], '|'.join(srt))
    n['trips_reversed'] = cells.n_reversed
    n['trips_row_unverified'] = cells.n_unverified
    return rows, tp, tns_of, dict(n)


RE_TOPO_READ = re.compile(r'地形図.{0,80}?(?:読んだ|読み取り)|今昔マップ.{0,120}?読んだ')
RE_TOPO_NOT = re.compile(r'読めば|読めない|読めず|読めなかった')
RE_TOPO_DESC = re.compile(r'今昔マップ on the web(?:〔[^〕]*〕)?・(.+?)(?:）で|）|で)')


def _topo_desc(note):
    """If the note starts with a topographic-map reading, return the map description (area, period, 〔sheet, edition〕;
    '' if absent); otherwise None."""
    head = (note or '').split('／')[0]
    if not RE_TOPO_READ.search(head) or RE_TOPO_NOT.search(head):
        return None
    m = RE_TOPO_DESC.search(head)
    return m.group(1).strip() if m else ''


def build_stop_coord_source(stops, parents, coord_source_of, key_of_stop, stop_id_of_key, rep_child):
    """stops: child stops of the published dataset (stop_id, stop_name, stop_lat, stop_lon); parents: parent-station
    rows; coord_source_of: stop_id -> coord_source in the work folder's stops_master; key_of_stop: stop_id ->
    (station name, line name); stop_id_of_key: (station name, line name) -> stop_id; rep_child: parent stop_id ->
    child stop_id whose coordinates it took.
    For stations whose coordinates come from the coordinate tables (coord_source = agent_known, release_proxy,
    wikidata, legacy:…), scripts/kb_sources.py builds the source by rule from the places table source (fixed terms)
    and the use column of the stop-place table. Stops if a station has no source."""
    sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
    import agent_knowledge as ak
    import kb_sources as ks
    places = ak._tables()[0]
    out, stat = {}, defaultdict(int)

    def row(sid, name, cls, method, ref='', rid='', label='', dist='', within='', ref_stop='', note=''):
        return {'stop_id': sid, 'stop_name': name, 'coord_class': cls, 'coord_method': method,
                'reference': ref, 'reference_id': rid, 'reference_label': label,
                'reference_distance_m': dist, 'checked_within_km': within, 'reference_stop_id': ref_stop,
                'reference_note': note}

    missing = []
    for s in stops:
        sid, name = s['stop_id'], s['stop_name']
        if not s.get('stop_lat'):         # stop without coordinates (dropped from the published dataset, so normally not reached)
            out[sid] = row(sid, name, 'unrecorded', 'no_coordinate')
            stat['no_coordinate'] += 1
            continue
        cs = coord_source_of.get(sid, '')
        key = key_of_stop.get(sid, (name, ''))
        if cs == 'inferred':
            r = row(sid, name, 'estimated', 'interpolated_mileage', '1925 timetable mileages')
        elif cs in ak.COORD_SOURCES or cs.startswith('legacy:'):
            e = ak.entry(*key)
            p = places.get(e['place_id']) if e else None
            if not e or not e.get('use') or p is None or (e['use'] != 'adjacent' and not p.get('source_type')):
                missing.append(key)
                r = row(sid, name, 'unrecorded', 'unrecorded')
            else:
                c = ks.release_columns(p, e)
                ref_stop = stop_id_of_key.get(c['ref_key'], '') if c['ref_key'] else ''   # published ID of the station whose point is borrowed
                if c['ref_key'] and not ref_stop:
                    missing.append(key)
                r = row(sid, name, c['coord_class'], c['coord_method'], c['reference'], c['reference_id'], c['reference_label'],
                        c['reference_distance_m'], c['checked_within_km'], ref_stop, c.get('reference_note', ''))
        else:
            r = row(sid, name, 'unrecorded', 'unrecorded')
        stat[r['coord_class']] += 1
        stat['id_' + ('yes' if r['reference_id'] or r['reference_stop_id'] else 'no')] += 1
        out[sid] = r
    if missing:
        raise SystemExit(f'★★ 座標KB の表から座標を当てた公開版の驛 {len(missing)} に出典が無いか、点を借りた驛が公開版に無い'
                         f'（場所の表の出典・対応の表の使い方の欄）: ' + '・'.join(f'{a}〔{b}〕' for a, b in missing[:10]))
    for p in parents:
        c = out.get(rep_child.get(p['stop_id'], ''))
        out[p['stop_id']] = row(p['stop_id'], p['stop_name'], c['coord_class'] if c else 'unrecorded',
                                'parent_station', ref_stop=rep_child.get(p['stop_id'], ''))
    return out, dict(stat)
