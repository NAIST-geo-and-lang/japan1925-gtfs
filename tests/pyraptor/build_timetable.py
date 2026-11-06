"""Build the pyraptor timetable (pyraptor_out/timetable.pcl) from gtfs_for_pyraptor/.

Calls the same code as pyraptor's own `python -m pyraptor.gtfs.timetable` (pyraptor.gtfs.timetable.main),
with one difference: transfers between platforms of the same station take 0 minutes instead of pyraptor's
default 2 minutes (TRANSFER_COST), because the journey planner of demo/route_planner (the search core embedded in
demo/route_planner/index.html) treats transfers within a station group as 0 minutes.
The date and agency names are read from gtfs_for_pyraptor/_meta.json (written by make_pyraptor_gtfs.py).

Usage (in tests/pyraptor):
  venv/bin/python build_timetable.py
  venv/bin/python build_timetable.py --transfer-sec 120     # pyraptor's default (2 minutes)
"""
import argparse
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description='gtfs_for_pyraptor → pyraptor_out/timetable.pcl')
    ap.add_argument('--in', dest='inp', default=os.path.join(HERE, 'gtfs_for_pyraptor'))
    ap.add_argument('--out', default=os.path.join(HERE, 'pyraptor_out'))
    ap.add_argument('--transfer-sec', type=int, default=0, help='同じ駅の中の乗り換え時間（秒・既定 0）')
    a = ap.parse_args()
    with open(os.path.join(a.inp, '_meta.json'), encoding='utf-8') as f:
        meta = json.load(f)

    import pyraptor.gtfs.timetable as ptt
    from pyraptor.model.structures import Trip
    ptt.TRANSFER_COST = a.transfer_sec   # gtfs_to_pyraptor_timetable() looks up this name
    # Speed fix (search results are unchanged): before trips get an ID (Trip.id), pyraptor stores stop times in the
    #   TripStopTimes dict keyed by (trip, stop index). Trips without an ID all hash to hash(None), so keys collide and
    #   the build becomes quadratic in the number of trips (about 66,000 trips for 3 days, tens of minutes).
    #   Until IDs are assigned, use a distinct hash per trip (afterwards the original hash(id)).
    #   The dict is only used to print counts; the search (pyraptor/model/raptor.py) does not read it.
    Trip.__hash__ = lambda self: hash(self.id) if self.id is not None else object.__hash__(self)
    t0 = time.time()
    ptt.main(a.inp, a.out, meta['date'], meta['agency_names'])
    info = {
        'built': time.strftime('%Y-%m-%d %H:%M:%S'),
        'seconds': round(time.time() - t0),
        'transfer_sec': a.transfer_sec,
        'gtfs_for_pyraptor_created': meta['created'],
        'days': meta['days'],
        'inputs': meta['inputs'],
    }
    with open(os.path.join(a.out, 'build_info.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    print(f'完了: {a.out}（{info["seconds"]} 秒・乗り換え {a.transfer_sec} 秒・{meta["days"]} 日ぶん）')


if __name__ == '__main__':
    main()
