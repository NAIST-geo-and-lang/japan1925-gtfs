#!/usr/bin/env python3
"""check_route_expectations.py — check the journey planner against the expectations table (check RQ9)

Why: looking only at counts and diffs after a rebuild, an answer that used to be right can change silently
even when the counts are as predicted.

What: run each row (one query) of the expectations table (`tests/route_search/expectations.csv`) with the
page's own implementation and check that the arrival time is as expected.

- Searches go through `tests/pyraptor/route_planner_batch.js`, which runs the search functions embedded in the HTML
  via `buildEnv` of `route_planner_probe.js`, so the check follows any change to the implementation
  (the logic is not reimplemented).
- FAIL when |actual arrival - expected arrival| > tol_min.
  WARN when the number of transfers differs from `expect_transfers` (the choice of route may vary by implementation).
  No route found, or a route found where none is expected, is also FAIL.

Usage:
    python3 tests/route_search/check_route_expectations.py                 # default: data/gtfs_v1_release_router/router_data.js
    python3 tests/route_search/check_route_expectations.py --data <router_data.js>
    python3 tests/route_search/check_route_expectations.py --csv <expectations.csv>
    python3 tests/route_search/check_route_expectations.py --update --why "reason"   # update expectations to current values

`--update` changes values, so `--why` is required (expectations are never rewritten silently).
  Answers changing after a data fix is normal; then update with a reason.

Exit code: 1 if there is a FAIL (for use in rebuild checks and CI)
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CSV = os.path.join(BASE, 'tests', 'route_search', 'expectations.csv')
DEFAULT_DATA = os.path.join(BASE, 'data', 'gtfs_v1_release_router', 'router_data.js')
HTML = os.path.join(BASE, 'demo', 'route_planner', 'index.html')
BATCH = os.path.join(BASE, 'tests', 'pyraptor', 'route_planner_batch.js')

FIELDS = ['id', 'from', 'to', 'dep', 'expect_arr_min', 'tol_min', 'expect_transfers',
          '根拠', '由来', '更新日', '更新の理由']


def load_table(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if list(r.keys())[:len(FIELDS)] != FIELDS:
            raise SystemExit(f'{path}: 列が違う（期待＝{FIELDS}）')
    return rows


def run_batch(rows, data):
    """Run all queries with the page's own implementation. Returns (from, to, dep) -> result."""
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'res.json')
        payload = {'html': HTML, 'data': data, 'out': out, 'variants': False,
                   'queries': [{'from': r['from'], 'to': r['to'], 'dep': r['dep']} for r in rows]}
        subprocess.run(['node', BATCH], input=json.dumps(payload), text=True, check=True)
        with open(out, encoding='utf-8') as f:
            res = json.load(f)
    return {(r['from'], r['to'], r['dep']): r for r in res}


def fmt(v):
    """Minutes -> readable time (+N日 for later days)."""
    if v is None:
        return '経路なし'
    d, m = divmod(int(v), 1440)
    return f'{m // 60:02d}:{m % 60:02d}' + (f'（+{d}日）' if d else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default=DEFAULT_CSV)
    ap.add_argument('--data', default=DEFAULT_DATA)
    ap.add_argument('--update', action='store_true', help='期待値を今の値へ更新する（--why が要る）')
    ap.add_argument('--why', default='', help='--update の理由（表に残る）')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    if a.update and not a.why:
        raise SystemExit('--update には --why「なぜ期待値を動かすか」が要る（黙って書き換えない）')

    rows = load_table(a.csv)
    got = run_batch(rows, a.data)
    print(f'期待値表 {len(rows)} 行／データ {os.path.relpath(a.data, BASE)}')

    fails, warns, updated = [], [], 0
    for r in rows:
        g = got.get((r['from'], r['to'], r['dep']))
        actual = None
        if g and g.get('found'):
            actual = g['arr_min']
        exp = r['expect_arr_min'].strip()
        tol = int(r['tol_min'] or 0)
        label = f"{r['id']} {r['from']}→{r['to']} {r['dep']}發"

        if a.update:
            # change only rows whose values change, writing the update date and reason (other rows keep their reasons)
            new_arr = '' if actual is None else str(actual)
            new_tr = '' if not g or not g.get('found') else str(g['transfers'])
            if (r['expect_arr_min'].strip(), r['expect_transfers'].strip()) != (new_arr, new_tr):
                r['expect_arr_min'], r['expect_transfers'] = new_arr, new_tr
                r['更新日'] = datetime.date.today().isoformat()
                r['更新の理由'] = a.why
                updated += 1
            continue

        if exp == '':                      # expected: no route
            if actual is not None:
                fails.append(f'  FAIL {label}: 経路が無いはずが {fmt(actual)} で見つかった')
            continue
        if actual is None:
            fails.append(f'  FAIL {label}: 経路が見つからない（期待 {fmt(int(exp))}）')
            continue
        diff = actual - int(exp)
        if abs(diff) > tol:
            fails.append(f'  FAIL {label}: {fmt(actual)}（期待 {fmt(int(exp))}・差 {diff:+d} 分・許容 ±{tol}）')
            continue
        et = r['expect_transfers'].strip()
        if et and g['transfers'] != int(et):
            warns.append(f"  WARN {label}: 乗換 {g['transfers']} 回（期待 {et} 回・到着は一致）")
        elif not a.quiet:
            print(f'  ok   {label}: {fmt(actual)}')

    if a.update:
        if not updated:
            print('期待値は今の値と同じ＝書かない')
            return 0
        with open(a.csv, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\r\n')
            w.writeheader()
            w.writerows(rows)
        print(f'★期待値を更新した: {updated} 行（理由＝{a.why}）→ {a.csv}')
        return 0

    for x in warns:
        print(x)
    for x in fails:
        print(x)
    print(f'\nFAIL {len(fails)} / WARN {len(warns)} / 検査 {len(rows)}')
    if fails:
        print('★期待値と違う。データを直した結果なら --update --why「理由」で期待値を動かす。'
              'そうでなければ退行なので直す。')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
