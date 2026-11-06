#!/usr/bin/env bash
# build_release_all.sh — builds the published dataset (data/gtfs_v1_release) from the stop_times intermediate files,
# using only coordinates that can be explained by redistributable sources.
#
#   bash scripts/release/build_release_all.sh              # work folder data/gtfs_v1_release_work → dataset data/gtfs_v1_release
#   bash scripts/release/build_release_all.sh --no-check   # skip the GTFS Validator runs (step 5)
#
# Steps:
#   1. Integrate the stop_times intermediate files (data/3_stop_times_intermediate_v1) in an empty work folder.
#   2. Run run_pipeline.sh in the work folder (coordinates, line skeletons, shapes, route-search groups and walking links,
#      parent stations and transfers.txt).
#   4. Run scripts/build_release_gtfs.py on the work folder (packaging, provenance tables, stable public IDs).
#   4e. Gate: every published coordinate (including parent stations) must be explained by a redistributable source
#       (scripts/release/check_coord_allowlist.py): the same value as a public point (N02-25, Location Reference Information,
#       historical place names, Wikipedia, Wikidata, GeoNames, coordinates fetched from the cited sources), a reading of an old
#       topographic map, or an interpolation or derived value from explained anchors. Stations whose cited sources cannot be
#       checked because the reference data in data/external are missing are flagged; download them with
#       scripts/release/fetch_external_sources.py. Values checked by hand are listed in
#       data/knowledge/public_release/verified_coordinates.csv. Report only (do not stop) = RELEASE_ALLOWLIST_GATE=0.
#   4f. Build the route-search network from the published dataset (data/gtfs_v1_release_router; not part of the dataset).
#       Skip = RELEASE_ROUTER_DATA=0.
#   5. GTFS Validator on the feed and on the printed-days variant made by tools/make_printed_days_gtfs.py.
#
# Coordinates come from the coordinate tables (RELEASE_KB_PLACES_DIR, default data/knowledge/places), looked up by stop name
# and line name; a stop missing from the tables stops step 5.1 of run_pipeline.sh. The reference records for the checks are read
# from RELEASE_PUBLIC_KB_DIR (default data/knowledge/public_release). feed_version is given by RELEASE_FEED_VERSION.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
CHECK=1
for a in "$@"; do
  case "$a" in
    --no-check) CHECK=0 ;;
    *) echo "知らない引数: $a" >&2; exit 2 ;;
  esac
done

W="${RELEASE_WORK_DIR:-$ROOT/data/gtfs_v1_release_work}"
PUBKB="${RELEASE_PUBLIC_KB_DIR:-$ROOT/data/knowledge/public_release}"
REF="${RELEASE_REF_DIR:-$ROOT/data/gtfs_v1_release_ref}"
PLACES="${RELEASE_KB_PLACES_DIR:-$ROOT/data/knowledge/places}"
# Output folders: RELEASE_OUT = dataset, RELEASE_ROUTER_OUT = route-search network (4f), RELEASE_REPORT_DIR = check reports.
OUT="${RELEASE_OUT:-$ROOT/data/gtfs_v1_release}"
ROUTER_OUT="${RELEASE_ROUTER_OUT:-$ROOT/data/gtfs_v1_release_router}"
REPORT="${RELEASE_REPORT_DIR:-data/reports/$(date +%Y%m%d)_release}"
mkdir -p "$REPORT"

for f in public_points.csv id_registry/registry.csv verified_geocoder_coincidences.csv; do
  [[ -f "$PUBKB/$f" ]] || { echo "公開用の照らすための記録が無い: $PUBKB/$f" >&2; exit 1; }
done
# The coordinate tables (places, the place of each stop, derived values, map readings) are checked for consistency when read.
for f in places.csv stop_place.csv derived.csv readings.csv; do
  [[ -f "$PLACES/$f" ]] || { echo "座標KB の表が無い: $PLACES/$f" >&2; exit 1; }
done
export AGENT_KNOWN_PLACES="$PLACES"
# Stop on any lookup missing from the tables (same as scripts/kb_places_env.sh, which run_pipeline.sh reads; also applies to step 4)
export AGENT_KNOWN_STRICT="${AGENT_KNOWN_STRICT:-1}"
export RELEASE_PUBLIC_POINTS="$PUBKB/public_points.csv"
export RELEASE_LEGACY_OK_LIST="$PUBKB/verified_geocoder_coincidences.csv"
python3 -c "import sys; sys.path.insert(0, 'scripts'); import agent_knowledge as a; print(f'  座標KB の表（{a.PLACES_DIR}）＝場所 {len(a._PLACES)}・対応 {len(a.ENTRIES)}')"
# The ID registry is read from a copy ($REF/reg_public), because the reader writes its report next to the registry.
REG_SRC="${RELEASE_ID_REGISTRY_DIR:-$PUBKB/id_registry}"
mkdir -p "$REF"; rm -rf "$REF/reg_public"; cp -R "$REG_SRC" "$REF/reg_public"
export RELEASE_ID_REGISTRY_DIR="$REF/reg_public"

echo "=== 1. 統合（stop_times の中間ファイルから・作業フォルダ ${W}）==="
# Before emptying the work folder, make sure it is not an important folder (in case RELEASE_WORK_DIR is set by mistake):
#   it must not be, or contain, the repository, an output or input folder, or a folder above them (compared with
#   os.path.samefile, so neither letter case nor symbolic links make a difference), and it must hold only what this
#   script writes there.
python3 - "$W" "$ROOT" "$OUT" "$ROUTER_OUT" <<'PY' || { echo "★★ 作業フォルダ（${W}）は消してよい場所でない＝RELEASE_WORK_DIR を直す" >&2; exit 1; }
import os, sys
w, root, out, rout = sys.argv[1:5]
if not os.path.isdir(w):
    sys.exit(0)
def inside(path, folder):
    p = os.path.realpath(path)
    while True:
        try:
            if os.path.samefile(p, folder):
                return True
        except OSError:
            pass
        if os.path.dirname(p) == p:
            return False
        p = os.path.dirname(p)
keep = [root, out, rout, os.path.expanduser("~"), "/"] + \
    [os.path.join(root, "data", d) for d in ("knowledge", "tables", "distance", "external", "3_stop_times_intermediate_v1",
                                            "2_timetable_with_tripnum_v1", "1_timetable_xlsx_v1", "1_timetable_xlsx_added_v1")]
if any(os.path.exists(k) and inside(k, w) for k in keep):
    sys.exit(1)
other = sorted(set(os.listdir(w)) - {"4_integrated", "gtfs", "track_geometry", "integrate.log", "pipeline.log", ".DS_Store"})
if other:
    print(f"  作業フォルダに、この処理が書いたものでないものがある：{'・'.join(other[:5])}", file=sys.stderr)
    sys.exit(1)
PY
rm -rf "$W"; mkdir -p "$W/4_integrated" "$W/gtfs" "$W/track_geometry"
STOP_TIMES_DIR=3_stop_times_intermediate_v1 INTEGRATED_DIR="$W/4_integrated" \
  INTEGRATE_QA_LOG="$W/4_integrated/qa_log.csv" python3 scripts/integrate_stop_times.py > "$W/integrate.log" 2>&1
grep -E "統合レコード数|GTFSトリップ数|warnings" "$W/integrate.log" || true

echo "=== 2. run_pipeline（公開用の座標）==="
env INTEGRATED_DIR="$W/4_integrated" GTFS_DIR="$W/gtfs" TRACK_GEOMETRY_DIR="$W/track_geometry" \
STOP_TIMES_DIR=3_stop_times_intermediate_v1 \
RELEASE_DROP_COORDLESS=1 INFER_COORDS_EXTRA_ANCHORS=release_proxy \
  bash scripts/run_pipeline.sh > "$W/pipeline.log" 2>&1 \
  || { echo "★★ run_pipeline.sh が止まった（記録＝${W}/pipeline.log）。最後の行：" >&2; tail -n 5 "$W/pipeline.log" >&2; exit 1; }
grep -E "5\.1 |5\.7|drop_coordless" "$W/pipeline.log" | head -6 || true

echo "=== 4. 公開版を作る（作業フォルダから）==="
# Route lines (extras/route_lines.geojson) = the line skeletons of the work folder. Call with RELEASE_ROUTE_LINES= (empty) to omit them.
GTFS_DIR="$W/gtfs" INTEGRATED_DIR="$W/4_integrated" STOP_TIMES_DIR=3_stop_times_intermediate_v1 \
RELEASE_ROUTE_LINES="${RELEASE_ROUTE_LINES-$W/track_geometry/line_skeletons.geojson}" RELEASE_DIR="${RELEASE_DIR:-$OUT}" \
  python3 scripts/build_release_gtfs.py

GATE_FAIL=0
echo "=== 4e. 公開版の座標が公開できる出典で説明できるか（許すものの一覧＝関門・★が残れば最後に止める）==="
E4="$REPORT/coordinate_sources_check.csv"
# If the reference data in data/external are missing, report the stations that could not be checked instead of stopping
# (the dataset is still written). Default ON. Stop as well = RELEASE_PUBLIC_GATE_NO_SOURCES_WARN=0.
MISSING_EXT=""
for f in n02/N02-25_Station.geojson historic_gazetteer/historic_gazetteer.tsv geonames/CN.zip; do
  [[ -f "$ROOT/data/external/$f" ]] || MISSING_EXT="$MISSING_EXT $f"
done
ls "$ROOT/data/external/isj/"*.zip > /dev/null 2>&1 || MISSING_EXT="$MISSING_EXT isj/*.zip"
[[ -n "$MISSING_EXT" ]] && echo "  外の資料が無い：${MISSING_EXT# }（4e は元の記録と照らせない驛を★にする）"
if [[ "${RELEASE_ALLOWLIST_GATE:-1}" == "1" ]]; then
  python3 scripts/release/check_coord_allowlist.py "$OUT" "$W/4_integrated" "$E4" --gate || GATE_FAIL=1
else
  python3 scripts/release/check_coord_allowlist.py "$OUT" "$W/4_integrated" "$E4" || true
  echo "  （RELEASE_ALLOWLIST_GATE=0＝4e を報告だけにした）"
fi

# 4f. Route-search network from the published dataset (reads only gtfs/ and extras/ of the dataset; the dataset is not changed).
if [[ "${RELEASE_ROUTER_DATA:-1}" == "1" ]]; then
  echo "=== 4f. 公開版から経路検索のデータを作る（data/gtfs_v1_release_router・公開版の包みには入れない）==="
  python3 scripts/release/build_release_router_data.py "$OUT" --out "$ROUTER_OUT"
fi

if [[ $CHECK -eq 1 ]]; then
  echo "=== 5. 検査 ==="
  bash scripts/run_gtfs_validator.sh "$OUT/gtfs" "$REPORT" | head -1
  # 5b. The printed-days variant (services only on the days printed in the timetable), made by the dataset's tools/
  if [[ -f "$OUT/tools/make_printed_days_gtfs.py" ]]; then
    PD="$(mktemp -d)"
    python3 "$OUT/tools/make_printed_days_gtfs.py" --out "$PD" | head -1
    bash scripts/run_gtfs_validator.sh "$PD" "${REPORT}_printed_days" | head -1
    rm -rf "$PD"
  fi
fi
if [[ $GATE_FAIL -eq 1 ]]; then
  if [[ -n "$MISSING_EXT" && "${RELEASE_PUBLIC_GATE_NO_SOURCES_WARN:-1}" == "1" ]]; then
    echo "★ 4e：外の資料（${MISSING_EXT# }）が無いので、座標の出典を元の記録と照らせなかった驛がある（一覧＝${E4}）。" >&2
    echo "  公開版のファイルは書き出した。照らすには python3 scripts/release/fetch_external_sources.py で資料を取り寄せてから回し直す。" >&2
  else
    echo "★★ 4e の関門で止めた：公開できる出典で説明できない座標が残っている（一覧＝${E4}）。" >&2
    exit 1
  fi
fi
