#!/usr/bin/env python3
"""
Build input folders for OpenTripPlanner (OTP). The published GTFS is only read; a copy is modified.

    python3 tests/opentripplanner/make_otp_inputs.py <published dataset folder (with gtfs/)> <output folder>

Creates six folders in the output folder, each with a GTFS zip and OTP configuration.

  pure_defaults               Calendar as is, OTP defaults (feedId only). Used to confirm that the build stops.
  asis_defaults               Calendar as is (only 1925-04-01). Changes only two OTP settings: keep the 1925 trips
                              and search journeys up to 4 days.
  april_defaults              Copy whose calendar runs every day of April 1925 (the timetable repeats daily).
                              Same settings as above.
  april_aligned               April copy with settings aligned to the published example examples/route_1925.py
                              (0-minute transfer slack, transfers.txt times used as is, walk up to 45 minutes
                              in a straight line, up to 30 transfers).
  april_aligned_split         As above, plus template trips of frequencies.txt moved to separate route IDs
                              (so they do not share a stop pattern with printed trips; a test of keeping OTP from
                              ignoring the printed trips).
  april_aligned_split_exact   As above, plus all exact_times in frequencies.txt set to 1 (diagnostic; like the
                              example, trips run at every headway from the first departure).

No trip, station or time value is changed (only the calendar.txt end date, the template trips' route_id and
exact_times).
"""
import csv
import io
import json
import os
import sys
import zipfile

BUILD_BASE = {
    # The default is one year before to three years after the build date, which drops every 1925 trip and stops the build
    'transitServiceStart': '1925-01-01',
    'transitServiceEnd': '1925-12-31',
    'dataImportReport': True,
}
ROUTER_DEFAULTS = {
    'routingDefaults': {
        # Default is 24 hours; 東京→京城 takes 2 days and 東京→大泊 3 days
        'maxJourneyDuration': 'PT96H',
        # Return every itinerary found (for comparison; by default filtered itineraries are removed)
        'itineraryFilters': {'debug': 'list-all'},
    }
}
ROUTER_ALIGNED = {
    'routingDefaults': {
        'maxJourneyDuration': 'PT96H',
        'transferSlack': 'PT0S',
        'itineraryFilters': {'debug': 'list-all'},
    },
    'transit': {'maxNumberOfTransfers': 30},
}
OTP_ALIGNED = {'otpFeatures': {'MinimumTransferTimeIsDefinitive': True}}


def read_zip_members(gtfs_dir):
    return {n: open(os.path.join(gtfs_dir, n), encoding='utf-8-sig').read()
            for n in sorted(os.listdir(gtfs_dir)) if n.endswith('.txt')}


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def to_text(rs, cols):
    b = io.StringIO()
    w = csv.DictWriter(b, fieldnames=cols, lineterminator='\n')
    w.writeheader()
    w.writerows(rs)
    return b.getvalue()


def april(files):
    out = dict(files)
    cal = rows(files['calendar.txt'])
    for r in cal:
        r['end_date'] = '19250430'
    out['calendar.txt'] = to_text(cal, list(cal[0].keys()))
    if 'feed_info.txt' in files:
        fi = rows(files['feed_info.txt'])
        for r in fi:
            if r.get('feed_end_date'):
                r['feed_end_date'] = '19250430'
        out['feed_info.txt'] = to_text(fi, list(fi[0].keys()))
    return out


def split_templates(files):
    out = dict(files)
    freq = {r['trip_id'] for r in rows(files['frequencies.txt'])}
    trips = rows(files['trips.txt'])
    routes = rows(files['routes.txt'])
    rmap = {r['route_id']: r for r in routes}
    need = sorted({t['route_id'] for t in trips if t['trip_id'] in freq})
    extra = []
    for rid in need:
        nr = dict(rmap[rid])
        nr['route_id'] = rid + 'F'
        nr['route_long_name'] = (nr.get('route_long_name') or '') + '（頻度の推定便）'
        extra.append(nr)
    for t in trips:
        if t['trip_id'] in freq:
            t['route_id'] += 'F'
    out['routes.txt'] = to_text(routes + extra, list(routes[0].keys()))
    out['trips.txt'] = to_text(trips, list(trips[0].keys()))
    return out, len(need), len(freq)


def exact(files):
    out = dict(files)
    fr = rows(files['frequencies.txt'])
    for r in fr:
        r['exact_times'] = '1'
    out['frequencies.txt'] = to_text(fr, list(fr[0].keys()))
    return out


def write_variant(base, name, files, build_extra, router, otp):
    """When build_extra is None, keep OTP defaults (set only the feedId)."""
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    zp = os.path.join(d, 'gtfs-1925.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, c in files.items():
            z.writestr(n, c)
    build = {} if build_extra is None else dict(BUILD_BASE, **build_extra)
    build['transitFeeds'] = [{'type': 'gtfs', 'feedId': 'J1925', 'source': 'gtfs-1925.zip'}]
    json.dump(build, open(os.path.join(d, 'build-config.json'), 'w'), indent=2)
    if router:
        json.dump(router, open(os.path.join(d, 'router-config.json'), 'w'), indent=2)
    if otp:
        json.dump(otp, open(os.path.join(d, 'otp-config.json'), 'w'), indent=2)
    return d


def main():
    rel, out = sys.argv[1], sys.argv[2]
    files = read_zip_members(os.path.join(rel, 'gtfs'))
    ap = april(files)
    sp, n_routes, n_tmpl = split_templates(ap)
    write_variant(out, 'pure_defaults', files, None, None, None)     # no settings (every 1925 trip is dropped and the build stops)
    write_variant(out, 'asis_defaults', files, {}, ROUTER_DEFAULTS, None)
    write_variant(out, 'april_defaults', ap, {}, ROUTER_DEFAULTS, None)
    write_variant(out, 'april_aligned', ap, {'maxTransferDuration': 'PT45M'}, ROUTER_ALIGNED, OTP_ALIGNED)
    write_variant(out, 'april_aligned_split', sp, {'maxTransferDuration': 'PT45M'}, ROUTER_ALIGNED, OTP_ALIGNED)
    write_variant(out, 'april_aligned_split_exact', exact(sp), {'maxTransferDuration': 'PT45M'},
                  ROUTER_ALIGNED, OTP_ALIGNED)
    print(f'wrote 6 inputs to {out} (split: {n_tmpl} template trips moved to {n_routes} new routes)')


if __name__ == '__main__':
    main()
