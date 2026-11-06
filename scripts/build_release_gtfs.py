#!/usr/bin/env python3
"""
Build the published GTFS (the version deposited on Zenodo) by **copying** the source feed (GTFS_DIR, written by run_pipeline.sh).

    python3 scripts/build_release_gtfs.py
      GTFS_DIR=gtfs_v1  INTEGRATED_DIR=4_integrated_v1  RELEASE_DIR=gtfs_v1_release (all under data/)

Nothing is written to GTFS_DIR (generate_router_data.py and other tools read trip_short_name in trips.txt as the
internal key, so it cannot change there). Only the published dataset is written, to a separate folder.

Differences from the source feed (everything else keeps the same rows in the same order):
  1. Add feed_info.txt (publisher, language, validity period, version, contact email; RELEASE_PUBLISHER_NAME,
     RELEASE_CONTACT_EMAIL).
  2. Replace the name and URL in agency.txt (RELEASE_AGENCY_NAME, RELEASE_PUBLISHER_URL).
  3. Reduce trip_short_name in trips.txt to **the number printed in the original** (same rule as tripLabel in the
     journey planner): digits only -> as is; "digits_lowercase" (7_b) -> the digits; internal keys starting with a
     letter (Up0154_tb003-2_1, FQ001) -> empty; anything else (symbols of the original such as 甲, イ, 不イ) -> as is.
     Template trips (TF…, TQ…) are not printed trains, so empty. The original values stay in trip_source.csv
     (trip_id -> internal key, original trip_short_name, source sheets).
  4. For trips of departure-only tables (tram and light-railway tables that print only the 發 (departure) at the
     first stop), add one row with the terminal 著 (arrival) = departure + printed running time
     (data/tables/departure_only_running_times.csv), making a two-stop trip. All added rows are written to
     estimated_stop_times.csv as estimates.
  5. Trips that still have a single stop (unusable for journey planning) are removed from trips.txt and
     stop_times.txt and moved, with times and coordinates, to single_stop_trips.csv (no values are discarded).
     Trip IDs T… are not renumbered. Stations used only by such trips are also removed from stops.txt.
  6. Transfers: add parent stations to stops.txt (location_type=1; stop_id = journey-planner station group G…;
     coordinates from a published child) and set parent_station on each stop. transfers.txt gets "0 minutes within
     a parent station" and "walking minutes of the journey planner between stations reached on foot". Grouping calls
     the journey planner's functions (generate_router_data.py) directly, so it matches the planner (checked against
     router_data.json; stops on mismatch). Input: GTFS_DIR and INTEGRATED_DIR (override with
     RELEASE_TRANSFERS_GTFS_DIR / RELEASE_TRANSFERS_INTEGRATED_DIR).
  7. Through trains: extras/physical_trains.csv (data/tables/through_trains/physical_trains.csv keyed by trip_id).
     Not put in GTFS block_id (overlapping sections, date handling and ships would make the validator report ERROR).
  8. Place the usage example examples/route_1925.py, README.md and LICENSE (data CC BY 4.0, example scripts MIT),
     copied from scripts/release/.
  9. Provenance (RELEASE_PROVENANCE=1, default; code in scripts/release/provenance.py): GTFS-standard timepoint in
     stop_times.txt (1 = at least one printed time; 0 = computed times and template trips), trip_num_source and
     trip_num_sources in trip_source.csv, per-stop sources in extras/stop_time_source.csv (transcription page,
     sheet, column, row), per-station coordinate sources in extras/stop_coord_source.csv. 0 = not added.
 10. shapes.txt is not included (RELEASE_SHAPES=0, default). Shapes are one skeleton per route, so they do not fit
     trips entering branches or through trips, and existing tools would compute wrong trip distances. The shape_id
     column of trips.txt is also removed. 1 = included.
 11. Calendar: every trip runs daily from 1925-03-28 to 04-30 (RELEASE_CALENDAR_DAILY=1, default). The longest trip
     reaches 104:30, so starting four days earlier gives every trip on the morning of April 1. Trips the original
     does not print as daily are not split by calendar but described in tables (13). 0 = the source feed's
     calendar (one day, 1925-04-01).
 12. Merge trips from the shipping tables with printed dates (p189-p192) that have the same route, direction, stops
     and times (RELEASE_MERGE_SAME_SAILINGS=1, default). Those tables print the times once beside the ports, shared
     by every column, so without dates GTFS would repeat the same trip once per column. 0 = not merged.
 13. Operating-day tables (RELEASE_OPERATING_DAYS=1, default): extras/printed_sailings.csv (one row per printed
     sailing: dates and the trip carrying its times), extras/operating_days.csv (trips not running daily: ships with
     printed dates, fixed days of the month, alternate days, suspended days, irregular), and
     tools/make_printed_days_gtfs.py, which builds from them a GTFS following the printed operating days. Code in
     scripts/release/operating_days.py. 0 = not added.
 14. Frequency-only routes (RQ…) whose route_short_name is shared with another route get a section name
     (route_long_name = "○○・○○間" from the printed table heading, otherwise from the section ends)
     (RELEASE_FREQ_ROUTE_NAMES=1, default; code in scripts/release/route_names.py). Published route IDs are keyed on
     the original routes.txt names, so they do not change. 0 = no names.
 15. Move the region column of routes.txt (not in the GTFS spec) to extras/route_region.csv (route_id, route name,
     section name, region) (RELEASE_REGION_EXTRAS=1, default). The source feed keeps its region column (read by
     internal tools such as the journey-planner data). 0 = kept in routes.txt.
 16. When template trips (frequencies.txt trips, estimated from e.g. "此間N分毎" in the original) share a route with
     printed trips, move them to a separate route with the same line name and "頻度の推定便" appended to
     route_long_name (RELEASE_SPLIT_TEMPLATE_ROUTES=1, default; code in scripts/release/template_routes.py).
     OpenTripPlanner 2.10 ignores printed trips with the same stop pattern on a route that has any frequencies.txt
     trip. Trip, stop and time values are unchanged. Added routes go at the end of routes.txt and also appear in
     route_region.csv. 0 = same route.
 17. Remove routes left without trips by 5 (single-stop trips removed) and 12 (same-time ship trips merged) from
     routes.txt and route_region.csv (RELEASE_DROP_EMPTY_ROUTES=1, default). Their published IDs are kept
     (referenced by route_id in single_stop_trips.csv). 0 = kept.
 18. Give registry IDs (TR…, ST…) also to the single-stop trips removed in 5 and to stations used only by them
     (RELEASE_SINGLE_STOP_IDS=1, default). Keys are the same as for trips and stations kept in GTFS (trip = internal
     key line name__direction__number; station = station name|line name). 0 = internal IDs (reassigned every build).
 19. Copy three kinds of derived tables to extras/ (RELEASE_DERIVED_TABLES=1, default; code in
     scripts/release/derived_tables.py): train type and facilities (trip_attributes.csv), sailing frequency
     (service_frequency.csv), frequency source text and interpretation (frequency_box.csv, frequency_sections.csv,
     frequency_only.csv). Trips are keyed by published trip_id, and internal record words are dropped from free text
     (stops if any remain). 0 = not included.
 20. Route lines for maps, extras/route_lines.geojson (RELEASE_ROUTE_LINES = path of the skeleton built from the
     published coordinates; empty = not added; code in scripts/release/route_lines.py): one line per line name,
     connecting stations in running order with straight segments (not track shapes). Stops if any vertex differs
     from a published station coordinate. build_release_all.sh passes the skeleton of its work folder.
 21. Drop internal record words and ★ marks from free text of every table, then check that none remain in any
     published file (GTFS, tables, README, examples; the contact email excepted) and stop otherwise
     (RELEASE_SCRUB_ALL_EXTRAS=1, default; scrub_extras and check_release_text in scripts/release/derived_tables.py).
     0 = only the three derived tables of 19 are scrubbed.
 22-27, 30. Unused numbers (the coordinate source table outputs the columns of the stop-place table in
     data/knowledge/places/ as they are).
 28. Keep parent-station IDs (PS…) when grouping changes (RELEASE_ID_PARENT_INHERIT=1, default; 0 = previous
     behavior): for a parent key not in the registry, go through its child stops from the smallest ID and take over
     the ID of the previous parent (parent_station_children.csv) if unused this time. Code: PARENT_INHERIT in
     stable_ids.py.
 29. Place tools/make_router_data.py, an example that builds journey-planner data (router_data.json) from the
     published dataset alone (RELEASE_ROUTER_EXAMPLE=1, default; source scripts/release/make_router_data.py, standard
     library only, byte-identical output to scripts/release/build_release_router_data.py, which calls the journey
     planner's own functions). 0 = not placed.
 31. Take a parent station's coordinate from a child that has the station's own point (RELEASE_PARENT_COORD_STATION=1,
     default; 0 = previous behavior, the group's first child): children are chosen in the order station point
     (authority in the coordinate tables) -> computed station position (derived, interpolated) -> substitute point
     (proxy, place_unverified) -> others (ties keep the previous order). Code: _parent_coord_rank.
 32. In the route lines for maps, add line names without a skeleton shape, built from adjacent station pairs of the
     published trips (RELEASE_ROUTE_LINES_FILL_EMPTY=1, default; 0 = previous behavior, not added). Code: FILL_EMPTY
     in route_lines.py.
 33. Transcription layer transcription/ (RELEASE_TRANSCRIPTION=1, default): copy the numbered workbooks and the
     workbooks before numbering with ASCII file names, and add a long CSV with the same content. Workbook notes
     (row 12) and number notes (row 11) keep only copies of the original; pink fills, comments with work words and
     author fields are removed. Code in scripts/release/package_layers.py. 0 = not included.
 34. Integrated layer integrated/ (RELEASE_INTEGRATED=1, default): integrated_stop_times, trips_master, stops_master
     (coordinate columns removed) with published trip_id, stop_id and route_id; work words dropped from free text.
     qa_log and split_trips_report are not included by default (RELEASE_INCLUDE_QA_LOG, RELEASE_INCLUDE_SPLIT_REPORT
     in package_layers.py). 0 = not included.
 35. Table of cells corrected as misprints of the original, extras/misprint_corrections.csv
     (RELEASE_MISPRINT_TABLE=1, default): a straight copy of data/tables/misprints.csv (only values checked in the
     printed reprint or with characters hard to misread in the scan). 0 = not included.
 36. Station-name variants table extras/stop_name_variants.csv (RELEASE_STOP_NAME_VARIANTS=1, default): per station,
     stop_name, the name in modern kanji (for search; per-character table scripts/release/shinjitai_map.csv) and the
     spellings printed in the transcription. Code in scripts/release/stop_name_variants.py. The six GTFS files are
     unchanged. 0 = not included.
 37. Detailed file description DETAILS.md (RELEASE_DETAILS=1, default): full text of the 13 notes (numbered as in
     the README), provenance, derived-table columns, transcription and integrated layers, and the journey-planner
     network, copied from scripts/release/DETAILS_release.md (Japanese: DETAILS_release_ja.md). 0 = not copied.
  Output layout: RELEASE_DIR/gtfs/ (GTFS), extras/ (tables), examples/ (examples for getting started), tools/ (tools
  that build other files from the GTFS), transcription/, integrated/, README.md, DETAILS.md, LICENSE.
  estimated_stop_times.csv also lists the computed values of the frequency-only template trips (TQ…) that are in
  the source feed.
"""
import csv
import hashlib
import os
import re
import shutil
import sys
from collections import OrderedDict, defaultdict
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GTFS_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('GTFS_DIR', 'gtfs_v1'))
INT_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated_v1'))
OUT_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('RELEASE_DIR', 'gtfs_v1_release'))
DUR_TABLE = os.path.join(BASE_DIR, 'data', 'tables', 'departure_only_running_times.csv')
# Input for transfers (station groups, proximity merges, walking pairs and minutes). Default GTFS_DIR and
#   INTEGRATED_DIR (published coordinates); RELEASE_TRANSFERS_GTFS_DIR / _INTEGRATED_DIR override them.
#   The rules are in generate_router_data.py.
TRANSFERS_GTFS_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('RELEASE_TRANSFERS_GTFS_DIR', GTFS_DIR))
TRANSFERS_INT_DIR = os.path.join(BASE_DIR, 'data', os.environ.get('RELEASE_TRANSFERS_INTEGRATED_DIR', INT_DIR))

# Agency name = the data source (the original, 『汽車時間表』 vol. 1 no. 1).
#   Routes are not assigned to their actual operators (government railways, private railways, SMR, shipping
#   companies); all routes share one nominal agency.
AGENCY_NAME = os.environ.get('RELEASE_AGENCY_NAME', '汽車時間表 1925年4月号（翻刻）')
# Publisher and contact. The contact goes to feed_contact_email in feed_info.txt; an empty RELEASE_CONTACT_EMAIL
#   gives the earlier form (feed_contact_url = publisher URL).
PUBLISHER_NAME = os.environ.get('RELEASE_PUBLISHER_NAME', '大内 啓樹（奈良先端科学技術大学院大学）')
CONTACT_EMAIL = os.environ.get('RELEASE_CONTACT_EMAIL', 'hiroki.ouchi@is.naist.jp')
# Publisher URL = the Zenodo DOI. For a placeholder: RELEASE_PUBLISHER_URL=https://example.org
PUBLISHER_URL = (os.environ.get('RELEASE_PUBLISHER_URL', '')
                 or 'https://doi.org/10.5281/zenodo.23200420')
FEED_VERSION = os.environ.get('RELEASE_FEED_VERSION', '')
# For the final build (with DOI, authors and title) set RELEASE_FINAL=1: stop if placeholders remain in README,
#   LICENSE, agency.txt or feed_info.txt (the DRAFT note, https://example.org, 〔Authors〕〔year〕〔Title〕
#   〔feed_version〕〔copyright holder〕, the DOI's 〔…〕) (check_placeholders in scripts/release/derived_tables.py).
#   Default 0 = placeholders allowed.
FINAL = os.environ.get('RELEASE_FINAL', '0') == '1'
# Copy the known-issues list scripts/release/KNOWN_ISSUES_release.md as KNOWN_ISSUES.md. On by default.
#   0 = not included (previous behavior).
KNOWN_ISSUES = os.environ.get('RELEASE_KNOWN_ISSUES', '1') == '1'
# Copy the Japanese README scripts/release/README_release_ja.md as README.ja.md. On by default.
#   0 = not included (previous behavior).
README_JA = os.environ.get('RELEASE_README_JA', '1') == '1'
# Copy the Japanese reference translation scripts/release/LICENSE_release_ja.md as LICENSE.ja.md (only the English
#   LICENSE is legally binding). On by default. 0 = not included (previous behavior).
LICENSE_JA = os.environ.get('RELEASE_LICENSE_JA', '1') == '1'
# Copy the Japanese known-issues list scripts/release/KNOWN_ISSUES_release_ja.md as KNOWN_ISSUES.ja.md (the English
#   version is authoritative). On by default. 0 = not included (previous behavior).
KNOWN_ISSUES_JA = os.environ.get('RELEASE_KNOWN_ISSUES_JA', '1') == '1'
# 37. Copy the detailed file description scripts/release/DETAILS_release.md as DETAILS.md (the Japanese
#   DETAILS_release_ja.md under the same condition as README_JA). On by default. 0 = not copied.
DETAILS = os.environ.get('RELEASE_DETAILS', '1') == '1'
# 40. Copy examples for common software, examples/with_gtfs_kit.py and examples/opentripplanner/ (configuration
#   files, README.md), from scripts/release/. On by default. 0 = not copied.
EXAMPLES_LIBS = os.environ.get('RELEASE_EXAMPLES_LIBS', '1') == '1'
# 33, 34. Include the transcription layer (transcription/) and the integrated layer (integrated/) (code in
#   scripts/release/package_layers.py). On by default. 0 = not included (previous behavior). 33 takes about five
#   minutes (opens and re-saves 356 workbooks).
TRANSCRIPTION = os.environ.get('RELEASE_TRANSCRIPTION', '1') == '1'
INTEGRATED_LAYER = os.environ.get('RELEASE_INTEGRATED', '1') == '1'
# 35. Copy the table of cells corrected as misprints, data/tables/misprints.csv, as extras/misprint_corrections.csv
#   (the transcription layer holds the corrected values, so the printed values survive only in this table).
#   On by default. 0 = not included (previous behavior).
MISPRINT_TABLE = os.environ.get('RELEASE_MISPRINT_TABLE', '1') == '1'
MISPRINT_SRC = os.path.join(BASE_DIR, 'data', 'tables', 'misprints.csv')
# 36. Include the station-name variants table (modern-kanji names and transcription spellings;
#   scripts/release/stop_name_variants.py), since stop_name has one spelling per station (mostly old kanji) and a
#   modern-kanji search would miss it. On by default. 0 = not included (previous behavior).
STOP_NAME_VARIANTS = os.environ.get('RELEASE_STOP_NAME_VARIANTS', '1') == '1'

PHYSICAL_TRAINS =os.path.join(BASE_DIR, 'data', 'tables', 'through_trains', 'physical_trains.csv')

sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
import generate_router_data as grd  # noqa: E402  station grouping and walking links use the journey planner's own functions

# Fix published IDs with the ID registry. On by default. 0 = internal IDs (previous behavior).
STABLE_IDS = os.environ.get('RELEASE_STABLE_IDS', '1') == '1'
# Provenance columns and tables (9). On by default. 0 = not added (previous behavior).
PROVENANCE = os.environ.get('RELEASE_PROVENANCE', '1') == '1'
# Include shapes.txt (10). Default 0 = not included. 1 = included (previous behavior).
SHAPES = os.environ.get('RELEASE_SHAPES', '0') == '1'
# Calendar: every trip daily (11). On by default. 0 = the source feed's calendar (previous behavior).
CALENDAR_DAILY = os.environ.get('RELEASE_CALENDAR_DAILY', '1') == '1'
CALENDAR_START = os.environ.get('RELEASE_CALENDAR_START', '19250328')
CALENDAR_END = os.environ.get('RELEASE_CALENDAR_END', '19250430')
# Merge same-time trips of the shipping tables with printed dates (12). On by default. 0 = not merged (previous behavior).
MERGE_SAME_SAILINGS = os.environ.get('RELEASE_MERGE_SAME_SAILINGS', '1') == '1'
# Operating-day tables and the tool that converts to a GTFS with the printed operating days (13). On by default.
#   0 = not added (previous behavior).
OPERATING_DAYS = os.environ.get('RELEASE_OPERATING_DAYS', '1') == '1'
# Give frequency-only routes a section name to tell them from same-named routes (14). On by default.
#   0 = no names (previous behavior).
FREQ_ROUTE_NAMES = os.environ.get('RELEASE_FREQ_ROUTE_NAMES', '1') == '1'
# Move the region column of routes.txt to extras/route_region.csv (15). On by default. 0 = kept in routes.txt (previous behavior).
REGION_EXTRAS = os.environ.get('RELEASE_REGION_EXTRAS', '1') == '1'
# Move template trips (frequencies.txt trips) to a route separate from printed trips (16). On by default.
#   0 = same route as the printed trips (previous behavior).
SPLIT_TEMPLATE_ROUTES = os.environ.get('RELEASE_SPLIT_TEMPLATE_ROUTES', '1') == '1'
# Remove routes left without trips from routes.txt (17). On by default. 0 = kept (previous behavior).
DROP_EMPTY_ROUTES = os.environ.get('RELEASE_DROP_EMPTY_ROUTES', '1') == '1'
# Give published IDs also to single-stop trips removed from GTFS and to stations used only by them (18). On by default.
#   0 = trip_id in single_stop_trips.csv and stop_id of removed stations stay internal (previous behavior).
SINGLE_STOP_IDS = os.environ.get('RELEASE_SINGLE_STOP_IDS', '1') == '1'
# Copy the three derived tables (train type and facilities, sailing frequency, frequency source text and
#   interpretation) to extras/ (19). On by default. 0 = not included (previous behavior).
DERIVED_TABLES = os.environ.get('RELEASE_DERIVED_TABLES', '1') == '1'
# Route lines for maps, extras/route_lines.geojson (20). Value = skeleton file built from published coordinates
#   (build_release_all.sh passes track_geometry/line_skeletons.geojson of its work folder). Empty = not added
#   (previous behavior). Stops if a vertex differs from a published station coordinate.
ROUTE_LINES_SRC = os.environ.get('RELEASE_ROUTE_LINES', '')
# Drop internal record words and ★ marks from free text of all tables and check every published file (21).
#   On by default. 0 = only the three derived tables (previous behavior).
SCRUB_ALL_EXTRAS = os.environ.get('RELEASE_SCRUB_ALL_EXTRAS', '1') == '1'
# Keep parent-station IDs when grouping changes (28): a parent key not in the registry takes over the previous
#   parent ID of its oldest child (PARENT_INHERIT in scripts/release/stable_ids.py). On by default. 0 = previous behavior.
ID_PARENT_INHERIT = os.environ.get('RELEASE_ID_PARENT_INHERIT', '1') == '1'
# Take a parent station's coordinate from a child with the station's own point (31). On by default. 0 = previous behavior.
PARENT_COORD_STATION = os.environ.get('RELEASE_PARENT_COORD_STATION', '1') == '1'
# In the route lines for maps, add line names without a shape, built from published trips (32). On by default.
#   0 = previous behavior.
ROUTE_LINES_FILL_EMPTY = os.environ.get('RELEASE_ROUTE_LINES_FILL_EMPTY', '1') == '1'
_TRANSFERS_STOPS_INFO = {}
# Place tools/make_router_data.py, which builds journey-planner data from the published dataset alone (29).
#   On by default. 0 = not placed (previous behavior).
ROUTER_EXAMPLE = os.environ.get('RELEASE_ROUTER_EXAMPLE', '1') == '1'
# Reword internal terms in free text of the tables for outside readers and check none remain (WORK_REWRITES in
#   scripts/release/derived_tables.py). Only with RELEASE_SCRUB_ALL_EXTRAS=1. On by default. 0 = previous behavior.
REWRITE_WORK_WORDS = os.environ.get('RELEASE_REWRITE_WORK_WORDS', '1') == '1'
# Second rewrite table (WORK_REWRITES_2 in scripts/release/derived_tables.py): reword dates, names of transcription
#   rules, names of tables not in the published dataset and internal integration terms in free text; stop if any
#   remain. Only with RELEASE_REWRITE_WORK_WORDS=1. On by default. 0 = previous behavior.
REWRITE_WORK_WORDS_2 = os.environ.get('RELEASE_REWRITE_WORK_WORDS_2', '1') == '1'
# Third rewrite table (WORK_REWRITES_3 in scripts/release/derived_tables.py): reword internal names in free-text
#   fields (FREE_TEXT_COLS) into the wording of the published documents; stop if any remain. package_layers.py
#   applies the same table to the transcription notes (row 12). Only with RELEASE_REWRITE_WORK_WORDS=1.
#   On by default. 0 = previous behavior.
REWRITE_WORK_WORDS_3 = os.environ.get('RELEASE_REWRITE_WORK_WORDS_3', '1') == '1'
# Also list in source_sheets of extras/trip_source.csv the band sheets whose values filled blank cells (sheets that
#   stop_time_source.csv cites for printed values). Only with RELEASE_PROVENANCE=1. On by default.
#   0 = previous behavior (only the sheets in the integration record).
TRIP_SOURCE_ALL_SHEETS = os.environ.get('RELEASE_TRIP_SOURCE_ALL_SHEETS', '1') == '1'

GTFS_FILES = ['agency.txt', 'calendar.txt', 'routes.txt', 'trips.txt', 'stop_times.txt',
              'stops.txt', 'shapes.txt', 'frequencies.txt']


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def write_csv(path, fields, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fields})


def printed_number(n):
    """Same rule as tripLabel in the search core embedded in demo/route_planner/index.html."""
    if re.fullmatch(r'\d+', n):
        return n
    m = re.fullmatch(r'(\d+)_[a-z]', n)
    if m:
        return m.group(1)
    if not n or re.match(r'[A-Za-z]', n):
        return ''
    return n


def build_station_groups():
    """Build station groups and walking links by passing the same input to the same functions as the journey planner
    (generate_router_data.main). Input: stops_master of TRANSFERS_INT_DIR and stop_times of TRANSFERS_GTFS_DIR
    (default INTEGRATED_DIR and GTFS_DIR)."""
    transfers_stop_times = read_csv(os.path.join(TRANSFERS_GTFS_DIR, 'stop_times.txt'))[1]
    stops_info = {}
    for r in read_csv(os.path.join(TRANSFERS_INT_DIR, 'stops_master.csv'))[1]:
        stops_info[r['stop_id']] = {
            'name': r['stop_name'], 'line': r['line_name'],
            'lat': float(r['stop_lat']) if r.get('stop_lat') else None,
            'lon': float(r['stop_lon']) if r.get('stop_lon') else None,
            'src': r.get('coord_source', ''),
        }
    _TRANSFERS_STOPS_INFO.update(stops_info)       # 31. used to look up the coordinate kind when choosing a parent's coordinate
    groups, group_of_stop, name_to_groups = grd.build_groups(stops_info)
    trip_stops = defaultdict(list)
    for r in transfers_stop_times:
        trip_stops[r['trip_id']].append(r)
    n_near = 0
    if grd.GROUP_NEAR:
        merged = grd.merge_near_groups(groups, group_of_stop, name_to_groups, stops_info, trip_stops,
                                       grd.GROUP_NEAR_M / 1000.0, trip_guard=grd.GROUP_NEAR_TRIP_GUARD)
        n_near = sum(1 for m in merged if m[7] == '併合')
    walks = {}
    if grd.WALK_EDGES:
        walks, _ = grd.build_walk_edges(groups, stops_info, trip_stops,
                                        grd.WALK_MAX_M, grd.WALK_SPEED_M_PER_MIN)
    return groups, group_of_stop, walks, n_near, {sid: (v['name'], v['line']) for sid, v in stops_info.items()}


def _parent_coord_rank(c, ll_of):
    """31. Rank of a child for taking the parent's coordinate (smaller first).
    0 = authority in the coordinate tables (the station's own point) and the published value equals stops_master (within 10 m)
    1 = computed station position (derived in the coordinate tables, or interpolated)
    2 = substitute point (proxy, place_unverified: a place or facility, not the station itself) with the published
        value equal to stops_master
    3 = others (e.g. values replaced in the published dataset)"""
    info = _TRANSFERS_STOPS_INFO.get(c, {})
    if not info or info.get('lat') is None or not ll_of[c][0]:
        return 3
    same = grd.haversine(info['lat'], info['lon'], float(ll_of[c][0]), float(ll_of[c][1])) * 1000 <= 10
    src = info.get('src', '')
    if src == 'agent_known':
        import agent_knowledge as _ak
        kind = _ak.lookup_kind(info['name'], info['line'])
        if kind == 'authority':
            return 0 if same else 3
        if kind == 'derived':
            return 1
        if kind in ('proxy', 'place_unverified'):
            return 2 if same else 3
        return 3
    if src == 'wikidata':        # Wikidata station item used in the published dataset = the station's own point
        return 0 if same else 3
    if src == 'release_proxy':   # substitute point used in the published dataset = a place, not the station
        return 2 if same else 3
    return 1 if 'inferred' in src else 3


def check_same_as_router(groups):
    """Check that the station groups equal those in router_data.json of TRANSFERS_GTFS_DIR (the journey planner's data).
    Stop if they differ."""
    p = os.path.join(TRANSFERS_GTFS_DIR, 'router_data.json')
    if not os.path.exists(p):
        print('  ★router_data.json が無いので、経路検索との照合を飛ばした')
        return
    import json
    with open(p, encoding='utf-8') as f:
        rg = json.load(f)['groups']
    mine = {g: v['name'] for g, v in groups.items()}
    theirs = {g: v['name'] for g, v in rg.items()}
    if mine != theirs:
        diff = sorted(set(mine.items()) ^ set(theirs.items()))[:10]
        raise SystemExit(f'駅のまとまりが経路検索（router_data.json）と違う: {diff}'
                         '（GTFS_DIR と INTEGRATED_DIR が同じ回の組か、環境変数の既定が変わっていないかを確かめる）')
    print(f'  駅のまとまりは経路検索（router_data.json）と同じ（{len(mine)}）')


def relabel_stable_ids(G, X, kept_stops, here_key, groups, transfers_key, key_of, source, extra_routes=(),
                       single_rows=()):
    """Rewrite internal IDs (S…, G…, R…, T…, SHP_R…) to the published IDs fixed by the ID registry (published files only).
    extra_routes: routes removed from routes.txt but referenced by tables (17); they get IDs and the tables' route_id
    is rewritten. single_rows: rows of single_stop_trips.csv (18); removed trips and stations used only by them
    also get IDs."""
    sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
    import stable_ids
    stable_ids.PARENT_INHERIT = ID_PARENT_INHERIT      # 28. keep parent-station IDs
    # build keys
    stop_items, stop_key = {}, {}
    for r in kept_stops:
        name, line = here_key[r['stop_id']]
        k = f'{name}|{line}'
        stop_key[r['stop_id']] = k
        stop_items[k] = {'lat': r['stop_lat'], 'lon': r['stop_lon'], 'line': line}
    for r in single_rows:      # 18. stations removed from stops.txt (used only by removed trips) get the same kind of key
        if r['stop_id'] not in stop_key:
            name, line = here_key[r['stop_id']]
            k = f'{name}|{line}'
            stop_key[r['stop_id']] = k
            stop_items[k] = {'lat': r['stop_lat'], 'lon': r['stop_lon'], 'line': line}
    _, st_rows = read_csv(os.path.join(G, 'stops.txt'))
    station_key = {}
    for r in st_rows:
        if r.get('location_type') == '1':
            rep = groups[r['stop_id']]['members'][0]
            station_key[r['stop_id']] = 'station|' + '|'.join(transfers_key.get(rep, (rep, '')))
    _, rt_rows = read_csv(os.path.join(G, 'routes.txt'))
    rt_rows += list(extra_routes)
    # keys use route_long_name of the original routes.txt (GTFS_DIR), so section names added in 14 do not change route IDs
    src_long = {r['route_id']: r.get('route_long_name', '') for r in read_csv(os.path.join(GTFS_DIR, 'routes.txt'))[1]}
    route_key = {}
    for r in rt_rows:
        k = ('freq' if r['route_id'].startswith('RQ') else 'rail') + \
            f"|{r['route_short_name']}|{src_long.get(r['route_id'], r.get('route_long_name', ''))}"
        if k in route_key.values():
            k += f"|{r['route_id']}"
        route_key[r['route_id']] = k
    orig_name = {s['trip_id']: s['original_trip_short_name'] for s in source}
    freq_start = {}
    if os.path.exists(os.path.join(G, 'frequencies.txt')):
        for r in read_csv(os.path.join(G, 'frequencies.txt'))[1]:
            freq_start.setdefault(r['trip_id'], r['start_time'])
    box_tpl = {}
    p = os.path.join(GTFS_DIR, 'frequency_box.csv')
    if os.path.exists(p):
        for r in read_csv(p)[1]:
            if r.get('template_trip_id'):
                box_tpl[r['template_trip_id']] = r.get('template_trip_key', '')
    _, tr_rows = read_csv(os.path.join(G, 'trips.txt'))
    trip_key = {}
    for r in tr_rows:
        tid = r['trip_id']
        if tid.startswith('TF'):
            k = f"box|{box_tpl.get(tid, '')}|{freq_start.get(tid, '')}"
        elif tid.startswith('TQ'):
            k = f"section|{orig_name.get(tid, '')}|{r['direction_id']}|{freq_start.get(tid, '')}"
        else:
            k = key_of.get(tid, tid)
        trip_key[tid] = k
    for r in single_rows:      # 18. trips removed from trips.txt get the same key as printed trips (internal key line name__direction__number)
        trip_key.setdefault(r['trip_id'], key_of.get(r['trip_id'], r['trip_id']))
    # child stop keys of each parent station (used by stable_ids to take over previous parent IDs; unused when OFF)
    station_members = {station_key[g]: [stop_key[m] for m in groups[g]['members'] if m in stop_key] for g in station_key}
    items = {'stop': stop_items,
             'station': {k: {'members': station_members[k]} for k in station_key.values()},
             'route': {k: {} for k in route_key.values()},
             'trip': {k: {} for k in trip_key.values()}}
    for kind in ('station', 'route', 'trip'):
        if len(items[kind]) != len({'station': station_key, 'route': route_key, 'trip': trip_key}[kind]):
            raise SystemExit(f'公開版の番号: {kind} の鍵が重なっている（固定できない）')
    ids, report = stable_ids.assign(items)
    m_stop = {sid: ids['stop'][k] for sid, k in stop_key.items()}
    m_stop.update({gid: ids['station'][k] for gid, k in station_key.items()})
    m_route = {rid: ids['route'][k] for rid, k in route_key.items()}
    m_trip = {tid: ids['trip'][k] for tid, k in trip_key.items()}
    m_shape = {f'SHP_{rid}': f'SH_{pid}' for rid, pid in m_route.items()}
    # internal-to-published ID map (for tools such as comparisons with the journey planner; not in the published dataset)
    with open(stable_ids.MAP_OUT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(['kind', 'internal_id', 'public_id'])
        for kind, m in (('stop', {k: v for k, v in m_stop.items() if not k.startswith('G')}),
                        ('station', {k: v for k, v in m_stop.items() if k.startswith('G')}),
                        ('route', m_route), ('trip', m_trip)):
            for k in sorted(m):
                w.writerow([kind, k, m[k]])
    cols = {'stop_id': m_stop, 'parent_station': m_stop, 'from_stop_id': m_stop, 'to_stop_id': m_stop,
            'reference_stop_id': m_stop,
            'route_id': m_route, 'trip_id': m_trip, 'shape_id': m_shape}
    for d in (G, X):
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if not (name.endswith('.txt') or name.endswith('.csv')):
                continue
            fields, rows = read_csv(path)
            touch = [c for c in fields if c in cols]
            if not touch:
                continue
            for r in rows:
                for c in touch:
                    if r.get(c):
                        r[c] = cols[c].get(r[c], r[c])
            write_csv(path, fields, rows)
    rl_path = os.path.join(X, 'route_lines.geojson')
    if os.path.exists(rl_path):    # 20. relabel route_ids of the route lines (GeoJSON) too
        import route_lines
        route_lines.relabel(rl_path, m_route)
    left = [r for r in read_csv(os.path.join(G, 'stops.txt'))[1] if not re.match(r'(ST|PS)\d', r['stop_id'])]
    if left:
        raise SystemExit(f'公開版の番号: 書き換わらなかった stop_id がある: {[r["stop_id"] for r in left[:5]]}')
    if single_rows:            # 18. no internal IDs left in single_stop_trips.csv
        pub = {'trip_id': r'TR\d', 'stop_id': r'ST\d', 'route_id': r'RT\d'}
        left = [f'{c}={r[c]}' for r in read_csv(os.path.join(X, 'single_stop_trips.csv'))[1]
                for c, p in pub.items() if r.get(c) and not re.match(p, r[c])]
        if left:
            raise SystemExit(f'公開版の番号: single_stop_trips.csv に内部の番号が残っている: {left[:5]}')
    n = {}
    for r in report:
        n[r['判定']] = n.get(r['判定'], 0) + 1
    print('  公開版の番号（番号台帳で固定）: ' + '・'.join(f'{k} {v}' for k, v in sorted(n.items()))
          + (f'（台帳を更新した）' if os.environ.get('RELEASE_WRITE_ID_REGISTRY', '0') == '1' else '（台帳は読むだけ）'))
    return report


def add_minutes(hms, minutes):
    h, m, s = (int(x) for x in hms.split(':'))
    t = h * 60 + m + minutes
    return f'{t // 60:02d}:{t % 60:02d}:{s:02d}'


# Names the dataset build writes at the top of RELEASE_DIR (an earlier output holds only these; macOS may add .DS_Store)
RELEASE_TOP_NAMES = {'gtfs', 'extras', 'examples', 'tools', 'transcription', 'integrated', 'README.md', 'README.ja.md',
                     'DETAILS.md', 'DETAILS.ja.md', 'KNOWN_ISSUES.md', 'KNOWN_ISSUES.ja.md', 'LICENSE', 'LICENSE.ja.md',
                     '.DS_Store'}


def _is_inside(path, folder):
    """True if path is folder or lies inside it. Compared with os.path.samefile, so neither the case of the letters
    (the default macOS file system ignores it) nor symbolic links make a difference."""
    p = os.path.realpath(path)
    while True:
        try:
            if os.path.samefile(p, folder):
                return True
        except OSError:
            pass
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent


def check_release_dir_removable():
    """Stop unless RELEASE_DIR can be removed safely: it must not be, or contain, an input folder, the repository or a
    folder above it, and it must be empty or hold only what the dataset build writes (RELEASE_TOP_NAMES)."""
    if not os.path.isdir(OUT_DIR):
        return
    data = os.path.join(BASE_DIR, 'data')
    inputs = [GTFS_DIR, INT_DIR, TRANSFERS_GTFS_DIR, TRANSFERS_INT_DIR, BASE_DIR, os.path.expanduser('~'), '/'] + \
        [os.path.join(data, d) for d in ('knowledge', 'tables', 'distance', 'external', '1_timetable_xlsx_v1',
                                         '1_timetable_xlsx_added_v1',
                                         os.environ.get('STOP_TIMES_DIR', '3_stop_times_intermediate_v1'),
                                         os.environ.get('TRIPNUM_DIR', '2_timetable_with_tripnum_v1'))]
    if ROUTE_LINES_SRC:
        inputs.append(ROUTE_LINES_SRC)
    if any(os.path.exists(k) and _is_inside(k, OUT_DIR) for k in inputs):
        raise SystemExit(f'RELEASE_DIR は消してよい場所でない（入力のフォルダかその上を指している）: {OUT_DIR}')
    other = sorted(set(os.listdir(OUT_DIR)) - RELEASE_TOP_NAMES)
    if other:
        raise SystemExit(f'RELEASE_DIR に公開版でないものがあるので、消さずに止めた: {OUT_DIR}（{"・".join(other[:5])}）')


def main():
    # Recreate the output folder every time (no leftovers), after checking that it is safe to remove.
    check_release_dir_removable()
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    G = os.path.join(OUT_DIR, 'gtfs')          # the GTFS itself (what validators and routing software read)
    X = os.path.join(OUT_DIR, 'extras')        # tables kept outside the GTFS
    for d in (G, X, os.path.join(OUT_DIR, 'examples')):
        os.makedirs(d)

    # fingerprint of the source feed's content (used in feed_version)
    h = hashlib.md5()
    for name in GTFS_FILES:
        p = os.path.join(GTFS_DIR, name)
        if os.path.exists(p):
            with open(p, 'rb') as f:
                h.update(f.read())
    version = FEED_VERSION or f'{date.today():%Y%m%d}-{h.hexdigest()[:8]}'

    # --- files copied as they are
    for name in (() if CALENDAR_DAILY else ('calendar.txt',)) + ('routes.txt', 'frequencies.txt') \
            + (('shapes.txt',) if SHAPES else ()):
        p = os.path.join(GTFS_DIR, name)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(G, name))
    freq_long = {}
    if FREQ_ROUTE_NAMES:   # 14. section names for frequency-only routes (to tell same-named routes apart)
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import route_names

        def extra_rows(name):
            p = os.path.join(GTFS_DIR, name)
            return read_csv(p)[1] if os.path.exists(p) else []
        r_fields, r_rows = read_csv(os.path.join(G, 'routes.txt'))
        freq_long = route_names.freq_route_long_names(r_rows, extra_rows('frequency_sections.csv'),
                                                      extra_rows('frequency_only.csv'))
        if freq_long:
            if 'route_long_name' not in r_fields:
                r_fields.append('route_long_name')
            for r in r_rows:
                if r['route_id'] in freq_long:
                    r['route_long_name'] = freq_long[r['route_id']]
            write_csv(os.path.join(G, 'routes.txt'), r_fields, r_rows)
    tpl_routes, tpl_move = [], {}
    if SPLIT_TEMPLATE_ROUTES:   # 16. template trips to a route separate from printed trips (routes added before the table of 15, so they appear there)
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import template_routes
        r_fields, r_rows = read_csv(os.path.join(G, 'routes.txt'))
        fp = os.path.join(GTFS_DIR, 'frequencies.txt')
        freq_ids = {r['trip_id'] for r in read_csv(fp)[1]} if os.path.exists(fp) else set()
        tpl_routes, tpl_move = template_routes.plan(r_rows, read_csv(os.path.join(GTFS_DIR, 'trips.txt'))[1],
                                                    freq_ids)
        if tpl_routes:
            if 'route_long_name' not in r_fields:
                r_fields.append('route_long_name')
            write_csv(os.path.join(G, 'routes.txt'), r_fields, r_rows + tpl_routes)
    n_region = 0
    if REGION_EXTRAS:      # 15. move the region column (not in the spec) to a table
        r_fields, r_rows = read_csv(os.path.join(G, 'routes.txt'))
        if 'region' in r_fields:
            write_csv(os.path.join(X, 'route_region.csv'),
                      ['route_id', 'route_short_name', 'route_long_name', 'region'], r_rows)
            write_csv(os.path.join(G, 'routes.txt'), [f for f in r_fields if f != 'region'], r_rows)
            n_region = len(r_rows)
    c_fields, cal = read_csv(os.path.join(GTFS_DIR, 'calendar.txt'))
    if CALENDAR_DAILY:     # 11. every trip daily (one service, as in the source feed; all weekdays 1)
        for c in cal:
            for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'):
                c[d] = '1'
            c['start_date'], c['end_date'] = CALENDAR_START, CALENDAR_END
        write_csv(os.path.join(G, 'calendar.txt'), c_fields, cal)

    # --- 1, 2. agency / feed_info
    a_fields, agencies = read_csv(os.path.join(GTFS_DIR, 'agency.txt'))
    for a in agencies:
        a['agency_name'] = AGENCY_NAME
        a['agency_url'] = PUBLISHER_URL
    if 'agency_lang' not in a_fields:
        a_fields.append('agency_lang')
    for a in agencies:
        a['agency_lang'] = 'ja'
    write_csv(os.path.join(G, 'agency.txt'), a_fields, agencies)
    fi_fields = ['feed_publisher_name', 'feed_publisher_url', 'feed_lang',
                 'feed_start_date', 'feed_end_date', 'feed_version']
    fi = {'feed_publisher_name': PUBLISHER_NAME, 'feed_publisher_url': PUBLISHER_URL,
          'feed_lang': 'ja', 'feed_start_date': min(c['start_date'] for c in cal),
          'feed_end_date': max(c['end_date'] for c in cal), 'feed_version': version}
    if CONTACT_EMAIL:      # contact = email (a placeholder URL is never the contact)
        fi_fields.append('feed_contact_email')
        fi['feed_contact_email'] = CONTACT_EMAIL
    else:                  # earlier form
        fi_fields.append('feed_contact_url')
        fi['feed_contact_url'] = PUBLISHER_URL
    write_csv(os.path.join(G, 'feed_info.txt'), fi_fields, [fi])

    # --- provenance (trip_id -> internal key, sheets)
    _, tm = read_csv(os.path.join(INT_DIR, 'trips_master.csv'))
    key_of = {r['gtfs_trip_id']: r['gtfs_trip_key'] for r in tm}
    sheets_of = defaultdict(list)
    _, integ = read_csv(os.path.join(INT_DIR, 'integrated_stop_times.csv'))
    for r in integ:
        s = sheets_of[r['gtfs_trip_key']]
        if r['source_sheet'] not in s:
            s.append(r['source_sheet'])
    sid_of = {}
    _, sm = read_csv(os.path.join(INT_DIR, 'stops_master.csv'))
    for r in sm:
        sid_of[(r['stop_name'], r['line_name'])] = r['stop_id']
    s_fields, stops = read_csv(os.path.join(GTFS_DIR, 'stops.txt'))
    stop_name = {r['stop_id']: r['stop_name'] for r in stops}
    stop_ll = {r['stop_id']: (r['stop_lat'], r['stop_lon']) for r in stops}

    # --- read trips / stop_times (order kept)
    t_fields, trips = read_csv(os.path.join(GTFS_DIR, 'trips.txt'))
    for t in trips:        # 16. template trips to the added routes
        if t['trip_id'] in tpl_move:
            t['route_id'] = tpl_move[t['trip_id']]
    st_fields, sts = read_csv(os.path.join(GTFS_DIR, 'stop_times.txt'))
    st_of = OrderedDict()
    for r in sts:
        st_of.setdefault(r['trip_id'], []).append(r)
    tm_of = {r['gtfs_trip_id']: r for r in tm}

    # --- 4. departure-only tables -> two-stop trips
    _, dur = read_csv(DUR_TABLE)
    rule_of = {d['source_sheet']: d for d in dur}
    estimated = []
    computed_rows = {}     # (trip_id, stop_sequence) -> page and sheet of the original (for the provenance table)
    n_two = 0
    refused = []
    for t in trips:
        tid = t['trip_id']
        rows = st_of.get(tid, [])
        key = key_of.get(tid)
        if len(rows) != 1 or not key:
            continue
        srcs = sheets_of.get(key, [])
        if len(srcs) != 1 or srcs[0] not in rule_of:
            continue
        d = rule_of[srcs[0]]
        line = tm_of[tid]['line_name']
        excl = set((d.get('除くtrip_id') or '').split())
        # the key of a trip without a printed number is `U<sheet name>_<trip_id>` (e.g. Up0150_tb001-1-1_26)
        num = key.split('__')[-1]
        col = num.rsplit('_', 1)[-1] if num.startswith(f'U{srcs[0]}_') else ''
        if col in excl:
            refused.append((tid, '除くtrip_id（原本の注記で終点が違う）'))
            continue
        r0 = rows[0]
        if stop_name.get(r0['stop_id'], '').split('〈')[0] != d['始発駅'] or not r0['departure_time']:
            refused.append((tid, '始発駅が表と合わない'))
            continue
        dest = sid_of.get((d['終点駅'], line))
        if not dest:
            refused.append((tid, '終点駅の stop_id が無い'))
            continue
        t_arr = add_minutes(r0['departure_time'], int(d['所要_分']))
        rows.append({'trip_id': tid, 'arrival_time': t_arr, 'departure_time': t_arr,
                     'stop_id': dest, 'stop_sequence': str(int(r0['stop_sequence']) + 1)})
        estimated.append({'trip_id': tid, 'stop_id': dest, 'stop_name': d['終点駅'],
                          'stop_sequence': rows[-1]['stop_sequence'], 'arrival_time': t_arr,
                          'departure_time': t_arr, 'kind': 'departure_only_terminal',
                          'basis': f'始發 {r0["departure_time"][:5]}＋原本 p{d["page"]} の「{d["原本の刷り"]}」',
                          'source_sheet': srcs[0]})
        computed_rows[(tid, rows[-1]['stop_sequence'])] = {'page': d['page'], 'sheet': srcs[0],
                                                           'basis': estimated[-1]['basis']}
        n_two += 1

    # computed values already in the source feed: terminals and intermediate stops of frequency-only template trips (TQ…)
    for tid, rows in st_of.items():
        if not tid.startswith('TQ'):
            continue
        for r in rows[1:]:
            if r['arrival_time']:
                estimated.append({'trip_id': tid, 'stop_id': r['stop_id'],
                                  'stop_name': stop_name.get(r['stop_id'], ''),
                                  'stop_sequence': r['stop_sequence'],
                                  'arrival_time': r['arrival_time'], 'departure_time': r['departure_time'],
                                  'kind': 'frequency_section_template',
                                  'basis': '始発時刻＋原本の所要（途中駅は座標の距離で按分）',
                                  'source_sheet': ''})

    # --- 5. remove single-stop trips
    single = []
    keep_trips = []
    for t in trips:
        rows = st_of.get(t['trip_id'], [])
        if len(rows) >= 2:
            keep_trips.append(t)
            continue
        key = key_of.get(t['trip_id'], '')
        for r in rows:
            single.append({'trip_id': t['trip_id'], 'route_id': t['route_id'],
                           'line_name': tm_of.get(t['trip_id'], {}).get('line_name', ''),
                           'direction_id': t['direction_id'],
                           'printed_number': printed_number(t['trip_short_name']),
                           'gtfs_trip_key': key, 'stop_id': r['stop_id'],
                           'stop_name': stop_name.get(r['stop_id'], ''),
                           'stop_lat': stop_ll.get(r['stop_id'], ('', ''))[0],
                           'stop_lon': stop_ll.get(r['stop_id'], ('', ''))[1],
                           'arrival_time': r['arrival_time'], 'departure_time': r['departure_time'],
                           'source_sheet': ' '.join(sheets_of.get(key, []))})
    # --- 12. merge same-time trips of the shipping tables with printed dates (merged sailings stay in printed_sailings.csv)
    sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
    import operating_days
    merged_sailings = {}
    if MERGE_SAME_SAILINGS:
        keep_trips, merged_sailings = operating_days.collapse_same_sailings(keep_trips, st_of, key_of)
    kept = {t['trip_id'] for t in keep_trips}
    # --- 17. remove routes without trips from routes.txt and route_region.csv (they still get published IDs)
    empty_routes = []
    if DROP_EMPTY_ROUTES:
        used_routes = {t['route_id'] for t in keep_trips}
        r_fields, r_rows = read_csv(os.path.join(G, 'routes.txt'))
        empty_routes = [r for r in r_rows if r['route_id'] not in used_routes]
        if empty_routes:
            write_csv(os.path.join(G, 'routes.txt'), r_fields, [r for r in r_rows if r['route_id'] in used_routes])
            rr_path = os.path.join(X, 'route_region.csv')
            if os.path.exists(rr_path):
                rr_fields, rr_rows = read_csv(rr_path)
                rr_rows = [r for r in rr_rows if r['route_id'] in used_routes]
                write_csv(rr_path, rr_fields, rr_rows)
                n_region = len(rr_rows)

    # --- 3. trip_short_name and provenance
    source = []
    for t in keep_trips:
        orig = t['trip_short_name']
        # template trips (TF… = frequency box, TQ… = frequency-only section) are not printed trains, so no number
        # (in the source feed they carry the number of the trip used as template)
        t['trip_short_name'] = '' if t['trip_id'].startswith(('TF', 'TQ')) else printed_number(orig)
        key = key_of.get(t['trip_id'], '')
        source.append({'trip_id': t['trip_id'], 'gtfs_trip_key': key,
                       'original_trip_short_name': orig, 'printed_number': t['trip_short_name'],
                       'source_sheets': ' '.join(sheets_of.get(key, []))})

    # --- 9. provenance (transcription cell per stop, timepoint, trip number source) = scripts/release/provenance.py
    prov_st, tp, prov_n = [], {}, {}
    if PROVENANCE:
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import provenance

        def opt(name):
            p = os.path.join(GTFS_DIR, name)
            return read_csv(p)[1] if os.path.exists(p) else []
        prov_st, tp, tns_of, prov_n = provenance.build_stop_time_source(
            st_of, kept, key_of, integ, stop_name, opt('stop_time_system.csv'), opt('frequency_box.csv'),
            opt('frequency_sections.csv'), computed_rows)
        for s in source:
            s['trip_num_source'], s['trip_num_sources'] = tns_of.get(s['trip_id'], ('', ''))
        if TRIP_SOURCE_ALL_SHEETS:
            more = defaultdict(list)
            for r in prov_st:
                for f in ('arrival', 'departure'):
                    sh = r.get(f'{f}_sheet', '')
                    if r.get(f'{f}_source') == 'printed' and sh and sh not in more[r['trip_id']]:
                        more[r['trip_id']].append(sh)
            for s in source:
                have = s['source_sheets'].split()
                s['source_sheets'] = ' '.join(have + [x for x in more.get(s['trip_id'], []) if x not in have])
    write_csv(os.path.join(X, 'trip_source.csv'),
              ['trip_id', 'gtfs_trip_key', 'original_trip_short_name', 'printed_number', 'source_sheets']
              + (['trip_num_source', 'trip_num_sources'] if PROVENANCE else []),
              source)
    write_csv(os.path.join(X, 'estimated_stop_times.csv'),
              ['trip_id', 'stop_id', 'stop_name', 'stop_sequence', 'arrival_time', 'departure_time',
               'kind', 'basis', 'source_sheet'], estimated)
    write_csv(os.path.join(X, 'single_stop_trips.csv'),
              ['trip_id', 'route_id', 'line_name', 'direction_id', 'printed_number', 'gtfs_trip_key',
               'stop_id', 'stop_name', 'stop_lat', 'stop_lon', 'arrival_time', 'departure_time',
               'source_sheet'], single)
    # remove stations used only by removed trips from stops.txt (coordinates stay in single_stop_trips.csv)
    used = {r['stop_id'] for tid in kept for r in st_of[tid]}
    dropped_stops = [r['stop_name'] for r in stops if r['stop_id'] not in used]
    kept_stops = [r for r in stops if r['stop_id'] in used]

    # --- 6. transfers (group stations with the same functions and input as generate_router_data.py, not a copy)
    groups, group_of_stop, walks, n_near, transfers_key = build_station_groups()
    check_same_as_router(groups)
    # stop_id must mean the same station in the transfer input (TRANSFERS_*) and the published dataset (else transfers cannot be copied)
    here_key = {r['stop_id']: (r['stop_name'], r['line_name']) for r in sm}
    bad = [sid for sid in (r['stop_id'] for r in kept_stops) if transfers_key.get(sid) != here_key.get(sid)]
    if bad:
        raise SystemExit(f'stop_id が内部のフィードと公開版で違う駅を指している: {bad[:10]}（乗り換えを写せない）')
    child_of = defaultdict(list)                   # group -> child stop_ids kept in the published dataset
    for r in kept_stops:
        child_of[group_of_stop[r['stop_id']]].append(r['stop_id'])
    s_fields = s_fields + ['location_type', 'parent_station']
    stations = []
    no_coord = []      # groups of stations without coordinates cannot get a parent (GTFS requires parent coordinates)
    ll_of = {r['stop_id']: (r['stop_lat'], r['stop_lon']) for r in kept_stops}
    rep_child = {}     # parent -> child whose coordinate it took (for the provenance table)
    for gid in sorted(child_of):
        g = groups[gid]
        # The parent's coordinate comes from a **published child** (the group coordinate g['lat'] is not used):
        #   the group's representative (first station) if published, else the first child with a coordinate.
        order = sorted(child_of[gid], key=lambda c: (c != g.get('members', [c])[0], c))
        if PARENT_COORD_STATION:   # 31. choose children: station point -> computed position -> substitute point -> others
            order = sorted(order, key=lambda c: _parent_coord_rank(c, ll_of))   # ties keep the previous order (sorted is stable)
        rep = next((c for c in order if ll_of[c][0]), None)
        if not rep:
            no_coord.append(gid)
            continue
        rep_child[gid] = rep
        lat, lon = float(ll_of[rep][0]), float(ll_of[rep][1])
        stations.append({'stop_id': gid, 'stop_name': g['name'], 'stop_lat': f'{lat:.6f}',
                         'stop_lon': f'{lon:.6f}', 'location_type': '1', 'parent_station': ''})
    for r in kept_stops:
        r['location_type'] = '0'
        gid = group_of_stop[r['stop_id']]
        r['parent_station'] = '' if gid in no_coord else gid
    if no_coord:
        print('  ★WARN 座標の無い駅（親の駅を作れない・GTFS の規格違反になる）: '
              + '・'.join(f'{r["stop_name"]}（{r["stop_id"]}）' for r in kept_stops if not r['stop_lat']))
    write_csv(os.path.join(G, 'stops.txt'), s_fields, kept_stops + stations)
    coord_n = {}
    if PROVENANCE:     # coordinate source per station (no free-text notes from the coordinate tables; structured records only)
        coord_rows, coord_n = provenance.build_stop_coord_source(
            kept_stops, stations, {r['stop_id']: r.get('coord_source', '') for r in sm}, here_key,
            {(r['stop_name'], r['line_name']): r['stop_id'] for r in sm}, rep_child)
        write_csv(os.path.join(X, 'stop_coord_source.csv'), provenance.COORD_FIELDS,
                  [coord_rows[r['stop_id']] for r in kept_stops + stations])
    transfers = []
    for gid in sorted(child_of):                   # within a station = 0 minutes (as in the journey planner)
        ch = child_of[gid]
        for a in ch:
            for b in ch:
                if a != b:
                    transfers.append((a, b, 0))
    n_walk = 0
    for g1 in sorted(walks):                       # stations connected on foot = the journey planner's walking minutes
        for g2, mins in walks[g1]:
            if g1 in child_of and g2 in child_of:
                n_walk += 1
                for a in child_of[g1]:
                    for b in child_of[g2]:
                        transfers.append((a, b, mins * 60))
    write_csv(os.path.join(G, 'transfers.txt'),
              ['from_stop_id', 'to_stop_id', 'transfer_type', 'min_transfer_time'],
              [{'from_stop_id': a, 'to_stop_id': b, 'transfer_type': '2', 'min_transfer_time': str(t)}
               for a, b, t in transfers])

    # --- 7. through trains = extras/physical_trains.csv (not in GTFS block_id)
    #   block_id means "the same vehicle continues within one service day", and validators report overlapping times
    #   as ERROR. Through trains (1) list the same section in two trips (上野->大宮 in 東北本線 143 and 高崎線 143),
    #   (2) have later trips written in their own day's times (東海道本線 31 arrives 神戸 40:04, 山陽本線 31 departs
    #   神戸 16:10), (3) include ships, so block_id would give ERRORs. They go to a table, in trip_id order.
    trip_of_key = {key_of.get(t['trip_id'], ''): t['trip_id'] for t in keep_trips}
    pt_rows = []
    with open(PHYSICAL_TRAINS, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            tid = trip_of_key.get(r['trip_key'])
            if tid:
                pt_rows.append({'physical_train_id': r['physical_train_id'], 'seq': r['seq'], 'trip_id': tid,
                                'gtfs_trip_key': r['trip_key']})
    write_csv(os.path.join(X, 'physical_trains.csv'),
              ['physical_train_id', 'seq', 'trip_id', 'gtfs_trip_key'], pt_rows)
    n_block = len(pt_rows)
    ptid = {r['physical_train_id'] for r in pt_rows}
    # --- 13. operating-day tables (printed_sailings.csv, operating_days.csv) = scripts/release/operating_days.py
    od_counts, n_ps, n_od = {}, 0, {}
    if OPERATING_DAYS:
        def opt_rows(d, name):
            p = os.path.join(d, name)
            return read_csv(p)[1] if os.path.exists(p) else []
        ps_rows, od_rows, od_counts = operating_days.build(
            keep_trips, st_of, key_of, merged_sailings, opt_rows(INT_DIR, 'qa_log.csv'), stop_name,
            opt_rows(GTFS_DIR, 'service_frequency.csv'), opt_rows(GTFS_DIR, 'trip_attributes.csv'))
        write_csv(os.path.join(X, 'printed_sailings.csv'), operating_days.PRINTED_SAILING_FIELDS, ps_rows)
        write_csv(os.path.join(X, 'operating_days.csv'), operating_days.OPERATING_DAYS_FIELDS, od_rows)
        n_ps = len(ps_rows)
        for r in od_rows:
            n_od[r['kind']] = n_od.get(r['kind'], 0) + 1
    # --- 19. three derived tables (train type and facilities, sailing frequency, frequency source text and
    #   interpretation) = scripts/release/derived_tables.py. Written before relabeling to published IDs, so their
    #   trip_id column is relabeled too.
    dt_summary, dt_scrubbed = {}, []
    if DERIVED_TABLES:
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import derived_tables
        dt_summary, dt_scrubbed = derived_tables.build(GTFS_DIR, X, key_of, kept, {r['trip_id'] for r in single},
                                                       merged_sailings)
    # --- 20. route lines for maps (skeleton built from published coordinates) = scripts/release/route_lines.py
    rl_summary = {}
    if ROUTE_LINES_SRC:
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import route_lines
        route_lines.FILL_EMPTY = ROUTE_LINES_FILL_EMPTY                                  # 32. build shapeless line names from trips
        _rrows = read_csv(os.path.join(G, 'routes.txt'))[1]
        _line_of_route = {r['route_id']: r['route_short_name'] for r in _rrows if not r['route_id'].startswith('RQ')}
        _seqs = defaultdict(list)
        for _t in keep_trips:
            if _t['route_id'] in _line_of_route and _t['trip_id'] in st_of:
                _seqs[_line_of_route[_t['route_id']]].append(
                    [r['stop_id'] for r in sorted(st_of[_t['trip_id']], key=lambda r: int(r['stop_sequence']))])
        rl_summary = route_lines.build(ROUTE_LINES_SRC, _rrows,
                                       read_csv(os.path.join(G, 'stops.txt'))[1],
                                       os.path.join(X, 'route_lines.geojson'), trip_seqs=_seqs)
    if not SHAPES:     # no shapes.txt, so drop the shape_id column too (no column pointing to missing shapes)
        t_fields = [f for f in t_fields if f != 'shape_id']
    write_csv(os.path.join(G, 'trips.txt'), t_fields, keep_trips)
    st_rows = [r for tid, rows in st_of.items() if tid in kept for r in rows]
    if PROVENANCE:     # GTFS-standard timepoint (1 = printed time; 0 = computed time or template trip, approximate)
        for r in st_rows:
            r['timepoint'] = tp[(r['trip_id'], r['stop_sequence'])]
    write_csv(os.path.join(G, 'stop_times.txt'), st_fields + (['timepoint'] if PROVENANCE else []), st_rows)
    if PROVENANCE:
        write_csv(os.path.join(X, 'stop_time_source.csv'), provenance.STOP_TIME_FIELDS, prov_st)

    # --- 8. usage examples and README
    shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'route_1925.py'),
                    os.path.join(OUT_DIR, 'examples', 'route_1925.py'))
    # tools that build other files from the GTFS go to tools/ (examples/ holds only getting-started examples)
    if OPERATING_DAYS or ROUTER_EXAMPLE:
        os.makedirs(os.path.join(OUT_DIR, 'tools'), exist_ok=True)
    if OPERATING_DAYS:
        shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'make_printed_days_gtfs.py'),
                        os.path.join(OUT_DIR, 'tools', 'make_printed_days_gtfs.py'))
    if ROUTER_EXAMPLE:   # 29. example that builds journey-planner data from the published dataset alone
        shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'make_router_data.py'),
                        os.path.join(OUT_DIR, 'tools', 'make_router_data.py'))
    if EXAMPLES_LIBS:    # 40. gtfs-kit example and OpenTripPlanner configuration
        for rel in ('with_gtfs_kit.py', os.path.join('opentripplanner', 'build-config.json'),
                    os.path.join('opentripplanner', 'router-config.json'), os.path.join('opentripplanner', 'otp-config.json'),
                    os.path.join('opentripplanner', 'README.md'), os.path.join('opentripplanner', 'plan_with_otp.py')):
            dst = os.path.join(OUT_DIR, 'examples', rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', rel), dst)
        if README_JA:    # Japanese translation of the OpenTripPlanner README
            shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'opentripplanner', 'README.ja.md'),
                            os.path.join(OUT_DIR, 'examples', 'opentripplanner', 'README.ja.md'))
    shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'README_release.md'),
                    os.path.join(OUT_DIR, 'README.md'))
    # license (data CC BY 4.0, example scripts MIT)
    shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'LICENSE_release.txt'),
                    os.path.join(OUT_DIR, 'LICENSE'))
    if KNOWN_ISSUES:     # known issues
        shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'KNOWN_ISSUES_release.md'),
                        os.path.join(OUT_DIR, 'KNOWN_ISSUES.md'))
    if README_JA:        # Japanese README
        shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'README_release_ja.md'),
                        os.path.join(OUT_DIR, 'README.ja.md'))
    if KNOWN_ISSUES_JA:  # Japanese known issues
        shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'KNOWN_ISSUES_release_ja.md'),
                        os.path.join(OUT_DIR, 'KNOWN_ISSUES.ja.md'))
    if LICENSE_JA:       # Japanese reference translation of LICENSE
        shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'LICENSE_release_ja.md'),
                        os.path.join(OUT_DIR, 'LICENSE.ja.md'))
    if DETAILS:          # 37. detailed file description (split from the README, which keeps the essentials)
        shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'DETAILS_release.md'),
                        os.path.join(OUT_DIR, 'DETAILS.md'))
        if README_JA:
            shutil.copyfile(os.path.join(BASE_DIR, 'scripts', 'release', 'DETAILS_release_ja.md'),
                            os.path.join(OUT_DIR, 'DETAILS.ja.md'))

    # --- keep IDs stable across versions (scripts/release/stable_ids.py, using the ID registry)
    id_report = []
    if STABLE_IDS:
        id_report = relabel_stable_ids(G, X, kept_stops, here_key, groups, transfers_key, key_of, source, empty_routes,
                                       single if SINGLE_STOP_IDS else ())
        if DERIVED_TABLES:   # 19. no internal IDs left in trip_id of the derived tables
            derived_tables.check_public_ids(X)
        if ROUTE_LINES_SRC:  # 20. no internal IDs left in route_ids of the route lines
            route_lines.check_public_ids(os.path.join(X, 'route_lines.geojson'))

    # --- 33, 34. transcription and integrated layers (after relabeling, so published trip_id and stop_id are used;
    #   their CSVs are also checked in 21)
    layer_stats = {}
    if TRANSCRIPTION or INTEGRATED_LAYER:
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import package_layers
        if TRANSCRIPTION:
            layer_stats['transcription'] = package_layers.build_transcription(OUT_DIR, package_layers.feed_date(version))
        if INTEGRATED_LAYER:
            import stable_ids as _sid
            layer_stats['integrated'] = package_layers.build_integrated(OUT_DIR, INT_DIR, _sid.MAP_OUT if STABLE_IDS else None)

    # --- 35. table of cells corrected as misprints (written before the check in 21, so its reasons are checked too)
    n_misprint = 0
    if MISPRINT_TABLE:
        with open(MISPRINT_SRC, encoding='utf-8-sig', newline='') as f:
            _mr = csv.DictReader(f)
            _mf, _mrows = _mr.fieldnames, list(_mr)
        write_csv(os.path.join(X, 'misprint_corrections.csv'), _mf, _mrows)
        n_misprint = len(_mrows)

    # --- 36. station-name variants table (after relabeling, so published stop_id; written before the check in 21)
    snv_summary = {}
    if STOP_NAME_VARIANTS:
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import stop_name_variants as _snv
        import provenance as _prov
        _snv_rows, snv_summary, _snv_odd = _snv.build(G, X, _prov.TRIPNUM_DIR)
        _snv.write(X, _snv_rows)

    # --- 21. drop internal record words and ★ marks from free text of all tables and check every published file
    #   (after relabeling)
    scrub_all_changed = {}
    if SCRUB_ALL_EXTRAS:
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts', 'release'))
        import derived_tables as _dt
        scrub_all_changed = _dt.scrub_extras(X, rewrite_work=REWRITE_WORK_WORDS, rewrite_work2=REWRITE_WORK_WORDS_2,
                                             rewrite_work3=REWRITE_WORK_WORDS and REWRITE_WORK_WORDS_3)
        _dt.check_release_text(OUT_DIR, allow=[CONTACT_EMAIL], final=FINAL)
        if REWRITE_WORK_WORDS:
            _dt.check_work_words(OUT_DIR, second=REWRITE_WORK_WORDS_2, third=REWRITE_WORK_WORDS_3)

    n_blank = sum(1 for s in source if not s['printed_number'])
    n_changed = sum(1 for s in source if s['printed_number'] != s['original_trip_short_name'])
    print(f'公開用 GTFS → {OUT_DIR}（feed_version {version}）')
    if freq_long:
        print('  頻度だけの表の路線に区間名（内部の番号）: ' + '・'.join(f'{rid}＝{v}' for rid, v in sorted(freq_long.items())))
    if n_region:
        print(f'  routes.txt の region 列を extras/route_region.csv へ移した（{n_region} 路線）')
    if tpl_routes:
        print(f'  雛形便を刷られた便と別の路線へ: {len(tpl_routes)} 路線を足し {len(tpl_move)} 便を移した'
              f'（route_long_name の末尾に「{template_routes.SUFFIX}」）')
    if empty_routes:
        print('  便が 1 本も残らない路線を routes.txt から外した: ' + '・'.join(r['route_short_name'] for r in empty_routes)
              + '（single_stop_trips.csv の route_id は公開番号のまま）')
    print(f'  trips {len(trips)} → {len(keep_trips)}（停車 1 つで外した {len(trips) - len(keep_trips) - len(merged_sailings)} 本'
          f' → single_stop_trips.csv・同じ時刻の船の便をまとめた {len(merged_sailings)} 本）')
    print(f'  暦: {"全便を " + CALENDAR_START + "〜" + CALENDAR_END + " の毎日" if CALENDAR_DAILY else "内部のフィードのまま"}')
    if OPERATING_DAYS:
        print(f'  運航日の付表: printed_sailings.csv {n_ps} 行（' + '・'.join(f'{k} {v}' for k, v in sorted(od_counts.items()))
              + '）／operating_days.csv ' + '・'.join(f'{k} {v}' for k, v in sorted(n_od.items())))
    print(f'  stop_times {len(sts)} → {sum(len(st_of[t]) for t in kept)}（2 駅の便にした {n_two} 本に終点の著を 1 行ずつ）')
    print(f'  見送り {len(refused)}: ' + '・'.join(f'{a}({b})' for a, b in refused[:10]))
    print(f'  stops {len(stops)} → {len(stops) - len(dropped_stops)}（外した便でしか使っていない駅: {"・".join(dropped_stops) or "なし"}）')
    print(f'  trip_short_name を変えた {n_changed} 本（うち空欄 {n_blank}）')
    print(f'  駅のまとまり（親の駅 location_type=1）{len(stations)}・近接の併合 {n_near}・transfers.txt {len(transfers)} 行'
          f'（同じ駅の中 {len(transfers) - sum(1 for *_, t in transfers if t)}・徒歩 {n_walk} 組）')
    print(f'  通し列車の付表 physical_trains.csv: {n_block} 便（物理列車 {len(ptid)} 本）')
    print(f'  estimated_stop_times.csv {len(estimated)} 行（発時刻だけの表 {n_two}・雛形便 TQ {len(estimated) - n_two}）')
    if PROVENANCE:
        print(f'  出どころ: timepoint 1＝{prov_n.get("timepoint_1", 0)}・0＝{prov_n.get("timepoint_0", 0)}／'
              f'刷られた欄の引き当て 同じシート {prov_n.get("same_sheet", 0)}・その便の別のシート {prov_n.get("trip_sheet", 0)}・'
              f'同じ番号の別のシート {prov_n.get("same_number", 0)}・★当たらない {prov_n.get("unmatched", 0)}／'
              f'行をワークブックの順に戻した便 {prov_n.get("trips_reversed", 0)}・ワークブックと駅の並びが合わない便 {prov_n.get("trips_row_unverified", 0)}')
        print('  座標の出どころ: ' + '・'.join(f'{k} {v}' for k, v in sorted(coord_n.items())))
        if prov_n.get('unmatched'):
            print('  ★WARN 転記のセルに当たらない欄がある（stop_time_source.csv の source=unmatched）')
    if DERIVED_TABLES:
        print('  派生表: ' + '・'.join(f'{k} {v}' for k, v in dt_summary.items()))
        if dt_scrubbed:
            print(f'  派生表の自由記述から内部の記録の言葉を落とした欄 {len(dt_scrubbed)}: '
                  + '・'.join(f'{a}:{b}:{c}' for a, b, c in dt_scrubbed))
    if SCRUB_ALL_EXTRAS:
        print('  付表すべての自由記述から内部の記録の言葉と★を落とした欄: '
              + ('・'.join(f'{k} {v}' for k, v in scrub_all_changed.items()) or 'なし')
              + '（公開版の全ファイルに残りなし）')
    if ROUTE_LINES_SRC:
        print(f"  路線の線 route_lines.geojson: {rl_summary['lines']} 線名（形の無い線名 {rl_summary['empty_skipped']} は除く）・"
              f"頂点 {rl_summary['vertices']}（すべて公開版の駅の座標）"
              + (f"・路線の無い線名 {rl_summary['no_route']}" if rl_summary['no_route'] else ''))
    else:
        print('  路線の線 route_lines.geojson: 置かない（RELEASE_ROUTE_LINES が空）')
    for k, v in layer_stats.items():   # 33, 34
        print(f'  {k}/: ' + '・'.join(f'{a} {b}' for a, b in v.items()))
    if MISPRINT_TABLE:                 # 35
        print(f'  原本の誤植として直したセル misprint_corrections.csv: {n_misprint} 行')
    if STOP_NAME_VARIANTS:             # 36
        print('  驛名の別名 stop_name_variants.csv: ' + '・'.join(f'{k} {v}' for k, v in snv_summary.items()))


if __name__ == '__main__':
    main()
