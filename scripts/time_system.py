#!/usr/bin/env python3
"""Look up the time system of the printed timetable ("日本内地及朝鮮時刻" Japan and Korea time /
"南滿洲及支那沿岸時刻" South Manchuria and China coast time / "哈爾賓時刻" Harbin time).

Tables that cross a border switch time systems partway (e.g. on p182 the top 3 rows are Korea time
and the rest Manchuria time; the last 2 rows of p183 are Harbin time). The footnote on p5, p6 and
p182-p185 states the offsets: South Manchuria/China coast time is 1 hour behind Japan/Korea time
and 26 minutes behind Harbin time.

Rules table: data/tables/time_system_rules.csv (built by hand from the footnotes and brackets of
the printed timetable). This module only reads it and returns
    lookup(sheet, line_name, stop_name, field) -> (time_system, offset_to_jst_min, rule_id)
offset_to_jst_min is the number of minutes to add to get Japan time (None = not stated in the
original, so not applied). With no matching rule, the default is Japan/Korea time and 0.

Priority: row (sheet + station + field) > line_stop (line + station) > sheet > line > line_prefix > default.
Station and line names are matched after NFC and old/new kanji normalization
(known_kanji_variants.normalize); the 〈region〉 tag on station names (added after integration) is removed.
"""
import csv
import os
import re
import unicodedata

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_CSV = os.environ.get('TIME_SYSTEM_RULES_PATH') or os.path.join(
    BASE_DIR, 'data', 'tables', 'time_system_rules.csv')

DEFAULT_SYSTEM = '日本内地及朝鮮時刻'
DEFAULT_OFFSET = 0

try:
    from known_kanji_variants import normalize as _kv_normalize
except Exception:  # pragma: no cover
    import sys
    sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
    from known_kanji_variants import normalize as _kv_normalize


_TAG_RE = re.compile(r'〈[^〉]*〉')   # strip the 〈region〉 tag added by disambiguate_stations (e.g. 安東〈朝鮮〉) before lookup


def _norm(s):
    if s is None:
        return ''
    s = unicodedata.normalize('NFC', str(s)).strip()
    s = _TAG_RE.sub('', s)
    return _kv_normalize(s, prefer_new=True)


class TimeSystemRules:
    def __init__(self, path=RULES_CSV):
        self.path = path
        self.rows = []
        self.by_row = {}          # (sheet, stop, field) -> rule
        self.by_line_stop = {}    # (line, stop, field) -> rule
        self.by_sheet = {}        # sheet -> rule
        self.by_line = {}         # line -> rule
        self.by_prefix = []       # [(prefix, rule)]
        if os.path.exists(path):
            with open(path, encoding='utf-8-sig', newline='') as f:
                for r in csv.DictReader(f):
                    self._add(r)

    def _add(self, r):
        r = dict(r)
        off = (r.get('offset_to_jst_min') or '').strip()
        r['offset'] = int(off) if off not in ('', None) else None
        r['field'] = (r.get('field') or 'both').strip() or 'both'
        scope = (r.get('scope') or '').strip()
        sheet = unicodedata.normalize('NFC', (r.get('sheet') or '').strip())
        line = _norm(r.get('line_name'))
        stop = _norm(r.get('stop_name'))
        self.rows.append(r)
        if scope == 'row':
            for fld in (('arr', 'dep') if r['field'] == 'both' else (r['field'],)):
                self.by_row[(sheet, stop, fld)] = r
        elif scope == 'line_stop':
            for fld in (('arr', 'dep') if r['field'] == 'both' else (r['field'],)):
                self.by_line_stop[(line, stop, fld)] = r
        elif scope == 'sheet':
            self.by_sheet[sheet] = r
        elif scope == 'line':
            self.by_line[line] = r
        elif scope == 'line_prefix':
            self.by_prefix.append((line, r))
        else:
            raise ValueError(f'time_system_rules.csv: 未知の scope {scope!r}（{r.get("rule_id")}）')

    def lookup(self, sheet, line_name, stop_name, field):
        """field is 'arr' or 'dep'. Returns (time_system, offset_to_jst_min|None, rule_id|'')."""
        sheet = unicodedata.normalize('NFC', (sheet or '').strip())
        line = _norm(line_name)
        stop = _norm(stop_name)
        r = (self.by_row.get((sheet, stop, field))
             or self.by_line_stop.get((line, stop, field))
             or self.by_sheet.get(sheet)
             or self.by_line.get(line))
        if r is None:
            for pfx, rr in self.by_prefix:
                if pfx and line.startswith(pfx):
                    r = rr
                    break
        if r is None:
            return DEFAULT_SYSTEM, DEFAULT_OFFSET, ''
        return r['time_system'], r['offset'], r.get('rule_id', '')


_RULES = None


def rules():
    global _RULES
    if _RULES is None:
        _RULES = TimeSystemRules()
    return _RULES


def lookup(sheet, line_name, stop_name, field):
    return rules().lookup(sheet, line_name, stop_name, field)


if __name__ == '__main__':
    import sys
    rs = rules()
    print(f'{rs.path}: {len(rs.rows)} 規則（row {len(rs.by_row)}・line_stop {len(rs.by_line_stop)}・'
          f'sheet {len(rs.by_sheet)}・line {len(rs.by_line)}・prefix {len(rs.by_prefix)}）')
    for probe in [('p0182_tb004-1', '滿鐵安奉線', '安東', 'arr'), ('p0182_tb004-1', '滿鐵安奉線', '安東', 'dep'),
                  ('p0182_tb004-1', '滿鐵安奉線', '哈爾賓', 'arr'), ('p0005_tb001-9', '朝鮮及満洲線', '奉天', 'dep'),
                  ('p0184_tb003-1', '支那國有鐵道京奉線', '北京', 'dep'), ('p0179_tb001-1-1', '臺灣總督府鐵道縦貫線及臺中線', '基隆', 'dep'),
                  ('p0087_tb002-1-1', '安濃鐵道線', '安東', 'dep'), ('p0192_tb001-1-1', '大阪商船會社定期航路', '大連', 'arr')]:
        print(probe, '->', rs.lookup(*probe))
    sys.exit(0)
