"""Download the openly licensed external sources read by the release gates and the land check into data/external/.

Sources, versions and md5 sums: scripts/release/external_sources.csv (one row per file).
  - N02-25 railway data (National Land Numerical Information, CC BY 4.0): download the zip, extract N02-25_Station.geojson
  - Location reference information at ōaza/chōme level, Reiwa 7, 19.0b (MLIT): zips for the 47 prefectures
  - GeoNames country file CN (CC BY 4.0): updated daily, so an md5 mismatch is only reported
  - Natural Earth 10m land (public domain, v5.1.2)
  - Historical place-name data (NIHU, H-GIS study group): cannot be downloaded automatically; fetch it by hand from
    the download page and place it (the md5 is still checked)
None of them changes the published dataset: they are used by the coordinate gate (step 4e of build_release_all.sh)
to check coordinate sources against the original records, and by check_on_land.py for the land test.
Only sources whose terms allow redistribution are fetched.

Usage (from the repository root):
  python3 scripts/release/fetch_external_sources.py            # fetch only missing files, check every md5
  python3 scripts/release/fetch_external_sources.py --check    # no download; only check presence and md5
Existing files are never overwritten (an md5 mismatch is reported, and the exit code is 1). Downloads and extracted
files are written to a temporary name and renamed only when their md5 matches the table (a mismatch is kept as .part
and not used); the daily-updated GeoNames file is renamed without the check.
"""
import argparse, csv, hashlib, os, sys, urllib.request, zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT = os.path.join(BASE_DIR, 'data', 'external')
TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'external_sources.csv')


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url, dst, want=None):
    """Download url to a temporary name and rename it to dst, only if its md5 is want (when want is given)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.part'
    req = urllib.request.Request(url, headers={'User-Agent': 'japan1925-gtfs fetch_external_sources'})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    if want and md5(tmp) != want:
        raise ValueError(f'md5 が記録と違うので使わない（{tmp} に残した）')
    os.replace(tmp, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='取り寄せず、あるか・md5 が合うかだけを見る')
    a = ap.parse_args()
    rows = list(csv.DictReader(open(TABLE, encoding='utf-8-sig')))
    bad = missing = 0
    manual = []
    for r in rows:
        dst = os.path.join(EXT, r['path'])
        how = r['how']
        if not os.path.exists(dst) and not a.check:
            if how.startswith('download'):
                print(f'取り寄せる: {r["path"]}  ← {r["url"]}')
                try:
                    download(r['url'], dst, None if how == 'download:unpinned' else r['md5'])
                except Exception as e:  # no network, or the site is down
                    print(f'  ★ 取り寄せられなかった: {e}')
            elif how.startswith('extract:'):
                _, src, member = how.split(':', 2)
                srcp = os.path.join(EXT, src)
                if os.path.exists(srcp):
                    with zipfile.ZipFile(srcp) as z, open(dst + '.part', 'wb') as f:
                        f.write(z.read(member))
                    if md5(dst + '.part') == r['md5']:
                        os.replace(dst + '.part', dst)
                        print(f'取り出した: {r["path"]}  ← {src}')
                    else:
                        print(f'  ★ 取り出したファイルの md5 が記録と違うので使わない（{dst}.part に残した）')
        if not os.path.exists(dst):
            missing += 1
            if how == 'manual':
                manual.append(r)
            else:
                print(f'★ 無い: {r["path"]}')
            continue
        got = md5(dst)
        if got == r['md5']:
            continue
        if how == 'download:unpinned':
            print(f'  md5 が記録と違う（毎日更新される資料なので使える・照らせる驛が変わりうる）: {r["path"]} {got}')
        else:
            bad += 1
            print(f'★ md5 が違う: {r["path"]} 記録 {r["md5"]} 手元 {got}')
    for r in manual:
        print(f'★ 手で取って置く: data/external/{r["path"]}\n    {r["name"]}＝{r["url"]}\n    {r["note"]}')
    ok = len(rows) - missing - bad
    print(f'外の資料 {len(rows)} ファイル：そろっている {ok}・無い {missing}・md5 が違う {bad}')
    return 0 if (missing == 0 and bad == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
