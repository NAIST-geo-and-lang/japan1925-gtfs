# Japan1925-GTFS: processing code

The Japanese version is available in `README.ja.md`. If the two versions differ, this English version takes precedence.

This repository contains the code and the manually curated reference tables used to build **Japan1925-GTFS**, a dataset of the scheduled railway and ferry services in Japan's national timetable of April 1925, published on Zenodo (<https://doi.org/10.5281/zenodo.23200420>, v1.0).

With this repository you can try the journey planner on the published dataset, rebuild the published dataset from its transcription workbooks, and rerun the journey-planning tests reported in the article that describes the dataset. The reference of the article will be added here once it is published.

## Getting started: try the journey planner

The journey planner (`demo/route_planner/index.html`) is a web page that searches for journeys in the published dataset and shows them on a map. You need only Python 3 (no additional libraries) and a web browser; you do not have to rebuild the dataset.

### 1. Get this repository and the dataset

```sh
git clone https://github.com/NAIST-geo-and-lang/japan1925-gtfs.git
cd japan1925-gtfs
curl -fL -o japan1925-gtfs-v1.0.zip "https://zenodo.org/records/23200420/files/japan1925-gtfs-v1.0.zip?download=1"
python3 -c "import hashlib, sys; h = hashlib.md5(open('japan1925-gtfs-v1.0.zip', 'rb').read()).hexdigest(); print(h); sys.exit(h != '4419cf6daae9a7787ccf3894fb400088')" && unzip -q japan1925-gtfs-v1.0.zip
```

The archive is about 21 MB (160 MB extracted). The fourth command prints the MD5 checksum of the archive and extracts the archive only if the checksum is the one recorded on Zenodo (4419cf6daae9a7787ccf3894fb400088); if it prints another value, download the archive again. You can also download it from <https://doi.org/10.5281/zenodo.23200420> and extract it in this folder.

### 2. Build the route-search network

```sh
python3 japan1925-gtfs-v1.0/tools/make_router_data.py --feed japan1925-gtfs-v1.0 --out demo/route_planner
```

This takes about a second. It reads only `gtfs/` and `extras/` of the dataset and writes `router_data.js` (and the same data as `router_data.json`) next to the page.

### 3. Open the page

Open `demo/route_planner/index.html` in a web browser. Opening the file directly is enough (no web server is needed), but the map tiles need an internet connection. The background map is GSI Tiles of the Geospatial Information Authority of Japan, which have detailed maps only for Japan and its surroundings; when you zoom in on Taiwan, Karafuto, Korea or Manchuria, the background map disappears. The line at the top of the page should read `データ: Japan1925-GTFS 20261026-ebd6f64c（駅 4576・便 22949）`.

Enter an origin, a destination and a departure time and click 検索 (search), or click one of the examples (例) below them. For example, 東京 → 下關 at 08:00 lists three journeys, the first of which is:

```text
08:15 発 → 08:05 着   23時間50分   乗換 0 回
東海道本線→山陽本線 3号   直通
```

It leaves 東京 at 08:15 and arrives at 下關 at 08:05 the next day (23 h 50 min, 0 transfers) on train No. 3, which runs through (直通) from 東海道本線 to 山陽本線. The stops of the selected journey are listed on the right, and clicking ▶ 出発 at the bottom moves the train along the map. The page is in Japanese. Station names are entered as printed, in the character forms of the source (for example 下關, not 下関); the input boxes suggest names as you type.

To search from the command line instead, use `examples/route_1925.py` in the dataset (see the README of the dataset).

## What is in this repository

| Path | Contents |
|---|---|
| `reproduce.sh` | Runs the whole build: extraction → integration → GTFS generation with coordinate assignment → packaging |
| `requirements.txt` | Python packages for the build (packages used only by the tests are installed with the commands in "Journey-planning tests") |
| `scripts/` | Processing steps (`extract_stop_times.py`, `integrate_stop_times.py`, `run_pipeline.sh` and the scripts it calls) |
| `scripts/release/` | Packaging of the dataset and its checks (`build_release_all.sh`), the documents and examples copied into the dataset, and download helpers |
| `data/tables/` | Manually curated tables read by the build: train renumbering, time-system rules, through trains, arrival/departure rows, frequency-only services, misprints, sailing dates, and others; see `data/tables/README.md` |
| `data/knowledge/places/` | Coordinate tables (places, the place of each stop, derived values, map readings); see `data/knowledge/places/README.md` |
| `data/knowledge/public_release/` | Reference records used by the coordinate check, and the identifier registry that keeps public IDs stable; see `data/knowledge/public_release/README.md` |
| `data/knowledge/release_reference_coords.json` | Coordinates of the cited Wikipedia revisions and Wikidata items, downloaded in advance; the coordinate check compares the published coordinates with them |
| `data/distance/` | Mileage tables from the timetable, used for interpolating coordinates and for checks |
| `demo/route_planner/index.html` | The journey planner (a web page; see "Getting started"; its search code is also used by the tests) |
| `tests/` | Journey-planning tests (`route_search/`, `pyraptor/`, `opentripplanner/`) and the check with Python GTFS libraries (`python_libraries/`) |

Comments in the code are in English. Messages printed by the scripts, and the text columns of the tables, are in Japanese.

## Rebuilding the dataset

Rebuilding needs Python 3.14, about 1 GB of free disk space, and an internet connection for the downloads. The Python packages are listed in `requirements.txt` (openpyxl 3.1.5 and shapely 2.1.2, the versions used to build the published dataset). The GTFS Validator 8.0.1 and Java 17, which check the rebuilt feed, are downloaded automatically and checked against fixed SHA-256 checksums before use.

```bash
python3.14 -m venv .venv   # a Python environment for this repository (once)
source .venv/bin/activate
pip install -r requirements.txt
```

With this environment active, run:

```bash
python3 scripts/fetch_transcription.py              # 1. download the dataset from Zenodo and place the transcription workbooks
python3 scripts/release/fetch_external_sources.py   # 2. (optional) reference data for the final coordinate check
bash reproduce.sh                                   # 3. build (about 15 minutes)
```

If you have already downloaded the archive in "Getting started", run step 1 as `python3 scripts/fetch_transcription.py --zip japan1925-gtfs-v1.0.zip` to skip the download.

The dataset is written to `data/gtfs_v1_release/`. Compared with the files published on Zenodo, all files are byte-identical except the transcription workbooks (`.xlsx`), whose cell values are identical but whose internal XML differs slightly (cursor position and default style attributes), because the formatting step is applied once more to workbooks that were already formatted.

Step 2 downloads public reference data used to check that every published coordinate can be explained by a citable source. The script fetches the files directly from the download URLs of their providers; by running it, you agree to their terms of use:

- MLIT National Land Numerical Information N02-25 (railway; CC BY 4.0): the terms of the National Land Numerical Information download site (<https://nlftp.mlit.go.jp/ksj/other/agreement.html>)
- MLIT Ōaza/Chōchōme-level Location Reference Information (Reiwa 7 / 2025 edition, version 19.0b): the terms of the Location Reference Information download service (<https://nlftp.mlit.go.jp/isj/agreement.html>)
- GeoNames (CC BY 4.0): <https://www.geonames.org/about.html>
- Natural Earth (public domain): <https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/LICENSE.md>

The Historical Place Names Data of the National Institutes for the Humanities and the H-GIS Research Group must be downloaded manually; the script prints where to get it and where to place it. Without these data, the build still writes the dataset and reports which stations could not be checked against their sources. The Natural Earth land polygons are also used by the build itself, to check that the stations are on land, so the build downloads them when step 2 has been skipped.

## Journey-planning tests

`reproduce.sh` also builds the route-search network from the rebuilt dataset in `data/gtfs_v1_release_router/`. Its `router_data.js` is byte-identical to the one made in "Getting started".

The tests read the rebuilt dataset and, except (ii), run in the environment above. Test (i) also needs Node.js 18 or later. Test (ii) uses pyraptor 1.3.10, which needs pandas earlier than 2.0 and therefore runs only on Python 3.11 or earlier, so (ii) has its own environment; the commands below install the versions used for the article (pyraptor also imports attrs, which it does not declare as a dependency), and the comparison takes about 10 minutes. Test (iv) installs gtfs-kit 13.0.1 and partridge 1.1.2 in the environment above. For (iii), OpenTripPlanner 2.10.0 and Java 25 are downloaded automatically on first use and checked against fixed SHA-256 checksums. Test (iii) builds the graphs and then runs up to four OpenTripPlanner servers at a time, each with up to 4 GB of memory; the servers listen only on this computer (ports 18090–18094). Its results are written to `data/reports/opentripplanner_<date>/`, and its work folder (a new temporary folder, or `OTP_WORK_DIR`) is kept after the run.

```bash
# (i) basic functionality: valid itineraries, queries with known answers, and physically impossible segments
node tests/route_search/check_route_itineraries.js
python3 tests/route_search/check_route_expectations.py
python3 tests/route_search/check_route_data_quality.py --rq4-only

# (ii) comparison with pyraptor (in its own environment, tests/pyraptor/venv)
cd tests/pyraptor
python3.11 -m venv venv
venv/bin/pip install pyraptor==1.3.10 pandas==1.5.3 numpy==1.26.4 attrs==26.1.0
venv/bin/python make_pyraptor_gtfs.py --release ../../data/gtfs_v1_release --out out/gtfs
venv/bin/python build_timetable.py --in out/gtfs --out out/timetable
venv/bin/python compare_route_planner.py --gtfs-dir out/gtfs --pyraptor-out out/timetable                         # the 14 fixed queries
venv/bin/python compare_route_planner.py --gtfs-dir out/gtfs --pyraptor-out out/timetable --sample 300 --seed 1   # 300 random queries
cd ../..

# (iii) compatibility with OpenTripPlanner 2.10.0 (downloads OpenTripPlanner and Java 25 on first use)
bash tests/opentripplanner/run_otp_check.sh

# (iv) reading the feed with gtfs-kit and partridge
pip install gtfs-kit==13.0.1 partridge==1.1.2
python3 tests/python_libraries/check_python_libs.py data/gtfs_v1_release
```

With the rebuilt dataset, the tests give the results reported in the article:

- (i) All 175 test queries give valid itineraries and all 25 queries with known answers give the expected results (FAIL 0 in both), and none of the 145,297 segments is physically impossible.
- (ii) The 14 fixed queries agree. Of the 300 random queries, 276 give matching results, 16 have no route in either planner, and the other 8 reach a search limit of one of the planners.
- (iii) Of the 320 queries, OpenTripPlanner and the dataset's planner `examples/route_1925.py` agree on the earliest arrival, or on finding no journey, for 262 with the configuration provided in the dataset and for 269 when all frequency-based trips run at exact times. With OpenTripPlanner's default settings plus the two that this feed requires (keeping the 1925 trips and searching journeys of up to four days), they agree for 256.
- (iv) Both libraries read all GTFS files (541 routes and 10,080 trips).

## License

The tables read by the build (the CSV and JSON files under `data/`) and the tables used by the tests (the CSV files under `tests/`) are licensed under Creative Commons Attribution 4.0 International (CC BY 4.0), like the published dataset. All other files (scripts, the journey planner, configuration files and documentation) are licensed under the MIT License. Most of the character pairs in `scripts/release/shinjitai_map.csv` are taken from kyujipy (MIT License). See `LICENSE`.

## Citation

If you use the dataset, please cite it as follows:

Ouchi, H., & Yamamoto, S. (2026). Japan1925-GTFS: a dataset of scheduled railway and ferry services from Japan's 1925 national timetable (Version v1.0) [Data set]. Zenodo. <https://doi.org/10.5281/zenodo.23200420>

BibTeX entry:

```bibtex
@misc{ouchi2026japan1925gtfs,
  author       = {Ouchi, Hiroki and Yamamoto, Shota},
  title        = {{Japan1925-GTFS}: a dataset of scheduled railway and ferry services from {Japan}'s 1925 national timetable},
  howpublished = {Zenodo},
  year         = {2026},
  note         = {Version v1.0},
  doi          = {10.5281/zenodo.23200420},
  url          = {https://doi.org/10.5281/zenodo.23200420}
}
```
