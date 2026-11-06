"""
Move the template trips of frequencies.txt (estimated trips) to their own route IDs in the published dataset
(called from step 16 of scripts/build_release_gtfs.py).

OpenTripPlanner 2.10 treats a whole stop pattern of a route as frequency-based if even one frequencies.txt trip uses it,
and then ignores the printed trips with the same pattern. For routes that have both printed and estimated trips,
the estimated trips move to a separate route whose long name adds "頻度の推定便" (estimated frequency trips)
to the line and section name. Trip, stop and time values are unchanged.
"""
from collections import defaultdict

SUFFIX = '頻度の推定便'


def plan(routes, trips, freq_trip_ids):
    """Return (rows to add to routes.txt, {template trip_id: new route_id}).
    The new route_id is the old one plus "T" (the published ID comes from the ID registry, keyed with the section name)."""
    count = defaultdict(lambda: [0, 0])          # route_id -> [estimated trips, printed trips]
    for t in trips:
        count[t['route_id']][0 if t['trip_id'] in freq_trip_ids else 1] += 1
    need = sorted(rid for rid, (n_tpl, n_printed) in count.items() if n_tpl and n_printed)
    by_id = {r['route_id']: r for r in routes}
    new_rows = []
    for rid in need:
        nid = rid + 'T'
        if nid in by_id:
            raise SystemExit(f'推定便の路線: route_id {nid} が既にある')
        row = dict(by_id[rid], route_id=nid)
        long = by_id[rid].get('route_long_name') or ''
        row['route_long_name'] = f'{long}・{SUFFIX}' if long else SUFFIX
        new_rows.append(row)
    move = {t['trip_id']: t['route_id'] + 'T' for t in trips
            if t['trip_id'] in freq_trip_ids and t['route_id'] in set(need)}
    return new_rows, move
