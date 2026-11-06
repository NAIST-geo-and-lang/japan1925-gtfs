#!/usr/bin/env python3
"""
Add the transcription layer (transcription/) and the integrated layer (integrated/) to the published dataset.

    Called from items 33 and 34 of build_release_gtfs.py (RELEASE_TRANSCRIPTION=1 and RELEASE_INTEGRATED=1 by
    default; 0 = not added = previous behavior).
    Also runs alone: python3 scripts/release/package_layers.py <published dataset folder> <integrated work folder> [feed_version]

Rules
  - Quality records (quality/) are not included.
  - Workbook notes (row 12) and number notes (row 11) are reduced to "form B": only copies of what the original
    prints. The history of corrections (dates, person names, record numbers, reasons) is left out. Kept are
      (1) paragraphs whose heading (【…】) matches KEEP_TAG: notes of the original, whole-table notes, sailing
          frequency, nautical miles, legends, etc. (printed content and table layout)
      (2) unheaded text containing "此間": copies of the frequency-box text of the original (GTFS frequency trips
          are built from it)
    Notes of the original keep only the fixed first part ("原文" = station, 著/發, time (午前/午後/時間帯不明)).
    Within kept paragraphs, parenthetical notes and sentences containing work words (person names, record
    numbers, dates, names of internal tools or checks) are dropped. Number notes keep only the machine-added
    "from <sheet> (…)" part. A heading matching neither KEEP_TAG nor WORK_TAG stops the build (so copied text is
    never dropped silently).
  - Pink cell fills (FFC7CE, correction marks for reviewers) are removed. Cell comments are removed (with
    RELEASE_DROP_ALL_COMMENTS=0, only those containing work words, and author names are cleared). The document
    author field is cleared and created/modified times and the zip entry times are set to the feed_version date
    (same input gives the same bytes).

Output
  transcription/workbooks/pNNN[-NNN].xlsx          numbered workbooks (pipeline input), 178
  transcription/workbooks_before_numbering/…        workbooks before numbering, 178
  transcription/transcription_long.csv              the same content in long form (one row = sheet x train column x
                                                    station; columns without times also get a row)
  transcription/files.csv                           file name (ASCII) to original name (only with
                                                    RELEASE_INCLUDE_FILES_CSV=1; not created by default)
  integrated/integrated_stop_times.csv              integrated layer (after splitting) + published trip_id and stop_id
  integrated/trips_master.csv, stops_master.csv     trips and stations (station coordinates removed; internal
                                                    coordinates are not published)
  (split_trips_report.csv and qa_log.csv are not included: RELEASE_INCLUDE_SPLIT_REPORT, RELEASE_INCLUDE_QA_LOG)
"""
import csv
import io
import os
import re
import sys
import unicodedata
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from derived_tables import MARKERS_ALL, scrub_all, rewrite_work_words, rewrite_work_words_3, WORK_WORDS_3  # noqa: E402

TRIPNUM_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('TRIPNUM_DIR', '2_timetable_with_tripnum_v1'))
RAW_DIRS = [os.path.join(BASE_DIR, 'data', d) for d in
            os.environ.get('RAW_XLSX_DIR', '1_timetable_xlsx_v1,1_timetable_xlsx_added_v1').split(',')]

# ---------------------------------------------------------------------------
# Workbook notes and number notes (form B)
# ---------------------------------------------------------------------------
# headings for printed content and table layout (kept)
KEEP_TAG = re.compile(
    r'^(?:原本注記|表全体|p\d+ ?全体|ページ全体|この表|このシート|表の型|表題|港名|空きスロット|日次|運航頻度|運航日|海里|浬程|運賃|凡例|'
    r'時・分が無い港|時刻（原文）|通過|途中終着|区間便|著/發|神戸の著發|整列|書き起こさないもの|付属表|表の注記|表の下の注記|表頭の注記|'
    r'驛名「[^」]+」について)')
# headings for work history (dropped): dates, people, corrections, rebuilds, reasons for decisions, etc.
WORK_TAG = re.compile(
    r'20\d\d|決裁|了承|修正|是正|再構築|再書起|新規作成|起票|要確認|当方発見|照合|検出|追加|誤植|据置|'
    r'判定|原理|物理|drift|N-\d+|F\d+')
# work words dropped within kept paragraphs (in addition to MARKERS_ALL)
WORK_WORDS_NOTE = re.compile(
    r'20\d\d-\d\d-\d\d|20\d\d/\d\d?/\d\d?|hist-timetable|セッション|Step ?\d|lint|(?<![A-Za-z])L\d{2}(?:_|\b)|'
    r'[12]_v3|(?<![A-Za-z0-9])v\d(?![0-9A-Za-z])|再生成|抑制|起票|仕様 ?§|§\d|作業フロー|教訓集|scripts/|data/|\.xlsx|\.md\b|'
    r'trip_num_source=|dpi|ppi|PDF|是正|旧読み|原本再確認|変えていない|移しただけ')
# Drop instructions to reviewers, internal tool names, internal map remarks and old history from the notes
#   (explanations of how hard-to-read values were read are kept). On by default.
#   Previous behavior (not dropped) = RELEASE_NOTE_SCRUB_CHECKER=0.
NOTE_SCRUB_CHECKER = os.environ.get('RELEASE_NOTE_SCRUB_CHECKER', '1') == '1'
CHECKER_WORDS_NOTE = re.compile(r'再確認は不要|直さずこのまま|地図の位置|検出器|当初の')
CHECKER_REWRITES = []   # pairs that remove part of a sentence before dropping (none match the published workbook notes)
_DROP = re.compile(MARKERS_ALL.pattern + '|' + WORK_WORDS_NOTE.pattern
                   + ('|' + CHECKER_WORDS_NOTE.pattern if NOTE_SCRUB_CHECKER else ''))
# A two-page spread workbook whose file name omits the right page (近代デジタル交通網p97.xlsx holds the tables of
#   p97 and p98; there is no p98 workbook) lists both pages in pages of files.csv. On by default.
#   Previous behavior = RELEASE_FILES_PAGES_SPREAD=0.
FILES_PAGES_SPREAD = os.environ.get('RELEASE_FILES_PAGES_SPREAD', '1') == '1'
SPREAD_PAGES = {'近代デジタル交通網p97.xlsx': [97, 98]}
_PAREN = re.compile(r'（[^（）]*）|\([^()]*\)')
_SEG = re.compile(r'(?=【)')
_TAG = re.compile(r'【([^】]*)】')
_GENPON_CORE = re.compile(r'【原本注記】「[^」]*」＝[^※【]*?(?:（(?:午前|午後|時間帯不明)）|時刻なし)')
_ROW11 = re.compile(r'from \S+ \([^)]*\)')
_SEP_TAIL = re.compile(r'[\s　／/、・]+$')


def drop_work_words(text):
    """Drop parenthetical parts and sentences containing work words (_DROP); like derived_tables.scrub with a wider
    word list."""
    if not text:
        return text
    text = text.replace('★', '').replace('**', '')
    if NOTE_SCRUB_CHECKER:
        for pat, rep in CHECKER_REWRITES:
            text = pat.sub(rep, text)
    if not _DROP.search(text):
        return text.strip()

    def paren(m):
        s = m.group(0)
        open_, close = s[0], s[-1]
        inner = s[1:-1]
        if not _DROP.search(inner):
            return s
        parts = re.split(r'([・／、;；])', inner)
        keep, sep = [], ''
        for i, p in enumerate(parts):
            if i % 2:
                sep = p
                continue
            if p.strip() and not _DROP.search(p):
                keep.append((sep if keep else '') + p)
            sep = ''
        return f'{open_}{"".join(keep)}{close}' if keep else ''
    prev = None
    while prev != text:          # repeat until stable, for nested parentheses
        prev = text
        text = _PAREN.sub(paren, text)
    sentences = re.findall(r'[^。]*。|[^。]+$', text)
    text = ''.join(s for s in sentences if not _DROP.search(s))
    return re.sub(r'[ 　]{2,}', ' ', text).strip()


class UnknownTag(Exception):
    pass


def note_b(text, where=''):
    """Reduce one workbook-note cell to form B. Return '' if nothing is kept; raise UnknownTag for an unlisted heading."""
    if not text:
        return ''
    out = []
    for seg in _SEG.split(str(text)):
        if not seg.strip():
            continue
        m = _TAG.match(seg)
        if m:
            tag = m.group(1)
            if KEEP_TAG.match(tag):
                if tag == '原本注記':
                    core = _GENPON_CORE.match(seg)
                    seg = core.group(0) if core else drop_work_words(seg.split('※')[0])
                else:
                    if tag.startswith('驛名「'):
                        seg = re.sub(r'^【(驛名「[^」]+」について)[^】]*】', r'【\1】', seg)
                    seg = drop_work_words(seg)
                seg = _SEP_TAIL.sub('', seg)
                if _TAG.fullmatch(seg.strip()):      # only the heading is left
                    continue
                out.append(seg)
            elif WORK_TAG.search(tag):
                continue
            else:
                raise UnknownTag(f'{where}: 【{tag}】')
        elif '此間' in seg:                           # frequency-box text of the original
            s = _SEP_TAIL.sub('', drop_work_words(seg))
            if s:
                out.append(s)
    res = ''
    for s in out:                                    # join paragraphs in original order (the frequency reader reads up to the next 【)
        res += (s if (not res or s.startswith('【')) else ' ' + s)
    if NOTE_REWRITE_3:
        res = rewrite_work_words_3(res)
    return res.strip()


def note11_b(text):
    """Keep only the machine-added "from <sheet> (…)" part of a number note (row 11)."""
    if not text:
        return ''
    m = _ROW11.match(str(text).strip())
    return m.group(0) if m else ''


# ---------------------------------------------------------------------------
# Workbooks
# ---------------------------------------------------------------------------
PINK = 'FFC7CE'
COMMENT_DROP = re.compile(_DROP.pattern + r'|旧|skipped|書き起こし者|推定|trip_num|Step')
# Remove all cell comments (notes of the original live only in the row-12 workbook notes). On by default.
#   Previous behavior (remove only comments with work words) = RELEASE_DROP_ALL_COMMENTS=0.
DROP_ALL_COMMENTS = os.environ.get('RELEASE_DROP_ALL_COMMENTS', '1') == '1'
# The integration log qa_log.csv is not included (the source of published values can be traced via
#   extras/stop_time_source.csv and source_sheet in integrated_stop_times.csv). Previous behavior (included) =
#   RELEASE_INCLUDE_QA_LOG=1.
INCLUDE_QA_LOG = os.environ.get('RELEASE_INCLUDE_QA_LOG', '0') == '1'
# The split log split_trips_report.csv is not included either (same tracing as for qa_log).
#   Previous behavior (included) = RELEASE_INCLUDE_SPLIT_REPORT=1.
INCLUDE_SPLIT_REPORT = os.environ.get('RELEASE_INCLUDE_SPLIT_REPORT', '0') == '1'
# Normalize workbook formatting: remove all transcription-time fills and freeze the header rows and the three station
#   columns A-C (D14 in workbooks/, D11 in workbooks_before_numbering/). Values are unchanged. On by default.
#   Previous behavior = RELEASE_WORKBOOK_PLAIN=0.
WORKBOOK_PLAIN = os.environ.get('RELEASE_WORKBOOK_PLAIN', '1') == '1'
# Reword work-only names in the workbook notes (row 12) into the wording of the published documents: apply
#   derived_tables.WORK_REWRITES_3 (the same table as for extras) to the form-B notes, and stop if WORK_WORDS_3
#   remain. On by default. Previous behavior = RELEASE_REWRITE_WORK_WORDS_3=0 (also off with
#   RELEASE_REWRITE_WORK_WORDS=0).
NOTE_REWRITE_3 = (os.environ.get('RELEASE_REWRITE_WORK_WORDS', '1') == '1'
                  and os.environ.get('RELEASE_REWRITE_WORK_WORDS_3', '1') == '1')
# Write times in transcription_long.csv with two-digit minutes. Workbook time cells mix numbers and text, and numbers
#   lose trailing zeros (4.40 becomes 4.4, 7.00 becomes 7), so numeric dep_time/arr_time cells are written as
#   "h.mm" (text cells and the workbooks are unchanged). Stop if a value does not read back to the original number
#   or has 60 or more minutes. On by default. Previous behavior (numbers as is) = RELEASE_LONG_TIME_TWO_DIGITS=0.
LONG_TIME_TWO_DIGITS = os.environ.get('RELEASE_LONG_TIME_TWO_DIGITS', '1') == '1'
# The file-name table transcription/files.csv is not included (no file refers to the original names, and pages
#   repeats the file name). Previous behavior (included) = RELEASE_INCLUDE_FILES_CSV=1.
INCLUDE_FILES_CSV = os.environ.get('RELEASE_INCLUDE_FILES_CSV', '0') == '1'


def ascii_name(name):
    """近代デジタル交通網p1-2.xlsx -> p001-002.xlsx; …p100.xlsx -> p100.xlsx"""
    nums = [int(x) for x in re.findall(r'\d+', unicodedata.normalize('NFC', name).replace('.xlsx', ''))]
    if len(nums) == 1:
        return f'p{nums[0]:03d}.xlsx'
    if len(nums) == 2:
        return f'p{nums[0]:03d}-{nums[1]:03d}.xlsx'
    raise SystemExit(f'ファイル名から頁を読めない: {name}')


def _fixed_props(wb, when):
    p = wb.properties
    p.creator = 'Japan1925-GTFS'
    p.lastModifiedBy = ''
    p.created = when
    p.modified = when
    p.title = p.subject = p.description = p.keywords = p.category = None


def _clean_cells(ws, from_openpyxl_comment):
    """Remove pink fills and comments with work words. Return (fills removed, comments removed, comments kept)."""
    from openpyxl.styles import PatternFill
    n_pink = n_cdrop = n_ckeep = 0
    for row in ws.iter_rows():
        for cell in row:
            f = cell.fill
            if f is not None and f.fill_type == 'solid' and str(f.fgColor.rgb).upper().endswith(PINK):
                cell.fill = PatternFill(fill_type=None)
                n_pink += 1
            if cell.comment is not None:
                t = cell.comment.text or ''
                if DROP_ALL_COMMENTS or COMMENT_DROP.search(t) or not t.strip():
                    cell.comment = None
                    n_cdrop += 1
                else:
                    cell.comment = from_openpyxl_comment(t.strip(), '')
                    n_ckeep += 1
    return n_pink, n_cdrop, n_ckeep


def _plain_sheet(ws, header_row):
    """Remove all fills and freeze rows up to header_row (the stop_order header) and columns A-C.
    Return the number of fills removed."""
    from openpyxl.styles import PatternFill
    if ws.cell(header_row, 1).value != 'stop_order':
        raise SystemExit(f'見出しの行が {header_row} 行目でない: {ws.title}')
    n = 0
    for row in ws.iter_rows():
        for cell in row:
            f = cell.fill
            if f is not None and f.fill_type not in (None, 'none'):
                cell.fill = PatternFill(fill_type=None)
                n += 1
    ws.freeze_panes = f'D{header_row + 1}'
    return n


def _normalize_zip(path, when):
    """Set the time of every zip entry to when (openpyxl writes the save time, so bytes would differ for the same input)."""
    dt = (max(when.year, 1980), when.month, when.day, 0, 0, 0)
    with zipfile.ZipFile(path) as z:
        items = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    # openpyxl's save_workbook always overwrites properties.modified with the save time (even after _fixed_props),
    #   so rewrite dcterms:modified in docProps/core.xml to when here (same input gives the same bytes)
    stamp = when.strftime('%Y-%m-%dT%H:%M:%SZ').encode()
    items = [(n, re.sub(rb'(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)', rb'\g<1>' + stamp + rb'\g<2>', d)
              if n == 'docProps/core.xml' else d) for n, d in items]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in items:
            zi = zipfile.ZipInfo(name, date_time=dt)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
    with open(path, 'wb') as f:
        f.write(buf.getvalue())


def _workbook_text(path):
    """Return all text of a saved workbook (cells, shared strings, comments, document properties) for checking."""
    import html
    out = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith('.xml') or n.endswith('.vml'):
                out.append(html.unescape(z.read(n).decode('utf-8', 'replace')))
    return '\n'.join(out)


def _fmt(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _fmt_time(v, where=''):
    """A time cell. With LONG_TIME_TWO_DIGITS, numeric cells are written as "h.mm" (4.4 -> 4.40, 7 -> 7.00);
    text cells are left as they are."""
    if not LONG_TIME_TWO_DIGITS or isinstance(v, bool) or not isinstance(v, (int, float)):
        return _fmt(v)
    h = int(v)
    m = round((v - h) * 100)
    s = f'{h}.{m:02d}'
    if v < 0 or m >= 60 or abs(float(s) - v) > 1e-9:
        raise SystemExit(f'時刻のセルを分 2 桁で書けない: {where} {v!r}')
    return s


LONG_FIELDS = ['file', 'sheet', 'page', 'table_name', 'line_name', 'direction_raw', 'direction', 'column',
               'trip_label_header', 'trip_label', 'trip_num', 'trip_num_source', 'trip_num_note', 'note',
               'stop_order', 'stop_name', 'stop_type', 'dep_time', 'dep_pm', 'arr_time', 'arr_pm']


def _raw_path(name):
    for d in RAW_DIRS:
        for f in os.listdir(d):
            if unicodedata.normalize('NFC', f) == name:
                return os.path.join(d, f)
    raise SystemExit(f'番号を付ける前のワークブックが無い: {name}')


def build_transcription(out_dir, when):
    """Build transcription/. Return a dict of counts."""
    import openpyxl
    from openpyxl.comments import Comment
    T = os.path.join(out_dir, 'transcription')
    W2 = os.path.join(T, 'workbooks')
    W1 = os.path.join(T, 'workbooks_before_numbering')
    os.makedirs(W2)
    os.makedirs(W1)
    files = sorted((unicodedata.normalize('NFC', f), f) for f in os.listdir(TRIPNUM_DIR)
                   if f.endswith('.xlsx') and not f.startswith('~$'))
    stats = {'workbooks': 0, 'sheets': 0, 'note_cells': 0, 'note_kept': 0, 'note11_cells': 0, 'note11_kept': 0,
             'pink': 0, 'comment_drop': 0, 'comment_keep': 0, 'long_rows': 0, 'genpon': 0}
    unknown = []
    long_rows, file_rows, seen_ascii = [], [], {}
    for name, fn in files:
        an = ascii_name(name)
        if an in seen_ascii:
            raise SystemExit(f'英数字のファイル名が重なる: {an}（{seen_ascii[an]}・{name}）')
        seen_ascii[an] = name
        wb2 = openpyxl.load_workbook(os.path.join(TRIPNUM_DIR, fn))
        wb1 = openpyxl.load_workbook(_raw_path(name))
        if wb1.sheetnames != wb2.sheetnames:
            raise SystemExit(f'番号を付ける前のワークブックと番号つきのワークブックのシートが合わない: {name}')
        pages = [int(x) for x in re.findall(r'\d+', an)]
        if FILES_PAGES_SPREAD and unicodedata.normalize('NFC', name) in SPREAD_PAGES:
            pages = SPREAD_PAGES[unicodedata.normalize('NFC', name)]
        for ws2 in wb2.worksheets:
            ws1 = wb1[ws2.title]
            if ws2.cell(1, 1).value != 'table_id' or ws2.cell(12, 1).value != '確認メモ':
                raise SystemExit(f'番号つきのワークブックの行の形が違う: {name} {ws2.title}')
            stats['sheets'] += 1
            # --- rows 11 and 12 (form B)
            for col in range(2, ws2.max_column + 1):
                c11, c12 = ws2.cell(11, col), ws2.cell(12, col)
                if c11.value not in (None, ''):
                    stats['note11_cells'] += 1
                    nv = note11_b(c11.value)
                    stats['note11_kept'] += bool(nv)
                    c11.value = nv or None
                if c12.value not in (None, ''):
                    stats['note_cells'] += 1
                    stats['genpon'] += str(c12.value).count('【原本注記】')
                    try:
                        nv = note_b(c12.value, f'{name} {ws2.title} 列{col}')
                    except UnknownTag as e:
                        unknown.append(str(e))
                        nv = ''
                    stats['note_kept'] += bool(nv)
                    c12.value = nv or None
            for ws in (ws1, ws2):
                p, cd, ck = _clean_cells(ws, Comment)
                stats['pink'] += p
                stats['comment_drop'] += cd
                stats['comment_keep'] += ck
            if WORKBOOK_PLAIN:
                stats['plain_fill'] = stats.get('plain_fill', 0) + _plain_sheet(ws2, 13) + _plain_sheet(ws1, 10)
            # --- long table (with the reduced rows 11 and 12)
            head = {k: _fmt(ws2.cell(r, 2).value) for r, k in
                    ((1, 'sheet'), (2, 'page'), (3, 'table_name'), (4, 'line_name'), (5, 'direction_raw'), (6, 'direction'))}
            col_of_trip1 = {ws1.cell(7, c).value: c for c in range(4, ws1.max_column + 1) if ws1.cell(7, c).value is not None}
            data_rows = [r for r in range(14, ws2.max_row + 1)
                         if any(ws2.cell(r, c).value not in (None, '') for c in (1, 2))]
            for col in range(4, ws2.max_column + 1):
                tid = ws2.cell(7, col).value
                if tid is None:
                    continue
                if (col - 4) % 4:
                    raise SystemExit(f'列車の列が 4 列ごとでない: {name} {ws2.title} 列{col}')
                c1 = col_of_trip1.get(tid)
                note = ' '.join(_fmt(ws2.cell(12, c).value) for c in range(col, col + 4) if ws2.cell(12, c).value)
                base = dict(head, file=an, column=_fmt(tid),
                            trip_label_header=_fmt(ws2.cell(8, col).value),
                            trip_label=_fmt(ws1.cell(9, c1).value) if c1 else '',
                            trip_num=_fmt(ws2.cell(9, col).value), trip_num_source=_fmt(ws2.cell(10, col).value),
                            trip_num_note=_fmt(ws2.cell(11, col).value), note=note)
                n = 0
                for r in data_rows:
                    vals = [ws2.cell(r, c).value for c in range(col, col + 4)]
                    if all(v in (None, '') for v in vals):
                        continue
                    where = f'{an} {ws2.title} 行{r} 列{col}'
                    long_rows.append(dict(base, stop_order=_fmt(ws2.cell(r, 1).value), stop_name=_fmt(ws2.cell(r, 2).value),
                                          stop_type=_fmt(ws2.cell(r, 3).value), dep_time=_fmt_time(vals[0], where),
                                          dep_pm=_fmt(vals[1]), arr_time=_fmt_time(vals[2], where), arr_pm=_fmt(vals[3])))
                    n += 1
                if not n:                                  # columns without times (note-only, empty) keep their header and notes
                    long_rows.append(dict(base))
        for wb, d in ((wb2, W2), (wb1, W1)):
            _fixed_props(wb, when)
            path = os.path.join(d, an)
            wb.save(path)
            _normalize_zip(path, when)
        file_rows.append({'file': an, 'original_file_name': name,
                          'pages': '-'.join(str(p) for p in pages),
                          'sheets': len(wb2.sheetnames)})
        stats['workbooks'] += 1
    if unknown:
        raise SystemExit(f'確認メモに一覧に無い見出しがある（{len(unknown)}）＝KEEP_TAG か WORK_TAG に足す: {unknown[:10]}')
    # --- check: no internal record words left in the saved workbooks
    left = []
    for d in (W2, W1):
        for f in sorted(os.listdir(d)):
            t = _workbook_text(os.path.join(d, f))
            left += [f'{os.path.basename(d)}/{f}:{m.group(0)}' for m in MARKERS_ALL.finditer(t)]
            # author fields (document creator, last modifier, comment authors) must be empty or the fixed value
            # (body text is not checked, since there is a station named "大内")
            with zipfile.ZipFile(os.path.join(d, f)) as z:
                who = []
                if 'docProps/core.xml' in z.namelist():
                    core = z.read('docProps/core.xml').decode('utf-8')
                    who += re.findall(r'<dc:creator>([^<]*)</dc:creator>', core)
                    who += re.findall(r'<cp:lastModifiedBy>([^<]*)</cp:lastModifiedBy>', core)
                for n in z.namelist():
                    if re.search(r'comments\d*\.xml$', n):
                        who += re.findall(r'<author>([^<]*)</author>', z.read(n).decode('utf-8'))
            left += [f'{os.path.basename(d)}/{f}:書き手={w}' for w in who if w not in ('', 'Japan1925-GTFS')]
    if left:
        raise SystemExit(f'公開するワークブックに内部の記録の言葉が残っている（{len(left)}）: {left[:10]}')
    if NOTE_REWRITE_3:
        left3 = sorted({f'{r["sheet"]}:{m.group(0)}' for r in long_rows for m in WORK_WORDS_3.finditer(r.get('note') or '')})
        if left3:
            raise SystemExit(f'確認メモに作業の中だけの呼び名が残っている（{len(left3)}）＝derived_tables.WORK_REWRITES_3 に足す: {left3[:10]}')
    _write(os.path.join(T, 'transcription_long.csv'), LONG_FIELDS, long_rows)
    if INCLUDE_FILES_CSV:
        _write(os.path.join(T, 'files.csv'), ['file', 'original_file_name', 'pages', 'sheets'], file_rows)
    stats['long_rows'] = len(long_rows)
    return stats


# ---------------------------------------------------------------------------
# Integrated layer
# ---------------------------------------------------------------------------
def _read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def _write(path, fields, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fields})


def _scrub_rows(rows, fields):
    n = 0
    for r in rows:
        for k in fields:
            v = r.get(k) or ''
            s = rewrite_work_words(scrub_all(v), second=True)
            if s != v:
                r[k] = s
                n += 1
    return n


def build_integrated(out_dir, int_dir, id_map_csv=None):
    """Build integrated/. id_map_csv maps internal to published IDs (kind,internal_id,public_id); without it,
    internal IDs are kept."""
    I = os.path.join(out_dir, 'integrated')
    os.makedirs(I)
    pub = {}
    if id_map_csv and os.path.exists(id_map_csv):
        for r in _read(id_map_csv)[1]:
            pub[(r['kind'], r['internal_id'])] = r['public_id']
    _, sm = _read(os.path.join(int_dir, 'stops_master.csv'))
    _, tm = _read(os.path.join(int_dir, 'trips_master.csv'))
    stop_pub = {(r['stop_name'], r['line_name']): pub.get(('stop', r['stop_id']), r['stop_id'] if not pub else '') for r in sm}
    trip_pub = {r['gtfs_trip_key']: pub.get(('trip', r['gtfs_trip_id']), r['gtfs_trip_id'] if not pub else '') for r in tm}
    stats = {}
    # stops_master (coordinate columns removed)
    s_fields = ['stop_id', 'stop_name', 'line_name', 'canonical_name', 'stop_type']
    rows = [dict(r, stop_id=stop_pub[(r['stop_name'], r['line_name'])]) for r in sm]
    _write(os.path.join(I, 'stops_master.csv'), s_fields, rows)
    stats['stops'] = len(rows)
    stats['stops_without_public_id'] = sum(1 for r in rows if not r['stop_id'])
    # trips_master (internal IDs replaced by published IDs)
    t_fields = ['trip_id', 'gtfs_trip_key', 'route_id', 'line_name', 'direction', 'trip_num', 'first_stop', 'first_dep',
                'last_stop', 'last_arr']
    rows = [dict(r, trip_id=trip_pub[r['gtfs_trip_key']],
                 route_id=pub.get(('route', r['route_id']), r['route_id'] if not pub else '')) for r in tm]
    _write(os.path.join(I, 'trips_master.csv'), t_fields, rows)
    stats['trips'] = len(rows)
    stats['trips_without_public_id'] = sum(1 for r in rows if not r['trip_id'])
    # integrated_stop_times (published trip_id and stop_id added)
    f, rows = _read(os.path.join(int_dir, 'integrated_stop_times.csv'))
    for r in rows:
        r['trip_id'] = trip_pub.get(r['gtfs_trip_key'], '')
        r['stop_id'] = stop_pub.get((r['stop_name'], r['line_name']), '')
    _write(os.path.join(I, 'integrated_stop_times.csv'), ['trip_id', 'stop_id'] + f, rows)
    stats['stop_times'] = len(rows)
    stats['stop_times_without_trip_id'] = sum(1 for r in rows if not r['trip_id'])
    # processing logs (work words dropped from free text)
    for name in (('qa_log.csv',) if INCLUDE_QA_LOG else ()) + (('split_trips_report.csv',) if INCLUDE_SPLIT_REPORT else ()):
        f, rows = _read(os.path.join(int_dir, name))
        stats[f'{name}_scrubbed_fields'] = _scrub_rows(rows, f)
        _write(os.path.join(I, name), f, rows)
        stats[name] = len(rows)
    return stats


def feed_date(version):
    m = re.match(r'(\d{4})(\d{2})(\d{2})', version or '')
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else datetime(2026, 1, 1)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    out, int_dir = sys.argv[1], sys.argv[2]
    ver = sys.argv[3] if len(sys.argv) > 3 else ''
    for sub in ('transcription', 'integrated'):
        if os.path.exists(os.path.join(out, sub)):
            raise SystemExit(f'{out}/{sub} がもうある（消してから）')
    print('transcription:', build_transcription(out, feed_date(ver)))
    id_map = os.path.join(os.environ.get('RELEASE_ID_REGISTRY_DIR') or os.path.join(BASE_DIR, 'data', 'knowledge', 'public_release', 'id_registry'),
                          'internal_id_map.csv')   # same location as in stable_ids.py
    print('integrated:', build_integrated(out, int_dir, id_map))
