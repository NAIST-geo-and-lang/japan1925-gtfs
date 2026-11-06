"""
build_frequency_sections.py — make the frequency-only tables (sections without a timetable grid) machine-readable as headway tables

Input
  data/tables/frequency_only/frequency_only.csv (master copy of the printed text)
  data/tables/frequency_only/frequency_sections_overrides.csv (optional): ends, first/last departures, headway and
    running time written by hand for sections that cannot be parsed
Output
  INTEGRATED_DIR/frequency_sections.csv: one row per section and direction. With GTFS_FREQ_SECTIONS=1, generate_gtfs.py
  reads it, writes routes (RQ...), stops (SQ...), template trips (TQ...) and frequencies.txt, and puts a copy with
  template_trip_id filled in at GTFS_DIR/frequency_sections.csv.

Only four printed numbers are used (first departure, last departure, headway, running time). The only addition is
  "arrival (著) at the terminus = first departure + running time". No workbook sheets are made; all trips are estimated (TQ).

Reading rules (summary)
  S1 Template trip: departure (發) at the first station = first departure; arrival (著) at the terminus = first departure
     + running time. Sections without a running time are not output.
  S2 Service period = first to last departure (inclusive). "頃" (about) is dropped.
  S3 Headway = the upper bound when a range is given. "N 回" (N times) gives (last − first) ÷ (N − 1).
     "頻繁ニ" (frequent) and seasonal service are not output.
  S4 a.m./p.m.: the first departure is a.m., the last is p.m. (the legend "太字ハ午後" says bold means p.m., and last
     departures are printed in bold; 12.MM is 24:MM).
  S5 Both directions: "X發…／Y發…" gives two rows. Without station names, both directions get the same period.
  S6 Intermediate stations: station names from the station column, names only (no times).
  S8 Sections whose ends cannot be read: overrides.
  S9 Grid-and-box tables (default ON; FREQ_SECTIONS_BOX_GRID=0 omits them): a small grid of printed first, switch-over
     and last departures with frequency boxes "此間○分毎ニ運轉" between them (type "頻度記載（始發・終發の時刻と此間○分毎の箱…）"
     with no workbook sheet; p36 靜岡電氣鐵道線). Each direction is split into "window" rows, from one printed time up to
     just before the next, stepped by the box headway, plus one row for the last printed time, appended after the other
     sections (TQ/SQ/RQ numbers of existing sections do not change). a.m./p.m. from "…は太字（午後）" in the note.
"""
import csv
import os
import re
import sys
import unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INT_DIR = os.path.join(BASE, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'))
WORK = os.path.join(BASE, 'data', 'tables', 'frequency_only')
SRC = os.path.join(WORK, 'frequency_only.csv')
OVERRIDES = os.path.join(WORK, 'frequency_sections_overrides.csv')
OUT = os.path.join(INT_DIR, 'frequency_sections.csv')

# S9: output grid (printed first, switch-over and last departures) + box (此間○分毎) tables as template trips and
#   frequencies.txt like other sections, without sheets (p36 靜岡電氣鐵道線, 靜岡驛前–清水). Default ON.
#   Previous behavior = FREQ_SECTIONS_BOX_GRID=0 (rows of this type are not output).
#   Boxes in tables that have a sheet (p63 金石電氣鐵道線) belong to build_frequency_box.py and are left out.
BOX_GRID = os.environ.get('FREQ_SECTIONS_BOX_GRID', '1') == '1'
# On lines whose station column is split as "本線：…／支線：…" (main line / branch), a section entering the branch
#   (origin and destination in different groups) is joined at the station found in both groups (the junction)
#   (e.g. 玉川電氣鐵道線 FQ002 "天現寺橋―世田谷" enters the branch at 三軒茶屋).
#   Default ON. Previous behavior (cut from the main-line sequence) = FREQ_SECTIONS_BRANCH_JOIN=0.
BRANCH_JOIN = os.environ.get('FREQ_SECTIONS_BRANCH_JOIN', '1') != '0'
BOX_GRID_TYPE = '頻度記載（始發・終發の時刻と此間'
# Estimate numbers not printed in the original (running time, service hours). Sections with grounds for an estimate are
#   added from `data/tables/frequency_only/frequency_sections_estimates.csv` (one row per section with its grounds;
#   split by direction only where times differ by direction).
#   A = round trip (departure and return are printed) / B = service hours borrowed from the main line /
#   C = running time estimated from mileage.
#   Rows are appended at the end (the original "not output" rows stay, so TQ/SQ/RQ numbers of existing sections do not
#   change). source = `estimate` (`estimate_ship` for ships: generate_gtfs sets route_type 4); the note starts with "推定:".
#   Default ON. Previous behavior (not output) = FREQ_SECTIONS_ESTIMATE=0.
ESTIMATE = os.environ.get('FREQ_SECTIONS_ESTIMATE', '1') != '0'
ESTIMATES = os.path.join(WORK, 'frequency_sections_estimates.csv')
# Replace a printed running time that contradicts the rest of the original with the estimate (e.g. p93 阪堺線 FQ055
#   "〃―宿院 約 6 分", where other sections of the same printed block give 26.5–33.5 minutes). When a type-C row of the
#   estimates table (running time only) points to a section with a printed running time, only the running time of that
#   section's rows is replaced, in place (TQ/SQ/RQ numbers do not change); source = estimate and the note starts with
#   "推定:" (estimated sections are not used as the yardstick for apportioning times). frequency_only.csv keeps the
#   printed value. Default ON. Previous behavior (no replacement; that estimate row is unused) = FREQ_SECTIONS_ESTIMATE_REPLACE=0.
ESTIMATE_REPLACE = os.environ.get('FREQ_SECTIONS_ESTIMATE_REPLACE', '1') != '0'

FIELDS = ['section_id', 'page', 'line_name', 'direction', 'origin', 'destination',
          'first_dep', 'last_dep', 'duration_min', 'interval_min_lo', 'interval_min_hi',
          'headway_secs', 'exact_times', 'est_trips', 'stations', 'pm_reading',
          'template_trip_id', 'source', 'note']

KANJI = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6}


def nfc(s):
    return unicodedata.normalize('NFC', s) if isinstance(s, str) else s


def clean_name(x):
    """Clean a station name: drop brackets, △ and spaces."""
    x = re.sub(r'[（(][^（）()]*[)）]', '', nfc(x))
    return x.strip('△ 　　')


def real_line_name(raw):
    """line_name_raw ("目黑・蒲田間（連帶線）（目黑蒲田電鐵線）") -> line name (the trailing （…線）, or else the name
    without brackets). This rule matches line_name in the coordinate tables."""
    raw = nfc(raw)
    stripped = re.sub(r'[（(].*?[)）]', '', raw).strip('△ 　')
    paren = [x.strip() for x in re.findall(r'[（(]([^（）()]*線)[)）]', raw)
             if x.strip() not in ('連帶線', '非連帶線') and not x.strip().startswith('電車')]
    # If the bracket holds "…支線" (大濱支線) and the text outside is already a line name (南海鐵道線 阪堺線),
    # use the outside: the branch belongs to the same line
    if paren and paren[-1].endswith('支線') and stripped.endswith('線'):
        paren = []
    return (paren[-1] if paren else stripped).split('　')[0].strip()


def section_ends(sec):
    """section_raw -> [ends...] (first = origin, last = destination). [] if unreadable."""
    s = nfc(sec).strip()
    s = re.sub(r'^(本線|支線|海岸線)[　 ]+', '', s)
    s = re.sub(r'[（(][^（）()]*[)）]', '', s)
    s = re.sub(r'間$', '', s).strip()
    if '發' in s:
        return []  # the "阪本發 三井寺下及紺屋關行" type goes to overrides
    parts = [clean_name(p) for p in re.split(r'[―－—・\-–]+', s) if clean_name(p)]
    return parts if len(parts) >= 2 else []


# A branch mark written inside the station column ("（和歌浦口ヨリ分岐線）権現前・新和歌浦").
#   Like "／支線：…", it means a separate branch starts here, so it starts a new group with the junction first.
BRANCH_MARK = re.compile(r'^[（(](.+?)(?:ヨリ|より)(?:分岐線|分岐|支線)[）)]')


def station_list(stations_raw):
    """stations column -> [[stations...], [stations...]] (one list per group, as in "本線：…／支線：…").

    With BRANCH_JOIN, a "（X ヨリ分岐線）" mark inside a group splits it there and
    puts the junction X first in the new group (so path_between can join at that station).
    """
    out = []
    for seg in re.split(r'[／/]', nfc(stations_raw or '')):
        seg = re.sub(r'^(本線|支線|海岸線)[：:]', '', seg.strip())
        names, cur, junction = [], [], None
        for tok in seg.split('・'):
            tok = tok.strip()
            m = BRANCH_MARK.match(tok) if BRANCH_JOIN else None
            if m:
                if cur:
                    names.append(cur)
                junction = clean_name(m.group(1))
                cur = [junction] if junction else []
                tok = BRANCH_MARK.sub('', tok)
            nm = clean_name(tok)
            if nm:
                cur.append(nm)
        if cur:
            names.append(cur)
        for group in names:
            group = [n for n in group if not n.startswith('主要駅') and n not in ('遊覽地',)]
            if group:
                out.append(group)
    return out


def path_between(segments, origin, dest):
    """Take the origin -> destination sequence from the station column groups (S6). An end not found is added by itself."""
    def find(names, x, strict=False):
        # exact match first (吉野 rather than 吉野口, 犬山 rather than 犬山口); else a prefix/suffix match (日光停車場前 ⊃ 停車場前)
        for i, n in enumerate(names):
            if n == x:
                return i
        if strict:
            return None
        for i, n in enumerate(names):
            if n.startswith(x) or x.startswith(n) or n.endswith(x) or x.endswith(n):
                return i
        return None
    # Try exact matches in all groups first. Checking "exact, then fuzzy" group by group lets a fuzzy match in an earlier
    #   group beat an exact match in a later one (e.g. 新和歌浦 matching 和歌浦 on the main line and never entering the branch).
    for strict in (True, False):
        for names in segments:
            i, j = find(names, origin, strict), find(names, dest, strict)
            if i is not None and j is not None and i != j:
                seq = names[i:j + 1] if i < j else list(reversed(names[j:i + 1]))
                note = ''
                if seq[0] != origin or seq[-1] != dest:
                    note = f'両端の名を驛名欄の表記に合わせた（{origin}→{seq[0]}／{dest}→{seq[-1]}）'
                return seq, note
        if strict and BRANCH_JOIN and len(segments) > 1:
            break   # if no single group holds both ends exactly, try crossing groups before fuzzy matching
    if BRANCH_JOIN and len(segments) > 1:
        # Cross groups (main line -> branch): join at a station found in both groups (the junction).
        #   The shortest join is used (ties follow group and station order, so the result is deterministic).
        best = None
        for a in segments:
            i = find(a, origin, True)
            if i is None:
                continue
            for b in segments:
                if b is a:
                    continue
                j = find(b, dest, True)
                if j is None:
                    continue
                for x in a:
                    ja, jb = find(a, x, True), find(b, x, True)
                    if ja is None or jb is None:
                        continue
                    head = a[i:ja + 1] if i <= ja else list(reversed(a[ja:i + 1]))
                    tail = b[jb:j + 1] if jb <= j else list(reversed(b[j:jb + 1]))
                    if len(head) < 2 or len(tail) < 2 or head[-1] != tail[0]:
                        continue
                    seq = head + tail[1:]
                    if best is None or len(seq) < len(best[0]):
                        best = (seq, x)
        if best:
            return best[0], f'本線と支線を分岐駅 {best[1]} でつないだ'
    for names in segments:
        i, j = find(names, origin), find(names, dest)
        if i is not None and j is None:
            return names[i:] + [dest], '終点が驛名欄に無い（両端を足した）'
        if j is not None and i is None:
            return [origin] + names[:j + 1], '起点が驛名欄に無い（両端を足した）'
    return [origin, dest], '驛名欄に両端が無い（両端だけ）'


_TIME = re.compile(r'(\d{1,2})\.(\d{2})')


def parse_first_last(raw, origin):
    """first_last_raw -> {'outbound': (first_hhmm, last_hhmm, pm_note), 'inbound': ...}.
    With "X發 … ／ Y發 …", X is the origin side. Without station names, both directions get the same period."""
    raw = nfc(raw or '').replace('頃', '')
    if not raw.strip():
        return {}
    parts = [p for p in re.split(r'／', raw) if _TIME.search(p)]
    res = {}
    for k, p in enumerate(parts):
        times = _TIME.findall(p)
        if len(times) < 2:
            continue
        (h1, m1), (h2, m2) = times[0], times[-1]
        first = f'{int(h1) % 12:02d}:{m1}'                       # first departure = a.m. (12.MM is 0:MM)
        last = f'{24 if int(h2) == 12 else int(h2) + 12:02d}:{m2}'  # last departure = p.m. (12.MM is 24:MM)
        m = re.match(r'\s*([^\s\d發]+)發', p)
        label = clean_name(m.group(1)) if m else ''
        if label:
            d = 'outbound' if (label == origin or label in origin or origin in label) else 'inbound'
        else:
            d = 'outbound' if k == 0 else 'inbound'
        res.setdefault(d, (first, last, f'始発 {h1}.{m1}＝午前／終発 {h2}.{m2}＝午後'))
    if len(res) == 1 and not any(re.search(r'發', p) for p in parts):
        res['inbound' if 'outbound' in res else 'outbound'] = list(res.values())[0]
    return res


def _minutes_list(text):
    """Turn "N 時間 M 分" and "N 分" into a list of minutes (times H.MM and "N 回" are excluded)."""
    t = _TIME.sub(' ', nfc(text or ''))
    t = re.sub(r'\d+\s*回', ' ', t)
    vals = []
    for h, m in re.findall(r'(\d+|[一二三四五六])\s*時間\s*(\d+)?\s*分?', t):
        vals.append((KANJI.get(h) or int(h)) * 60 + (int(m) if m else 0))
    t2 = re.sub(r'(\d+|[一二三四五六])\s*時間\s*(\d+)?\s*分?', ' ', t)
    vals += [int(x) for x in re.findall(r'(\d+)\s*分', t2)]
    return vals


def parse_interval(raw, first, last):
    """-> (lo, hi, note). (None, None, reason) if unreadable."""
    raw = nfc(raw or '')
    if not raw.strip():
        return None, None, '間隔の記載なし'
    if '頻繁' in raw:
        return None, None, '「頻繁ニ運轉」＝間隔の数字なし'
    if '每年' in raw or '毎年' in raw or '日曜' in raw:
        return None, None, '季節・曜日運転＝出さない'
    m = re.search(r'(\d+)\s*回', raw)
    if m and first and last:
        n = int(m.group(1))
        span = _hhmm(last) - _hhmm(first)
        if n >= 2 and span > 0:
            hw = round(span / (n - 1))
            return hw, hw, f'「{n} 回」から（終発−始発）÷（回数−1）＝{hw} 分'
    vals = _minutes_list(raw)
    if not vals:
        return None, None, '間隔が読めない'
    return min(vals), max(vals), ''


def parse_duration(raw):
    raw = nfc(raw or '')
    if not raw.strip():
        return None
    vals = _minutes_list(raw)
    return max(vals) if vals else None


def _hhmm(s):
    h, m = s.split(':')
    return int(h) * 60 + int(m)


def _fmt(m):
    return f'{m // 60:02d}:{m % 60:02d}'


def load_overrides():
    out = {}
    if not os.path.exists(OVERRIDES):
        return out
    with open(OVERRIDES, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            out[(nfc(r['section_id']).strip(), (r.get('direction') or '').strip() or '*')] = r
    return out


def _hm_key(hm):
    """Make '8.00' and '08.00' the same key."""
    h, m = hm.split('.')
    return f'{int(h)}.{m}'


def _to_min(hm, pm):
    """'H.MM' -> minutes from 0:00. a.m. = H mod 12 (12.MM is 0:MM); p.m. = H + 12 (12.MM is 24:MM), as in S4."""
    h, m = hm.split('.')
    h, m = int(h), int(m)
    return ((24 if h == 12 else h + 12) if pm else h % 12) * 60 + m


def parse_grid(text_raw):
    """text_raw after "〔小さな格子〕" (small grid) -> [(origin station, [('t', 'H.MM') | ('box', lo, hi), ...]), ...]
    (one row per direction). Rows are separated by "／", cells by "｜". The first cell is "(page ref, mark) station 發 H.MM".
    "（同上）" (ditto) = the box at the same position in the row above. Any unreadable cell gives [] (not output)."""
    s = nfc(text_raw or '')
    if '〔小さな格子〕' not in s:
        return []
    out, prev = [], []
    for line in s.split('〔小さな格子〕', 1)[1].split('／'):
        cells = [c.strip() for c in line.split('｜')]
        m = re.search(r'([^\s\d,，●◎\-－]+)\s*發\s*(\d{1,2}\.\d{2})$', cells[0])
        if not m:
            return []
        toks = [('t', m.group(2))]
        for i, c in enumerate(cells[1:], start=1):
            if re.fullmatch(r'\d{1,2}\.\d{2}', c):
                toks.append(('t', c))
            elif '同上' in c:
                if i >= len(prev) or prev[i][0] != 'box':
                    return []
                toks.append(prev[i])
            elif '毎' in c and _minutes_list(c):
                v = _minutes_list(c)
                toks.append(('box', min(v), max(v)))
            else:
                return []
        out.append((clean_name(m.group(1)), toks))
        prev = toks
    return out


def bold_pm_times(note):
    """Note text "8.00／8.53／11.24／11.41 は太字（午後）" -> {'8.00', '8.53', '11.24', '11.41'}. None if absent.
    Times inside a grid (switch-overs) are not settled by S4's "first = a.m., last = p.m.", so the note in which the
    transcriber listed the bold (p.m.) times is used."""
    m = re.search(r'((?:\d{1,2}\.\d{2}\s*[／/・、,]\s*)*\d{1,2}\.\d{2})\s*は太字（午後）', nfc(note or ''))
    if not m:
        return None
    return {f'{int(h)}.{mm}' for h, mm in _TIME.findall(m.group(1))}


def build_box_grid(src_rows):
    """S9: grid (printed first, switch-over and last departures) + box (此間 N 分毎) tables; only those without a sheet.
    Each direction is split into windows: rows from printed time a to just before the next printed time b, stepped by the
    box headway (first_dep = a, last_dep = one minute before b, so the end_time that generate_gtfs writes to frequencies.txt
    is b), and one row for the last printed time (first_dep = last_dep).
    Every printed time becomes the departure of an estimated trip (no times are made up; the only addition is S1's
    arrival at the terminus)."""
    out = []
    for r in src_rows:
        if not nfc(r['type']).startswith(BOX_GRID_TYPE):
            continue
        if (r.get('already_sheet') or '').strip() not in ('', 'N'):
            continue
        sid, line = nfc(r['id']), real_line_name(r['line_name_raw'])
        base = {'section_id': sid, 'page': r['page'], 'line_name': line, 'source': 'csv'}
        ends = section_ends(r['section_raw'])
        grid = parse_grid(r['text_raw'])
        pm = bold_pm_times(r['note'])
        if not ends or not grid or pm is None:
            why = ('両端が読めない' if not ends else '格子が読めない' if not grid
                   else '午前午後の読み（note の「…は太字（午後）」）が無い')
            out.append({**base, 'note': f'S9 格子＋箱：{why}（出さない）'})
            continue
        origin, dest = ends[0], ends[-1]
        seq, seq_note = path_between(station_list(r['stations']), origin, dest)
        dur = parse_duration(r['duration_raw'])
        for label, toks in grid:
            if label == origin or label in origin or origin in label:
                d, s = 'outbound', seq
            elif label == dest or label in dest or dest in label:
                d, s = 'inbound', list(reversed(seq))
            else:
                out.append({**base, 'note': f'S9 格子＋箱：行の起点「{label}」が両端に無い（出さない）'})
                continue
            times = [(i, t[1]) for i, t in enumerate(toks) if t[0] == 't']
            mins = [_to_min(hm, _hm_key(hm) in pm) for _, hm in times]
            reading = '・'.join(f'{hm}＝{"午後（太字）" if _hm_key(hm) in pm else "午前"}' for _, hm in times)
            common = {**base, 'direction': d, 'origin': s[0], 'destination': s[-1],
                      'duration_min': dur if dur is not None else '', 'exact_times': 0,
                      'stations': '・'.join(s), 'pm_reading': f'格子の刷り {reading}'}
            ok = (len(times) >= 2 and toks[-1][0] == 't'
                  and all(b > a for a, b in zip(mins, mins[1:]))
                  and all(j - i == 2 and toks[i + 1][0] == 'box' for (i, _), (j, _) in zip(times, times[1:])))
            if not ok:
                out.append({**common, 'note': 'S9 格子＋箱：刷られた時刻が増えていない・刷られた時刻の間に箱が 1 つずつ無い（出さない）'})
                continue
            n = len(times)
            for k in range(n):
                a = mins[k]
                box = toks[times[k][0] + 1] if k + 1 < n else toks[times[k - 1][0] + 1]
                lo, hi = box[1], box[2]
                span_txt = f'{lo}分毎' if lo == hi else f'{lo}分乃至{hi}分毎'
                if k + 1 < n:
                    last = mins[k + 1] - 1
                    what = f'刷られた {times[k][1]} から次の刷られた {times[k + 1][1]} の手前まで 此間{span_txt}'
                else:
                    last = a
                    what = f'刷られた終發 {times[k][1]} の 1 本（間隔は直前の箱）'
                row = {**common, 'first_dep': _fmt(a), 'last_dep': _fmt(last),
                       'interval_min_lo': lo, 'interval_min_hi': hi}
                notes = ([seq_note] if seq_note else []) + [f'S9 格子＋箱 窓 {k + 1}/{n}＝{what}']
                if dur is None:
                    notes.append('所要なし＝終点の著が作れない（出さない）')
                else:
                    row['headway_secs'] = hi * 60
                    row['est_trips'] = (last - a) // hi + 1
                row['note'] = '・'.join(notes)
                out.append(row)
    return out


def build():
    with open(SRC, encoding='utf-8-sig') as f:
        src_rows = list(csv.DictReader(f))
    rows = [r for r in src_rows if nfc(r['type']).startswith('頻度記載のみの区画')]
    overrides = load_overrides()
    out = []
    for r in rows:
        sid = nfc(r['id'])
        line = real_line_name(r['line_name_raw'])
        ov_any = overrides.get((sid, '*'))
        ends = section_ends(r['section_raw'])
        if ov_any and ov_any.get('origin'):
            ends = [clean_name(ov_any['origin']), clean_name(ov_any['destination'])]
        if not ends:
            out.append({'section_id': sid, 'page': r['page'], 'line_name': line, 'source': 'csv',
                        'note': f'両端が読めない（S8＝overrides に書く）: {r["section_raw"][:40]}'})
            continue
        origin, dest = ends[0], ends[-1]
        segments = station_list(r['stations'])
        seq, seq_note = path_between(segments, origin, dest)
        dur = parse_duration(ov_any['duration_raw'] if ov_any and ov_any.get('duration_raw') else r['duration_raw'])
        fl = parse_first_last(ov_any['first_last_raw'] if ov_any and ov_any.get('first_last_raw') else r['first_last_raw'], origin)
        if not fl:
            out.append({'section_id': sid, 'page': r['page'], 'line_name': line, 'origin': origin, 'destination': dest,
                        'stations': '・'.join(seq), 'source': 'csv', 'note': '始発・終発が読めない'})
            continue
        for d in ('outbound', 'inbound'):
            if d not in fl:
                continue
            first, last, pmnote = fl[d]
            s = seq if d == 'outbound' else list(reversed(seq))
            o, t = s[0], s[-1]
            ov = overrides.get((sid, d)) or ov_any
            lo, hi, inote = parse_interval(ov['interval_raw'] if ov and ov.get('interval_raw') else r['interval_raw'], first, last)
            row = {'section_id': sid, 'page': r['page'], 'line_name': line, 'direction': d, 'origin': o, 'destination': t,
                   'first_dep': first, 'last_dep': last, 'duration_min': dur if dur is not None else '',
                   'interval_min_lo': lo if lo is not None else '', 'interval_min_hi': hi if hi is not None else '',
                   'exact_times': 0, 'stations': '・'.join(s), 'pm_reading': pmnote,
                   'source': 'override' if ov else 'csv', 'note': ''}
            notes = [x for x in (seq_note, inote) if x]
            if dur is None:
                notes.append('所要なし＝終点の著が作れない（出さない）')
            if lo is None:
                notes.append('間隔なし（出さない）')
            if _hhmm(last) - _hhmm(first) < 120:
                notes.append('有効時間帯が 2 時間未満＝午前午後の読みを要確認')
            if dur is not None and lo is not None:
                span = _hhmm(last) - _hhmm(first)
                row['headway_secs'] = hi * 60
                row['est_trips'] = span // hi + 1
            row['note'] = '・'.join(notes)
            out.append(row)
    if BOX_GRID:
        out.extend(build_box_grid(src_rows))   # S9: appended (TQ/SQ/RQ numbers of existing sections do not change)
    if ESTIMATE:
        out.extend(build_estimates(out, {nfc(r['id']): r for r in rows}))   # estimates: appended after that
    return out


def build_estimates(built, src_by_id):
    """Build the rows to append from the estimates table (with ESTIMATE_REPLACE, printed running times are replaced in place)."""
    if not os.path.exists(ESTIMATES):
        print(f'  警告: 推定の表が無い（{ESTIMATES}）＝推定は出さない')
        return []
    with open(ESTIMATES, encoding='utf-8-sig') as f:
        est = list(csv.DictReader(f))
    add = []
    for e in est:
        sid = nfc(e['section_id']).strip()
        dur = int(e['duration_min'])
        why = '推定: ' + nfc(e['根拠']).strip()
        src = 'estimate_ship' if (e.get('route_type') or '').strip() == '4' else 'estimate'
        if not (e.get('first_dep') or '').strip():
            # Type C: add only the running time to the existing rows (first/last departure and headway are printed)
            base = [r for r in built if r['section_id'] == sid and r.get('direction')]
            if not base:
                print(f'  警告: 推定 {sid} の元の行が無い＝足さない')
            # Rows with a printed running time: replaced in place (FREQ_SECTIONS_ESTIMATE_REPLACE); no row is appended.
            printed = [r for r in base if str(r.get('duration_min', '')).strip() != '']
            if printed and not ESTIMATE_REPLACE:
                print(f'  推定 {sid}: 刷られた所要がある区画＝置き換えない（FREQ_SECTIONS_ESTIMATE_REPLACE=0）')
            for r in printed:
                if not ESTIMATE_REPLACE:
                    continue
                old_dur = r['duration_min']
                r['duration_min'] = dur
                r['source'] = src
                r['note'] = f'{why}（刷られた所要 {old_dur} 分を置き換えた）' + (f'・{r["note"]}' if r.get('note') else '')
            for r in base:
                if any(r is p for p in printed):
                    continue
                hi = r.get('interval_min_hi')
                if hi in ('', None):
                    continue
                n = {**r, 'duration_min': dur, 'source': src, 'template_trip_id': ''}
                n['headway_secs'] = int(hi) * 60
                n['est_trips'] = (_hhmm(r['last_dep']) - _hhmm(r['first_dep'])) // int(hi) + 1
                n['note'] = why
                add.append(n)
            continue
        # Types A and B: ends, stations and service hours also come from the estimates table
        r0 = src_by_id.get(sid, {})
        line = real_line_name(r0.get('line_name_raw', '')) if r0 else ''
        seq = [x for x in nfc(e['stations']).split('・') if x]
        first, last = e['first_dep'].strip(), e['last_dep'].strip()
        hi = int(e['interval_min'])
        dirs = [e['direction'].strip()] if e['direction'].strip() else ['outbound', 'inbound']
        for d in dirs:
            ss = seq if d == 'outbound' else list(reversed(seq))
            add.append({'section_id': sid, 'page': r0.get('page', ''), 'line_name': line, 'direction': d,
                        'origin': ss[0], 'destination': ss[-1], 'first_dep': first, 'last_dep': last,
                        'duration_min': dur, 'interval_min_lo': hi, 'interval_min_hi': hi,
                        'headway_secs': hi * 60, 'exact_times': 0,
                        'est_trips': (_hhmm(last) - _hhmm(first)) // hi + 1,
                        'stations': '・'.join(ss), 'pm_reading': '', 'source': src, 'note': why})
    return add


def main():
    rows = build()
    os.makedirs(INT_DIR, exist_ok=True)
    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in FIELDS})
    ok = [r for r in rows if r.get('headway_secs')]
    print(f'build_frequency_sections: 行 {len(rows)}（区画×方向）／frequencies.txt に出せる {len(ok)}・出せない {len(rows) - len(ok)} → {OUT}')
    for r in rows:
        if not r.get('headway_secs'):
            print(f'  - {r["section_id"]} p{r["page"]} {r["line_name"]} {r.get("direction", "")} {r.get("origin", "")}→{r.get("destination", "")}: {r.get("note", "")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
