"""
generate_router_data.py

Build router_data.json from GTFS data: the data file used by the journey planner
(demo/route_planner/index.html).

Station groups (like parent_station):
  (name, line) stations with the same name within GROUP_DIST_KM are merged into one
  group, and stops in trips are identified by group ID (`G00001`...). This keeps
  e.g. 大久保 on the Chūō line and 大久保 in Hyōgo as different stations.

Output: gtfs/router_data.json
  {
    "groups": {
      "G00001": {"name": "東京", "lat": 35.68, "lon": 139.77},
      ...
    },
    "name_to_groups": {
      "東京": ["G00001"],
      "大久保": ["G00123", "G00456", "G00789"],   // 3 stations with the same name
      ...
    },
    "trips": [
      {
        "k": "東海道本線__outbound__21",
        "l": "東海道本線",
        "d": "outbound",
        "n": "21",
        "s": ["G00001", "G00010", ...],   // group_id sequence
        "dep": ["08:00", null, ...],
        "arr": [null, "08:15", ...]
      }, ...
    ]
  }
"""

import csv
import json
import math
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# GTFS_DIR / INTEGRATED_DIR as in the other scripts. An absolute path in the variable wins in
# os.path.join, so folders outside data/ can be used.
GTFS_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs'))
STOPS_MASTER = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'),
                            'stops_master.csv')
OUT_JSON = os.path.join(GTFS_DIR, 'router_data.json')
OUT_JS = os.path.join(GTFS_DIR, 'router_data.js')

# Distance (km) within which stations with the same name form one group.
# Kept loose because the accuracy of 1925 coordinates varies.
GROUP_DIST_KM = 5.0
# Group key = normalized base name (〈region〉 tag removed, old/new character forms unified by
#   known_kanji_variants) instead of the exact name, so the same station within 5 km is not split by a
#   tag (稚内 / 稚内〈北海道〉) or character form (稚內 / 稚内). name_to_groups lists every spelling.
#   Default ON. Previous behavior (exact name) = ROUTER_GROUP_NORMALIZE=0.
GROUP_NORMALIZE = os.environ.get('ROUTER_GROUP_NORMALIZE', '1') != '0'
# Do not merge same-name stations that are far apart (e.g. 中野 on 西武鐵道新宿線 and 中央本線, 1,611 m;
#   博多 station and port, 2.2 km), which would otherwise allow 0-minute transfers.
#   When ON, two stations whose coordinates are both reliable (coord_kind = authority in the coordinate
#   tables, and the stops_master value within 10 m of the table value) and more than
#   ROUTER_GROUP_SAME_NAME_SPLIT_M apart become separate groups. Pairs with a less reliable coordinate
#   (proxy, derived, interpolated) are still merged within 5 km.
#   Split pairs are joined by walking links (ROUTER_WALK_EDGES), up to ROUTER_WALK_SAME_NAME_MAX_M even
#   beyond 1 km (0 = no extension).
#   Default ON. Previous behavior (same name within 5 km = one station) = ROUTER_GROUP_SAME_NAME_SPLIT=0.
GROUP_SAME_NAME_SPLIT = os.environ.get('ROUTER_GROUP_SAME_NAME_SPLIT', '1') != '0'
GROUP_SAME_NAME_SPLIT_M = float(os.environ.get('ROUTER_GROUP_SAME_NAME_SPLIT_M', '300'))
WALK_SAME_NAME_MAX_M = float(os.environ.get('ROUTER_WALK_SAME_NAME_MAX_M', '5000'))
# Also split stations with proxy coordinates (e.g. 敦賀 and 高知: station vs. port). A proxy point may be
#   off by ROUTER_GROUP_SAME_NAME_SPLIT_PROXY_M (default 1,000 m); two stations are split when their
#   distance exceeds GROUP_SAME_NAME_SPLIT_M plus both margins (authority + proxy: over 1.3 km;
#   proxy + proxy: over 2.3 km). Only when the coordinate is within 10 m of the table value.
#   Split pairs are joined by walking up to ROUTER_WALK_SAME_NAME_MAX_M.
#   Default ON. Previous behavior = ROUTER_GROUP_SAME_NAME_SPLIT_PROXY=0.
GROUP_SAME_NAME_SPLIT_PROXY = os.environ.get('ROUTER_GROUP_SAME_NAME_SPLIT_PROXY', '1') != '0'
GROUP_SAME_NAME_SPLIT_PROXY_M = float(os.environ.get('ROUTER_GROUP_SAME_NAME_SPLIT_PROXY_M', '1000'))
# Stations whose coord_source is release_proxy (a place point, not a station) or wikidata (a Wikidata
#   station item): (1) included in walking links; (2) margin for same-name splitting = 0 for wikidata,
#   ROUTER_PUBLIC_PLACE_MARGIN_M (default 1,000 m) for release_proxy; (3) proximity merging (50 m) as for
#   other stations. If ROUTER_PUBLIC_PLACE_WALK_MAX_M (default 0 = no limit) > 0, walking links touching
#   a release_proxy station are limited to that distance.
#   build_release_gtfs.py uses the same rules for parent stations and transfers.txt.
PUBLIC_WALK_SRC = ('release_proxy', 'wikidata')
PUBLIC_PLACE_MARGIN_M = float(os.environ.get('ROUTER_PUBLIC_PLACE_MARGIN_M', '1000'))
PUBLIC_PLACE_WALK_MAX_M = float(os.environ.get('ROUTER_PUBLIC_PLACE_WALK_MAX_M', '0'))
# Through trains: one train printed in one column is split into 2-5 trips at line-name boundaries.
#   Each trip gets 'p' = physical_train_id from data/tables/through_trains/physical_trains.csv
#   (links judged 継続_確定 "confirmed continuation", chained), and the search counts no transfer when
#   the next trip has the same p. Trips without p count as transfers. GTFS is not changed.
#   Default ON. Previous behavior (every change counts as a transfer) = ROUTER_PHYSICAL_TRAINS=0.
#   The table path can be set with ROUTER_PHYSICAL_TRAINS_CSV.
PHYSICAL_TRAINS = os.environ.get('ROUTER_PHYSICAL_TRAINS', '1') != '0'

# Write `meta` to router_data (when and from which GTFS it was built, sizes), so the page and checks
#   can detect a mismatch between code and data. Default ON. Previous behavior (no `meta`) = ROUTER_DATA_META=0.
DATA_META = os.environ.get('ROUTER_DATA_META', '1') != '0'

# Walking links: private-railway "新○○" stations are often a short walk from the government-railway
#   station (新武生 305 m, 新今市 442 m, ...). Merging with a larger radius would collapse both into one
#   point, so they are kept as walks instead.
#   Group pairs within ROUTER_WALK_MAX_M go to `walks` (group_id -> [[other group_id, minutes], ...]);
#   minutes = distance / ROUTER_WALK_SPEED_M_PER_MIN, rounded up. Same exclusions as proximity merging
#   ((1) adjacent stops on the same line, (2) coordinates not from the coordinate tables). The search
#   allows one walk before boarding (no chained walks).
#   Default ON. Previous behavior (no `walks`) = ROUTER_WALK_EDGES=0.
WALK_EDGES = os.environ.get('ROUTER_WALK_EDGES', '1') != '0'   # default ON (previous behavior = 0)
WALK_MAX_M = float(os.environ.get('ROUTER_WALK_MAX_M', '1000'))
WALK_SPEED_M_PER_MIN = float(os.environ.get('ROUTER_WALK_SPEED_M_PER_MIN', '80'))
# Proximity merging: stations with different names but close coordinates (e.g. government-railway
#   「鹿兒島」 and the tram stop 「停車場前」) form one group. Only distance counts (not name or company),
#   but adjacent stops on the same line are not merged (tram stops ~300 m apart would collapse the line).
#   Record = GTFS_DIR/router_group_near.csv.
#   Default ON. Previous behavior = ROUTER_GROUP_NEAR=0. Distance = ROUTER_GROUP_NEAR_M (below).
GROUP_NEAR = os.environ.get('ROUTER_GROUP_NEAR', '1') != '0'
# Proximity merging distance, default 50 m: merging means "the same place listed under two names".
#   Close but separate places beyond 50 m (岐阜/新岐阜 160 m, 刈谷/刈谷新 86 m, ...) are handled by
#   1-3 minute walking links (ROUTER_WALK_EDGES), so no 0-minute transfer needs a walk.
#   Previous behavior = ROUTER_GROUP_NEAR_M=250.
GROUP_NEAR_M = float(os.environ.get('ROUTER_GROUP_NEAR_M', '50'))
# Close the chaining gap in proximity merging: the "adjacent stops on the same line" exclusion looks at
#   one pair only, so a chain through other pairs can still put two adjacent stops in one group (e.g.
#   merging 黑崎 on 鹿兒島本線 with 黑崎驛前 on 九州電氣軌道線 made a trip pass 黑崎 twice).
#   When ON, a merge is refused if it would make one trip pass the same group twice, checked per
#   current connected component (not per pair).
#   Default ON. Previous behavior (chains allowed) = ROUTER_GROUP_NEAR_TRIP_GUARD=0.
GROUP_NEAR_TRIP_GUARD = os.environ.get('ROUTER_GROUP_NEAR_TRIP_GUARD', '1') != '0'
# Proximity merging must not rejoin same-name stations split as different places: it ignores names,
#   so a stop of another line at the same point can bridge them (e.g. 西大分: the 大阪商船 port and
#   西大分 station on 日豐本線, 642 m apart).
#   When ON: (1) refuse a merge that would put a "same name, different place" pair (_same_name_apart)
#   into one group, checked per connected component; (2) in build_groups, when several groups could
#   take a station, use the nearest instead of the first created.
#   Default ON. Previous behavior = ROUTER_GROUP_NEAR_SAME_NAME_GUARD=0.
GROUP_NEAR_SAME_NAME_GUARD = os.environ.get('ROUTER_GROUP_NEAR_SAME_NAME_GUARD', '1') != '0'
# Collapse consecutive stops in the same group on estimated trips. Frequency-only template trips have
#   stations without times; name and proximity merging can put adjacent stops of one line in one group
#   (靜岡 and 靜岡驛前 on 靜岡電氣鐵道線 both join the government-railway 靜岡), and the search does not
#   use the second of two consecutive same-group stops as a transfer point.
#   When ON, such runs in template trips expanded to estimated trips become one stop (keep the stop with
#   a time; if neither has one keep the first; if both have times keep both). GTFS and printed trips
#   are not changed. Default ON. Previous behavior = ROUTER_EST_SAME_GROUP_COLLAPSE=0.
EST_SAME_GROUP_COLLAPSE = os.environ.get('ROUTER_EST_SAME_GROUP_COLLAPSE', '1') == '1'
# Boarding candidates and labels kept per station. Without this, the search boards only the earliest
#   trip per (line, direction, terminus) and keeps only the earliest arrival per station, which drops
#   overtaking trains and can lose routes at the transfer limit (10).
#   ROUTER_EXACT_SEARCH=1 writes two flags to router_params in router_data (GTFS is not changed):
#     EXACT_CANDIDATES = earliest trip per identical stop sequence (keeping every trip that reaches
#       some station earlier when overtaking occurs)
#     PARETO_TRANSFERS = keep labels not dominated in both arrival time and number of transfers
#   They are always set together (one variable); either alone makes some searches slower or fail.
#   Default ON. Previous behavior = ROUTER_EXACT_SEARCH=0.
EXACT_SEARCH = os.environ.get('ROUTER_EXACT_SEARCH', '1') != '0'
EXACT_CANDIDATES = PARETO_TRANSFERS = EXACT_SEARCH
# Also board today's part of a trip that started the previous day. Without this, boarding times only
#   shift forward by days, so at stations with times of 24:00 or later the search waits for the next
#   day (e.g. 上平井 24:02 departure of 三蟠鐵道線 28 cannot be boarded at 0:01).
#   When ON, writes PREV_DAY_BOARDING and PARETO_CONTINUATION to router_params: boarding times also
#   shift back by days (each leg has dayShift, which the page uses for times), and each station keeps
#   labels that can continue on the same through train. GTFS is not changed.
#   Default ON. Previous behavior = ROUTER_PREV_DAY_BOARDING=0.
PREV_DAY_BOARDING = os.environ.get('ROUTER_PREV_DAY_BOARDING', '1') != '0'
# Among routes arriving at the same time, take the one with fewer transfers (otherwise the first found
#   wins, which can add a transfer). Writes TIE_FEWER_TRANSFERS to router_params; arrival times do not
#   change. Default ON. Previous behavior (flag not written) = ROUTER_TIE_FEWER_TRANSFERS=0.
TIE_FEWER_TRANSFERS = os.environ.get('ROUTER_TIE_FEWER_TRANSFERS', '1') != '0'
# A label reached on foot must not remove a label reached by train at the same station: an early walk
#   arrival (which cannot walk again) would otherwise hide a later train arrival that can walk on.
#   Writes WALK_LABELS_SEPARATE to router_params, and walk arrivals are kept in a separate table
#   (effective only with PARETO_TRANSFERS = ROUTER_EXACT_SEARCH). GTFS is not changed.
#   Default ON. Previous behavior (flag not written) = ROUTER_WALK_LABELS_SEPARATE=0.
WALK_LABELS_SEPARATE = os.environ.get('ROUTER_WALK_LABELS_SEPARATE', '1') != '0'
# Do not revisit a station already used in the same journey (boarded, alighted, walked to, or the
#   origin); a real traveler would wait there instead. Otherwise the no-chained-walks rule can be
#   bypassed by riding out and back. Stations only passed through do not count.
#   Writes NO_REVISIT to router_params. GTFS is not changed. scripts/release/route_1925.py uses the
#   same rule. Default ON. Previous behavior (flag not written) = ROUTER_NO_REVISIT=0.
NO_REVISIT = os.environ.get('ROUTER_NO_REVISIT', '1') != '0'
PHYSICAL_TRAINS_CSV = os.environ.get('ROUTER_PHYSICAL_TRAINS_CSV',
                                     os.path.join(BASE_DIR, 'data', 'tables', 'through_trains', 'physical_trains.csv'))


def load_physical_trains(path):
    """trip_key (line__direction__number) -> physical_train_id. Stops if a key is in two trains (inconsistent table)."""
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            k = r['trip_key']
            if k in out and out[k] != r['physical_train_id']:
                raise SystemExit(f'physical_trains.csv: {k} が 2 本の物理列車に入っている（{out[k]} / {r["physical_train_id"]}）')
            out[k] = r['physical_train_id']
    return out
try:
    from known_kanji_variants import normalize as _kv_normalize
except Exception:      # pragma: no cover
    _kv_normalize = None


try:
    # Tags for same-name stations on islands (〈嚴島〉) = disambiguate_stations.ISLAND_TAGS (DISAMBIG_ISLAND_TAG, default ON).
    from disambiguate_stations import ISLAND_TAG_NAMES as _KEEP_GROUP_TAGS
except Exception:      # pragma: no cover
    _KEEP_GROUP_TAGS = set()


def _group_key(name):
    if not GROUP_NORMALIZE or _kv_normalize is None:
        return name
    base, _, tag = name.partition('〈')
    key = _kv_normalize(base, prefer_new=True)
    # Keep the island tag so island stations are not merged with mainland stations of the same name
    #   (region tags such as 〈朝鮮〉 are still removed). Such names exist only with DISAMBIG_ISLAND_TAG=1 (default).
    tag = tag.rstrip('〉')
    if tag and tag in _KEEP_GROUP_TAGS:
        key += f'〈{tag}〉'
    return key


def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return float('inf')
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


_SURE_CACHE = {}


def _coord_margin(info):
    """How far a coordinate may be off, for GROUP_SAME_NAME_SPLIT: 0 (a source point of the station itself),
    GROUP_SAME_NAME_SPLIT_PROXY_M (a proxy point; only with GROUP_SAME_NAME_SPLIT_PROXY), or None (not used).
    Based on coord_source = agent_known, the coord_kind in the coordinate tables, and the stops_master value
    being within 10 m of the table value. wikidata stations get 0; release_proxy stations get
    PUBLIC_PLACE_MARGIN_M (only with GROUP_SAME_NAME_SPLIT_PROXY)."""
    if info.get('lat') is not None and info.get('lon') is not None:
        if info.get('src') == 'wikidata':
            return 0.0
        if info.get('src') == 'release_proxy':
            return PUBLIC_PLACE_MARGIN_M if GROUP_SAME_NAME_SPLIT_PROXY else None
    if info.get('src') != 'agent_known' or info.get('lat') is None or info.get('lon') is None:
        return None
    k = (info['name'], info['line'], info['lat'], info['lon'])
    if k not in _SURE_CACHE:
        import agent_knowledge as _ak
        margin = None
        kind = _ak.lookup_kind(info['name'], info['line'])
        if kind == 'authority' or (GROUP_SAME_NAME_SPLIT_PROXY and kind == 'proxy'):
            c = _ak.lookup(info['name'], info['line'])
            if c and haversine(c[0], c[1], info['lat'], info['lon']) * 1000 <= 10:
                margin = 0.0 if kind == 'authority' else GROUP_SAME_NAME_SPLIT_PROXY_M
        _SURE_CACHE[k] = margin
    return _SURE_CACHE[k]


def _coord_is_sure(info):
    """Whether the coordinate can be used for splitting (authority, or proxy with GROUP_SAME_NAME_SPLIT_PROXY)."""
    return _coord_margin(info) is not None


def _same_name_apart(a, b):
    """Whether two same-name stations are different places: both coordinates usable and farther apart than
    GROUP_SAME_NAME_SPLIT_M plus both margins (without GROUP_SAME_NAME_SPLIT_PROXY: authority pairs only, margin 0)."""
    ma, mb = _coord_margin(a), _coord_margin(b)
    return (ma is not None and mb is not None
            and haversine(a['lat'], a['lon'], b['lat'], b['lon']) * 1000 > GROUP_SAME_NAME_SPLIT_M + ma + mb)


def build_groups(stops_info):
    """stops_info: {stop_id -> {name, line, lat, lon}}
    Give stops with the same name that are close together the same group_id.
    With GROUP_SAME_NAME_SPLIT, a stop is not added to a group containing a "different place" (_same_name_apart).
    """
    groups = {}              # group_id -> {name, lat, lon, members: [stop_id]}
    group_of_stop = {}       # stop_id -> group_id
    name_to_groups = defaultdict(list)  # name -> [group_id]
    next_id = 0

    # Process same-name sets in turn
    name_to_stops = defaultdict(list)
    for sid, info in stops_info.items():
        name_to_stops[_group_key(info['name'])].append(sid)
    key_to_groups = defaultdict(list)   # key -> [group_id] (the key is separate from the display name)

    for key, sids in name_to_stops.items():
        # Cluster stations with the same key
        for sid in sids:
            info = stops_info[sid]
            assigned = None
            best_d = None
            for gid in key_to_groups[key]:
                g = groups[gid]
                d_g = haversine(info['lat'], info['lon'], g['lat'], g['lon'])
                if d_g <= GROUP_DIST_KM:
                    if GROUP_SAME_NAME_SPLIT and any(_same_name_apart(info, stops_info[m]) for m in g['members']):
                        continue
                    if not (GROUP_NEAR_SAME_NAME_GUARD and GROUP_SAME_NAME_SPLIT):
                        assigned = gid
                        break
                    # GROUP_NEAR_SAME_NAME_GUARD: if several groups qualify, join the nearest
                    #   (the first created could be a port group 642 m away, as at 西大分)
                    d_m = min(haversine(info['lat'], info['lon'], stops_info[m]['lat'], stops_info[m]['lon'])
                              for m in g['members'])
                    if best_d is None or d_m < best_d:
                        assigned, best_d = gid, d_m
            if assigned is None:
                next_id += 1
                assigned = f'G{next_id:05d}'
                groups[assigned] = {
                    'name': info['name'],
                    'lat': info['lat'],
                    'lon': info['lon'],
                    'members': [sid],
                }
                key_to_groups[key].append(assigned)
            else:
                groups[assigned]['members'].append(sid)
            group_of_stop[sid] = assigned
            # Index under each original spelling
            if assigned not in name_to_groups[info['name']]:
                name_to_groups[info['name']].append(assigned)

    return groups, group_of_stop, dict(name_to_groups)


def _walk_src_ok(info):
    """Whether the coordinate can be used for walking links: from the coordinate tables (coord_source = agent_known, release_proxy, wikidata)."""
    return info.get('src') == 'agent_known' or info.get('src') in PUBLIC_WALK_SRC


def build_walk_edges(groups, stops_info, trip_stops, max_m, speed):
    """Build walking links between groups (only with WALK_EDGES; call after proximity merging).

    Returns (walks, rows). walks = {group_id: [[other, minutes], ...]} (both directions).
    rows = record for the CSV. Same exclusions as proximity merging:
      (1) adjacent stops on the same line, (2) coordinates not from the coordinate tables
    Distance = shortest between stations of the two groups; minutes = distance / speed, rounded up (min 1).
    """
    adj = set()
    for st_list in trip_stops.values():
        ids = [r['stop_id'] for r in sorted(st_list, key=lambda x: int(x['stop_sequence']))]
        for a, b in zip(ids, ids[1:]):
            adj.add(frozenset((a, b)))
    cell = defaultdict(list)
    for gid in sorted(groups):
        for sid in groups[gid]['members']:
            info = stops_info[sid]
            if info['lat'] is None or info['lon'] is None:
                continue
            cell[(int(info['lat'] * 100), int(info['lon'] * 100))].append((sid, gid))
    best = {}     # (gidA, gidB) -> (distance m, representative station/line names)
    excluded = []
    seen = set()
    for key in sorted(cell):
        for sid, gid in cell[key]:
            a = stops_info[sid]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for sid2, gid2 in cell.get((key[0] + dx, key[1] + dy), []):
                        if gid2 <= gid or (gid, gid2, sid, sid2) in seen:
                            continue
                        b = stops_info[sid2]
                        d_m = haversine(a['lat'], a['lon'], b['lat'], b['lon']) * 1000
                        if d_m > max_m:
                            continue
                        seen.add((gid, gid2, sid, sid2))
                        if not (_walk_src_ok(a) and _walk_src_ok(b)):
                            excluded.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d_m),
                                             f'除外（座標が KB 由来でない: {a.get("src")}/{b.get("src")}）'))
                            continue
                        if (PUBLIC_PLACE_WALK_MAX_M > 0 and d_m > PUBLIC_PLACE_WALK_MAX_M
                                and 'release_proxy' in (a.get('src'), b.get('src'))):
                            excluded.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d_m),
                                             f'除外（代わりの点の驛で {PUBLIC_PLACE_WALK_MAX_M:.0f} m 超）'))
                            continue
                        if frozenset((sid, sid2)) in adj and a['line'] == b['line']:
                            excluded.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d_m),
                                             '除外（同じ線の隣の停留所）'))
                            continue
                        k = (gid, gid2)
                        if k not in best or d_m < best[k][0]:
                            best[k] = (d_m, a['name'], a['line'], b['name'], b['line'])
    # Same-name stations split by GROUP_SAME_NAME_SPLIT are joined by walking up to WALK_SAME_NAME_MAX_M
    #   even beyond max_m (within 5 km, the range that would otherwise be one group).
    long_keys = set()
    if GROUP_SAME_NAME_SPLIT and WALK_SAME_NAME_MAX_M > max_m:
        gid_of = {sid: gid for gid in sorted(groups) for sid in groups[gid]['members']}
        by_key = defaultdict(list)
        for sid in sorted(gid_of):
            if _coord_is_sure(stops_info[sid]):
                by_key[_group_key(stops_info[sid]['name'])].append(sid)
        lim = min(WALK_SAME_NAME_MAX_M, GROUP_DIST_KM * 1000)
        for key in sorted(by_key):
            sids = by_key[key]
            for i, s1 in enumerate(sids):
                for s2 in sids[i + 1:]:
                    g1, g2 = sorted((gid_of[s1], gid_of[s2]))
                    if g1 == g2:
                        continue
                    a, b = stops_info[s1], stops_info[s2]
                    d_m = haversine(a['lat'], a['lon'], b['lat'], b['lon']) * 1000
                    if d_m <= max_m or d_m > lim or (g1, g2) in best and (g1, g2) not in long_keys:
                        continue
                    if (g1, g2) not in best or d_m < best[(g1, g2)][0]:
                        if gid_of[s1] != g1:
                            a, b = b, a
                        best[(g1, g2)] = (d_m, a['name'], a['line'], b['name'], b['line'])
                        long_keys.add((g1, g2))
    walks = defaultdict(list)
    rows = []
    for (g1, g2), (d_m, n1, l1, n2, l2) in sorted(best.items()):
        mins = max(1, int(math.ceil(d_m / speed)))
        walks[g1].append([g2, mins])
        walks[g2].append([g1, mins])
        rows.append((g1, g2, n1, l1, n2, l2, round(d_m),
                     f'徒歩 {mins} 分' + ('（同じ名前・離れた驛）' if (g1, g2) in long_keys else '')))
    rows.extend(excluded)
    return {g: sorted(v) for g, v in walks.items()}, sorted(rows, key=lambda r: (r[7].startswith('除外'), r[6]))


def same_name_split_rows(groups, stops_info, walks):
    """Record of same-name station pairs (station x line) split by GROUP_SAME_NAME_SPLIT, and whether a walk joins them."""
    gid_of = {sid: gid for gid in sorted(groups) for sid in groups[gid]['members']}
    walk_min = {(g, h): m for g, lst in walks.items() for h, m in lst}
    by_key = defaultdict(list)
    for sid in sorted(gid_of):
        if _coord_is_sure(stops_info[sid]):
            by_key[_group_key(stops_info[sid]['name'])].append(sid)
    rows = []
    for key in sorted(by_key):
        sids = by_key[key]
        for i, s1 in enumerate(sids):
            for s2 in sids[i + 1:]:
                a, b = stops_info[s1], stops_info[s2]
                g1, g2 = gid_of[s1], gid_of[s2]
                d_m = haversine(a['lat'], a['lon'], b['lat'], b['lon']) * 1000
                if g1 == g2 or d_m > GROUP_DIST_KM * 1000 or not _same_name_apart(a, b):
                    continue
                m = walk_min.get((g1, g2))
                rows.append((a['name'], a['line'], g1, b['line'], g2, round(d_m),
                             f'徒歩 {m} 分' if m is not None else '乗り継げない'))
    return sorted(rows, key=lambda r: (-r[5], r[0], r[1], r[3]))


def merge_near_groups(groups, group_of_stop, name_to_groups, stops_info, trip_stops, near_km,
                      trip_guard=None):
    """Merge groups with different names whose closest stations are within near_km.
    Excluded: two stations that are adjacent stops on the same line (consecutive in stop_times, same line).
    trip_guard (GROUP_NEAR_TRIP_GUARD): refuse merges that would make one trip pass the same group twice,
    checked per current connected component (a per-pair check can be bypassed by chains).
    Merged into the smaller id (deterministic). Returns the list of merged pairs (record)."""
    # Default follows the module setting, so callers that omit the argument get the same groups
    #   as the journey planner.
    if trip_guard is None:
        trip_guard = GROUP_NEAR_TRIP_GUARD
    name_guard = GROUP_NEAR_SAME_NAME_GUARD and GROUP_SAME_NAME_SPLIT
    adj = set()
    stop_trips = defaultdict(set)
    for tid, st_list in trip_stops.items():
        ids = [r['stop_id'] for r in sorted(st_list, key=lambda x: int(x['stop_sequence']))]
        for a, b in zip(ids, ids[1:]):
            adj.add(frozenset((a, b)))
        for sid in ids:
            stop_trips[sid].add(tid)
    parent = {gid: gid for gid in groups}
    # Trips stopping in each connected component; combined on every merge (checked per component, not per pair)
    comp_trips = {gid: set().union(*(stop_trips[s] for s in groups[gid]['members'])) if groups[gid]['members']
                  else set() for gid in groups}
    comp_members = {gid: list(groups[gid]['members']) for gid in groups}   # for name_guard

    def _apart_across(r1, r2):
        for x in comp_members[r1]:
            kx = _group_key(stops_info[x]['name'])
            for y in comp_members[r2]:
                if _group_key(stops_info[y]['name']) == kx and _same_name_apart(stops_info[x], stops_info[y]):
                    return True
        return False

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    cell = defaultdict(list)
    for gid in sorted(groups):
        for sid in groups[gid]['members']:
            info = stops_info[sid]
            if info['lat'] is None or info['lon'] is None:
                continue
            cell[(int(info['lat'] * 100), int(info['lon'] * 100))].append((sid, gid))
    merged = []
    seen = set()
    for key in sorted(cell):
        for sid, gid in cell[key]:
            a = stops_info[sid]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for sid2, gid2 in cell.get((key[0] + dx, key[1] + dy), []):
                        if gid2 <= gid or (gid, gid2, sid, sid2) in seen:
                            continue
                        b = stops_info[sid2]
                        d = haversine(a['lat'], a['lon'], b['lat'], b['lon'])
                        if d * 1000 > near_km * 1000:
                            continue
                        seen.add((gid, gid2, sid, sid2))
                        # Do not merge stations whose coordinates are not from the coordinate tables (agent_known):
                        # interpolated values may sit on another station and create false transfers.
                        if a.get('src') != 'agent_known' or b.get('src') != 'agent_known':
                            merged.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d * 1000),
                                           f'除外（座標が KB 由来でない: {a.get("src")}/{b.get("src")}）'))
                            continue
                        if frozenset((sid, sid2)) in adj and a['line'] == b['line']:
                            merged.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d * 1000), '除外（同じ線の隣の停留所）'))
                            continue
                        r1, r2 = find(gid), find(gid2)
                        if trip_guard and r1 != r2 and (comp_trips[r1] & comp_trips[r2]):
                            merged.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d * 1000),
                                           '除外（束ねると 1 本の便が同じ点を 2 回通る）'))
                            continue
                        if name_guard and r1 != r2 and _apart_across(r1, r2):
                            merged.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d * 1000),
                                           '除外（束ねると同じ名前の別の場所の驛が 1 つになる）'))
                            continue
                        merged.append((gid, gid2, a['name'], a['line'], b['name'], b['line'], round(d * 1000), '併合' if r1 != r2 else '併合（既に同じ）'))
                        if r1 != r2:
                            lo, hi = min(r1, r2), max(r1, r2)
                            parent[hi] = lo
                            comp_trips[lo] |= comp_trips[hi]
                            comp_members[lo] += comp_members[hi]
    # Apply the merges
    for gid in sorted(groups):
        root = find(gid)
        if root != gid:
            groups[root]['members'] += groups[gid]['members']
            del groups[gid]
    for sid, gid in list(group_of_stop.items()):
        group_of_stop[sid] = find(gid)
    for name, gids in list(name_to_groups.items()):
        out = []
        for gid in gids:
            r = find(gid)
            if r not in out:
                out.append(r)
        name_to_groups[name] = out
    return merged


def _hhmm(t):
    """GTFS time (HH:MM:SS) -> HH:MM. None if empty."""
    if not t:
        return None
    parts = t.split(':')
    return f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else t


def _hms(t):
    a = t.split(':')
    return int(a[0]) * 60 + int(a[1])


def load_freq_labels(box_rows, sec_rows):
    """Build display names of estimated trips (e.g. "此間12分毎") from frequency boxes (frequency_box.csv)
    and frequency-only sections (frequency_sections.csv); template trips are identified by template_trip_id.
    Returns (template trip -> label, set of template trips for listed times (kind ③)).
    The published extras (template trip column named trip_id) give the same labels
    (scripts/release/build_release_router_data.py)."""
    freq_label = {}
    listed_tf = set()      # kind ③ template trips (one template per departure; trip_id goes in the key to avoid clashes)
    for r in box_rows or ():
        if not r.get('template_trip_id'):
            continue
        if str(r.get('kind', '')).startswith('③'):
            # Listed times, kind ③ (rows exist only with FREQ_BOX_LISTED=1 in build_frequency_box)
            freq_label[r['template_trip_id']] = f"{r.get('service_kind', '')} {(r.get('note') or '').split('＝')[0].replace('原本の列挙 ', '')}（此間ノモノアリ）"
            listed_tf.add(r['template_trip_id'])
            continue
        if r.get('minute_of_hour') not in ('', None):
            lab = f"毎時{int(r['minute_of_hour'])}分發"
        elif r.get('interval_min_lo') == r.get('interval_min_hi'):
            lab = f"此間{r['interval_min_lo']}分毎"
        else:
            lab = f"此間{r['interval_min_lo']}分乃至{r['interval_min_hi']}分毎"
        if r.get('service_kind'):
            lab = f"{r['service_kind']} {lab}"
        freq_label[r['template_trip_id']] = lab
    for r in sec_rows or ():
        if not r.get('template_trip_id'):
            continue
        lo, hi = r.get('interval_min_lo'), r.get('interval_min_hi')
        lab = f'{lo}分毎' if lo == hi else f'{lo}分乃至{hi}分毎'
        freq_label[r['template_trip_id']] = lab
    return freq_label, listed_tf


def build_trips(trip_stops, trip_info, routes, group_of_stop, groups, stops_info,
                freq_of, freq_label, listed_tf, phys):
    """Turn trips (trip_id -> stop_times rows) into trips over station groups (router_data trips).
    trip_info[trip_id] = {route_id, name, direction} (if 'key' is present it becomes the trip key k, else
    line__direction__number; if 't' is present it is copied as t = the published trip_id).
    routes = route_id -> line name. Template trips in frequencies.txt (freq_of) are expanded to estimated
    trips (est:1). phys = trip key -> through-train ID.
    Returns (trips, trips with a through-train ID, estimated trips, stops collapsed in template trips).
    The published GTFS (parent stations = station groups) is built the same way
    (scripts/release/build_release_router_data.py). If this changes, also update
    scripts/release/make_router_data.py (a standard-library-only copy)."""
    n_phys = 0
    n_est = 0
    n_collapsed = 0
    trips = []
    for trip_id, st_list in trip_stops.items():
        info = trip_info.get(trip_id)
        if not info:
            continue
        line_name = routes.get(info['route_id'], '')
        st_list.sort(key=lambda x: int(x['stop_sequence']))

        gids = []
        for r in st_list:
            sid = r['stop_id']
            gid = group_of_stop.get(sid)
            if gid is None:
                # not grouped (missing coordinates): skipped
                continue
            gids.append((gid, r))
        if not gids:
            continue
        if EST_SAME_GROUP_COLLAPSE and trip_id in freq_of:
            # Collapse consecutive same-group stops in template trips, keeping the stop with a time (EST_SAME_GROUP_COLLAPSE)
            kept = []
            for g, r in gids:
                has_t = bool(r.get('departure_time') or r.get('arrival_time'))
                if kept and kept[-1][0] == g:
                    prev_t = bool(kept[-1][1].get('departure_time') or kept[-1][1].get('arrival_time'))
                    if has_t and not prev_t:
                        kept[-1] = (g, r)
                        n_collapsed += 1
                        continue
                    if not has_t:
                        n_collapsed += 1
                        continue
                kept.append((g, r))
            gids = kept

        trip_key = info.get('key') or f"{line_name}__{info['direction']}__{info['name']}"
        # Names of the stops actually served (the group may be 「鹿兒島」 while the trip's stop is 「停車場前」).
        #   Only indices whose name differs from the group name ({index: name}); the page and
        #   scripts/route_planner_probe.js read them with stopName().
        sn = {str(i): stops_info[r['stop_id']]['name'] for i, (g, r) in enumerate(gids)
              if stops_info[r['stop_id']]['name'] != groups[g]['name']}
        if trip_id in freq_of:
            # Expand a template trip to estimated trips (every headway from start_time until before end_time)
            mins = [(_hms(r['departure_time']) if r.get('departure_time') else None,
                     _hms(r['arrival_time']) if r.get('arrival_time') else None) for _, r in gids]
            t0 = next(m for m in (d if d is not None else a for d, a in mins) if m is not None)
            for fr in freq_of[trip_id]:
                start, end, hw = _hms(fr['start_time']), _hms(fr['end_time']), int(fr['headway_secs']) // 60
                k = 0
                d = start
                while d < end and hw > 0:
                    shift = d - t0
                    k += 1
                    trips.append({
                        'k': (f'{trip_key}_{trip_id}_freq{k}' if trip_id in listed_tf else f'{trip_key}_freq{k}'),
                        'l': line_name, 'd': info['direction'],
                        'n': freq_label.get(trip_id, '此間○分毎'),
                        's': [g for g, _ in gids],
                        'dep': [f'{(m + shift) // 60:02d}:{(m + shift) % 60:02d}' if m is not None else None for m, _ in mins],
                        'arr': [f'{(m + shift) // 60:02d}:{(m + shift) % 60:02d}' if m is not None else None for _, m in mins],
                        'est': 1,
                        **({'sn': sn} if sn else {}),
                        **({'t': info['t']} if info.get('t') else {}),
                    })
                    n_est += 1
                    d += hw
            continue
        rec = {
            'k': trip_key,
            'l': line_name,
            'd': info['direction'],
            'n': info['name'],
            's': [g for g, _ in gids],
            'dep': [_hhmm(r.get('departure_time')) for _, r in gids],
            'arr': [_hhmm(r.get('arrival_time')) for _, r in gids],
        }
        if trip_key in phys:
            rec['p'] = phys[trip_key]
            n_phys += 1
        if sn:
            rec['sn'] = sn
        if info.get('t'):
            rec['t'] = info['t']
        trips.append(rec)
    return trips, n_phys, n_est, n_collapsed


def build_router_params():
    """Search-rule flags read by the search core embedded in demo/route_planner/index.html.
    Flags that are OFF are not written (if empty, router_params is not written)."""
    router_params = {}
    if EXACT_CANDIDATES:
        router_params['EXACT_CANDIDATES'] = True
    if PARETO_TRANSFERS:
        router_params['PARETO_TRANSFERS'] = True
    if PREV_DAY_BOARDING:
        # Always together (previous-day boarding alone lets an earlier label hide one that continues on the same train)
        router_params['PREV_DAY_BOARDING'] = True
        router_params['PARETO_CONTINUATION'] = True
    if TIE_FEWER_TRANSFERS:
        router_params['TIE_FEWER_TRANSFERS'] = True
    if WALK_LABELS_SEPARATE:
        router_params['WALK_LABELS_SEPARATE'] = True
    if NO_REVISIT:
        router_params['NO_REVISIT'] = True
    return router_params


def main():
    # 1. Read (stop_id, name, line, lat, lon) from stops_master.csv
    stops_info = {}
    with open(STOPS_MASTER, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            lat = float(r['stop_lat']) if r.get('stop_lat') else None
            lon = float(r['stop_lon']) if r.get('stop_lon') else None
            stops_info[r['stop_id']] = {
                'name': r['stop_name'],
                'line': r['line_name'],
                'lat': lat,
                'lon': lon,
                'src': r.get('coord_source', ''),
            }
    print(f'stops_info: {len(stops_info)}')

    # 2. Group close stops with the same name
    groups, group_of_stop, name_to_groups = build_groups(stops_info)
    print(f'groups: {len(groups)}')
    # Names with several groups (different stations with the same name)
    multi = {n: gs for n, gs in name_to_groups.items() if len(gs) > 1}
    print(f'  同名異駅 (>1 group): {len(multi)}')
    if multi:
        sample = list(multi.items())[:10]
        for n, gs in sample:
            # Stations without coordinates (coord_source=none in stops_master) may occur, so allow None
            coords_str = ', '.join(
                f'({groups[g]["lat"]:.2f}, {groups[g]["lon"]:.2f})'
                if groups[g]['lat'] is not None and groups[g]['lon'] is not None else '(座標なし)'
                for g in gs)
            print(f'    {n}: {len(gs)} groups  {coords_str}')

    # 3. route_id -> line_name from routes.txt
    routes = {}
    with open(os.path.join(GTFS_DIR, 'routes.txt'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            routes[r['route_id']] = r['route_short_name']

    # 4. trips.txt
    trip_info = {}
    with open(os.path.join(GTFS_DIR, 'trips.txt'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            trip_info[r['trip_id']] = {
                'route_id': r['route_id'],
                'name': r.get('trip_short_name', ''),
                'direction': 'outbound' if r.get('direction_id') == '0' else 'inbound',
            }

    # 5. Group stop_times.txt by trip
    trip_stops = defaultdict(list)
    with open(os.path.join(GTFS_DIR, 'stop_times.txt'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            trip_stops[r['trip_id']].append(r)

    # 5.5 Proximity merging (only with ROUTER_GROUP_NEAR=1; here because it uses stop_times adjacency)
    if GROUP_NEAR:
        merged = merge_near_groups(groups, group_of_stop, name_to_groups, stops_info, trip_stops,
                                   GROUP_NEAR_M / 1000.0, trip_guard=GROUP_NEAR_TRIP_GUARD)
        n_m = sum(1 for m in merged if m[7].startswith('併合'))
        n_x = sum(1 for m in merged if m[7].startswith('除外'))
        with open(os.path.join(GTFS_DIR, 'router_group_near.csv'), 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['group_a', 'group_b', 'stop_a', 'line_a', 'stop_b', 'line_b', 'dist_m', '結果'])
            w.writerows(merged)
        print(f'  近接グループの併合（{GROUP_NEAR_M:.0f}m）: 併合 {n_m}・除外（同じ線の隣） {n_x} → groups {len(groups)}')
    else:
        stale = os.path.join(GTFS_DIR, 'router_group_near.csv')
        if os.path.exists(stale):
            os.remove(stale)

    # 5.6 Walking links (only with ROUTER_WALK_EDGES=1; after merging, between the final groups)
    walks = None
    if WALK_EDGES:
        walks, wrows = build_walk_edges(groups, stops_info, trip_stops, WALK_MAX_M, WALK_SPEED_M_PER_MIN)
        with open(os.path.join(GTFS_DIR, 'router_walk_edges.csv'), 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['group_a', 'group_b', 'stop_a', 'line_a', 'stop_b', 'line_b', 'dist_m', '結果'])
            w.writerows(wrows)
        n_w = sum(1 for r in wrows if not r[7].startswith('除外'))
        print(f'  徒歩の辺（{WALK_MAX_M:.0f}m 以内・{WALK_SPEED_M_PER_MIN:.0f}m/分）: {n_w} 対'
              f'（除外 {len(wrows) - n_w}）→ router_walk_edges.csv')
    else:
        stale = os.path.join(GTFS_DIR, 'router_walk_edges.csv')
        if os.path.exists(stale):
            os.remove(stale)

    # 5.7 Record of split same-name stations (only with GROUP_SAME_NAME_SPLIT=1) and whether a walk joins them
    split_path = os.path.join(GTFS_DIR, 'router_same_name_split.csv')
    if GROUP_SAME_NAME_SPLIT:
        srows = same_name_split_rows(groups, stops_info, walks or {})
        with open(split_path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['stop_name', 'line_a', 'group_a', 'line_b', 'group_b', 'dist_m', '乗り継ぎ'])
            w.writerows(srows)
        n_cut = sum(1 for r in srows if r[6] == '乗り継げない')
        print(f'  同じ名前で分けた驛（両方の座標が確かで {GROUP_SAME_NAME_SPLIT_M:.0f}m 超）: {len(srows)} 組'
              f'（うち歩いてもつながらない {n_cut}）→ router_same_name_split.csv')
    elif os.path.exists(split_path):
        os.remove(split_path)

    # 4.5 frequencies.txt (exists only with GTFS_FREQUENCIES=1 in generate_gtfs).
    #   Its trips (template trips TF...) are not printed trips, so they are not written as is but
    #   expanded to estimated trips over the service window, marked est:1 (shown as 「（推定）」 "estimated").
    freq_of = defaultdict(list)
    freq_path = os.path.join(GTFS_DIR, 'frequencies.txt')
    if os.path.exists(freq_path):
        with open(freq_path, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                freq_of[r['trip_id']].append(r)
    box_rows = sec_rows = None
    box_path = os.path.join(GTFS_DIR, 'frequency_box.csv')
    if freq_of and os.path.exists(box_path):
        with open(box_path, encoding='utf-8-sig') as f:
            box_rows = list(csv.DictReader(f))
    sec_path = os.path.join(GTFS_DIR, 'frequency_sections.csv')
    if freq_of and os.path.exists(sec_path):
        with open(sec_path, encoding='utf-8-sig') as f:
            sec_rows = list(csv.DictReader(f))
    freq_label, listed_tf = load_freq_labels(box_rows, sec_rows)

    # 6. Build the trips array (s = group_id sequence)
    phys = load_physical_trains(PHYSICAL_TRAINS_CSV) if PHYSICAL_TRAINS else {}
    trips, n_phys, n_est, n_collapsed = build_trips(trip_stops, trip_info, routes, group_of_stop, groups, stops_info,
                                                    freq_of, freq_label, listed_tf, phys)

    # 7. Output data
    # Drop group members (not needed; smaller file)
    groups_out = {
        gid: {'name': g['name'], 'lat': g['lat'], 'lon': g['lon']}
        for gid, g in groups.items()
    }

    data = {
        'groups': groups_out,
        'name_to_groups': name_to_groups,
        'trips': trips,
    }
    if walks:
        data['walks'] = walks

    # Search-rule flags; OFF flags are not written (no router_params if all are OFF)
    router_params = build_router_params()
    if router_params:
        data['router_params'] = router_params
        print(f'  router_params（経路検索の決まり）: {router_params}')

    # Provenance of this data (when, from which GTFS); read by the page footer and checks.
    if DATA_META:
        import datetime as _dt
        st_path = os.path.join(GTFS_DIR, 'stop_times.txt')
        src_mtime = ''
        if os.path.exists(st_path):
            src_mtime = _dt.datetime.fromtimestamp(os.path.getmtime(st_path)).strftime('%Y-%m-%d %H:%M')
        data['meta'] = {
            'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'gtfs_dir': os.environ.get('GTFS_DIR', 'gtfs'),
            'integrated_dir': os.environ.get('INTEGRATED_DIR', '4_integrated'),
            'gtfs_stop_times_mtime': src_mtime,
            'groups': len(groups),
            'trips': len(trips),
        }
        print(f"  meta（データの素性）: {data['meta']}")

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    with open(OUT_JS, 'w', encoding='utf-8') as f:
        f.write('var ROUTER_DATA = ')
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')

    print(f'router_data.json 生成完了: {OUT_JSON}')
    print(f'router_data.js   生成完了: {OUT_JS}')
    print(f'  trips:  {len(trips)}')
    if freq_of:
        print(f'  推定便（frequencies.txt から展開・est:1）: {n_est}（雛形便 {len(freq_of)} 本）')
    if EST_SAME_GROUP_COLLAPSE:
        print(f'  推定便の雛形で同じグループが続く駅をまとめた（ROUTER_EST_SAME_GROUP_COLLAPSE=1）: {n_collapsed} 駅')
    if PHYSICAL_TRAINS:
        print(f'  physical_train_id を持つ trips: {n_phys}（対応表 {len(phys)} 鍵・{len(set(phys.values()))} 本）')
    print(f'  groups: {len(groups)}')
    print(f'  names:  {len(name_to_groups)}')


if __name__ == '__main__':
    main()
