#!/usr/bin/env python3
"""
Sort the results of compare_otp.py into "match / OTP later / OTP earlier" and label each mismatch with its cause.

    python3 tests/opentripplanner/classify.py <published dataset folder> <compare_otp.py output .jsonl> <config,config,...>

Standard output: counts per config. <jsonl>.csv: one row per query (arrival times and labels).
Labels are derived mechanically from the itineraries, using only the published GTFS (not OTP internals).
"""
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict

rel, path, configs = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
g = os.path.join(rel, 'gtfs')


def read(name):
    return list(csv.DictReader(open(os.path.join(g, name), encoding='utf-8-sig')))


stops = {r['stop_id']: r for r in read('stops.txt')}
trans = {(r['from_stop_id'], r['to_stop_id']) for r in read('transfers.txt')}
freq = read('frequencies.txt')
freq_all = {r['trip_id'] for r in freq}
freq_headway = {r['trip_id'] for r in freq if r['exact_times'] in ('0', '')}
trips = {r['trip_id']: r for r in read('trips.txt')}
st = defaultdict(list)
for r in read('stop_times.txt'):
    st[r['trip_id']].append(r)
patterns = defaultdict(list)          # same unit as OTP: (route, direction, stop sequence)
untimed = set()                       # stops with blank times (intermediate stations only)
for t, rs in st.items():
    rs.sort(key=lambda x: int(x['stop_sequence']))
    patterns[(trips[t]['route_id'], trips[t].get('direction_id', ''), tuple(x['stop_id'] for x in rs))].append(t)
    untimed |= {(t, x['stop_id']) for x in rs if not x['arrival_time'] and not x['departure_time']}
# Printed trips with the same stop sequence as a frequency template trip (OTP 2.10 searches that pattern as a
# frequency-based trip and does not use them)
hidden = {t for v in patterns.values() if any(x in freq_all for x in v) for t in v if t not in freq_all}
MAXJ = 96 * 60
EXAMPLE_DAYS = 5   # the example expands only --days (default 5) days of trips in compare_otp.py; journeys boarding on day 6 are not found
RADIUS_M = {'april_defaults': 30 * 60 * 1.35}   # defaults: 30 minutes of walking (1.35 m/s); others 45 minutes


def dist(a, b):
    a, b = stops[a], stops[b]
    la1, lo1, la2, lo2 = map(math.radians, [float(a['stop_lat']), float(a['stop_lon']),
                                            float(b['stop_lat']), float(b['stop_lon'])])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def sid(x):
    return x.split(':', 1)[1] if x and ':' in x else x


def other_station(a, b):
    return stops[a]['parent_station'] != stops[b]['parent_station']


def label(r, cfg):
    h, m = r['dep'].split(':')
    t0 = int(h) * 60 + int(m)
    ref, o = r['ref_arr'], r.get(cfg, {})
    if 'error' in o:
        return 'OTP の問い合わせが失敗'
    otp = o.get('arr')
    rs = r.get('ref_struct') or []
    if ref is not None and ref - t0 > MAXJ:
        return '一致（96 時間を超える旅）' if otp == ref else '見本の旅が 96 時間を超える（OTP の探索の上限の外）'
    if otp == ref:
        return '一致' if ref is not None else '両方とも経路なし'
    why = []
    if ref is not None and (otp is None or otp > ref):
        if any(l['kind'] == 'ride' and l['trip'] in hidden for l in rs):
            why.append('刷られた便を OTP が使わない（頻度の雛形便と停車の並びが同じ）')
        if any(l['kind'] == 'ride' and l['trip'] in freq_headway for l in rs):
            why.append('頻度の便（exact_times=0）を OTP は間隔ぶん待つとみなす')
        if rs and ((rs[0]['kind'] == 'walk' and other_station(rs[0]['from'], rs[0]['to']))
                   or (rs[-1]['kind'] == 'walk' and other_station(rs[-1]['from'], rs[-1]['to']))):
            why.append('別の駅へ歩いて始まる・終わる旅（OTP は最初と最後に歩けない）')
        if any(l['kind'] == 'walk' and dist(l['from'], l['to']) > RADIUS_M.get(cfg, 45 * 60 * 1.35) for l in rs):
            why.append('transfers.txt の組が OTP の歩く範囲の外')
        if cfg == 'april_defaults' and r.get('april_aligned', {}).get('arr') == ref:
            why.append('乗換の余裕・歩く範囲の既定（そろえた設定では一致）')
        # Walking the straight line between the published coordinates (OTP walk speed 1.33 m/s) takes longer than the
        #   example's transfer slack (previous arrival to next departure); OTP uses its own walk, not the transfers.txt time
        #   (e.g. 四日市→四日市市: same parent station, 0 minutes in transfers.txt, 667 m apart)
        for k, l in enumerate(rs):
            if l['kind'] != 'walk' or not l.get('from') or not l.get('to') or l['from'] == l['to']:
                continue
            prev = next((x for x in reversed(rs[:k]) if x['kind'] == 'ride'), None)
            nxt = next((x for x in rs[k + 1:] if x['kind'] == 'ride'), None)
            if prev and nxt and prev.get('arr') is not None and nxt.get('dep') is not None:
                if dist(l['from'], l['to']) / 1.33 / 60 > nxt['dep'] - prev['arr']:
                    why.append('乗換の歩き：公開版の座標の直線を歩くと見本の乗換の余裕より長い（OTP は transfers.txt の時間を使わない）')
                    break
        if o.get('arr_1m') is not None and o['arr_1m'] <= ref:
            why.append('OTP の探す幅しだい（幅を 1 分にして問い合わせ直すと見本と同じか早い）')
        return 'OTP が遅い・見つからない：' + ('＋'.join(why) if why else '原因不明')
    os_ = o.get('struct') or []
    if any(l['mode'] == 'WALK' and l['from'] and l['to'] and sid(l['from']) != sid(l['to'])
           and (sid(l['from']), sid(l['to'])) not in trans and other_station(sid(l['from']), sid(l['to']))
           for l in os_):
        why.append('OTP が transfers.txt に無い駅どうしを歩く（座標の直線距離で）')
    if any(l['mode'] != 'WALK' and l.get('trip') and ((sid(l['trip']), sid(l['from'])) in untimed
                                                      or (sid(l['trip']), sid(l['to'])) in untimed) for l in os_):
        why.append('OTP が時刻の空欄の途中駅で乗り降りする（前後から時刻を補う）')
    if ref is None and any(l['mode'] != 'WALK' and l.get('dep') is not None and l['dep'] >= EXAMPLE_DAYS * 1440 for l in os_):
        # e.g. 羅東→笹子 at 20:00 includes the 基隆→門司 ship (88 hours) and arrives on day 6; with 6 days the example gets the same arrival
        why.append(f'見本の検索の窓（{EXAMPLE_DAYS} 日）の外で乗る旅（見本の日数を増やすと同じ着）')
    return 'OTP が早い・OTP だけ見つかる：' + ('＋'.join(why) if why else '原因不明')


def hhmm(x):
    if x is None:
        return ''
    d, m = divmod(x, 1440)
    return f'{m // 60:02d}:{m % 60:02d}' + (f'(+{d})' if d else '')


recs = [json.loads(l) for l in open(path, encoding='utf-8')]
counts = {c: Counter() for c in configs}
idx = defaultdict(list)
rows = []
for r in recs:
    row = {'i': r['i'], '出発駅': r['from_name'], '到着駅': r['to_name'], '出発時刻': r['dep'],
           '見本の到着': hhmm(r['ref_arr'])}
    for c in configs:
        lab = label(r, c)
        counts[c][lab] += 1
        idx[f'{c}|{lab}'].append(r['i'])
        row[f'{c}_到着'] = hhmm(r.get(c, {}).get('arr'))
        row[f'{c}_札'] = lab
    rows.append(row)
for c in configs:
    n = sum(counts[c].values())
    same = sum(v for k, v in counts[c].items() if k.startswith(('一致', '両方とも')))
    print(f'== {c}（{n} 検索・一致 {same}＝{100 * same / n:.1f}%）')
    for k, v in counts[c].most_common():
        print(f'  {v:4d}  {k}')
json.dump(idx, open(path + '.classes.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
with open(path.rsplit('.', 1)[0] + '.csv', 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator='\r\n')
    w.writeheader()
    w.writerows(rows)
