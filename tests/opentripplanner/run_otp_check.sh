#!/usr/bin/env bash
# Loads the published GTFS feed into OpenTripPlanner (OTP) and compares its itineraries with the dataset's example
# journey planner examples/route_1925.py.
#
#   bash tests/opentripplanner/run_otp_check.sh [RELEASE_DIR] [OUT_DIR]
#     RELEASE_DIR default = data/gtfs_v1_release (the dataset folder with gtfs/, extras/ and examples/)
#     OUT_DIR     default = data/reports/opentripplanner_<YYYYMMDD>
#
# - The OTP jar (shaded) and Java 25 (Eclipse Temurin 25.0.4.1+1) are kept in data/external/otp/ and downloaded when
#   missing. Downloads are checked against the SHA-256 values below before use, and the cached jar on every run.
#   Java is unpacked into a temporary folder and renamed only when complete, and its version is checked before use.
#   To use copies you already have, pass OTP_JAR and OTP_JAVA (used as they are). OTP version = OTP_VERSION
#   (default 2.10.0; OTP_JAR_SHA256 is read only for another version: pass the SHA-256 of that version's jar).
# - The dataset is only read; a copy is modified in a work folder (OTP_WORK_DIR, default a new temporary folder,
#   which is kept after the run so that the inputs and logs can be inspected). A folder named release in the work
#   folder is replaced only if it is a copy made by an earlier run.
# - The servers listen only on this computer (127.0.0.1), on 5 ports from OTP_PORT_BASE (default 18090), up to 4 at
#   a time with up to 4 GB of memory each, and are stopped at the end.
# - Steps: (1) copy the dataset and record its md5 (2) make 6 inputs (make_otp_inputs.py) (3) build the graphs
#   (4) query Tokyo→Shimonoseki and Tokyo→Keijō on the copy with a one-day calendar
#   (5) compare 320 searches with the example planner on the 4 April copies (compare_otp.py)
#   (6) label the causes of the differences (classify.py)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
REL="${1:-$ROOT/data/gtfs_v1_release}"
OUT="${2:-$ROOT/data/reports/opentripplanner_$(date +%Y%m%d)}"
VER="${OTP_VERSION:-2.10.0}"
CACHE="$ROOT/data/external/otp"
BASE="${OTP_PORT_BASE:-18090}"
mkdir -p "$CACHE" "$OUT"

# SHA-256 of otp-shaded-2.10.0.jar (the .sha256 file published next to the jar on Maven Central)
OTP_JAR_SHA256_2_10_0=5a5d1efd30b19295418ac49ad048c5f5cac341af63dd41d5e2ae5ad9e7b37885
JDK_RELEASE=jdk-25.0.4.1+1
JDK_VERSION=25.0.4.1
sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
fetch_checked() {  # $1=URL $2=file $3=SHA-256: download to a temporary name, check it, then rename
  curl -fsSL -o "$2.part" "$1"
  [ "$(sha256_of "$2.part")" = "$3" ] || { echo "ダウンロードしたファイルの SHA-256 が合わない（使わない）: $1"; exit 1; }
  mv "$2.part" "$2"
}
unpack_jdk() {  # $1=checked tar.gz $2=JDK folder: unpack into a temporary folder, then rename (no half-unpacked JDK_HOME)
  local tmp
  tmp="$(mktemp -d "$CACHE/unpack.XXXXXX")"
  tar xzf "$1" -C "$tmp"
  mv "$tmp/$(basename "$2")" "$2"
  rmdir "$tmp"
  rm -f "$1"
}

JAR="${OTP_JAR:-}"
if [ -z "$JAR" ]; then
  JAR="$CACHE/otp-shaded-$VER.jar"
  want="${OTP_JAR_SHA256:-}"
  if [ "$VER" = "2.10.0" ]; then want="$OTP_JAR_SHA256_2_10_0"; fi   # the fixed value always applies to the default version
  [ -n "$want" ] || { echo "OTP $VER の jar の SHA-256 を OTP_JAR_SHA256 で渡す"; exit 1; }
  [ -f "$JAR" ] || fetch_checked "https://repo1.maven.org/maven2/org/opentripplanner/otp-shaded/$VER/otp-shaded-$VER.jar" "$JAR" "$want"
  [ "$(sha256_of "$JAR")" = "$want" ] || { echo "jar の SHA-256 が合わない（消してから回し直す）: $JAR"; exit 1; }
fi
JAVA="${OTP_JAVA:-}"
if [ -z "$JAVA" ]; then
  arch="$(uname -m)"; [ "$arch" = "arm64" ] && arch=aarch64; [ "$arch" = "x86_64" ] && arch=x64
  case "$(uname -s)" in Darwin) os=mac ;; Linux) os=linux ;; *) os="$(uname -s)" ;; esac
  case "$os-$arch" in   # SHA-256 of OpenJDK25U-jdk_<arch>_<os>_hotspot_25.0.4.1_1.tar.gz (Adoptium)
    mac-aarch64)   sum=61979887f7506a24a57439ff99adb8b3a7fc89977d9cfe3b8984f58a981b7b9d ;;
    mac-x64)       sum=e6229d9504f7922053ab31821b9e6bee8761daf7b026a3476d1a027563009880 ;;
    linux-aarch64) sum=69df11a02cfa3ef7d7ca645e03edce6778ec090e100f6ae2b42097865730ac52 ;;
    linux-x64)     sum=dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e ;;
    *) echo "この環境（$os $arch）の Java 25 は自動で用意できない＝OTP_JAVA で渡す"; exit 1 ;;
  esac
  JDK_HOME="$CACHE/$JDK_RELEASE"
  if [ ! -d "$JDK_HOME" ]; then
    tgz="$CACHE/OpenJDK25U-jdk_${arch}_${os}_hotspot_25.0.4.1_1.tar.gz"
    fetch_checked "https://github.com/adoptium/temurin25-binaries/releases/download/${JDK_RELEASE/+/%2B}/$(basename "$tgz")" "$tgz" "$sum"
    unpack_jdk "$tgz" "$JDK_HOME"
  fi
  JAVA="$JDK_HOME/bin/java"
  if [ "$os" = "mac" ]; then JAVA="$JDK_HOME/Contents/Home/bin/java"; fi
  java_version="$("$JAVA" -version 2>&1 || true)"
  case "$java_version" in
    *"\"$JDK_VERSION\""*) ;;
    *) echo "Java $JDK_VERSION が使えない（$JDK_HOME を消してから回し直す）"; exit 1 ;;
  esac
fi

WORK="${OTP_WORK_DIR:-$(mktemp -d)}"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

# (1) Copy of the dataset and its fingerprint. An existing release folder is replaced only if it is a copy made by an
#     earlier run (it has gtfs/feed_info.txt), so that a mistaken OTP_WORK_DIR removes nothing else.
if [ -e "$WORK/release" ] && [ ! -f "$WORK/release/gtfs/feed_info.txt" ]; then
  echo "作業フォルダの release は前の回の写しでない（消さずに止めた）: $WORK/release"; exit 1
fi
rm -rf "$WORK/release" && mkdir -p "$WORK/release"
cp -Rp "$REL/gtfs" "$REL/extras" "$REL/examples" "$WORK/release/"
{
  echo "公開版: $REL"
  echo "feed_version: $(sed -n 2p "$WORK/release/gtfs/feed_info.txt" | awk -F, '{print $6}')"
  echo "OTP: $("$JAVA" -jar "$JAR" --version 2>/dev/null | grep -m1 'Version' || true)"
  echo "Java: $("$JAVA" -version 2>&1 | head -1)"
  (cd "$WORK/release/gtfs" && md5 -r *.txt 2>/dev/null || md5sum *.txt)
} > "$OUT/input_fingerprint.txt"

# (2) Six inputs
python3 "$HERE/make_otp_inputs.py" "$WORK/release" "$WORK/in"
VARIANTS=(asis_defaults april_defaults april_aligned april_aligned_split april_aligned_split_exact)

# (3) Build the graphs (summaries of the build reports go to OUT). The input with all defaults is expected to fail;
#     the lines giving the reason are kept.
"$JAVA" -Xmx4G -jar "$JAR" --build --save "$WORK/in/pure_defaults" > "$WORK/in/pure_defaults/build.log" 2>&1 || true
grep -E "Limiting transit service|removed\. Reason|OtpAppException" "$WORK/in/pure_defaults/build.log" \
  | sed -E 's/^[0-9:.]+ [A-Z]+ +\[main\] +\([A-Za-z]+\.java:[0-9]+\) //' | cut -c1-300 > "$OUT/build_pure_defaults.txt" || true
for v in "${VARIANTS[@]}"; do
  "$JAVA" -Xmx4G -jar "$JAR" --abortOnUnknownConfig --build --save "$WORK/in/$v" > "$WORK/in/$v/build.log" 2>&1
  grep -E "Limiting transit service|frequency-based and|Created a total of|Issue summary|  - [A-Za-z]|Transit built" \
    "$WORK/in/$v/build.log" | sed -E 's/^[0-9:.]+ [A-Z]+ +\[main\] +\([A-Za-z]+\.java:[0-9]+\) //' > "$OUT/build_$v.txt"
done
# Of the build issues, keep the details of the two rare kinds (consecutive stops at the same point, hops of 0 minutes)
for k in HopZeroDistance HopZeroTime; do
  f="$WORK/in/asis_defaults/report/$k.html"
  [ -f "$f" ] && sed -e 's/<[^>]*>/\n/g' "$f" | grep -E "^(Zero-distance hop|Zero-time hop)" > "$OUT/build_issues_$k.txt" || true
done

serve() {  # $1=input name $2=port; listen only on this computer (OTP's default 0.0.0.0 is every network interface)
  "$JAVA" -Xmx4G -jar "$JAR" --abortOnUnknownConfig --load --bindAddress 127.0.0.1 --port "$2" "$WORK/in/$1" \
    > "$WORK/in/$1/serve.log" 2>&1 &
  PIDS+=($!)
  for _ in $(seq 1 120); do grep -q "Grizzly server running" "$WORK/in/$1/serve.log" 2>/dev/null && return 0; sleep 1; done
  echo "サーバーが立たない: $1"; exit 1
}

# (4) Copy with a one-day calendar
serve asis_defaults "$BASE"
python3 - "$HERE" "$BASE" > "$OUT/one_day_calendar.txt" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import otp_tools as ot
port = int(sys.argv[2])
for o, d, name in [('PS02298', 'PS00296', '東京→下關'), ('PS02298', 'PS00471', '東京→京城〈朝鮮〉')]:
    pc = ot.plan(port, o, d, '1925-04-01T08:00+09:00', window='PT24H')
    its = sorted((e['node'] for e in pc['edges']), key=lambda it: it['end'])
    print(name, '1925-04-01 08:00 發 →', its[0]['end'] if its else 'なし',
          [x['code'] for x in pc['routingErrors']])
PY
cleanup; PIDS=()

# (5) 320 searches on the 4 April copies
PORTS=""; i=1
for v in april_defaults april_aligned april_aligned_split april_aligned_split_exact; do
  serve "$v" $((BASE + i)); PORTS="$PORTS${PORTS:+,}$v=$((BASE + i))"; i=$((i + 1))
done
python3 "$HERE/compare_otp.py" --release "$WORK/release" --ports "$PORTS" --out "$WORK/comparison.jsonl"
cleanup; PIDS=()

# (6) Classification
python3 "$HERE/classify.py" "$WORK/release" "$WORK/comparison.jsonl" \
  april_defaults,april_aligned,april_aligned_split,april_aligned_split_exact | tee "$OUT/classification.txt"
mv "$WORK/comparison.csv" "$OUT/comparison.csv"
echo "結果: ${OUT}（作業用フォルダ: ${WORK}）"
