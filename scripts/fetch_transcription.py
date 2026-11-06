"""Fetch the transcription workbooks of Japan1925-GTFS v1.0 from Zenodo and place them where the processing scripts read them.

The published dataset (DOI 10.5281/zenodo.23200420) contains the transcription workbooks in
transcription/workbooks/ (with train numbers) and transcription/workbooks_before_numbering/.
This script downloads the distribution zip (or uses a local copy), checks its MD5 checksum, and copies
the workbooks into data/2_timetable_with_tripnum_v1/, data/1_timetable_xlsx_v1/ and
data/1_timetable_xlsx_added_v1/ under the file names that the processing scripts use
(the mapping is scripts/transcription_workbook_names.csv).

Usage (from the repository root):
  python3 scripts/fetch_transcription.py                 # download from Zenodo
  python3 scripts/fetch_transcription.py --zip PATH      # use a zip you have already downloaded
Existing files are not overwritten unless they are identical.
"""
import argparse, csv, hashlib, io, os, sys, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP_URL = 'https://zenodo.org/api/records/23200420/files/japan1925-gtfs-v1.0.zip/content'
ZIP_MD5 = '4419cf6daae9a7787ccf3894fb400088'
TOP = 'japan1925-gtfs-v1.0/'
NAMES = os.path.join(ROOT, 'scripts', 'transcription_workbook_names.csv')


def md5_bytes(b):
    return hashlib.md5(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', help='path to a downloaded japan1925-gtfs-v1.0.zip')
    a = ap.parse_args()
    if a.zip:
        data = open(a.zip, 'rb').read()
    else:
        print(f'Downloading {ZIP_URL}')
        req = urllib.request.Request(ZIP_URL, headers={'User-Agent': 'japan1925-gtfs fetch_transcription'})
        with urllib.request.urlopen(req, timeout=600) as r:
            data = r.read()
    got = md5_bytes(data)
    if got != ZIP_MD5:
        sys.exit(f'MD5 mismatch: expected {ZIP_MD5}, got {got}')
    z = zipfile.ZipFile(io.BytesIO(data))
    rows = list(csv.DictReader(open(NAMES, encoding='utf-8')))
    placed = same = 0
    for r in rows:
        for member, ddir, dname in (
                (f'{TOP}transcription/workbooks/{r["published_name"]}', r['tripnum_dir'], r['tripnum_name']),
                (f'{TOP}transcription/workbooks_before_numbering/{r["published_name"]}', r['before_numbering_dir'], r['before_numbering_name'])):
            b = z.read(member)
            dst = os.path.join(ROOT, ddir, dname)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                if md5_bytes(open(dst, 'rb').read()) == md5_bytes(b):
                    same += 1
                    continue
                sys.exit(f'A different file already exists (not overwritten): {dst}')
            with open(dst, 'wb') as f:
                f.write(b)
            placed += 1
    print(f'Workbooks: {placed} placed, {same} already present ({len(rows)} pages x 2 layers)')


if __name__ == '__main__':
    main()
