#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Copy the coordinates in stops_master.csv into gtfs/stops.txt.

run_pipeline.sh runs generate_gtfs (step 4) before the coordinate steps
(apply_agent_knowledge, infer_coords, ...), so stations that first get coordinates
in step 5 would stay empty in stops.txt. Run this at the end of step 5.

Environment variables are the same as generate_gtfs.py (INTEGRATED_DIR / GTFS_DIR;
absolute paths allowed).
"""
import csv
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INT_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'))
GTFS_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs'))


def main():
    master_path = os.path.join(INT_DIR, 'stops_master.csv')
    stops_path = os.path.join(GTFS_DIR, 'stops.txt')
    coords = {}
    with open(master_path, encoding='utf-8-sig') as fp:
        for row in csv.DictReader(fp):
            lat = (row.get('stop_lat') or '').strip()
            lon = (row.get('stop_lon') or '').strip()
            if lat and lon:
                coords[row['stop_id']] = (lat, lon)

    with open(stops_path, encoding='utf-8-sig') as fp:
        rows = list(csv.reader(fp))
    header, body = rows[0], rows[1:]
    i_id = header.index('stop_id')
    i_lat = header.index('stop_lat')
    i_lon = header.index('stop_lon')

    filled = updated = 0
    for row in body:
        got = coords.get(row[i_id])
        if not got:
            continue
        was_empty = not row[i_lat].strip() or not row[i_lon].strip()
        if (row[i_lat], row[i_lon]) != got:
            row[i_lat], row[i_lon] = got
            if was_empty:
                filled += 1
            else:
                updated += 1

    with open(stops_path, 'w', encoding='utf-8', newline='') as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(body)

    remain = sum(1 for r in body if not r[i_lat].strip())
    print(f"sync_gtfs_stop_coords: 空→充填 {filled} / 値更新 {updated} / なお空 {remain} / 全 {len(body)} 駅")


if __name__ == '__main__':
    main()
