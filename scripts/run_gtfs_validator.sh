#!/usr/bin/env bash
# Run the MobilityData GTFS validator (gtfs-validator) on a copy of a GTFS feed.
#
#   bash scripts/run_gtfs_validator.sh [GTFS_DIR] [OUT_DIR]
#     GTFS_DIR default = data/gtfs_v1_release/gtfs
#     OUT_DIR  default = data/reports/<YYYYMMDD>
#
# - Only *.txt files are copied to a temporary folder and read (nothing is written to GTFS_DIR).
# - The validator and Java 17 live in data/external/gtfs_validator/ (not in git).
#   They are downloaded if missing (v8.0.1 CLI jar, Eclipse Temurin 17.0.20.1+1 from Adoptium) and checked against
#   the SHA-256 values below before use; the cached jar is checked on every run. Java is unpacked into a temporary
#   folder and renamed only when complete, and its version is checked before use. Java passed as
#   GTFS_VALIDATOR_JAVA is used as it is. GTFS_VALIDATOR_SHA256 is read only for another validator version
#   (GTFS_VALIDATOR_VERSION): pass the SHA-256 of that version's jar.
# - The validator writes into a new temporary folder; its files are then copied to OUT_DIR, replacing those of an
#   earlier run, so a report left in OUT_DIR is never read as this run's.
# - Output = OUT_DIR/report.json, report.html, system_errors.json, and
#   summary.tsv with counts per notice (severity / code / count).
# - Exit code 1 if there is at least one ERROR.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GTFS_DIR="${1:-$ROOT/data/gtfs_v1_release/gtfs}"
OUT_DIR="${2:-$ROOT/data/reports/$(date +%Y%m%d)}"
VER="${GTFS_VALIDATOR_VERSION:-8.0.1}"
CACHE="$ROOT/data/external/gtfs_validator"
JAR="$CACHE/gtfs-validator-$VER-cli.jar"
mkdir -p "$CACHE"

# SHA-256 of gtfs-validator-8.0.1-cli.jar (the digest GitHub shows for the release asset)
VALIDATOR_SHA256_8_0_1=19293ddd9b6f954f216d4f12054bd8a3232921751c4484339e339764a91000e2
JDK_RELEASE=jdk-17.0.20.1+1
JDK_VERSION=17.0.20.1
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

want="${GTFS_VALIDATOR_SHA256:-}"
if [ "$VER" = "8.0.1" ]; then want="$VALIDATOR_SHA256_8_0_1"; fi   # the fixed value always applies to the default version
[ -n "$want" ] || { echo "gtfs-validator $VER の jar の SHA-256 を GTFS_VALIDATOR_SHA256 で渡す"; exit 1; }
[ -f "$JAR" ] || fetch_checked "https://github.com/MobilityData/gtfs-validator/releases/download/v$VER/gtfs-validator-$VER-cli.jar" "$JAR" "$want"
[ "$(sha256_of "$JAR")" = "$want" ] || { echo "jar の SHA-256 が合わない（消してから回し直す）: $JAR"; exit 1; }
JAVA="${GTFS_VALIDATOR_JAVA:-}"
if [ -z "$JAVA" ]; then
  arch="$(uname -m)"; [ "$arch" = "arm64" ] && arch=aarch64; [ "$arch" = "x86_64" ] && arch=x64
  case "$(uname -s)" in Darwin) os=mac ;; Linux) os=linux ;; *) os="$(uname -s)" ;; esac
  case "$os-$arch" in   # SHA-256 of OpenJDK17U-jdk_<arch>_<os>_hotspot_17.0.20.1_1.tar.gz (Adoptium)
    mac-aarch64)   sum=196d13ba5f10414bef7f6a05a9b3f00edacb18ebacef2b99485db9e2ee18f0e8 ;;
    mac-x64)       sum=c01975da12ed4235250ff891fe8bba73a9e73037d444b269c9d0922b5dbc8e0a ;;
    linux-aarch64) sum=457b57af8f9c93ec39080bb8c764f559dc8c89a6da1a39d718a400b7890d3e41 ;;
    linux-x64)     sum=3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e ;;
    *) echo "この環境（$os $arch）の Java 17 は自動で用意できない＝GTFS_VALIDATOR_JAVA で渡す"; exit 1 ;;
  esac
  JDK_HOME="$CACHE/$JDK_RELEASE"
  if [ ! -d "$JDK_HOME" ]; then
    tgz="$CACHE/OpenJDK17U-jdk_${arch}_${os}_hotspot_17.0.20.1_1.tar.gz"
    fetch_checked "https://github.com/adoptium/temurin17-binaries/releases/download/${JDK_RELEASE/+/%2B}/$(basename "$tgz")" "$tgz" "$sum"
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

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/in" "$TMP/out"
cp "$GTFS_DIR"/*.txt "$TMP/in"/
# The validator's exit code is not used (the report is read below); a missing report means the run itself failed.
"$JAVA" -jar "$JAR" -i "$TMP/in" -o "$TMP/out" -c jp >/dev/null 2>&1 || true
[ -f "$TMP/out/report.json" ] || { echo "バリデータが report.json を書かなかった（Java とバリデータの jar を確かめる）"; exit 2; }
mkdir -p "$OUT_DIR"
cp -R "$TMP/out/." "$OUT_DIR/"

python3 - "$OUT_DIR" <<'PY'
import json, sys
out = sys.argv[1]
d = json.load(open(f"{out}/report.json"))
order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
ns = sorted(d["notices"], key=lambda n: (order[n["severity"]], -n["totalNotices"]))
with open(f"{out}/summary.tsv", "w") as f:
    f.write("severity\tcode\tcount\n")
    for n in ns:
        f.write(f"{n['severity']}\t{n['code']}\t{n['totalNotices']}\n")
err = sum(n["totalNotices"] for n in ns if n["severity"] == "ERROR")
warn = sum(n["totalNotices"] for n in ns if n["severity"] == "WARNING")
print(f"gtfs-validator {d['summary'].get('validatorVersion')}: ERROR {err} / WARNING {warn}")
for n in ns:
    print(f"  {n['severity']:7s} {n['code']:45s} {n['totalNotices']}")
sys.exit(1 if err else 0)
PY
