#!/usr/bin/env python3
"""Band orientation check: does a band's station order disagree with the line's own up/down direction?

## What it finds

Row 6 `direction` of a connecting band (another line's trips printed for reference) is often
taken from the heading of the table that carries it (下リ列車 / 上リ列車 / 靑森行 ...). The band
shows trips of a different line, so the direction can be the reverse of that line's own
direction (direction must follow the line, not the table heading).

Duplicate checks of the form "the shorter trip's (station, time) pairs are all contained in the
longer trip" stay silent for bands where

  * the band has the 著 (arrival) at the junction and the detail table has the 發 (departure)
    (a few minutes apart), or
  * the partner trip is not in the corpus.

This check ignores times and looks only at station order.

## Method

1. From `integrated_stop_times.csv`, collect trips with non-combined line names per line, turn
   them to the outbound order by `direction`, and take the longest station sequence as the
   line's reference.
2. For trips from a single source sheet (i.e. the band itself), count whether the station
   order follows or reverses the reference; report it if it disagrees with the sheet's `direction`.

## False positive types

| Type | Example | How to tell |
|---|---|---|
| Thin reference (the line is only on those 2 sheets, so the reference is the band itself) | 滿洲線 (n=3), 作備線 (n=2), 滿鐵咸鏡線北部 (n=4), 東京灣汽船會社定期航路 (n=5) | Small `参照n` (reference length). Both mirror sheets flagged is the signature |
| Branching line (the reference cannot be one straight sequence) | 東北本線 上野-田端-池袋-赤羽 (electric) | The band's stations are on the branch |
| The original uses two conventions | 中央本線: p69 has 飯田町→鹽尻 as 下リ (down); p67 has 名古屋→鹽尻 as 下リ | Shown as `mixed` for the same line |
| Combined line name whose parts cannot share one direction | p47 tb001-7, p48 tb001-2, p80 tb001-1-1, p134 tb002-7 | Per-part verdicts split (`★成分どうしが逆`, parts disagree) |

Cases with `参照n` >= 15 whose mirror partner has the correct direction are likely true positives.

## Usage

    python3 scripts/detectors/detect_band_orientation.py                       # default: data/4_integrated_v1
    python3 scripts/detectors/detect_band_orientation.py --integrated <dir>    # another directory
    python3 scripts/detectors/detect_band_orientation.py --min-ref 15          # drop thin references
    python3 scripts/detectors/detect_band_orientation.py --out <path.csv>

Standalone check. Exit code 1 if there is at least one candidate.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))

from known_kanji_variants import normalize as normalize_kanji_variants  # noqa: E402

FIELDS = ["page", "sheet", "line_name", "行6", "判定", "種類", "成分", "参照n", "便数", "始駅", "終駅"]


def canon(name):
    return normalize_kanji_variants(name or '', prefer_new=True)


def is_composite(line_name):
    return '及' in line_name or '、' in line_name


def resolve(integrated_dir):
    """Accept an absolute path, a repository-relative path (data/4_integrated_v1) or a bare name (4_integrated_v1)."""
    for cand in (integrated_dir,
                 os.path.join(BASE_DIR, integrated_dir),
                 os.path.join(BASE_DIR, 'data', integrated_dir)):
        path = os.path.join(cand, 'integrated_stop_times.csv')
        if os.path.exists(path):
            return path
    raise SystemExit('integrated_stop_times.csv が見つかりません: %s' % integrated_dir)


def load(integrated_dir):
    path = resolve(integrated_dir)
    with open(path, encoding='utf-8-sig') as f:
        return path, list(csv.DictReader(f))


def build(rows):
    """Build trips (station sequences) and a reference station sequence per line (outbound order)."""
    trips = defaultdict(list)
    gk_sheets = defaultdict(set)
    for r in rows:
        key = (r['line_name'], r['direction'], r['trip_num'], r['gtfs_trip_key'])
        trips[key].append((int(r['stop_sequence']), canon(r['stop_name'])))
        gk_sheets[r['gtfs_trip_key']].add(r['source_sheet'])

    ref = defaultdict(list)
    for (line, direction, _num, _gk), stops in trips.items():
        if is_composite(line):
            continue
        seq = [s for _, s in sorted(stops)]
        if direction == 'inbound':
            seq = seq[::-1]
        ref[line].append((len(seq), seq))
    for line in ref:
        ref[line].sort(key=lambda x: -x[0])
    return trips, gk_sheets, ref


def orient(ref, line, stops):
    """Return 'outbound' if stops follow the line's outbound order, 'inbound' if reversed."""
    for n, seq in ref.get(line, []):
        index = {s: i for i, s in enumerate(seq)}
        pos = [index[s] for s in stops if s in index]
        if len(set(pos)) < 2:
            continue
        forward = sum(1 for a, b in zip(pos, pos[1:]) if b > a)
        backward = sum(1 for a, b in zip(pos, pos[1:]) if b < a)
        if forward == backward:
            continue
        return ('outbound' if forward > backward else 'inbound'), n
    return None, 0


def scan(rows, min_ref=0):
    trips, gk_sheets, ref = build(rows)
    # group bands (trips from a single source sheet) by sheet x component line
    per_band = defaultdict(lambda: defaultdict(list))
    for (line, direction, num, gk), stops in trips.items():
        sheets = gk_sheets[gk]
        if len(sheets) != 1:
            continue
        sheet = next(iter(sheets))
        if '/' in sheet:
            continue
        seq = [s for _, s in sorted(stops)]
        verdict, n = orient(ref, line, seq)
        per_band[(sheet, direction)][line].append((verdict, n, num, seq[0], seq[-1]))

    out = []
    for (sheet, direction), comps in sorted(per_band.items()):
        decided = {}
        for line, items in comps.items():
            vs = {v for v, _n, _num, _a, _b in items if v}
            if not vs:
                continue
            best = max((n for _v, n, _num, _a, _b in items), default=0)
            if best < min_ref:
                continue
            decided[line] = (list(vs)[0] if len(vs) == 1 else 'mixed', best, items)
        if not decided:
            continue
        values = {v for v, _n, _items in decided.values()}
        if len(values) == 1 and next(iter(values)) == direction:
            continue                      # all components agree with the sheet direction = OK
        kind = '★成分どうしが逆' if len(values) > 1 else '行6 が逆'
        for line, (v, n, items) in sorted(decided.items()):
            out.append({
                "page": sheet[:5], "sheet": sheet, "line_name": line, "行6": direction,
                "判定": v, "種類": kind, "成分": ('合成' if is_composite(line) else '単一'),
                "参照n": n, "便数": len(items), "始駅": items[0][3], "終駅": items[0][4],
            })
    return out


def main():
    ap = argparse.ArgumentParser(description="帯の駅の並びと線自身の上下の食い違い")
    ap.add_argument("--integrated", default="4_integrated_v1")
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-ref", type=int, default=0, metavar="N",
                    help="基準の駅列がこの長さ未満の線は出さない（薄い基準の偽陽性よけ。推奨 15）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    path, rows = load(args.integrated)
    found = scan(rows, min_ref=args.min_ref)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(found)

    if not args.quiet:
        print("%s: 行 %d" % (path, len(rows)))
        sheets = sorted({r["sheet"] for r in found})
        n_conf = len({r["sheet"] for r in found if r["種類"].startswith("★")})
        print("帯の向きの食い違い: %d 行 / %d シート（うち成分どうしが逆＝%d シート）"
              % (len(found), len(sheets), n_conf))
        for r in found:
            print("  %-20s %-9s %-16s(%s) 判定=%-9s 参照n=%-3d 便%-3d %s → %s  %s"
                  % (r["sheet"], r["行6"], r["line_name"], r["成分"], r["判定"],
                     r["参照n"], r["便数"], r["始駅"], r["終駅"], r["種類"]))
        if args.out:
            print("  → %s" % os.path.relpath(args.out, BASE_DIR))
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
