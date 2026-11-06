"""
extract_stop_times.py

Extract stop_times in long format from the workbooks (2_timetable_with_tripnum_xlsx_fixed/)
and write an intermediate Excel table.

Output: 3_stop_times_intermediate/{file name}.xlsx
  - sheet "stop_times":    all stop records (midnight crossing corrected; 1 row = 1 trip x 1 station)
  - sheet "trip_summary":  per-trip summary (reference for GTFS trip design)
  - sheet "issues":        records still needing review after correction (unexpected reversals etc.)

Midnight crossing correction:
  - Process records of the same sheet and trip_id in stop_order.
  - Within a station, process arr_time before dep_time.
  - If a time goes back 30 minutes or more from the previous one, add 24 hours (1440 minutes).
  - Keep that offset for all later times.
  - Times after midnight thus become 24:xx, 25:xx, 32:xx etc. (GTFS style).

stop_order reversal (inbound private railways):
  - Some inbound private-railway sheets list stations in the same geographic order as
    outbound, so times decrease along stop_order.
  - Before the midnight correction, detect trips whose times decrease overall and
    reverse their stop_order (1,2,...,N -> N,...,2,1).
  - Decreasing times also occur on night trains crossing midnight, so first decide by
    發 (departure) / 著 (arrival) markers:
      first = 發 / last = 著 -> already in travel order; do not reverse (midnight correction handles it)
      first = 著 / last = 發 -> reversed for sure; reverse (also catches night trains whose times look increasing)
      undecided (summary bands with only 著 or only 發, etc.) -> decide by the decreasing trend of times
"""

import openpyxl
import os
import sys
import re
import unicodedata
import csv
from collections import defaultdict


# ---------------------------------------------------------------------------
# Time conversion utilities
# ---------------------------------------------------------------------------

_KANJI_NUM = {
    '初': 1, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '1': 1, '2': 2, '3': 3, '4': 4, '5': 5,
    '6': 6, '7': 7, '8': 8, '9': 9,
}


def _parse_day_offset(suffix):
    """Return the day offset in minutes from a suffix such as `/初日`, `/二日目`, `/四日目`.
    Day 1 = 0, day 2 = 1440, day 3 = 2880, ... Returns 0 if it cannot be parsed."""
    if not suffix:
        return 0
    # `初日`, `二日目`, `三日目`, ...
    m = re.search(r'([初一二三四五六七八九十1-9])\s*日', suffix)
    if not m:
        return 0
    n = _KANJI_NUM.get(m.group(1), 1)
    return (n - 1) * 1440


# --- Weekday suffixes (`/水曜日` `/金曜日`) = EXTRACT_WEEKDAY_OFFSET -----------
# For weekly long-distance sailings the original sometimes prints the weekday instead of the day
# number (p6 connection table, 敦賀-浦鹽斯德: `土曜日 2.00 / 月曜日 10.00`, `水曜日 正午 / 金曜日 6.00`).
# `_parse_day_offset` only reads `([初一二三四五六七八九十1-9])日`, so weekdays are read here.
_WEEKDAY_IDX = {'日': 0, '月': 1, '火': 2, '水': 3, '木': 4, '金': 5, '土': 6}
_WEEKDAY_RE = re.compile(r'^\s*([日月火水木金土])\s*曜日?\s*$')


def _weekday_index(time_val):
    """Return the weekday index (Sun=0 to Sat=6) if the cell is `<time>/<weekday>`, else None."""
    if not isinstance(time_val, str) or '/' not in time_val:
        return None
    m = _WEEKDAY_RE.match(time_val.split('/', 1)[1])
    return _WEEKDAY_IDX[m.group(1)] if m else None


def pm_flag(pm):
    """pm cell value -> True (p.m.) / False (a.m.) / None (cannot interpret).

    Do not test with `if pm:`. pm should be numeric 0/1, but some cells hold the
    string '0', and a non-empty string is truthy, which would turn a.m. into p.m.
    Full-width '０' is also a.m. Values other than 0/1 return None so the caller
    can report them (never silently p.m.).
    """
    if pm is None:
        return False
    if isinstance(pm, bool):
        return pm
    if isinstance(pm, (int, float)):
        if float(pm) == 0:
            return False
        if float(pm) == 1:
            return True
        return None
    s = unicodedata.normalize('NFKC', str(pm)).strip()
    if s == '':
        return False
    if s in ('0', '0.0'):
        return False
    if s in ('1', '1.0'):
        return True
    return None


def to_hhmm(time_val, pm):
    """
    H.MM + pm flag (0 = a.m., 1 = p.m.) -> HH:MM string (hours 0-23).
    12-hour rules:
      PM=1: h=12 -> unchanged (noon), h!=12 -> h+12
      PM=0: h=12 -> 0 (midnight),     h!=12 -> unchanged

    If the value has a "/N日目" (day N) suffix such as `12.00/初日`, return a
    GTFS-style time with (N-1) x 1440 minutes added (e.g. 36:00).
    """
    if time_val is None:
        return None
    day_offset = 0
    if isinstance(time_val, str):
        s = time_val.strip().lstrip('*')
        # non-time markers such as `...` (not served / no time) and `↓` (passes) -> None
        if s in ("", "...", "…", "↓", "‖", "║", "ノ"):
            return None
        # `12.00/初日` form: split the time from the day suffix
        if '/' in s:
            time_part, day_part = s.split('/', 1)
            day_offset = _parse_day_offset(day_part)
            s = time_part.strip()
        m = re.match(r"(\d+)\.?(\d*)", s)
        if not m:
            return f"ERR:{time_val}"
        h, mins_str = int(m.group(1)), m.group(2)
        minute = int(mins_str) if mins_str else 0
    else:
        h = int(time_val)
        minute = round((time_val - h) * 100)
    is_pm = pm_flag(pm)
    if is_pm is None:
        return f"ERR:pm={pm!r}({time_val})"
    if is_pm:
        if h != 12:
            h += 12
    else:
        if h == 12:
            h = 0
    if day_offset:
        h += day_offset // 60
    return f"{h:02d}:{minute:02d}"


def hhmm_to_minutes(hhmm):
    """HH:MM (24:xx etc. allowed) -> minutes (int). None -> None."""
    if hhmm is None or (isinstance(hhmm, str) and hhmm.startswith("ERR")):
        return None
    parts = hhmm.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def minutes_to_hhmm(total_min):
    """Minutes (may exceed 24 hours) -> HH:MM string (GTFS style: 24:xx, 25:xx, ...)."""
    h = total_min // 60
    m = total_min % 60
    return f"{h:02d}:{m:02d}"


# ---------------------------------------------------------------------------
# Midnight crossing correction
# ---------------------------------------------------------------------------

def correct_overnight(records):
    """
    Apply the midnight crossing correction to the records of one trip (in stop_order).

    At each station, check arr_time then dep_time; if a time goes back 30 minutes or
    more from the maximum so far, add 1440 minutes and keep that offset for all later times.

    Modifies records in place and returns the list.
    """
    recs = sorted(records, key=lambda r: r["stop_order"])

    offset   = 0     # current offset (minutes)
    prev_max = None  # maximum time so far (minutes, including offset)

    for r in recs:
        for key in ("arr_time", "dep_time"):   # arr before dep
            t = r[key]
            if t is None or (isinstance(t, str) and t.startswith("ERR")):
                continue

            t_min = hhmm_to_minutes(t) + offset

            if prev_max is not None and t_min < prev_max - 30:
                # crossed midnight -> add 1440 minutes to the offset
                offset += 1440
                t_min  += 1440

            r[key] = minutes_to_hhmm(t_min)

            if prev_max is None or t_min > prev_max:
                prev_max = t_min

    return recs


# ---------------------------------------------------------------------------
# stop_order reversal detection (inbound private railways)
# ---------------------------------------------------------------------------

# Do not use mod 1440 for multi-day trips.
# ------------------------------------------------------------------
# Times with a day suffix (`12.00/初日`, `1.00/三日目`) are already absolute after to_hhmm()
# (e.g. 61:00). Taking adjacent differences mod 1440 would make "the next port 23 hours later"
# look like "1 hour back" and reverse the station order, so count raw differences instead.
# Default ON. Previous behavior = EXTRACT_MULTIDAY_ORDER=0.
MULTIDAY_ORDER = os.environ.get("EXTRACT_MULTIDAY_ORDER", "1") != "0"

# A single row of another line's station inside the main line's station column (e.g. 鹽竈 of
#   鹽竈線 in the summary block of 東北本線 on p99) is marked `branch:<line name>` in stop_type
#   in the transcription. Remove marked rows from the main-line trip and emit them, paired with
#   the adjacent main-line station (junction), as a separate band trip of that line
#   (line_name = that line, stop_type = station). An arrival-only row (terminating) pairs with
#   the previous station (its 發 if any, else its 著); a departure-only row (originating) pairs
#   with the next station (its 著 if any, else its 發); roles are not swapped. A row with both
#   pairs with both neighbors. source_sheet, trip_id and trip_num stay as on the main line.
#   Default ON. Previous behavior (marked rows stay as main-line stops) = EXTRACT_BRANCH_SPLIT=0.
BRANCH_SPLIT = os.environ.get("EXTRACT_BRANCH_SPLIT", "1") != "0"

# Convert cross-border time systems to Japan time. Tables crossing a border switch the time system
#   they are printed in (footnote "時差 南滿洲及支那沿岸時刻ハ日本内地及朝鮮時刻ヨリ 1 時間遲ク 哈爾賓時刻ヨリ 26 分遲シ").
#   Before the midnight correction, add to each cell the minutes to Japan time looked up in the rules
#   table (data/tables/time_system_rules.csv, scripts/time_system.py): South Manchuria/China coast +60,
#   Harbin +34. Cells whose rule is "not stated" (Taiwan, Russian territory, overseas ports) are unchanged.
#   When ON, write _extract_flags.json to the output directory (read for the derived table stop_time_system.csv).
#   Default ON. Previous behavior (keep the printed time system) = EXTRACT_TZ_TO_JST=0.
TZ_TO_JST = os.environ.get("EXTRACT_TZ_TO_JST", "1") != "0"

# Convert weekdays such as `/水曜日` `/金曜日` to days. Within one column of one sheet, follow the
#   weekdays in stop_order, accumulate (current - previous) mod 7 days and add 1440 minutes x days
#   (Sat->Mon = +2 days, Wed->Fri = +2 days). Cells without a weekday are untouched.
#   Default ON. Previous behavior (weekdays ignored, day 0) = EXTRACT_WEEKDAY_OFFSET=0.
WEEKDAY_OFFSET = os.environ.get("EXTRACT_WEEKDAY_OFFSET", "1") != "0"
EXTRACT_FLAGS_FILE = "_extract_flags.json"

# Renumbering table: for a train whose number changes partway down one printed column, keep the
#   transcription as printed and emit the stops from the given stop onward under another number
#   (e.g. p17 東海道本線 上リ column 25: 688 up to 米原 著 2.22, 88 from 米原 發 2.28 onward).
#   Table = data/tables/renumbering.csv (path: EXTRACT_RENUMBER_TABLE_PATH).
#   For each row, sort the stops of (source_sheet, trip_id) whose trip_num is "元の番号" (old number)
#   by stop_order and give "新しい番号" (new number) to the first stop with a time in "起点の欄"
#   (著/發) at "起点の駅" (start station) and all later stops (empty start station = all stops).
#   If line, direction or old number do not match, the start is missing, or the start stop also has
#   a time in the other field, leave it and WARN.
#   Applied after the midnight correction and branch splitting (times and stations unchanged; if
#   "新しい線名" (new line name) is set, the line name is changed too).
#   When ON, add a flag to _extract_flags.json (split_combined_trips.py reads it to look up the
#   arrival/departure merge table under the new number too).
#   Default ON. Previous behavior (do nothing) = EXTRACT_RENUMBER_TABLE=0.
RENUMBER_TABLE = os.environ.get("EXTRACT_RENUMBER_TABLE", "1") != "0"
RENUMBER_TABLE_PATH = os.environ.get("EXTRACT_RENUMBER_TABLE_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tables", "renumbering.csv")
_RENUMBER_ROWS = None
_RENUMBER_SEEN = set()   # 改番ID (renumbering IDs) whose sheet was found in this run


def load_renumber_table():
    """Read the renumbering table (once). Returns a list of rows (with the table's headers)."""
    global _RENUMBER_ROWS
    if _RENUMBER_ROWS is None:
        with open(RENUMBER_TABLE_PATH, encoding="utf-8-sig", newline="") as f:
            _RENUMBER_ROWS = [r for r in csv.DictReader(f) if (r.get("改番ID") or "").strip()]
    return _RENUMBER_ROWS


def _num_str(v):
    """String for comparing number cells (688.0 -> "688")."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return "" if v is None else str(v).strip()


def apply_renumber_table(records, rules):
    """Apply the renumbering rules to records (rewrites trip_num in place).
    Returns [(renumbering ID, number of stops renumbered, reason if not applied)].
    Rules whose sheet is not in this file are not returned."""
    groups = defaultdict(list)
    for r in records:
        groups[(r["source_sheet"], str(r["trip_id"]))].append(r)
    sheets = {k[0] for k in groups}
    out = []
    for rule in rules:
        rid = rule["改番ID"].strip()
        sheet = rule["source_sheet"].strip()
        if sheet not in sheets:
            continue
        _RENUMBER_SEEN.add(rid)
        tid = str(int(float(rule["trip_id"])))
        old = rule["元の番号"].strip()
        new = rule["新しい番号"].strip()
        recs = sorted(groups.get((sheet, tid), []), key=lambda x: x["stop_order"])
        base = [r for r in recs if _num_str(r["trip_num"]) == old]
        if not base:
            out.append((rid, 0, f"{sheet} 列{tid} に元の番号 {old} の停車が無い"))
            continue
        want_line = (rule.get("line_name") or "").strip()
        want_dir = (rule.get("direction") or "").strip()
        # skip stops split out to another line's band (only the line differs): use stops matching line and direction
        cand = [r for r in base if (not want_line or str(r["line_name"]).strip() == want_line)
                and (not want_dir or str(r["direction"]).strip() == want_dir)]
        if not cand:
            seen = "／".join(sorted({f"{r['line_name']}・{r['direction']}" for r in base}))
            out.append((rid, 0, f"線名・方向が表と違う（この列は {seen}）"))
            continue
        stop = (rule.get("起点の駅") or "").strip()
        start = 0
        if stop:
            field = (rule.get("起点の欄") or "").strip()
            if field not in ("著", "發"):
                out.append((rid, 0, f"起点の欄が 著／發 でない（{field!r}）"))
                continue
            key, other = ("dep_time", "arr_time") if field == "發" else ("arr_time", "dep_time")
            hits = [i for i, r in enumerate(cand) if str(r["stop_name"]).strip() == stop and r[key]]
            if not hits:
                out.append((rid, 0, f"起点 {stop}（{field}）の停車が無い"))
                continue
            start = hits[0]
            if cand[start][other]:
                out.append((rid, 0, f"起点 {stop} の停車が{'著' if field == '發' else '發'}も持つ"
                                    "（行を分けないと付け替えられない）"))
                continue
        # "新しい線名" (optional column) = change the line name along with the number, where one printed
        #   column turns into another railway's train (p183: 長春-哈爾賓 in the 滿鐵 column is a 東支鐵道南線
        #   train, numbered in the header of p185). Empty = line name unchanged.
        new_line = (rule.get("新しい線名") or "").strip()
        for r in cand[start:]:
            r["trip_num"] = int(new) if isinstance(r["trip_num"], (int, float)) and new.isdigit() else new
            if new_line:
                r["line_name"] = new_line
        out.append((rid, len(cand) - start, ""))
    return out


def apply_weekday_offsets(raw_records):
    """Add elapsed days per sheet x column (trip_id) to cells with a `/<weekday>` suffix
    (called only when WEEKDAY_OFFSET is ON). Returns the number of cells changed.

    Follow only the stops with a weekday in stop_order and accumulate
    `(current - previous) mod 7` days; the first weekday is day 0.
    This does not work if stop_order is not the travel order (an up table whose station
    column is in down order); in the current corpus only the 2 sheets on p6 use weekdays,
    and both are in travel order.
    """
    groups = defaultdict(list)
    for r in raw_records:
        if "_dep_wd" in r or "_arr_wd" in r:
            groups[(r["source_sheet"], r["trip_id"])].append(r)
    n = 0
    for _key, rows in groups.items():
        rows.sort(key=lambda r: (r["stop_order"], 0))
        day = 0
        prev_wd = None
        for r in rows:
            # the original never has weekdays on both 著 and 發 of one row, but check both in order
            for wd_key, t_key in (("_arr_wd", "arr_time"), ("_dep_wd", "dep_time")):
                wd = r.get(wd_key)
                if wd is None:
                    continue
                if prev_wd is not None:
                    day += (wd - prev_wd) % 7
                prev_wd = wd
                t = r.get(t_key)
                if day and t and not (isinstance(t, str) and t.startswith("ERR")):
                    r[t_key] = minutes_to_hhmm(hhmm_to_minutes(t) + day * 1440)
                    n += 1
    for r in raw_records:
        r.pop("_dep_wd", None)
        r.pop("_arr_wd", None)
    return n


def apply_time_system_offsets(raw_records):
    """Add the rules table's offset_to_jst_min to dep_time/arr_time (called only when TZ_TO_JST is ON).
    Returns (number of cells changed, {time system: number of cells})."""
    import time_system as _ts
    from collections import Counter
    n = 0
    by_sys = Counter()
    for r in raw_records:
        for fld, key in (("dep", "dep_time"), ("arr", "arr_time")):
            t = r.get(key)
            if t is None or (isinstance(t, str) and t.startswith("ERR")):
                continue
            system, off, _rule = _ts.lookup(r["source_sheet"], r["line_name"], r["stop_name"], fld)
            if not off:
                continue
            r[key] = minutes_to_hhmm(hhmm_to_minutes(t) + off)
            n += 1
            by_sys[system] += 1
    return n, dict(by_sys)


def branch_line_of(stop_type):
    """Return the line name if stop_type is `branch:<line name>`, else None."""
    if isinstance(stop_type, str):
        t = stop_type.strip()
        if t.startswith("branch:"):
            name = t[len("branch:"):].strip()
            return name or None
    return None


def split_branch_rows(records):
    """Split stops marked `branch:<line name>` out of the main-line trip into a band of that line.
    Returns (new records, number of bands split). Called after the midnight correction (times are HH:MM).
    Trips without marks keep their order and content (so ON/OFF give the same output on an unmarked corpus)."""
    groups = defaultdict(list)
    for r in records:
        groups[(r["source_sheet"], r["trip_id"])].append(r)
    split_keys = {k for k, recs in groups.items() if any(branch_line_of(r["stop_type"]) for r in recs)}
    if not split_keys:
        return records, 0

    def process(recs):
        recs_s = sorted(recs, key=lambda x: x["stop_order"])
        main = [r for r in recs_s if not branch_line_of(r["stop_type"])]
        runs = []   # consecutive marks of the same line form one band
        for r in recs_s:
            bl = branch_line_of(r["stop_type"])
            if bl is None:
                continue
            if runs and runs[-1][0] == bl and \
                    not any(runs[-1][1][-1]["stop_order"] < m["stop_order"] < r["stop_order"] for m in main):
                runs[-1][1].append(r)
            else:
                runs.append((bl, [r]))
        out = list(main)
        for bl, run in runs:
            first, last = run[0], run[-1]
            prev_main = [m for m in main if m["stop_order"] < first["stop_order"]]
            next_main = [m for m in main if m["stop_order"] > last["stop_order"]]
            neither = first["dep_time"] is None and last["arr_time"] is None
            attach_prev = last["arr_time"] is not None or neither
            attach_next = first["dep_time"] is not None or neither
            if attach_prev and prev_main:
                # junction (previous main-line station): its 發 only if present, else its 著 as is (roles not swapped)
                pm = dict(prev_main[-1])
                if pm["dep_time"] is not None:
                    pm["arr_time"] = None
                pm["line_name"] = bl
                out.append(pm)
            for r in run:
                br = dict(r)
                br["line_name"] = bl
                br["stop_type"] = "station"
                out.append(br)
            if attach_next and next_main:
                # junction (next main-line station): its 著 only if present, else its 發 as is
                nm = dict(next_main[0])
                if nm["arr_time"] is not None:
                    nm["dep_time"] = None
                nm["line_name"] = bl
                out.append(nm)
        return out, len(runs)

    out, n_bands, done = [], 0, set()
    for r in records:                       # keep the original order (unmarked trips unchanged)
        k = (r["source_sheet"], r["trip_id"])
        if k not in split_keys:
            out.append(r)
        elif k not in done:
            done.add(k)
            recs2, nb = process(groups[k])
            out.extend(recs2)
            n_bands += nb
    return out, n_bands


def is_reverse_ordered(records):
    """
    Decide whether a trip's times decrease overall along stop_order.

    Compare the number of increases and decreases over adjacent time pairs in stop_order;
    True if decreases exceed twice the increases.
    """
    sorted_recs = sorted(records, key=lambda r: r["stop_order"])
    times = []
    for r in sorted_recs:
        for key in ("arr_time", "dep_time"):
            t_min = hhmm_to_minutes(r[key])
            if t_min is not None:
                times.append(t_min)

    if len(times) < 2:
        return False

    # Multi-day trips (times of 1440 minutes or more from day suffixes) use absolute times,
    #   so count raw differences without mod.
    if MULTIDAY_ORDER and any(t >= 1440 for t in times):
        inc = sum(1 for i in range(1, len(times)) if times[i] > times[i - 1])
        dec = sum(1 for i in range(1, len(times)) if times[i] < times[i - 1])
        return dec > inc * 2

    increasing = 0
    decreasing = 0
    for i in range(1, len(times)):
        # Interpret each adjacent difference as the smallest displacement mod 1440.
        # E.g. 長野 23.50p 發 -> 篠ノ井 12.07a 發 (a night-train fragment) looks like -1423 minutes
        # as a raw difference but is +17 minutes across midnight. Counting it as a decrease would
        # wrongly reverse 2-station night fragments that 發/著 cannot decide.
        # Conversely, a night fragment listed destination-first (23:50 below 0:10) reads as
        # -20 minutes and is caught for reversal.
        # Pairs 9-15 hours apart (540-900 minutes) cannot be called forward or backward
        # (e.g. 京奉線 104 奉天 7.05a -> 山海關 7.50p is a real 12h45m forward run), so they
        # do not vote; the other pairs decide by majority.
        d = (times[i] - times[i - 1]) % 1440
        if 0 < d < 540:
            increasing += 1
        elif d > 900:
            decreasing += 1
        # 540 <= d <= 900 and d == 0 are neutral (no vote)

    return decreasing > increasing * 2


def head_tail_role(records):
    """Return whether the first and last rows are 發 (departure) or 著 (arrival) ("?" if undecided).

    The origin has only 發 and the terminus only 著, so (first, last) == ("發", "著") means
    stop_order is already the travel order: do not reverse even if times decrease (night train).
    ("著", "發") means reversed order (inbound private railways, etc.): reversing is correct.
    """
    srt = sorted(records, key=lambda r: r["stop_order"])

    def role(r):
        if r["dep_time"] and not r["arr_time"]:
            return "發"
        if r["arr_time"] and not r["dep_time"]:
            return "著"
        return "?"

    return role(srt[0]), role(srt[-1])


def reverse_stop_order(records):
    """
    Reverse the stop_order of the records (N,...,2,1 -> 1,2,...,N).
    """
    orders = sorted(set(r["stop_order"] for r in records))
    old_to_new = {old: new for old, new in zip(orders, reversed(orders))}
    for r in records:
        r["stop_order"] = old_to_new[r["stop_order"]]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def extract_file(input_path, output_path):
    fname = os.path.basename(input_path)
    print(f"抽出中: {fname}")
    wb_in = openpyxl.load_workbook(input_path)

    raw_records = []   # raw stop records

    for shname in wb_in.sheetnames:
        ws = wb_in[shname]
        source_file   = fname
        source_sheet  = shname.strip()
        table_name    = ws.cell(3, 2).value
        line_name     = ws.cell(4, 2).value
        direction_raw = ws.cell(5, 2).value
        direction     = ws.cell(6, 2).value

        tid_row  = [ws.cell(7,  c).value for c in range(1, ws.max_column + 1)]
        tnum_row = [ws.cell(9,  c).value for c in range(1, ws.max_column + 1)]
        tsrc_row = [ws.cell(10, c).value for c in range(1, ws.max_column + 1)]

        trip_cols = {}
        for ci, tid in enumerate(tid_row):
            if isinstance(tid, (int, float)):
                trip_cols[ci] = {
                    "trip_id":         int(tid),
                    "trip_num":        tnum_row[ci],
                    "trip_num_source": tsrc_row[ci],
                }

        for row in ws.iter_rows(min_row=13, values_only=True):
            stop_order = row[0]
            stop_name  = row[1]
            stop_type  = row[2] if len(row) > 2 else None
            if stop_order is None:
                continue
            # In workbooks with a review-note row, row 13 is the stop_order header.
            # Skip non-numeric stop_order (headers etc.); convert numeric strings to int.
            if isinstance(stop_order, str):
                _so = stop_order.strip()
                if not _so.isdigit():
                    continue
                stop_order = int(_so)
            elif not isinstance(stop_order, (int, float)):
                continue

            # `＜station＞` or `<station>` marks a via point (has a time column but no stop).
            # Not a GTFS stop, so skip it.
            if isinstance(stop_name, str):
                s = stop_name.strip()
                if (s.startswith('＜') and s.endswith('＞')) or \
                   (s.startswith('<') and s.endswith('>')):
                    continue

            for ci, tinfo in trip_cols.items():
                dep_val = row[ci]     if ci     < len(row) else None
                dep_pm  = row[ci + 1] if ci + 1 < len(row) else None
                arr_val = row[ci + 2] if ci + 2 < len(row) else None
                arr_pm  = row[ci + 3] if ci + 3 < len(row) else None

                if dep_val is None and arr_val is None:
                    continue

                rec = {
                    "source_file":      source_file,
                    "source_sheet":     source_sheet,
                    "table_name":       table_name,
                    "line_name":        line_name,
                    "direction":        direction,
                    "direction_raw":    direction_raw,
                    "trip_id":          tinfo["trip_id"],
                    "trip_num":         tinfo["trip_num"],
                    "trip_num_source":  tinfo["trip_num_source"],
                    "stop_order":       stop_order,
                    "stop_name":        stop_name,
                    "stop_type":        stop_type,
                    "dep_time":         to_hhmm(dep_val, dep_pm),
                    "arr_time":         to_hhmm(arr_val, arr_pm),
                }
                if WEEKDAY_OFFSET:
                    _dwd, _awd = _weekday_index(dep_val), _weekday_index(arr_val)
                    if _dwd is not None:
                        rec["_dep_wd"] = _dwd
                    if _awd is not None:
                        rec["_arr_wd"] = _awd
                raw_records.append(rec)

    # --- Convert weekday suffixes to days (only when EXTRACT_WEEKDAY_OFFSET=1) ---
    # Added before the midnight correction (same input as if the original printed "N日目").
    weekday_count = 0
    if WEEKDAY_OFFSET:
        weekday_count = apply_weekday_offsets(raw_records)

    # --- Cross-border time systems (only when EXTRACT_TZ_TO_JST=1) ---
    # Added before reversal detection and the midnight correction (same input as if printed in Japan time).
    tz_count = 0
    if TZ_TO_JST:
        tz_count, tz_by_sys = apply_time_system_offsets(raw_records)

    # --- stop_order reversal detection (inbound private railways) ---
    # For each (source_sheet, trip_id), detect a decreasing trend of times and reverse stop_order.
    # Night trains crossing midnight also show decreasing times, so decide by 發/著 first.
    reverse_groups = defaultdict(list)
    for r in raw_records:
        reverse_groups[(r["source_sheet"], r["trip_id"])].append(r)

    reverse_count = 0
    for key, recs in reverse_groups.items():
        head, tail = head_tail_role(recs)
        if (head, tail) == ("發", "著"):
            # first 發, last 著 = already in travel order; night trains are left to the midnight correction
            continue
        if (head, tail) == ("著", "發"):
            # first 著, last 發 = reversed for sure; also catches night trains whose times look increasing
            reverse_stop_order(recs)
            reverse_count += 1
            continue
        # trips that 發/著 cannot decide (summary bands with only 著 or only 發, etc.): decide by time trend
        if is_reverse_ordered(recs):
            reverse_stop_order(recs)
            reverse_count += 1

    # --- Midnight crossing correction ---
    # Group by (source_sheet, trip_id) and correct.
    # Different trip_ids with the same trip_num on one sheet form one group only if their
    # stop_orders do not overlap (a train split across columns).
    trip_groups_raw = defaultdict(list)

    # decide whether trip_ids with the same sheet and trip_num can be grouped
    from collections import defaultdict as _dd
    sheet_num_ids = _dd(list)  # (sheet, trip_num) -> [(trip_id, stop_orders)]
    for r in raw_records:
        sheet_num_ids[(r["source_sheet"], r["trip_num"])].append(r["trip_id"])
    # check stop_order overlap per trip_num
    mergeable_ids = {}  # trip_id -> group_key
    for (sheet, tnum), ids_list in sheet_num_ids.items():
        unique_ids = sorted(set(ids_list))
        if len(unique_ids) <= 1 or tnum is None:
            continue
        # collect the stop_orders of each trip_id
        id_orders = _dd(set)
        for r in raw_records:
            if r["source_sheet"] == sheet and r["trip_id"] in unique_ids:
                id_orders[r["trip_id"]].add(r["stop_order"])
        # mergeable only if stop_orders do not overlap
        all_orders = []
        overlap = False
        for tid in unique_ids:
            for prev_orders in all_orders:
                if id_orders[tid] & prev_orders:
                    overlap = True
                    break
            if overlap:
                break
            all_orders.append(id_orders[tid])
        if not overlap:
            for tid in unique_ids:
                mergeable_ids[(sheet, tid)] = (sheet, tnum)

    for r in raw_records:
        key = mergeable_ids.get((r["source_sheet"], r["trip_id"]),
                                (r["source_sheet"], r["trip_id"]))
        trip_groups_raw[key].append(r)

    overnight_count = 0
    for key, recs in trip_groups_raw.items():
        before = [(r["dep_time"], r["arr_time"]) for r in sorted(recs, key=lambda x: x["stop_order"])]
        correct_overnight(recs)  # in-place
        after  = [(r["dep_time"], r["arr_time"]) for r in sorted(recs, key=lambda x: x["stop_order"])]
        if before != after:
            overnight_count += 1

    records = raw_records   # corrected

    # --- Split out other lines' stations (only when EXTRACT_BRANCH_SPLIT=1) ---
    branch_count = 0
    if BRANCH_SPLIT:
        records, branch_count = split_branch_rows(records)

    # --- Renumbering table (only when EXTRACT_RENUMBER_TABLE=1) ---
    renumber_log = []
    if RENUMBER_TABLE:
        renumber_log = apply_renumber_table(records, load_renumber_table())

    # --- trip_summary ---
    trip_groups = defaultdict(list)
    for r in records:
        key = (r["source_sheet"], r["trip_id"], r["trip_num"], r["trip_num_source"], r["line_name"])
        trip_groups[key].append(r)

    trip_summary = []
    for (sheet, tid, tnum, tsrc, _line), recs in sorted(trip_groups.items(), key=lambda kv: kv[0][:4]):
        recs_s = sorted(recs, key=lambda x: x["stop_order"])
        first, last = recs_s[0], recs_s[-1]
        trip_summary.append({
            "source_sheet":    sheet,
            "table_name":      recs_s[0]["table_name"],
            "line_name":       recs_s[0]["line_name"],
            "direction":       recs_s[0]["direction"],
            "trip_id":         tid,
            "trip_num":        tnum,
            "trip_num_source": tsrc,
            "stop_count":      len(recs_s),
            "first_stop":      first["stop_name"],
            "first_dep":       first["dep_time"] or first["arr_time"],
            "last_stop":       last["stop_name"],
            "last_arr":        last["arr_time"] or last["dep_time"],
        })

    # --- issues: reversals remaining after correction (input errors, etc.) ---
    issues = []
    for (sheet, tid, tnum, tsrc, _line), recs in trip_groups.items():
        recs_s = sorted(recs, key=lambda x: x["stop_order"])
        prev_max = None
        for i, r in enumerate(recs_s):
            for key in ("arr_time", "dep_time"):
                t = r[key]
                t_min = hhmm_to_minutes(t)
                if t_min is None:
                    continue
                if prev_max is not None and t_min < prev_max - 5:
                    prev_r = recs_s[i - 1] if i > 0 else r
                    issues.append({
                        "source_sheet": sheet,
                        "trip_id":      tid,
                        "trip_num":     tnum,
                        "issue":        f"補正後も時刻逆転 ({key})",
                        "stop_order":   r["stop_order"],
                        "stop_name":    r["stop_name"],
                        "time":         t,
                        "prev_stop":    prev_r["stop_name"],
                        "prev_time":    prev_r["dep_time"] or prev_r["arr_time"],
                    })
                if prev_max is None or t_min > prev_max:
                    prev_max = t_min

    # --- Write ---
    wb_out = openpyxl.Workbook()

    ws1 = wb_out.active
    ws1.title = "stop_times"
    h1 = ["source_file", "source_sheet", "table_name", "line_name",
          "direction", "direction_raw", "trip_id", "trip_num",
          "trip_num_source", "stop_order", "stop_name", "stop_type",
          "dep_time", "arr_time"]
    ws1.append(h1)
    for r in records:
        ws1.append([r[h] for h in h1])

    ws2 = wb_out.create_sheet("trip_summary")
    h2 = ["source_sheet", "table_name", "line_name", "direction",
          "trip_id", "trip_num", "trip_num_source", "stop_count",
          "first_stop", "first_dep", "last_stop", "last_arr"]
    ws2.append(h2)
    for r in trip_summary:
        ws2.append([r[h] for h in h2])

    ws3 = wb_out.create_sheet("issues")
    h3 = ["source_sheet", "trip_id", "trip_num", "issue",
          "stop_order", "stop_name", "time", "prev_stop", "prev_time"]
    ws3.append(h3)
    for r in issues:
        ws3.append([r[h] for h in h3])

    wb_out.save(output_path)
    print(f"  stop_times:   {len(records)}件")
    print(f"  trip_summary: {len(trip_summary)}便")
    if reverse_count:
        print(f"  stop_order反転: {reverse_count}トリップ")
    print(f"  深夜越え補正: {overnight_count}トリップ")
    if branch_count:
        print(f"  他線の駅の切り出し(branch:): {branch_count}帯")
    for rid, n, why in renumber_log:
        if why:
            print(f"  ★WARN 改番表 {rid}: 付け替えなかった＝{why}")
        else:
            print(f"  改番表 {rid}: {n}停車の番号を付け替えた")
    if WEEKDAY_OFFSET and weekday_count:
        print(f"  曜日サフィックスの日数換算: {weekday_count}セル")
    if TZ_TO_JST and tz_count:
        print(f"  時差の換算(内地時刻へ): {tz_count}セル {tz_by_sys}")
    print(f"  残存 issues:  {len(issues)}件")
    print(f"  保存: {output_path}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="stop_times を long 形式で抽出")
    parser.add_argument("filenames", nargs="*", default=["近代デジタル交通網p1-2.xlsx"],
                        help="処理対象のExcelファイル名")
    parser.add_argument("--input-dir", default=None,
                        help="入力ディレクトリ（デフォルト: 2_timetable_with_tripnum_xlsx_fixed）")
    parser.add_argument("--output-dir", default=None,
                        help="出力ディレクトリ（デフォルト: 3_stop_times_intermediate）")
    args = parser.parse_args()

    base_dir   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    input_dir  = args.input_dir if args.input_dir else os.path.join(base_dir, "data", "2_timetable_with_tripnum_xlsx_fixed")
    output_dir = args.output_dir if args.output_dir else os.path.join(base_dir, "data", "3_stop_times_intermediate")
    os.makedirs(output_dir, exist_ok=True)

    # write flags only when ON (when OFF remove old flags, so a reused directory does not mislead)
    _flags_path = os.path.join(output_dir, EXTRACT_FLAGS_FILE)
    _flags = {}
    if TZ_TO_JST:
        _flags["EXTRACT_TZ_TO_JST"] = 1
        _flags["rules"] = os.path.relpath(__import__("time_system").RULES_CSV, base_dir)
    if RENUMBER_TABLE:   # renumbering table: add the flag only when ON
        _flags["EXTRACT_RENUMBER_TABLE"] = 1
        _flags["renumber_table"] = os.path.relpath(RENUMBER_TABLE_PATH, base_dir)
    if _flags:
        import json
        with open(_flags_path, "w", encoding="utf-8") as _f:
            json.dump(_flags, _f, ensure_ascii=False, indent=1)
    elif os.path.exists(_flags_path):
        os.remove(_flags_path)

    for fname in args.filenames:
        input_path  = os.path.join(input_dir, fname)
        output_path = os.path.join(output_dir, fname)
        if not os.path.exists(input_path):
            print(f"ファイルが見つかりません: {input_path}")
            continue
        extract_file(input_path, output_path)

    if RENUMBER_TABLE:
        _missing = [r["改番ID"].strip() for r in load_renumber_table() if r["改番ID"].strip() not in _RENUMBER_SEEN]
        if _missing:
            _joined = "・".join(_missing)
            print(f"改番表: このたびの抽出にシートが無かった行 {len(_missing)}（そのページを抽出していなければ正常）: {_joined}")
