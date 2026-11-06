"""
Operating-day tables of the published dataset, and merging of ship trips with printed dates
(called from scripts/build_release_gtfs.py).

The published calendar runs every trip daily from 1925-03-28 to 04-30. Trips the printed timetable does not show
as daily are not split by calendar; they are described in two tables:

  extras/printed_sailings.csv  one row per sailing of the shipping tables with printed dates (24 tables, p189-p192):
                               the printed dates, the published trip (trip_id) carrying its times, and the stops used
                               (stop_sequences).
  extras/operating_days.csv    trips that do not run daily (per published trip_id): ships with printed dates,
                               fixed days of the month, alternate days, suspended days, irregular.

tools/make_printed_days_gtfs.py builds from these two a GTFS that follows the printed operating days.

Dates come from data/tables/sailing_dates.csv (transcription of the 【運航日】 (sailing days) part of the
workbook notes). Because GTFS has no dates, distinct sailings with identical times are either already merged into
one trip at integration (crossline_dedup, different line names) or appear as same-time trips in one table. The
latter are merged into one trip here (RELEASE_MERGE_SAME_SAILINGS). printed_sailings.csv records which sailing
went into which trip.
"""
import csv
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAILINGS_CSV = os.path.join(BASE_DIR, 'data', 'tables', 'sailing_dates.csv')
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
import known_kanji_variants as kv  # noqa: E402

YEAR = 1925
KEY_RE = re.compile(r'__U(p\d{4}_tb[0-9-]+)_(\d+)$')      # key suffix of an unnumbered trip: U<sheet name>_<column>

PRINTED_SAILING_FIELDS = ['sailing_id', 'page', 'source_sheet', 'table_name', 'line_name', 'direction_raw', 'column',
                          'ship', 'ports', 'printed_dates', 'service_date', 'trip_id', 'stop_sequences', 'how',
                          'table_note', 'note']
OPERATING_DAYS_FIELDS = ['trip_id', 'kind', 'operating_days', 'n_sailings', 'printed_text', 'source_sheets', 'note']

# Ships on fixed days of the month, alternate days, or with suspended days (the 【運航頻度】 (frequency) text of
#   service_frequency.csv, read and turned into machine-usable rules).
#   Key = suffix of the internal trip key (U<sheet name>_<column>); value = kind, calendar rule, printed text.
MONTHLY_RULES = {
    'p0193_tb002-1-1_1': ('monthly', 'day:1', '東京發 毎月一日'),
    'p0193_tb002-1-1_2': ('monthly', 'day:21', '東京發 毎月廿一日'),
    'p0193_tb002-2-1_1': ('monthly', 'day:3', '三宅島（坪田村）發 毎月三日'),
    'p0193_tb002-2-1_2': ('monthly', 'day:23', '大島（波浮港村）發 毎月廿三日'),
    'p0193_tb003-1-1_1': ('monthly', 'day:2,8,14,20,26', '東京發 毎月 2・8・14・20・26 日（但天候ノ都合ニヨリ出發期日ヲ變更スルコトアリ）'),
    'p0193_tb003-2-1_1': ('monthly_days_not_printed', '', '八丈島からの戻りの出航日は刷られていない（東京發は毎月 2・8・14・20・26 日）'),
    'p0194_tb004-1-1_1': ('daily_except', 'except_day:16,last', '毎日（但 毎月十六日及月末日ハ休航）'),
    'p0194_tb004-2-1_1': ('daily_except', 'except_day:16,last', '毎日（但 毎月十六日及月末日ハ休航）'),
    'p0195_tb001-1-1_1': ('alternate_days', 'even', '大阪發 毎偶數日'),
    'p0195_tb001-2-1_1': ('alternate_days', 'even', '門司發 毎偶數日'),
    'p0195_tb002-1-1_1': ('alternate_days', 'odd', '大阪發 毎奇數日'),
    'p0195_tb002-2-1_1': ('alternate_days', 'odd', '若松發 毎奇數日'),
    'p0195_tb003-1-1_1': ('alternate_days', 'odd', '大阪發 毎奇數日'),
    'p0195_tb003-2-1_1': ('alternate_days', 'even', '鹿兒島發 毎偶數日'),
    'p0195_tb004-1-1_1': ('daily_except', 'except_weekday:Mon', '毎日（但毎週月曜日ニハ休航）'),
    'p0195_tb004-2-1_1': ('daily_except', 'except_weekday:Mon', '毎日（但毎週月曜日ニハ休航）'),
}


def _read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _md(s):
    m, d = s.split('.')
    return date(YEAR, int(m), int(d))


def _mins(t):
    if not t:
        return None
    h, m, _s = t.split(':')
    return int(h) * 60 + int(m)


def _suffix(key):
    m = KEY_RE.search(key or '')
    return f'{m.group(1)}_{m.group(2)}' if m else None


def load_sailings():
    rows = _read(SAILINGS_CSV)
    for r in rows:
        r['_ports'] = r['ports'].split('|')
        r['_dates'] = [[_md(x) for x in c.split('・')] if c else [] for c in r['printed_dates'].split('|')]
    return rows


def sailing_sheets():
    return {r['source_sheet'] for r in load_sailings()}


def collapse_same_sailings(keep_trips, st_of, key_of):
    """Merge trips from the shipping tables with printed dates that have the same route, direction, stops and times.
    The first trip in order is kept. Return (kept trips, {merged trip: kept trip})."""
    sheets = sailing_sheets()
    first, merged = {}, {}
    for t in keep_trips:
        suf = _suffix(key_of.get(t['trip_id'], ''))
        if not suf or suf.rsplit('_', 1)[0] not in sheets:
            continue
        sig = (t['route_id'], t.get('direction_id', ''),
               tuple((r['stop_id'], r['arrival_time'], r['departure_time']) for r in st_of[t['trip_id']]))
        if sig in first:
            merged[t['trip_id']] = first[sig]
        else:
            first[sig] = t['trip_id']
    return [t for t in keep_trips if t['trip_id'] not in merged], merged


def _service_date(sailing, rep_rows, stop_name):
    """GTFS service date of the sailing: the date printed for the port of the trip's first stop, minus the days
    contained in that stop's time."""
    first = rep_rows[0]
    name = stop_name.get(first['stop_id'], '').split('〈')[0]
    t = _mins(first['departure_time'] or first['arrival_time']) or 0
    for p, ds in zip(sailing['_ports'], sailing['_dates']):
        if ds and kv.equivalent(p, name):
            return ds[-1] - timedelta(days=t // 1440)          # if 著 and 發 differ, the 發 (departure) date
    ds = next(d for d in sailing['_dates'] if d)
    return ds[-1]


def _company(line):
    m = re.match(r'(.+?會社)', line or '')
    return m.group(1) if m else line


def _date_ok(sailing, row, sd, stop_name):
    """Whether this stop's time agrees, in days, with the date printed for that port of this sailing."""
    name = stop_name.get(row['stop_id'], '').split('〈')[0]
    for p, ds in zip(sailing['_ports'], sailing['_dates']):
        if ds and kv.equivalent(p, name):
            ts = [x for x in (_mins(row['arrival_time']), _mins(row['departure_time'])) if x is not None]
            return any(sd + timedelta(days=t // 1440) in ds for t in ts)
    return False


def build(keep_trips, st_of, key_of, merged, qa_rows, stop_name, service_frequency, trip_attributes):
    """Build the rows of both tables (trip_id stays internal here; it is rewritten to published IDs later)."""
    kept = {t['trip_id'] for t in keep_trips}
    tid_of_suffix = {}
    for tid, key in key_of.items():
        suf = _suffix(key)
        if suf:
            tid_of_suffix.setdefault(suf, tid)
    tid_of_key = {k: t for t, k in key_of.items()}
    # trips merged into a trip of another line name at integration (crossline_dedup): partner key and its station x time
    partner, snap = {}, defaultdict(list)
    for r in qa_rows:
        if r['kind'] in ('crossline_dedup', 'crossline_dedup2'):
            m = re.search(r'相手=(\S+)', r['detail'])
            if m:
                partner[r['key']] = m.group(1)
        elif r['kind'] in ('crossline_dedup_stop', 'crossline_dedup2_stop'):
            snap[r['key']].append((r['stop_name'], r['dep_time'] or r['arr_time']))
    removed_by_suffix = {}
    for k in partner:
        suf = _suffix(k)
        if suf:
            removed_by_suffix[suf] = k

    sailings = load_sailings()
    ps_rows, by_rep = [], defaultdict(list)
    counts = defaultdict(int)
    for s in sailings:
        suf = f"{s['source_sheet']}_{s['trip_id']}"
        tid = tid_of_suffix.get(suf)
        rep, seqs, how = None, [], ''
        if tid and tid in kept:
            rep, how = tid, 'own_trip'
        elif tid and tid in merged:
            rep, how = merged[tid], 'merged_same_times_in_table'
        elif tid:
            how = 'dropped_single_stop'
        elif suf in removed_by_suffix:
            k = removed_by_suffix[suf]
            p_tid = tid_of_key.get(partner[k])
            p_tid = merged.get(p_tid, p_tid)
            if p_tid in kept:
                rep, how = p_tid, 'merged_same_times_other_line'
            else:
                how = 'merged_partner_missing'
        else:
            how = 'no_printed_times' if '便にできない' in s['table_note'] else 'not_in_gtfs'
        if rep:
            rows = st_of[rep]
            if how == 'merged_same_times_other_line' and len(snap[removed_by_suffix[suf]]) < 2:
                # a sailing with only one printed time (e.g. the p191 table with only 靑島發 11.00): one stop is not a trip
                how, rep = 'one_printed_time', None
            elif how == 'merged_same_times_other_line':
                # use only stops matching the merged trip's station x time from the integration log
                # (allowing multiples of 24 hours for crossing midnight)
                want = snap[removed_by_suffix[suf]]
                for r in rows:
                    n = stop_name.get(r['stop_id'], '').split('〈')[0]
                    ts = {x % 1440 for x in (_mins(r['arrival_time']), _mins(r['departure_time'])) if x is not None}
                    if any(kv.equivalent(n, w.split('〈')[0]) and _mins(t + ':00') % 1440 in ts for w, t in want if t):
                        seqs.append(r['stop_sequence'])
                if len(seqs) < 2:
                    how, rep, seqs = 'merged_stops_unmatched', None, []
                elif _company(s['line_name']) == _company(key_of.get(rep, '').split('__')[0]):
                    # the same company's route is also printed in another table (p192 to 大連 -> band in the p6
                    # connection table): use all stops and times of the target trip only if every time agrees in
                    # days with this sailing's dates (p192 has no figure for the 大連 arrival)
                    base_rows = [r for r in rows if r['stop_sequence'] in set(seqs)]
                    sd0 = _service_date(s, base_rows, stop_name)
                    if all(_date_ok(s, r, sd0, stop_name) for r in rows):
                        seqs = [r['stop_sequence'] for r in rows]
                        how = 'merged_same_times_same_company'
            else:
                seqs = [r['stop_sequence'] for r in rows]       # same-time trip in the same table: the kept trip's stops as they are
        use = [r for r in st_of[rep] if r['stop_sequence'] in set(seqs)] if rep else []
        sd = _service_date(s, use, stop_name).isoformat() if rep else ''
        row = {'sailing_id': f"{s['source_sheet']}#{s['trip_id']}", 'page': s['page'],
               'source_sheet': s['source_sheet'], 'table_name': s['table_name'], 'line_name': s['line_name'],
               'direction_raw': s['direction_raw'], 'column': s['trip_id'], 'ship': s['ship'], 'ports': s['ports'],
               'printed_dates': s['printed_dates'], 'service_date': sd, 'trip_id': rep or '',
               'stop_sequences': ';'.join(seqs), 'how': how, 'table_note': s['table_note'], 'note': s['note']}
        ps_rows.append(row)
        counts[how] += 1
        if rep:
            by_rep[rep].append(row)

    od_rows = []
    for rep, rows in by_rep.items():
        days = sorted({r['service_date'] for r in rows})
        od_rows.append({'trip_id': rep, 'kind': 'printed_dates', 'operating_days': ';'.join(days),
                        'n_sailings': len(rows),
                        'printed_text': '; '.join(f"{r['ship']} {r['printed_dates'].replace('|', '→')}" for r in rows),
                        'source_sheets': ' '.join(sorted({r['source_sheet'] for r in rows})),
                        'note': '日付の刷られた航路の表（型B）の出航。1 行ずつは printed_sailings.csv'})
    seen = {r['trip_id'] for r in od_rows}
    for r in service_frequency:
        suf = _suffix(r['trip_key'])
        rule = MONTHLY_RULES.get(suf)
        tid = tid_of_key.get(r['trip_key'])
        if not rule or not tid or tid not in kept or tid in seen:
            continue
        seen.add(tid)
        od_rows.append({'trip_id': tid, 'kind': rule[0], 'operating_days': rule[1], 'n_sailings': '',
                        'printed_text': (r.get('frequency_raw') or '').strip(), 'source_sheets': r['source_sheet'],
                        'note': rule[2]})
    for r in trip_attributes:
        toks = [t for t in r['other_tokens'].split('|') if t.startswith('不')]
        tid = tid_of_key.get(r['trip_key'])
        if not toks or not tid or tid not in kept or tid in seen:
            continue
        seen.add(tid)
        od_rows.append({'trip_id': tid, 'kind': 'irregular', 'operating_days': '', 'n_sailings': '',
                        'printed_text': ' '.join(toks), 'source_sheets': r['source_sheets'],
                        'note': '原本の列頭に不定期の印「不」＝運転日は刷られていない'})
    return ps_rows, od_rows, dict(counts)
