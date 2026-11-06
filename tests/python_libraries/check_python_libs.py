#!/usr/bin/env python3
"""
Check that the published GTFS can be read by the Python GTFS libraries gtfs-kit and partridge.

    <Python with gtfs_kit and partridge> tests/python_libraries/check_python_libs.py <published dataset folder>

  - gtfs-kit: reads all files, prints statistics for 1925-04-01 and runs assess_quality (a basic quality check).
    Also counts trips with implausible speeds caused by measuring trip distance along the full shape
    (stop_times has no shape_dist_traveled and shapes has one shape per route, so short trips get the whole route length).
  - partridge: loads the feed for the busiest service date.
"""
import math
import os
import sys
import tempfile
import warnings
import zipfile

warnings.simplefilter('ignore')
import gtfs_kit as gk  # noqa: E402
import partridge as ptg  # noqa: E402

rel = sys.argv[1]
gdir = os.path.join(rel, 'gtfs')
with tempfile.TemporaryDirectory() as tmp:
    zp = os.path.join(tmp, 'gtfs.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in sorted(os.listdir(gdir)):
            if n.endswith('.txt'):
                z.write(os.path.join(gdir, n), n)

    print(f'== gtfs-kit {getattr(gk, "__version__", "")}'.rstrip())
    feed = gk.read_feed(zp, dist_units='km')
    for name in ['agency', 'routes', 'trips', 'stops', 'stop_times', 'calendar', 'frequencies', 'transfers',
                 'shapes', 'feed_info']:
        df = getattr(feed, name, None)
        print(f'  {name:12s}', None if df is None else df.shape)
    dates = feed.get_dates()
    print('  運行日', dates)
    ts = feed.compute_trip_stats()
    ns = feed.compute_network_stats(dates, trip_stats=ts)
    print('  1925-04-01 の統計（compute_network_stats）')
    for k in ['num_stops', 'num_routes', 'num_trips', 'peak_num_trips', 'peak_start_time']:
        print(f'    {k:16s} {ns[k].iloc[0]}')
    print('  assess_quality')
    for _, r in feed.assess_quality().iterrows():
        print(f'    {r["indicator"]:36s} {r["value"]}')
    st = feed.stops.set_index('stop_id')

    def crow(a, b):
        la1, lo1, la2, lo2 = map(math.radians, [st.at[a, 'stop_lat'], st.at[a, 'stop_lon'],
                                                st.at[b, 'stop_lat'], st.at[b, 'stop_lon']])
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
        return 2 * 6371 * math.asin(math.sqrt(h))

    d = ts.dropna(subset=['distance']).copy()
    d['crow'] = [crow(a, b) for a, b in zip(d.start_stop_id, d.end_stop_id)]
    print(f'  便の距離（線の形の全長で数える）: 距離のある便 {len(d)}・時速 100 km 超 {int((d.speed > 100).sum())}'
          f'・距離が始発〜終点の直線の 3 倍超かつ 20 km 超 {int(((d.distance > 3 * d.crow) & (d.distance > 20)).sum())}'
          f'・最大の時速 {d.speed.max():.0f} km')
    if len(d):   # the published dataset has no shapes, so no trip has a distance and no example is printed
        top = d.sort_values('speed', ascending=False).iloc[0]
        rn = feed.routes.set_index('route_id')['route_short_name']
        print(f'    例: {top.trip_id} {rn[top.route_id]} {st.at[top.start_stop_id, "stop_name"]}→'
              f'{st.at[top.end_stop_id, "stop_name"]} {top.duration * 60:.0f} 分・{top.distance:.1f} km')

    print(f'== partridge {ptg.__version__}')
    date, sids = ptg.read_busiest_date(zp)
    pf = ptg.load_feed(zp, view={'trips.txt': {'service_id': sids}})
    print('  いちばん便の多い日', date, sorted(sids))
    for name in ['routes', 'trips', 'stops', 'stop_times', 'frequencies', 'transfers', 'shapes']:
        print(f'  {name:12s}', getattr(pf, name).shape)
