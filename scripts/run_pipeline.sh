#!/bin/bash
# run_pipeline.sh
#
# Run everything from step 3.5 (split_combined_trips) to GTFS, line skeletons and shapes
# in one go, so that disambiguate_stations cannot be skipped.
#
# Prerequisite: integrated_stop_times.csv in INTEGRATED_DIR is up to date (scripts/integrate_stop_times.py).
#               scripts/release/build_release_all.sh runs both with a work folder.
#
# Usage:
#   bash scripts/run_pipeline.sh [options]
#
# Each --no-... option turns off a step that is on by default and restores the previous
# behavior (see the comments in the case block below for all options):
#   --skip-router, --skip-aux     skip router_data (the slow final step)
#   --no-refresh-coords           do not refresh interpolated coordinates (see below)
#   --no-split-subroutes          do not split GTFS routes for line names holding separate
#                                 physical routes (transcribed line_name is never changed;
#                                 record = 4_integrated/subroute_report.csv, subroute_b_check.csv)
#   --no-unify-split              do not unify a station split into tagged/untagged names
#   --no-frequencies              do not write frequency boxes ("此間○分毎ニ運轉") to frequencies.txt
#   --no-freq-sections            do not write frequency-only sections to frequencies.txt
#   --no-freq-box-grid            do not write the small grid + frequency box table (p36 靜岡電氣鐵道線)
#   --no-freq-box-listed          do not write listed departure times of kind ③ boxes as estimated trips
#   --no-freq-box-name-variants   frequency boxes: compare station names exactly (no old/new character forms)
#   --no-infer-name-variants      interpolation: look up mileage by exact station names
#   --no-freq-box-anchor-origin   frequency boxes: do not anchor the window at the template trip's first station
#   --no-freq-branch-join         frequency-only sections: cut from the main-line order only
#   --no-group-near               journey planner: no proximity merging of station groups
#   --no-est-same-group-collapse  journey planner: do not collapse consecutive same-group stops of template trips
#   --no-exact-search             journey planner: previous boarding candidates and labels
#   --no-prev-day-boarding        journey planner: do not board trips that started the previous day
#   --no-tie-fewer-transfers      journey planner: no tie-break by fewer transfers
#   --no-same-name-split          journey planner: do not split same-name stations > 300 m apart
#   --no-same-name-split-proxy    journey planner: do not split same-name stations with proxy coordinates
#   --no-ship-by-route-type       service_frequency.csv: select ships by line-name words only
#   --no-ship-freq-strict         service_frequency.csv: previous handling of suspension notes
#   --no-ship-date-grid-words     service_frequency.csv: previous detection of date-grid tables
#   --no-near-same-name-guard     journey planner: proximity merging may rejoin split same-name stations
#   --no-walk-labels-separate     journey planner: walk and train arrivals share one label table
#   --allow-revisit               journey planner: allow revisiting stations already used
#   --no-a08-actions              do not apply data/tables/arrival_departure_rows/actions.csv
#   --no-a08-merge                do not merge 著 (arrival) / 發 (departure) rows into one stop
#   --no-a08-multi-drop           do not apply both drop_before and drop_after to one trip
#   --no-single-line-band         always split combined-line bands at the boundary station
#   --no-boundary-additions       do not add 福知山線及山陰本線 / 函館、根室本線 to the split table
#   --no-rebase-late-start        do not shift cut trips to start before 24:00 (SPLIT_REBASE_LATE_START=0)
#   --no-fill-from-partner        do not fill boundary fields from the partner trip (GTFS_FILL_FROM_PARTNER=0)
#   --no-keep-unprinted-boundary  split 支那國有鐵道隴海及汴洛線 at 鄭州 (SPLIT_KEEP_UNPRINTED_BOUNDARY=0)
#   --no-cd-table-from-input      count dedicated tables after splitting (SPLIT_CD_TABLE_FROM_INPUT=0)
#   --no-contained-dedup          do not drop fully contained duplicate trips
#   --no-island-tag               do not tag island stations (〈嚴島〉)
#   --no-region-classify-1925     do not use 1925 line names for region classification
#   --no-tag-region-fix           do not align 〈region〉 tags with station locations
#   --no-contained-dedup-multi    do not drop bands contained across several trips / same-place stations
#   --no-extend-existing          do not extend existing short trips with split band parts
#   --no-lone-anchor-last         interpolation: average single-anchor guesses with other estimates
#
# Refreshing interpolated coordinates (default ON): if generate_gtfs inherits coordinates
#   from an existing stops_master (GTFS_INHERIT_EXISTING=1), infer_coords fills only empty
#   stations, so old interpolated values would never be updated. Only inferred /
#   legacy:inferred values are cleared; authority coordinates do not move
#   (scripts/refresh_inferred_coords.py). Previous behavior: --no-refresh-coords.
#
# any step that fails halts the pipeline (set -e).
set -euo pipefail

# Move to the project root (works from any directory)
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SKIP_AUX=0
WALK_EDGES=1              # walking links in the journey planner (ROUTER_WALK_EDGES; previous behavior: --no-walk-edges)
NEAR_TRIP_GUARD=1         # chaining guard for proximity merging (ROUTER_GROUP_NEAR_TRIP_GUARD; previous behavior: --no-group-near-trip-guard)
DATA_META=1               # write meta to router_data (ROUTER_DATA_META; previous behavior: --no-data-meta)
FREQ_SEC_INTERP=1         # estimated times between the ends of frequency-only template trips (GTFS_FREQ_SECTION_INTERP; previous behavior: --no-freq-section-interp)
REFRESH_COORDS=1          # refresh interpolated coordinates (default ON; previous behavior: --no-refresh-coords)
# Coordinates come from the coordinate tables: scripts/kb_places_env.sh is sourced, and each
#   (station name, line name) is looked up in data/knowledge/places/ (publishable values only) via the
#   stop-place table; the place value and its source are written to stops_master.
for arg in "$@"; do
  case "$arg" in
    --skip-router|--skip-aux) SKIP_AUX=1 ;;
    --walk-edges) WALK_EDGES=1 ;;                    # same as default
    --no-walk-edges) WALK_EDGES=0 ;;                 # switch: no walking links (previous behavior)
    --group-near-trip-guard) NEAR_TRIP_GUARD=1 ;;       # same as default
    --no-group-near-trip-guard) NEAR_TRIP_GUARD=0 ;;    # switch: allow chains (previous behavior)
    --data-meta) DATA_META=1 ;;                      # same as default
    --no-data-meta) DATA_META=0 ;;                   # switch: no meta (previous behavior)
    --freq-section-interp) FREQ_SEC_INTERP=1 ;;      # same as default
    --no-freq-section-interp) FREQ_SEC_INTERP=0 ;;   # switch: stations between the ends stay blank (previous behavior)
    --refresh-coords) REFRESH_COORDS=1 ;;      # same as default (kept for compatibility)
    --no-refresh-coords) REFRESH_COORDS=0 ;;   # switch
    # Split GTFS routes for line names holding separate physical routes (line_name unchanged; default ON)
    --split-subroutes) export GTFS_SPLIT_SUBROUTES=1 ;;      # same as default
    --no-split-subroutes) export GTFS_SPLIT_SUBROUTES=0 ;;   # switch
    # When folding a combined line name into one line, do not fold if a station exists only on the other line (default ON)
    --reclassify-guard) export SPLIT_RECLASSIFY_GUARD=1 ;;      # same as default
    --no-reclassify-guard) export SPLIT_RECLASSIFY_GUARD=0 ;;   # switch
    # Before dropping a duplicate listing, check for times found only in that band (default ON)
    --dedup-keep-unique) export SPLIT_DEDUP_KEEP_UNIQUE=1 ;;      # same as default
    --no-dedup-keep-unique) export SPLIT_DEDUP_KEEP_UNIQUE=0 ;;   # switch
    # Write 著/發 printed only in combined-line bands into blank fields of the component line's trip with the same number (default ON)
    --combined-fill-blanks) export INTEGRATE_COMBINED_FILL_BLANKS=1 ;;     # same as default
    --no-combined-fill-blanks) export INTEGRATE_COMBINED_FILL_BLANKS=0 ;;  # switch (previous behavior: band values not written)
    # Weave times found only in an omitted band into blank fields of an existing trip (default ON)
    --merge-unique-times) export SPLIT_MERGE_UNIQUE_TIMES=1 ;;      # same as default
    --no-merge-unique-times) export SPLIT_MERGE_UNIQUE_TIMES=0 ;;   # switch
    # Combined-line bands whose two parts run in opposite directions: set the direction per component (default ON)
    --part-direction) export SPLIT_PART_DIRECTION=1 ;;              # same as default
    --no-part-direction) export SPLIT_PART_DIRECTION=0 ;;           # switch
    # Bands without a matching detailed trip: reverse if the line's station order (same measure as
    # scripts/detectors/detect_band_orientation.py) shows the direction is reversed (default ON)
    --part-direction-order) export SPLIT_PART_DIRECTION_ORDER=1 ;;      # same as default
    --no-part-direction-order) export SPLIT_PART_DIRECTION_ORDER=0 ;;   # switch
    # Unify one station split into tagged/untagged names (白石 / 白石〈北海道〉)
    # after checking in the coordinate tables that both are the same place (default ON)
    --unify-split) export DISAMBIG_UNIFY_SPLIT=1 ;;                 # same as default
    --no-unify-split) export DISAMBIG_UNIFY_SPLIT=0 ;;              # switch (previous behavior: not unified)
    # Old rule splitting 川口 on 東北本線 with a 〈岩手〉 tag (the current rule is empty)
    --same-line-split-legacy) export DISAMBIG_SAME_LINE_SPLIT_LEGACY=1 ;;   # previous behavior
    # Write frequency boxes ("此間○分毎ニ運轉") to frequencies.txt (+ template trips TF...)
    # (default ON; the derived table frequency_box.csv of step 3.8 is always built)
    --frequencies) export GTFS_FREQUENCIES=1 ;;               # same as default
    --no-frequencies) export GTFS_FREQUENCIES=0 ;;            # switch (previous behavior: no boxes, the 6 GTFS files unchanged)
    # Write frequency-only sections to frequencies.txt (+ routes RQ..., stops SQ..., template trips TQ...)
    # (default ON; the derived table frequency_sections.csv of step 3.9 is always built)
    --freq-sections) export GTFS_FREQ_SECTIONS=1 ;;           # same as default
    --no-freq-sections) export GTFS_FREQ_SECTIONS=0 ;;        # switch (previous behavior: no frequency-only sections)
    # Also write the table of a small printed grid (first, change-over, last trips) + frequency box (p36 靜岡電氣鐵道線)
    # as sections (default ON; build_frequency_sections.py)
    --freq-box-grid) export FREQ_SECTIONS_BOX_GRID=1 ;;       # same as default
    --no-freq-box-grid) export FREQ_SECTIONS_BOX_GRID=0 ;;    # switch (previous behavior: not written)
    --freq-box-listed) export FREQ_BOX_LISTED=1 ;;            # same as default
    --no-freq-box-listed) export FREQ_BOX_LISTED=0 ;;         # switch (previous behavior: listed times of kind ③ not written)
    --freq-box-name-variants) export FREQ_BOX_NAME_VARIANTS=1 ;;   # same as default
    --no-freq-box-name-variants) export FREQ_BOX_NAME_VARIANTS=0 ;; # switch (previous behavior: exact station names in frequency boxes)
    --infer-name-variants) export INFER_COORDS_NAME_VARIANTS=1 ;;  # same as default
    --no-infer-name-variants) export INFER_COORDS_NAME_VARIANTS=0 ;; # switch (previous behavior: mileage looked up by exact station names)
    --freq-box-anchor-origin) export FREQ_BOX_ANCHOR_ORIGIN=1 ;;      # same as default
    --no-freq-box-anchor-origin) export FREQ_BOX_ANCHOR_ORIGIN=0 ;;   # switch (previous behavior: first row of the station column)
    --freq-sections-estimate) export FREQ_SECTIONS_ESTIMATE=1 ;;      # same as default
    --no-freq-sections-estimate) export FREQ_SECTIONS_ESTIMATE=0 ;;   # switch (previous behavior: no estimates for unprinted values)
    --freq-sections-estimate-replace) export FREQ_SECTIONS_ESTIMATE_REPLACE=1 ;;      # same as default
    --no-freq-sections-estimate-replace) export FREQ_SECTIONS_ESTIMATE_REPLACE=0 ;;   # switch (previous behavior: inconsistent printed running times, e.g. p93 阪堺線 FQ055 "約 6 分", kept as printed)
    # Lines whose station column is printed as 「本線：…／支線：…」 (main line / branch): join at the junction
    # when a section enters the branch (default ON; build_frequency_sections.py)
    --freq-branch-join) export FREQ_SECTIONS_BRANCH_JOIN=1 ;;     # same as default
    --no-freq-branch-join) export FREQ_SECTIONS_BRANCH_JOIN=0 ;;  # switch (previous behavior: cut from the main-line order)
    # Separate 著/發 rows that are different trains in the original (＊ or another column): drop or split
    # them as listed (default ON; split_combined_trips.py, data/tables/arrival_departure_rows/actions.csv)
    --a08-actions) export SPLIT_A08_ACTIONS=1 ;;              # same as default
    --no-a08-actions) export SPLIT_A08_ACTIONS=0 ;;           # switch (previous behavior: actions not applied)
    # Apply both drop_before and drop_after when both exist for one trip (e.g. p182 安奉線: the Korean
    # rows at the top and the part beyond 奉天; default ON; split_combined_trips.py)
    --a08-multi-drop) export SPLIT_A08_MULTI_DROP=1 ;;        # same as default
    --no-a08-multi-drop) export SPLIT_A08_MULTI_DROP=0 ;;     # switch (previous behavior: skip trips with two or more actions)
    # Merge the remaining separate 著/發 rows (pairs judged mergeable) into one stop
    # (default ON; split_combined_trips.py, data/tables/arrival_departure_rows/merges.csv)
    --a08-merge) export SPLIT_A08_MERGE=1 ;;                  # same as default
    --no-a08-merge) export SPLIT_A08_MERGE=0 ;;               # switch (previous behavior: two rows)
    # Line-name cell spanning several bands: a combined-line band whose stations are all on one line is assigned
    # to that line instead of being split at the boundary (default ON; split_combined_trips.py; transcription unchanged)
    --single-line-band) export SPLIT_SINGLE_LINE_BAND=1 ;;      # same as default
    --no-single-line-band) export SPLIT_SINGLE_LINE_BAND=0 ;;   # switch (previous behavior: always split at the boundary station)
    # Add two combined line names missing from BOUNDARY_STATIONS that split at one station
    # (福知山線及山陰本線 = 福知山, 函館、根室本線 = 瀧川; default ON; split_combined_trips.py)
    --boundary-additions) export SPLIT_BOUNDARY_ADDITIONS=1 ;;      # same as default
    --no-boundary-additions) export SPLIT_BOUNDARY_ADDITIONS=0 ;;   # switch (previous behavior: not added)
    # Trips whose front part was cut (band split, 著/發 actions, renumbering table) are shifted so they start
    # between 0:00 and 23:59 local time (default ON; split_combined_trips.py; report action=rebase_late_start)
    --rebase-late-start) export SPLIT_REBASE_LATE_START=1 ;;      # same as default
    --no-rebase-late-start) export SPLIT_REBASE_LATE_START=0 ;;   # switch (previous behavior)
    # At boundary stations of trips of the same through train, fill the field GTFS would copy with the
    # partner trip's printed value (default ON; generate_gtfs.py; GTFS only; report = INTEGRATED_DIR/partner_fill_report.csv)
    --fill-from-partner) export GTFS_FILL_FROM_PARTNER=1 ;;      # same as default
    --no-fill-from-partner) export GTFS_FILL_FROM_PARTNER=0 ;;   # switch (previous behavior)
    # Keep a combined line name whose boundary is not printed (支那國有鐵道隴海及汴洛線) as one trip
    # (default ON; split_combined_trips.py)
    --keep-unprinted-boundary) export SPLIT_KEEP_UNPRINTED_BOUNDARY=1 ;;      # same as default
    --no-keep-unprinted-boundary) export SPLIT_KEEP_UNPRINTED_BOUNDARY=0 ;;   # switch (previous behavior: split at 鄭州)
    # Decide "dedicated table" in the deduplication step from the transcription before splitting
    # (default ON; split_combined_trips.py)
    --cd-table-from-input) export SPLIT_CD_TABLE_FROM_INPUT=1 ;;          # same as default
    --no-cd-table-from-input) export SPLIT_CD_TABLE_FROM_INPUT=0 ;;       # switch (previous behavior: counted from trips left after splitting)
    # Drop fully contained duplicate trips: unnumbered bands (all in one numbered trip of the same line, or in
    # the two trips of a connection guide) and same-number trips under another line name (generic names of
    # connection tables vs. dedicated tables), when every (station, field, time) is in a kept trip
    # (default ON; split_combined_trips.py)
    --contained-dedup) export SPLIT_CONTAINED_DEDUP=1 ;;        # same as default
    --no-contained-dedup) export SPLIT_CONTAINED_DEDUP=0 ;;     # switch (previous behavior: kept)
    # Tag same-name island stations (宮島 on 大阪商船) with 〈嚴島〉 to separate them from mainland stations
    # (default ON; disambiguate_stations.py)
    --island-tag) export DISAMBIG_ISLAND_TAG=1 ;;        # same as default
    --no-island-tag) export DISAMBIG_ISLAND_TAG=0 ;;     # switch (previous behavior: island port and mainland station merged)
    # Add 1925 line names to the region classification / align 〈region〉 tags with station locations (both default ON;
    # disambiguate_stations.py, generate_gtfs.py, build_gtfs_extras.py)
    --region-classify-1925) export REGION_CLASSIFY_1925=1 ;;       # same as default
    --no-region-classify-1925) export REGION_CLASSIFY_1925=0 ;;    # switch (previous behavior)
    --tag-region-fix) export DISAMBIG_TAG_REGION_FIX=1 ;;          # same as default
    --no-tag-region-fix) export DISAMBIG_TAG_REGION_FIX=0 ;;       # switch (previous behavior)
    # Drop bands contained across same-number trips of other lines, or via same-place stations with other names
    # (default ON; split_combined_trips.py)
    --contained-dedup-multi) export SPLIT_CONTAINED_DEDUP_MULTI=1 ;;      # same as default
    --no-contained-dedup-multi) export SPLIT_CONTAINED_DEDUP_MULTI=0 ;;   # switch (previous behavior: second listing of the same train kept)
    # When a split band part fully contains an existing short trip with the same number and direction, extend that trip
    # (default ON; split_combined_trips.py)
    --extend-existing) export SPLIT_EXTEND_EXISTING=1 ;;        # same as default
    --no-extend-existing) export SPLIT_EXTEND_EXISTING=0 ;;     # switch (previous behavior: band kept under the combined name)
    # Interpolation: guesses from single-anchor trips (0.005-degree offsets) are used only for stations
    # no other trip can estimate (default ON; infer_coords.py)
    --lone-anchor-last) export INFER_COORDS_LONE_ANCHOR_LAST=1 ;;     # same as default
    --no-lone-anchor-last) export INFER_COORDS_LONE_ANCHOR_LAST=0 ;;  # switch (previous behavior: averaged with equal weight)
    # Merge station groups with different names but close coordinates (ROUTER_GROUP_NEAR_M, default 50 m)
    # (default ON; generate_router_data.py; not adjacent stops of one line, not coordinates outside the tables)
    --group-near) export ROUTER_GROUP_NEAR=1 ;;               # same as default
    --no-group-near) export ROUTER_GROUP_NEAR=0 ;;            # switch (previous behavior: same names only)
    # Collapse consecutive same-group stops of template trips into one stop
    # (default ON; generate_router_data.py)
    --est-same-group-collapse) export ROUTER_EST_SAME_GROUP_COLLAPSE=1 ;;      # same as default
    --no-est-same-group-collapse) export ROUTER_EST_SAME_GROUP_COLLAPSE=0 ;;   # switch (previous behavior: not collapsed)
    # Journey planner boarding candidates and labels (keep overtaking trains; no lost routes at the transfer limit)
    # (default ON; generate_router_data.py writes a flag to router_data for the search core)
    --exact-search) export ROUTER_EXACT_SEARCH=1 ;;      # same as default
    --no-exact-search) export ROUTER_EXACT_SEARCH=0 ;;   # switch (previous behavior)
    # Also board today's part of trips that started the previous day, and keep labels continuing on the same through train
    # (default ON; flag in router_data)
    --prev-day-boarding) export ROUTER_PREV_DAY_BOARDING=1 ;;      # same as default
    --no-prev-day-boarding) export ROUTER_PREV_DAY_BOARDING=0 ;;   # switch (previous behavior: boarding times shift forward only, no dayShift)
    # Among routes arriving at the same time, take the one with fewer transfers
    # (default ON; flag in router_data)
    --tie-fewer-transfers) export ROUTER_TIE_FEWER_TRANSFERS=1 ;;      # same as default
    --no-tie-fewer-transfers) export ROUTER_TIE_FEWER_TRANSFERS=0 ;;   # switch (previous behavior: first found wins)
    # Do not merge same-name stations far apart (> 300 m with reliable coordinates; joined by walks up to 5 km)
    # (default ON; generate_router_data.py; the published parent stations and transfers use the same function)
    --same-name-split) export ROUTER_GROUP_SAME_NAME_SPLIT=1 ;;      # same as default
    --no-same-name-split) export ROUTER_GROUP_SAME_NAME_SPLIT=0 ;;   # switch (previous behavior: same name within 5 km = one station)
    --same-name-split-proxy) export ROUTER_GROUP_SAME_NAME_SPLIT_PROXY=1 ;;      # same as default
    --no-same-name-split-proxy) export ROUTER_GROUP_SAME_NAME_SPLIT_PROXY=0 ;;   # switch (previous behavior: authority pairs only)
    --ship-by-route-type) export EXTRAS_SHIP_BY_ROUTE_TYPE=1 ;;      # same as default
    --no-ship-by-route-type) export EXTRAS_SHIP_BY_ROUTE_TYPE=0 ;;   # switch (previous behavior: ships chosen by line-name words only)
    --ship-freq-strict) export EXTRAS_SHIP_FREQ_STRICT=1 ;;      # same as default
    --no-ship-freq-strict) export EXTRAS_SHIP_FREQ_STRICT=0 ;;   # switch (previous behavior: suspension notes from the whole note; "毎月" in provisos also classifies)
    --ship-date-grid-words) export EXTRAS_SHIP_DATE_GRID_WORDS=1 ;;      # same as default
    --no-ship-date-grid-words) export EXTRAS_SHIP_DATE_GRID_WORDS=0 ;;   # switch (previous behavior: only the words 「型B」「マス目が月日」 in the notes)
    --near-same-name-guard) export ROUTER_GROUP_NEAR_SAME_NAME_GUARD=1 ;;      # same as default
    --no-near-same-name-guard) export ROUTER_GROUP_NEAR_SAME_NAME_GUARD=0 ;;   # switch (previous behavior: names ignored, first group created)
    # Keep walk arrivals separate from train arrivals (so an early walk arrival does not hide a later train arrival)
    # (default ON; flag in router_data)
    --walk-labels-separate) export ROUTER_WALK_LABELS_SEPARATE=1 ;;      # same as default
    --no-walk-labels-separate) export ROUTER_WALK_LABELS_SEPARATE=0 ;;   # switch (previous behavior: one label table)
    # Do not revisit stations already used in the journey
    # (default ON; flag in router_data)
    --no-revisit) export ROUTER_NO_REVISIT=1 ;;          # same as default
    --allow-revisit) export ROUTER_NO_REVISIT=0 ;;       # switch (previous behavior: revisits allowed)
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

source scripts/kb_places_env.sh || { echo '★★ 座標KB の表の検査で止めた（scripts/kb_places_env.sh）' >&2; exit 1; }

run() {
  echo
  echo "=== $1 ==="
  shift
  "$@"
}

# Step 3 post-processing: split combined trips -> add 〈region〉 tags
run "3.5 split_combined_trips"     python3 scripts/split_combined_trips.py
run "3.6 disambiguate_stations"    python3 scripts/disambiguate_stations.py

# 3.8 Derived table of frequency boxes (transcription unchanged; affects GTFS only with GTFS_FREQUENCIES=1 in step 4)
if [[ -f scripts/build_frequency_box.py ]]; then
  run "3.8 build_frequency_box"      python3 scripts/build_frequency_box.py
fi

# 3.9 Derived table of frequency-only sections (transcription unchanged; affects GTFS only with GTFS_FREQ_SECTIONS=1 in step 4)
if [[ -f scripts/build_frequency_sections.py ]]; then
  run "3.9 build_frequency_sections" python3 scripts/build_frequency_sections.py
fi

# Refresh interpolated coordinates (default ON; off with --no-refresh-coords).
# Must run before generate_gtfs, which can inherit coordinates from an existing stops_master.
if [[ $REFRESH_COORDS -eq 1 ]]; then
  run "3.7 refresh_inferred_coords" python3 scripts/refresh_inferred_coords.py
fi

# Step 4: GTFS
run "4   generate_gtfs"            env GTFS_FREQ_SECTION_INTERP="$FREQ_SEC_INTERP" python3 scripts/generate_gtfs.py

# Step 5: coordinates
# 5.1 = apply coordinates from the coordinate tables; coord_source follows the stop-place table.
run "5.1 apply_agent_knowledge"    python3 scripts/apply_agent_knowledge.py
run "5.2 infer_coords"             env INFER_COORDS_RELIABLE_ONLY=1 python3 scripts/infer_coords.py
run "5.3 check_on_land"            python3 scripts/check_on_land.py
run "5.6 sync_gtfs_stop_coords"    python3 scripts/sync_gtfs_stop_coords.py
# For the published dataset (CC BY 4.0): drop stops without coordinates from GTFS (stops without times and
# stops between the ends of frequency-only sections; a section without end coordinates is dropped whole;
# timed stops of regular trips are listed, not dropped). Only when RELEASE_DROP_COORDLESS=1.
if [[ "${RELEASE_DROP_COORDLESS:-0}" == "1" ]]; then
  run "5.7 drop_coordless_stops"    python3 scripts/drop_coordless_stops.py
fi

# Step 6: line skeletons and GTFS shapes
run "6.1 build_line_skeleton"      python3 scripts/build_line_skeleton.py
run "6.2 generate_shapes"          python3 scripts/generate_shapes.py
# 6.5 Derived tables (the 6 GTFS files unchanged): train types, service frequency, route -> region, frequency-only sections
if [[ -f scripts/build_gtfs_extras.py ]]; then
  run "6.5 build_gtfs_extras"        python3 scripts/build_gtfs_extras.py
fi

if [[ $SKIP_AUX -eq 0 ]]; then
  if [[ -f scripts/generate_router_data.py ]]; then
    run "7.2 generate_router_data" env ROUTER_WALK_EDGES="$WALK_EDGES" ROUTER_DATA_META="$DATA_META" ROUTER_GROUP_NEAR_TRIP_GUARD="$NEAR_TRIP_GUARD" python3 scripts/generate_router_data.py
  fi
fi

echo
echo "=== Pipeline 完了 ==="
