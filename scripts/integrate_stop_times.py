"""
integrate_stop_times.py

Combine the stop_times of every file in 3_stop_times_intermediate/, join the
segments of each (line_name, direction, trip_num), and write
4_integrated/integrated_stop_times.csv.

Flow:
  A. Load the stop_times of all intermediate files into one table
  B. Group by (line_name, direction, trip_num)
  C. Order the sheets within each group by time
  D. Drop summary sheets (those contained in a detailed sheet)
  E. Merge boundary stops (arr and dep into one record)
  F. Assign a global stop_sequence
  G. Write the CSV
"""

import os
import csv
import re
import unicodedata
from collections import defaultdict, Counter
import openpyxl

from known_kanji_variants import normalize as normalize_kanji_variants
from known_kanji_variants import LINE_NAME_ALIASES


def canonicalize_stop_names(all_records):
    """Unify old/new kanji spellings of stop_name to the majority form, **per line**.

    The transcription keeps each page's printed spelling, so one station can be
    spelled differently on different pages. The GTFS stop key is
    `(stop_name, line_name)`, so without this the same station splits into
    several stop_ids.

    - Group key = `(known_kanji_variants.normalize(name, prefer_new=True), line_name)`:
      only names the dictionary treats as equal on the same line are merged
      (other lines stay separate stops, e.g. 青島 on 宮崎鐵道線 and 靑島 on 膠濟本線).
    - Canonical form = most records -> most old-form kanji -> string order (deterministic).
    - Call this **after** `canonicalize_line_names()`.

    Rewrites all_records in place and returns {(old_name, line_name): new_name}.
    """
    from known_kanji_variants import _OLD_TO_NEW as _KV_OLD

    def _old_kanji_count(s):
        return sum(1 for ch in s if ch in _KV_OLD)

    counts = Counter((r['stop_name'], r['line_name'])
                     for r in all_records
                     if r.get('stop_name') and r.get('line_name'))
    groups = defaultdict(list)
    for (name, line), c in counts.items():
        groups[(normalize_kanji_variants(name, prefer_new=True), line)].append((name, c))

    name_map = {}
    for (_, line), name_counts in groups.items():
        if len(name_counts) < 2:
            continue
        name_counts.sort(key=lambda x: (-x[1], -_old_kanji_count(x[0]), x[0]))
        canonical = name_counts[0][0]
        for name, _c in name_counts[1:]:
            name_map[(name, line)] = canonical

    if name_map:
        for r in all_records:
            key = (r.get('stop_name'), r.get('line_name'))
            if key in name_map:
                r['stop_name'] = name_map[key]

    return name_map


# Unify old/new kanji spellings **across lines** (after the per-line pass), with the same ranking rule.
#   Otherwise 稚内 and 稚內 on different lines stay apart and fall into different station groups in the
#   journey planner. Only the spelling changes; the stop key stays (stop_name, line_name).
#   Default ON. Previous behavior = INTEGRATE_CANON_STOP_GLOBAL=0.
CANON_STOP_GLOBAL = os.environ.get('INTEGRATE_CANON_STOP_GLOBAL', '1') != '0'


def canonicalize_stop_names_global(all_records):
    """Unify old/new kanji spellings of stop_name to one form across the whole corpus.
    Call after canonicalize_stop_names() (per line). Rewrites in place and returns
    {(old_name, line_name): new_name}; an empty dict when disabled."""
    if not CANON_STOP_GLOBAL:
        return {}
    from known_kanji_variants import _OLD_TO_NEW as _KV_OLD

    def _old_kanji_count(s):
        return sum(1 for ch in s if ch in _KV_OLD)

    counts = Counter((r['stop_name'], r['line_name'])
                     for r in all_records
                     if r.get('stop_name') and r.get('line_name'))
    groups = defaultdict(list)
    for (name, line), c in counts.items():
        groups[normalize_kanji_variants(name, prefer_new=True)].append((name, line, c))
    name_map = {}
    for _key, members in groups.items():
        if len({n for n, _l, _c in members}) < 2:
            continue
        by_name = Counter()
        for n, _l, c in members:
            by_name[n] += c
        ranked = sorted(by_name.items(),
                        key=lambda x: (-x[1], -_old_kanji_count(x[0]), x[0]))
        canonical = ranked[0][0]
        for n, l, _c in members:
            if n != canonical:
                name_map[(n, l)] = canonical
    if name_map:
        for r in all_records:
            key = (r.get('stop_name'), r.get('line_name'))
            if key in name_map:
                r['stop_name'] = name_map[key]
    return name_map


def canonicalize_line_names(all_records):
    """Unify spelling variants of line_name.

    1. Old/new kanji variants -> majority form (kanji_variants dictionary),
       e.g. 水戸鐡道線 (26) and 水戸鐵道線 (132) -> 水戸鐵道線
    2. Aliases registered in LINE_NAME_ALIASES (known_kanji_variants),
       e.g. 北陸線 -> 北陸本線

    Variants outside the dictionary are not merged.
    Rewrites all_records in place and returns the mapping.
    """
    canonical_map = {}

    # === Pass 1: unify old/new kanji variants to the majority ===
    line_counts = Counter(r['line_name'] for r in all_records if r.get('line_name'))
    # Group by the new-form spelling
    groups = defaultdict(list)
    for name, count in line_counts.items():
        canon_key = normalize_kanji_variants(name, prefer_new=True)
        groups[canon_key].append((name, count))
    # Unify only groups with more than one spelling
    for canon_key, name_counts in groups.items():
        if len(name_counts) > 1:
            # Most records first; ties by longer name (prefer old form)
            name_counts.sort(key=lambda x: (-x[1], -len(x[0])))
            canonical = name_counts[0][0]
            for name, _ in name_counts:
                if name != canonical:
                    canonical_map[name] = canonical

    # === Pass 2: explicit aliases from LINE_NAME_ALIASES ===
    # If Pass 1 already mapped a name, link to the final canonical form
    for alias, canonical in LINE_NAME_ALIASES:
        # If Pass 1 mapped the alias, point its target to the canonical form
        actual_alias = canonical_map.get(alias, alias)
        # Follow the canonical form if Pass 1 mapped it
        actual_canonical = canonical_map.get(canonical, canonical)
        if actual_alias != actual_canonical:
            canonical_map[alias] = actual_canonical
            # Also redirect mappings that pointed to the alias
            for k, v in list(canonical_map.items()):
                if v == actual_alias:
                    canonical_map[k] = actual_canonical

    # === Apply ===
    if canonical_map:
        for r in all_records:
            ln = r.get('line_name')
            if ln in canonical_map:
                r['line_name'] = canonical_map[ln]

    return canonical_map


def normalize_stop_name(name):
    """Normalize a station name wrapped in ＜＞ and drop a parenthesized note."""
    if name and name.startswith('＜') and name.endswith('＞'):
        name = name[1:-1]
        name = re.sub(r'（.*）', '', name)
    return name


def minutes_to_hhmm(total_min):
    """Minutes (may exceed 24h) -> HH:MM string (GTFS style: 24:xx, 25:xx, ...)."""
    h = total_min // 60
    m = total_min % 60
    return f'{h:02d}:{m:02d}'


def apply_time_offset(records, offset_min):
    """Return a new list with offset_min added to every arr_time / dep_time."""
    result = []
    for r in records:
        new_r = dict(r)
        for key in ('arr_time', 'dep_time'):
            t = time_to_min(r.get(key))
            if t is not None:
                new_r[key] = minutes_to_hhmm(t + offset_min)
        result.append(new_r)
    return result


BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR   = os.path.join(BASE_DIR, 'data', os.environ.get('STOP_TIMES_DIR', '3_stop_times_intermediate'))
OUTPUT_DIR  = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'))
# QA log (opt-in): when set, write a CSV of records dropped by E' (non-monotonic removal),
# sheets not chosen by select_sheets, and B.5 time-consistency splits. Not written when unset.
# E' silently drops conflicting records, so this log helps find pm errors, wrong train numbers
# and duplicated transcription.
QA_LOG_PATH = os.environ.get('INTEGRATE_QA_LOG')


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def time_to_min(t):
    """HH:MM (24:xx etc. allowed) -> minutes. Returns None for None."""
    if t is None:
        return None
    if isinstance(t, str) and t.startswith('ERR'):
        return None
    h, m = map(int, str(t).split(':'))
    return h * 60 + m


# ---------------------------------------------------------------------------
# Step A: load all intermediate files
# ---------------------------------------------------------------------------

# Read the intermediate files in NFC-normalized name order (macOS file names may be NFD, which changes
#   the byte order and the order of qa_log.csv; the integrated output is the same).
#   Default ON. Previous behavior (raw byte order) = INTEGRATE_SORT_NFC=0.
SORT_NFC = os.environ.get('INTEGRATE_SORT_NFC', '1') != '0'


def load_all_stop_times():
    records = []
    names = os.listdir(INPUT_DIR)
    names = sorted(names, key=lambda n: unicodedata.normalize('NFC', n)) if SORT_NFC else sorted(names)
    for fname in names:
        if not fname.endswith('.xlsx'):
            continue
        # read_only=True: only values are read, so output is unchanged and loading is much faster
        wb = openpyxl.load_workbook(os.path.join(INPUT_DIR, fname),
                                    read_only=True, data_only=True)
        ws = wb['stop_times']
        headers = None
        for row in ws.iter_rows(values_only=True):
            if headers is None:
                headers = list(row)
                continue
            records.append(dict(zip(headers, row)))
        wb.close()
    return records


# ---------------------------------------------------------------------------
# Step B: grouping
# ---------------------------------------------------------------------------

def group_records(all_records):
    """
    Group by (line_name, direction, trip_num).
    Trips with trip_num None get a placeholder trip_num (U{source_sheet}_{trip_id});
    they come from a single sheet, so integration passes them through.
    Also returns uncertain_count (for logging).
    """
    groups = defaultdict(list)
    uncertain_count = 0
    for r in all_records:
        if r.get('trip_num') is None:
            # Assign a placeholder trip_num
            synthetic = f"U{r['source_sheet']}_{r['trip_id']}"
            r['trip_num'] = synthetic
            key = (r['line_name'], r['direction'], synthetic)
            groups[key].append(r)
            uncertain_count += 1
        else:
            key = (r['line_name'], r['direction'], str(r['trip_num']))
            groups[key].append(r)
    return groups, uncertain_count


def _time_match(t1, t2, tol=5):
    """Whether two times (minutes) match: True if they differ by a multiple of 1440 ± tol,
    so times on different days after crossing midnight still match."""
    if t1 is None or t2 is None:
        return None  # undecidable
    diff = abs(t1 - t2) % 1440
    if diff > 720:
        diff = 1440 - diff
    return diff <= tol


def _b5_handoff_ok(dep1, arr1, dep2, arr2):
    """B.5 complement check (INTEGRATE_B5_COMPLEMENT): at one station, one side has only
    著 (arrival) and the other only 發 (departure), i.e. a hand-over at a boundary station.
    Treated as the same train if the gap (earlier arrival -> later departure) is within
    [-B5_NEG_TOL, B5_MAXDWELL] minutes. Larger negative gaps or > 600 min stay separate
    (kept as clues to conflicts in the original or pm errors)."""
    def gap(a_arr, b_dep):
        d = (b_dep - a_arr) % 1440
        return d - 1440 if d > 720 else d
    if arr1 is not None and dep2 is not None and dep1 is None and arr2 is None:
        return -B5_NEG_TOL <= gap(arr1, dep2) <= B5_MAXDWELL
    if dep1 is not None and arr2 is not None and arr1 is None and dep2 is None:
        return -B5_NEG_TOL <= gap(arr2, dep1) <= B5_MAXDWELL
    return False


_TABLE_RE = re.compile(r'^(p\d+)_tb(\d+)')


def _table_key(sheet_name):
    """Return (page, table number) from a sheet name, or None."""
    m = _TABLE_RE.match(str(sheet_name))
    return (m.group(1), m.group(2)) if m else None


def _unit_meta(recs):
    """Metadata of a B.5 comparison unit (sheet or physical column), used by the guards."""
    tbs = set()
    for r in recs:
        t = _table_key(r['source_sheet'])
        if t is not None:
            tbs.add(t)
    tids = {r['trip_id'] for r in recs if r.get('trip_id') is not None}
    ordered = [r for r in recs if r.get('stop_order') is not None]
    ordered.sort(key=lambda r: r['stop_order'])
    return {'tb': tbs, 'tid': tids, 'order': [r['stop_name'] for r in ordered]}


def _b5_column_guard_ok(m1, m2):
    """B5_COLUMN_GUARD (within one table, the same physical column?).

    In the original, one printed column is one train. The column survives as the
    transcription's trip_id, so **joining within the same table (page, tb) requires
    equal trip_id**. Different tables/pages cannot be compared, so return True.
    Examples: p51 中國鐵道線 11 has trip_id=6 on all 3 sheets (one through train);
              p62 温泉電軌線 10 has trip_id 1 and 5 (separate trips on two branches).
    """
    if not (m1['tb'] & m2['tb']):
        return True
    if not (m1['tid'] and m2['tid']):
        return True
    return bool(m1['tid'] & m2['tid'])


def _b5_path_guard_ok(m1, m2):
    """B5_PATH_GUARD (did the two arrive at the junction by different routes?).

    Across tables/pages trip_id cannot be compared, so look at the route shape.
    If, at any common station, the sets of earlier stations are both non-empty and
    disjoint, the two reached the junction by different routes = different trains.
    Only earlier stations are checked; checking later ones too would wrongly reject
    summary bands that skip stations (e.g. 常磐線 814, 水戸 straight to 上野).
    """
    s1, s2 = m1['order'], m2['order']
    # Iterate in sorted order (set order varies between runs); the result does not depend on it.
    common = set(s1) & set(s2)
    for name in sorted(common):
        pre1 = set(s1[:s1.index(name)])
        pre2 = set(s2[:s2.index(name)])
        if pre1 and pre2 and not (pre1 & pre2):
            return False
    return True


def _b5_guard_ok(u1, u2, unit_meta):
    """Combine B5_COLUMN_GUARD and B5_PATH_GUARD. Always True if both switches are off."""
    if not (B5_COLUMN_GUARD or B5_PATH_GUARD):
        return True
    m1, m2 = unit_meta.get(u1), unit_meta.get(u2)
    if m1 is None or m2 is None:
        return True
    if B5_COLUMN_GUARD and not _b5_column_guard_ok(m1, m2):
        return False
    if B5_PATH_GUARD and not _b5_path_guard_ok(m1, m2):
        return False
    return True


def _b5_segment_link_ok(u1, u2, unit_meta, sheet_times):
    """Thin wrapper returning only whether a cross-band join (B5_SEGMENT_LINK) is allowed."""
    return _b5_seglink_candidate(u1, u2, unit_meta, sheet_times) is not None


def _b5_seglink_candidate(u1, u2, unit_meta, sheet_times):
    """Cross-band join (B5_SEGMENT_LINK): **join a trip that passes the boundary station
    across the bands of a stacked table**.

    Returns `(gap_minutes, earlier_band, later_band)` when allowed, else None.
    The gap is used by `B5_SEGLINK_NEAREST` to pick only the nearest partner.

    In a table split vertically into segments, a train that does not stop at the
    boundary station has no time printed in either band (the original prints `↓`,
    passing), so there is no common station and B.5 would split the trip.
    Example: p168 函館本線 上リ 2 (黒松內 2.43, 長萬部 ↓, then 八雲 3.59).

    Allowed only if all hold:
      1. different bands of the same table (page + tb)
      2. the same physical column in the original (equal trip_id), as in B5_COLUMN_GUARD
      3. no time overlap, and end of earlier band -> start of later band is 0..B5_SEGLINK_MAXGAP min
    Condition 2 prevents gluing two trains that share one printed column.
    """
    m1, m2 = unit_meta.get(u1), unit_meta.get(u2)
    if m1 is None or m2 is None:
        return None
    # 1. same table
    if not (len(m1['tb']) == 1 and m1['tb'] == m2['tb']):
        return None
    # 2. same physical column
    if not (len(m1['tid']) == 1 and m1['tid'] == m2['tid']):
        return None
    # 3. times are consecutive
    def span(u):
        vals = [v for pairs in sheet_times[u].values()
                for pair in pairs for v in pair if v is not None]
        return (min(vals), max(vals)) if vals else (None, None)
    a1, b1 = span(u1)
    a2, b2 = span(u2)
    if None in (a1, b1, a2, b2):
        return None
    # Either may be the later one, so try both directions (shift=0).
    # B5_SEGLINK_PLUS24: if a sheet missed the +24h for crossing midnight, the later side connects
    # after adding 1440 (extract only fixes midnight within one sheet, so times wrap to 0:xx at a new band).
    # The cross-sheet overnight fix later corrects the times after joining.
    cands = []
    if 0 <= a2 - b1 <= B5_SEGLINK_MAXGAP:
        cands.append((a2 - b1, u1, u2))
    if 0 <= a1 - b2 <= B5_SEGLINK_MAXGAP:
        cands.append((a1 - b2, u2, u1))
    if cands:
        return min(cands)
    if not B5_SEGLINK_PLUS24:
        return None
    # Allow +1440 only between bands whose segment number M is consecutive.
    # In a connection table (e.g. p5) one column is an itinerary of separate trains, so joining bands
    # with non-consecutive M would create non-existent journeys (北京→漢口 followed by 天津→浦口).
    # Segment splits of one table always use consecutive M.
    if not _seg_adjacent(u1, u2):
        return None
    for shift in (1440,):
        if 0 <= (a2 + shift) - b1 <= B5_SEGLINK_MAXGAP:   # u2 is later (missed +24h)
            cands.append(((a2 + shift) - b1, u1, u2))
        if 0 <= (a1 + shift) - b2 <= B5_SEGLINK_MAXGAP:   # u1 is later
            cands.append(((a1 + shift) - b2, u2, u1))
    return min(cands) if cands else None


def _b5_cluster_gap_ok(early, late, gap, find, units, sheet_times):
    """`B5_SEGLINK_CLUSTER_SPAN`: check "no time overlap" of a cross-band join per **cluster
    already joined at common stations**, not per band.

    Condition 3 and B5_SEGLINK_NEAREST work per band (physical column), so a band already
    joined to a later band at a common station could still be joined to another band of a
    different train (p5 connection table, 支那國有鐵道線 trip 1: a band of another 京漢線 train,
    北京 發 23:00 -> 漢口, was attached, and 北京 and 漢口 vanished from the output).
    When ON, do not join if any time of the other cluster falls inside this band's time range
    (the band cannot fit into a gap of that cluster). Middle bands of stacked tables and
    single-time bands are joined as before. Candidates found with +24h (B5_SEGLINK_PLUS24)
    get the same +1440 on the later side."""
    re_, rl = find(early), find(late)
    if re_ == rl:
        return True

    def times(u):
        return [v for pairs in sheet_times[u].values() for pair in pairs for v in pair if v is not None]

    te, tl = times(early), times(late)
    if not te or not tl:
        return True
    shift = gap - (min(tl) - max(te))          # 0 (as is) or 1440 (+24h from B5_SEGLINK_PLUS24)
    lo_l, hi_l = min(tl) + shift, max(tl) + shift
    lo_e, hi_e = min(te), max(te)
    for u in units:
        r = find(u)
        if r == re_ and u != early:
            if any(lo_l < v < hi_l for v in times(u)):
                return False
        elif r == rl and u != late:
            if any(lo_e < v + shift < hi_e for v in times(u)):
                return False
    return True


def _seg_adjacent(u1, u2):
    """Whether two units are in the same table and band (N) with consecutive segment number M."""
    m1 = re.match(r'(p\d{4})_tb(\d{3})-(\d+)-(\d+)#', u1)
    m2 = re.match(r'(p\d{4})_tb(\d{3})-(\d+)-(\d+)#', u2)
    if not (m1 and m2):
        return False
    if m1.group(1, 2, 3) != m2.group(1, 2, 3):
        return False
    return abs(int(m1.group(4)) - int(m2.group(4))) == 1


def split_groups_by_time_consistency(groups):
    """Split one (line, direction, trip_num) into separate trips when sheets disagree on
    the times at common stations.

    Example: 山陽本線 inbound 24 splits into a night train (下關 21:23) and a morning train
    (下關 08:23).

    Algorithm (union-find):
    1. For each sheet build {stop_name: [(dep_min, arr_min), ...]}
    2. Compare the times at common stations for each pair of sheets
       - all common stations consistent -> same cluster (union)
       - any clear mismatch -> different clusters
    3. With several clusters, the largest keeps trip_num; the others get suffixes
       `_b`, `_c`, ... as separate groups
    """
    new_groups = defaultdict(list)
    n_split = 0
    split_log = []
    seglink_log = []   # pairs joined across bands (audit trail)
    seglink_skip_log.clear()   # pairs not joined because of B5_SEGLINK_CLUSTER_SPAN (only when ON)

    for key, records in groups.items():
        line_name, direction, trip_num = key

        # Placeholder numbers (U_...) come from a single sheet; no split needed
        if str(trip_num).startswith('U'):
            new_groups[key].extend(records)
            continue

        # Collect records per unit.
        # With B5_UNIT_COLUMN the unit is the physical column (source_sheet#c{trip_id}), so two
        # same-numbered columns in one sheet (e.g. p175, 366 twice) are split like separate sheets.
        sheet_records = defaultdict(list)
        for r in records:
            if B5_UNIT_COLUMN:
                unit = f"{r['source_sheet']}#c{r['trip_id']}"
            else:
                unit = r['source_sheet']
            sheet_records[unit].append(r)
        sheets = list(sheet_records.keys())

        if len(sheets) <= 1:
            new_groups[key].extend(records)
            continue

        # Per-unit metadata (table, column, station order) for the guards and cross-band joins
        unit_meta = {}
        if B5_COLUMN_GUARD or B5_PATH_GUARD or B5_SEGMENT_LINK:
            for unit, recs in sheet_records.items():
                unit_meta[unit] = _unit_meta(recs)

        # {stop_name: [(dep_min, arr_min)]} for each sheet
        sheet_times = {}
        for sheet, recs in sheet_records.items():
            d = defaultdict(list)
            for r in recs:
                d[r['stop_name']].append((
                    time_to_min(r.get('dep_time')),
                    time_to_min(r.get('arr_time')),
                ))
            sheet_times[sheet] = d

        # Union-Find
        parent = {s: s for s in sheets}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # Consistency check for each pair of sheets
        conflicts = []      # evidence for splits (for the QA log)
        seglinks = []       # pairs joined across bands (audit trail)
        seglink_cands = []  # B5_SEGLINK_NEAREST candidates (gap, earlier band, later band)
        for i in range(len(sheets)):
            for j in range(i + 1, len(sheets)):
                s1, s2 = sheets[i], sheets[j]
                # The guard depends only on the pair, so evaluate it once outside the station loop
                guard_ok = _b5_guard_ok(s1, s2, unit_meta)
                t1, t2 = sheet_times[s1], sheet_times[s2]
                common = set(t1.keys()) & set(t2.keys())
                if not common:
                    # No common station -> cannot check; do not union (becomes its own cluster).
                    # B5_SEGMENT_LINK: but if same table, same physical column and consecutive
                    # times, it is one trip passing the boundary station, so join.
                    if B5_SEGMENT_LINK:
                        cand = _b5_seglink_candidate(s1, s2, unit_meta, sheet_times)
                        if cand is not None:
                            if B5_SEGLINK_NEAREST:
                                seglink_cands.append(cand)   # (gap, earlier band, later band)
                            else:
                                union(s1, s2)
                                seglinks.append((s1, s2))
                                for u in (s1, s2):
                                    SEGLINK_SHEETS[key].add(u.split('#')[0])
                    continue
                consistent = True
                any_match = False
                # Iterate in sorted order so the station recorded as evidence (we break at the first
                #   mismatch) does not depend on set order. The split result does not depend on order.
                for name in sorted(common):
                    if not consistent:
                        break
                    for (dep1, arr1) in t1[name]:
                        if not consistent:
                            break
                        for (dep2, arr2) in t2[name]:
                            # Same-kind comparison (dep-dep, arr-arr) ±5 min; any clear mismatch
                            # means inconsistent. Only if undecidable, fall back to cross-kind
                            # comparison (dep-arr, arr-dep) ±10 min.
                            same_results = [
                                _time_match(dep1, dep2, tol=5),
                                _time_match(arr1, arr2, tol=5),
                            ]
                            if any(r is False for r in same_results):
                                consistent = False
                                _d = (dep1, dep2) if _time_match(dep1, dep2, tol=5) is False \
                                    else (arr1, arr2)
                                conflicts.append((name, s1, _d[0], s2, _d[1]))
                                break
                            if any(r is True for r in same_results):
                                any_match = True
                                continue
                            # B.5 complement (INTEGRATE_B5_COMPLEMENT): an arrival-only / departure-only
                            # hand-over is treated as the same train (not split)
                            if (B5_COMPLEMENT_ENABLED
                                    and guard_ok
                                    and _b5_handoff_ok(dep1, arr1, dep2, arr2)):
                                any_match = True
                                continue
                            # Undecidable by same kind: check continuity across kinds (arr = dep)
                            cross_results = [
                                _time_match(dep1, arr2, tol=10),
                                _time_match(arr1, dep2, tol=10),
                            ]
                            if any(r is False for r in cross_results):
                                # Large time difference at the same station: separate trip
                                consistent = False
                                _d = (dep1, arr2) if _time_match(dep1, arr2, tol=10) is False \
                                    else (arr1, dep2)
                                conflicts.append((name, s1, _d[0], s2, _d[1]))
                                break
                            if any(r is True for r in cross_results):
                                any_match = True
                # Consistent and at least one comparison made -> union
                if consistent and any_match:
                    union(s1, s2)

        # B5_SEGLINK_NEAREST: join only the nearest partner among candidates (in deterministic order).
        if B5_SEGMENT_LINK and B5_SEGLINK_NEAREST and seglink_cands:
            used_early, used_late = set(), set()
            for gap, early, late in sorted(seglink_cands):
                if early in used_early or late in used_late:
                    continue
                # B5_SEGLINK_CLUSTER_SPAN (default ON): do not join if the band does not fit into a gap of the joined cluster
                if B5_SEGLINK_CLUSTER_SPAN and not _b5_cluster_gap_ok(early, late, gap, find, sheets, sheet_times):
                    seglink_skip_log.append({'key': key, 'u1': early, 'u2': late})
                    continue
                used_early.add(early)
                used_late.add(late)
                union(early, late)
                seglinks.append((early, late))
                for u in (early, late):
                    SEGLINK_SHEETS[key].add(u.split('#')[0])

        for (u1, u2) in seglinks:
            seglink_log.append({'key': key, 'u1': u1, 'u2': u2})

        # Split by cluster
        clusters = defaultdict(list)
        for s in sheets:
            clusters[find(s)].append(s)

        if len(clusters) == 1:
            new_groups[key].extend(records)
            continue

        # Several clusters: the largest keeps the key, the others get a suffix
        cluster_list = sorted(clusters.values(),
                              key=lambda c: (-sum(len(sheet_records[s]) for s in c), c[0]))
        for idx, cluster_sheets in enumerate(cluster_list):
            cluster_recs = [r for s in cluster_sheets for r in sheet_records[s]]
            if idx == 0:
                new_key = key
            else:
                # suffix: _b, _c, ...
                suffix = chr(ord('b') + idx - 1) if idx < 26 else f'x{idx}'
                new_trip_num = f'{trip_num}_{suffix}'
                new_key = (line_name, direction, new_trip_num)
            new_groups[new_key].extend(cluster_recs)
        n_split += len(cluster_list) - 1
        split_log.append({
            'key': key,
            'clusters': [(len(c), c) for c in cluster_list],
            # Evidence for the split (station, both sheets, both times). Hints for checking the transcription:
            # ~720 min = likely pm error / 50-70 min = hour digit / small = reused train number
            'conflicts': conflicts[:20],
        })

    return new_groups, n_split, split_log, seglink_log


# ---------------------------------------------------------------------------
# Step C: compute sheet statistics and order sheets by time
# ---------------------------------------------------------------------------

def compute_sheet_stats(records):
    """
    Compute statistics per source_sheet.

    Returns:
        dict: {sheet_name: {'first_min', 'last_min', 'stop_count', 'records'}}
    """
    sheet_records = defaultdict(list)
    for r in records:
        sheet_records[r['source_sheet']].append(r)

    stats = {}
    for sheet, recs in sheet_records.items():
        sorted_recs = sorted(recs, key=lambda x: x['stop_order'])
        times = []
        for r in sorted_recs:
            for key in ('dep_time', 'arr_time'):
                t = time_to_min(r[key])
                if t is not None:
                    times.append(t)
        if not times:
            continue

        # first_min: time of the first record in stop_order (not min(times), which would pick
        # an early-morning time of the next day on a sheet that crosses midnight)
        first_rec = sorted_recs[0]
        first_min = time_to_min(first_rec.get('dep_time') or first_rec.get('arr_time'))
        if first_min is None:
            first_min = min(times)

        # last_min: time of the last record in stop_order
        last_rec = sorted_recs[-1]
        last_min = time_to_min(last_rec.get('arr_time') or last_rec.get('dep_time'))
        if last_min is None:
            last_min = max(times)

        raw_span = max(abs(last_min - first_min), 1)
        stop_density = len(recs) / raw_span
        # detail_score = stop_count * stop_density = stop_count^2 / span
        # Strongly favors more stops, so detailed sheets win over summary sheets
        detail_score = len(recs) * stop_density
        stats[sheet] = {
            'first_min':       first_min,
            'last_min':        last_min,
            'first_stop_name': first_rec.get('stop_name'),
            'last_stop_name':  last_rec.get('stop_name'),
            'stop_count':      len(recs),
            'stop_density':    stop_density,
            'detail_score':    detail_score,
            'records':         sorted_recs,
        }
    return stats


# ---------------------------------------------------------------------------
# Step C.5: chain consecutive segments
# ---------------------------------------------------------------------------
# On pages that split one train into short segment sheets (e.g. p69, p83), greedy selection would
# drop a short first segment as a summary/detail duplicate, and the through trip would lose its first stations.
#
# So obvious consecutive segments are joined into one unit **before** greedy selection, and selection
# works on units (the selection logic itself is unchanged). All three chain conditions are required:
#   1. boundary match: A's last station == B's first station (compared after variant normalization)
#   2. consecutive times: B's first time − A's last time is in [-CHAIN_TOL, CHAIN_DWELL_MAX] min
#                  (allows duplicated boundary rows and junction stops; modulo 1440 for midnight)
#   3. segment split: station sets overlap only at the boundary (<= 1 station), so summaries are never chained
# Links must be mutually unique (on conflict prefer the smaller time gap and finer segment;
# ambiguous links are not made and selection falls back to no chaining).
# Default ON. Previous behavior = INTEGRATE_CHAIN=0.

CHAIN_ENABLED = os.environ.get('INTEGRATE_CHAIN', '1') != '0'
CHAIN_DWELL_MAX = int(os.environ.get('CHAIN_DWELL_MAX', '60'))
CHAIN_TOL = int(os.environ.get('CHAIN_TOL', '15'))

# Hole filling in sheet selection (INTEGRATE_HOLE_FILL, extends E''): recover middle segments missed
#   by the chosen chain by weaving in unchosen sheets that cover them.
#   Default ON. Previous behavior (E'' only) = INTEGRATE_HOLE_FILL=0.
# B.5 complement (INTEGRATE_B5_COMPLEMENT): at a boundary station, an arrival-only / departure-only pair
#   with a gap in [-B5_NEG_TOL, B5_MAXDWELL] min is treated as the same train.
#   Default ON. Previous behavior (split) = INTEGRATE_B5_COMPLEMENT=0.
#   Large negative gaps and same-kind mismatches are still split (kept as clues to pm errors etc.).
HOLE_FILL_ENABLED = os.environ.get('INTEGRATE_HOLE_FILL', '1') != '0'
HOLE_MAXDWELL = int(os.environ.get('HOLE_MAXDWELL', '60'))
B5_COMPLEMENT_ENABLED = os.environ.get('INTEGRATE_B5_COMPLEMENT', '1') != '0'
B5_MAXDWELL = int(os.environ.get('B5_MAXDWELL', '60'))
B5_NEG_TOL = 10
# Use the physical column (source_sheet, trip_id) instead of the sheet as the B.5 unit.
#   A sheet can hold two columns with the same trip_num (e.g. p175, 366 twice); treating the sheet as
#   one block would glue different trains into one trip. Columns get the same checks as sheets.
#   Previous behavior = B5_UNIT=sheet.
B5_UNIT_COLUMN = os.environ.get('B5_UNIT', 'column') != 'sheet'
# Guards for the B.5 complement, so it does not glue different trains with the same number:
#   B5_COLUMN_GUARD: within one table, require equal trip_id (printed column)
#   B5_PATH_GUARD:   across tables/pages, require that the routes before the junction are not disjoint
#   Both default ON. Previous behavior = each =0.
B5_COLUMN_GUARD = os.environ.get('B5_COLUMN_GUARD', '1') == '1'
B5_PATH_GUARD = os.environ.get('B5_PATH_GUARD', '1') == '1'
# Cross-band join (B5_SEGMENT_LINK): join a trip passing the boundary station across bands of a
#   stacked table (otherwise it has no common station and splits into `_b`). Requires same table,
#   same physical column and consecutive times (see _b5_seglink_candidate).
#   Default ON. Previous behavior = B5_SEGMENT_LINK=0.
B5_SEGMENT_LINK = os.environ.get('B5_SEGMENT_LINK', '1') == '1'
# Sheets joined across bands (group key -> {sheet...}). Step E'' uses this to allow alignment
# without a shared station.
SEGLINK_SHEETS = defaultdict(set)
B5_SEGLINK_MAXGAP = int(os.environ.get('B5_SEGLINK_MAXGAP', '240'))
# B5_SEGLINK_PLUS24: cross-band joins also catch a missed +24h (only between bands with consecutive M).
#   Default ON. Previous behavior = B5_SEGLINK_PLUS24=0.
B5_SEGLINK_PLUS24 = os.environ.get('B5_SEGLINK_PLUS24', '1') == '1'
# B5_SEGLINK_NEAREST: a band joins at most one partner on each side (smallest gap first, ties by name).
#   Otherwise every band starting within 240 min of a band's end is joined; in a connection table (p5)
#   this creates non-existent journeys and stations are lost when weaving.
#   Default ON. Previous behavior = B5_SEGLINK_NEAREST=0.
B5_SEGLINK_NEAREST = os.environ.get('B5_SEGLINK_NEAREST', '1') == '1'   # default ON
# B5_SEGLINK_CLUSTER_SPAN: check "no overlap" per cluster already joined at common stations
#   (see _b5_cluster_gap_ok). Pairs not joined go to qa_log as b5_seglink_skip.
#   Default ON. Previous behavior = B5_SEGLINK_CLUSTER_SPAN=0.
B5_SEGLINK_CLUSTER_SPAN = os.environ.get('B5_SEGLINK_CLUSTER_SPAN', '1') == '1'
seglink_skip_log = []   # pairs not joined by B5_SEGLINK_CLUSTER_SPAN (reset by split_groups_by_time_consistency)
# Never output negative times in a trip. Default ON. Previous behavior = INTEGRATE_NO_NEGATIVE=0.
NO_NEGATIVE_TIME = os.environ.get('INTEGRATE_NO_NEGATIVE', '1') == '1'
# Put each trip split by B.5 (b5_split) back on its own time axis. Two same-numbered columns of one sheet
#   (different trains) get the midnight fix as one trip at extraction, so after the split a morning trip can
#   keep next-day times (信越本線 153: 直江津 30:05 發). When ON, a split trip (original key and _b, _c, ...)
#   whose first time is 24:00 or later is shifted back by a multiple of 1440 to start at 0:00-23:59.
#   Trips that were not split (multi-day ships, continuing segments) are untouched.
#   Default ON. Previous behavior = INTEGRATE_B5_SPLIT_REBASE=0. Logged as b5_split_rebase.
B5_SPLIT_REBASE = os.environ.get('INTEGRATE_B5_SPLIT_REBASE', '1') != '0'
# B.7b/B.7c do not drop a trip from a table that lists the time of only one station (departure-only tables,
#   ship tables printing one time per port) just because one station x time matches another line's trip
#   (one match cannot tell a duplicated band from coincidence). Decided by table shape: kept if every trip
#   column of the table has exactly one time (2+ columns). A one-station fragment of a band (other columns
#   have 2+ stations) is still dropped. Logged as crossline_keep_single_time.
#   Default ON. Previous behavior = INTEGRATE_CROSSLINE_KEEP_DEPONLY=0.
CROSSLINE_KEEP_DEPONLY = os.environ.get('INTEGRATE_CROSSLINE_KEEP_DEPONLY', '1') != '0'
# B.7c's tie-break for equal mutual containment ("keep the dedicated table's trip") compares a trip with
#   **at least one** dedicated-table source against one with **none** (checking "all sources dedicated" would
#   treat a trip printed both in its own table and as a band elsewhere as not dedicated). Sources are
#   collected from all original records of the same (line name, direction, number).
#   Default ON. Previous behavior = INTEGRATE_CROSSLINE_EQ_ANY_DEDICATED=0.
CROSSLINE_EQ_ANY_DEDICATED = os.environ.get('INTEGRATE_CROSSLINE_EQ_ANY_DEDICATED', '1') != '0'


def _single_time_sheets(records):
    """Set of sheets where every trip column has exactly one time and there are 2+ columns
    (tables listing the time of a single station)."""
    per = defaultdict(lambda: defaultdict(int))
    for r in records:
        if r.get('dep_time') or r.get('arr_time'):
            per[r.get('source_sheet')][r.get('trip_id')] += 1
    return {sh for sh, d in per.items() if sh and len(d) >= 2 and max(d.values()) == 1}
# E' (non-monotonic removal) Phase 2: for a duplicate with the same station and time, drop one record instead
#   of cutting a whole segment. Default ON. Previous behavior = INTEGRATE_EPRIME_DUP_ONE=0.
#   See the Phase 2 comments in remove_non_monotonic.
EPRIME_DUP_ONE = os.environ.get('INTEGRATE_EPRIME_DUP_ONE', '1') == '1'

# For trips on a line with two different stations of the same name, rows matching
#   disambiguate_stations.SAME_LINE_SPLITS (markers = neighboring stations) are compared as name〈tag〉,
#   so E'' ("station not in the trip") and E' ("non-adjacent duplicate name") do not treat them as one.
#   Output names are unchanged (disambiguate adds the tag later).
#   Default ON. Previous behavior = INTEGRATE_SAME_LINE_SPLIT=0.
SAME_LINE_SPLIT_KEY = os.environ.get('INTEGRATE_SAME_LINE_SPLIT', '1') != '0'

# Keep 著/發 printed only on unchosen sheets. E'' picks up only stations missing from the trip, so an
#   unchosen band/summary's time for an **empty field** of a station already in the trip was lost
#   (e.g. 關西本線 282, 王寺 著 16:35). For unchosen sheets that pass E'' alignment, fill empty fields of
#   existing rows. **No stations are added.** Only values that fit between neighbors
#   (著 <= 發, previous <= 著, 發 <= next). Fields with a different value, or the same time in the other
#   field, are left alone. Default ON. Previous behavior = INTEGRATE_UNSELECTED_KEEP_UNIQUE=0.
UNSELECTED_FILL = os.environ.get('INTEGRATE_UNSELECTED_KEEP_UNIQUE', '1') != '0'

# When values in the same field disagree, take the clearly more detailed table (main table).
#   If a 2-station band is chosen and a 21-station main table is not, stations in both keep the band's value
#   (e.g. `中國鐵道線 outbound 18` at 津山口: band `p0051_tb003-6` says 17:04, main table `p0051_tb002-2`
#   says 17:05; the original prints both). UNSELECTED_FILL fills only empty fields. For unchosen sheets that
#   pass E'' alignment, overwrite an existing value only if all hold:
#     (1) same field (著/著, 發/發) with different values (2) difference <= DETAIL_WINS_MAX_DIFF min
#         (larger means another train with the same number)
#     (3) station density >= DETAIL_WINS_RATIO times, at least as many stations as the current source,
#         and >= DETAIL_WINS_MIN_STOPS stations
#     (4) keeps 著 <= 發 (5) does not pass neighboring stations' times
#   No stations or records change, only cell values. Logged as `unselected_overwrite`.
#   Default ON. Previous behavior = INTEGRATE_DETAIL_WINS=0.
DETAIL_WINS = os.environ.get('INTEGRATE_DETAIL_WINS', '1') != '0'
DETAIL_WINS_MAX_DIFF = int(os.environ.get('INTEGRATE_DETAIL_WINS_MAX_DIFF', '10'))
DETAIL_WINS_RATIO = float(os.environ.get('INTEGRATE_DETAIL_WINS_RATIO', '2.0'))
DETAIL_WINS_MIN_STOPS = int(os.environ.get('INTEGRATE_DETAIL_WINS_MIN_STOPS', '3'))
try:
    from disambiguate_stations import SAME_LINE_SPLITS as _SAME_LINE_SPLITS
except Exception:      # pragma: no cover
    _SAME_LINE_SPLITS = {}


def _split_keys(records, namef=None):
    """Return comparison keys in record order, with rows matching SAME_LINE_SPLITS as
    name〈tag〉 (namef = name normalizer; None means raw stop_name).
    With INTEGRATE_SAME_LINE_SPLIT=0, return namef(name) as is."""
    names = [namef(r['stop_name']) if namef else r['stop_name'] for r in records]
    if not SAME_LINE_SPLIT_KEY or not _SAME_LINE_SPLITS:
        return names
    bases = [str(r['stop_name']).split('〈')[0] for r in records]
    out = list(names)
    for i, r in enumerate(records):
        rules = _SAME_LINE_SPLITS.get((r.get('line_name'), bases[i]))
        if not rules:
            continue
        around = set()
        if i > 0:
            around.add(bases[i - 1])
        if i + 1 < len(records):
            around.add(bases[i + 1])
        for markers, tag in rules:
            if around & markers:
                out[i] = f'{names[i]}〈{tag}〉'
                break
    return out
# E' Phase 2: also merge same-station, same-time duplicates left **adjacent**. INTEGRATE_EPRIME_DUP_ONE
#   only looks at non-adjacent ones, so with 3+ duplicates the rest end up adjacent after one is dropped.
#   Adjacent same names with different times (printed 著 and 發 rows) are untouched
#   (`_same_stop_same_time` returns False). Default ON. Previous behavior = INTEGRATE_EPRIME_DUP_ADJ=0.
EPRIME_DUP_ADJ = os.environ.get('INTEGRATE_EPRIME_DUP_ADJ', '1') == '1'


# Where the original prints 著 and 發 on two rows, keep the value when E' Phase 1 (two trips interleaved)
#   drops the second row. Phase 1 keeps only the first row of each station, which is right (one stop per
#   station), but the dropped row's value is written into the kept row's empty field first.
#   Conditions: (1) the kept row's field is empty (2) the dropped row has only that field (3) after aligning
#   days by multiples of 1440, 著 <= 發 and dwell <= EPRIME_P1_MERGE_DWELL min (4) does not pass neighbors.
#   Existing values are not overwritten; no stations or records are added.
#   Default ON. Previous behavior = INTEGRATE_EPRIME_P1_MERGE=0.
EPRIME_P1_MERGE = os.environ.get('INTEGRATE_EPRIME_P1_MERGE', '1') != '0'
EPRIME_P1_MERGE_DWELL = int(os.environ.get('INTEGRATE_EPRIME_P1_MERGE_DWELL', '60'))

# Do not fire E' Phase 3/4's "time goes back" check on adjacent 著 -> 發 rows of the same station.
#   At a border station (p182 安東) 著 is in Korean time and 發 in Manchurian time, so the time seems to go
#   back and Phase 3 would drop the printed 著. Applies only when the next row is the same station, this row
#   has only 著 and the next has 發. With EXTRACT_TZ_TO_JST=1 the times no longer go back, so this rarely
#   applies (harmless with both on). Default OFF. Enable = INTEGRATE_P3_ADJ_GUARD=1.
EPRIME_P3_ADJ_GUARD = os.environ.get('INTEGRATE_P3_ADJ_GUARD', '0') == '1'


def _adjacent_arr_dep(a, b):
    """Whether a (arrival only) -> b (has departure) are two adjacent rows of one station
    (INTEGRATE_P3_ADJ_GUARD; the caller checks the station name)."""
    return bool(a.get('arr_time')) and not a.get('dep_time') and bool(b.get('dep_time'))


def _align_day(value, ref):
    """Shift value by a multiple of 1440 to the copy nearest to ref."""
    return value + 1440 * int(round((ref - value) / 1440.0))


def _p1_merge_dropped(records, dropped, max_dwell=None):
    """INTEGRATE_EPRIME_P1_MERGE: use rows dropped by Phase 1 to fill empty fields of kept rows.

    Does not modify records; returns a new list (filled rows get new dicts).
    Filled entries in dropped get phase 'p1_著發マージ' (for the QA log).
    """
    if max_dwell is None:
        max_dwell = EPRIME_P1_MERGE_DWELL
    if not dropped:
        return records
    records = list(records)
    idx_of = defaultdict(list)
    for i, r in enumerate(records):
        idx_of[r.get('stop_name')].append(i)

    def _t(r, f):
        return time_to_min(r.get(f))

    def _prev_t(i):
        for j in range(i - 1, -1, -1):
            t = _t(records[j], 'dep_time')
            if t is None:
                t = _t(records[j], 'arr_time')
            if t is not None:
                return t
        return None

    def _next_t(i):
        for j in range(i + 1, len(records)):
            t = _t(records[j], 'arr_time')
            if t is None:
                t = _t(records[j], 'dep_time')
            if t is not None:
                return t
        return None

    for n, (phase, r) in enumerate(dropped):
        if phase != 'p1_二便混入':
            continue
        name = r.get('stop_name')
        if name not in idx_of:
            continue
        od, oa = _t(r, 'dep_time'), _t(r, 'arr_time')
        if (od is None) == (oa is None):
            continue                      # skip rows with both or neither field
        rt = od if od is not None else oa
        best = None
        for i in idx_of[name]:
            kd, ka = _t(records[i], 'dep_time'), _t(records[i], 'arr_time')
            kt = kd if kd is not None else ka
            if kt is None:
                continue
            d = abs(_align_day(rt, kt) - kt)
            if best is None or d < best[0]:
                best = (d, i, kd, ka)
        if best is None:
            continue
        _, i, kd, ka = best
        if ka is None and kd is not None and oa is not None:
            v = _align_day(oa, kd)                 # add 著 to a departure-only row
            if v < 0 or not (0 <= kd - v <= max_dwell):
                continue
            pt = _prev_t(i)
            if pt is not None and v < pt:
                continue
            nr = dict(records[i])
            nr['arr_time'] = minutes_to_hhmm(v)
        elif kd is None and ka is not None and od is not None:
            v = _align_day(od, ka)                 # add 發 to an arrival-only row
            if v < 0 or not (0 <= v - ka <= max_dwell):
                continue
            nt = _next_t(i)
            if nt is not None and v > nt:
                continue
            nr = dict(records[i])
            nr['dep_time'] = minutes_to_hhmm(v)
        else:
            continue
        records[i] = nr
        dropped[n] = ('p1_著發マージ', r)
    return records


def _chain_gap(a_last, b_first):
    """Minutes from A's last time to B's first time (smallest absolute value modulo 1440)."""
    d = (b_first - a_last) % 1440
    if d > 720:
        d -= 1440
    return d


def build_chain_units(sheet_stats):
    """Return unit statistics with consecutive segments chained.

    Returns:
        (unit_stats, unit_members)
        unit_stats:   {name: stats} ready for select_sheets; chains get combined
                      stats, single sheets keep their own.
        unit_members: {unit_name: [member sheet names in chain order]}
    """
    names = list(sheet_stats.keys())
    stations = {}
    for n in names:
        stations[n] = {normalize_kanji_variants(
            normalize_stop_name(r['stop_name']), prefer_new=True)
            for r in sheet_stats[n]['records']}

    def _norm_name(s):
        if s is None:
            return None
        return normalize_kanji_variants(normalize_stop_name(s), prefer_new=True)

    # Enumerate candidate links (conditions 1-3)
    links = []
    for a in names:
        sa = sheet_stats[a]
        for b in names:
            if a == b:
                continue
            sb = sheet_stats[b]
            if _norm_name(sa['last_stop_name']) != _norm_name(sb['first_stop_name']):
                continue
            if len(stations[a] & stations[b]) > 1:
                continue                      # overlap beyond the boundary = not a segment split
            gap = _chain_gap(sa['last_min'], sb['first_min'])
            if not (-CHAIN_TOL <= gap <= CHAIN_DWELL_MAX):
                continue
            links.append((abs(gap), sa['stop_density'] + sb['stop_density'], a, b))

    # Make links mutually unique: smaller time gap first (5-min steps), ties by higher density
    # (stations/min). Preferring fewer stops would let summary links win whenever summary and
    # detail break at the same station; with density, detailed sheets chain and summaries are deduplicated.
    links.sort(key=lambda x: (x[0] // 5, -x[1]))
    succ, pred = {}, {}
    for _gap, _dens, a, b in links:
        if a in succ or b in pred:
            continue                          # keep only the best of competing links
        succ[a] = b
        pred[b] = a

    # Follow chains from their starts (sheets without pred)
    unit_stats, unit_members = {}, {}
    visited = set()
    for n in names:
        if n in visited or n in pred:
            continue
        chain = [n]
        visited.add(n)
        cur = n
        while cur in succ and succ[cur] not in visited:
            cur = succ[cur]
            chain.append(cur)
            visited.add(cur)
        if len(chain) == 1:
            unit_stats[n] = dict(sheet_stats[n])
            unit_stats[n]['via_stops'] = stations[n]
            unit_members[n] = [n]
            continue
        head, tail = sheet_stats[chain[0]], sheet_stats[chain[-1]]
        total_stops = sum(sheet_stats[c]['stop_count'] for c in chain)
        # End = first time plus the accumulated running time of each segment and boundary dwell.
        # Using tail['last_min'] directly breaks ordering for chains crossing midnight (raw clock
        # value smaller than the start), so build a monotonic cumulative value.
        end = head['first_min']
        for i, c in enumerate(chain):
            s = sheet_stats[c]
            end += max(abs(s['last_min'] - s['first_min']), 1)
            if i + 1 < len(chain):
                end += max(_chain_gap(s['last_min'],
                                      sheet_stats[chain[i + 1]]['first_min']), 0)
        span = max(end - head['first_min'], 1)
        uname = f'⛓{chain[0]}+{len(chain) - 1}'
        unit_stats[uname] = {
            'first_min':       head['first_min'],
            'last_min':        end,
            'first_stop_name': head['first_stop_name'],
            'last_stop_name':  tail['last_stop_name'],
            'stop_count':      total_stops,
            'stop_density':    total_stops / span,
            'detail_score':    total_stops * total_stops / span,
            'records':         [],            # filled from member sheets after expansion
            'via_stops':       set().union(*(stations[c] for c in chain)),
        }
        unit_members[uname] = chain
    # Sheets not reached (e.g. cycles where every sheet has pred) become single units
    for n in names:
        if n not in visited:
            unit_stats[n] = dict(sheet_stats[n])
            unit_stats[n]['via_stops'] = stations[n]
            unit_members[n] = [n]
    return unit_stats, unit_members


# ---------------------------------------------------------------------------
# Step D: greedy selection of the best sheet set (drops summary sheets)
# ---------------------------------------------------------------------------

def select_sheets(sheet_stats, tolerance_min=60, max_gap_min=360,
                  overnight_tolerance_min=240):
    """
    From the sheets of one group, select the set that best covers the journey.

    Algorithm:
    - A cluster of sheets sharing the same first_min is taken as the start
      (several tables with the same departure = summary and detailed versions)
    - Without a cluster, start from the smallest first_min
    - Candidates are sheets starting within tolerance_min of the current end
    - Without candidates, try sheets missing the overnight fix (connect at first_min + 1440)
    - Otherwise stop at a gap larger than max_gap_min

    Returns:
        list of sheet names in order
    """
    from collections import Counter

    if not sheet_stats:
        return []

    sorted_sheets = sorted(sheet_stats.items(), key=lambda x: x[1]['first_min'])

    # Decide the main start first_min:
    # a first_min shared by several sheets (count > 1) is the most reliable start
    first_min_counts = Counter(s['first_min'] for _, s in sorted_sheets)
    cluster_sheets = defaultdict(list)
    for n, s in sorted_sheets:
        cluster_sheets[s['first_min']].append((n, s))

    max_count = max(first_min_counts.values())
    if max_count > 1:
        best_start = min(k for k, v in first_min_counts.items() if v == max_count)
    else:
        best_start = sorted_sheets[0][1]['first_min']

    # Refine best_start: the largest cluster may be a mid-journey connection.
    # If sheets of an earlier cluster (count >= 2) pass best_start, that cluster is the true start
    for _ in range(len(first_min_counts)):
        updated = False
        for t in sorted(first_min_counts.keys(), reverse=True):
            if t >= best_start or first_min_counts[t] < 2:
                continue
            max_last = max(s['last_min'] for _, s in cluster_sheets[t])
            if max_last >= best_start - tolerance_min:
                best_start = t
                updated = True
                break
        if not updated:
            break

    # --- Connection-based correction of best_start ---
    # If sheet A's last station == sheet B's first station, A connects to B.
    # A preceding sheet ending at the first station of the best_start sheet is the
    # true start (including overnight).
    best_start_sheets = [s for _, s in sorted_sheets if s['first_min'] == best_start]
    if best_start_sheets:
        best_start_first_stop = best_start_sheets[0]['first_stop_name']
        for _, s in sorted_sheets:
            if s['first_min'] == best_start:
                continue
            # Does this sheet end at the first station of the best_start sheet?
            if (s['last_stop_name'] == best_start_first_stop
                    and s['first_min'] != best_start):
                # Connected -> this sheet may come first; if its last_min < best_start the day
                # changed (e.g. last_min=1875 (=31:15), best_start=900 (=15:00)).
                # Either way the preceding sheet is the start.
                best_start = s['first_min']
                break
        else:
            # Generalization for chains: if a unit passes the candidate's first station as an
            # inner station (a chain that absorbed the boundary), its head is the true start.
            # Ex. 1: two summaries cluster at 名古屋 (890), but a chain from 大垣 (800) contains
            #        名古屋 -> start is 800.
            # Ex. 2: 鹿兒島 24: the night-train fix adds +1440 to the true first sheet, so it looks
            #        "later"; as in the connection fix above, no time condition is applied.
            # (The fix above stops working once the ending sheet is absorbed into a chain.)
            from known_kanji_variants import normalize as _kv_norm
            _tgt = _kv_norm(normalize_stop_name(best_start_first_stop or ''),
                            prefer_new=True)
            for _, s in sorted_sheets:
                _first = _kv_norm(normalize_stop_name(
                    s['first_stop_name'] or ''), prefer_new=True)
                _last = _kv_norm(normalize_stop_name(
                    s['last_stop_name'] or ''), prefer_new=True)
                if (s['first_min'] != best_start
                        and _tgt and _tgt in s.get('via_stops', ())
                        and _first != _tgt and _last != _tgt):
                    best_start = s['first_min']
                    break

    # Journey start station: most common first_stop_name among sheets with first_min == best_start
    start_stop_names = [s['first_stop_name'] for _, s in sorted_sheets
                        if s['first_min'] == best_start and s['first_stop_name'] is not None]
    journey_start_stop = max(set(start_stop_names), key=start_stop_names.count) if start_stop_names else None

    selected = []
    used        = set()
    defer_count = {}   # sheet name -> times deferred (prevents infinite loops)
    MAX_DEFER   = 5
    current_end = None

    def is_restart_sheet(s):
        """Whether a sheet restarts from the journey's start station (another train):
        same start station but a time different from best_start.
        """
        return (journey_start_stop is not None
                and s['first_stop_name'] == journey_start_stop
                and s['first_min'] != best_start)

    def mark_used_except_overnight(candidate_list, cur_end):
        """
        Add candidates that cannot be an overnight continuation to used.
        Overnight candidate: first_min < best_start - 15 and last_min + 1440 > cur_end
        """
        for n, s in candidate_list:
            if n in used:
                continue
            is_overnight_cand = (
                cur_end is not None
                and s['first_min'] < best_start - 15
                and s['last_min'] + 1440 > cur_end
                and defer_count.get(n, 0) < MAX_DEFER
            )
            if is_overnight_cand:
                defer_count[n] = defer_count.get(n, 0) + 1
            else:
                used.add(n)

    while True:
        unused = [(n, s) for n, s in sorted_sheets if n not in used]
        if not unused:
            break

        if current_end is None:
            # All sheets of the main start cluster are candidates, except sheets starting 15+ min
            # before best_start (possible overnight continuation) and restarts from the start station
            start_pool = [(n, s) for n, s in unused
                          if s['first_min'] >= best_start - 15
                          and s['first_min'] <= best_start + tolerance_min
                          and not is_restart_sheet(s)]
            candidates = start_pool if start_pool else unused
        else:
            # Regular candidates start within ± tolerance of the current end
            # (restarts from the start station are other trains and excluded)
            regular = [(n, s) for n, s in unused
                       if s['first_min'] >= current_end - tolerance_min
                       and s['first_min'] <= current_end + tolerance_min
                       and not is_restart_sheet(s)]
            # Sheets missing the overnight fix: +1440 is near current_end (lower bound limited by tolerance_min)
            overnight_pool = [(n, s) for n, s in unused
                              if s['first_min'] < best_start - 15
                              and s['first_min'] + 1440 >= current_end - tolerance_min
                              and s['first_min'] + 1440 <= current_end + overnight_tolerance_min]
            candidates = regular + [x for x in overnight_pool if x not in regular]

        if not candidates:
            # Try sheets missing the overnight fix (+1440 within overnight_tolerance),
            # excluding restarts from the start station
            overnight_ext = [(n, s) for n, s in unused
                             if s['first_min'] + 1440 >= current_end - tolerance_min
                             and s['first_min'] + 1440 <= current_end + overnight_tolerance_min
                             and s['last_min'] + 1440 > current_end
                             and not is_restart_sheet(s)]
            if overnight_ext:
                best_name, best_stats = max(overnight_ext,
                                            key=lambda x: (x[1]['last_min'], x[1]['stop_count']))
                selected.append(best_name)
                used.add(best_name)
                # Mark other unused non-overnight sheets as used
                mark_used_except_overnight(
                    [(n, s) for n, s in unused if n != best_name],
                    best_stats['last_min'] + 1440
                )
                current_end = best_stats['last_min'] + 1440
                continue

            # Candidates by station name: sheets starting where the last sheet ends
            # (for international connections with long waits)
            if selected:
                last_selected_stats = sheet_stats[selected[-1]]
                last_stop = last_selected_stats.get('last_stop_name')
                if last_stop:
                    connected = [(n, s) for n, s in unused
                                 if s['first_stop_name'] == last_stop
                                 and not is_restart_sheet(s)]
                    if connected:
                        # The connecting sheet may be earlier than current_end (next afternoon
                        # after an overnight) -> select with the overnight fix
                        best_name, best_stats = max(connected,
                                                    key=lambda x: (x[1]['stop_count'], x[1]['last_min']))
                        selected.append(best_name)
                        used.add(best_name)
                        # Update current_end; add 1440 if the sheet's last_min is smaller
                        new_end = best_stats['last_min']
                        if new_end < current_end:
                            new_end += 1440
                        current_end = new_end
                        continue

            if not candidates:
                # Check the gap: only positive gaps allowed (negative = before the start -> another train)
                next_sheet = min(unused, key=lambda x: x[1]['first_min'])
                gap = next_sheet[1]['first_min'] - current_end
                if gap < 0 or gap > max_gap_min:
                    break   # negative (another train) or too large -> end of journey
                candidates = [next_sheet]

        # Keep only candidates that extend beyond the current end
        extending = [(n, s) for n, s in candidates
                     if current_end is None or s['last_min'] > current_end]


        if not extending:
            # Try candidates that extend after the overnight fix (overnight_tolerance),
            # excluding restarts from the start station
            overnight_ext = [(n, s) for n, s in candidates
                             if current_end is not None
                             and s['last_min'] + 1440 > current_end
                             and s['first_min'] + 1440 <= current_end + overnight_tolerance_min
                             and not is_restart_sheet(s)]
            if overnight_ext:
                best_name, best_stats = max(overnight_ext,
                                            key=lambda x: (x[1]['last_min'], x[1]['stop_count']))
                selected.append(best_name)
                used.add(best_name)
                # Mark all unused sheets except overnight candidates as used
                mark_used_except_overnight(
                    [(n, s) for n, s in unused if n != best_name],
                    best_stats['last_min'] + 1440
                )
                current_end = best_stats['last_min'] + 1440
                continue

            # Mark candidates that cannot be an overnight continuation as used
            mark_used_except_overnight(candidates, current_end)
            continue

        # Sheet choice:
        # Start (current_end is None):
        #   - top detail_score >= 2x the second -> density first (clearly more detailed sheet)
        #   - close scores -> coverage (last_min) first (widest coverage)
        # Extension (current_end is not None):
        #   - stop_density first (most detailed next sheet), ties by last_min
        density_mode_start = False
        if current_end is None and len(extending) >= 2:
            sorted_ext = sorted(extending, key=lambda x: x[1]['detail_score'], reverse=True)
            top_score  = sorted_ext[0][1]['detail_score']
            sec_score  = sorted_ext[1][1]['detail_score']
            if top_score >= 2 * sec_score:
                # A clearly denser sheet exists -> density mode
                best_name, best_stats = sorted_ext[0]
                density_mode_start = True
            else:
                # Scores are close -> prefer coverage
                best_name, best_stats = max(extending,
                                            key=lambda x: (x[1]['last_min'], x[1]['detail_score']))
        else:
            # Extension: prefer stop_density (detailed sheet for the next segment)
            best_name, best_stats = max(extending,
                                        key=lambda x: (x[1]['stop_density'], x[1]['last_min']))
        selected.append(best_name)
        used.add(best_name)
        if density_mode_start:
            # Start chosen in density mode: discard other start candidates as other trains
            mark_used_except_overnight(
                [(n, s) for n, s in candidates if n != best_name],
                best_stats['last_min']
            )
        else:
            # Discard unused sheets that do not extend beyond best
            # (including leftovers from earlier candidates)
            mark_used_except_overnight(
                [(n, s) for n, s in unused if n != best_name and s['last_min'] <= best_stats['last_min']],
                best_stats['last_min']
            )
        current_end = best_stats['last_min']

    return selected


# ---------------------------------------------------------------------------
# Removal of non-monotonic times
# ---------------------------------------------------------------------------

def _same_stop_same_time(a, b):
    """Same station and all time fields present in both are equal (INTEGRATE_EPRIME_DUP_ONE).

    Fields present on only one side (e.g. band has only 發, detail has both) are not compared.
    False if no field is present on both sides (nothing to compare).
    """
    if a['stop_name'] != b['stop_name']:
        return False
    compared = False
    for f in ('dep_time', 'arr_time'):
        va, vb = a.get(f), b.get(f)
        if va and vb:
            if time_to_min(va) != time_to_min(vb):
                return False
            compared = True
    return compared


def remove_non_monotonic(records, dropped=None):
    """
    Remove records that make times non-monotonic in an integrated record list.

    Phase 1: two interleaved trips
      If many stop_names appear twice in one trip, two trips are interleaved.
      Keep the first occurrence of each duplicated station (train A), drop the second (train B).

    Phase 2-4: remaining non-monotonic records
      e.g. leftover summary/detail duplicates; drop records of already-seen stations whose time goes back.

    dropped: for the QA log. If a list is given, (phase, record) is appended.
      None (default) records nothing; the removal itself is unchanged.
    """
    if dropped is None:
        dropped = []            # throwaway (caller does not collect it)
    if len(records) <= 1:
        return records

    # --- Phase 1: detect two interleaved trips ---
    from collections import Counter
    name_counts = Counter(r['stop_name'] for r in records)
    dup_names = {n for n, c in name_counts.items() if c >= 2}

    # Many duplicated station names -> two interleaved trips
    had_interleaving = False
    if len(dup_names) >= len(name_counts) * 0.4 and len(dup_names) >= 2:
        had_interleaving = True
        # Keep only the first occurrence of each duplicated name
        seen = set()
        phase1 = []
        for r in records:
            name = r['stop_name']
            if name in dup_names:
                if name in seen:
                    dropped.append(('p1_二便混入', r))
                    continue  # second or later -> drop
                seen.add(name)
            phase1.append(r)
        records = phase1

        # Extra filter: keep only strictly increasing times
        # (also drops stations unique to train B)
        strict = [records[0]]
        prev_max = time_to_min(records[0].get('dep_time') or records[0].get('arr_time'))
        for r in records[1:]:
            cur_time = time_to_min(r.get('dep_time') or r.get('arr_time'))
            if cur_time is None:
                strict.append(r)
                continue
            if prev_max is not None and cur_time < prev_max:
                dropped.append(('p1_二便混入', r))
                continue  # goes back -> drop
            strict.append(r)
            if prev_max is None or cur_time > prev_max:
                prev_max = cur_time
        records = strict

        # INTEGRATE_EPRIME_P1_MERGE: move values of dropped rows into empty fields of kept rows.
        # Default ON. Previous behavior = INTEGRATE_EPRIME_P1_MERGE=0.
        if EPRIME_P1_MERGE:
            records = _p1_merge_dropped(records, dropped)

    # --- Phase 2: resolve non-adjacent duplicate station names ---
    # Detect and remove summary+detail duplicates and invalid segment joins.
    #
    # If the same name appears at prev_i and i (i > prev_i+1):
    #   option A: keep records[i:] (summary first -> prefer the later detail)
    #   option B: keep records[:prev_i+1] (invalid segment at the end -> keep the first part)
    # Take the option keeping more records; do nothing if it keeps less than 50%.

    original_len = len(records)
    changed = True
    while changed:
        changed = False
        name_positions = {}
        keys2 = _split_keys(records)             # same-name different stations get different keys (INTEGRATE_SAME_LINE_SPLIT)
        for i, r in enumerate(records):
            name = keys2[i]
            if name in name_positions:
                prev_i = name_positions[name]
                if EPRIME_DUP_ADJ and i - prev_i == 1 and \
                        _same_stop_same_time(records[prev_i], r):
                    # INTEGRATE_EPRIME_DUP_ADJ: also merge adjacent same-station, same-time rows
                    #   (left adjacent after a non-adjacent duplicate was dropped). Adjacent rows with
                    #   different times (printed 著/發 rows) are excluded by _same_stop_same_time.
                    keep = records[prev_i]
                    fill = {f: r[f] for f in ('dep_time', 'arr_time')
                            if not keep.get(f) and r.get(f)}
                    dropped.append(('p2_同駅同時刻重複', r))
                    if fill:
                        keep = dict(keep)
                        keep.update(fill)
                        records = (records[:prev_i] + [keep] + records[i + 1:])
                    else:
                        records = records[:i] + records[i + 1:]
                    changed = True
                    break
                if i - prev_i > 1:  # non-adjacent
                    # INTEGRATE_EPRIME_DUP_ONE: a same-station, same-time duplicate is one station listed
                    #   twice, so drop **one record** instead of cutting a whole part, which would also lose
                    #   the stations in between (e.g. 常磐線 上リ 804: a 2-station connecting band attached
                    #   at the end removed 9 stations). Duplicates with different times (another train woven
                    #   in) are still cut. Fields present only in the dropped row are copied first.
                    #   Default ON. Previous behavior = INTEGRATE_EPRIME_DUP_ONE=0.
                    if EPRIME_DUP_ONE and _same_stop_same_time(records[prev_i], r):
                        keep = records[prev_i]
                        fill = {f: r[f] for f in ('dep_time', 'arr_time')
                                if not keep.get(f) and r.get(f)}
                        dropped.append(('p2_同駅同時刻重複', r))
                        if fill:
                            # Do not modify the dict shared with the caller (replace it)
                            keep = dict(keep)
                            keep.update(fill)
                            records = (records[:prev_i] + [keep]
                                       + records[prev_i + 1:i] + records[i + 1:])
                        else:
                            records = records[:i] + records[i + 1:]
                        changed = True
                        break

                    option_a = records[i:]             # keep the later part
                    option_b = records[:prev_i + 1]    # keep the earlier part

                    # Take the option keeping more records
                    best = option_a if len(option_a) >= len(option_b) else option_b

                    # Skip if less than 50% would remain (e.g. round trips)
                    if len(best) >= original_len * 0.5:
                        best_ids = {id(x) for x in best}
                        for x in records:
                            if id(x) not in best_ids:
                                dropped.append(('p2_非隣接重複', x))
                        records = best
                        changed = True
                        break
            name_positions[name] = i

    # --- Phase 3: drop summary records whose station appears again later ---
    name_last_idx = {}
    keys3 = _split_keys(records)                 # same-name different stations get different keys (INTEGRATE_SAME_LINE_SPLIT)
    for i, r in enumerate(records):
        name_last_idx[keys3[i]] = i

    phase3 = []
    for i, r in enumerate(records):
        cur_time = time_to_min(r.get('dep_time') or r.get('arr_time'))
        name = keys3[i]
        if cur_time is not None and i < len(records) - 1:
            next_time = time_to_min(records[i+1].get('dep_time') or records[i+1].get('arr_time'))
            if (next_time is not None and next_time < cur_time
                    and name_last_idx.get(name, i) > i):
                # INTEGRATE_P3_ADJ_GUARD: next row is the 發 row of the same station -> not a summary duplicate
                if (EPRIME_P3_ADJ_GUARD and keys3[i+1] == name
                        and name_last_idx.get(name, i) == i + 1
                        and _adjacent_arr_dep(r, records[i+1])):
                    phase3.append(r)
                    continue
                dropped.append(('p3_概略除去', r))
                continue
        phase3.append(r)

    # --- Phase 4: final pass dropping already-seen stations whose time goes back ---
    result = [phase3[0]] if phase3 else []
    keys4 = _split_keys(phase3)                  # same-name different stations get different keys (INTEGRATE_SAME_LINE_SPLIT)
    seen_names = {keys4[0]} if phase3 else set()
    prev_max = time_to_min(phase3[0].get('dep_time') or phase3[0].get('arr_time')) if phase3 else None

    for j, r in enumerate(phase3[1:], 1):
        cur_time = time_to_min(r.get('dep_time') or r.get('arr_time'))
        name = keys4[j]

        if cur_time is None:
            result.append(r)
            seen_names.add(name)
            continue

        if prev_max is not None and cur_time < prev_max:
            if name in seen_names:
                # INTEGRATE_P3_ADJ_GUARD: keep if the previous row is the 著 row of the same station (kept in Phase 3)
                if not (EPRIME_P3_ADJ_GUARD and keys4[j-1] == name
                        and _adjacent_arr_dep(phase3[j-1], r)
                        and result and result[-1] is phase3[j-1]):
                    dropped.append(('p4_最終逆行', r))
                    continue

        result.append(r)
        seen_names.add(name)
        if prev_max is None or cur_time > prev_max:
            prev_max = cur_time

    return result


# ---------------------------------------------------------------------------
# Step E: merge boundary stops
# ---------------------------------------------------------------------------

# If a sheet being appended has stations earlier than the last time of the trip assembled so far, insert
#   them at their time position instead of appending them at the end. _assemble just appends sheets in
#   order, so a later-chosen sheet covering an earlier segment ended up at the back (e.g. 山陰及東海道線
#   上リ 654 got the stop order 舞鶴→綾部→新舞鶴→京都). Same idea as E'' weaving, applied to chosen sheets.
#   Only if all four hold (otherwise append as before):
#     (1) the rows going back in time are consecutive at the start of the sheet (no timeless row first,
#         no later row going back again)
#     (2) each such row is either a station not in the trip or the same station with the same time
#         (same station with a different time: untouched)
#     (3) at least one station is not in the trip (pure duplicates are left to E')
#     (4) somewhere the sheet has a row with the same station and time as the trip (same train, same day)
#   Same-station, same-time rows fill empty fields of the trip's row and are then dropped.
#   select_sheets is unchanged. Default ON. Previous behavior = INTEGRATE_CONCAT_TIME_ORDER=0.
CONCAT_TIME_ORDER = os.environ.get('INTEGRATE_CONCAT_TIME_ORDER', '1') != '0'


def _concat_backward_insert(integrated, recs):
    """INTEGRATE_CONCAT_TIME_ORDER: insert the leading rows of recs (the next sheet) that are earlier
    than the trip's last time at their time position in the trip.

    Conditions (1)-(4) are in the CONCAT_TIME_ORDER comment; otherwise return the arguments unchanged.
    Rows of integrated (dict copies made by _assemble) are modified in place only to fill empty fields.

    Returns: (new integrated, remaining recs, list of inserted rows)
    """
    if not integrated or not recs:
        return integrated, recs, []

    def _n(s):
        return normalize_kanji_variants(normalize_stop_name(s), prefer_new=True)

    def _rt(r):
        return time_to_min(r.get('dep_time') or r.get('arr_time'))

    jt = [_rt(r) for r in integrated]
    known = [t for t in jt if t is not None]
    if not known:
        return integrated, recs, []
    jmax = max(known)
    n_back = 0
    for r in recs:
        t = _rt(r)
        if t is None or t >= jmax:
            break
        n_back += 1
    if n_back == 0:
        return integrated, recs, []
    for r in recs[n_back:]:                                  # ①
        t = _rt(r)
        if t is not None and t < jmax:
            return integrated, recs, []
    jkeys = _split_keys(integrated, _n)
    rkeys = _split_keys(recs, _n)

    def _same_rows(q):
        return [i for i, jk in enumerate(jkeys)
                if jk == rkeys[q] and _same_stop_same_time(integrated[i], recs[q])]

    if not any(_same_rows(q) for q in range(len(recs))):   # ④
        return integrated, recs, []
    jset = set(jkeys)
    plan = []
    for q in range(n_back):
        if rkeys[q] not in jset:
            plan.append((q, None))
            continue
        hit = _same_rows(q)
        if not hit:
            return integrated, recs, []                      # ②
        plan.append((q, hit[0]))
    if all(i is not None for _, i in plan):                  # ③
        return integrated, recs, []
    out = list(integrated)
    ot = list(jt)
    inserted = []
    for q, i in plan:
        r = recs[q]
        if i is not None:
            keep = integrated[i]
            for f in ('dep_time', 'arr_time'):
                if not keep.get(f) and r.get(f):
                    keep[f] = r[f]
            continue
        t = _rt(r)
        pos = 0
        for k, tt in enumerate(ot):
            if tt is not None and tt <= t:
                pos = k + 1
        out.insert(pos, r)
        ot.insert(pos, t)
        inserted.append(r)
    return out, recs[n_back:], inserted


def merge_boundary(prev_recs, next_recs):
    """
    If the last of prev_recs and the first of next_recs have the same stop_name,
    merge their arr and dep into one record.

    Returns:
        (merged_prev_recs, trimmed_next_recs)
    """
    if not prev_recs or not next_recs:
        return prev_recs, next_recs

    last  = prev_recs[-1]
    first = next_recs[0]

    if last['stop_name'] != first['stop_name']:
        return prev_recs, next_recs

    # Merge: take arr (and dep) from whichever side has it
    merged = dict(last)
    if merged.get('arr_time') is None and first.get('arr_time') is not None:
        merged['arr_time'] = first['arr_time']
    if merged.get('dep_time') is None and first.get('dep_time') is not None:
        merged['dep_time'] = first['dep_time']

    return prev_recs[:-1] + [merged], next_recs[1:]


# ---------------------------------------------------------------------------
# Main integration
# ---------------------------------------------------------------------------

# Stop the overnight fix (fix_overnight_sheets) from shifting a whole trip one day later when the first sheet
#   is a long daytime run, by checking the times at common stations. fix_overnight_sheets adds +24h to the
#   (smaller) earlier side of a gap of 6h+ between sheet start times, so a daytime first sheet running 6h+ was
#   mistaken for a night train (e.g. 中央本線 上リ 702 departing 名古屋 at 30:05).
#   When ON, each sheet taken as next-day is compared with the later sheets at common stations:
#     some station matches only on the same day (within INTEGRATE_OVERNIGHT_ANCHOR_TOL min) and none on the
#       next day (1440 ± TOL) -> do not shift that sheet
#     otherwise (next-day match, no match, or no common station) -> shift as before (safe side)
#   Default ON. Previous behavior = INTEGRATE_OVERNIGHT_ANCHOR=0. Logged as `overnight_anchor_same_day`.
OVERNIGHT_ANCHOR = os.environ.get('INTEGRATE_OVERNIGHT_ANCHOR', '1') != '0'
OVERNIGHT_ANCHOR_TOL = int(os.environ.get('INTEGRATE_OVERNIGHT_ANCHOR_TOL', '60'))


def _overnight_anchor_votes(low, highs, tol=None):
    """INTEGRATE_OVERNIGHT_ANCHOR: compare station times of sheet low (taken as next-day) with the
    same stations in the later sheets highs.

    A station counts only if it matches exactly one of same day (diff <= tol) or next day (|diff - 1440| <= tol).
    Returns: (stations matching the same day, stations matching the next day)
    """
    if tol is None:
        tol = OVERNIGHT_ANCHOR_TOL

    def _n(s):
        return normalize_kanji_variants(normalize_stop_name(s), prefer_new=True)

    ht = defaultdict(list)
    for h in highs:
        for r in h['records']:
            for f in ('dep_time', 'arr_time'):
                t = time_to_min(r.get(f))
                if t is not None:
                    ht[_n(r['stop_name'])].append(t)
    same = nxt = 0
    for r in low['records']:
        us = ht.get(_n(r['stop_name']))
        if not us:
            continue
        ts = [t for t in (time_to_min(r.get(f)) for f in ('dep_time', 'arr_time')) if t is not None]
        if not ts:
            continue
        d_same = min(abs(u - t) for u in us for t in ts)
        d_next = min(abs(u - t - 1440) for u in us for t in ts)
        if d_same <= tol < d_next:
            same += 1
        elif d_next <= tol < d_same:
            nxt += 1
    return same, nxt


def fix_overnight_sheets(sheet_stats):
    """
    Fix midnight crossings between sheets.

    extract_stop_times.py only fixes midnight within a sheet, so a crossing between sheets
    (e.g. 下關 10:10 -> 廣島 04:10, really 28:10 next day) leaves a small first_min.

    Method: sort the first_min of all sheets and find the largest gap. If the gap is 6h (360 min)
    or more and the sheets below it are the minority, treat them as next-day sheets and add 1440.

    INTEGRATE_OVERNIGHT_ANCHOR (default ON): next-day sheets that match the later sheets only on the
    same day are not shifted. Returns the sheets not shifted [(name, matching stations)]
    (empty or None when nothing is fixed or the switch is OFF).
    """
    if len(sheet_stats) < 3:
        return

    first_mins = sorted(s['first_min'] for s in sheet_stats.values())

    # Find the largest gap
    max_gap = 0
    gap_index = 0
    for i in range(len(first_mins) - 1):
        gap = first_mins[i + 1] - first_mins[i]
        if gap > max_gap:
            max_gap = gap
            gap_index = i

    if max_gap < 360:  # under 6h -> no midnight crossing
        return

    threshold = first_mins[gap_index]
    low_count = gap_index + 1
    high_count = len(first_mins) - low_count

    if low_count >= high_count:  # fix only a minority
        return

    # INTEGRATE_OVERNIGHT_ANCHOR: the later sheets (fixed before shifting)
    highs = ([s for s in sheet_stats.values() if s['first_min'] > threshold]
             if OVERNIGHT_ANCHOR else None)
    kept = []
    # Add 1440 to the earlier-side sheets
    for name, stats in sheet_stats.items():
        if stats['first_min'] <= threshold:
            if OVERNIGHT_ANCHOR:
                same, nxt = _overnight_anchor_votes(stats, highs)
                if same and not nxt:
                    kept.append((name, same))
                    continue
            stats['first_min'] += 1440
            stats['last_min'] += 1440
            stats['records'] = apply_time_offset(stats['records'], 1440)
    return kept


def integrate_group(key, records, qa_rows=None):
    """
    Integrate the records of one group (one line, direction and train number) into a
    single list with stop_sequence.

    qa_rows: list for the QA log (None records nothing). Records dropped by E' and sheets
      not chosen by select_sheets are appended as dict rows.

    Returns:
        (integrated_records, warnings)
    """
    sheet_stats = compute_sheet_stats(records)
    overnight_kept = fix_overnight_sheets(sheet_stats) or []
    if overnight_kept and qa_rows is not None:
        # INTEGRATE_OVERNIGHT_ANCHOR (default ON): log next-day sheets left unshifted (same-day match)
        for o_sheet, n_same in overnight_kept:
            qa_rows.append({
                'key': f'{key[0]}__{key[1]}__{key[2]}',
                'kind': 'overnight_anchor_same_day', 'sheet': o_sheet,
                'stop_name': '', 'dep_time': '', 'arr_time': '',
                'detail': f'日跨ぎ補正でずらさなかった（遅い側のシートと同じ日の時刻で合う駅 {n_same}・翌日で合う駅 0・INTEGRATE_OVERNIGHT_ANCHOR）',
            })

    def _assemble(selected):
        """Build the final trip from the chosen sheets: concatenate, merge boundaries, E',
        fix direction, assign stop_sequence.

        Returns: (integrated, warnings, eprime_dropped)
        """
        warnings = []
        if not selected:
            return [], warnings, []

        integrated = []
        concat_inserted = []        # INTEGRATE_CONCAT_TIME_ORDER: rows inserted at their time position (for the QA log)
        for i, sheet in enumerate(selected):
            # Copy dicts so that assembling twice (chain/legacy comparison) does not write
            # stop_sequence into shared records (values are unchanged)
            recs = [dict(r) for r in sheet_stats[sheet]['records']]
            if i == 0:
                integrated = recs
            else:
                # Cross-sheet overnight fix
                last_time  = time_to_min(integrated[-1].get('dep_time') or integrated[-1].get('arr_time'))
                first_time = time_to_min(recs[0].get('dep_time') or recs[0].get('arr_time'))
                if last_time is not None and first_time is not None and first_time < last_time - 90:
                    # Crossed midnight: add a multiple of 1440.
                    # Threshold 90 min: 30 min also fires on route overlaps (e.g. 名古屋→大府), while real
                    # midnight crossings go back by hundreds of minutes.
                    # offset is the smallest multiple of 1440 with first_time + offset >= last_time - 90.
                    # ((last-first)//1440+1)*1440 would overshoot to 2880 when the previous sheet already
                    # has +1440 and the boundary time is duplicated (last-first exactly 1440), creating
                    # +24h jumps.
                    offset = ((last_time - first_time - 90 + 1439) // 1440) * 1440
                    recs = apply_time_offset(recs, offset)
                    # Recompute first_time after the fix
                    first_time_new = time_to_min(recs[0].get('dep_time') or recs[0].get('arr_time'))
                    if first_time_new is not None and first_time_new < last_time - 90:
                        # Still going back: record a warning
                        warnings.append({
                            'key':        str(key),
                            'issue':      '時刻逆転（overnight 補正後も継続）',
                            'prev_sheet': integrated[-1]['source_sheet'],
                            'prev_stop':  integrated[-1]['stop_name'],
                            'prev_time':  integrated[-1].get('dep_time') or integrated[-1].get('arr_time'),
                            'next_sheet': recs[0]['source_sheet'],
                            'next_stop':  recs[0]['stop_name'],
                            'next_time':  recs[0].get('dep_time') or recs[0].get('arr_time'),
                        })

                # INTEGRATE_CONCAT_TIME_ORDER (default ON): insert earlier stations at their time position
                if CONCAT_TIME_ORDER:
                    integrated, recs, ins = _concat_backward_insert(integrated, recs)
                    concat_inserted.extend(ins)
                integrated, recs = merge_boundary(integrated, recs)
                integrated = integrated + recs

        # Remove non-monotonic times (interleaved trips or summary/detail duplicates)
        eprime_dropped = []
        if concat_inserted:
            # INTEGRATE_CONCAT_TIME_ORDER audit: QA log kind eprime_c14_時刻順に挿入 (inserted rows, not dropped ones)
            eprime_dropped.extend(('c14_時刻順に挿入', r) for r in concat_inserted)
        integrated = remove_non_monotonic(integrated, dropped=eprime_dropped)

        # Make sure stop_sequence follows time (direction of travel); reverse if not.
        # GTFS requires stop_sequence to increase along the trip, and inbound sheets may
        # number stop_order in line order, opposite to time.
        times = []
        for r in integrated:
            t = time_to_min(r.get('dep_time') or r.get('arr_time'))
            if t is not None:
                times.append(t)
        if len(times) >= 2:
            inc = sum(1 for i in range(1, len(times)) if times[i] > times[i - 1])
            dec = sum(1 for i in range(1, len(times)) if times[i] < times[i - 1])
            if dec > inc * 2:
                integrated = list(reversed(integrated))

        # Assign stop_sequence
        for seq, r in enumerate(integrated, 1):
            r['stop_sequence'] = seq

        return integrated, warnings, eprime_dropped

    def _final_coverage(integrated):
        """Coverage of the final output = (unique stations, records)."""
        st = {normalize_kanji_variants(normalize_stop_name(r['stop_name']),
                                       prefer_new=True) for r in integrated}
        return (len(st), len(integrated))

    def _weave_parallel(integrated, selected):
        """Step E'' (weave in unique stations of parallel sheets).

        Unchosen sheets in the same B.5 cluster show the same train on another page.
        If one has **stations not in the trip**, and aligns on shared stations (day offset;
        median residual <= 5 min, max 10 min), insert those records at their time position.
        This recovers stations lost from parallel sheets (e.g. 37 stations on a detailed
        日豐 page). Stations that cannot be aligned or have no time are not woven in.

        Returns: (integrated, woven=[(sheet, [station...]), ...])
        """
        if not integrated:
            return integrated, []

        def _n(s):
            return normalize_kanji_variants(normalize_stop_name(s),
                                            prefer_new=True)

        jt = [time_to_min(r.get('dep_time') or r.get('arr_time'))
              for r in integrated]
        jkeys = _split_keys(integrated, _n)          # same-name different stations get different keys (INTEGRATE_SAME_LINE_SPLIT)
        jnames = set(jkeys)
        jtimes_by_name = defaultdict(list)
        for k_, t in zip(jkeys, jt):
            if t is not None:
                jtimes_by_name[k_].append(t)

        woven = []
        for sheet in sheet_stats:
            if sheet in selected:
                continue
            recs = sheet_stats[sheet]['records']
            rkey_of = {id(r): k_ for r, k_ in zip(recs, _split_keys(recs, _n))}
            uniq = [r for r in recs if rkey_of[id(r)] not in jnames]
            if not uniq:
                continue
            # Alignment: estimate the day offset k*1440 from time differences at shared stations
            diffs = []
            for r in recs:
                nm = rkey_of[id(r)]
                t = time_to_min(r.get('dep_time') or r.get('arr_time'))
                if t is None or nm not in jtimes_by_name:
                    continue
                best = min(jtimes_by_name[nm], key=lambda tj: abs(tj - t))
                diffs.append(best - t)
            if not diffs:
                # Sheets joined across bands (B5_SEGMENT_LINK) are known to be the same column
                # with consecutive times, so the day offset is 0 and they can be inserted without
                # a shared station (otherwise stations are lost, e.g. 土浦 on 常磐線 上リ 802).
                if B5_SEGMENT_LINK and sheet in SEGLINK_SHEETS.get(key, ()):
                    med = 0
                else:
                    continue    # cannot align on shared stations -> do not weave
            else:
                diffs.sort()
                med = diffs[len(diffs) // 2]
            k = round(med / 1440.0)
            if diffs:
                resid = sorted(abs(d - k * 1440) for d in diffs)
                # True median (mean of the middle two for an even count); resid[len//2] would
                # take the upper value, effectively max <= 5 with two anchors.
                med_resid = (resid[(len(resid) - 1) // 2] + resid[len(resid) // 2]) / 2
                if med_resid > 5 or resid[-1] > 10:
                    continue    # a shared station disagrees -> do not weave
            # diffs is empty only for sheets joined across bands (med=0 above); the join already
            # established same table, same column and consecutive times, so insert as is.
            off = k * 1440
            inserted = []
            for r in uniq:
                t = time_to_min(r.get('dep_time') or r.get('arr_time'))
                if t is None:
                    continue    # a unique station without time cannot be placed
                nr = dict(r)
                if off:
                    nr = apply_time_offset([nr], off)[0]
                nt = t + off
                pos = 0
                for idx, tt in enumerate(jt):
                    if tt is not None and tt <= nt:
                        pos = idx + 1
                integrated.insert(pos, nr)
                jt.insert(pos, nt)
                jnames.add(rkey_of[id(r)])
                jtimes_by_name[rkey_of[id(r)]].append(nt)
                inserted.append(nr['stop_name'])
            if inserted:
                woven.append((sheet, inserted))
        return integrated, woven

    def _weave_hole_fill(integrated, selected):
        """Step E'' extension: hole filling in sheet selection (INTEGRATE_HOLE_FILL).

        When the chosen chain misses part of the trip (a middle hole, a cut end, or a whole
        separate segment), weave in unchosen sheets covering that part. Plain E''
        (_weave_parallel) rejected them because the dwell between 著 and 發 (minutes to tens of
        minutes) counted as residual. Three extensions:
          1. Kind-aware alignment: same-kind comparisons (發-發 / 著-著) keep the usual gate
             (median residual <= 5 min, max 10 min); arrival-only vs departure-only is allowed
             within [-10, HOLE_MAXDWELL] min (as in the B.5 complement).
          2. Iterative weaving: woven stations anchor the next sheet (recovers chains of
             segments); up to 6 passes until no progress.
          3. Sheets with no shared station: inserted only if the whole block fits into a gap
             of the trip's timeline (rejected if the day offset is ambiguous or it interleaves).
        Each sheet is committed only after a trial run of E' shows that **no existing station
        is lost** and at least one inserted station survives (per-sheet guard).
        Previous behavior (E'' only) = INTEGRATE_HOLE_FILL=0.

        Returns: (integrated, woven=[(sheet, [station...]), ...])
        """
        if not integrated:
            return integrated, []

        def _n(s):
            return normalize_kanji_variants(normalize_stop_name(s),
                                            prefer_new=True)

        def _rt(r):
            return time_to_min(r.get('dep_time') or r.get('arr_time'))

        def _try_align(recs, cur, sheet=None):
            """Align against the current trip cur. Returns the day offset (minutes) on success,
            None on failure (residual gate fails or nothing to compare)."""
            jpairs = defaultdict(list)
            rkey_of = {id(r): k_ for r, k_ in zip(recs, _split_keys(recs, _n))}
            for r, k_ in zip(cur, _split_keys(cur, _n)):     # see INTEGRATE_SAME_LINE_SPLIT
                jpairs[k_].append(
                    (time_to_min(r.get('dep_time')),
                     time_to_min(r.get('arr_time'))))
            # --- Day offset estimate (as in plain E''; dep/arr pooled) ---
            jtimes = defaultdict(list)
            for nm, pairs in jpairs.items():
                for (dj, aj) in pairs:
                    for t in (dj, aj):
                        if t is not None:
                            jtimes[nm].append(t)
            diffs = []
            for r in recs:
                nm = rkey_of[id(r)]
                t = _rt(r)
                if t is None or nm not in jtimes:
                    continue
                best = min(jtimes[nm], key=lambda tj: abs(tj - t))
                diffs.append(best - t)
            if not diffs:
                return _zero_shared_offset(recs, cur, sheet)
            diffs.sort()
            off = round(diffs[len(diffs) // 2] / 1440.0) * 1440
            # --- Kind-aware residual gate ---
            per_station = []          # best (violation, kind, residuals) per station
            for r in recs:
                nm = rkey_of[id(r)]
                if nm not in jpairs:
                    continue
                ds = time_to_min(r.get('dep_time'))
                as_ = time_to_min(r.get('arr_time'))
                if ds is None and as_ is None:
                    continue
                best = None      # (violation, kind, residuals)
                for (dj, aj) in jpairs[nm]:
                    ent_s = []
                    if ds is not None and dj is not None:
                        ent_s.append(dj - ds - off)
                    if as_ is not None and aj is not None:
                        ent_s.append(aj - as_ - off)
                    if ent_s:
                        cand = (max(abs(x) for x in ent_s), 's', ent_s)
                    else:
                        ent_c = []
                        if as_ is not None and dj is not None:
                            ent_c.append(dj - (as_ + off))   # 著 (sheet) -> 發 (trip)
                        if ds is not None and aj is not None:
                            ent_c.append((ds + off) - aj)    # 著 (trip) -> 發 (sheet)
                        if not ent_c:
                            continue
                        viol = max(0 if -10 <= x <= HOLE_MAXDWELL
                                   else min(abs(x + 10), abs(x - HOLE_MAXDWELL))
                                   for x in ent_c)
                        cand = (viol, 'c', ent_c)
                    if best is None or cand[0] < best[0]:
                        best = cand
                if best is None:
                    continue
                per_station.append(best)
            # Outlier anchors (> 30 min: another run, digit error, passing twice on a reversal) are
            # ignored only if there are 2+ clean anchors in the majority (e.g. 信越 105, where a
            # summary's time for the second pass of 新津 differs by 77 min); otherwise reject.
            # Outliers matching the clock on a different day (residual = multiple of 1440 ± 10 min,
            # a midnight-fix mismatch) likely affect the whole sheet, so the sheet is rejected
            # (e.g. 東海道 28, 沼津 著 48:58 vs 24:58).
            clean = [b for b in per_station if b[0] <= 30]
            outl = [b for b in per_station if b[0] > 30]
            if any(min(b[0] % 1440, 1440 - b[0] % 1440) <= 10 for b in outl):
                return None
            if outl and (len(clean) < 2 or len(outl) >= len(clean)):
                return None
            strict = [abs(x) for b in clean if b[1] == 's' for x in b[2]]
            cross = [x for b in clean if b[1] == 'c' for x in b[2]]
            if not strict and not cross:
                return None
            if strict:
                strict.sort()
                # True median (taking the upper value would make [0,7] with two anchors a median of 7,
                # and a detailed sheet differing from the summary by 7 min would not be woven in)
                med_strict = (strict[(len(strict) - 1) // 2] + strict[len(strict) // 2]) / 2
                if med_strict > 5 or strict[-1] > 10:
                    return None
            if any(not (-10 <= x <= HOLE_MAXDWELL) for x in cross):
                return None
            return off

        def _zero_shared_offset(recs, cur, sheet=None):
            """No shared station (a whole separate segment): accept only if exactly one day
            offset fits the whole block into a gap of the trip's timeline."""
            times = [t for t in (_rt(r) for r in recs) if t is not None]
            # One time is usually not enough to fix the day offset, but sheets joined across bands
            # (B5_SEGMENT_LINK) are already confirmed as the same column with consecutive times,
            # so one station suffices (e.g. 土浦 on 常磐線 上リ 802).
            seglinked = (B5_SEGMENT_LINK and sheet is not None
                         and sheet in SEGLINK_SHEETS.get(key, ()))
            if len(times) < (1 if seglinked else 2):
                return None
            if len(times) == 1 and seglinked:
                times = times * 2
            f, l = times[0], times[-1]
            jvalid = [t for t in (_rt(r) for r in cur) if t is not None]
            if not jvalid:
                return None
            placement = []
            for k in (0, 1, -1):
                off = 1440 * k
                fo, lo = f + off, l + off
                inside = [t for t in jvalid if fo + 15 < t < lo - 15]
                if inside:
                    continue                     # trip stations fall inside = a parallel route
                prev = [t for t in jvalid if t <= fo + 15]
                nxt = [t for t in jvalid if t >= lo - 15]
                if not prev and not nxt:
                    continue
                if prev and not (-15 <= fo - max(prev) <= 360):
                    continue
                if nxt and not (-15 <= min(nxt) - lo <= 360):
                    continue
                placement.append(off)
            if len(placement) != 1:
                return None                      # no fit or ambiguous day
            return placement[0]

        def _fill_columns(cand, recs, rkey_of, off, sheet=None):
            """UNSELECTED_FILL: fill empty fields (著 or 發) of stations already in trip cand with
            values from the aligned (off) unchosen sheet recs. No stations are added.
            DETAIL_WINS: when values in the same field disagree, take the clearly more detailed sheet.
            Returns (filled [(station, field, value)...], overwritten [(station, field, new, old,
            source sheet)...]); modifies the dicts of cand in place."""
            ckeys = _split_keys(cand, _n)
            idx_of = defaultdict(list)
            for i, k_ in enumerate(ckeys):
                idx_of[k_].append(i)

            def _tm(r, f):
                return time_to_min(r.get(f))

            def _prev_t(i):
                for j in range(i - 1, -1, -1):
                    t = _tm(cand[j], 'dep_time')
                    if t is None:
                        t = _tm(cand[j], 'arr_time')
                    if t is not None:
                        return t
                return None

            def _next_t(i):
                for j in range(i + 1, len(cand)):
                    t = _tm(cand[j], 'arr_time')
                    if t is None:
                        t = _tm(cand[j], 'dep_time')
                    if t is not None:
                        return t
                return None

            filled = []
            overwritten = []

            def _owner(rec, col):
                """Sheet that last wrote this field (source_sheet if never overwritten)."""
                return rec.get('_dw_' + col) or rec.get('source_sheet')

            def _ncount(name):
                """How detailed the sheet is for this trip = (density, stations).
                Density = stations / time span. Raw station counts can favor a summary (a section
                page only covers its own part), so compare density; but density alone would make a
                one-station fragment strongest (span floor 1 min -> density 1.0), so stations count too."""
                st = sheet_stats.get(name)
                return (st['stop_density'], st['stop_count']) if st else None

            for r in recs:
                k_ = rkey_of[id(r)]
                if k_ not in idx_of:
                    continue
                rd, ra = _tm(r, 'dep_time'), _tm(r, 'arr_time')
                if rd is None and ra is None:
                    continue
                rd = rd + off if rd is not None else None
                ra = ra + off if ra is not None else None
                rt = rd if rd is not None else ra
                # If the trip has several rows with this key (printed 著/發 rows, reversals), use the nearest in time
                best = None
                for i in idx_of[k_]:
                    cd, ca = _tm(cand[i], 'dep_time'), _tm(cand[i], 'arr_time')
                    ct = cd if cd is not None else ca
                    if ct is None:
                        continue                 # skip rows without time
                    d = abs(ct - rt)
                    if best is None or d < best[0]:
                        best = (d, i, cd, ca)
                if best is None or best[0] > 120:
                    continue                     # over 2h = another pass (reversal etc.)
                _, i, cd, ca = best
                if cd is not None and ca is None and ra is not None:
                    # Add 著 to a departure-only row (fields present on both sides must agree)
                    if rd is not None and abs(rd - cd) > 10:
                        continue
                    pt = _prev_t(i)
                    if ra <= cd and (pt is None or pt <= ra):
                        cand[i]['arr_time'] = minutes_to_hhmm(ra)
                        filled.append((cand[i]['stop_name'], 'arr', cand[i]['arr_time']))
                elif ca is not None and cd is None and rd is not None:
                    # Add 發 to an arrival-only row
                    if ra is not None and abs(ra - ca) > 10:
                        continue
                    nt = _next_t(i)
                    if ca <= rd and (nt is None or rd <= nt):
                        cand[i]['dep_time'] = minutes_to_hhmm(rd)
                        filled.append((cand[i]['stop_name'], 'dep', cand[i]['dep_time']))
                if not DETAIL_WINS or sheet is None:
                    continue
                # --- DETAIL_WINS: when the same field disagrees, take the clearly more detailed sheet ---
                n_new = _ncount(sheet)
                for col, sv in (('arr', ra), ('dep', rd)):
                    if sv is None:
                        continue
                    cv = _tm(cand[i], col + '_time')
                    if cv is None or cv == sv:
                        continue                 # empty fields belong to UNSELECTED_FILL; equal values: nothing to do
                    if abs(cv - sv) > DETAIL_WINS_MAX_DIFF:
                        continue                 # large difference = another train with the same number
                    old_owner = _owner(cand[i], col)
                    n_old = _ncount(old_owner)
                    if n_old is None or n_new is None:
                        continue
                    if (n_new[0] < n_old[0] * DETAIL_WINS_RATIO
                            or n_new[1] < DETAIL_WINS_MIN_STOPS
                            or n_new[1] < n_old[1]):
                        continue                 # change only when clearly more detailed (safe side)
                    other = _tm(cand[i], ('dep' if col == 'arr' else 'arr') + '_time')
                    if col == 'arr':
                        if other is not None and sv > other:
                            continue             # keep 著 <= 發
                        pt = _prev_t(i)
                        if pt is not None and sv < pt:
                            continue             # do not pass the previous station
                    else:
                        if other is not None and sv < other:
                            continue
                        nt2 = _next_t(i)
                        if nt2 is not None and sv > nt2:
                            continue
                    old_hhmm = cand[i][col + '_time']
                    cand[i][col + '_time'] = minutes_to_hhmm(sv)
                    cand[i]['_dw_' + col] = sheet
                    overwritten.append((cand[i]['stop_name'], col,
                                        cand[i][col + '_time'], old_hhmm,
                                        old_owner, n_old, n_new))
            return filled, overwritten

        woven = []
        cur = [dict(r) for r in integrated]
        candidates = sorted((s for s in sheet_stats if s not in selected),
                            key=lambda s: (sheet_stats[s]['first_min'], s))
        done = set()
        for _pass in range(6):
            progress = False
            for sheet in candidates:
                if sheet in done:
                    continue
                recs = sheet_stats[sheet]['records']
                cur_names = set(_split_keys(cur, _n))        # see INTEGRATE_SAME_LINE_SPLIT
                rkey_of = {id(r): k_ for r, k_ in zip(recs, _split_keys(recs, _n))}
                uniq = [r for r in recs if rkey_of[id(r)] not in cur_names]
                # UNSELECTED_FILL: also check whether empty fields of stations in the trip can be filled
                fillable = (UNSELECTED_FILL or DETAIL_WINS) and any(
                    rkey_of[id(r)] in cur_names for r in recs)
                if not uniq and not fillable:
                    done.add(sheet)
                    continue
                off = _try_align(recs, cur, sheet)
                if off is None:
                    continue                     # retry in the next pass (after more anchors)
                # --- Insert at the time position (same mechanism as plain E'') ---
                cand = [dict(r) for r in cur]
                jt = [_rt(r) for r in cand]
                inserted = []
                inserted_keys = []
                for r in uniq:
                    t = _rt(r)
                    if t is None:
                        continue                 # cannot place a row without time
                    nr = dict(r)
                    if off:
                        nr = apply_time_offset([nr], off)[0]
                    nt = t + off
                    pos = 0
                    for idx, tt in enumerate(jt):
                        if tt is not None and tt <= nt:
                            pos = idx + 1
                    cand.insert(pos, nr)
                    jt.insert(pos, nt)
                    inserted.append(nr['stop_name'])
                    inserted_keys.append(rkey_of[id(r)])
                # --- UNSELECTED_FILL: fill empty fields of existing rows from the unchosen sheet ---
                filled, overwritten = (
                    _fill_columns(cand, recs, rkey_of, off, sheet)
                    if fillable else ([], []))
                if not UNSELECTED_FILL:
                    filled = []                  # with only DETAIL_WINS on, do not fill
                if not inserted and not filled and not overwritten:
                    done.add(sheet)
                    continue
                # --- Per-sheet guard: a trial run of E' must not lose existing stations ---
                test = remove_non_monotonic([dict(r) for r in cand])
                test_names = set(_split_keys(test, _n))
                if not cur_names <= test_names:
                    continue                     # reject insertions that remove existing stations
                if inserted and not (set(inserted_keys) & test_names):
                    done.add(sheet)
                    continue                     # pointless if no inserted station survives
                cur = cand
                if inserted:
                    woven.append((sheet, inserted))
                if filled:
                    fill_log.append((sheet, filled))
                if overwritten:
                    ow_log.append((sheet, overwritten))
                done.add(sheet)
                progress = True
            if not progress:
                break
        return cur, woven

    if CHAIN_ENABLED:
        # Step C.5-D: assemble **both** the chain selection and the legacy selection to the final
        # form and take the one with wider coverage (unique stations, then records).
        # - Not chain only: legacy greedy selection can mix across unit boundaries (summary head +
        #   detailed tail), which sometimes wins (e.g. 北陸 675, where summaries chained and blocked a
        #   45-station detailed chain).
        # - Compared on the final form (after boundary merge and E'), because wider selection
        #   coverage can still shrink in E' depending on join order.
        # Ties go to legacy (conservative), so coverage never gets narrower than legacy.
        # The chosen side is logged in the QA log.
        unit_stats, unit_members = build_chain_units(sheet_stats)
        selected_units = select_sheets(unit_stats)
        sel_chain = [m for u in selected_units for m in unit_members[u]]
        sel_legacy = select_sheets(sheet_stats)

        if sel_chain == sel_legacy:
            selected = sel_legacy
            integrated, warnings, eprime_dropped = _assemble(selected)
            chain_mode = 'same'
        else:
            res_chain = _assemble(sel_chain)
            res_legacy = _assemble(sel_legacy)
            if _final_coverage(res_chain[0]) > _final_coverage(res_legacy[0]):
                selected = sel_chain
                integrated, warnings, eprime_dropped = res_chain
                chain_mode = 'chain'
            else:
                selected = sel_legacy
                integrated, warnings, eprime_dropped = res_legacy
                chain_mode = 'legacy'
            if qa_rows is not None:
                qa_rows.append({
                    'key': f'{key[0]}__{key[1]}__{key[2]}',
                    'kind': f'chain_mode_{chain_mode}', 'sheet': '',
                    'stop_name': '', 'dep_time': '', 'arr_time': '',
                    'detail': f"chain={sel_chain} legacy={sel_legacy}",
                })

        # Step E'': weave in unique stations of parallel sheets (same B.5 cluster = same train).
        # Default is the hole-filling version (_weave_hole_fill);
        # INTEGRATE_HOLE_FILL=0 uses plain E'' (_weave_parallel).
        pre_weave = list(integrated)
        pre_names = {normalize_kanji_variants(normalize_stop_name(r['stop_name']),
                                              prefer_new=True) for r in integrated}
        fill_log = []                             # UNSELECTED_FILL: (sheet, [(station, field, value)...])
        ow_log = []                               # DETAIL_WINS: (sheet, [(station, field, new, old, source)...])
        _weave = _weave_hole_fill if HOLE_FILL_ENABLED else _weave_parallel
        integrated, woven = _weave(integrated, set(selected))
        if woven or fill_log or ow_log:
            guard = []
            integrated = remove_non_monotonic(integrated, dropped=guard)
            post_names = {normalize_kanji_variants(
                normalize_stop_name(r['stop_name']), prefer_new=True)
                for r in integrated}
            if not pre_names <= post_names:
                # Safety valve: roll everything back if weaving + guard lost an original station
                # (an insertion can cause a non-adjacent duplicate and E' cuts the head/tail of the trip)
                integrated = pre_weave
                woven = []
                fill_log = []
                ow_log = []
                guard = []
            for seq, r in enumerate(integrated, 1):
                r['stop_sequence'] = seq
            eprime_dropped = list(eprime_dropped) + \
                [(f'weave_guard_{p}', r) for p, r in guard]
        if fill_log and qa_rows is not None:
            for f_sheet, cells in fill_log:
                for st_name, col, val in cells:
                    qa_rows.append({
                        'key': f'{key[0]}__{key[1]}__{key[2]}',
                        'kind': 'unselected_fill', 'sheet': f_sheet,
                        'stop_name': st_name,
                        'dep_time': val if col == 'dep' else '',
                        'arr_time': val if col == 'arr' else '',
                        'detail': f"落選シートの{'發' if col == 'dep' else '著'}で空欄を埋めた（INTEGRATE_UNSELECTED_KEEP_UNIQUE）",
                    })
        if ow_log and qa_rows is not None:
            for o_sheet, cells in ow_log:
                for st_name, col, val, old_val, old_sheet, d_old, d_new in cells:
                    qa_rows.append({
                        'key': f'{key[0]}__{key[1]}__{key[2]}',
                        'kind': 'unselected_overwrite', 'sheet': o_sheet,
                        'stop_name': st_name,
                        'dep_time': val if col == 'dep' else '',
                        'arr_time': val if col == 'arr' else '',
                        'detail': (f"{'發' if col == 'dep' else '著'} {old_val} → {val}"
                                   f"（細かいほうの表を優先・INTEGRATE_DETAIL_WINS。旧＝{old_sheet}"
                                   f" 密度 {d_old[0]:.3f}→{d_new[0]:.3f}"
                                   f"・駅数 {d_old[1]}→{d_new[1]}）"),
                    })
        if woven:
            if qa_rows is not None:
                for w_sheet, w_stations in woven:
                    qa_rows.append({
                        'key': f'{key[0]}__{key[1]}__{key[2]}',
                        'kind': 'weave_added', 'sheet': w_sheet,
                        'stop_name': '', 'dep_time': '', 'arr_time': '',
                        'detail': f"並走シートの独自駅{len(w_stations)}駅を編み込み: "
                                  f"{'/'.join(w_stations[:8])}"
                                  f"{'…' if len(w_stations) > 8 else ''}",
                    })
    else:
        selected = select_sheets(sheet_stats)
        integrated, warnings, eprime_dropped = _assemble(selected)

    if qa_rows is not None:
        for sheet in sheet_stats:
            if sheet not in selected:
                s = sheet_stats[sheet]
                qa_rows.append({
                    'key': f'{key[0]}__{key[1]}__{key[2]}',
                    'kind': 'unselected_sheet', 'sheet': sheet,
                    'stop_name': '', 'dep_time': '', 'arr_time': '',
                    'detail': f"n={s['stop_count']} "
                              f"{s['first_stop_name']}→{s['last_stop_name']} "
                              f"stations={'|'.join(r['stop_name'] for r in s['records'])}",
                })
        for phase, r in eprime_dropped:
            qa_rows.append({
                'key': f'{key[0]}__{key[1]}__{key[2]}',
                'kind': f'eprime_{phase}', 'sheet': r.get('source_sheet') or '',
                'stop_name': r.get('stop_name') or '',
                'dep_time': r.get('dep_time') or '',
                'arr_time': r.get('arr_time') or '', 'detail': '',
            })

    # INTEGRATE_NO_NEGATIVE: never output negative times.
    # Weaving (Step E'') aligns unchosen sheets to the trip, so if the trip missed a +24h, stations
    # from a sheet that correctly has +24h come in at -24h (e.g. 上野 on 常磐線 下リ 801 at `-2:00`;
    # printed 22:00). Relative times are right, so shift the whole trip by a multiple of 1440
    # until the earliest time is >= 0.
    # Default ON. Previous behavior = INTEGRATE_NO_NEGATIVE=0.
    if NO_NEGATIVE_TIME and integrated:
        mins = [t for t in (time_to_min(r.get('dep_time')) for r in integrated) if t is not None]
        mins += [t for t in (time_to_min(r.get('arr_time')) for r in integrated) if t is not None]
        if mins and min(mins) < 0:
            shift = ((-min(mins)) + 1439) // 1440 * 1440
            integrated = apply_time_offset(integrated, shift)
            for seq, r in enumerate(integrated, 1):
                r['stop_sequence'] = seq

    return integrated, warnings


# ---------------------------------------------------------------------------
# Step G: CSV output
# ---------------------------------------------------------------------------

OUT_FIELDS = [
    'gtfs_trip_key', 'line_name', 'direction', 'trip_num',
    'stop_sequence', 'stop_name', 'stop_type',
    'dep_time', 'arr_time', 'source_sheet',
]

WARN_FIELDS = [
    'key', 'issue',
    'prev_sheet', 'prev_stop', 'prev_time',
    'next_sheet', 'next_stop', 'next_time',
]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Step A
    print('Step A: 全中間ファイル読み込み中...')
    all_records = load_all_stop_times()
    print(f'  総レコード数: {len(all_records):,}')
    single_time_sheets = _single_time_sheets(all_records) if CROSSLINE_KEEP_DEPONLY else set()
    cl_kept_single = []   # trips kept by INTEGRATE_CROSSLINE_KEEP_DEPONLY (for qa_log)

    # Step A.5: unify old/new kanji variants of line_name to the majority
    canonical_map = canonicalize_line_names(all_records)
    if canonical_map:
        print(f'  line_name 表記揺れ統一: {len(canonical_map)} 件')
        for src, dst in sorted(canonical_map.items()):
            print(f'    {src} → {dst}')

    # Step A.6: unify old/new kanji variants of stop_name per line
    #   (the transcription keeps printed spellings; otherwise one station splits into several stop_ids)
    stop_map = canonicalize_stop_names(all_records)
    if stop_map:
        print(f'  stop_name 表記揺れ統一: {len(stop_map)} 件')
        for (src, line), dst in sorted(stop_map.items()):
            print(f'    [{line}] {src} → {dst}')
    gmap = canonicalize_stop_names_global(all_records)      # INTEGRATE_CANON_STOP_GLOBAL
    if gmap:
        print(f'  stop_name 表記揺れ統一（路線をまたぐ・INTEGRATE_CANON_STOP_GLOBAL）: {len(gmap)} 件')
        for (src, line), dst in sorted(gmap.items()):
            print(f'    [{line}] {src} → {dst}')

    # Step B
    print('Step B: グループ化...')
    groups, uncertain_count = group_records(all_records)
    print(f'  グループ数:         {len(groups):,}')
    if uncertain_count:
        print(f'  uncertain 仮番号付与: {uncertain_count:,} レコード')

    # Step B.5: split by time consistency (same trip_num but times disagree at common stations)
    groups, n_split, split_log, seglink_log = split_groups_by_time_consistency(groups)
    if n_split:
        print(f'  時刻整合性で分離: {n_split} 追加 trip (元キー {len(split_log)})')
    if seglink_log:
        print(f'  帯またぎ結合(B5_SEGMENT_LINK): {len(seglink_log)} ペア')
        print(f'  分離後グループ数: {len(groups):,}')

    # Summary dedup for combined line names (with 及)
    # A trip of a combined line name such as 東海道及山陽本線 is dropped as a summary duplicate
    # if a component line (東海道本線, 山陽本線) has a trip with the same trip_num.
    COMBINED_LINES = {
        '東海道及山陽本線': ['東海道本線', '山陽本線'],
        '山陽及東海道本線': ['山陽本線', '東海道本線'],
        '山口及山陰線': ['山口線', '山陰線'],
        '山陰及山口線': ['山陰線', '山口線'],
        '小濱及舞鶴線': ['小濱線', '舞鶴線'],
        '舞鶴及小濱線': ['舞鶴線', '小濱線'],
        '凾館及宗谷本線': ['凾館本線', '宗谷本線'],
        '宗谷及凾館本線': ['宗谷本線', '凾館本線'],
        '鹿兒島及長崎本線': ['鹿兒島本線', '長崎本線'],
        '函館・根室・宗谷本線': ['函館本線', '根室本線', '宗谷本線'],
        '安奉線及滿洲線': ['安奉線', '滿洲線'],
        '朝鮮及満洲線': ['朝鮮線', '滿洲線'],
        '朝鮮及滿洲線': ['朝鮮線', '滿洲線'],
    }
    # Write 著/發 printed only on a band into empty fields of the same-numbered detailed trip.
    #   The two guards below can only keep or drop a band and ignore the train number, so for a band
    #   spanning two lines the value was lost (東海道及山陽本線 673, 京都 著 17:36: the detailed
    #   東海道本線 673 prints only 京都 發, and train 73 has the same time, so the band is dropped).
    #   When ON, only write the band's (line, direction, number, station, field, time) to a side file
    #   (groups are untouched, so keep/drop decisions are as with OFF). split_combined_trips.py fills
    #   the empty fields at the end of the split step (after all dedup).
    #   Default ON. Previous behavior (no side file) = INTEGRATE_COMBINED_FILL_BLANKS=0.
    if os.environ.get('INTEGRATE_COMBINED_FILL_BLANKS', '1') != '0':
        _fb_path = os.path.join(OUTPUT_DIR, 'combined_band_cells.csv')
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(_fb_path, 'w', encoding='utf-8-sig', newline='') as _f:
            _w = csv.writer(_f, lineterminator='\r\n')
            _w.writerow(['line_name', 'direction', 'trip_num', 'stop_name', 'field', 'time', 'source_sheet'])
            for _k in sorted(groups):
                if not any(ch in _k[0] for ch in '及、・'):
                    continue
                for _r in groups[_k]:
                    for _fld in ('arr_time', 'dep_time'):
                        _t = time_to_min(_r.get(_fld))
                        if _t is not None:
                            _w.writerow([_k[0], _k[1], _k[2], _r.get('stop_name'), _fld,
                                         minutes_to_hhmm(_t % 1440), _r.get('source_sheet', '')])
        print(f'  帯の値の控え（INTEGRATE_COMBINED_FILL_BLANKS）: {_fb_path}')

    removed_combined = 0
    keys_to_remove = set()
    for key in groups:
        line_name, direction, trip_num = key
        if line_name not in COMBINED_LINES:
            continue
        parts = COMBINED_LINES[line_name]
        has_individual = any(
            (p, direction, trip_num) in groups for p in parts
        )
        if has_individual:
            keys_to_remove.add(key)
            removed_combined += 1

    # Do not discard times printed nowhere else. The check above only looks at whether
    #   (component line, direction, trip_num) exists and compares no times, so 著/發 printed only on the
    #   combined band were lost (e.g. `73 神戶 著19:44`). Before dropping, check each
    #   (station, 著/發, time mod 24h) against the remaining groups; if any is missing, keep the trip
    #   (a combined-name trip may then remain in GTFS). Step B.7 uses the same guard.
    #   Default ON. Previous behavior = INTEGRATE_COMBINED_KEEP_UNIQUE=0.
    KEEP_UNIQUE_CELLS = os.environ.get('INTEGRATE_COMBINED_KEEP_UNIQUE', '1') != '0'
    # Also look at the train number. The check above drops a band if (station, field, time) exists in any
    #   remaining group, so a value printed only on the band is lost when another train has the same time
    #   (p80 參宮線及關西本線 53/55, 柘植 著 11:26, dropped because 關西本線 175 has the same time).
    #   When ON, for a combined-name band, if a component line has a same-numbered group containing all of
    #   the band's stations (the detailed trip of the same train) and lacks some (station, field, time) of
    #   the band, keep the band. The split step then merges it into that trip and fills the empty fields
    #   (SPLIT_SINGLE_LINE_BAND / SPLIT_MERGE_UNIQUE_TIMES). Bands spanning other lines, or without a
    #   same-numbered component trip, are handled as before.
    #   Default ON. Previous behavior = INTEGRATE_COMBINED_KEEP_UNIQUE_NUM=0.
    KEEP_UNIQUE_SAME_NUM = KEEP_UNIQUE_CELLS and os.environ.get('INTEGRATE_COMBINED_KEEP_UNIQUE_NUM', '1') != '0'   # default ON

    def _ck_norm(s):
        return normalize_kanji_variants(normalize_stop_name((s or '').strip()),
                                        prefer_new=True)

    def _ck_cells(records):
        """Set of (station, 著/發 field, time mod 24h); rows with one field count only that field."""
        out = set()
        for r in records:
            st = _ck_norm(r.get('stop_name'))
            for f in ('arr_time', 'dep_time'):
                t = time_to_min(r.get(f))
                if t is not None:
                    out.add((st, f, t % 1440))
        return out

    def _a27_num(key):
        """Base train number of a group (B.5 suffix `_b` / `_c` removed)."""
        return re.sub(r'_[a-z]$', '', str(key[2]))

    def _ck_components(line_name):
        """Candidate component line names of a combined name split at 及, 、, ・ (as is, +本線, +線),
        built as in Step B.7."""
        comps = set()
        for part in re.split(r'[及、・]', line_name or ''):
            part = part.strip()
            if part:
                comps |= {_ck_norm(part), _ck_norm(part + '本線'), _ck_norm(part + '線')}
        comps.discard(_ck_norm(line_name))
        return comps

    # Occurrence counts of (station, field, time) over all groups. Decremented on each drop, so the check
    # always sees what remains. groups iterates in insertion order, so the result is deterministic.
    a27_counts = Counter()
    a27_by_num = defaultdict(list)   # base number -> group keys with that number (only with KEEP_UNIQUE_SAME_NUM)
    a27_gone = set()                 # keys decided to drop (still in groups; deleted together later)
    a27_sets = {}                    # cache: key -> (station set, (station, field, time) set)
    if KEEP_UNIQUE_CELLS:
        for _k, _recs in groups.items():
            for _c in _ck_cells(_recs):
                a27_counts[_c] += 1
            if KEEP_UNIQUE_SAME_NUM:
                a27_by_num[_a27_num(_k)].append(_k)

    def _a27_peer_sets(key):
        if key not in a27_sets:
            recs = groups[key]
            a27_sets[key] = ({_ck_norm(r.get('stop_name')) for r in recs}, _ck_cells(recs))
        return a27_sets[key]

    def _a27_unique(key):
        """Return the (station, field, time) that would vanish from the output if key were dropped.
        With KEEP_UNIQUE_SAME_NUM, for a combined-name band also return values missing from a
        same-numbered component group containing all of the band's stations (the same train's detail)."""
        cells = _ck_cells(groups[key])
        out = {c for c in cells if a27_counts.get(c, 0) <= 1}
        if KEEP_UNIQUE_SAME_NUM and any(ch in key[0] for ch in '及、・'):
            comps = _ck_components(key[0])
            stations = {_ck_norm(r.get('stop_name')) for r in groups[key]}
            holders = [k for k in a27_by_num.get(_a27_num(key), ())
                       if k != key and k not in a27_gone and k in groups and _ck_norm(k[0]) in comps
                       and stations <= _a27_peer_sets(k)[0]]
            if holders:
                out |= {c for c in cells if not any(c in _a27_peer_sets(k)[1] for k in holders)}
        return sorted(out)

    def _a27_release(key):
        for _c in _ck_cells(groups[key]):
            a27_counts[_c] -= 1
        a27_gone.add(key)

    kept_unique_combined = []
    if keys_to_remove and KEEP_UNIQUE_CELLS:
        for key in sorted(keys_to_remove):
            missing = _a27_unique(key)
            if missing:
                kept_unique_combined.append((key, missing))
            else:
                _a27_release(key)
        for key, _missing in kept_unique_combined:
            keys_to_remove.discard(key)
            removed_combined -= 1

    for key in keys_to_remove:
        del groups[key]
    if removed_combined:
        print(f'  「及」路線の概略重複除去: {removed_combined}トリップ')
        print(f'  残りグループ数:    {len(groups):,}')
    if kept_unique_combined:
        n_cells = sum(len(m) for _k, m in kept_unique_combined)
        print(f'  ↑うち保持(そこにしか無い時刻あり・INTEGRATE_COMBINED_KEEP_UNIQUE): '
              f'{len(kept_unique_combined)}トリップ / {n_cells}セル')

    # ------------------------------------------------------------------
    # Step B.7: summary dedup (drop summary/connection duplicates by matching times)
    # ------------------------------------------------------------------
    # Summaries/connection bands that duplicate a detailed page produce no GTFS trip (the detailed
    # page's train is used). Connection-only trips without detail are kept.
    # COMBINED_LINES above only drops exact trip_num matches, leaving duplicates with other numbers or
    # unlisted combined names. Here it is generalized by **matching times**:
    #   target = groups with a combined line_name containing 及
    #   compare times at common stations with same-direction groups of the component lines (split at 及/、/・);
    #   drop only if detailed trips with >= 2 matching stations and more matches than mismatches
    #   are found and together **fully cover** the combined trip's stations (0 uncovered).
    #   Duplicates with unique stations are kept and logged (kind=summary_kept_uncovered).
    #   Trips without detail are kept.
    # Default ON. Previous behavior = INTEGRATE_SUMMARY_DEDUP=0.
    # Allowed uncovered stations: SUMMARY_DEDUP_UNCOVERED_MAX (default 0).
    sd_removed, sd_kept = [], []
    sd_kept_unique = []
    if os.environ.get('INTEGRATE_SUMMARY_DEDUP', '1') != '0':
        def _sd_norm(s):
            return normalize_kanji_variants(normalize_stop_name((s or '').strip()),
                                            prefer_new=True)

        def _sd_times(records):
            out = {}
            for r in records:
                t = time_to_min(r.get('dep_time')) or time_to_min(r.get('arr_time'))
                if t is not None:
                    out.setdefault(_sd_norm(r['stop_name']), []).append(t % 1440)
            return out

        def _sd_match(a, b, tol=10):
            hits = miss = 0
            for st in set(a) & set(b):
                d = min(min(abs(x - y) % 1440, 1440 - (abs(x - y) % 1440))
                        for x in a[st] for y in b[st])
                if d <= tol:
                    hits += 1
                elif d > 60:
                    miss += 1
            return hits, miss

        by_line_dir = defaultdict(list)
        for key in groups:
            by_line_dir[(_sd_norm(key[0]), key[1])].append(key)

        # Station-level reverse index (groups without 及): a unique station counts as covered if it is
        # in a detailed trip of a line not among the components (e.g. 播但線, 小濱線, 山口線, 大社線)
        station_idx = defaultdict(list)
        for key2 in groups:
            if '及' in key2[0]:
                continue
            for r in groups[key2]:
                t = time_to_min(r.get('dep_time')) or time_to_min(r.get('arr_time'))
                if t is not None:
                    station_idx[(_sd_norm(r['stop_name']), key2[1])].append(t % 1440)

        sd_cache = {}
        for key in list(groups.keys()):
            line_name, direction, trip_num = key
            if '及' not in line_name:
                continue
            comps = set()
            for p in re.split(r'[及、・]', line_name):
                p = p.strip()
                if p:
                    comps |= {_sd_norm(p), _sd_norm(p + '本線'), _sd_norm(p + '線')}
            comps.discard(_sd_norm(line_name))
            a = _sd_times(groups[key])
            ast = {_sd_norm(r['stop_name']) for r in groups[key]}
            matched, covered = [], set()
            for c in sorted(comps):
                for k2 in by_line_dir.get((c, direction), []):
                    if k2 == key or k2 not in groups:
                        continue
                    if k2 not in sd_cache:
                        sd_cache[k2] = (_sd_times(groups[k2]),
                                        {_sd_norm(r['stop_name']) for r in groups[k2]})
                    h, m = _sd_match(a, sd_cache[k2][0])
                    if h >= 2 and h > m:
                        matched.append(f'{k2[0]}__{k2[1]}__{k2[2]}')
                        covered |= sd_cache[k2][1]
            uncov_max = int(os.environ.get('SUMMARY_DEDUP_UNCOVERED_MAX', '0'))
            uncov = []
            for st in sorted(ast - covered):
                mine = a.get(st, [])
                ok = any(min(abs(x - y) % 1440, 1440 - (abs(x - y) % 1440)) <= 10
                         for x in mine for y in station_idx.get((st, direction), []))
                if not ok:
                    uncov.append(st)
            # Station x time snapshot (QA log: audits what dropped trips lose and diagnoses
            # unique stations of kept trips)
            snap = []
            seen_snap = set()
            for r in groups[key]:
                t = time_to_min(r.get('dep_time')) or time_to_min(r.get('arr_time'))
                if t is None:
                    continue
                ent = (r['stop_name'], minutes_to_hhmm(t % 1440))
                if ent not in seen_snap:
                    seen_snap.add(ent)
                    snap.append(ent)
            if matched and len(uncov) <= uncov_max:
                # INTEGRATE_COMBINED_KEEP_UNIQUE (default ON): station-level coverage alone loses 著/發
                #   printed only on the band (_sd_times takes one time per station, 發 if present).
                #   Keep the trip if some (station, field, time mod 24h) is not in a remaining trip.
                uniq = _a27_unique(key) if KEEP_UNIQUE_CELLS else []
                if uniq:
                    sd_kept_unique.append((key, uniq))
                    sd_kept.append((key, matched, uncov, snap))
                else:
                    if KEEP_UNIQUE_CELLS:
                        _a27_release(key)
                    sd_removed.append((key, matched, uncov, snap))
                    del groups[key]
            elif matched:
                sd_kept.append((key, matched, uncov, snap))
        if sd_removed:
            print(f'  概略重複除去(時刻照合): {len(sd_removed)}トリップ')
            print(f'  残りグループ数:    {len(groups):,}')
        if sd_kept_unique:
            _n = sum(len(u) for _k, u in sd_kept_unique)
            print(f'  ↑うち保持(そこにしか無い時刻あり・INTEGRATE_COMBINED_KEEP_UNIQUE): '
                  f'{len(sd_kept_unique)}トリップ / {_n}セル')

    # ------------------------------------------------------------------
    # Step B.7b: drop short trips fully contained in a trip of another line name
    # ------------------------------------------------------------------
    # B.7 only compares combined names with their components, so bands under a different line name
    # (e.g. 滿洲線 2 stations in the p5 connection table within 滿鐵安奉線 21 stations on p182;
    # 城東線 within 關西本線) appear as separate 2-station trips of the same train.
    # Rule (conservative): drop only if all of this trip's (station, time) are contained, to the minute
    # (tol 0), in a **same-direction** trip of another line name that has more stations.
    # No chaining (decided in order of station count); equal mutual containment is not dropped.
    # Dropped trips are logged with station x time (kind=crossline_dedup / crossline_dedup_stop).
    # Default ON. Previous behavior = INTEGRATE_CROSSLINE_DEDUP=0.
    cl_removed = []
    if os.environ.get('INTEGRATE_CROSSLINE_DEDUP', '1') != '0':
        def _cl_norm(s):
            return normalize_kanji_variants(normalize_stop_name((s or '').strip()),
                                            prefer_new=True)

        def _cl_pairs(records):
            """{(station, time mod 1440)} and raw minutes per station (including +1440 for midnight)."""
            out, raw = set(), defaultdict(set)
            for r in records:
                st = _cl_norm(r['stop_name'])
                for t in (time_to_min(r.get('dep_time')), time_to_min(r.get('arr_time'))):
                    if t is not None:
                        out.add((st, t % 1440))
                        raw[st].add(t)
            return out, raw

        def _cl_same_offset(raw_a, raw_b):
            """Whether every (station, minute) of a is in b with one common day offset (multiple of 1440).
            Matching mod 1440 alone could confuse the same port and time on another day of a multi-day
            voyage, so the offset must be the same at all stations."""
            offsets = None
            for st, ts in raw_a.items():
                tb = raw_b.get(st, set())
                cand = set()
                for ta in ts:
                    for x in tb:
                        if (x - ta) % 1440 == 0:
                            cand.add(x - ta)
                if not cand:
                    return False
                offsets = cand if offsets is None else offsets & cand
                if not offsets:
                    return False
            return offsets is not None and bool(offsets)

        _cl_all = {k: _cl_pairs(v) for k, v in groups.items()}
        cl_pairs = {k: v[0] for k, v in _cl_all.items()}
        cl_raw = {k: v[1] for k, v in _cl_all.items()}
        cl_index = defaultdict(set)
        for k, ps in cl_pairs.items():
            for pr in ps:
                cl_index[pr].add(k)
        # Decide in order of station count (ties by key), so a trip already decided is not dropped
        order = sorted(groups.keys(), key=lambda k: (-len(cl_pairs[k]), k))
        dropped = set()
        for k in order:
            ps = cl_pairs[k]
            if not ps:
                continue
            cands = None
            for pr in ps:
                cands = cl_index[pr] if cands is None else cands & cl_index[pr]
                if not cands:
                    break
            if not cands:
                continue
            best = None
            for k2 in sorted(cands):
                if k2 == k or k2 in dropped:
                    continue
                if _cl_norm(k2[0]) == _cl_norm(k[0]) or k2[1] != k[1]:
                    continue                      # same line name / other direction: skip
                if len(cl_pairs[k2]) <= len(ps):
                    continue                      # drop only if this trip is part of the other
                if not _cl_same_offset(cl_raw[k], cl_raw[k2]):
                    continue                      # day offset differs by station = a trip on another day
                if best is None or len(cl_pairs[k2]) > len(cl_pairs[best]):
                    best = k2
            if best is None:
                continue
            snap = sorted((st, minutes_to_hhmm(t)) for st, t in ps)
            if single_time_sheets and all(r.get('source_sheet') in single_time_sheets for r in groups[k]):
                cl_kept_single.append((k, best, snap, 'B.7b'))   # INTEGRATE_CROSSLINE_KEEP_DEPONLY: keep trips from single-station-time tables
                continue
            cl_removed.append((k, best, snap))
            dropped.add(k)
        for k, _best, _snap in cl_removed:
            del groups[k]
        if cl_removed:
            print(f'  別線名に丸ごと含まれる短いトリップの除去(B.7b): {len(cl_removed)}トリップ')
            print(f'  残りグループ数:    {len(groups):,}')

    # Steps C-F: integrate each group
    print('Step C〜F: 統合処理中...')
    output_rows = []
    all_warnings = []
    qa_rows = [] if QA_LOG_PATH else None
    if qa_rows is not None:
        # Also log B.5 splits (same number but inconsistent times = candidates for wrong numbers)
        for entry in split_log:
            k = entry['key']
            qa_rows.append({
                'key': f'{k[0]}__{k[1]}__{k[2]}', 'kind': 'b5_split',
                'sheet': '', 'stop_name': '', 'dep_time': '', 'arr_time': '',
                'detail': '; '.join(f"{n}件:{','.join(sheets)}"
                                    for n, sheets in entry['clusters']),
            })
            # Evidence for the split (time mismatch at a common station), one row each. Hints:
            # ~720 min = pm error / 50-70 min = hour digit / small = reused number
            for (st, s1, tt1, s2, tt2) in entry.get('conflicts', []):
                d = abs((tt1 or 0) - (tt2 or 0)) % 1440
                d = min(d, 1440 - d)
                qa_rows.append({
                    'key': f'{k[0]}__{k[1]}__{k[2]}', 'kind': 'b5_conflict',
                    'sheet': s1, 'stop_name': st,
                    'dep_time': minutes_to_hhmm(tt1) if tt1 is not None else '',
                    'arr_time': minutes_to_hhmm(tt2) if tt2 is not None else '',
                    'detail': f'{s1}={minutes_to_hhmm(tt1) if tt1 is not None else "?"} vs '
                              f'{s2}={minutes_to_hhmm(tt2) if tt2 is not None else "?"} '
                              f'差{d}分',
                })

    if qa_rows is not None:
        for e in seglink_log:
            k = e['key']
            qa_rows.append({
                'key': f'{k[0]}__{k[1]}__{k[2]}', 'kind': 'b5_seglink',
                'sheet': e['u1'], 'stop_name': '', 'dep_time': '', 'arr_time': '',
                'detail': f"{e['u1']} + {e['u2']}（同じ表の同じ物理列・境界駅は通過）",
            })
        for e in seglink_skip_log:   # filled only when B5_SEGLINK_CLUSTER_SPAN is ON
            k = e['key']
            qa_rows.append({
                'key': f'{k[0]}__{k[1]}__{k[2]}', 'kind': 'b5_seglink_skip',
                'sheet': e['u1'], 'stop_name': '', 'dep_time': '', 'arr_time': '',
                'detail': f"{e['u1']} + {e['u2']} は結合しない（共通駅でつながった組の時刻が、相手の帯の時刻の範囲の内側に入る＝すき間に差し込めない・B5_SEGLINK_CLUSTER_SPAN）",
            })

    if qa_rows is not None:
        for key, matched, uncov, snap in sd_removed:
            qa_rows.append({
                'key': f'{key[0]}__{key[1]}__{key[2]}', 'kind': 'summary_dedup',
                'sheet': '', 'stop_name': '', 'dep_time': '', 'arr_time': '',
                'detail': f"概略重複除去: 詳細={';'.join(matched[:4])} "
                          f"未被覆={'/'.join(uncov[:4]) if uncov else 'なし'}",
            })
            for st, hhmm in snap:
                qa_rows.append({
                    'key': f'{key[0]}__{key[1]}__{key[2]}',
                    'kind': 'summary_dedup_stop',
                    'sheet': '', 'stop_name': st, 'dep_time': hhmm,
                    'arr_time': '', 'detail': '',
                })
        for key, best, snap in cl_removed:
            qa_rows.append({
                'key': f'{key[0]}__{key[1]}__{key[2]}', 'kind': 'crossline_dedup',
                'sheet': '', 'stop_name': '', 'dep_time': '', 'arr_time': '',
                'detail': f"別線名に丸ごと含まれるため除去: 相手={best[0]}__{best[1]}__{best[2]} "
                          f"({len(snap)}駅×時刻)",
            })
            for st, hhmm in snap:
                qa_rows.append({
                    'key': f'{key[0]}__{key[1]}__{key[2]}', 'kind': 'crossline_dedup_stop',
                    'sheet': '', 'stop_name': st, 'dep_time': hhmm, 'arr_time': '', 'detail': '',
                })
        for key, matched, uncov, snap in sd_kept:
            qa_rows.append({
                'key': f'{key[0]}__{key[1]}__{key[2]}', 'kind': 'summary_kept_uncovered',
                'sheet': '', 'stop_name': '', 'dep_time': '', 'arr_time': '',
                'detail': f"概略重複・保持(重複だが独自駅{len(uncov)}駅): "
                          f"詳細={';'.join(matched[:3])} 独自={'/'.join(uncov[:6])}",
            })
            for st, hhmm in snap:
                qa_rows.append({
                    'key': f'{key[0]}__{key[1]}__{key[2]}',
                    'kind': 'summary_kept_stop',
                    'sheet': '', 'stop_name': st, 'dep_time': hhmm,
                    'arr_time': '', 'detail': '',
                })

    # INTEGRATE_B5_SPLIT_REBASE: keys of trips split by b5_split (original key and _b, _c, ...)
    b5_split_keys = set()
    if B5_SPLIT_REBASE:
        for entry in split_log:
            l0, d0, n0 = entry['key']
            b5_split_keys.add(entry['key'])
            for idx in range(1, len(entry['clusters'])):
                sfx = chr(ord('b') + idx - 1) if idx < 26 else f'x{idx}'
                b5_split_keys.add((l0, d0, f'{n0}_{sfx}'))

    for key in sorted(groups.keys()):
        line_name, direction, trip_num = key
        records = groups[key]

        integrated, warnings = integrate_group(key, records, qa_rows=qa_rows)
        all_warnings.extend(warnings)
        if B5_SPLIT_REBASE and key in b5_split_keys and integrated:
            _ts = [t for r in integrated for t in (time_to_min(r.get('dep_time')), time_to_min(r.get('arr_time')))
                   if t is not None]
            if _ts and min(_ts) >= 1440:
                _shift = -(min(_ts) // 1440) * 1440
                integrated = apply_time_offset(integrated, _shift)
                if qa_rows is not None:
                    qa_rows.append({'key': f'{line_name}__{direction}__{trip_num}', 'kind': 'b5_split_rebase',
                                    'sheet': '', 'stop_name': '', 'dep_time': '', 'arr_time': '',
                                    'detail': f'分けた便の時刻を {_shift} 分ずらした（最初の時刻 {minutes_to_hhmm(min(_ts))}）'})

        trip_key = f'{line_name}__{direction}__{trip_num}'
        for r in integrated:
            output_rows.append({
                'gtfs_trip_key': trip_key,
                'line_name':     line_name,
                'direction':     direction,
                'trip_num':      trip_num,
                'stop_sequence': r['stop_sequence'],
                'stop_name':     normalize_stop_name(r['stop_name']),
                'stop_type':     r.get('stop_type'),
                'dep_time':      r.get('dep_time'),
                'arr_time':      r.get('arr_time'),
                'source_sheet':  r.get('source_sheet'),
            })

    # ------------------------------------------------------------------
    # Step B.7c: drop short trips fully contained in another line name (re-check after integration)
    # ------------------------------------------------------------------
    # B.7b runs on groups (bundles of sheets), when later sheets of the other trip may not yet have
    # their +1440 (applied in Steps C-F), so the "same day offset at all stations" guard fails
    # (e.g. 滿洲線 上リ 14 in the p5 connection table equals 滿鐵滿洲本線 14 on p183, but 大連 lacks +1440
    # at B.7b). Here the same rule is applied again on **integrated times** (one timeline per trip):
    # same direction, other line name, all (station, time) contained, the other has more, constant
    # day offset. No chaining (decided in order of time count).
    # Default ON. Previous behavior = INTEGRATE_CROSSLINE_DEDUP2=0.
    cl2_removed = []
    if os.environ.get('INTEGRATE_CROSSLINE_DEDUP2', '1') != '0':
        def _cl2_norm(s):
            return normalize_kanji_variants(normalize_stop_name((s or '').strip()),
                                            prefer_new=True)

        # Tie-break for equal counts (mutual containment).
        # B.7b/B.7c drop only if the other has more station x times, so equal mutual containment is
        # kept (safe side). But ship routes often have only 2 ports, so a dedicated table (e.g. p172
        # 稚泊航路) and a connection band on a main-line page or connection table (連絡汽船 etc.) stayed
        # equal and the same sailing appeared twice in GTFS.
        # Tie-break only by "dedicated table beats summary/connection band":
        #   dedicated table = only one line_name appears in that table (page, tb)
        #   summary/connection band = the table has several line_names, this being one
        # Decided from the transcription's structure, so no hand-kept list of line names is needed.
        # If both are dedicated or both are bands, nothing is dropped
        # (e.g. 東北及信越線 on p133 and 信越及東北線 on p134).
        # Default ON. Previous behavior (keep equal counts) = INTEGRATE_CROSSLINE_EQ=0.
        _cl_eq = os.environ.get('INTEGRATE_CROSSLINE_EQ', '1') != '0'

        cl_tbl_lines = defaultdict(set)
        for r in all_records:
            t = _table_key(r.get('source_sheet'))
            if t is not None and r.get('line_name'):
                cl_tbl_lines[t].add(r['line_name'])

        by_trip = defaultdict(list)
        for r in output_rows:
            by_trip[(r['line_name'], r['direction'], r['trip_num'])].append(r)

        def _cl2_dedicated(k):
            """Whether the trip's sources are all dedicated tables (only this line in the table)."""
            tabs = {_table_key(r.get('source_sheet')) for r in by_trip[k]}
            tabs.discard(None)
            return bool(tabs) and all(len(cl_tbl_lines.get(t, ())) == 1 for t in tabs)

        cl_key_sheets = defaultdict(set)
        if CROSSLINE_EQ_ANY_DEDICATED:
            for r in all_records:
                n = r.get('trip_num')
                n = '' if n is None else (str(int(n)) if isinstance(n, float) and n.is_integer() else str(n).strip())
                cl_key_sheets[(r.get('line_name'), r.get('direction'), n)].add(r.get('source_sheet'))

        def _cl2_any_dedicated(k):
            """INTEGRATE_CROSSLINE_EQ_ANY_DEDICATED: whether any source of the trip (output rows and original
            records with the same key) is a dedicated table."""
            sheets = {r.get('source_sheet') for r in by_trip[k]} | cl_key_sheets.get((k[0], k[1], str(k[2]).strip()), set())
            tabs = {_table_key(s) for s in sheets}
            tabs.discard(None)
            return any(len(cl_tbl_lines.get(t, ())) == 1 for t in tabs)

        cl2_pairs, cl2_raw = {}, {}
        for k, recs in by_trip.items():
            ps, raw = set(), defaultdict(set)
            for r in recs:
                st = _cl2_norm(r['stop_name'])
                for t in (time_to_min(r.get('dep_time')), time_to_min(r.get('arr_time'))):
                    if t is not None:
                        ps.add((st, t % 1440))
                        raw[st].add(t)
            cl2_pairs[k], cl2_raw[k] = ps, raw

        def _cl2_same_offset(raw_a, raw_b):
            offsets = None
            for st, ts in raw_a.items():
                tb = raw_b.get(st, set())
                cand = {x - ta for ta in ts for x in tb if (x - ta) % 1440 == 0}
                if not cand:
                    return False
                offsets = cand if offsets is None else offsets & cand
                if not offsets:
                    return False
            return bool(offsets)

        cl2_index = defaultdict(set)
        for k, ps in cl2_pairs.items():
            for pr in ps:
                cl2_index[pr].add(k)

        cl2_dropped = set()
        for k in sorted(by_trip.keys(), key=lambda k: (-len(cl2_pairs[k]), k)):
            ps = cl2_pairs[k]
            if not ps:
                continue
            cands = None
            for pr in ps:
                cands = cl2_index[pr] if cands is None else cands & cl2_index[pr]
                if not cands:
                    break
            if not cands:
                continue
            best = None
            for k2 in sorted(cands):
                if k2 == k or k2 in cl2_dropped:
                    continue
                if _cl2_norm(k2[0]) == _cl2_norm(k[0]) or k2[1] != k[1]:
                    continue
                if len(cl2_pairs[k2]) < len(ps):
                    continue
                if len(cl2_pairs[k2]) == len(ps):
                    # Equal = mutual containment. Only with INTEGRATE_CROSSLINE_EQ ON, tie-break by
                    # "dedicated table > summary/connection band" (see above).
                    if not _cl_eq:
                        continue
                    if CROSSLINE_EQ_ANY_DEDICATED:
                        if not (_cl2_any_dedicated(k2) and not _cl2_any_dedicated(k)):
                            continue
                    elif not (_cl2_dedicated(k2) and not _cl2_dedicated(k)):
                        continue
                if not _cl2_same_offset(cl2_raw[k], cl2_raw[k2]):
                    continue
                if best is None or len(cl2_pairs[k2]) > len(cl2_pairs[best]):
                    best = k2
            if best is None:
                continue
            snap = sorted((st, minutes_to_hhmm(t)) for st, t in ps)
            if single_time_sheets and all(r.get('source_sheet') in single_time_sheets for r in by_trip[k]):
                cl_kept_single.append((k, best, snap, 'B.7c'))   # INTEGRATE_CROSSLINE_KEEP_DEPONLY: keep trips from single-station-time tables
                continue
            cl2_removed.append((k, best, snap))
            cl2_dropped.add(k)

        if cl2_removed:
            output_rows = [r for r in output_rows
                           if (r['line_name'], r['direction'], r['trip_num'])
                           not in cl2_dropped]
            print(f'  別線名に丸ごと含まれる短いトリップの除去(B.7c・統合後): '
                  f'{len(cl2_removed)}トリップ')
            if qa_rows is not None:
                for key, best, snap in cl2_removed:
                    qa_rows.append({
                        'key': f'{key[0]}__{key[1]}__{key[2]}',
                        'kind': 'crossline_dedup2', 'sheet': '', 'stop_name': '',
                        'dep_time': '', 'arr_time': '',
                        'detail': (f"統合後に別線名へ丸ごと含まれるため除去"
                                   f"{'（同数・専用表優先）' if len(cl2_pairs[best]) == len(snap) else ''}: "
                                   f"相手={best[0]}__{best[1]}__{best[2]} "
                                   f"({len(snap)}駅×時刻)"),
                    })
                    for st, hhmm in snap:
                        qa_rows.append({
                            'key': f'{key[0]}__{key[1]}__{key[2]}',
                            'kind': 'crossline_dedup2_stop', 'sheet': '',
                            'stop_name': st, 'dep_time': hhmm,
                            'arr_time': '', 'detail': '',
                        })

    # Trips kept by INTEGRATE_CROSSLINE_KEEP_DEPONLY
    if cl_kept_single:
        print(f'  ↑1 驛の時刻だけの表の便は落とさなかった（INTEGRATE_CROSSLINE_KEEP_DEPONLY）: '
              f'{len({k for k, _b, _s, _st in cl_kept_single})}トリップ')
        if qa_rows is not None:
            for key, best, snap, step in cl_kept_single:
                qa_rows.append({
                    'key': f'{key[0]}__{key[1]}__{key[2]}', 'kind': 'crossline_keep_single_time',
                    'sheet': '', 'stop_name': '', 'dep_time': '', 'arr_time': '',
                    'detail': (f"{step}: 1 驛の時刻だけを並べた表の便なので落とさない"
                               f"（{len(snap)}驛×時刻が {best[0]}__{best[1]}__{best[2]} と同じ）"),
                })

    # Step G: CSV output
    out_path  = os.path.join(OUTPUT_DIR, 'integrated_stop_times.csv')
    warn_path = os.path.join(OUTPUT_DIR, 'integrated_warnings.csv')

    with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(output_rows)

    with open(warn_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=WARN_FIELDS)
        w.writeheader()
        w.writerows(all_warnings)

    # Write the line names of each table (counted over all extracted records, as for INTEGRATE_CROSSLINE_EQ).
    #   SPLIT_CD_TABLE_FROM_INPUT in the split step uses this to decide "dedicated table" (counting on the
    #   split step's input would miss lines removed by dedup here).
    _tl = defaultdict(set)
    for r in all_records:
        t = _table_key(r.get('source_sheet'))
        if t is not None and r.get('line_name'):
            _tl[t].add(r['line_name'])
    with open(os.path.join(OUTPUT_DIR, 'table_lines.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['page', 'tb', 'line_name'])
        for (pg, tb), lines in sorted(_tl.items()):
            for ln in sorted(lines):
                w.writerow([pg, tb, ln])

    # Copy extract's flags (e.g. whether times were converted to Japan time) to the output, or remove a
    #   stale copy. build_gtfs_extras.py (stop_time_system.csv) reads it from INTEGRATED_DIR.
    _flags_in = os.path.join(INPUT_DIR, '_extract_flags.json')
    _flags_out = os.path.join(OUTPUT_DIR, '_extract_flags.json')
    if os.path.exists(_flags_in):
        import shutil
        shutil.copyfile(_flags_in, _flags_out)
    elif os.path.exists(_flags_out):
        os.remove(_flags_out)

    if qa_rows is not None:
        qa_fields = ['key', 'kind', 'sheet', 'stop_name',
                     'dep_time', 'arr_time', 'detail']
        os.makedirs(os.path.dirname(os.path.abspath(QA_LOG_PATH)), exist_ok=True)
        with open(QA_LOG_PATH, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=qa_fields)
            w.writeheader()
            w.writerows(qa_rows)
        n_ep = sum(1 for r in qa_rows if r['kind'].startswith('eprime'))
        n_un = sum(1 for r in qa_rows if r['kind'] == 'unselected_sheet')
        n_b5 = sum(1 for r in qa_rows if r['kind'] == 'b5_split')
        n_bc = sum(1 for r in qa_rows if r['kind'] == 'b5_conflict')
        n_wv = sum(1 for r in qa_rows if r['kind'] == 'weave_added')
        print(f'  QAログ: {QA_LOG_PATH}（E\'除去 {n_ep}・落選シート {n_un}・'
              f'B.5分割 {n_b5}・B.5証跡 {n_bc}・編み込み {n_wv}）')

    print(f'\n出力: {out_path}')
    print(f'  統合レコード数:   {len(output_rows):,}')
    print(f'  GTFSトリップ数:   {len(groups) - len(cl2_removed):,}')
    print(f'  warnings:         {len(all_warnings)} 件')
    if all_warnings:
        print(f'  詳細: {warn_path}')


if __name__ == '__main__':
    main()
