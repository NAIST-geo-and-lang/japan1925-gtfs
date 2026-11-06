#!/bin/bash
# Reproduce the Japan1925-GTFS v1.0 dataset from its published transcription workbooks.
#
# Usage (from the repository root):
#   python3 scripts/fetch_transcription.py              # 1. place the transcription workbooks (from Zenodo)
#   python3 scripts/release/fetch_external_sources.py   # 2. (optional) public reference data for the final coordinate check
#   bash reproduce.sh                                   # 3. build; the dataset is written to data/gtfs_v1_release/
#
# Steps: extraction, then scripts/release/build_release_all.sh (integration -> GTFS generation with coordinate
# assignment -> packaging -> checks). The intermediate files go to data/3_stop_times_intermediate_v1 and
# data/gtfs_v1_release_work. To reproduce the published files byte for byte, the feed version is fixed to that of v1.0
# (RELEASE_FEED_VERSION).
set -euo pipefail
cd "$(dirname "$0")"
n=$(ls data/2_timetable_with_tripnum_v1/*.xlsx 2>/dev/null | wc -l | tr -d ' ')
if [[ "$n" != "178" ]]; then
  echo "Expected 178 workbooks in data/2_timetable_with_tripnum_v1 (found $n). Run: python3 scripts/fetch_transcription.py" >&2
  exit 1
fi
mkdir -p data/3_stop_times_intermediate_v1
files=(); while IFS= read -r f; do files+=("$(basename "$f")"); done < <(ls data/2_timetable_with_tripnum_v1/*.xlsx)
echo "== 1/2 extraction"
python3 scripts/extract_stop_times.py "${files[@]}" --input-dir data/2_timetable_with_tripnum_v1 --output-dir data/3_stop_times_intermediate_v1 > /dev/null
echo "== 2/2 integration, GTFS generation with coordinate assignment, and packaging (data/gtfs_v1_release)"
RELEASE_FINAL=1 RELEASE_FEED_VERSION="${RELEASE_FEED_VERSION:-20261026-ebd6f64c}" bash scripts/release/build_release_all.sh
