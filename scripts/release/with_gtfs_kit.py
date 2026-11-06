#!/usr/bin/env python3
"""
Read the feed with gtfs-kit (https://github.com/mrcagney/gtfs_kit):  pip install gtfs-kit

    python3 examples/with_gtfs_kit.py            # reads the gtfs/ folder next to examples/
    python3 examples/with_gtfs_kit.py path/to/gtfs

Prints the feed summary, the stops where most trips call on 1925-04-01, and the routes with most
trips. Tested with gtfs-kit 13.0.1 and pandas 3.0.

Notes:
  * The feed has no shapes.txt and no shape_dist_traveled, so gtfs-kit's distance-based statistics
    (the distance column of compute_trip_stats, and compute_route_stats) come out empty. Counts and
    times do not need them.
  * Times later than 24:00:00 belong to the following day(s) of the same trip; gtfs-kit keeps them
    as strings such as "40:06:00".
"""
import os
import sys

import gtfs_kit as gk

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gtfs')
feed = gk.read_feed(path, dist_units='km')

print(feed.describe().to_string(index=False))

date = '19250401'      # any day of calendar.txt: every service runs every day
print(f'\nStops where most trips call on {date}:')
stop_stats = feed.compute_stop_stats([date])
top = stop_stats.sort_values('num_trips', ascending=False).head(5)
top = top.merge(feed.stops[['stop_id', 'stop_name']], on='stop_id')
print(top[['stop_id', 'stop_name', 'num_trips', 'start_time', 'end_time']].to_string(index=False))

print('\nRoutes with most trips:')
per_route = feed.trips.groupby('route_id').size().rename('num_trips')
routes = feed.routes.set_index('route_id').join(per_route).sort_values('num_trips', ascending=False).head(5)
print(routes[['route_short_name', 'route_long_name', 'num_trips']].to_string())
