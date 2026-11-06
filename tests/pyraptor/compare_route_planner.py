"""Run pyraptor (an existing library) and the journey planner of demo/route_planner on the same queries and compare.

Requires make_pyraptor_gtfs.py and build_timetable.py to have been run on the same GTFS as the journey planner data.
First checks that both really come from the same GTFS (station groups and all stations and times of day-1 trips);
stops if they differ (continue with --allow-data-mismatch).

Compares the earliest arrival time. Both searches minimize it, so correct implementations agree.
Travel time and number of transfers are not compared (for the same arrival, the first trip may differ by implementation).

Mismatches are diagnosed as to which side missed the itinerary (CSV column diagnosis; the text before "（" is the kind):
  - pyraptor earlier / only pyraptor found a route
      1) Rerun modified versions of the journey planner (the search core embedded in the HTML, changed in memory;
         the HTML is not modified). Arrives at the same time or earlier without candidate pruning (at each station,
         only the earliest trip per line, direction and terminus) -> the journey planner missed it; arrives with the
         transfer limit raised from 10 to 20 -> outside the journey planner's limits; arrives when also boarding today's
         run of trips that left the previous day (PREV_DAY_BOARDING) -> missed a previous-day trip.
      2) Otherwise replay pyraptor's itinerary on the journey planner data and rules and report the reason.
  - journey planner earlier / only the journey planner found a route -> replay its itinerary on pyraptor's data.
      Outside the days (make_pyraptor_gtfs.py --days, --days-before) or rounds (--rounds) -> outside pyraptor's range;
      replayable but not found -> to investigate, missed by pyraptor.

Usage (in tests/pyraptor):
  venv/bin/python compare_route_planner.py                              # fixed queries (CASES in query_pyraptor.py)
  venv/bin/python compare_route_planner.py 大阪 京城〈朝鮮〉 09:00      # one query
  venv/bin/python compare_route_planner.py --sample 300 --seed 1        # 300 random stations and departure times
  venv/bin/python compare_route_planner.py --sweep 青森 東京 --step 60  # one pair, every 60 minutes from 0:00
  venv/bin/python compare_route_planner.py --cases compare_out/compare_<datetime>.csv --only-mismatch   # rerun previous mismatches
Main options:
  --html / --router-data   journey planner HTML and data (default demo/route_planner/index.html and
                           data/gtfs_v1_release_router/router_data.js)
  --rounds N               maximum pyraptor rounds (about the number of boarded trips; default 10, the same as the
                           journey planner's transfer limit MAX_TRANSFERS)
  --no-router-variants     do not rerun mismatches with modified versions of the journey planner
  --allow-data-mismatch    compare even if the data check fails
Output: compare_out/compare_<datetime>.csv (one row per query) and a summary on screen (mismatches show both
itineraries and the diagnosis).
"""
import argparse
import collections
import csv
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tests', 'route_search'))
import query_pyraptor as qp  # noqa: E402
# Reachability used to classify "no route on both sides" is taken as is from check_route_data_quality.py (RQ8)
import check_route_data_quality as rqdq  # noqa: E402

OUT_DIR = os.environ.get('PYRAPTOR_COMPARE_OUT') or os.path.join(HERE, 'compare_out')   # override with PYRAPTOR_COMPARE_OUT
VERDICTS = ['一致', 'pyraptorが早い', '経路検索が早い', '経路検索だけ見つかった', 'pyraptorだけ見つかった',
            '両方とも経路なし', '駅名なし']
# Journey planner limits used in the diagnosis (same values as PARAMS of the search core embedded in
# demo/route_planner/index.html; keep them in sync)
ROUTER_WAIT_MAX_MIN = 2880
ROUTER_MAX_TRANSFERS = 10
# Walking links. Both sides have them, so replays check them too (set in main())
_ROUTER_WALKS = {}   # journey planner walks (group -> [[other group, minutes], ...])
_PY_WALKS = {}       # walks passed to pyraptor (built by the same function, so they should match)


def parse_args():
    ap = argparse.ArgumentParser(description='pyraptor と demo/route_planner の経路検索を比べる')
    ap.add_argument('od', nargs='*', help='出発駅 到着駅 [HH:MM]')
    ap.add_argument('--html', default=os.path.join(REPO, 'demo', 'route_planner', 'index.html'))
    ap.add_argument('--router-data', default=os.path.join(REPO, 'data', 'gtfs_v1_release_router', 'router_data.js'))
    ap.add_argument('--gtfs-dir', default=qp.GTFS_DIR, help='make_pyraptor_gtfs.py の出力')
    ap.add_argument('--pyraptor-out', default=qp.OUT_DIR, help='build_timetable.py の出力')
    ap.add_argument('--sample', type=int, default=0, help='駅と出発時刻を無作為に選んで N 通り')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--sample-min-trips', type=int, default=10,
                    help='無作為に選ぶ駅を、便がこの本数以上止まる駅に限る（既定 10）')
    ap.add_argument('--sweep', nargs=2, metavar=('FROM', 'TO'), help='1 区間を出発時刻を変えて回す')
    ap.add_argument('--step', type=int, default=60, help='--sweep の刻み（分）')
    ap.add_argument('--cases', help='区間の一覧の CSV（列 from・to・dep。前回の compare_*.csv をそのまま渡せる）')
    ap.add_argument('--only-mismatch', action='store_true',
                    help='--cases のうち、判定が「一致」「両方とも経路なし」以外の行だけを回す')
    ap.add_argument('--rounds', type=int, default=10)
    ap.add_argument('--no-router-variants', action='store_true')
    ap.add_argument('--allow-data-mismatch', action='store_true')
    return ap.parse_args()


def load_router_data(path):
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    return json.loads(raw[raw.index('{'):raw.rindex('}') + 1])


def rmin(t):
    if not t:
        return None
    h, m = t.split(':')[:2]
    return int(h) * 60 + int(m)


def load_pyraptor_gtfs(gtfs_dir):
    """Read the output of make_pyraptor_gtfs.py (for the data check and diagnosis). Times in minutes."""
    gid_of = {}
    with open(os.path.join(gtfs_dir, 'stops.txt'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            gid_of[r['stop_id']] = r['stop_name']
    trips = {}
    with open(os.path.join(gtfs_dir, 'trips.txt'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            trips[r['trip_id']] = r
    seq = collections.defaultdict(list)   # trip_id -> [(stop_sequence, station group, arrival, departure)]
    with open(os.path.join(gtfs_dir, 'stop_times.txt'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            seq[r['trip_id']].append((int(r['stop_sequence']), gid_of[r['stop_id']],
                                      rmin(r['arrival_time']), rmin(r['departure_time'])))
    for v in seq.values():
        v.sort()
    clamped = {}
    with open(os.path.join(gtfs_dir, '_clamped.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            clamped[(r['trip_id'], int(r['stop_sequence']))] = (r['arrival_before'], r['departure_before'])
    base_ids = collections.defaultdict(list)   # journey planner key k -> IDs of day-1 trips
    for tid, r in trips.items():
        if r['day'] == '1':
            base_ids[r['router_key']].append(tid)
    clamped_keys = {trips[tid]['router_key'] for tid, _ in clamped}
    return {'trips': trips, 'seq': seq, 'clamped': clamped, 'base_ids': base_ids, 'clamped_keys': clamped_keys}


def data_check(meta, router, pg):
    """Check all station groups and day-1 trips (stations, departures, arrivals) against the journey planner data."""
    msgs, ok = [], True
    mg, rg = meta['groups'], router['groups']
    only_m, only_r = set(mg) - set(rg), set(rg) - set(mg)
    bad = [g for g in sorted(set(mg) & set(rg))
           if [mg[g][0], mg[g][1], mg[g][2]] != [rg[g]['name'], rg[g]['lat'], rg[g]['lon']]]
    if only_m or only_r or bad:
        ok = False
        msgs.append(f'❌ 駅グループが違う（pyraptor 側だけ {len(only_m)}・経路検索側だけ {len(only_r)}・'
                    f'名前か座標が違う {len(bad)}）')
    else:
        msgs.append(f'✅ 駅グループ {len(mg)} 個が一致（番号・名前・座標）')

    ours, n_est = collections.Counter(), 0
    for tid, row in pg['trips'].items():
        if row['day'] != '1':
            continue
        n_est += row['est'] == '1'
        items = []
        for n, g, a, d in pg['seq'][tid]:
            before = pg['clamped'].get((tid, n))
            if before:
                a, d = rmin(before[0]), rmin(before[1])
            items.append((g, d, a))
        ours[(row['router_key'], tuple(items))] += 1
    theirs, short = collections.Counter(), 0
    for t in router['trips']:
        items = []
        for g, d, a in zip(t['s'], t['dep'], t['arr']):
            dm, am = rmin(d), rmin(a)
            if dm is None and am is None:
                continue
            items.append((g, dm if dm is not None else am, am if am is not None else dm))
        if len(items) < 2:
            short += 1
            continue
        theirs[(t['k'], tuple(items))] += 1
    only_ours, only_theirs = ours - theirs, theirs - ours
    n_est_r = sum(1 for t in router['trips'] if t.get('est'))
    if only_ours or only_theirs:
        ok = False
        msgs.append(f'❌ 1 日目の便が違う（pyraptor 側だけ {sum(only_ours.values())} 本・'
                    f'経路検索側だけ {sum(only_theirs.values())} 本）')
        for (k, _), _n in list(only_ours.items())[:5]:
            msgs.append(f'     pyraptor 側だけ: {k}')
        for (k, _), _n in list(only_theirs.items())[:5]:
            msgs.append(f'     経路検索側だけ: {k}')
    else:
        msgs.append(f'✅ 1 日目の便 {sum(ours.values())} 本の駅と時刻が全部一致'
                    f'（うち推定便 {n_est} 本・経路検索のデータの推定便 {n_est_r} 本）')
    if short:
        msgs.append(f'ℹ️ 時刻のある駅が 1 つだけの便 {short} 本は pyraptor に入れていない（乗り降りに使えないので結果は変わらない）')
    msgs.append(f'ℹ️ 時刻が前へ戻るので繰り上げた行 {len(pg["clamped"])}（pyraptor 側だけ・_clamped.csv）')
    return ok, msgs


def run_router(html, data, queries, variants=False):
    os.makedirs(OUT_DIR, exist_ok=True)
    # Use a new file name per run (so two concurrent runs do not mix results); removed after reading.
    res_path = os.path.join(OUT_DIR, f'_route_planner_result_{os.getpid()}_{int(variants)}.json')
    payload = {'html': os.path.abspath(html), 'data': os.path.abspath(data), 'queries': queries,
               'out': res_path, 'variants': variants}
    p = subprocess.run(['node', os.path.join(HERE, 'route_planner_batch.js')],
                       input=json.dumps(payload, ensure_ascii=False), text=True, encoding='utf-8',
                       capture_output=True)
    if p.returncode != 0:
        raise SystemExit('demo/route_planner の検索が失敗しました:\n' + p.stderr[-3000:])
    with open(res_path, encoding='utf-8') as f:
        res = json.load(f)
    os.remove(res_path)
    return res


def sample_queries(router, n, seed, min_trips):
    served = collections.Counter(g for t in router['trips'] for g in set(t['s']))
    names = sorted(nm for nm, gids in router['name_to_groups'].items()
                   if sum(served[g] for g in gids) >= min_trips)
    rnd = random.Random(seed)
    out = []
    while len(out) < n:
        a, b = rnd.choice(names), rnd.choice(names)
        if set(router['name_to_groups'][a]) & set(router['name_to_groups'][b]):
            continue
        m = rnd.randrange(4 * 60, 23 * 60, 5)
        out.append({'from': a, 'to': b, 'dep': f'{m // 60:02d}:{m % 60:02d}'})
    return out


def judge(rp, py):
    if rp.get('error'):
        return '駅名なし', None
    rf, pf = bool(rp.get('found')), py['found']
    if rf and pf:
        diff = py['arr_min'] - rp['arr_min']
        return ('一致' if diff == 0 else ('pyraptorが早い' if diff < 0 else '経路検索が早い')), diff
    if rf:
        return '経路検索だけ見つかった', None
    if pf:
        return 'pyraptorだけ見つかった', None
    return '両方とも経路なし', None


# Do not let "no route on both sides" pass unexamined (if both fail for the same reason, the comparison shows no mismatch).
#   Three classes, decided from the data alone without either search.
NO_ROUTE_A = '(a) 端点に乗り降りできる駅が無い'
NO_ROUTE_B = '(b) 線路がつながっていない'
NO_ROUTE_C = '(c) 上限の外★'


def no_route_reason(reach, rp):
    """Reason why neither side found a route. reach = (set of groups where one can board or alight, find, mainland root).
    Class (c) suggests a real bug (the route is lost to the transfer limit, the wait limit or pruning)."""
    U, find, _main = reach
    fg = [g for g in (rp.get('from_gids') or []) if g in U]
    tg = [g for g in (rp.get('to_gids') or []) if g in U]
    if not fg or not tg:
        return NO_ROUTE_A
    roots = {find(g) for g in fg}
    if not any(find(g) in roots for g in tg):
        return NO_ROUTE_B
    return NO_ROUTE_C


def replay_on_router(legs, dep_min, router_by_key, prev_day=False):
    """Replay pyraptor's itinerary on the journey planner data and rules (boarding rules, wait and transfer limits of
    the embedded search core). prev_day is True when the journey planner data has the PREV_DAY_BOARDING flag
    (today's run of trips that left the previous day can be boarded).
    Returns None if replayable, else (kind, reason); kind is 'limit' (outside limits) or 'missing' (trip or time absent)."""
    if not legs:
        return 'missing', '行程が空'
    cur, transfers, prev, prev_walk = dep_min, 0, None, False
    for n, l in enumerate(legs, 1):
        if l.get('walk'):   # walking leg: check the same link exists in the journey planner walks, advance by the walk (not a transfer)
            if prev_walk:
                # The journey planner forbids chained walks (`cur.walked` in the embedded search core, to keep the search small).
                #   pyraptor relaxes footpaths from every marked stop each round, so walk-walk itineraries can appear.
                return 'limit', (f'{n} 本目も徒歩（{l["from"]}→{l["to"]}）＝'
                                 '経路検索は歩きの連鎖を禁じている（demo/route_planner/index.html の cur.walked）')
            edge = next((m for g, m in (_ROUTER_WALKS.get(l['from_gid']) or []) if g == l['to_gid']), None)
            if edge is None:
                return 'missing', f'{n} 本目の徒歩（{l["from"]}→{l["to"]}）が経路検索の walks に無い'
            if edge != l['walk_min']:
                return 'missing', f'{n} 本目の徒歩の分数が違う（pyraptor {l["walk_min"]} 分・経路検索 {edge} 分）'
            cur, prev, prev_walk = l['arr_min'], None, True
            continue
        prev_walk = False
        hit = None
        for t in router_by_key.get(l['key'], []):
            s = t['s']
            for i in range(len(s) - 1):
                if s[i] != l['from_gid']:
                    continue
                bd = rmin(t['dep'][i]) if t['dep'][i] else rmin(t['arr'][i])
                if bd is None:
                    continue
                ed = bd
                while ed < cur:
                    ed += 1440
                if prev_day:
                    while ed - 1440 >= cur:
                        ed -= 1440
                if ed != l['dep_min']:
                    continue
                for j in range(i + 1, len(s)):
                    if s[j] != l['to_gid']:
                        continue
                    am = rmin(t['arr'][j]) if t['arr'][j] else rmin(t['dep'][j])
                    if am is None:
                        continue
                    at = am + (ed - bd)
                    while at < ed:
                        at += 1440
                    if at == l['arr_min']:
                        hit = (ed, t)
                        break
                if hit is not None:
                    break
            if hit is not None:
                break
        if hit is None:
            return 'missing', f'{n} 本目（{l["label"]}・{l["from"]}→{l["to"]}）が経路検索のデータでたどれない'
        ed, t = hit
        # Same counting as the embedded search core: cannot board once transfers reach the limit; continuing on the same through train (same p) is not counted
        if transfers >= ROUTER_MAX_TRANSFERS:
            return 'limit', (f'pyraptor の行程は {n} 本目に乗る時点で乗換 {transfers} 回＝経路検索の上限 {ROUTER_MAX_TRANSFERS} 回'
                             f'（乗車 {len(legs)} 本の行程）')
        if ed - cur > ROUTER_WAIT_MAX_MIN:
            return 'limit', f'pyraptor の行程は {n} 本目の前の待ちが {ed - cur} 分＝経路検索の上限 {ROUTER_WAIT_MAX_MIN} 分を超える'
        continuation = prev is not None and prev is not t and prev.get('p') and prev.get('p') == t.get('p')
        transfers += 0 if continuation else 1
        prev, cur = t, l['arr_min']
    return None


def replay_on_pyraptor(legs, pg, days, rounds, days_before=0):
    """Replay the journey planner's itinerary on pyraptor's data (day copy = day_shift; negative = previous-day copy).
    Returns None if replayable, else (kind, reason); kind is 'range' (outside days or rounds), 'clamped'
    (a raised row) or 'missing'."""
    for n, l in enumerate(legs, 1):
        # Walking leg: the same links were passed to pyraptor. A missing link is outside the conversion's range,
        #   not a pyraptor miss, so say so instead of "to investigate".
        if l.get('walk'):
            edge = next((m for g, m in (_PY_WALKS.get(l['from_gid']) or []) if g == l['to_gid']), None)
            if edge is None:
                return 'range', (f'{n} 本目が徒歩（{l["from"]}→{l["to"]}）で、pyraptor 用のデータにその辺が無い'
                                 '（make_pyraptor_gtfs.py を作り直す）')
            continue
        ds = l['day_shift']
        if ds >= days:
            return 'range', f'{n} 本目が {ds + 1} 日目の便＝pyraptor は {days} 日ぶん（make_pyraptor_gtfs.py --days を増やす）'
        if ds < -days_before:
            return 'range', (f'{n} 本目が {-ds} 日前に出た便＝pyraptor の前の日の写しは {days_before} 日ぶん'
                             f'（make_pyraptor_gtfs.py --days-before を増やす）')
        suffix = '' if ds == 0 else (f'_d{ds + 1}' if ds > 0 else f'_dm{-ds}')
        found = False
        for base in pg['base_ids'].get(l['key'], []):
            st = pg['seq'].get(base + suffix, [])
            for i, (_, g, _a, d) in enumerate(st):
                if g == l['from_gid'] and d == l['dep_min'] and any(
                        g2 == l['to_gid'] and a2 == l['arr_min'] for _, g2, a2, _d in st[i + 1:]):
                    found = True
                    break
            if found:
                break
        if not found:
            if l['key'] in pg['clamped_keys']:
                return 'clamped', f'{n} 本目（{l["line"]} {l["num"]}）は時刻を繰り上げた便'
            return 'missing', f'{n} 本目（{l["line"]} {l["num"]}・{l["from"]}→{l["to"]}）が pyraptor のデータでたどれない'
    if len(legs) > rounds:
        return 'range', f'乗車 {len(legs)} 本＝pyraptor の探索の回数 --rounds {rounds} を超える（--rounds を増やす）'
    return None


def diagnose(v, q, rp, py, router_by_key, pg, days, rounds, var, prev_day=False, days_before=0):
    """Diagnose a mismatch. The text before the first "（" is the kind (used in the summary counts).
    var = arrivals of the modified journey planner versions (None if not run)."""
    if v in ('pyraptorが早い', 'pyraptorだけ見つかった'):
        tried = bool(var) and 'error' not in var
        if tried:
            pa = py['arr_min']

            def reaches(k):
                return var.get(k) is not None and var[k] <= pa
            if reaches('noprune'):
                return '経路検索の取りこぼし（候補の絞り込みを外した経路検索は、同じか早い時刻に着く）'
            if reaches('tr20'):
                return '経路検索の上限の外（乗換の上限を 10 回から 20 回にした経路検索は、同じか早い時刻に着く）'
            if reaches('both'):
                return '経路検索の取りこぼしと上限の外（絞り込みを外し、乗換の上限も 20 回にすると着く）'
            if not prev_day and reaches('prevday'):
                return '経路検索の取りこぼし・前の日の便（前の日に出た便の今日の分にも乗る経路検索は、同じか早い時刻に着く）'
        r = replay_on_router(py['legs'], qp.to_min(q['dep']), router_by_key, prev_day)
        if r is None:
            if tried:
                return '要調査・経路検索の取りこぼし（手直し版でも着かないが、pyraptor の行程は経路検索のデータと決まりでたどれる）'
            return '経路検索の取りこぼし（pyraptor の行程は、経路検索のデータと決まりでもそのままたどれる）'
        kind, why = r
        if kind == 'limit':
            return f'経路検索の上限の外（{why}）'
        return f'要調査（pyraptor の行程を経路検索のデータでたどれない: {why}）'
    if v in ('経路検索が早い', '経路検索だけ見つかった'):
        r = replay_on_pyraptor(rp['legs'], pg, days, rounds, days_before)
        if r is None:
            return '要調査・pyraptor の取りこぼし（経路検索の行程は、pyraptor のデータでもそのままたどれる）'
        kind, why = r
        if kind == 'range':
            return f'pyraptor の範囲外（{why}）'
        if kind == 'clamped':
            return f'データの扱いの違い（{why}）'
        return f'要調査（経路検索の行程を pyraptor のデータでたどれない: {why}）'
    return ''


def legs_lines(legs, router_side):
    out = []
    for l in legs:
        if router_side:
            name = f"{l['line']} {l['num'] or '(番号なし)'}" + ('（推定）' if l['est'] else '')
        else:
            name = l['label']
        out.append(f"{name}: {l['from']} {qp.fmt_min(l['dep_min'])} → {l['to']} {qp.fmt_min(l['arr_min'])}")
    return out


def read_cases(path, only_mismatch):
    with open(path, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if only_mismatch:
        rows = [r for r in rows if r.get('verdict') not in ('一致', '両方とも経路なし')]
    return [{'from': r['from'], 'to': r['to'], 'dep': r['dep']} for r in rows]


def main():
    a = parse_args()
    t_all = time.time()
    with open(os.path.join(a.gtfs_dir, '_meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    router = load_router_data(a.router_data)
    pg = load_pyraptor_gtfs(a.gtfs_dir)
    global _ROUTER_WALKS, _PY_WALKS
    _ROUTER_WALKS = router.get('walks') or {}
    _PY_WALKS = meta.get('walks') or {}
    router_params = router.get('router_params') or {}
    prev_day = bool(router_params.get('PREV_DAY_BOARDING'))
    days_before = int(meta.get('days_before', 0))

    print('== 1. データの突き合わせ（pyraptor 用の GTFS と、経路検索のデータ）')
    print(f'  pyraptor 用: {a.gtfs_dir}（{meta["created"]} に変換・{meta["days"]} 日ぶん＋前の日 {days_before} 日・'
          f'元＝{meta["inputs"]["gtfs"]}）')
    print(f'  経路検索　 : {os.path.abspath(a.router_data)}（router_params＝{router_params or "なし"}）')
    ok, msgs = data_check(meta, router, pg)
    for m in msgs:
        print('  ' + m)
    info_path = os.path.join(a.pyraptor_out, 'build_info.json')
    if not os.path.exists(info_path):
        ok = False
        print(f'  ❌ {info_path} がありません（build_timetable.py を先に回す）')
    else:
        with open(info_path, encoding='utf-8') as f:
            info = json.load(f)
        if info.get('gtfs_for_pyraptor_created') != meta['created']:
            ok = False
            print(f'  ❌ pyraptor_out は {info.get("gtfs_for_pyraptor_created")} の変換から作ったもので、'
                  f'今の gtfs_for_pyraptor（{meta["created"]}）と違う（build_timetable.py をやり直す）')
        else:
            print(f'  ✅ pyraptor_out は今の gtfs_for_pyraptor から作ったもの（{info["built"]}・'
                  f'同じ駅の中の乗り換え {info["transfer_sec"]} 秒）')
    if not ok and not a.allow_data_mismatch:
        print('\n→ データがそろっていないので比べません。同じ回の GTFS から作り直すか、--allow-data-mismatch を付けてください。')
        return 1

    if a.cases:
        queries = read_cases(a.cases, a.only_mismatch)
    elif a.sweep:
        queries = [{'from': a.sweep[0], 'to': a.sweep[1], 'dep': f'{m // 60:02d}:{m % 60:02d}'}
                   for m in range(0, 1440, a.step)]
    elif a.od:
        if len(a.od) < 2:
            raise SystemExit('出発駅と到着駅を渡してください（例: 大阪 京城〈朝鮮〉 09:00）')
        queries = [{'from': a.od[0], 'to': a.od[1], 'dep': a.od[2] if len(a.od) > 2 else '08:00'}]
    elif a.sample:
        queries = sample_queries(router, a.sample, a.seed, a.sample_min_trips)
    else:
        queries = [{'from': f, 'to': t, 'dep': d} for f, t, d in qp.CASES]
    if not queries:
        print('\n回す区間がありません。')
        return 0

    print(f'\n== 2. demo/route_planner の経路検索（{len(queries)} 件）')
    t0 = time.time()
    rp_all = run_router(a.html, a.router_data, queries)
    print(f'  {time.time() - t0:.0f} 秒')

    print(f'\n== 3. pyraptor（{len(queries)} 件）')
    t0 = time.time()
    tt = qp.read_timetable(a.pyraptor_out)
    trips_day1 = {tid: r for tid, r in pg['trips'].items() if r['day'] == '1'}
    router_by_key = collections.defaultdict(list)
    for t in router['trips']:
        router_by_key[t['k']].append(t)
    print(f'  タイムテーブルの読み込み {time.time() - t0:.0f} 秒')
    results = []
    for i, (q, rp) in enumerate(zip(queries, rp_all), 1):
        t1 = time.time()
        if rp.get('error'):
            py = {'found': False, 'arr_min': None, 'round': None, 'legs': [], 'valid': None, 'note': ''}
        else:
            py = qp.search(tt, meta, trips_day1, rp['from_gids'], rp['to_gids'], qp.to_min(q['dep']), a.rounds)
        sec = time.time() - t1
        v, diff = judge(rp, py)
        print(f'  [{i}/{len(queries)}] {q["from"]} → {q["to"]} {q["dep"]} 発: {v}'
              + (f'（差 {diff} 分）' if diff else '') + f'  {sec:.1f} 秒')
        results.append((q, rp, py, v, diff, sec))

    reach = rqdq.usable_and_components(router)   # reachability for classifying "no route on both sides" (timed stops plus walking links)
    reasons = {k: (no_route_reason(reach, rp) if v == '両方とも経路なし' else '')
               for k, (q, rp, py, v, diff, sec) in enumerate(results)}
    variants = {}
    # Also rerun class (c) (no route on both sides although the data connects them) with the modified versions
    #   to see whether the transfer limit or candidate pruning loses it
    need = [k for k, r in enumerate(results)
            if r[3] in ('pyraptorが早い', 'pyraptorだけ見つかった') or reasons[k] == NO_ROUTE_C]
    if need and not a.no_router_variants:
        print(f'\n== 3b. 経路検索の手直し版で回し直す（診断用・{len(need)} 件）')
        t0 = time.time()
        for k, r in zip(need, run_router(a.html, a.router_data, [results[k][0] for k in need], variants=True)):
            variants[k] = r.get('variants')
        print(f'  {time.time() - t0:.0f} 秒')

    rows, detail = [], []
    counts, diag_counts, none_counts = collections.Counter(), collections.Counter(), collections.Counter()
    for k, (q, rp, py, v, diff, sec) in enumerate(results):
        var = variants.get(k)
        diag = diagnose(v, q, rp, py, router_by_key, pg, meta['days'], a.rounds, var, prev_day, days_before)
        notes = []
        rp_legs, py_legs = rp.get('legs') or [], py['legs']
        if {l['key'] for l in rp_legs + py_legs} & pg['clamped_keys']:
            notes.append('時刻を繰り上げた便を使う（_clamped.csv）')
        if py['found'] and py['valid'] is False:
            notes.append('pyraptor の行程のたどり直しが不完全（到着時刻は有効）')
        if py['note']:
            notes.append(py['note'])
        if rp.get('error'):
            notes.append(rp['error'])
        if var and 'error' in var:
            notes.append('手直し版を作れない: ' + var['error'])
        note = '／'.join(notes)
        counts[v] += 1
        reason = reasons[k]
        if reason:
            none_counts[reason] += 1
        vv = var if var and 'error' not in var else {}
        if reason == NO_ROUTE_C:
            # Narrow down class (c): which limit loses it, according to the modified versions
            if vv.get('tr20') is not None or vv.get('both') is not None:
                diag = '経路検索の上限の外（乗換の上限を 10 回から 20 回にすると着く）'
            elif vv.get('noprune') is not None:
                diag = '経路検索の取りこぼし（候補の絞り込みを外すと着く）'
            elif vv:
                diag = '要調査（上限を緩めても見つからない＝データの上ではつながっているのに経路が無い）'
        if diag:
            diag_counts[diag.split('（')[0]] += 1
        rows.append({
            'from': q['from'], 'to': q['to'], 'dep': q['dep'], 'verdict': v,
            'diff_min': '' if diff is None else diff, 'diagnosis': diag,
            'no_route_reason': reason, 'note': note,
            'route_planner_arr': qp.fmt_min(rp.get('arr_min')) if rp.get('found') else '',
            'pyraptor_arr': qp.fmt_min(py['arr_min']) if py['found'] else '',
            'route_planner_arr_min': rp.get('arr_min', ''), 'pyraptor_arr_min': py['arr_min'] if py['found'] else '',
            'router_noprune_arr_min': vv.get('noprune', ''), 'router_tr20_arr_min': vv.get('tr20', ''),
            'router_both_arr_min': vv.get('both', ''), 'router_prevday_arr_min': vv.get('prevday', ''),
            'route_planner_legs': ' ／ '.join(legs_lines(rp_legs, True)),
            'pyraptor_legs': ' ／ '.join(legs_lines(py_legs, False)),
            'route_planner_transfers': rp.get('transfers', ''), 'pyraptor_round': py['round'] or '',
            'route_planner_est_legs': sum(1 for l in rp_legs if l['est']),
            'pyraptor_est_legs': sum(1 for l in py_legs if l['est']),
            'pyraptor_sec': round(sec, 1), 'route_planner_ms': rp.get('ms', ''),
        })
        if v not in ('一致', '両方とも経路なし') or reason == NO_ROUTE_C:
            detail.append((q, v + (('　' + reason) if reason else ''), diff, diag, note, rp, py, vv))

    print('\n== 4. まとめ')
    for v in VERDICTS:
        if counts[v]:
            print(f'  {v}: {counts[v]}')
    if none_counts:
        # Classes of "no route on both sides"; any case of (c) suggests a real bug
        print('  （両方とも経路なしの仕分け）')
        for r in (NO_ROUTE_A, NO_ROUTE_B, NO_ROUTE_C):
            if none_counts[r]:
                print(f'    {r}: {none_counts[r]}')
        if none_counts[NO_ROUTE_C]:
            print(f'    ★{NO_ROUTE_C} が {none_counts[NO_ROUTE_C]} 件＝'
                  '乗換の上限・待ちの上限・枝刈りで消えている疑い。下の行程を見て切り分ける')
    if diag_counts:
        print('  （食い違いの診断）')
        for d, n in diag_counts.most_common():
            print(f'    {d}: {n}')
    for q, v, diff, diag, note, rp, py, vv in detail:
        print(f'\n  ● {q["from"]} → {q["to"]} {q["dep"]} 発: {v}' + (f'（差 {diff} 分）' if diff else ''))
        if diag:
            print(f'    診断: {diag}')
        if note:
            print(f'    ※{note}')
        if rp.get('found'):
            print(f'    経路検索: 到着 {qp.fmt_min(rp["arr_min"])}（乗換 {rp["transfers"]} 回）')
            for line in legs_lines(rp['legs'], True):
                print('      ' + line)
        else:
            print('    経路検索: ' + ('経路なし' if not rp.get('error') else rp['error']))
        if vv:
            print('    経路検索の手直し版: ' + '／'.join(
                f'{label} {qp.fmt_min(vv[k]) if vv.get(k) is not None else "経路なし"}'
                for k, label in (('noprune', '絞り込みなし'), ('tr20', '乗換 20 回'), ('both', '両方'),
                                 ('prevday', '前の日の便にも乗る'))))
        if py['found']:
            print(f'    pyraptor: 到着 {qp.fmt_min(py["arr_min"])}（乗車 {len(py["legs"])} 本）')
            for line in legs_lines(py['legs'], False):
                print('      ' + line)
        else:
            print('    pyraptor: 経路なし' + (f'（{py["note"]}）' if py['note'] else ''))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv = os.path.join(OUT_DIR, f'compare_{time.strftime("%Y%m%d_%H%M%S")}.csv')
    with open(out_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f'\n結果: {out_csv}（全体 {time.time() - t_all:.0f} 秒）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
