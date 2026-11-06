#!/usr/bin/env python3
"""
Compare the earliest arrival of the same queries between the published example examples/route_1925.py
and OpenTripPlanner (OTP).

    python3 tests/opentripplanner/compare_otp.py --release <published dataset folder> \
        --ports april_defaults=18082,april_aligned=18084 [--n 300] [--seed 20260927] --out results.jsonl

  - Queries: 10 fixed pairs x 2 departure times, plus 300 random pairs.
    Origin and destination are parent stations of the published dataset (PS...); both planners get the same one
    (when several stations share a name, the one with more trips).
  - Date 1925-04-05. OTP reads a copy that runs every day of April, so trips that left the day before are running
    too (the same assumption as the example).
  - The example searches up to 5 days ahead; OTP uses the settings from make_otp_inputs.py (journeys up to 96 hours).
  - One JSON line per query, with the example's itinerary (ref_struct) and OTP's earliest-arrival itinerary
    (<name>.struct). Classify the results with classify.py.
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otp_tools as ot  # noqa: E402

JST = timezone(timedelta(hours=9))
DAY0 = datetime(1925, 4, 5, tzinfo=JST)
FIXED = [('東京', '下關'), ('上野', '青森'), ('東京', '京城〈朝鮮〉'), ('東京', '札幌'), ('大阪', '長崎'),
         ('上野', '新潟'), ('東京', '奈良'), ('大阪', '高松棧橋'), ('東京', '稚內'), ('東京', '大泊〈樺太〉')]


def minutes(iso):
    """Minutes since 1925-04-05 0:00 (Japan time)."""
    return int((datetime.fromisoformat(iso) - DAY0).total_seconds() // 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--release', required=True)
    ap.add_argument('--ports', required=True, help='名前=ポート,名前=ポート')
    ap.add_argument('--n', type=int, default=300)
    ap.add_argument('--seed', type=int, default=20260927)
    ap.add_argument('--days', type=int, default=5)
    ap.add_argument('--window', default='PT6H')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    ports = [(kv.split('=')[0], int(kv.split('=')[1])) for kv in a.ports.split(',')]

    sys.dont_write_bytecode = True     # do not create __pycache__ in the dataset's examples/
    sys.path.insert(0, os.path.join(a.release, 'examples'))
    import route_1925 as r
    tt = r.Timetable(os.path.join(a.release, 'gtfs'), os.path.join(a.release, 'extras'))
    served = {s for (_, timed, _) in tt.patterns for (s, *_rest) in timed}
    stations = sorted(g for g in tt.stations if any(c in served for c in tt.children[g]))
    by_name = {}
    for g in stations:
        by_name.setdefault(tt.stations[g], []).append(g)

    def pick(name):
        gs = by_name.get(name) or []
        return max(gs, key=lambda g: sum(1 for (_, timed, _) in tt.patterns for (s, *_x) in timed
                                         if s in tt.children[g]), default=None)

    rnd = random.Random(a.seed)
    q = []
    for o, d in FIXED:
        go, gd = pick(o), pick(d)
        if go and gd:
            for t in ('08:00', '20:00'):
                q.append((go, gd, t))
    while len(q) < a.n + 20:
        go, gd = rnd.sample(stations, 2)
        q.append((go, gd, rnd.choice(['06:00', '08:00', '12:00', '20:00'])))

    out = open(a.out, 'w', encoding='utf-8')
    t_ref, t_otp = 0.0, Counter()
    for i, (go, gd, t) in enumerate(q):
        h, m = t.split(':')
        t0 = int(h) * 60 + int(m)
        s = time.time()
        res = tt.search([go], [gd], t0, a.days)
        t_ref += time.time() - s
        rec = {'i': i, 'from': go, 'to': gd, 'from_name': tt.stations[go], 'to_name': tt.stations[gd], 'dep': t,
               'ref_arr': None, 'ref_transfers': None, 'ref_legs': None}
        if res:
            legs, arr = res
            lines, ntr = tt.show(legs)
            rec.update(ref_arr=arr, ref_transfers=ntr, ref_legs=lines,
                       ref_struct=[{'kind': 'walk', 'from': l[1], 'to': l[2], 'min': l[4]} if l[0] == 'walk' else
                                   {'kind': 'ride', 'trip': l[1][5], 'from': l[1][2], 'to': l[2][3],
                                    'dep': l[1][0], 'arr': l[2][1], 'est': bool(l[1][6] or l[2][6])}
                                   for l in legs])
        for label, port in ports:
            s = time.time()
            try:
                pc = ot.plan(port, go, gd, f'1925-04-05T{t}+09:00', window=a.window, n=100)
            except Exception as e:  # noqa: BLE001
                rec[label] = {'error': str(e)[:300]}
                continue
            t_otp[label] += time.time() - s
            its = [e['node'] for e in pc['edges']]
            best = min(its, key=lambda it: it['end']) if its else None
            info = {'n': len(its), 'errors': [x['code'] for x in pc['routingErrors']],
                    'window_used': pc['pageInfo']['searchWindowUsed']}
            if best:
                info['struct'] = [{'mode': l['mode'], 'trip': (l.get('trip') or {}).get('gtfsId'),
                                   'from': (l['from'].get('stop') or {}).get('gtfsId'),
                                   'to': (l['to'].get('stop') or {}).get('gtfsId'),
                                   'dep': minutes(l['start']['scheduledTime']),
                                   'arr': minutes(l['end']['scheduledTime'])}
                                  for l in best['legs']]
                info.update(arr=minutes(best['end']), start=minutes(best['start']),
                            transfers=best['numberOfTransfers'], walk_s=best['walkTime'],
                            notices=[n['tag'] for n in best['systemNotices']],
                            legs=[f"{(l['route'] or {}).get('shortName') or l['mode']}"
                                  f"{' ' + l['trip']['tripShortName'] if l.get('trip') and l['trip'].get('tripShortName') else ''} "
                                  f"{l['from']['name']} {l['start']['scheduledTime'][5:16]} -> "
                                  f"{l['to']['name']} {l['end']['scheduledTime'][5:16]}"
                                  for l in best['legs']])
            # When OTP arrives later than the example or finds nothing, query again with a 1-minute search window
            #   (兩國橋→市ケ谷 at 20:00: a 6-hour window returns only next-morning itineraries, a 1-minute window
            #   returns the 22:30 arrival; this is how OTP searches)
            if rec['ref_arr'] is not None and (info.get('arr') is None or info['arr'] > rec['ref_arr']):
                try:
                    pc1 = ot.plan(port, go, gd, f'1925-04-05T{t}+09:00', window='PT1M', n=100)
                    its1 = [e['node'] for e in pc1['edges']]
                    if its1:
                        info['arr_1m'] = minutes(min(its1, key=lambda it: it['end'])['end'])
                except Exception:  # noqa: BLE001
                    pass
            rec[label] = info
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.flush()
        if (i + 1) % 50 == 0:
            print(f'{i + 1}/{len(q)} 見本 {t_ref:.0f}s ' + ' '.join(f'{k} {v:.0f}s' for k, v in t_otp.items()),
                  flush=True)
    out.close()


if __name__ == '__main__':
    main()
