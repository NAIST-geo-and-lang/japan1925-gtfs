# Japan1925-GTFS

The Japanese version is available in `README.ja.md`. If the two versions differ, this English version takes precedence.

This dataset provides a GTFS (General Transit Feed Specification; <https://gtfs.org/>) feed of scheduled railway, tramway, and ferry services published in the April 1925 inaugural issue of *Kishā Jikanhyō* (汽車時間表), Japan's national timetable. It also includes the source-table transcriptions and records that trace times and train numbers back to the source timetable, and station coordinates to the references they were taken from.

| | |
|---|---|
| **Download** | https://doi.org/10.5281/zenodo.23200420 (ZIP archive: approximately 21 MB compressed, 160 MB extracted) |
| **Coverage** | Japan proper (including Hokkaido), Karafuto, Korea, and Taiwan, plus connecting services in Manchuria, China, and the Russian Far East, as covered by the source timetable |
| **Feed** | 541 routes · 10,080 trips (9,849 transcribed from printed timetables; 231 template trips for headway-based services; see `DETAILS.md`, note 5) · 5,124 stops grouped into 4,576 parent stations · 87,652 stop times |
| **Source** | 193 timetable pages (pp. 1–195, excluding two map pages), transcribed into 178 workbooks and checked page by page against the scans |
| **Calendar** | All trips are modeled as operating daily from 1925-03-28 to 1925-04-30 (a dataset convention; see `DETAILS.md`, note 1). |
| **Version** | v1.0 — `feed_version` `20261026-ebd6f64c` in `gtfs/feed_info.txt`; identifiers remain stable across versions |
| **License** | CC BY 4.0 for data; MIT for scripts and configuration files in `examples/` and `tools/` (see `LICENSE`). Station coordinates also require the source attributions listed below. |
| **Cite as** | Ouchi, H., & Yamamoto, S. (2026). Japan1925-GTFS: a dataset of scheduled railway and ferry services from Japan's 1925 national timetable (Version v1.0) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.23200420 (see the "License and citation" section below for BibTeX) |

The dataset represents services **as published in the timetable**, not evidence of which trains or ships actually operated on a particular date. The service calendar, transfer times, and some times and coordinates reflect modeling conventions or estimates (see the "Limitations" section below and "Details of the GTFS layer (`gtfs/`)" in `DETAILS.md`). Every printed time included in the GTFS feed can be traced to its source page, table, column, and row (see the "Examples of analysis with the CSV files" section below).

## Getting started

### 1. Get the files

Download and extract the archive from https://doi.org/10.5281/zenodo.23200420 (approximately 21 MB compressed, 160 MB extracted). The `gtfs/` folder (4 MB) contains the files needed for routing and network analysis. The `extras/` folder provides provenance records and information not supported by standard GTFS; `transcription/` contains the transcribed tables; and `integrated/` contains train records produced between transcription and GTFS conversion. Each folder and file is described in more detail in the "What is in the dataset" section below.

### 2. Try a journey search

#### How to search

In the folder extracted in step 1, use the included script `examples/route_1925.py` to search for a journey from Tokyo to Shimonoseki (下關), leaving at 08:00 or later (the script needs only Python 3; no additional libraries have to be installed):

```sh
python3 examples/route_1925.py 東京 下關 08:00
```

It prints:

```text
東京 -> 下關  depart 08:15  arrive 08:05 (+1 day)  (23 h 50 min, 0 transfers)
  ride: 東海道本線 3号  東京 08:15 -> 神戸 20:40
  through: 山陽本線 3号  神戸 20:46 -> 下關 08:05 (+1 day)
```

`ride` indicates the train boarded; `through` indicates a continuation on the same train across a line boundary and does not count as a transfer.

#### How to give station names

Stations are given by their names as printed, in the character forms of the source (for example 下關, not 下関). The names that can be used are in `extras/stop_name_variants.csv`: rows with `location_type` `1` are stations, `stop_name` is the name to give, and `name_shinjitai` is the same name in modern character forms (a region tag such as 〈滿洲〉 may be left out).

An excerpt of the station rows of the table:

```text
stop_id,stop_name,location_type,name_shinjitai,printed_names
...
PS00296,下關,1,下関,
PS01008,哈爾賓〈滿洲〉,1,哈爾賓〈満洲〉,
PS01873,廣島,1,広島,
PS02805,澁谷,1,渋谷,
...
```

To search by part of a name, use `--list`. The next example lists the stations whose names contain 高田, with their lines:

```sh
python3 examples/route_1925.py --list 高田
```

It prints:

```text
PS03386 美濃高田 / 美濃高田（養老鐵道線）
PS03755 豐後高田 / 豐後高田（宇佐參宮鐵道線）
PS04284 高田 / 高田（信越本線）
PS04285 高田 / 高田（和歌山線）・高田（櫻井線）
PS04286 高田本山 / 高田本山（伊勢鐵道線）
PS04287 高田馬場 / 高田馬場（山手線）
```

Each line starts with a station identifier (`PS…`), followed by the station name and its stops, one for each line (for how stations and stops relate, see "3. Use the feed in GTFS software" below). Two stations are named 高田: `PS04284` on 信越本線 and `PS04285` on 和歌山線 and 櫻井線. When a name matches several stations, the script uses all of them as the origin or destination and prints the one actually used, with the line ridden.

#### Journeys of several days

Journeys of several days can be searched as well. The next example is a journey of just over four days by train and ferry from Tokyo to Harbin (哈爾賓); `--days` is the number of days the journey may take (default 5):

```sh
python3 examples/route_1925.py 東京 哈爾賓 08:00 --days 5
```

It prints:

```text
東京 -> 哈爾賓  depart 08:15  arrive 08:49 (+4 days)  (96 h 34 min, 4 transfers)
  ride: 東海道本線 3号  東京 08:15 -> 神戸 20:40
  through: 山陽本線 3号  神戸 20:46 -> 下關 08:05 (+1 day)
  ride: 連絡汽船 1号  下關 10:30 (+1 day) -> 釜山〈朝鮮〉 18:30 (+1 day)
  ride: 京釜本線 1号  釜山（棧橋） 20:00 (+1 day) -> 京城〈朝鮮〉 07:45 (+2 days)
  through: 京義本線 1号  京城〈朝鮮〉 08:05 (+2 days) -> 安東〈滿洲〉 20:50 (+2 days)
  through: 滿鐵安奉線 1号  安東〈滿洲〉 21:40 (+2 days) -> 蘇家屯 07:07 (+3 days)
  ride: 滿鐵滿洲本線・旅順線及營口線 13号  蘇家屯 07:46 (+3 days) -> 長春〈滿洲〉 17:00 (+3 days)
  ride: 東支鐵道南線 10号  長春〈滿洲〉 23:29 (+3 days) -> 哈爾賓〈滿洲〉 08:49 (+4 days)
```

`(+4 days)` means four days later. Times in Manchuria are shown converted to Japan time, as in the GTFS feed.

### 3. Use the feed in GTFS software

The `gtfs/` folder contains a standard GTFS feed, except that `shapes.txt` is not provided.

- The Python libraries gtfs-kit (<https://pypi.org/project/gtfs-kit/>) and partridge (<https://pypi.org/project/partridge/>) can read the folder directly. See `examples/with_gtfs_kit.py` for a gtfs-kit example.
- Applications that require a GTFS ZIP file rather than a folder, such as OpenTripPlanner (<https://www.opentripplanner.org/>) and the R packages tidytransit (<https://cran.r-project.org/package=tidytransit>) and gtfstools (<https://cran.r-project.org/package=gtfstools>), need a ZIP containing the nine files from `gtfs/` at its root, not inside a subfolder. The full dataset archive is not itself a GTFS ZIP because those files are stored under `gtfs/`. Instructions for creating one are in `examples/opentripplanner/README.md`.
- Each *(station name, line)* pair is represented by a separate stop, with stops grouped into parent stations. `transfers.txt` specifies transfers of 0 minutes within a parent station and walking times of 1–39 minutes between nearby parent stations. Without this file, transfers between lines are not possible (`DETAILS.md`, note 3).
- Times continue beyond midnight rather than resetting at 24:00 (for example, `26:30:00`, up to `104:30:00`). Because some trips last several days, routing software must consider trips that began on earlier dates and allow journeys longer than one day (`DETAILS.md`, note 2).
- OpenTripPlanner also needs to be configured for a service period covering 1925 and journeys lasting more than one day. Ready-to-use configuration files and a script for querying the server are provided in `examples/opentripplanner/` (`DETAILS.md`, note 12).
- The validation tool gtfs-validator 8.0.1 (<https://github.com/MobilityData/gtfs-validator>) of MobilityData (<https://mobilitydata.org/>), the international non-profit organization that promotes the GTFS standard, reports no errors. Its warnings are explained in the "Validation with gtfs-validator" section of `DETAILS.md`.

### 4. Read next

See `DETAILS.md` for a description of each file, the columns of the tables in `extras/`, `transcription/`, and `integrated/`, and the full explanation of the modeling conventions. `KNOWN_ISSUES.md` documents material not transcribed, approximate data, and inconsistencies in the source timetable.

## What is in the dataset

### Folders and files

| Path | Contents |
|---|---|
| `gtfs/` | The GTFS feed: `agency`, `calendar`, `feed_info`, `routes`, `stops`, `trips`, `stop_times`, `frequencies`, and `transfers` (no `shapes`). The folder, or a ZIP of its nine files, can be used with GTFS software (see step 3 of the "Getting started" section above). |
| `extras/` | 16 tables, mostly linked by GTFS identifiers, plus one GeoJSON file. These provide provenance for stop times, coordinates, and train numbers; through-train connections; operating days and dated sailings; train types and classes; source text for headway-based services; computed times; corrections of source misprints; alternative station-name spellings; and straight-line route drawings for maps. |
| `examples/` | Examples for using the feed: a journey planner that requires only the Python standard library, a script that reads the feed with gtfs-kit, and ready-to-use configuration files for OpenTripPlanner 2 in `opentripplanner/`. |
| `tools/` | Two Python scripts requiring only the standard library. One creates a version of the feed that respects printed operating days; the other builds a route-search network (stations, trips, and walking transfers in a single JSON file) using only `gtfs/` and `extras/`. |
| `transcription/` | The transcribed timetable tables: 178 workbooks covering individual pages or facing-page pairs, in two versions (before and after train numbers were assigned), plus a combined long-format CSV. |
| `integrated/` | Stop times at the stage between the transcription and the GTFS feed. The information on the same train, written separately on several sheets, is combined into one trip. Trips with a name covering several lines, such as 東海道及山陽本線 (Tōkaidō and San'yō main lines), are also divided by line. |
| `README.md` | This document (Japanese version: `README.ja.md`). |
| `DETAILS.md` | Full descriptions of the files and columns (Japanese version: `DETAILS.ja.md`). |
| `KNOWN_ISSUES.md` | Known issues and limitations (Japanese version: `KNOWN_ISSUES.ja.md`). |
| `LICENSE` | License terms (Japanese reference translation: `LICENSE.ja.md`). |

### Main tables in `extras/`

The main tables in `extras/` are:

| Table | Purpose |
|---|---|
| `stop_time_source.csv` | Source page, sheet, column, and row for printed times; whether each time was printed, copied, computed, or part of a template trip; the time system used in the source and its offset to Japan time |
| `stop_coord_source.csv` | How each coordinate was obtained (`station`, `place`, or `estimated`), with source identifiers |
| `trip_source.csv` | The transcription sheets associated with each trip and how its train number was determined |
| `physical_trains.csv` | Trips that form a single through train in the source (represented as separate trips by line in the GTFS feed) |
| `operating_days.csv`, `printed_sailings.csv` | Services not described as daily in the source: those with specified operating days or dates, and irregular trains (不) without printed operating days (all are modeled as daily in the feed in `gtfs/`) |
| `estimated_stop_times.csv` | Computed times, including arrivals calculated from printed running times and times for frequency-only services (see note 6 in `DETAILS.md`) |
| `stop_name_variants.csv` | Modern character forms of station names to support searching |
| `trip_attributes.csv`, `route_region.csv` | Train types and classes; the region assigned to each route in 1925 |

For descriptions of each file and of the columns of the tables in `extras/`, `transcription/`, and `integrated/`, see "Files" and the subsequent sections in `DETAILS.md`.

## Examples of analysis with the CSV files

### Load the files

You can also explore the files with the Python library pandas (<https://pandas.pydata.org/>) or another CSV reader:

```python
import pandas as pd
routes = pd.read_csv('gtfs/routes.txt')
trips = pd.read_csv('gtfs/trips.txt', dtype={'trip_short_name': str})
n = trips.groupby('route_id').size().rename('trips')
routes.join(n, on='route_id').nlargest(3, 'trips')[['route_short_name', 'route_long_name', 'trips']]
# (row index omitted)
#  route_short_name route_long_name  trips
#            東海道本線          東京・神戸間    304
#             東北本線             NaN    177
#             山陽本線             NaN    147
```

### Trace a value back to the printed page

Each row in `gtfs/stop_times.txt` has a corresponding record in `extras/stop_time_source.csv` documenting the origin of its times. For printed times, that record identifies the page, sheet, column, and row in the transcription:

```python
src = pd.read_csv('extras/stop_time_source.csv', dtype=str)
t = trips.merge(routes).query("route_short_name == '東海道本線' and trip_short_name == '3'").trip_id.iloc[0]
src.query("trip_id == @t and stop_sequence == '1'").iloc[0]
# (selected fields) stop_name 東京 · departure_source printed · departure_page 1 · departure_sheet p0001_tb001-1 · departure_column 3 · departure_row 1
```

For example, the 08:15 departure of limited express train 3 from Tokyo appears on page 1 of the source, in train column 3 of sheet `p0001_tb001-1` in `transcription/workbooks/p001-002.xlsx`. Station coordinates can likewise be traced to their references through `extras/stop_coord_source.csv`, and train numbers to the source timetable through `extras/trip_source.csv`.

## How the dataset was created

### Source

The source is the April 1925 inaugural issue of *Kishā Jikanhyō* (vol. 1, no. 1), compiled by the Traffic Bureau of the Ministry of Railways and published by the Japan Travel Culture Association (日本旅行文化協会). We used the 2022 facsimile reprint published by JTB Publishing (『時刻表復刻版 1925年4月号 創刊号』, ISBN 978-4-533-15112-5) and transcribed the original 1925 pages from scans we made of the reprint. Neither the scans nor the new cover and commentary included in the reprint are distributed with the dataset.

### Transcription and checking

The pages were transcribed according to a common set of guidelines, using LLM agents (large language model agents) except for pp. 1–22 and 178–185, which were transcribed by a human. All pages were checked against the scans using both human review and automated checks. For the 30 pages transcribed by a human, the reviewer was the same person, so those checks were not independent; the agents also compared those pages with the scans. In a random sample of 500 transcribed time cells, one differed from the source; it was corrected before release.

When digits were difficult to distinguish in the scans (particularly bold 3, 8, and 9), we selected the reading most consistent with adjacent services and other tables showing the same train. We corrected values judged to be misprints in the source only when the correct value could be established beyond reasonable doubt, recording these changes in `extras/misprint_corrections.csv`. Source descriptions of frequency-only services, stored in `extras/frequency_only.csv` and used to construct template trips, were transcribed separately and were not part of the page-by-page checks.

### Building the GTFS feed

To build the GTFS feed, we joined transcription sheets referring to the same train, created one trip per train and line, and converted times to Japan time where the source specified a time difference. The feed uses a single agency in `gtfs/agency.txt`, 「汽車時間表 1925年4月号（翻刻）」 (meaning "services published in *Kishā Jikanhyō*, April 1925"), rather than assigning services to their historical operators, such as the Ministry of Railways, private railways, the South Manchuria Railway, and shipping companies. See `DETAILS.md` for further information on transcription and processing.

## Station coordinates and their sources

### How the coordinates were obtained

Coordinates are intended to approximate station locations in 1925. For every stop, `extras/stop_coord_source.csv` documents how its coordinates were obtained and identifies the source (see "Provenance of times, train numbers and coordinates" in `DETAILS.md`).

Coordinates classified as station locations (`coord_class` `station`) were drawn from station articles on Wikipedia (mainly Japanese, but also Chinese, Korean, and Russian; `reference_id` identifies the article revision), Wikidata, the MLIT railway dataset N02-25, Historical Place Names Data (including stations shown on historical 1:50,000 maps), and coordinates read by the project from historical topographic maps through Konjaku Map on the Web.

Where a station location could not be established from those sources, we instead used a nearby place point (`place`) or estimated a position from neighboring stations (`estimated`), usually in proportion to distances printed in the 1925 timetable. Place points came from MLIT address reference data, Wikidata, Wikipedia articles on towns, ports, or nearby present-day stations, the MLIT railway dataset N02-25, GeoNames, GSI Maps (for some port landing points), Historical Place Names Data, and historical topographic maps. We also consulted the 1926 edition of 『鐵道停車場一覽』 (*Tetsudō Teishajō Ichiran*, a list of railway stations) to identify the village (大字) where a station was located. From Wikipedia we used only coordinates and revision identifiers, and from map services we recorded only latitude and longitude; neither article text nor map images are included.

### Attributions

The following sources are acknowledged as required by their terms of use:

- 「国土数値情報（鉄道データ）」 N02-25, Ministry of Land, Infrastructure, Transport and Tourism (MLIT), Japan, CC BY 4.0. 出典：国土交通省国土数値情報ダウンロードサイト（<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html>）。 「国土数値情報（鉄道データ）」（国土交通省）（<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html>）を加工して作成
- 「大字・町丁目位置参照情報」, MLIT, Japan (Reiwa 7 / 2025 edition, version 19.0b). 出典：位置参照情報ダウンロードサービス（国土交通省）（<https://nlftp.mlit.go.jp/isj/>）。 「位置参照情報ダウンロードサービス」（国土交通省）（<https://nlftp.mlit.go.jp/isj/>）を加工して作成
- 地理院地図 (GSI Maps), Geospatial Information Authority of Japan（出典：地理院地図（国土地理院）（<https://maps.gsi.go.jp/>））
- Historical Place Names Data (歴史地名データ), National Institutes for the Humanities (NIHU) and the H-GIS Research Group (place names from former 1:50,000 topographic maps and the Dai Nihon Chimei Jisho), used with modification. 「歴史地名データ（人間文化研究機構・H-GIS研究会。旧5万分の1地形図・大日本地名辞書の地名）を加工して作成」。This release makes use of research outcomes of NIHU and the H-GIS Research Group (https://www.nihu.jp/ja/database/source_map/about.html).
- Konjaku Map on the Web: 谷 謙二 (2017) 「今昔マップ旧版地形図タイル画像配信・閲覧サービス」の開発. GIS-理論と応用, 25(1), 1–10
- Wikipedia (station and place articles; revision links in `reference_id`); Wikidata (CC0); GeoNames (geonames.org, CC BY 4.0)
- 『鐵道停車場一覽』, 1926 (Taishō 15) edition, National Diet Library, pid 1020981 (<https://dl.ndl.go.jp/pid/1020981>; public domain)

## Limitations

- The dataset reflects services as published, not verified historical operations. A service's appearance in the timetable does not establish that it ran on any particular date, and its absence from the feed does not establish that it did not run (see sections 1–3 of `KNOWN_ISSUES.md`).
- Fares were not transcribed into structured fields, although some remain in the source text in `extras/frequency_only.csv`. The shipping-table columns for ship names, tonnage, and passenger capacity were also excluded, except for ship names printed as column headings. Vertically printed notes are retained in the notes of the transcription (row 12 of the workbooks) rather than as stop times, but their transcription is incomplete.
- Station coordinates are **approximate** and intended for network-level analysis and mapping, not analyses requiring positional accuracy of a few hundred meters. The `coord_class` field in `extras/stop_coord_source.csv` distinguishes station locations, substitute place points, and estimated positions.
- Departure times for headway-based services and some intermediate stop times are estimated (`timepoint` `0`). If the source gives only an arrival or a departure time at a stop, the missing counterpart is assigned the same time. Identical arrival and departure times therefore do not necessarily imply a zero-minute stop.
- Some trips retain composite line names that refer to two or more lines, such as 臺灣總督府鐵道縦貫線及臺中線 (the Trunk Line and Taichū Line of the Taiwan Government-General Railways; see section 4 of `KNOWN_ISSUES.md`).

A complete list of known issues, including counts, is provided in `KNOWN_ISSUES.md`.

## License and citation

### License

The GTFS feed (`gtfs/`), supplementary tables (`extras/`), transcriptions (`transcription/`), and integrated records (`integrated/`) are licensed under Creative Commons Attribution 4.0 International (CC BY 4.0; https://creativecommons.org/licenses/by/4.0/). Scripts and configuration files in `examples/` and `tools/` are licensed under the MIT License. See `LICENSE` (with a Japanese reference translation in `LICENSE.ja.md`). The station coordinates incorporate data from the sources listed above, whose terms of use require the corresponding attributions.

### Citation

Please cite the dataset as follows:

Ouchi, H., & Yamamoto, S. (2026). Japan1925-GTFS: a dataset of scheduled railway and ferry services from Japan's 1925 national timetable (Version v1.0) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.23200420

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

## Versions

This dataset is version v1.0 (`feed_version` `20261026-ebd6f64c` in `gtfs/feed_info.txt`). Corrections will be published in subsequent versions on Zenodo. Stop, parent station, route, and trip identifiers remain stable across versions; identifiers of removed records will not be reused.

## Reporting problems

To report an error, contact the address listed in `gtfs/feed_info.txt` and include the relevant `trip_id` or `stop_id` and, if possible, the source page number. An example of a report is given under "Reporting problems" in `KNOWN_ISSUES.md`.
