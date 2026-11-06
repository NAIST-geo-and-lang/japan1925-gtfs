"""
split_combined_trips.py

Split trips with a combined line name ("X及Y本線") into two at the junction station.

Input:  data/4_integrated/integrated_stop_times.csv
Output: the same file (in place) + data/4_integrated/split_trips_report.csv

Steps:
  1. Read integrated_stop_times.csv.
  2. For each trip, check whether line_name is in BOUNDARY_STATIONS.
  3. Find the junction station among the trip's stops.
  4. Split into 2 trips at the junction (the junction is in both).
     New key = `{component line}__{direction}__{trip_num}`.
  5. Orientation: which side of the junction belongs to which component line is decided
     from station-to-line evidence (station sets of single-line trips, mileage lookup),
     propagated over a corridor through shared stop_order between trips
     (same order = same direction, reversed = opposite).
  6. Collisions: if a part's key collides with an existing trip, drop only the parts that
     are a reprint of the same run (stations contained, times within +/-10 minutes; the
     detail table wins). If the part has its own stations or the times differ (possibly
     another train with the same number), keep the whole combined-line trip unsplit.
  7. Final dedup (double listings with 及): among trips still under a combined line name,
     drop those whose every (station, time) is covered by non-combined trips in the same
     direction within +/-10 minutes. Keep if any (station, time) is unique.
     Switch: SPLIT_FINAL_DEDUP=0. Report action=dedup_covered.
  8. Direction per component: a combined-line band is a through itinerary, so the line's own
     up/down can flip between the front and back parts (`常磐及成田線`: 上野->我孫子 is down
     on 常磐線, 我孫子->成田 is up on 成田線). Just before building a part's key, flip its
     direction only if (a) no same-numbered trip exists in the same direction and (b) it is
     wholly covered by a same-numbered trip in the opposite direction. Because of (b) it always
     ends as "covered -> dropped"; no new trip is created.
     Switch: SPLIT_PART_DIRECTION=0. Report action=part_direction_flip.
  9. Direction of bands without a partner: step 8 requires (b), so bands whose detail trip is
     not in the corpus keep a reversed direction label. Only then, flip it if the line's own
     station order (the same measure as `detect_band_orientation`) says it is reversed. Done
     only when no trip with the same number exists in either direction, so the trip count is
     unchanged; only the direction label changes.
     Switch: SPLIT_PART_DIRECTION_ORDER=0 (default ON). Report action=part_direction_order.
  10. Different trains across the 著 (arrival) row and 發 (departure) row: where the original
     prints one station as a 著 row and a 發 row and the page image shows a transfer mark ＊
     or a different column, act per the actions table
     `data/tables/arrival_departure_rows/actions.csv`: drop (e.g. a band on p182 reprinting the
     main table of p183) or split into 2 trips (key suffix _b). Drop only if every
     (station, 著/發, time mod 24h) remains in another trip.
     Switch: SPLIT_A08_ACTIONS=0 (default ON).
     Report action=a08_drop_after / a08_drop_before / a08_split_after / a08_split_before / a08_refused.
  11. Merge a 著 row and a 發 row into one stop: among the remaining "arrival-only row then
     departure-only row of the same station" pairs, those the page image shows with neither ＊
     nor a terminating line (merge table `data/tables/arrival_departure_rows/merges.csv`)
     become one row with 著 from row 1 and 發 from row 2 (no time is dropped).
     Pairs not in the merge table are untouched.
     Switch: SPLIT_A08_MERGE=0 (default ON).
     Report action=a08_merge / a08_merge_refused / a08_unread.
  12. Do not split a band that runs on only one line (one line-name cell spanning several
     bands): one line-name cell in the original can head both a through band and a band on only
     one line, so the transcription gives both the combined name. Even if the junction is a stop,
     if all stations belong to one line (mileage CSV + station sets of non-combined trips), at
     least one station is only on that line and none is only on the other, assign the band to
     that line without splitting (p80 名古屋->龜山->柘植 is 關西本線).
     Switch: SPLIT_SINGLE_LINE_BAND=0 (default ON). Report action=single_line_band.
  13. Rebase trips whose front part was cut: the back part of a split combined band, trips
     whose front was dropped/split by the actions table of step 10, and trips renumbered from a
     station onward keep the day clock of the cut front part, so they start at 24:00 or later
     (e.g. 滿鐵安奉線 6 奉天 34:00). Shift them back by a multiple of 1440 so the first time
     (local time, i.e. without the time-system offset) falls in 0:00-23:59 (same idea as
     INTEGRATE_B5_SPLIT_REBASE in integration).
     Switch: SPLIT_REBASE_LATE_START (default ON; =0 for previous behavior). Report action=rebase_late_start.
"""

import csv
import math
import os
import re
import sys
from collections import defaultdict, OrderedDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTEGRATED = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'integrated_stop_times.csv')
REPORT = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'split_trips_report.csv')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from known_kanji_variants import normalize as _kv_norm

# combined line -> (front line, back line, junction station)
# Along the trip's station order (first -> last), stations up to the junction are the front part
# and stations from the junction on are the back part. The junction is in both trips.
BOUNDARY_STATIONS = {
    # === Japan proper ===
    '北陸及東海道本線':       ('北陸本線', '東海道本線', '米原'),
    '東海道及北陸本線':       ('東海道本線', '北陸本線', '米原'),
    '東海道及山陽本線':       ('東海道本線', '山陽本線', '神戸'),
    '山陽及東海道本線':       ('山陽本線', '東海道本線', '神戸'),
    '城東線及東海道本線':     ('城東線', '東海道本線', '大阪'),
    '北陸及信越本線':         ('北陸本線', '信越本線', '直江津'),
    '信越及北陸本線':         ('信越本線', '北陸本線', '直江津'),
    '信越及東北線':           ('信越本線', '東北本線', '高崎'),
    '東北及信越線':           ('東北本線', '信越本線', '高崎'),
    '東北及信越線高崎線':     ('東北本線', '信越本線', '高崎'),
    '東北本線及常磐線':       ('東北本線', '常磐線', '岩沼'),
    '篠ノ井及信越線':         ('篠ノ井線', '信越本線', '篠ノ井'),
    # Mirror for the up direction. The line-name cell of the up table on p70 is set in 2 columns:
    # "信越及篠ノ井線" (left "信越及" / right "篠ノ井線").
    '信越及篠ノ井線':         ('信越本線', '篠ノ井線', '篠ノ井'),

    # === Kansai and Chugoku ===
    '城東及關西本線':         ('城東線', '關西本線', '天王寺'),
    '關西本線及城東線':       ('關西本線', '城東線', '天王寺'),
    '參宮線及關西本線':       ('參宮線', '關西本線', '龜山'),
    # Mirror for the up direction. The line-name cell of the up table on p80 is set in 2 columns,
    # "關西本線及參宮線", heading 2 sub-blocks (柘植->龜山->名古屋 / 柘植->龜山->山田->鳥羽).
    '關西本線及參宮線':       ('關西本線', '參宮線', '龜山'),
    '山陰本線及福知山線':     ('山陰本線', '福知山線', '福知山'),
    '山陰及大社本線':         ('山陰本線', '大社線', '出雲今市'),
    '山陰本線及大社線':       ('山陰本線', '大社線', '出雲今市'),
    '山陰及舞鶴本線':         ('山陰本線', '舞鶴線', '綾部'),
    '山陰本線及舞鶴線':       ('山陰本線', '舞鶴線', '綾部'),
    '山陰及山口線':           ('山陰本線', '山口線', '益田'),
    '山口及山陰線':           ('山口線', '山陰本線', '益田'),
    '小濱及舞鶴線':           ('小濱線', '舞鶴線', '新舞鶴'),
    '舞鶴及小濱線':           ('舞鶴線', '小濱線', '新舞鶴'),

    # === Kanto ===
    '常磐及成田線':           ('常磐線', '成田線', '我孫子'),
    '總武及成田線':           ('總武本線', '成田線', '佐倉'),
    # Mirror for the up direction. The line-name cell of the 成田->兩國橋 band in the up table on p138
    # is set in 2 columns: "成田及總武線" (left "成田及" / right "總武線").
    '成田及總武線':           ('成田線', '總武本線', '佐倉'),

    # === Hokkaido ===
    '凾館及宗谷本線':         ('函館本線', '宗谷本線', '旭川'),
    '宗谷及凾館本線':         ('宗谷本線', '函館本線', '旭川'),

    # === Kyushu ===
    '日豐及鹿兒島本線':       ('日豐本線', '鹿兒島本線', '吉松'),
    '鹿兒島及長崎本線':       ('鹿兒島本線', '長崎本線', '鳥栖'),

    # === Korea and Manchuria ===
    '安奉線及滿洲線':         ('滿鐵安奉線', '滿洲線', '奉天〈滿洲〉'),
    '朝鮮及滿洲線':           ('朝鮮線', '滿洲線', '安東〈滿洲〉'),
    '朝鮮及満洲線':           ('朝鮮線', '滿洲線', '安東〈滿洲〉'),
    '滿鐵京元線及咸鏡線南部': ('滿鐵京元線', '滿鐵咸鏡線南部', '元山'),

    # === China ===
    '支那國有鐵道滬寧及滬杭甬線': ('支那國有鐵道滬寧線', '支那國有鐵道滬杭甬線', '上海'),
    '支那國有鐵道隴海及汴洛線':   ('支那國有鐵道隴海線', '支那國有鐵道汴洛線', '鄭州'),
    '支那國有鐵道粤漢及株萍線':   ('支那國有鐵道粤漢線', '支那國有鐵道株萍線', '株州'),
}

# === 3-way combined lines (order: front -> mid -> back) ===
# Structure: line_name -> (line_A, line_B, line_C, boundary_AB, boundary_BC)
BOUNDARY_STATIONS_3WAY = {
    '東北、信越及北陸本線': ('東北本線', '信越本線', '北陸本線', '高崎', '直江津'),
    '北陸、信越及東北本線': ('北陸本線', '信越本線', '東北本線', '直江津', '高崎'),
}

# Combined line names added to the split table (names not in the table are neither split nor handled
#   by SPLIT_SINGLE_LINE_BAND and stay as a combined-name route). Only names with 2 components, one
#   junction, and mileage and detail-trip evidence for the component lines:
#   - 福知山線及山陰本線 = p78 down; mirror of "山陰本線及福知山線" in the table
#   - 函館、根室本線 = summary band on p176 (函館->小樽->瀧川->...->池田; 函館本線 to 根室本線 at 瀧川)
#   Branching names (函館・宗谷及根室本線 / 臺灣總督府鐵道縦貫線及臺中線 / 滿鐵滿洲本線・旅順線及營口線)
#   and a heading that covers 4 lines with 2 names (東海道及山陰線) cannot be split at one junction.
#   Default ON. Previous behavior (not added) = SPLIT_BOUNDARY_ADDITIONS=0.
BOUNDARY_ADDITIONS = {
    '福知山線及山陰本線':     ('福知山線', '山陰本線', '福知山'),
    '函館、根室本線':         ('函館本線', '根室本線', '瀧川'),
}
BOUNDARY_ADDITIONS_ON = os.environ.get('SPLIT_BOUNDARY_ADDITIONS', '1') != '0'
if BOUNDARY_ADDITIONS_ON:
    BOUNDARY_STATIONS.update(BOUNDARY_ADDITIONS)

# Do not split combined names whose boundary is not printed. On p184 the line-name cell only says
#   "支那國有鐵道隴海及汴洛線" and does not show where 汴洛線 begins (鄭州 in the table is a convenience;
#   in 1925 the 汴洛 line ran 開封-洛陽).
#   Default ON. Previous behavior (split at 鄭州) = SPLIT_KEEP_UNPRINTED_BOUNDARY=0.
UNPRINTED_BOUNDARY_NAMES = {'支那國有鐵道隴海及汴洛線'}
KEEP_UNPRINTED_BOUNDARY = os.environ.get('SPLIT_KEEP_UNPRINTED_BOUNDARY', '1') != '0'
if KEEP_UNPRINTED_BOUNDARY:
    for _n in UNPRINTED_BOUNDARY_NAMES:
        BOUNDARY_STATIONS.pop(_n, None)


def _base_name(name):
    """Station name without the disambiguation tag (〈滿洲〉 etc.)."""
    return (name or '').split('〈')[0]


def _part_covered(part_rows, existing_rows, tol=10):
    """Is part a reprint of the same run as existing (the existing trip with the same key)?
    Stations (base names) must be contained, and rows with times must match within +/-tol minutes.
    The same number with very different times is another train (e.g. 成田線 462 = morning
    我孫子->成田 local vs. through summary 462 = midday 成田->上野): return False and the caller
    keeps the whole original trip. Differences within +/-tol are summary-band rounding; the detail wins."""
    ex_names = set()
    ex_times = defaultdict(list)
    for r in existing_rows:
        b = _base_name(r['stop_name'])
        ex_names.add(b)
        t = _row_min(r)
        if t is not None:
            ex_times[b].append(t % 1440)
    for r in part_rows:
        b = _base_name(r['stop_name'])
        if b not in ex_names:
            return False
        t = _row_min(r)
        if t is None:
            continue
        t %= 1440
        if not any(min(abs(t - c) % 1440, 1440 - (abs(t - c) % 1440)) <= tol
                   for c in ex_times.get(b, ())):
            return False
    return True


def _part_covered_any(part_rows, existing_rows, tol=10):
    """Like `_part_covered` (stations contained + times within +/-tol) but compares both 著 and 發
    (avoids the one-time-per-station gap of `_row_min`). Used only for the remaining parts of the
    band being extended by `SPLIT_EXTEND_EXISTING`."""
    ex_names = set()
    ex_times = defaultdict(list)
    for r in existing_rows:
        b = _kv_norm(_base_name(r['stop_name']))
        ex_names.add(b)
        for col in ('arr_time', 'dep_time'):
            t = _to_min(r.get(col))
            if t is not None:
                ex_times[b].append(t % 1440)
    for r in part_rows:
        b = _kv_norm(_base_name(r['stop_name']))
        if b not in ex_names:
            return False
        for col in ('arr_time', 'dep_time'):
            t = _to_min(r.get(col))
            if t is None:
                continue
            if not any(_cyc(t % 1440, c) <= tol for c in ex_times.get(b, ())):
                return False
    return True


def _resolve_part_direction(sub_line, part_rows, direction, trip_num, final):
    """Decide the `direction` of a split part (`SPLIT_PART_DIRECTION`).

    `SPLIT_PART_DIRECTION=0` (previous behavior) = use the combined trip's direction.
    By default (ON), return the opposite direction only if both hold:
      (a) `{sub_line}__{direction}__{trip_num}` does not exist
      (b) `{sub_line}__{opp}__{trip_num}` exists and `_part_covered()` says it wholly
          covers the part (all stations present, times within +/-10 minutes)
    With (b) the caller always ends in "covered -> dropped", so no new trip is created
    (times only in the band are written into blanks by `_merge_unique_times`).

    With `SPLIT_PART_DIRECTION_ORDER` (default ON; `=0` for previous behavior), if no
    same-numbered trip exists in either direction (a band without a detail partner), flip
    when the line's station order (same measure as the band orientation check) says it is
    reversed = `_order_says_reverse()`.
    """
    if not PART_DIRECTION:
        return direction
    if f'{sub_line}__{direction}__{trip_num}' in final:
        return direction
    opp = 'inbound' if direction == 'outbound' else 'outbound'
    ko = f'{sub_line}__{opp}__{trip_num}'
    if ko in final:
        return opp if _part_covered(part_rows, final[ko]) else direction
    # band without a partner: measure by station order (`SPLIT_PART_DIRECTION_ORDER`, default ON)
    if PART_DIRECTION_ORDER and _order_says_reverse(sub_line, part_rows, direction):
        return opp
    return direction


def _order_says_reverse(sub_line, part_rows, direction):
    """Is the part's station order the reverse of the line's reference (band orientation check measure)?"""
    ref = LINE_ORDER_REF.get(sub_line)
    if not ref or ref[0][0] < PART_DIR_MINREF:
        return False
    stops = [_bo.canon(r['stop_name']) for r in part_rows]
    verdict, n = _bo.orient(LINE_ORDER_REF, sub_line, stops)
    return bool(verdict) and n >= PART_DIR_MINREF and verdict != direction


def _to_min(t):
    """'HH:MM' (may exceed 24h) -> minutes. Invalid values -> None."""
    s = str(t) if t is not None else ''
    if ':' not in s:
        return None
    try:
        h, m = s.split(':')
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _row_min(r):
    t = _to_min(r.get('dep_time'))
    if t is None:
        t = _to_min(r.get('arr_time'))
    return t


def _load_lookup_pairs():
    """(station, line) pairs from the mileage transcription (evidence for orientation if present)."""
    path = os.path.join(BASE_DIR, 'data', 'distance', 'lookup_positions.csv')
    pairs = set()
    if os.path.exists(path):
        with open(path, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                pairs.add((_base_name(r['stop_name']), r['line_name']))
    return pairs


LOOKUP_PAIRS = _load_lookup_pairs()


# ------------------------------------------------------------------
# Checking reclassify
# ------------------------------------------------------------------
# When the junction is not in the trip, _stopwise_split assigns stations to components and fills
# undecided ones from their neighbors, so it can fold even stations only on the other component
# into one line (action=reclassified; e.g. 信越及東北線 上野->直江津, a summary band on p61, would put
# 上野 on 信越本線). Using transcription evidence (mileage CSV (station, line) + station sets of
# non-combined trips in the same file), if any station has no evidence for the target line but has
# evidence for the other component, do not reclassify; keep the combined name (splitting would only
# give a 1-station trip; same treatment as kept/kept_conflict).
# Default ON. Previous behavior = SPLIT_RECLASSIFY_GUARD=0.
RECLASSIFY_GUARD = os.environ.get('SPLIT_RECLASSIFY_GUARD', '1') != '0'

# A station's line is decided only from transcription evidence. _classify_stop (per-station assignment
# when the junction is not in the trip) uses _build_line_evidence (mileage CSV (station, line) +
# station sets of non-combined trips); _station_line_score (orientation votes when splitting at the
# junction) counts 2 points for non-combined trips and 1 for the mileage CSV. The coordinate tables
# are not used. If every part of a per-station split into 2+ lines is covered by existing trips (the
# cross-line band would vanish), do not split; leave it to the dedup step (the R3a riding condition)
# (_stopwise_all_covered).


def _build_line_evidence(plain_stations):
    """line name -> set of station names from the transcription (kanji variants normalized):
    (1) mileage CSV (station, line); (2) station sets of trips with non-combined line_name in the same file.
    The coordinate tables are not included: their keys come from downstream output, so a wrong
    assignment there would confirm itself (circular)."""
    ev = defaultdict(set)
    for st, line in LOOKUP_PAIRS:
        ev[line].add(_kv_norm(st))
    for line, names in plain_stations.items():
        for st in names:
            ev[line].add(_kv_norm(st))
    return ev


def _reclassify_blockers(trip_rows, chosen, others, line_evidence):
    """Station names that block folding into chosen:
    stations with no evidence for chosen but evidence for another component (others).
    Stations with no evidence either way are neutral (do not block)."""
    blockers = []
    for r in trip_rows:
        k = _kv_norm(_base_name(r['stop_name']))
        if k in line_evidence.get(chosen, ()):
            continue
        if any(k in line_evidence.get(o, ()) for o in others):
            blockers.append(r['stop_name'])
    return blockers


def _single_line_of(names, line_a, line_b, line_evidence):
    """If all stations in names belong to one line, return that line (SPLIT_SINGLE_LINE_BAND).
    Condition: all stations have evidence for that line, at least one is only on that line and none
    is only on the other. Otherwise None (split at the junction as before).
    Returns (line name or None, list of stations only on that line)."""
    ea = line_evidence.get(line_a, set())
    eb = line_evidence.get(line_b, set())
    keys = [(n, _kv_norm(_base_name(n))) for n in names]
    all_a = all(k in ea for _, k in keys)
    all_b = all(k in eb for _, k in keys)
    only_a = [n for n, k in keys if k in ea and k not in eb]
    only_b = [n for n, k in keys if k in eb and k not in ea]
    if all_a and only_a and not only_b and not all_b:
        return line_a, only_a
    if all_b and only_b and not only_a and not all_a:
        return line_b, only_b
    return None, []


# ------------------------------------------------------------------
# Write times found only in a dropped band into blanks of the existing trip
# ------------------------------------------------------------------
# When a part's key collides with an existing trip and `_part_covered()` calls it a reprint of the
# same run, `commit_parts()` drops the part (the detail wins). That check uses `_row_min` (one time
# per station, 發 if present), so a band's 著 (arrival) can match the detail's 發 (departure) and
# dropping the band loses that 著 (e.g. 綾部 著 in the p4 connection table; the detail page p76
# prints only one time at 綾部). A separate trip would duplicate the detail, so write the time into
# an empty field of the existing trip (same idea as the gap-fill weaving in integration).
# Default ON. Previous behavior = SPLIT_MERGE_UNIQUE_TIMES=0.
MERGE_UNIQUE_TIMES = os.environ.get('SPLIT_MERGE_UNIQUE_TIMES', '1') != '0'

# Combined-line bands whose front and back parts run in opposite directions on their own lines
# ------------------------------------------------------------------
# A part's key is `{component line}__{direction}__{trip_num}`, with `direction` taken from row 6 of
# the combined trip (the band's sheet). A connecting band is a through itinerary, so the line's own
# up/down can differ between the front and back parts.
#   e.g. `常磐及成田線` (p0137_tb003-1, 下リ列車) = 上野->我孫子->成田:
#        上野->我孫子 is down on 常磐線; 我孫子->成田 is up on 成田線
# Row 6 of a sheet holds one value, so the transcription cannot express this (either way one
# component gets the reversed key and its run appears twice). So flip the direction per component
# here, only when both hold:
#   (a) no same-numbered trip exists in the part's direction
#   (b) a same-numbered trip exists in the opposite direction and `_part_covered()` says it
#       wholly covers the part (all stations, times within +/-10 minutes)
# A flipped part is covered by definition and dropped (band-only times go into blanks via
# `_merge_unique_times`); no new trip is created.
# Default ON. Previous behavior = SPLIT_PART_DIRECTION=0.
PART_DIRECTION = os.environ.get('SPLIT_PART_DIRECTION', '1') != '0'

# ------------------------------------------------------------------
# Direction per component, stage 2 (bands without a partner)
# ------------------------------------------------------------------
# (b) above assumes a partner exists, so bands with no partner on the line's detail pages keep a
# reversed label. When (b) fails, measure by the line's own station order, calling `build()` /
# `orient()` of the band orientation check (`scripts/detectors/detect_band_orientation.py`).
# Three conditions:
#   (a)  no same-numbered trip in the same direction
#   (b') no same-numbered trip in the opposite direction either (if one exists, the coverage check applies)
#   (c)  the line's reference sequence is at least `SPLIT_PART_DIR_MINREF` (default 15) long and
#        a majority vote says the part's order is the reverse
# The reference is the longest station sequence among non-combined trips, so a band is never its own reference.
# Both keys are free, so flipping changes only the direction label, not the trip count.
# Default ON. Previous behavior = SPLIT_PART_DIRECTION_ORDER=0.
PART_DIRECTION_ORDER = os.environ.get('SPLIT_PART_DIRECTION_ORDER', '1') != '0'
PART_DIR_MINREF = int(os.environ.get('SPLIT_PART_DIR_MINREF', '15'))
# line name -> [(length, station sequence)] in outbound order. Built by main() from input rows.
LINE_ORDER_REF = {}
_bo = None                      # band orientation check module (loaded only when ON)

# ------------------------------------------------------------------
# Do not split a band that runs on only one line at the junction
# ------------------------------------------------------------------
# One line-name cell in the original can head several stacked bands (p80 "參宮線及關西本線" =
# 鳥羽->龜山->柘植, a cross-line through band, and 名古屋->龜山->柘植, 關西本線 only). The
# transcription writes the combined name on every band it heads. If the junction (龜山) is a stop,
# the 2-way split below always splits, creating a nonexistent "參宮線" for 名古屋->龜山.
# So before splitting, check with transcription evidence (_build_line_evidence) whether all stations
# belong to one line, at least one is only on that line and none is only on the other; if so, fold
# into that line (then the usual collision handling: drop if covered, write band-only times into
# blanks). Split if any station lacks evidence or there are stations only on each line.
# Default ON. Previous behavior = SPLIT_SINGLE_LINE_BAND=0.
SINGLE_LINE_BAND = os.environ.get('SPLIT_SINGLE_LINE_BAND', '1') != '0'

# ------------------------------------------------------------------
# Extend an existing trip with a band part
# ------------------------------------------------------------------
# If a part's key collides with an existing trip and the part is not wholly contained in it
# (`_part_covered` is false), `commit_parts()` keeps the whole band under the combined name
# (kept_conflict). But the containment can go the other way: the existing trip is wholly contained
# in the part (e.g. the p48 band 山陰本線及舞鶴線 30, 新舞鶴->舞鶴->梅迫->綾部; the 舞鶴線 detail on
# p72 has only 新舞鶴 發 -> 舞鶴 著). Then extend the existing trip (same number and direction, a
# single-line trip present before splitting) along the part's station order: add rows for stations
# only in the part and fill blanks of shared stations with `_merge_unique_times`. Conditions (else
# keep the original trip):
#   (1) all stations of the existing trip are in the part, in the same order (no station twice in either)
#   (2) its times match the part within +/-10 minutes, with the same midnight shift (multiple of 1440) at every station
#   (3) times do not decrease after extending
#   (4) the part has more stations (if equal, the coverage check applies)
# The extended trip keeps its key, line, direction and number; added rows keep the band's source sheet.
# Logged as extend_existing in split_trips_report.csv.
# Default ON. Previous behavior = SPLIT_EXTEND_EXISTING=0.
EXTEND_EXISTING = os.environ.get('SPLIT_EXTEND_EXISTING', '1') == '1'


def _load_line_order_ref(rows):
    """Build each line's reference sequence with `build()` of the band orientation check (called only when ON)."""
    global _bo, LINE_ORDER_REF
    if _bo is None:
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'detectors'))
        import detect_band_orientation as bo   # noqa: E402  (lazy import; not loaded when OFF)
        _bo = bo
    _, _, ref = _bo.build(rows)
    LINE_ORDER_REF = ref


def _cyc(a, b):
    """Time difference in minutes on a 24-hour cycle."""
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def _merge_unique_times(part_rows, existing_rows, tol=10):
    """Write times found only in the dropped part into empty fields of the existing trip.

    Conditions (skip if any fails):
      - fill only empty fields (never overwrite an existing value)
      - if a station appears more than once (Y-shaped branch), use the row with the nearest time
      - shift by a multiple of 1440 to match the target row's day (do not write 27:21 as 3:21)
      - 著 (arrival) must not be after 發 (departure), and 發 not before 著
    Returns [(station, '著'|'發', time written), ...]
    """
    idx = defaultdict(list)
    for r in existing_rows:
        idx[_kv_norm(_base_name(r['stop_name']))].append(r)
    merged = []
    for pr in part_rows:
        cands = idx.get(_kv_norm(_base_name(pr['stop_name'])))
        if not cands:
            continue
        for col, lab, other in (('arr_time', '著', 'dep_time'),
                                ('dep_time', '發', 'arr_time')):
            t = _to_min(pr.get(col))
            if t is None:
                continue
            # nothing to do if the existing trip already has this field (within +/-tol)
            if any(_cyc(t, v) <= tol for v in
                   (_to_min(r.get(col)) for r in cands) if v is not None):
                continue
            best = bestd = None
            for r in cands:
                for c2 in ('dep_time', 'arr_time'):
                    v = _to_min(r.get(c2))
                    if v is None:
                        continue
                    d = _cyc(t, v)
                    if bestd is None or d < bestd:
                        best, bestd = r, d
            if best is None or bestd > tol or best.get(col):
                continue
            ref = _to_min(best.get(other))
            if ref is None:
                continue
            t2 = t + int(round((ref - t) / 1440.0)) * 1440
            if t2 < 0 or (lab == '著' and t2 > ref) or (lab == '發' and t2 < ref):
                continue
            best[col] = '%02d:%02d' % (t2 // 60, t2 % 60)
            merged.append((pr['stop_name'], lab, best[col]))
    return merged


def _extend_plan(part_rows, existing_rows, tol=10):
    """Can the existing trip be extended by the part (`SPLIT_EXTEND_EXISTING`)? None if not.
    If so, return (midnight shift k [multiple of 1440 minutes], [('ex'|'new', row), ...] in the part's station order)."""
    pn = [_kv_norm(_base_name(r['stop_name'])) for r in part_rows]
    ex = sorted(existing_rows, key=lambda r: int(r['stop_sequence']))
    en = [_kv_norm(_base_name(r['stop_name'])) for r in ex]
    if len(set(pn)) != len(pn) or len(set(en)) != len(en) or len(pn) <= len(en):
        return None
    pos = {n: i for i, n in enumerate(pn)}
    if any(n not in pos for n in en):
        return None
    idxs = [pos[n] for n in en]
    if idxs != sorted(idxs):
        return None
    shifts = set()
    for n, r in zip(en, ex):
        tp, te = _row_min(part_rows[pos[n]]), _row_min(r)
        if tp is None or te is None:
            continue
        k = int(round((te - tp) / 1440.0))
        if abs(te - (tp + k * 1440)) > tol:
            return None
        shifts.add(k)
    if len(shifts) != 1:
        return None
    k = shifts.pop()
    exmap = dict(zip(en, ex))
    plan = [('ex', exmap[n]) if n in exmap else ('new', pr) for n, pr in zip(pn, part_rows)]
    last = None
    for kind, r in plan:
        for col in ('arr_time', 'dep_time'):
            t = _to_min(r.get(col))
            if t is None:
                continue
            if kind == 'new':
                t += k * 1440
            if last is not None and t < last:
                return None
            last = t
    return k, plan


def _station_line_score(rows, line, plain_stations):
    """Amount of evidence that the stations in rows belong to line:
    station sets of single-line trips in the same file (strongest, 2 points), mileage lookup (1 point)."""
    score = 0
    for r in rows:
        nm = r['stop_name']
        b = _base_name(nm)
        if b in plain_stations.get(line, ()):
            score += 2
        if (b, line) in LOOKUP_PAIRS:
            score += 1
    return score


def _shared_order_relation(rows_a, rows_b):
    """Relative direction of 2 trips from the stop_order of shared stations (base names, first occurrence):
    'same' (same order = same direction) / 'rev' (reversed = opposite) / None (fewer than 2 shared, or mixed).
    Generalizes the fact that up and down trips have mutually reversed stop_order."""
    pos_a = {}
    for i, r in enumerate(rows_a):
        pos_a.setdefault(_base_name(r['stop_name']), i)
    pos_b = {}
    for i, r in enumerate(rows_b):
        pos_b.setdefault(_base_name(r['stop_name']), i)
    shared = sorted((b for b in pos_a if b in pos_b), key=lambda b: pos_a[b])
    if len(shared) < 2:
        return None
    n_same = n_rev = 0
    for prev, cur in zip(shared, shared[1:]):
        if pos_b[cur] > pos_b[prev]:
            n_same += 1
        elif pos_b[cur] < pos_b[prev]:
            n_rev += 1
    if n_same and not n_rev:
        return 'same'
    if n_rev and not n_same:
        return 'rev'
    return None


def _resolve_orientations(entries, plain_stations):
    """Decide (line before junction, line after junction) for trips to be split.

    Station-to-line votes (_station_line_score) can be empty for a single trip (e.g. no
    evidence for the Chinese 隴海/汴洛 lines). So trips in the same corridor (same line pair
    and junction) are linked by comparing shared stations' stop_order (same order = same
    direction, reversed = opposite), and votes are summed over each connected group to get a
    consistent orientation. Only groups with no evidence at all fall back to the order of the
    components in the line name.
    entries: [{'tk','rows','front','back','boundary_idx'}, ...] (one corridor)
    Returns {tk: (side1_line, side2_line)}
    """
    n = len(entries)
    c0, c1 = sorted([entries[0]['front'], entries[0]['back']])
    ev = []
    for e in entries:
        s1 = e['rows'][:e['boundary_idx']]
        s2 = e['rows'][e['boundary_idx'] + 1:]
        score_c0 = (_station_line_score(s1, c0, plain_stations)
                    + _station_line_score(s2, c1, plain_stations))
        score_c1 = (_station_line_score(s1, c1, plain_stations)
                    + _station_line_score(s2, c0, plain_stations))
        ev.append(score_c0 - score_c1)  # positive -> before junction = c0

    parent = list(range(n))
    parity = [0] * n  # 1 if opposite to the root

    def find(x):
        path = []
        while parent[x] != x:
            path.append(x)
            x = parent[x]
        root = x
        p = 0
        for node in reversed(path):
            p ^= parity[node]
            parent[node] = root
            parity[node] = p
        return root

    for i in range(n):
        for j in range(i + 1, n):
            rel = _shared_order_relation(entries[i]['rows'], entries[j]['rows'])
            if rel is None:
                continue
            ri, rj = find(i), find(j)
            if ri == rj:
                continue
            parent[rj] = ri
            parity[rj] = parity[i] ^ parity[j] ^ (1 if rel == 'rev' else 0)

    comps = defaultdict(list)
    for i in range(n):
        comps[find(i)].append(i)
    out = {}
    for members in comps.values():
        total = sum(ev[i] * (1 if parity[i] == 0 else -1) for i in members)
        if total == 0:
            # group with no evidence: use the line-name component order of the longest trip and
            # propagate to all through parity (keeps up/down reversal consistent)
            ref = max(members, key=lambda i: len(entries[i]['rows']))
            total = 1 if ((entries[ref]['front'] == c0) == (parity[ref] == 0)) else -1
        for i in members:
            e = entries[i]
            if total > 0:
                side1 = c0 if parity[i] == 0 else c1
            else:
                side1 = c1 if parity[i] == 0 else c0
            side2 = c1 if side1 == c0 else c0
            out[e['tk']] = (side1, side2)
    return out


def _classify_stop(stop_name, sub_lines, line_evidence):
    """Decide which sub_line stop_name belongs to from transcription evidence (None unless exactly one matches; then inherited from neighbors)."""
    k = _kv_norm(_base_name(stop_name))
    matches = [sl for sl in sub_lines if k in line_evidence.get(sl, ())]
    return matches[0] if len(matches) == 1 else None


def _stopwise_split(trip_rows, sub_lines, line_evidence):
    """Assign each stop to a sub_line and group consecutive stops of the same sub_line.
    Stops without evidence inherit the sub_line of their decided neighbors.
    Returns list of (sub_line_or_None, list of trip_rows).
    """
    classifications = [_classify_stop(r['stop_name'], sub_lines, line_evidence) for r in trip_rows]
    # inherit forward
    last = None
    for i in range(len(classifications)):
        if classifications[i] is None:
            classifications[i] = last
        else:
            last = classifications[i]
    # inherit backward (fill leading None)
    last = None
    for i in range(len(classifications) - 1, -1, -1):
        if classifications[i] is None:
            classifications[i] = last
        else:
            last = classifications[i]
    # group consecutive runs
    groups = []
    cur_line = classifications[0]
    cur_group = [trip_rows[0]]
    for i in range(1, len(trip_rows)):
        if classifications[i] != cur_line:
            groups.append((cur_line, cur_group))
            cur_group = []
        cur_line = classifications[i]
        cur_group.append(trip_rows[i])
    groups.append((cur_line, cur_group))
    return groups


def _stopwise_all_covered(groups, d, n, final):
    """Are all parts of a per-station split into 2+ lines covered by same-numbered existing trips
    (either direction), i.e. would splitting make the cross-line band vanish?
    Whether to drop the band is left to the dedup step (R3a of SPLIT_CONTAINED_DEDUP_MULTI, which
    checks whether only the band represents a through ride across lines); if splitting creates
    nothing new, do not split here."""
    merged = []
    for sl, rs in groups:
        if merged and merged[-1][0] == sl:
            merged[-1] = (sl, merged[-1][1] + rs)
        else:
            merged.append((sl, rs))
    if any(sl is None for sl, _ in merged) or len(merged) < 2:
        return False             # bands folded into one line (not crossing lines) are folded and dropped as before
    opp = 'inbound' if d == 'outbound' else 'outbound'
    return all(any(k in final and _part_covered(rs, final[k]) for k in (f'{sl}__{d}__{n}', f'{sl}__{opp}__{n}'))
               for sl, rs in merged)


def _kept_stopwise_covered(final, split_log, tk, ln, trip_rows, groups):
    final.setdefault(tk, []).extend(trip_rows)
    split_log.append({
        'trip_key': tk, 'line_name': ln, 'action': 'kept_stopwise_covered',
        'reason': '驛ごとに分けると、どの部分も同じ番号の既存の便に被覆されて帯がまるごと消える＝消すかは重複を除く段（乗車の条件つき）に任せる',
        'stops': ' → '.join(r['stop_name'] for r in trip_rows),
        'front_trip': '', 'front_stops': ' || '.join(f'{sl}: ' + ' → '.join(r['stop_name'] for r in rs) for sl, rs in groups),
        'back_trip': '', 'back_stops': '',
    })


def _emit_stopwise(groups, commit_parts, split_log, tk, original_ln, trip_rows):
    """Create sub-trips from per-stop groups (via commit_parts, which handles collisions).
    Returns the commit_parts outcome."""
    # merge adjacent groups of the same sub_line into one trip
    merged = []
    for sub_line, rs in groups:
        if merged and merged[-1][0] == sub_line:
            merged[-1] = (sub_line, merged[-1][1] + rs)
        else:
            merged.append((sub_line, rs))
    labels, outcome = commit_parts(merged, _rows=trip_rows)
    split_log.append({
        'trip_key': tk, 'line_name': original_ln,
        'action': 'stopwise_split' if outcome == 'committed' else 'kept_conflict',
        'reason': f'{len(merged)} groups by 転記の証拠',
        'stops': ' → '.join(r['stop_name'] for _, rs in merged for r in rs),
        'front_trip': ' | '.join(labels),
        'front_stops': ' || '.join(' → '.join(r['stop_name'] for r in rs)
                                   for _, rs in merged),
        'back_trip': '', 'back_stops': '',
    })
    return outcome


def _split_3way_parts(trip_rows, names, lines, b_ab, b_bc):
    """Return a 3-way split of a 3-way combined trip at its 2 junctions ([(sub_line, rows), ...]).
    Only if both junctions are in the trip; otherwise None."""
    if b_ab not in names or b_bc not in names:
        return None
    ai = names.index(b_ab)
    bi = names.index(b_bc)
    if ai >= bi:
        return None  # order reversed
    if ai == 0 or bi == len(names) - 1:
        return None  # at an end
    line_a, line_b, line_c = lines
    return [
        (line_a, trip_rows[:ai + 1]),
        (line_b, trip_rows[ai:bi + 1]),
        (line_c, trip_rows[bi:]),
    ]


# Fix 著 (arrival) row / 發 (departure) row pairs that are different trains in the original, per the actions table
# ------------------------------------------------------------------
# The original sometimes prints a station as a 著 row and a 發 row, so one trip has the same station
# on 2 consecutive rows. On the page images most have neither ＊ nor a terminating line (one stop of
# the same train), but in these places the rows before and after are different trains:
#   - p182 滿鐵安奉線 奉天: transfer mark ＊ at the end of band (3) (奉天->長春->哈爾賓), which reprints
#     trains of the p183 main table -> drop band (3)'s side
#   - p183 上リ 12, 長春 著 ＊7.00: arrival of the 長春-哈爾賓 band, not in any other trip
#     -> keep it as a separate train (key suffix _b)
#   - different columns with the same number in the original (p38 55/不55, p39 25/不25,
#     p185 東支鐵道線 3, 4) -> split into 2 trips (trip_num unchanged)
# ＊ is not in the transcription (only visible in the page image), so the input is an actions table
# (CSV), not a rule. One row = (line_name, direction, trip_num, stop_name, action). Act only if the
# trip has exactly one "arrival-only row -> departure-only row of the same station" pair; if the trip
# is missing, there are 0 or 2+ pairs, the table has 2 rows for the trip, a dropped time is not in any
# other trip, or `_b`/`_c` is taken, leave it and log `a08_refused`.
#   drop_after   ... keep up to the 著 row, drop from the 發 row on
#   drop_before  ... drop from the start to the 著 row, keep from the 發 row on
#   split_after  ... make the 發 row onward a separate trip (key suffix _b)
#   split_before ... make the start through the 著 row a separate trip (key suffix _b)
# Dropped times are checked as in the final dedup: every (station, 著/發, time mod 24h) must remain
# in some trip after the action.
# Default ON. Previous behavior = SPLIT_A08_ACTIONS=0.
# Table path = SPLIT_A08_ACTIONS_PATH (default `data/tables/arrival_departure_rows/actions.csv`).
A08_ACTIONS = os.environ.get('SPLIT_A08_ACTIONS', '1') != '0'
A08_ACTIONS_PATH = os.environ.get('SPLIT_A08_ACTIONS_PATH') or os.path.join(
    BASE_DIR, 'data', 'tables', 'arrival_departure_rows', 'actions.csv')
A08_KINDS = ('drop_after', 'drop_before', 'split_after', 'split_before')
# Apply both "drop front" and "drop back" rows to one trip. The p182 安奉線 table prints, in the same
#   column, a header part 釜山 發, 京城 〃, 安東 著 (bracketed in the station column with page ref "181"
#   and "朝鮮時刻" = excerpt from the Korean line on p181) and a tail 奉天 發, 長春, 哈爾賓 (bracketed,
#   page ref "183,185"). When ON, if all actions for a trip are drop_before/drop_after, apply all
#   (dropped times are checked row by row; skip an action that would leave fewer than 2 rows). Trips
#   that also have a split_* action are skipped.
#   Default ON. Previous behavior (skip trips with 2+ rows) = SPLIT_A08_MULTI_DROP=0.
A08_MULTI_DROP = os.environ.get('SPLIT_A08_MULTI_DROP', '1') == '1'


def _a08_dn(name):
    return _kv_norm(_base_name(name), prefer_new=True)


def _a08_cells(rs):
    """Set of (station, 著/發, time mod 24h)."""
    out = set()
    for r in rs:
        b = _a08_dn(r['stop_name'])
        for col, lab in (('dep_time', '發'), ('arr_time', '著')):
            t = _to_min(r.get(col))
            if t is not None:
                out.add((b, lab, t % 1440))
    return out


def _a08_pairs(rows, stop_name):
    """Positions of the 著 row of each "arrival-only row of stop_name -> departure-only row of the same station" pair in rows (stop_sequence order)."""
    want = _a08_dn(stop_name)
    hits = []
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        if (_a08_dn(a['stop_name']) == want and _a08_dn(b['stop_name']) == want
                and _to_min(a.get('arr_time')) is not None and _to_min(a.get('dep_time')) is None
                and _to_min(b.get('dep_time')) is not None and _to_min(b.get('arr_time')) is None):
            hits.append(i)
    return hits


def _a08_apply(final, split_log):
    """Apply the actions table to final (modified in place). Returns (dropped, split, refused)."""
    with open(A08_ACTIONS_PATH, encoding='utf-8-sig', newline='') as f:
        acts = list(csv.DictReader(f))
    for a in acts:
        if a['処置'] not in A08_KINDS:
            raise SystemExit(f'処置表の「処置」が不明: {a["処置ID"]} {a["処置"]}（{A08_ACTIONS_PATH}）')

    def names(rs):
        return ' → '.join(r['stop_name'] for r in rs)

    def log(a, tk, action, reason, rs, front=('', ()), back=('', ())):
        split_log.append({
            'trip_key': tk, 'line_name': a['line_name'], 'action': action,
            'reason': f'{a["処置ID"]} {a["処置"]}@{a["stop_name"]}: {reason}',
            'stops': names(rs), 'front_trip': front[0], 'front_stops': names(front[1]),
            'back_trip': back[0], 'back_stops': names(back[1]),
        })

    # 1) decide all cut positions first (before modifying final, so actions do not affect each other)
    per_key = defaultdict(int)
    drops_only = defaultdict(lambda: True)   # SPLIT_A08_MULTI_DROP: are all actions for the trip drop_*?
    for a in acts:
        per_key[f'{a["line_name"]}__{a["direction"]}__{a["trip_num"]}'] += 1
        if not a['処置'].startswith('drop_'):
            drops_only[f'{a["line_name"]}__{a["direction"]}__{a["trip_num"]}'] = False
    plans = []
    n_refused = 0
    for a in acts:
        tk = f'{a["line_name"]}__{a["direction"]}__{a["trip_num"]}'
        rows = sorted(final.get(tk, []), key=lambda r: int(r['stop_sequence']))
        hits = _a08_pairs(rows, a['stop_name']) if rows else []
        why = ('トリップが無い' if not rows else
               '同じトリップに処置が 2 行以上ある' if per_key[tk] > 1 and not (A08_MULTI_DROP and drops_only[tk]) else
               f'著だけの行 → 發だけの行 が {len(hits)} 組' if len(hits) != 1 else None)
        if why:
            n_refused += 1
            log(a, tk, 'a08_refused', why, rows)
            continue
        i = hits[0]
        if a['処置'] in ('drop_after', 'split_after'):
            keep, other = rows[:i + 1], rows[i + 1:]
        else:
            other, keep = rows[:i + 1], rows[i + 1:]
        plans.append((a, tk, rows, keep, other))

    # 2) do dropped times remain in some trip after the actions? (if not, do not drop)
    dropped = {id(r) for a, tk, rows, keep, other in plans
               if a['処置'].startswith('drop_') for r in other}
    remain = set()
    for rs in final.values():
        remain |= _a08_cells([r for r in rs if id(r) not in dropped])

    n_drop = n_split = 0
    inserts = {}
    gone = {}   # rows dropped per trip (a second drop on the same trip builds on the first)
    for a, tk, rows, keep, other in plans:
        kind = a['処置']
        if kind.startswith('drop_'):
            lost = sorted(_a08_cells(other) - remain)
            if lost:
                n_refused += 1
                log(a, tk, 'a08_refused', '落とす時刻がほかのトリップに無い: ' + '・'.join(
                    '%s%s%02d:%02d' % (b, lab, t // 60, t % 60) for b, lab, t in lost), rows)
                continue
            g = gone.get(tk, set()) | {id(r) for r in other}
            left = [r for r in rows if id(r) not in g]   # same as keep when there is one action
            if A08_MULTI_DROP and len(left) < 2:
                n_refused += 1
                log(a, tk, 'a08_refused', '残る行が 2 行未満', rows)
                continue
            gone[tk] = g
            final[tk] = [dict(r, stop_sequence=str(k + 1)) for k, r in enumerate(left)]
            n_drop += 1
            log(a, tk, 'a08_' + kind,
                ('原本の乗換印 ＊＝別の列車の重複掲載を落とす（落とす時刻はすべてほかのトリップに在る）'
                 if '參照頁' not in (a.get('原本の根拠') or '') else
                 '原本の括弧と參照頁＝ほかの表からの抜き書きを落とす（落とす時刻はすべてほかのトリップに在る）'),
                rows, front=(tk, keep), back=('(落とした)', other))
            continue
        nk = next((f'{tk}{s}' for s in ('_b', '_c') if f'{tk}{s}' not in final), None)
        if nk is None:
            n_refused += 1
            log(a, tk, 'a08_refused', f'{tk} の _b・_c がどちらも既に在る', rows)
            continue
        suffix = nk[len(tk):]
        final[tk] = [dict(r, stop_sequence=str(k + 1)) for k, r in enumerate(keep)]
        inserts[tk] = (nk, [dict(r, gtfs_trip_key=nk, trip_num=r['trip_num'] + suffix,
                                 stop_sequence=str(k + 1)) for k, r in enumerate(other)])
        n_split += 1
        after = kind == 'split_after'
        log(a, tk, 'a08_' + kind, '原本では別の列車＝2 本に分ける', rows,
            front=(tk, keep) if after else (nk, other),
            back=(nk, other) if after else (tk, keep))
    if inserts:
        # put each new trip right after its original (keeps output order)
        items = list(final.items())
        final.clear()
        for k, v in items:
            final[k] = v
            if k in inserts:
                final[inserts[k][0]] = inserts[k][1]
    return n_drop, n_split, n_refused


# Merge a 著 (arrival) row and a 發 (departure) row into one stop
# ------------------------------------------------------------------
# The "arrival-only row -> departure-only row of the same station" pairs left after the actions table
# have neither ＊ nor a terminating line on the page image: one stop of the same train printed on 2
# rows. Two consecutive rows of the same station in GTFS give a zero-distance segment and a double
# stop, so merge them into one row with 著 from row 1 and 發 from row 2 (no time is dropped; the
# (station, 著/發, time) set is unchanged).
# ＊ is not in the transcription, so merge only pairs listed in the merge table
# `data/tables/arrival_departure_rows/merges.csv`, not by rule. Unread pairs are untouched and logged
# as `a08_unread` (read the original for new pairs).
# Condition: the trip has exactly one such pair whose dwell (發 - 著) equals the table's (keys,
# sequence numbers and day counting may change, but the dwell minutes do not).
# Default ON. Previous behavior = SPLIT_A08_MERGE=0.
# Table path = SPLIT_A08_MERGE_PATH (default `data/tables/arrival_departure_rows/merges.csv`).
A08_MERGE = os.environ.get('SPLIT_A08_MERGE', '1') != '0'
A08_MERGE_PATH = os.environ.get('SPLIT_A08_MERGE_PATH') or os.path.join(
    BASE_DIR, 'data', 'tables', 'arrival_departure_rows', 'merges.csv')


def _renumber_map():
    """If the renumbering table (EXTRACT_RENUMBER_TABLE of extract_stop_times.py) was applied at
    extraction, return {(source_sheet, old number): (new number, start station)}; else empty.
    Read from _extract_flags.json copied by integration (so extract and split cannot disagree if an
    environment variable is not passed)."""
    p = os.path.join(os.path.dirname(INTEGRATED), '_extract_flags.json')
    if not os.path.exists(p):
        return {}
    import json
    with open(p, encoding='utf-8') as f:
        flags = json.load(f)
    if flags.get('EXTRACT_RENUMBER_TABLE') != 1:
        return {}
    path = os.path.join(BASE_DIR, flags.get('renumber_table') or os.path.join('data', 'tables', 'renumbering.csv'))
    out = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if (r.get('改番ID') or '').strip():
                out[(r['source_sheet'].strip(), r['元の番号'].strip())] = (
                    r['新しい番号'].strip(), (r.get('起点の駅') or '').strip())
    return out


def _a08_merge(final, split_log):
    """Merge the pairs in the merge table into one row (final modified in place). Returns (merged, refused, unread)."""
    with open(A08_MERGE_PATH, encoding='utf-8-sig', newline='') as f:
        items = list(csv.DictReader(f))

    def log(tk, line, action, reason, stop):
        split_log.append({'trip_key': tk, 'line_name': line, 'action': action, 'reason': reason,
                          'stops': stop, 'front_trip': '', 'front_stops': '', 'back_trip': '', 'back_stops': ''})

    def n_pairs(tk, it):
        rows = sorted(final.get(tk, []), key=lambda r: int(r['stop_sequence']))
        want = int(it['停車（分）'])
        return len([i for i in _a08_pairs(rows, it['stop_name'])
                    if _to_min(rows[i + 1]['dep_time']) - _to_min(rows[i]['arr_time']) == want])

    renum = _renumber_map()
    by_key = defaultdict(list)
    for it in items:
        tk = f'{it["line_name"]}__{it["direction"]}__{it["trip_num"]}'
        rn = renum.get(((it.get('シート') or '').strip(), str(it['trip_num']).strip())) if renum else None
        if rn and n_pairs(tk, it) == 0:
            # stops renumbered by the renumbering table: look up under the new number's key; do not merge a pair at the renumbering boundary
            tk2 = f'{it["line_name"]}__{it["direction"]}__{rn[0]}'
            if n_pairs(tk2, it) == 1:
                tk = tk2
            elif rn[1] and _a08_dn(it['stop_name']) == _a08_dn(rn[1]):
                log(tk, it['line_name'], 'a08_merge_boundary',
                    f'{it["まとめID"]} {it["stop_name"]}: 改番表で {it["trip_num"]}→{rn[0]} に分かれる境目'
                    f'（著は {it["trip_num"]}・發は {rn[0]}）＝まとめない', it['stop_name'])
                continue
        by_key[tk].append(it)

    n_merged = n_refused = 0
    for tk, its in by_key.items():
        rows = sorted(final.get(tk, []), key=lambda r: int(r['stop_sequence']))
        at = {}
        for it in its:
            want = int(it['停車（分）'])
            hits = [i for i in _a08_pairs(rows, it['stop_name'])
                    if _to_min(rows[i + 1]['dep_time']) - _to_min(rows[i]['arr_time']) == want]
            why = ('トリップが無い' if not rows else
                   f'停車 {want} 分の 著だけの行 → 發だけの行 が {len(hits)} 組' if len(hits) != 1 else
                   '同じ組がまとめ表に 2 行ある' if hits[0] in at else None)
            if why:
                n_refused += 1
                log(tk, it['line_name'], 'a08_merge_refused', f'{it["まとめID"]} {it["stop_name"]}: {why}',
                    it['stop_name'])
                continue
            at[hits[0]] = it
        if not at:
            continue
        out = []
        skip = False
        for i, r in enumerate(rows):
            if skip:
                skip = False
                continue
            r2 = dict(r, stop_sequence=str(len(out) + 1))
            if i in at:
                nxt = rows[i + 1]
                r2['dep_time'] = nxt['dep_time']
                skip = True
                n_merged += 1
                log(tk, r['line_name'], 'a08_merge',
                    f'{at[i]["まとめID"]} {r["stop_name"]}: 著{r["arr_time"]}（seq {r["stop_sequence"]}）＋'
                    f'發{nxt["dep_time"]}（seq {nxt["stop_sequence"]}）＝1 回の停車（{at[i]["停車（分）"]} 分）',
                    r['stop_name'])
            out.append(r2)
        final[tk] = out

    # "arrival-only -> departure-only" pairs in neither the merge table nor the actions table: ＊ not yet read in the original (untouched)
    acted = set()
    if os.path.exists(A08_ACTIONS_PATH):
        with open(A08_ACTIONS_PATH, encoding='utf-8-sig', newline='') as f:
            for a in csv.DictReader(f):
                acted.add((f'{a["line_name"]}__{a["direction"]}__{a["trip_num"]}', _a08_dn(a['stop_name'])))
    n_unread = 0
    for tk, rs in final.items():
        rs = sorted(rs, key=lambda r: int(r['stop_sequence']))
        for i in range(len(rs) - 1):
            a, b = rs[i], rs[i + 1]
            if _a08_pairs(rs[i:i + 2], a['stop_name']) and (tk, _a08_dn(a['stop_name'])) not in acted:
                n_unread += 1
                log(tk, a['line_name'], 'a08_unread',
                    f'{a["stop_name"]}: 著{a["arr_time"]}→發{b["dep_time"]} がまとめ表にも処置表にも無い'
                    '＝原本の ＊ を読んでいない（まとめない）', a['stop_name'])
    return n_merged, n_refused, n_unread


# Write 著/發 found only in combined-line bands into blanks of the same-numbered detail trip.
#   With INTEGRATE_COMBINED_FILL_BLANKS=1, integration (integrate_stop_times.py) saves the band values
#   to `combined_band_cells.csv`. Here, after all dedup and weaving, values not found anywhere under
#   the same number in the output are written into empty fields of the same-numbered trip of a
#   component line. It never affects which trips are kept or dropped (done last); only blank cells change.
#   Conditions: (1) the same number and (station, field, time mod 24h) is not in the output; (2) the
#   same-numbered component trip has exactly one row for the station, with this field empty and a time
#   in the other field; (3) dwell 0-60 minutes (day aligned to the other field); (4) never write 發 on
#   a trip's last row or 著 on its first row (beyond the terminus / before the origin can be a train with
#   another number, e.g. 817 -> 835 at 平).
#   Default ON. Previous behavior = INTEGRATE_COMBINED_FILL_BLANKS=0.
FILL_BLANKS = os.environ.get('INTEGRATE_COMBINED_FILL_BLANKS', '1') != '0'


def _fb_line_components(line):
    comps = set()
    for part in re.split(r'[及、・]', line or ''):
        part = part.strip()
        if part:
            comps |= {_kv_norm(part, prefer_new=True), _kv_norm(part + '本線', prefer_new=True),
                      _kv_norm(part + '線', prefer_new=True)}
    comps.discard(_kv_norm(line or '', prefer_new=True))
    return comps


def _fb_base(num):
    return re.sub(r'_[a-z]$', '', str(num or '').strip())


def _fill_band_blanks(final, split_log, path):
    """Returns the number of cells (written, skipped)."""
    if not os.path.exists(path):
        print(f'警告: 帯の値の控えが無い（{path}）＝空欄への書き込みは見送り')
        return 0, 0
    by_num = defaultdict(list)          # base number -> [(key, rows)]
    have = set()                        # (number, station, field, time mod 24h)
    for key, rs in final.items():
        n = _fb_base(rs[0].get('trip_num'))
        by_num[n].append((key, rs))
        for r in rs:
            b = _a08_dn(r['stop_name'])
            for col in ('arr_time', 'dep_time'):
                t = _to_min(r.get(col))
                if t is not None:
                    have.add((n, b, col, t % 1440))
    cells = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for c in csv.DictReader(f):
            t = _to_min(c['time'])
            if t is None or str(c['trip_num']).startswith('U'):
                continue
            cells.append((c['line_name'], _fb_base(c['trip_num']), _a08_dn(c['stop_name']), c['field'], t % 1440))
    n_done = n_skip = 0
    for line, n, st, col, t in sorted(set(cells)):
        if (n, st, col, t) in have:
            continue
        comps = _fb_line_components(line)
        other = 'dep_time' if col == 'arr_time' else 'arr_time'
        hits = []
        for key, rs in by_num.get(n, ()):
            if _kv_norm(rs[0]['line_name'], prefer_new=True) not in comps:
                continue
            for i, r in enumerate(rs):
                if _a08_dn(r['stop_name']) == st:
                    hits.append((key, rs, i, r))
        reason = ''
        if len(hits) != 1:
            reason = f'成分の線の同じ番号にその駅の行が {len(hits)} 行'
        else:
            key, rs, i, r = hits[0]
            o = _to_min(r.get(other))
            if r.get(col) or o is None:
                reason = 'その欄が空いていない・反対の欄が空'
            else:
                d = ((o - t) if col == 'arr_time' else (t - o)) % 1440
                new = o - d if col == 'arr_time' else o + d
                if d > 60 or new < 0:
                    reason = f'停車 {d} 分'
                elif (col == 'dep_time' and i == len(rs) - 1) or (col == 'arr_time' and i == 0):
                    reason = '終点の發・始発の著'
        lab = '著' if col == 'arr_time' else '發'
        if reason:
            n_skip += 1
            split_log.append({'trip_key': f'{line}__{n}', 'line_name': line, 'action': 'fill_blank_refused',
                              'reason': f'{st}{lab}{t // 60:02d}:{t % 60:02d}: {reason}', 'stops': '',
                              'front_trip': '', 'front_stops': '', 'back_trip': '', 'back_stops': ''})
            continue
        r[col] = '%02d:%02d' % (new // 60, new % 60)
        have.add((n, st, col, t))
        n_done += 1
        split_log.append({'trip_key': key, 'line_name': rs[0]['line_name'], 'action': 'fill_blank',
                          'reason': f'帯 {line} にしか無い {st}{lab}{r[col]} を空欄へ',
                          'stops': ' → '.join(x['stop_name'] for x in rs),
                          'front_trip': '', 'front_stops': '', 'back_trip': '', 'back_stops': ''})
    return n_done, n_skip


# Drop duplicate trips that are wholly contained in others
#   The earlier dedup steps (in integration, the final dedup, SPLIT_PART_DIRECTION) only look at
#   "another line name, same direction" or numbered components, so these 2 types are dropped here:
#   R1 unnumbered band (trip_num is integration's provisional key U...): all its (station, field,
#      time) are in one numbered trip of the same line name (any direction; connecting bands are
#      transcribed with the table heading's direction, so the label can be reversed), or its front and
#      back halves are each in one of 2 numbered trips of the same line and direction (a transfer
#      guide: 2 trains in one column). E.g. the p137 常磐線 band (822), the p121 信越本線 band (1 + 103 etc.).
#   R2 generic line names in connection tables: 2 trips with the same number (ignoring suffixes like
#      "_b") and different line names, one wholly contained in the other (any direction). Keep the
#      trip from the dedicated table (one line name in that table) and drop the band/connection-table
#      trip. Values missing from the kept trip (e.g. a 著 printed only in the connection table) are
#      first woven into empty fields of that station (if that is impossible, do not drop).
#      E.g. 支那國有鐵道線 in p5 "日本・支那間聯絡" vs 京奉線 and 膠濟本線 on p184.
#   Drop only if every (station, field, time) of the dropped trip is in the kept trip, so no value is
#   lost (only the provisional unnumbered key disappears). Two numbered trips with different numbers
#   (coupled or through trains, e.g. 總武本線 7/107) and two unnumbered trips (separate sailings of a
#   dated route) are not dropped.
#   Default ON. Previous behavior = SPLIT_CONTAINED_DEDUP=0. Logged in split_trips_report.csv as
#   contained_dedup_r1a / r1b / r2 and contained_weave.
CONTAINED_DEDUP = os.environ.get('SPLIT_CONTAINED_DEDUP', '1') == '1'


def _cd_table(sheet):
    m = re.match(r'(p\d+)_tb(\d+)', sheet or '')
    return (m.group(1), m.group(2)) if m else None


def _cd_base_num(num):
    return re.sub(r'_[a-z]+$', '', num or '')


def _cd_cells(rs):
    """List of (base station name, field, time) (time in raw minutes)."""
    out = []
    for i, r in enumerate(rs):
        st = _kv_norm(_base_name(r['stop_name']), prefer_new=True)
        for col, lab in (('arr_time', '著'), ('dep_time', '發')):
            t = _to_min(r.get(col))
            if t is not None:
                out.append((i, st, lab, t))
    return out


def _cd_contained(cells_k, rs2):
    """Are all cells_k (from _cd_cells) in trip rs2 (with the same multiple-of-24h shift at every station)?
    Returns the shift if so, else None."""
    idx = defaultdict(list)
    for (_, st, lab, t) in _cd_cells(rs2):
        idx[(st, lab)].append(t)
    offs = None
    for (_, st, lab, t) in cells_k:
        cand = {x - t for x in idx.get((st, lab), ()) if (x - t) % 1440 == 0}
        offs = cand if offs is None else (offs & cand)
        if not offs:
            return None
    return min(offs) if offs else None


def _cd_weave(rs_keep, rs_drop, off):
    """Plan to write (station, field, time) found only in rs_drop into empty fields of the same station
    in rs_keep (only if all can be written). off = rs_keep time - rs_drop time (multiple of 24 hours).
    Returns [(row, field, 'HH:MM')] or None."""
    have = {(st, lab, t % 1440) for (_, st, lab, t) in _cd_cells(rs_keep)}
    byst = defaultdict(list)
    for i, r in enumerate(rs_keep):
        byst[_kv_norm(_base_name(r['stop_name']), prefer_new=True)].append(i)
    plan = []
    for (_, st, lab, t) in _cd_cells(rs_drop):
        if (st, lab, t % 1440) in have:
            continue
        rows_i = byst.get(st, [])
        if len(rows_i) != 1:
            return None
        i = rows_i[0]
        r = rs_keep[i]
        col, other = ('arr_time', 'dep_time') if lab == '著' else ('dep_time', 'arr_time')
        if r.get(col):
            return None
        t2 = t + off
        ref = _to_min(r.get(other))
        if t2 < 0 or ref is None:
            return None
        if lab == '著' and not (0 <= ref - t2 <= 60):
            return None
        if lab == '發' and not (0 <= t2 - ref <= 60):
            return None
        prev = [v for x in rs_keep[:i] for v in (_to_min(x.get('arr_time')), _to_min(x.get('dep_time'))) if v is not None]
        nxt = [v for x in rs_keep[i + 1:] for v in (_to_min(x.get('arr_time')), _to_min(x.get('dep_time'))) if v is not None]
        if (prev and t2 < max(prev)) or (nxt and t2 > min(nxt)):
            return None
        plan.append((r, col, '%02d:%02d' % (t2 // 60, t2 % 60)))
    return plan


# R3 = bands wholly contained across same-numbered trips of other lines, or via the same station under
#   another name. R1 and R2 drop only when contained in one trip with the same station names, so these
#   reprints of the same train are dropped here:
#   R3a a trip whose every (station, field, time) is spread over 2+ trips with the same number (ignoring
#       suffixes) and different line names (p5 connection table 朝鮮線 1, 2, 7, 8 = 滿鐵安奉線 + 京釜本線;
#       鹿兒島及長崎本線 101 and 5 others = 長崎本線 + 鹿兒島本線; p133 東海道及北陸本線 503; p122 兩毛線
#       141, 143). It summarizes a cross-line through band, so it is dropped even from a dedicated table.
#   R3b a band/connection-table trip wholly contained in one same-numbered trip of another line when the
#       same station printed under another name counts as the same (p5 支那國有鐵道線 北京<->漢口 = p184
#       京漢線 北京前門<->漢口大智門). Drop only if band-only values can be woven into empty fields of
#       the kept trip (p5 支那國有鐵道線 天津<->浦口, 濟南府 著; p184 津浦線 has only 發).
#   "Same station" = same name after removing tags and unifying old/new kanji, or coordinates in the
#   coordinate tables within SPLIT_CONTAINED_DEDUP_PLACE_KM (default 0.5 km). The coordinate tables are
#   used only to tell whether 2 differently named stations are the same place (not as evidence of a
#   station's line).
#   In R3a too, values in no other trip must be woven into an empty field of a partner trip that has the
#   station (the p122 兩毛線 band's 新前橋 著; the 上越南線 trip has only 發). Numbers and times must all
#   match, so another train is never dropped.
#   No value is lost (trips with values that cannot be woven are kept). But values of a trip dropped by
#   R3b's "same station under another name" appear under the kept trip's names (p184 北京前門, 漢口大智門).
#   To match by name only, set SPLIT_CONTAINED_DEDUP_PLACE_KM=0.
#   Default ON. Previous behavior = SPLIT_CONTAINED_DEDUP_MULTI=0.
#   Logged in split_trips_report.csv as contained_dedup_r3a / r3b, contained_weave_r3a / r3b and
#   contained_keep_r3a (bands kept by the riding condition).
CONTAINED_DEDUP_MULTI = os.environ.get('SPLIT_CONTAINED_DEDUP_MULTI', '1') == '1'
CDM_PLACE_KM = float(os.environ.get('SPLIT_CONTAINED_DEDUP_PLACE_KM', '0.5'))
_CDM_PLACE_CACHE = {}
# R3a riding condition: even if all band values are in other trips, only the band may represent a
#   through ride across lines (e.g. 東北本線及常磐線 801: 常磐線 801 ends at 原ノ町 and 東北本線 801 jumps
#   上野->仙臺, so 原ノ町->仙臺 exists only in the band). So R3a drops only if every adjacent pair of
#   main-table trips, in band order, is 継続_確定 (confirmed continuation) in the through-train link
#   judgments (hand-made, CDM_VERDICTS) and at a station where both stop the later trip departs after
#   the earlier one arrives (within 180 minutes, same day). The judgments are hand-made input, so reading
#   them here is not circular (derived tables are not read).
CDM_VERDICTS = os.environ.get('SPLIT_CONTAINED_DEDUP_VERDICTS_PATH') or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'tables', 'through_trains', 'link_judgments.csv')
_CDM_CONT = None


def _cdm_continuations():
    global _CDM_CONT
    if _CDM_CONT is None:
        _CDM_CONT = set()
        if os.path.exists(CDM_VERDICTS):
            with open(CDM_VERDICTS, encoding='utf-8-sig', newline='') as f:
                for r in csv.DictReader(f):
                    if r.get('verdict') == '継続_確定':
                        _CDM_CONT.add((r['from_trip_key'], r['to_trip_key']))
    return _CDM_CONT


def _cdm_chain_ok(cT, final, used):
    """R3a riding condition. Returns (ok, reason)."""
    first = {}
    for k2 in used:
        got, _ = _cdm_cover(cT, final[k2])
        if got:
            first[k2] = min(cT[j][0] for j in got)
    order = sorted(first, key=lambda k2: (first[k2], k2))
    cont = _cdm_continuations()
    for a, b in zip(order, order[1:]):
        if (a, b) not in cont and (b, a) not in cont:
            return False, f'{a} と {b} の乗り継ぎが物理列車の判定表で 継続_確定 でない'
        ra, rb = final[a], final[b]
        ok = False
        for i, x in enumerate(ra):
            if i == 0:
                continue
            ta = _to_min(x.get('arr_time')) if x.get('arr_time') else _to_min(x.get('dep_time'))
            for k, y in enumerate(rb):
                if k == len(rb) - 1 or ta is None:
                    continue
                tb = _to_min(y.get('dep_time')) if y.get('dep_time') else _to_min(y.get('arr_time'))
                if tb is not None and _cdm_same(x['stop_name'], x['line_name'], y['stop_name'], y['line_name']) \
                        and (tb - ta) % 1440 <= 180:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            return False, f'{a} から {b} へ乗り継げる驛が無い（帯だけが通しの乗車を表している）'
    return True, ''


def _cdm_place(name, line):
    key = (name, line)
    if key not in _CDM_PLACE_CACHE:
        # Decide "same station, different name" with the coordinate tables (data/knowledge/places/).
        # Table inconsistencies and queries missing from the stop-place table (AGENT_KNOWN_STRICT=1) are not
        # swallowed (no exception is caught here).
        import agent_knowledge as _ak
        v = _ak.lookup(name, line)
        _CDM_PLACE_CACHE[key] = (float(v[0]), float(v[1])) if v else None
    return _CDM_PLACE_CACHE[key]


def _cdm_same(a_name, a_line, b_name, b_line):
    if _kv_norm(_base_name(a_name), prefer_new=True) == _kv_norm(_base_name(b_name), prefer_new=True):
        return True
    if CDM_PLACE_KM <= 0:
        return False
    pa, pb = _cdm_place(_base_name(a_name), a_line), _cdm_place(_base_name(b_name), b_line)
    if not (pa and pb):
        return False
    p = math.pi / 180
    x = math.sin((pb[0] - pa[0]) * p / 2) ** 2 + math.cos(pa[0] * p) * math.cos(pb[0] * p) * math.sin((pb[1] - pa[1]) * p / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x)) <= CDM_PLACE_KM


def _cdm_cells(rs):
    """[(row index, station, line, field, time)]"""
    out = []
    for i, r in enumerate(rs):
        for col, lab in (('arr_time', '著'), ('dep_time', '發')):
            t = _to_min(r.get(col))
            if t is not None:
                out.append((i, r['stop_name'], r['line_name'], lab, t))
    return out


def _cdm_cover(cT, rs2):
    """Indices of cT found in rs2 and the shift used (multiple of 24 hours, the one with the most matches)."""
    c2 = _cdm_cells(rs2)
    offs = defaultdict(set)
    for j, (_, st, ln, lab, t) in enumerate(cT):
        for (_, st2, ln2, lab2, t2) in c2:
            if lab2 == lab and (t2 - t) % 1440 == 0 and _cdm_same(st, ln, st2, ln2):
                offs[t2 - t].add(j)
    if not offs:
        return set(), None
    off = max(offs, key=lambda o: (len(offs[o]), -abs(o), -o))
    return offs[off], off


def _cdm_weave(rs_keep, cells_rest, off):
    """Plan to write cells_rest (in _cdm_cells form) into empty fields of the same station in rs_keep (only if all fit)."""
    plan = []
    for (_, st, ln, lab, t) in cells_rest:
        rows_i = [i for i, r in enumerate(rs_keep) if _cdm_same(st, ln, r['stop_name'], r['line_name'])]
        if len(rows_i) != 1:
            return None
        i = rows_i[0]
        r = rs_keep[i]
        col, other = ('arr_time', 'dep_time') if lab == '著' else ('dep_time', 'arr_time')
        if r.get(col):
            return None
        # Never write 著 at the origin or 發 at the terminus (unused by route search, so the connection time
        # would be lost; same rule as INTEGRATE_COMBINED_FILL_BLANKS. E.g. 綾部 著 8:33 of band 山陰及東海道線 346
        # goes to 舞鶴線 346, which ends at 綾部, not to 山陰本線 346, which starts there).
        if (lab == '著' and i == 0) or (lab == '發' and i == len(rs_keep) - 1):
            return None
        t2 = t + off
        ref = _to_min(r.get(other))
        if t2 < 0 or ref is None:
            return None
        if lab == '著' and not (0 <= ref - t2 <= 60):
            return None
        if lab == '發' and not (0 <= t2 - ref <= 60):
            return None
        prev = [v for x in rs_keep[:i] for v in (_to_min(x.get('arr_time')), _to_min(x.get('dep_time'))) if v is not None]
        nxt = [v for x in rs_keep[i + 1:] for v in (_to_min(x.get('arr_time')), _to_min(x.get('dep_time'))) if v is not None]
        if (prev and t2 < max(prev)) or (nxt and t2 > min(nxt)):
            return None
        plan.append((r, col, '%02d:%02d' % (t2 // 60, t2 % 60)))
    return plan


def _table_lines(rows):
    """Table (page, tb) -> set of line_names in that table."""
    tbl_lines = defaultdict(set)
    for r in rows:
        t = _cd_table(r.get('source_sheet'))
        if t is not None:
            tbl_lines[t].add(r['line_name'])
    return tbl_lines


def _table_lines_from_extract(rows):
    """Read line names per table from table_lines.csv written by integration (counted over all extracted
    records, as for INTEGRATE_CROSSLINE_EQ in integration). If missing (older integration output), count
    from this step's input and say so."""
    p = os.path.join(os.path.dirname(INTEGRATED), 'table_lines.csv')
    if not os.path.exists(p):
        print(f'  ★ {p} が無い＝専用表を分割の段の入力で数える（統合を回し直すと抽出の段で数える）')
        return _table_lines(rows)
    tbl_lines = defaultdict(set)
    for r in csv.DictReader(open(p, encoding='utf-8')):
        tbl_lines[(r['page'], r['tb'])].add(r['line_name'])
    return tbl_lines


# Decide dedicated tables from the transcription before splitting. Counting "dedicated table = only one
# line_name in that table" from trips left after splitting and dedup makes a connection table look
# dedicated once its other bands have been dropped, so a band that should go remains (p5 connection table
# 支那國有鐵道線). Read table_lines.csv, counted by integration over all extracted records (by the
# transcription's structure, as INTEGRATE_CROSSLINE_EQ in integration).
# Default ON. Previous behavior (count from remaining trips) = SPLIT_CD_TABLE_FROM_INPUT=0.
CD_TABLE_FROM_INPUT = os.environ.get('SPLIT_CD_TABLE_FROM_INPUT', '1') != '0'


def _contained_dedup(final, split_log, input_tbl_lines=None):
    """Drop wholly contained trips by R1 and R2. Returns counts {'r1a','r1b','r2','weave'}."""
    tbl_lines = input_tbl_lines if input_tbl_lines is not None else _table_lines(
        r for rs in final.values() for r in rs)

    def dedicated(rs):
        tabs = {_cd_table(r.get('source_sheet')) for r in rs}
        tabs.discard(None)
        return bool(tabs) and all(len(tbl_lines[t]) == 1 for t in tabs)

    def lnorm(s):
        return _kv_norm(s or '', prefer_new=True)

    by_line = defaultdict(list)
    for key, rs in final.items():
        if rs:
            by_line[lnorm(rs[0]['line_name'])].append(key)
    by_num = defaultdict(list)
    for key, rs in final.items():
        if rs and not rs[0]['trip_num'].startswith('U'):
            by_num[_cd_base_num(rs[0]['trip_num'])].append(key)

    counts = {'r1a': 0, 'r1b': 0, 'r2': 0, 'weave': 0}
    dropped = set()

    def log(key, rs, action, reason):
        split_log.append({'trip_key': key, 'line_name': rs[0]['line_name'], 'action': action, 'reason': reason,
                          'stops': ' → '.join(r['stop_name'] for r in rs),
                          'front_trip': '', 'front_stops': '', 'back_trip': '', 'back_stops': ''})

    order = sorted(final.keys(), key=lambda k: (len(_cd_cells(final[k])), k))
    for key in order:
        if key in dropped:
            continue
        rs = final[key]
        cells = _cd_cells(rs)
        if len(cells) < 2 or len({st for (_, st, _l, _t) in cells}) < 2:
            continue
        num = rs[0]['trip_num']
        line = lnorm(rs[0]['line_name'])
        if num.startswith('U'):
            # R1a: all in one numbered trip of the same line name (any direction)
            hit = None
            for k2 in sorted(by_line[line]):
                if k2 == key or k2 in dropped or final[k2][0]['trip_num'].startswith('U'):
                    continue
                if _cd_contained(cells, final[k2]) is not None:
                    hit = k2
                    break
            if hit:
                log(key, rs, 'contained_dedup_r1a', f'番号なしの帯の (駅,欄,時刻) がすべて {hit} に在る')
                dropped.add(key)
                counts['r1a'] += 1
                continue
            # R1b: front and back halves each in a numbered trip of the same line and direction (transfer guide)
            d = rs[0]['direction']
            same = [k2 for k2 in sorted(by_line[line]) if k2 != key and k2 not in dropped
                    and final[k2][0]['direction'] == d and not final[k2][0]['trip_num'].startswith('U')]
            for cut in range(1, len(rs)):
                pre = [c for c in cells if c[0] < cut]
                post = [c for c in cells if c[0] >= cut]
                if len(pre) < 2 or not post:
                    continue
                xs = [k2 for k2 in same if _cd_contained(pre, final[k2]) is not None]
                ys = [k2 for k2 in same if _cd_contained(post, final[k2]) is not None]
                pair = next(((x, y) for x in xs for y in ys if x != y), None)
                if pair:
                    log(key, rs, 'contained_dedup_r1b',
                        f'乗りつぎ案内＝{rs[cut - 1]["stop_name"]} までは {pair[0]}・{rs[cut]["stop_name"]} からは {pair[1]} に全部在る')
                    dropped.add(key)
                    counts['r1b'] += 1
                    break
            continue
        # R2: all in a same-numbered trip with a different line name (any direction)
        base = _cd_base_num(num)
        for k2 in sorted(by_num.get(base, [])):
            if k2 == key or k2 in dropped:
                continue
            rs2 = final[k2]
            if lnorm(rs2[0]['line_name']) == line:
                continue
            off = _cd_contained(cells, rs2)
            if off is None:
                continue
            ded_k, ded_2 = dedicated(rs), dedicated(rs2)
            if not ded_k:
                log(key, rs, 'contained_dedup_r2', f'番号が同じ別の線名の便 {k2} に (駅,欄,時刻) がすべて在る（こちらは帯・聯絡表）')
                dropped.add(key)
                counts['r2'] += 1
                break
            if ded_k and not ded_2:
                plan = _cd_weave(rs, rs2, -off)
                if plan is None:
                    continue
                for (r, col, v) in plan:
                    r[col] = v
                    counts['weave'] += 1
                    log(key, rs, 'contained_weave', f'{k2}（帯・聯絡表）にだけ在る {r["stop_name"]}{"著" if col == "arr_time" else "發"}{v} を空欄へ')
                log(k2, rs2, 'contained_dedup_r2', f'番号が同じ専用表の便 {key} に (駅,欄,時刻) がすべて在る（編み込み {len(plan)}）')
                dropped.add(k2)
                counts['r2'] += 1
                break
        if not CONTAINED_DEDUP_MULTI or key in dropped:
            continue
        # R3（SPLIT_CONTAINED_DEDUP_MULTI）
        cT = _cdm_cells(rs)
        cands = [k2 for k2 in sorted(by_num.get(base, [])) if k2 != key and k2 not in dropped
                 and lnorm(final[k2][0]['line_name']) != line]
        # R3a: all spread over 2+ trips of other line names (values in none of them only if they can be woven into an empty field of a partner trip with that station)
        cover, used, offs = set(), [], {}
        for k2 in cands:
            got, off2 = _cdm_cover(cT, final[k2])
            if got - cover:
                cover |= got
                used.append(k2)
                offs[k2] = off2
        if used and len({lnorm(final[k2][0]['line_name']) for k2 in used}) >= 2:
            plan_all = []
            for j, c in enumerate(cT):
                if j in cover:
                    continue
                pl = next((pl for k2 in used for pl in [_cdm_weave(final[k2], [c], offs[k2])] if pl), None)
                if pl is None:
                    plan_all = None
                    break
                plan_all.extend(pl)
            chain_ok, chain_why = _cdm_chain_ok(cT, final, used) if plan_all is not None else (True, '')
            if plan_all is not None and not chain_ok:
                log(key, rs, 'contained_keep_r3a', f'値はすべて {"・".join(used)} に在る（編み込みも可）が落とさない＝{chain_why}')
                counts['keep_r3a'] = counts.get('keep_r3a', 0) + 1
            elif plan_all is not None:
                for (r, col, v) in plan_all:
                    r[col] = v
                    counts['weave_r3'] = counts.get('weave_r3', 0) + 1
                    log(key, rs, 'contained_weave_r3a', f'{key}（帯・聯絡表）にだけ在る {r["stop_name"]}{"著" if col == "arr_time" else "發"}{v} を空欄へ')
                log(key, rs, 'contained_dedup_r3a', f'番号が同じ別の線名の便 {"・".join(used)} にまたがって (驛,欄,時刻) がすべて在る（編み込み {len(plan_all)}）')
                dropped.add(key)
                counts['r3a'] = counts.get('r3a', 0) + 1
                continue
        # R3b: counting the same station under another name as the same, a band/connection-table trip is all in one trip (band-only values only if they can be woven)
        if dedicated(rs):
            continue
        for k2 in cands:
            rs2 = final[k2]
            got, off = _cdm_cover(cT, rs2)
            if not got:
                continue
            rest = [c for j, c in enumerate(cT) if j not in got]
            plan = _cdm_weave(rs2, rest, off) if rest else []
            if plan is None:
                continue
            for (r, col, v) in plan:
                r[col] = v
                counts['weave_r3'] = counts.get('weave_r3', 0) + 1
                log(k2, rs2, 'contained_weave_r3b', f'{key}（帯・聯絡表）にだけ在る {r["stop_name"]}{"著" if col == "arr_time" else "發"}{v} を空欄へ')
            log(key, rs, 'contained_dedup_r3b', f'番号が同じ別の線名の便 {k2} に (驛,欄,時刻) がすべて在る（別の名前の同じ驛を含む・編み込み {len(plan)}）')
            dropped.add(key)
            counts['r3b'] = counts.get('r3b', 0) + 1
            break
    for key in dropped:
        del final[key]
    return counts


# ------------------------------------------------------------------
# Rebase trips whose front part was cut to their own day clock
# ------------------------------------------------------------------
# Each trip counts days on its own clock. Trips whose front part was cut in these 3 steps keep the
# day clock of the cut part and start at 24:00 or later:
#   (1) back parts of combined-line bands split at the junction (2nd and later parts in commit_parts),
#       e.g. 滿鐵咸鏡線南部 103 元山 31:05
#   (2) trips whose front was dropped/split by the arrival/departure actions table (the rest after
#       drop_before, the _b of split_after, the rest after split_before), e.g. 滿鐵安奉線 6 奉天 34:00,
#       東支鐵道線 3_b 哈爾賓 48:29
#   (3) trips renumbered from a start station onward by the renumbering table (EXTRACT_RENUMBER_TABLE),
#       e.g. 滿鐵滿洲本線・旅順線及營口線 12 長春 33:00
# When ON, only these trips are shifted back by a multiple of 1440 (same idea as
# INTEGRATE_B5_SPLIT_REBASE in integration; order and running times unchanged). Days are counted in the
# printed (local) time: shift so that the first time minus the time-system offset (60/34 minutes added
# by EXTRACT_TZ_TO_JST) falls in 0:00-23:59 (so a trip leaving at 23:xx local time, past 24:00 in Japan
# time, is not moved to hour 0; 東支鐵道線 3_b leaves 哈爾賓 at 23:55 local and becomes 24:29). Trips
# without a cut front (dated sailings, trips past 24:00 only because of the offset) are untouched.
# Logged as action=rebase_late_start. Default ON. Previous behavior = SPLIT_REBASE_LATE_START=0.
REBASE_LATE_START = os.environ.get('SPLIT_REBASE_LATE_START', '1') != '0'


def _extract_flags():
    """_extract_flags.json copied by integration (empty if missing)."""
    p = os.path.join(os.path.dirname(INTEGRATED), '_extract_flags.json')
    if not os.path.exists(p):
        return {}
    import json
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _renumber_cut_keys(final):
    """(3) trips renumbered from a start station onward by the renumbering table whose first row is that
    start station (same sheet). Returns {key: reason}; empty if the table was not applied at extraction."""
    flags = _extract_flags()
    if flags.get('EXTRACT_RENUMBER_TABLE') != 1:
        return {}
    path = os.path.join(BASE_DIR, flags.get('renumber_table') or os.path.join('data', 'tables', 'renumbering.csv'))
    out = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            rid = (r.get('改番ID') or '').strip()
            start = (r.get('起点の駅') or '').strip()
            if not rid or not start:
                continue
            line = (r.get('新しい線名') or '').strip() or r['line_name'].strip()
            key = f'{line}__{r["direction"].strip()}__{r["新しい番号"].strip()}'
            rs = final.get(key)
            if not rs:
                continue
            first = min(rs, key=lambda x: int(x['stop_sequence']))
            if (first['source_sheet'] == r['source_sheet'].strip()
                    and _a08_dn(first['stop_name']) == _a08_dn(start)):
                out[key] = f'改番表 {rid}（{r["source_sheet"].strip()} の {start} から後ろを {r["新しい番号"].strip()} に）'
    return out


def _rebase_late_start(final, split_log, cut_from):
    """cut_from = {key: why the front was cut}. Shift trips whose first time (local) is 24:00 or later
    back by a multiple of 1440. Returns (trips shifted, trips cut but left because they start before 24:00)."""
    tz_on = _extract_flags().get('EXTRACT_TZ_TO_JST') == 1
    if tz_on:
        import time_system
    n_rebased = n_kept = 0
    for key in sorted(cut_from):
        rs = final.get(key)
        if not rs:
            continue
        cells = [(t, int(r['stop_sequence']), r, fld) for r in rs for fld in ('arr', 'dep')
                 for t in [_to_min(r.get(f'{fld}_time'))] if t is not None]
        if not cells:
            continue
        t0, _, r0, f0 = min(cells, key=lambda c: (c[0], c[1]))
        off = 0
        if tz_on:
            _sys, o, _rule = time_system.lookup(r0['source_sheet'], r0['line_name'], r0['stop_name'], f0)
            off = o or 0
        k = (t0 - off) // 1440
        if k <= 0:
            n_kept += 1
            continue
        shift = k * 1440
        new_rows = []
        for r in rs:
            r2 = dict(r)
            for col in ('arr_time', 'dep_time'):
                t = _to_min(r2.get(col))
                if t is not None:
                    r2[col] = '%02d:%02d' % ((t - shift) // 60, (t - shift) % 60)
            new_rows.append(r2)
        final[key] = new_rows
        n_rebased += 1
        split_log.append({
            'trip_key': key, 'line_name': rs[0]['line_name'], 'action': 'rebase_late_start',
            'reason': (f'{cut_from[key]}＝前を切った便。最初の時刻 {t0 // 60:02d}:{t0 % 60:02d}'
                       + (f'（時差 {off} 分＝現地 {(t0 - off) // 60:02d}:{(t0 - off) % 60:02d}）' if off else '')
                       + f' を {shift} 分前へ'),
            'stops': ' → '.join(r['stop_name'] for r in sorted(new_rows, key=lambda x: int(x['stop_sequence']))),
            'front_trip': '', 'front_stops': '', 'back_trip': '', 'back_stops': '',
        })
    return n_rebased, n_kept


def main():
    # read
    with open(INTEGRATED, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    input_tbl_lines = _table_lines_from_extract(rows) if CD_TABLE_FROM_INPUT else None

    # group by trip_key (plain first, composite after -> plain wins in dedup)
    trips_plain = defaultdict(list)
    trips_composite = defaultdict(list)
    for r in rows:
        ln = r['line_name']
        target = trips_composite if (ln in BOUNDARY_STATIONS or ln in BOUNDARY_STATIONS_3WAY) else trips_plain
        target[r['gtfs_trip_key']].append(r)

    print(f'読込: {len(rows)} レコード')
    print(f'  plain: {len(trips_plain)} trip / composite: {len(trips_composite)} trip')

    # Build the output as "trip key -> rows" (collisions are handled per key).
    # Plain trips go in first, so if splitting creates the same key, the existing single-line detail wins.
    final = OrderedDict()
    for tk, trip_rows in trips_plain.items():
        final[tk] = trip_rows

    # orientation evidence: station sets of single-line trips (line_name -> base station names)
    plain_stations = defaultdict(set)
    for trip_rows in trips_plain.values():
        pln = trip_rows[0]['line_name']
        for r in trip_rows:
            plain_stations[pln].add(_base_name(r['stop_name']))

    # transcription evidence for checking reclassify (mileage CSV + station sets of non-combined trips)
    line_evidence = _build_line_evidence(plain_stations)

    # reference sequences for direction per component, stage 2 (bands without a partner; only when ON)
    if PART_DIRECTION and PART_DIRECTION_ORDER:
        _load_line_order_ref(rows)

    # Orientation pre-pass: collect trips to split per corridor (line pair + junction) and propagate
    # votes through shared stop_order to decide (line before junction, line after junction).
    corridor_entries = defaultdict(list)
    for tk, trip_rows in trips_composite.items():
        ln = trip_rows[0]['line_name']
        if ln not in BOUNDARY_STATIONS:
            continue
        fl, bl, bd = BOUNDARY_STATIONS[ln]
        rows_sorted = sorted(trip_rows, key=lambda r: int(r['stop_sequence']))
        names_s = [r['stop_name'] for r in rows_sorted]
        if bd not in names_s:
            continue
        bidx = names_s.index(bd)
        if bidx == 0 or bidx == len(names_s) - 1:
            continue
        corridor_entries[(frozenset((fl, bl)), bd)].append(
            {'tk': tk, 'rows': rows_sorted, 'front': fl, 'back': bl,
             'boundary_idx': bidx})
    resolved = {}
    for entries in corridor_entries.values():
        resolved.update(_resolve_orientations(entries, plain_stations))

    split_log = []
    n_split = 0
    n_split_3way = 0
    n_reclassified = 0
    n_stopwise = 0
    n_kept = 0
    n_skipped = 0
    n_guard_kept = 0
    n_covered = 0
    n_conflict_kept = 0
    n_merged_times = 0
    n_part_dir_flip = 0
    n_part_dir_order = 0
    n_single_line_band = 0
    n_extended = 0                 # SPLIT_EXTEND_EXISTING (default ON)
    n_extended_stops = 0
    plain_keys = set(trips_plain)  # keys of single-line trips present before splitting (only these may be extended)
    cut_from = {}                  # SPLIT_REBASE_LATE_START: key of trips whose front was cut -> reason (recorded only; unused when =0)

    for tk, trip_rows in trips_composite.items():
        ln = trip_rows[0]['line_name']
        direction = trip_rows[0]['direction']
        trip_num = trip_rows[0]['trip_num']

        def commit_parts(parts, _tk=tk, _rows=None, _d=direction, _n=trip_num):
            """Commit a split plan parts=[(sub_line or None, rows), ...] to final.

            - A part that collides with an existing trip of the same key and is a reprint of the same
              run (stations contained, times within +/-10 minutes) is dropped (the existing
              single-line detail wins).
            - If any colliding part has its own stations or mismatched times, keep the whole
              combined-line trip unsplit (no mislabeled fragments or duplicate trips; a different
              train with the same number is not taken as a duplicate; same principle as keeping
              what cannot be covered in integration's dedup).
            - Parts with sub_line=None (per-stop classification failed) keep the original line_name and key.
            Returns (list of labels of committed parts, 'committed'|'kept_conflict')."""
            nonlocal n_covered, n_conflict_kept, n_merged_times, n_part_dir_flip
            nonlocal n_part_dir_order, n_extended, n_extended_stops
            # direction per component (SPLIT_PART_DIRECTION); decide all before modifying `final`
            #   so parts do not affect each other (deterministic).
            pdirs = [(_resolve_part_direction(sl, rs, _d, _n, final) if sl else _d)
                     for sl, rs in parts]
            extend = {}      # SPLIT_EXTEND_EXISTING: key of existing trip to extend -> plan (decided here, not yet written)
            any_cov = set()  # same: indices of remaining band parts covered by existing trips comparing both 著 and 發
            conflicts = []
            for i, ((sub_line, rs), _pd) in enumerate(zip(parts, pdirs)):
                if sub_line is None:
                    continue
                key = f'{sub_line}__{_pd}__{_n}'
                if key in final and not _part_covered(rs, final[key]):
                    plan = (_extend_plan(rs, final[key])
                            if EXTEND_EXISTING and key in plain_keys and key not in extend else None)
                    if plan is not None:
                        extend[key] = plan
                        continue
                    conflicts.append((i, key))
            if extend:
                # For the remaining parts of a band being extended, measure coverage with both 著 and 發
                #   (`_row_min` takes one time per station, preferring 發, so a band's 著 misses a detail
                #   station printed with both 著 and 發, e.g. p75 344 福知山 著 06:28 / 發 06:42).
                #   Only parts covered by the same-direction key, or (with no same-direction key) by the
                #   opposite-direction key (direction flipped).
                for i, ((sub_line, rs), _pd) in enumerate(zip(parts, pdirs)):
                    if sub_line is None:
                        continue
                    key = f'{sub_line}__{_pd}__{_n}'
                    if key in extend:
                        continue
                    if key in final:
                        if any(ci == i for ci, _ in conflicts) and _part_covered_any(rs, final[key]):
                            any_cov.add(i)
                        continue
                    opp = 'inbound' if _pd == 'outbound' else 'outbound'
                    ko = f'{sub_line}__{opp}__{_n}'
                    if ko in final and _part_covered_any(rs, final[ko]):
                        pdirs[i] = opp
                        any_cov.add(i)
                conflicts = [(i, key) for i, key in conflicts if i not in any_cov]
            if conflicts:
                final[_tk] = list(_rows)
                n_conflict_kept += 1
                return [f'(衝突: {conflicts[0][1]} に無い駅を含む→元トリップ維持)'], 'kept_conflict'
            labels = []
            for idx, ((sub_line, rs), _pd) in enumerate(zip(parts, pdirs)):
                if sub_line is None:
                    final.setdefault(_tk, []).extend(dict(r) for r in rs)
                    labels.append('(unknown_part: 元キーのまま)')
                    continue
                if _pd != _d:
                    n_part_dir_flip += 1
                    by_order = f'{sub_line}__{_pd}__{_n}' not in final
                    if by_order:
                        n_part_dir_order += 1
                    split_log.append({
                        'trip_key': _tk, 'line_name': rs[0]['line_name'],
                        'action': ('part_direction_order' if by_order
                                   else 'part_direction_flip'),
                        'reason': (f'{sub_line} の区間は帯の向き({_d})と逆＝'
                                   + ('その線の駅の並び（detect_band_orientation と同じ物差し）で判定'
                                      '＝相手のトリップは無し'
                                      if by_order else
                                      f'{sub_line}__{_pd}__{_n} に丸ごと被覆される')),
                        'stops': ' → '.join(r['stop_name'] for r in rs),
                        'front_trip': f'{sub_line}__{_pd}__{_n}', 'front_stops': '',
                        'back_trip': '', 'back_stops': '',
                    })
                key = f'{sub_line}__{_pd}__{_n}'
                if idx in any_cov:
                    # remaining part of a band being extended (SPLIT_EXTEND_EXISTING), covered on both 著 and 發: drop it, weave into blanks only
                    n_covered += 1
                    m = _merge_unique_times(rs, final[key]) if MERGE_UNIQUE_TIMES else []
                    if m:
                        n_merged_times += len(m)
                        split_log.append({
                            'trip_key': _tk, 'line_name': rs[0]['line_name'],
                            'action': 'merged_unique_time',
                            'reason': f'{key} の空欄へ ' + '・'.join(f'{a}{b}{c}' for a, b, c in m),
                            'stops': ' → '.join(r['stop_name'] for r in rs),
                            'front_trip': key, 'front_stops': '', 'back_trip': '', 'back_stops': '',
                        })
                    labels.append(f'({sub_line}: 既存トリップに被覆済み〔著・發で照合〕→省略)')
                    continue
                if key in final:
                    if _part_covered(rs, final[key]):
                        n_covered += 1
                        note = ''
                        if MERGE_UNIQUE_TIMES:
                            m = _merge_unique_times(rs, final[key])
                            if m:
                                n_merged_times += len(m)
                                note = ('・帯にしか無い時刻を編み込み: '
                                        + '・'.join(f'{a}{b}{c}' for a, b, c in m))
                                split_log.append({
                                    'trip_key': _tk, 'line_name': rs[0]['line_name'],
                                    'action': 'merged_unique_time',
                                    'reason': f'{key} の空欄へ ' + '・'.join(
                                        f'{a}{b}{c}' for a, b, c in m),
                                    'stops': ' → '.join(r['stop_name'] for r in rs),
                                    'front_trip': key, 'front_stops': '',
                                    'back_trip': '', 'back_stops': '',
                                })
                        labels.append(f'({sub_line}: 既存トリップに被覆済み→省略{note})')
                        continue
                    if key in extend:
                        # extend the existing trip along the part's station order (SPLIT_EXTEND_EXISTING)
                        k, plan = extend.pop(key)
                        ex0 = final[key][0]
                        new_rows, added = [], []
                        for kind, r in plan:
                            if kind == 'ex':
                                new_rows.append(r)
                                continue
                            r2 = dict(r)
                            for f in ('line_name', 'gtfs_trip_key', 'direction', 'trip_num'):
                                r2[f] = ex0[f]
                            for col in ('arr_time', 'dep_time'):
                                t = _to_min(r2.get(col))
                                if t is not None and k:
                                    t += k * 1440
                                    r2[col] = '%02d:%02d' % (t // 60, t % 60)
                            new_rows.append(r2)
                            added.append(r2['stop_name'])
                        for i, r in enumerate(new_rows):
                            r['stop_sequence'] = str(i + 1)
                        final[key] = new_rows
                        m = _merge_unique_times(rs, final[key]) if MERGE_UNIQUE_TIMES else []
                        n_extended += 1
                        n_extended_stops += len(added)
                        n_merged_times += len(m)
                        split_log.append({
                            'trip_key': _tk, 'line_name': rs[0]['line_name'],
                            'action': 'extend_existing',
                            'reason': (f'{key} の駅が帯の部分に全部あり時刻も合う＝部分の並びで延ばした（足した駅 '
                                       + '・'.join(added) + '）'
                                       + ('・空欄へ ' + '・'.join(f'{a}{b}{c}' for a, b, c in m) if m else '')),
                            'stops': ' → '.join(r['stop_name'] for r in rs),
                            'front_trip': key, 'front_stops': ' → '.join(r['stop_name'] for r in new_rows),
                            'back_trip': '', 'back_stops': '',
                        })
                        labels.append(f'({sub_line}: 既存トリップ {key} を延ばした＝' + '・'.join(added) + ')')
                        continue
                    # The same line appearing twice, apart, in one trip (A,B,A) is outside the precheck;
                    # keep it under a key with _sw if it has its own stations.
                    key = f'{key}_sw{idx}'
                out = []
                for i, r in enumerate(rs):
                    r2 = dict(r)
                    r2['line_name'] = sub_line
                    r2['gtfs_trip_key'] = key
                    r2['stop_sequence'] = str(i + 1)
                    if _pd != _d:
                        # For a flipped part, also set the `direction` column (fixing only the key would
                        #   leave the column stale for the band orientation check and GTFS).
                        #   With SPLIT_PART_DIRECTION=0, _pd == _d, so no cell changes.
                        r2['direction'] = _pd
                    out.append(r2)
                final[key] = out
                labels.append(key)
                if idx >= 1:
                    cut_from[key] = f'{_tk} を分けた後ろの部分'
            return labels, 'committed'

        # sort by station order
        trip_rows = sorted(trip_rows, key=lambda r: int(r['stop_sequence']))
        names = [r['stop_name'] for r in trip_rows]

        # 3-way
        if ln in BOUNDARY_STATIONS_3WAY:
            la, lb, lc, b_ab, b_bc = BOUNDARY_STATIONS_3WAY[ln]
            parts3 = _split_3way_parts(trip_rows, names, (la, lb, lc), b_ab, b_bc)
            if parts3:
                labels3, oc3 = commit_parts(parts3, _rows=trip_rows)
                if oc3 == 'committed':
                    n_split_3way += 1
                split_log.append({'trip_key': tk, 'line_name': ln,
                                  'action': 'split_3way' if oc3 == 'committed' else 'kept_conflict',
                                  'reason': f'boundaries={b_ab},{b_bc}', 'stops': ' → '.join(names),
                                  'front_trip': ' | '.join(labels3), 'front_stops': '',
                                  'back_trip': '', 'back_stops': ''})
                continue
            # junctions not both present -> fall back to per-stop split
            groups = _stopwise_split(trip_rows, (la, lb, lc), line_evidence)
            if any(sl for sl, _ in groups) and _stopwise_all_covered(groups, direction, trip_num, final):
                _kept_stopwise_covered(final, split_log, tk, ln, trip_rows, groups)
                continue
            if any(sl for sl, _ in groups):
                if _emit_stopwise(groups, commit_parts, split_log, tk, ln,
                                  trip_rows) == 'committed':
                    n_stopwise += 1
                continue
            final.setdefault(tk, []).extend(trip_rows)
            n_skipped += 1
            split_log.append({'trip_key': tk, 'line_name': ln, 'action': 'skipped_3way',
                              'reason': 'no boundary, no 転記の証拠 match', 'stops': ' → '.join(names),
                              'front_trip': '', 'front_stops': '', 'back_trip': '', 'back_stops': ''})
            continue

        # 2-way
        front_line, back_line, boundary = BOUNDARY_STATIONS[ln]

        # sort by station order
        trip_rows = sorted(trip_rows, key=lambda r: int(r['stop_sequence']))
        names = [r['stop_name'] for r in trip_rows]

        # index of the junction
        if boundary not in names:
            # junction not in the trip -> try per-stop reclassify
            groups = _stopwise_split(trip_rows, (front_line, back_line), line_evidence)
            if any(sl for sl, _ in groups) and _stopwise_all_covered(groups, direction, trip_num, final):
                _kept_stopwise_covered(final, split_log, tk, ln, trip_rows, groups)
                continue
            if len(groups) == 1 and groups[0][0] is not None:
                # all stops on one sub_line -> reclassify
                sub_line = groups[0][0]
                # check: do not fold if a station is only on the other component (keep the combined name)
                blockers = (_reclassify_blockers(
                    trip_rows, sub_line,
                    [x for x in (front_line, back_line) if x != sub_line],
                    line_evidence) if RECLASSIFY_GUARD else [])
                if blockers:
                    final.setdefault(tk, []).extend(trip_rows)
                    n_guard_kept += 1
                    split_log.append({
                        'trip_key': tk, 'line_name': ln,
                        'action': 'kept_reclassify_guard',
                        'reason': (f'{sub_line} の証拠が無く相手の成分の証拠がある駅: '
                                   + '・'.join(blockers)),
                        'stops': ' → '.join(names),
                        'front_trip': '', 'front_stops': '',
                        'back_trip': '', 'back_stops': '',
                    })
                    continue
                labels, oc = commit_parts([(sub_line, trip_rows)], _rows=trip_rows)
                if oc == 'committed':
                    n_reclassified += 1
                split_log.append({
                    'trip_key': tk, 'line_name': ln,
                    'action': 'reclassified' if oc == 'committed' else 'kept_conflict',
                    'reason': f'all on {sub_line}',
                    'stops': ' → '.join(names),
                    'front_trip': ' | '.join(labels),
                    'front_stops': ' → '.join(names),
                    'back_trip': '', 'back_stops': '',
                })
                continue
            if any(sl for sl, _ in groups):
                if _emit_stopwise(groups, commit_parts, split_log, tk, ln,
                                  trip_rows) == 'committed':
                    n_stopwise += 1
                continue
            # cannot decide at all -> leave as is
            final.setdefault(tk, []).extend(trip_rows)
            n_skipped += 1
            split_log.append({
                'trip_key': tk,
                'line_name': ln,
                'action': 'skipped',
                'reason': f'boundary "{boundary}" not in trip, no 転記の証拠 match',
                'stops': ' → '.join(names),
                'front_trip': '', 'front_stops': '', 'back_trip': '', 'back_stops': '',
            })
            continue

        # a band running on only one line is folded into that line without splitting (SPLIT_SINGLE_LINE_BAND)
        if SINGLE_LINE_BAND:
            one, only = _single_line_of(names, front_line, back_line, line_evidence)
            if one:
                labels, oc = commit_parts([(one, trip_rows)], _rows=trip_rows)
                if oc == 'committed':
                    n_single_line_band += 1
                split_log.append({
                    'trip_key': tk, 'line_name': ln,
                    'action': 'single_line_band' if oc == 'committed' else 'kept_conflict',
                    'reason': f'全駅が {one} の駅（{"・".join(only)} は {one} だけ）',
                    'stops': ' → '.join(names),
                    'front_trip': ' | '.join(labels), 'front_stops': ' → '.join(names),
                    'back_trip': '', 'back_stops': '',
                })
                continue

        boundary_idx = names.index(boundary)

        # junction at the first or last stop: only one side, so do not split
        if boundary_idx == 0 or boundary_idx == len(names) - 1:
            final.setdefault(tk, []).extend(trip_rows)
            n_kept += 1
            split_log.append({
                'trip_key': tk,
                'line_name': ln,
                'action': 'kept',
                'reason': f'boundary at edge (idx {boundary_idx} of {len(names)})',
                'stops': ' → '.join(names),
            })
            continue

        # Orientation: BOUNDARY_STATIONS only gives (line_A, line_B, junction); which way the trip runs
        # cannot be decided from the direction flag (the printed up/down can disagree with geography,
        # e.g. 山陽及東海道本線 runs east for both outbound and inbound). Apply the orientation decided by
        # the pre-pass _resolve_orientations (station-to-line votes propagated over shared stop_order).
        rs_lines = resolved.get(tk)
        swapped = bool(rs_lines) and rs_lines[0] != front_line
        if rs_lines:
            front_line, back_line = rs_lines

        # Split
        # front: 0 .. boundary_idx (inclusive)
        # back:  boundary_idx .. end (inclusive, junction included)
        # Keys differ by line_name. On collision with an existing single-line trip, commit_parts either
        # drops the part (detail wins) or keeps the whole original trip, by station containment.
        labels, oc = commit_parts(
            [(front_line, trip_rows[:boundary_idx + 1]),
             (back_line, trip_rows[boundary_idx:])], _rows=trip_rows)
        if oc == 'committed':
            n_split += 1
        split_log.append({
            'trip_key': tk,
            'line_name': ln,
            'action': 'split' if oc == 'committed' else 'kept_conflict',
            'reason': f'boundary={boundary}'
                      + ('（向き=stop_order伝播でswap）' if swapped else ''),
            'stops': ' → '.join(names),
            'front_trip': labels[0],
            'front_stops': ' → '.join(names[:boundary_idx + 1]),
            'back_trip': labels[1] if len(labels) > 1 else '',
            'back_stops': ' → '.join(names[boundary_idx:]),
        })

    # Final dedup (remaining double listings with 及):
    # After splitting and reclassifying, trips still under a combined line name whose every
    # (station, time) is covered by non-combined trips (single-line details + split parts) in the same
    # direction within +/-10 minutes are double listings of the same train and are dropped. This
    # removes leftovers of paired combined-name listings (integration's dedup only compares combined
    # vs. non-combined) after one of them became single-line trips by splitting.
    # Keep if any (station, time) is unique (no information is lost, as in integration's dedup).
    # Trips with fewer than 2 timed stations are kept unchecked. Switch: SPLIT_FINAL_DEDUP=0.
    n_final_dedup = 0
    n_dedup_kept_unique = 0
    if os.environ.get('SPLIT_FINAL_DEDUP', '1') != '0':
        # match on base names with kanji variants unified (亀山 = 龜山 etc.)
        def _dn(name):
            return _kv_norm(_base_name(name), prefer_new=True)
        time_idx = defaultdict(list)
        name_idx = defaultdict(set)
        for key, rs in final.items():
            if not rs or '及' in rs[0]['line_name']:
                continue
            d = rs[0]['direction']
            for r in rs:
                b = _dn(r['stop_name'])
                name_idx[d].add(b)
                t = _row_min(r)
                if t is not None:
                    time_idx[(b, d)].append(t % 1440)
        removable = []
        for key in list(final.keys()):
            rs = final[key]
            if not rs or '及' not in rs[0]['line_name']:
                continue
            d = rs[0]['direction']
            timed = 0
            covered = True
            for r in rs:
                b = _dn(r['stop_name'])
                t = _row_min(r)
                if t is None:
                    if b not in name_idx.get(d, ()):
                        covered = False
                        break
                    continue
                timed += 1
                ok = any(min(abs(t - c) % 1440, 1440 - (abs(t - c) % 1440)) <= 10
                         for c in time_idx.get((b, d), ()))
                if not ok:
                    covered = False
                    break
            if covered and timed >= 2:
                removable.append(key)

        # Before dropping, check that the band has no time found nowhere else.
        # The coverage check above takes one time per station (發 if present, else 著) and matches within
        # +/-10 minutes, so a band's 著 can match a detail's 發 (meant to absorb the dwell), and a 著 (or 發)
        # printed only in the band could be lost. So just before dropping, check per (station, field, time)
        # that a remaining trip has the same value; if not, keep the band.
        # Default ON. Previous behavior = SPLIT_DEDUP_KEEP_UNIQUE=0.
        keep_unique = os.environ.get('SPLIT_DEDUP_KEEP_UNIQUE', '1') != '0'
        cells = set()
        if keep_unique:
            drop = set(removable)
            for key, rs in final.items():
                if key in drop:
                    continue
                for r in rs:
                    b = _dn(r['stop_name'])
                    for col, lab in (('dep_time', '發'), ('arr_time', '著')):
                        t = _to_min(r.get(col))
                        if t is not None:
                            cells.add((b, lab, t % 1440))

        for key in removable:
            rs = final[key]
            if keep_unique:
                own = set()
                for r in rs:
                    b = _dn(r['stop_name'])
                    for col, lab in (('dep_time', '發'), ('arr_time', '著')):
                        t = _to_min(r.get(col))
                        if t is not None:
                            own.add((b, lab, t % 1440))
                uniq = sorted(own - cells)
                if uniq:
                    cells |= own
                    n_dedup_kept_unique += 1
                    split_log.append({
                        'trip_key': key, 'line_name': rs[0]['line_name'],
                        'action': 'kept_unique_time',
                        'reason': ('被覆扱いだが、この帯にしか無い時刻がある: '
                                   + '・'.join('%s%s%02d:%02d' % (b, lab, t // 60, t % 60)
                                               for b, lab, t in uniq)),
                        'stops': ' → '.join(r['stop_name'] for r in rs),
                        'front_trip': '', 'front_stops': '',
                        'back_trip': '', 'back_stops': '',
                    })
                    continue
            n_final_dedup += 1
            split_log.append({
                'trip_key': key, 'line_name': rs[0]['line_name'],
                'action': 'dedup_covered',
                'reason': '全駅×時刻が非及トリップに±10分で被覆＝同一列車の二重掲載',
                'stops': ' → '.join(r['stop_name'] for r in rs),
                'front_trip': '', 'front_stops': '',
                'back_trip': '', 'back_stops': '',
            })
            del final[key]

    # arrival/departure rows actions table (different trains across the 著 row and 發 row; default ON, SPLIT_A08_ACTIONS)
    _n_log = len(split_log)
    a08_counts = _a08_apply(final, split_log) if A08_ACTIONS else None
    for e in split_log[_n_log:]:   # SPLIT_REBASE_LATE_START: trips whose front was cut by an action (recorded only)
        if e['action'] == 'a08_drop_before':
            cut_from[e['trip_key']] = f'著發 2 行の処置表 {e["reason"].split(" ")[0]}（前を落とした）'
        elif e['action'] in ('a08_split_after', 'a08_split_before'):
            cut_from[e['back_trip']] = f'著發 2 行の処置表 {e["reason"].split(" ")[0]}（前を別の便に分けた）'
    # arrival/departure rows merge table (merge the remaining 著 row + 發 row into one stop; default ON, SPLIT_A08_MERGE)
    a08_merge_counts = _a08_merge(final, split_log) if A08_MERGE else None
    # band-only values into blanks of the same-numbered detail trip (default ON, INTEGRATE_COMBINED_FILL_BLANKS)
    fill_counts = _fill_band_blanks(final, split_log, os.path.join(os.path.dirname(INTEGRATED), 'combined_band_cells.csv')) \
        if FILL_BLANKS else None
    # drop wholly contained duplicate trips (default ON, SPLIT_CONTAINED_DEDUP)
    cd_counts = _contained_dedup(final, split_log, input_tbl_lines) if CONTAINED_DEDUP else None
    # rebase trips whose front part was cut to their own day clock (default ON, SPLIT_REBASE_LATE_START)
    rebase_counts = None
    if REBASE_LATE_START:
        for k, why in _renumber_cut_keys(final).items():
            cut_from.setdefault(k, why)
        rebase_counts = _rebase_late_start(final, split_log, cut_from)

    print(f'2-way 分割: {n_split} trip')
    print(f'3-way 分割: {n_split_3way} trip')
    print(f'reclassify (単一 sub-line): {n_reclassified} trip')
    print(f'stop-wise 分割: {n_stopwise} trip')
    print(f'保留(境界駅未通過・分類不能): {n_skipped}')
    if RECLASSIFY_GUARD or n_guard_kept:
        print(f'保留(reclassify 裏取りで却下・合成名のまま): {n_guard_kept}')
    print(f'保留(境界駅が端): {n_kept}')
    if SINGLE_LINE_BAND or n_single_line_band:
        print(f'片方の線だけの帯（境界駅で割らずにその線へ畳む）: {n_single_line_band} trip')
    if PART_DIRECTION or n_part_dir_flip:
        print(f'成分ごとの向き読み替え(SPLIT_PART_DIRECTION・帯と逆): {n_part_dir_flip} 部分')
    print(f'衝突→被覆済みで省略(既存詳細を採用): {n_covered} 部分')
    if n_merged_times:
        print(f'  うち帯にしか無い時刻を既存トリップへ編み込み: {n_merged_times} セル')
    if EXTEND_EXISTING or n_extended:
        print(f'衝突→既存の便を帯の部分で延ばした: {n_extended} 部分（足した駅 {n_extended_stops}）')
    print(f'衝突→独自駅ありで元トリップ丸ごと維持: {n_conflict_kept} trip')
    print(f'最終dedup(及の二重掲載・全駅×時刻被覆): {n_final_dedup} trip')
    if n_dedup_kept_unique:
        print(f'最終dedup 保留(帯にしか無い時刻がある): {n_dedup_kept_unique} trip')
    if a08_counts is not None:
        print(f'著發 2 行の処置表(原本では別の列車): 落とす {a08_counts[0]} trip・'
              f'分ける {a08_counts[1]} trip・見送り {a08_counts[2]}')
    if a08_merge_counts is not None:
        print(f'著發 2 行のまとめ表(著行・發行を 1 回の停車に): まとめた {a08_merge_counts[0]} 組・'
              f'見送り {a08_merge_counts[1]}・まとめ表に無い {a08_merge_counts[2]}')

    if fill_counts is not None:
        print(f'帯にしか無い値を詳細の空欄へ: 書いた {fill_counts[0]} セル・見送り {fill_counts[1]}')
    if cd_counts is not None:
        print(f'丸ごと含まれる重複便の除去: 番号なしの帯 {cd_counts["r1a"]}・乗りつぎ案内 {cd_counts["r1b"]}・'
              f'番号が同じ別の線名 {cd_counts["r2"]} trip（編み込み {cd_counts["weave"]} セル）')
        if CONTAINED_DEDUP_MULTI:
            print(f'  R3（SPLIT_CONTAINED_DEDUP_MULTI）: 別の線名の便にまたがって {cd_counts.get("r3a", 0)}・'
                  f'別の名前の同じ驛 {cd_counts.get("r3b", 0)} trip（編み込み {cd_counts.get("weave_r3", 0)} セル）・'
                  f'乗車の条件で落とさなかった帯 {cd_counts.get("keep_r3a", 0)}')
    if rebase_counts is not None:
        print(f'前を切った便を自分の日の時計に戻す: ずらした {rebase_counts[0]} trip・'
              f'24:00 より前に始まるので触らなかった {rebase_counts[1]} trip（前を切った便 {len(cut_from)}）')

    # assemble the output (key collisions already handled by commit_parts)
    deduped_rows = []
    seen = set()
    n_dup = 0
    for rs in final.values():
        for r in rs:
            marker = (r['gtfs_trip_key'], r['stop_sequence'])
            if marker in seen:
                n_dup += 1
                continue
            seen.add(marker)
            deduped_rows.append(r)
    if n_dup:
        print(f'警告: (key,seq) 重複 {n_dup} 件を除去（想定外・要調査）')
    print(f'最終: {len(deduped_rows)} レコード ({len(set(r["gtfs_trip_key"] for r in deduped_rows))} trip)')

    # write back
    with open(INTEGRATED, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(deduped_rows)
    print(f'更新: {INTEGRATED}')

    # report
    with open(REPORT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['trip_key', 'line_name', 'action', 'reason',
                                            'stops', 'front_trip', 'front_stops',
                                            'back_trip', 'back_stops'])
        w.writeheader()
        w.writerows(split_log)
    print(f'レポート: {REPORT}')


if __name__ == '__main__':
    main()
