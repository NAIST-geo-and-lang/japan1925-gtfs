# kb_places_env.sh — settings for assigning coordinates from the coordinate tables (data/knowledge/places/).
# Use with `source scripts/kb_places_env.sh`; run_pipeline.sh always reads it. Coordinates are looked up by scripts/agent_knowledge.py.
# The repository root is determined from the location of this file (works from any working directory).
_KB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K="$_KB_ROOT/data/knowledge"
export AGENT_KNOWN_PLACES="${AGENT_KNOWN_PLACES:-$K/places}"   # coordinate tables (same as the default of scripts/agent_knowledge.py)
# Public points near the published coordinates, read by the coordinate checks
export RELEASE_PUBLIC_POINTS="${RELEASE_PUBLIC_POINTS:-$K/public_release/public_points.csv}"
export INFER_COORDS_EXTRA_ANCHORS="${INFER_COORDS_EXTRA_ANCHORS:-release_proxy}"
export AGENT_KNOWN_STRICT="${AGENT_KNOWN_STRICT:-1}"   # stop on any lookup missing from the tables (scripts/agent_knowledge.py)
export GTFS_INHERIT_EXISTING=0   # do not carry over coordinates from a previous stops_master
# Read the tables once to check them (duplicate lookups, unknown place IDs, values outside the vocabulary),
# and check their format (UTF-8 with BOM, CRLF line endings), which would otherwise still be readable.
PYTHONDONTWRITEBYTECODE=1 python3 -c "
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'scripts'))
import agent_knowledge as a
a._tables()
bad = [n for n in ('places.csv', 'stop_place.csv', 'derived.csv', 'readings.csv')
       if os.path.exists(os.path.join(a.PLACES_DIR, n)) and (lambda r: not r.startswith(b'\\xef\\xbb\\xbf') or b'\\n' in r.replace(b'\\r\\n', b''))(open(os.path.join(a.PLACES_DIR, n), 'rb').read())]
if bad:
    sys.exit('表の形が BOM 付き UTF-8・CRLF でない: ' + '・'.join(bad))
" "$_KB_ROOT" \
  || { echo "★★ 座標KB の表（${AGENT_KNOWN_PLACES}）が食い違う" >&2; return 1 2>/dev/null || exit 1; }
if [[ "${AGENT_KNOWN_PLACES}" != "$K/places" ]]; then
  echo "★ 座標KB の表が既定（$K/places）でない＝${AGENT_KNOWN_PLACES} で作る" >&2
fi
echo "座標KB の表（${AGENT_KNOWN_PLACES}）で座標を当てる（公開できる値だけ）"
