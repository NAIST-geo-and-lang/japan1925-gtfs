"""
infer_coords.py

Give estimated coordinates to stations in stops_master.csv that have none, using line and stop_sequence
information.

stops_master.csv is keyed by (stop_name, line_name); each (name, line) has its own coordinates.

Algorithm:
  1. Build the station order of each trip from integrated_stop_times.csv
  2. Read distances between stations from data/distance/lookup_segments_summary.csv
  3. Interpolate within each trip, using stations that already have coordinates as anchors
     - if the physical distance between anchors is known (distance lookup) -> interpolate in proportion to distance
     - otherwise -> equal spacing by stop_sequence (fallback)
  4. One (name, line) can get several estimates from several trips; they are averaged

Environment variables:
  INFER_COORDS_RELIABLE_ONLY=1 uses only reliable sources as anchors
  INFER_COORDS_NO_DISTANCE=1   does not use the distance lookup (old algorithm)
  INFER_COORDS_EXCLUDE_KB_DERIVED=1
      excludes stations whose coord_kind is 'derived' in the coordinate tables (values placed by mileage
      interpolation or automatic estimation) from the anchors (no interpolation on top of interpolation). Default OFF.
      With it ON, fewer anchors may leave some stations without coordinates.
  INFER_COORDS_STRIP_TAG=0
      Default ON: the 〈region〉 tag is stripped from station names when looking up the distance table.
      0 = previous behavior (look up with the tag).
"""

import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_knowledge  # noqa: E402  (lookup_kind gives coord_kind)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOPS_MASTER = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'stops_master.csv')
INTEGRATED = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'integrated_stop_times.csv')
SEGMENTS_LOOKUP = os.path.join(BASE_DIR, 'data', 'distance', 'lookup_segments_summary.csv')


_ALL_FIELDS = []


def load_stops_master():
    """Return a map (name, line) -> dict."""
    global _ALL_FIELDS
    with open(STOPS_MASTER, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        _ALL_FIELDS = list(reader.fieldnames or [])
        rows = list(reader)
    stops = {}
    for r in rows:
        lat = r.get('stop_lat', '')
        lon = r.get('stop_lon', '')
        d = dict(r)
        d['stop_lat'] = float(lat) if lat else None
        d['stop_lon'] = float(lon) if lon else None
        key = (r['stop_name'], r.get('line_name', ''))
        stops[key] = d
    return stops


def load_trips():
    """Return the station order of each trip as a sequence of (name, line)."""
    with open(INTEGRATED, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    trip_stops = defaultdict(list)
    for r in rows:
        key = r['gtfs_trip_key']
        trip_stops[key].append((
            int(r['stop_sequence']),
            r['stop_name'],
            r['line_name'],
        ))

    trip_seqs = {}
    for key, stops in trip_stops.items():
        stops.sort(key=lambda x: x[0])
        trip_seqs[key] = [(s[1], s[2]) for s in stops]
    return trip_seqs


def load_segment_lookup():
    """
    Return a dict (line_name, frozenset({stop_a, stop_b})) -> segment_km.
    When there are several values (minor_variance), the mean of min and max is used.
    Pairs not in the table are absent (lookups give None).
    """
    if os.environ.get('INFER_COORDS_NO_DISTANCE', '0') == '1':
        return {}

    if not os.path.exists(SEGMENTS_LOOKUP):
        print(f'Warning: {SEGMENTS_LOOKUP} not found, falling back to sequence-based')
        return {}

    seg = {}
    with open(SEGMENTS_LOOKUP, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                line = r['line_name']
                a = r['stop_a']
                b = r['stop_b']
                # mean of min and max (the same value when consistent)
                km = (float(r['min_km']) + float(r['max_km'])) / 2
                seg[(line, frozenset([a, b]))] = km
            except (KeyError, ValueError):
                continue
    return seg


def _in_valid_range(lat, lon):
    return 21 <= lat <= 54 and 110 <= lon <= 146


_RELIABLE_SOURCES = {
    'agent_known',           # coordinate tables (data/knowledge/places/)
    'existing',              # earlier trusted coordinates
    'wikipedia_ja',
    'wikidata',
    'manual',
    'line_center_inferred',
    # 'perline' is not a trusted anchor: it can match a different station of the same name
}


_EXCLUDED_DERIVED_ANCHORS = set()   # anchors actually excluded (counted at the end)


# Also use proxy points (coord_source = release_proxy in the coordinate tables: MLIT location reference points,
# Wikidata place points, etc.) as interpolation anchors (comma-separated coord_source values; default empty).
# Without them, stations at proxy points can alternate with stations placed on a straight line between distant
# reliable stations, making the route zigzag.
_EXTRA_ANCHOR_SOURCES = {x.strip() for x in os.environ.get('INFER_COORDS_EXTRA_ANCHORS', '').split(',') if x.strip()}


def _is_reliable_anchor(s):
    if os.environ.get('INFER_COORDS_RELIABLE_ONLY', '0') != '1':
        return True
    src = (s.get('coord_source') or '').strip()
    if src not in _RELIABLE_SOURCES and src not in _EXTRA_ANCHOR_SOURCES:
        return False
    # values placed by calculation are not anchors, even from the coordinate tables (default OFF)
    if src == 'agent_known' and os.environ.get('INFER_COORDS_EXCLUDE_KB_DERIVED', '0') == '1':
        key = (s.get('stop_name', ''), s.get('line_name') or '')
        if agent_knowledge.lookup_kind(key[0], key[1] or None) == 'derived':
            _EXCLUDED_DERIVED_ANCHORS.add(key)
            return False
    return True


# When looking up the distance table (lookup_segments_summary.csv, no 〈region〉 tags), strip the tag from stops_master
#   station names (e.g. 平壤〈朝鮮〉). Otherwise the section beyond a tagged station is interpolated by equal spacing in
#   stop order instead of by mileage. Default ON. Previous behavior = INFER_COORDS_STRIP_TAG=0.
STRIP_TAG = os.environ.get('INFER_COORDS_STRIP_TAG', '1') == '1'
# A trip with only one anchor (e.g. a two-station band) has no direction, so it gives provisional values shifted by
#   0.005 degrees (about 500 m) per station to the north-east / south-west. These are used only for stations with no
#   estimate from any other trip (averaging them with other trips' values pulls the result toward the anchor).
#   Default ON. Previous behavior (averaged with equal weight) = INFER_COORDS_LONE_ANCHOR_LAST=0
#   (--no-lone-anchor-last in run_pipeline.sh).
LONE_ANCHOR_LAST = os.environ.get('INFER_COORDS_LONE_ANCHOR_LAST', '1') == '1'
# The distance table (transcribed station names) is looked up exactly with stops_master station names (whose spelling
#   integration aligned to the more common form, INTEGRATE_CANON_STOP_GLOBAL); only for sections with no exact hit,
#   both sides are normalized to new forms with scripts/known_kanji_variants.py and looked up again.
#   Default ON. Previous behavior = INFER_COORDS_NAME_VARIANTS=0 (--no-infer-name-variants in run_pipeline.sh).
NAME_VARIANTS = os.environ.get('INFER_COORDS_NAME_VARIANTS', '1') != '0'
if NAME_VARIANTS:
    import known_kanji_variants as _kv  # noqa: E402


def _nv(s):
    return _kv.normalize(s, prefer_new=True) if s else s


_NORM_CACHE = {}


def _get_segment(k1, k2, segment_lookup):
    """Get segment_km for a pair of adjacent stations; a hit with either station's line_name is enough."""
    name1, line1 = k1
    name2, line2 = k2
    if STRIP_TAG:
        name1, name2 = name1.split('〈')[0], name2.split('〈')[0]
    pair = frozenset([name1, name2])
    for line in (line1, line2):
        km = segment_lookup.get((line, pair))
        if km is not None:
            return km
    if NAME_VARIANTS:
        npair = frozenset([_nv(name1), _nv(name2)])
        norm = _NORM_CACHE.get(id(segment_lookup))
        if norm is None:
            norm = {}
            for (ln, pr), v in segment_lookup.items():
                norm.setdefault((_nv(ln), frozenset(_nv(x) for x in pr)), v)
            _NORM_CACHE[id(segment_lookup)] = norm
        for line in (line1, line2):
            km = norm.get((_nv(line), npair))
            if km is not None:
                return km
    return None


def _compute_trip_positions(stop_keys, segment_lookup):
    """
    Return, for each station of the trip, the cumulative physical distance [km] from the trip's first station.
    None from the first unknown segment onward.
    All floats if every segment is known; otherwise the tail is None.
    """
    n = len(stop_keys)
    positions = [0.0] + [None] * (n - 1)
    for i in range(1, n):
        seg = _get_segment(stop_keys[i - 1], stop_keys[i], segment_lookup)
        if seg is None or positions[i - 1] is None:
            positions[i] = None
        else:
            positions[i] = positions[i - 1] + seg
    return positions


def _ratio_in_segment(positions, ai, bi, j):
    """
    Return the ratio at j within the anchor section [ai, bi].
    Proportional to distance if positions are known at both ends and at j; otherwise by sequence.
    """
    if (positions[ai] is not None and
        positions[bi] is not None and
        positions[j] is not None):
        span = positions[bi] - positions[ai]
        if span > 0:
            return (positions[j] - positions[ai]) / span
    # fallback: sequence-based
    span_seq = bi - ai
    if span_seq <= 0:
        return 0.0
    return (j - ai) / span_seq


def interpolate_on_trip(stop_keys, stops_dict, accumulator, segment_lookup, weak_accumulator=None):
    """
    Interpolate a trip's (name, line) sequence from reliable anchors.
    Proportional to distance where the distance lookup covers the section, otherwise equal spacing by sequence.
    With weak_accumulator, extrapolation from a trip with only one anchor (no direction, so provisional values shifted
    by 0.005 degrees per station to the north-east / south-west) goes there instead (INFER_COORDS_LONE_ANCHOR_LAST).
    """
    # position within the trip by physical distance
    positions = _compute_trip_positions(stop_keys, segment_lookup)

    # collect anchors
    anchors = []
    for i, k in enumerate(stop_keys):
        s = stops_dict.get(k)
        if s and s['stop_lat'] is not None:
            if _in_valid_range(s['stop_lat'], s['stop_lon']) and _is_reliable_anchor(s):
                anchors.append((i, s['stop_lat'], s['stop_lon']))

    if not anchors:
        return 0
    if weak_accumulator is not None and len(anchors) == 1:
        accumulator = weak_accumulator

    filled = 0

    # from the start to the first anchor (extrapolation)
    if anchors[0][0] > 0:
        ai, alat, alon = anchors[0]
        # always compute the delta for the sequence-based fallback
        if len(anchors) >= 2:
            bi, blat, blon = anchors[1]
            dlat = (blat - alat) / (bi - ai) if bi != ai else 0
            dlon = (blon - alon) / (bi - ai) if bi != ai else 0
            # per-km coefficients when distance-based interpolation is possible
            if (positions[ai] is not None and positions[bi] is not None and
                positions[bi] - positions[ai] > 0):
                span_km = positions[bi] - positions[ai]
                dlat_per_km = (blat - alat) / span_km
                dlon_per_km = (blon - alon) / span_km
                use_distance = True
            else:
                use_distance = False
        else:
            dlat, dlon = 0.005, 0.005
            use_distance = False

        for j in range(ai):
            k = stop_keys[j]
            s = stops_dict.get(k)
            if s and s['stop_lat'] is None:
                if use_distance and positions[j] is not None:
                    delta_km = positions[j] - positions[ai]  # negative (j is before ai)
                    new_lat = alat + dlat_per_km * delta_km
                    new_lon = alon + dlon_per_km * delta_km
                else:
                    new_lat = alat - dlat * (ai - j)
                    new_lon = alon - dlon * (ai - j)
                if _in_valid_range(new_lat, new_lon):
                    accumulator[k].append((new_lat, new_lon))
                    filled += 1

    # between anchors (interpolation)
    for k_idx in range(len(anchors) - 1):
        ai, alat, alon = anchors[k_idx]
        bi, blat, blon = anchors[k_idx + 1]
        span = bi - ai
        if span <= 1:
            continue
        for j in range(ai + 1, bi):
            k = stop_keys[j]
            s = stops_dict.get(k)
            if s and s['stop_lat'] is None:
                ratio = _ratio_in_segment(positions, ai, bi, j)
                new_lat = alat + (blat - alat) * ratio
                new_lon = alon + (blon - alon) * ratio
                if _in_valid_range(new_lat, new_lon):
                    accumulator[k].append((new_lat, new_lon))
                    filled += 1

    # from the last anchor to the end (extrapolation)
    if anchors[-1][0] < len(stop_keys) - 1:
        ai, alat, alon = anchors[-1]
        if len(anchors) >= 2:
            pi, plat, plon = anchors[-2]
            dlat = (alat - plat) / (ai - pi) if ai != pi else 0
            dlon = (alon - plon) / (ai - pi) if ai != pi else 0
            if (positions[pi] is not None and positions[ai] is not None and
                positions[ai] - positions[pi] > 0):
                span_km = positions[ai] - positions[pi]
                dlat_per_km = (alat - plat) / span_km
                dlon_per_km = (alon - plon) / span_km
                use_distance = True
            else:
                use_distance = False
        else:
            dlat, dlon = 0.005, 0.005
            use_distance = False

        for j in range(ai + 1, len(stop_keys)):
            k = stop_keys[j]
            s = stops_dict.get(k)
            if s and s['stop_lat'] is None:
                if use_distance and positions[j] is not None:
                    delta_km = positions[j] - positions[ai]  # positive
                    new_lat = alat + dlat_per_km * delta_km
                    new_lon = alon + dlon_per_km * delta_km
                else:
                    new_lat = alat + dlat * (j - ai)
                    new_lon = alon + dlon * (j - ai)
                if _in_valid_range(new_lat, new_lon):
                    accumulator[k].append((new_lat, new_lon))
                    filled += 1

    return filled


def main():
    stops = load_stops_master()
    trips = load_trips()
    segment_lookup = load_segment_lookup()

    no_coord_before = sum(1 for s in stops.values() if s['stop_lat'] is None)
    use_dist = 'with' if segment_lookup else 'WITHOUT'
    print(f'座標なし(name,line): {no_coord_before}')
    if os.environ.get('INFER_COORDS_EXCLUDE_KB_DERIVED', '0') == '1':
        print('INFER_COORDS_EXCLUDE_KB_DERIVED=1: KB の derived をアンカーから外す')
    print(f'distance lookup: {len(segment_lookup)} segment entries ({use_dist} distance)')

    # count the trips where distance-based interpolation applies
    if segment_lookup:
        full_dist_trips = 0
        partial_dist_trips = 0
        no_dist_trips = 0
        for stop_keys in trips.values():
            positions = _compute_trip_positions(stop_keys, segment_lookup)
            n_known = sum(1 for p in positions if p is not None)
            if n_known == len(positions):
                full_dist_trips += 1
            elif n_known > 1:
                partial_dist_trips += 1
            else:
                no_dist_trips += 1
        print(f'  全駅 distance 既知 trip: {full_dist_trips}')
        print(f'  一部 distance 既知 trip: {partial_dist_trips}')
        print(f'  distance 不在 trip:     {no_dist_trips}')

    # interpolate in several passes
    for pass_num in range(1, 6):
        remaining_before = sum(1 for s in stops.values() if s['stop_lat'] is None)
        if remaining_before == 0:
            break

        accumulator = defaultdict(list)
        weak = defaultdict(list) if LONE_ANCHOR_LAST else None
        for tk, stop_keys in trips.items():
            if pass_num >= 2:
                has_missing = any(
                    stops.get(k) and stops[k]['stop_lat'] is None
                    for k in stop_keys
                )
                if not has_missing:
                    continue
            interpolate_on_trip(stop_keys, stops, accumulator, segment_lookup, weak)
        if weak:
            # Provisional values from single-anchor trips are not used for stations that other trips could estimate
            # (only for stations with nothing else)
            dropped = []
            for k, vals in weak.items():
                if k not in accumulator:
                    accumulator[k] = vals
                elif stops.get(k) and stops[k]['stop_lat'] is None:
                    dropped.append(k)
            if dropped:
                print(f'INFER_COORDS_LONE_ANCHOR_LAST=1: Pass {pass_num} でアンカー 1 つの便の仮の値を使わなかった驛 {len(dropped)}＝'
                      + '・'.join(f'{n}（{l}）' for n, l in sorted(dropped)[:12]) + ('…' if len(dropped) > 12 else ''))

        filled = 0
        for k, vals in accumulator.items():
            s = stops.get(k)
            if s and s['stop_lat'] is None:
                avg_lat = sum(v[0] for v in vals) / len(vals)
                avg_lon = sum(v[1] for v in vals) / len(vals)
                if _in_valid_range(avg_lat, avg_lon):
                    s['stop_lat'] = avg_lat
                    s['stop_lon'] = avg_lon
                    filled += 1

        remaining_after = sum(1 for s in stops.values() if s['stop_lat'] is None)
        print(f'Pass {pass_num}: {filled} 駅補間 (残り {remaining_after})')
        if remaining_after == remaining_before:
            break

    no_coord_after = sum(1 for s in stops.values() if s['stop_lat'] is None)
    print(f'\n座標なし(name,line) (処理後): {no_coord_after}')

    if no_coord_after > 0:
        print('\n座標未確定:')
        for (name, line), s in sorted(stops.items()):
            if s['stop_lat'] is None:
                print(f'  {name} on {line}')

    # save
    fieldnames = _ALL_FIELDS or ['stop_id', 'stop_name', 'line_name', 'canonical_name',
                                   'stop_type', 'stop_lat', 'stop_lon', 'coord_source']
    with open(STOPS_MASTER, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for k, s in sorted(stops.items(), key=lambda x: x[1]['stop_id']):
            row = {kk: s.get(kk, '') for kk in fieldnames}
            if s.get('stop_lat') is not None:
                row['stop_lat'] = f"{s['stop_lat']:.6f}"
                row['stop_lon'] = f"{s['stop_lon']:.6f}"
            else:
                row['stop_lat'] = ''
                row['stop_lon'] = ''
            if 'coord_source' in fieldnames:
                if s.get('stop_lat') is not None:
                    # has coordinates and coord_source is empty, 'none' or 'nullified_*' -> set to 'inferred'
                    cur = s.get('coord_source', '') or ''
                    if (not cur or cur in ('none', 'wd_out_of_range', 'wd_miss',
                                            'nullified_anomaly', 'nullified_broken_line',
                                            'nullified_sea')):
                        row['coord_source'] = 'inferred'
                elif s.get('stop_lat') is None:
                    if not s.get('coord_source') or s.get('coord_source') == 'inferred':
                        row['coord_source'] = 'none'
            writer.writerow(row)
    if _EXCLUDED_DERIVED_ANCHORS:
        print(f'アンカーから外した KB derived: {len(_EXCLUDED_DERIVED_ANCHORS)} 駅')
    print(f'\nstops_master.csv 更新完了: {STOPS_MASTER}')


if __name__ == '__main__':
    main()
