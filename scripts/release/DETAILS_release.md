# Japan1925-GTFS — details of the files

The Japanese version is available in `DETAILS.ja.md`. If the two versions differ, this English version takes precedence.

This document supplements the dataset's `README.md`. It describes how the dataset is organized, every file ("Files"), the transcription and integrated layers, the details of the GTFS layer (numbered notes), the results of validation with gtfs-validator, the provenance tables, the columns of every table in `extras/`, and the route-search network. The references "(`DETAILS.md`, note n)" in `README.md` and `KNOWN_ISSUES.md` refer to item n of the numbered notes below.

## How the dataset is organized

The data in this dataset form three layers: the transcription of the printed tables (`transcription/`), the stop times of each trip, with the printings of the same train in several places of the source combined into one trip (`integrated/`), and the feed (`gtfs/`). The derived tables in `extras/` link the feed back to the source and preserve information from the source that cannot be represented in the standard GTFS files.

The transcription has one sheet for each band of a timetable and each direction of the trains (such as up and down). A band is one of the blocks of rows, one above another, into which a timetable of the source is divided; a band prints the times of the trains on one line, or on one stretch of a line. For example, the timetable of down trains 高岡・氷見間 on p. 64 is divided into a band for 中越線 (高岡, 越中中川, 能町) and a band for 氷見線 (伏木, 雨晴, 島尾, 氷見).

```
transcription/   the printed tables: one sheet per band and direction of a table
                 (a time is a cell: sheet, column, row)
      |   sheets that print the same train are joined into one trip;
      |   trips under composite line headings are split at the junction
      v
integrated/      one record per trip and stop (trip_id, stop_id, source_sheet)
      |   computed times (note 6) and times of template trips (note 5) added;
      |   where one time of a stop is printed, the other is copied from it
      v
gtfs/            the feed (trip_id, stop_id, stop_sequence)

extras/ links the feed back to the source:
  stop_time_source.csv    trip_id + stop_sequence -> page, sheet, column and row of each time
  stop_coord_source.csv   stop_id                 -> how each coordinate was obtained
  trip_source.csv         trip_id                 -> sheets of the trip, how its number was found
  physical_trains.csv     trip_id                 -> physical_train_id (trips of one through train)
```

## Files

### The feed and the documents

| Path | Contents |
|---|---|
| `gtfs/` | The GTFS feed (excluding `shapes.txt`; see note 11 below). GTFS software can read this folder or a zip containing its nine files (see "Getting started" in `README.md`). `stops.txt` holds both the stops and their parent stations (`location_type` `1`; see note 3 below). |
| `README.md` | Overview of the dataset: getting started, what is in it, examples of analysis with the CSV files, how it was created, the sources of the coordinates, its limitations, license and citation. |
| `README.ja.md` | Japanese translation of `README.md` (the English version takes precedence). |
| `DETAILS.md` | This document: how the dataset is organized, the file inventory, the transcription and integrated layers, the details of the GTFS layer (numbered notes), the results of validation with gtfs-validator, the provenance tables, the columns of every table in `extras/`, and the route-search network. |
| `DETAILS.ja.md` | Japanese translation of this document (the English version takes precedence). |
| `KNOWN_ISSUES.md` | Known issues and limitations: what was not transcribed, services and printed values that are not in the feed, and where times or positions are approximate. |
| `KNOWN_ISSUES.ja.md` | Japanese translation of `KNOWN_ISSUES.md` (the English version takes precedence). |
| `LICENSE` | The license terms: CC BY 4.0 for the data, the MIT License for the scripts and configuration files in `examples/` and `tools/`. |
| `LICENSE.ja.md` | Japanese translation of `LICENSE` for reference (the English text takes precedence). |

### Tables in `extras/`

| Path | Contents |
|---|---|
| `extras/estimated_stop_times.csv` | Every time in `gtfs/stop_times.txt` that is **not printed in the source** but computed (see note 6 below). |
| `extras/single_stop_trips.csv` | Printed times that belong to a trip with only one timed stop. They cannot be routed, so they are kept here instead of in `gtfs/`. These trips are not in `gtfs/trips.txt`, and a stop or route used only by them is not in `gtfs/stops.txt` or `gtfs/routes.txt` (`stop_name` and `line_name` give the names); their identifiers are stable like all others (see "Versions" in `README.md`). |
| `extras/stop_name_variants.csv` | Other spellings of each stop and parent station, for search: `stop_id`, `stop_name`, `location_type`, the name with every old character form replaced by its modern form (`name_shinjitai`, for example 下関 for 下關 and 大分駅前 for 大分驛前), and the spellings printed in the transcription cells of the stop's times (`printed_names`, most frequent first, separated by `\|`; empty for parent stations and for stops without printed times). |
| `extras/misprint_corrections.csv` | Transcription cells in which a value judged to be a misprint in the source was corrected: the cell location (`page`, `sheet` of `transcription/workbooks/`, `cell`, train `column`, `stop_order`, `station`, `field`), the printed value (`printed_value`), the value used (`corrected_value`), and the reason (`reason`). Only misprints whose printed value was confirmed in the printed book or is clearly legible on the scans are listed. |
| `extras/physical_trains.csv` | Trips representing a single through train in the printed timetable (see note 4 below): `physical_train_id`, `seq`, `trip_id` and `gtfs_trip_key` (the trip key; see note 9 below). `seq` is the order in which the trips of a train are linked; where tables cut the same train at different points (a band under a composite line heading and the detailed tables), it need not be the running order. |
| `extras/trip_source.csv` | For each `trip_id`: the trip key (see note 9 below), `original_trip_short_name` (the train-number part of that key: usually the printed number; a provisional key beginning with `U` where none is printed; a suffix such as `_b` marks a second trip under the same number), the transcription sheet(s) it comes from (`p<page>_tb<table>-<band>[-<segment>]`), the printed train number (`printed_number`, the same as `trip_short_name`), and how the train number was determined (see "Provenance of times, train numbers and coordinates" below). |
| `extras/stop_time_source.csv` | For each row of `gtfs/stop_times.txt`: the sources of its arrival and departure times, down to the page, transcription sheet, column and row (see "Provenance of times, train numbers and coordinates" below). |
| `extras/route_region.csv` | For each `route_id`: the region of the line in 1925 (内地, 北海道, 樺太, 朝鮮, 臺灣, 滿洲, 支那, 露領), classified from the line name. Shipping routes (`route_type` 4) are all given 内地, although their ports may lie in other regions. |
| `extras/stop_coord_source.csv` | For each row of `gtfs/stops.txt`: how and from which source its coordinates were obtained, with identifiers (see "Provenance of times, train numbers and coordinates" below). |
| `extras/operating_days.csv` | Trips that do not run every day in the source: sailings on printed dates, monthly or alternate-day sailings, sailings with days off, and irregular trains (see note 1 below). |
| `extras/printed_sailings.csv` | For each sailing of the dated shipping tables (pp. 189–192): the dates printed for each port, the service date, and the trip and stops that carry its times (see note 1 below). |
| `extras/trip_attributes.csv` | For each printed trip: the train type (特急 limited express, 急行 express), the classes carried, and sleeping-car and dining-car marks, as printed at the head of its column (see "Details of the derived tables (`extras/`)" below). |
| `extras/service_frequency.csv` | For each ferry trip: the sailing frequency stated in the source — every day, alternate days, set days of the month, printed dates, or not stated (see "Details of the derived tables (`extras/`)" below). |
| `extras/frequency_box.csv`, `extras/frequency_sections.csv`, `extras/frequency_only.csv` | The source text of the frequency-based services and how it was converted into `gtfs/frequencies.txt`: boxes such as "此間12分毎ニ運轉" inside a timetable, and frequency-only services printed only as text (first and last departures, headway, running time) (see note 5 below and "Details of the derived tables (`extras/`)" below). |
| `extras/route_lines.geojson` | For drawing maps: one line for each line name, connecting its stations in running order with straight segments. It is not the track (see note 11 below). Lines with only frequency-only services are not drawn. |

### Examples and tools

| Path | Contents |
|---|---|
| `examples/route_1925.py` | A Python script using only the standard library to find earliest-arrival journeys in the feed. |
| `examples/with_gtfs_kit.py` | Uses gtfs-kit to read the feed and print a summary, the most frequently served stops, and the routes with the most trips. |
| `examples/opentripplanner/` | `build-config.json`, `router-config.json` and `otp-config.json` for OpenTripPlanner 2 with the settings of note 12 below; `README.md` (Japanese: `README.ja.md`) on how to install it, make a GTFS zip of `gtfs/` and use them; and `plan_with_otp.py`, a standard-library Python script that asks the running server for journeys by station name and time. |
| `tools/make_printed_days_gtfs.py` | A standard-library Python script that writes a copy of the feed in which the services of `extras/operating_days.csv` run only on their printed days (see note 1 below). |
| `tools/make_router_data.py` | A standard-library Python script that builds, from `gtfs/` and `extras/` only, a route-search network: the stations, trips and walking transfers of the feed in one JSON file (see "Route-search network" below). |

### `transcription/`

| Path | Contents |
|---|---|
| `transcription/workbooks/` | The transcription workbooks with train numbers, one per page or spread of the source (178 files), named by page (for example, `p001-002.xlsx` covers pp. 1–2; only `p097.xlsx` covers the spread of pp. 97–98). The feed is built from these workbooks. |
| `transcription/workbooks_before_numbering/` | The same workbooks before train numbers were assigned. They differ only in the header rows: rows 1–8 are the same, then `trip_label` (row 9: the label printed at the start of a band in the column), the column headings (row 10), and the stations from row 11; there are no train-number rows and no notes row. The station rows are the same as in `workbooks/`. |
| `transcription/transcription_long.csv` | The content of `workbooks/` as one table (see "Details of the transcription layer (`transcription/`)" below for the columns). |

### `integrated/`

| Path | Contents |
|---|---|
| `integrated/integrated_stop_times.csv` | The stop times of each trip after the sheets that print the same train are joined into one trip, and trips under composite line headings (such as 東海道及山陽本線) are split at the junction (see "Details of the integrated layer (`integrated/`)" below for the columns). |
| `integrated/trips_master.csv` | The list of trips. Each row represents one trip; the columns are `trip_id`, `gtfs_trip_key`, `route_id`, `line_name`, `direction`, `trip_num`, `first_stop` and `first_dep`, `last_stop` and `last_arr`. As in `integrated_stop_times.csv`, `trip_id` is empty for the 54 sailings that the feed merges into another trip of the same table. |
| `integrated/stops_master.csv` | The list of stops. Each row represents one combination of station name and line; the columns are `stop_id`, `stop_name`, `line_name`, `canonical_name` (empty in this version), `stop_type` (`station` or `port`). It has no coordinates; the coordinates of the feed are in `gtfs/stops.txt` (see "Station coordinates and their sources" in `README.md`). |

## Details of the transcription layer (`transcription/`)

### Workbook sheets

Each sheet of the files in `transcription/workbooks/` holds one band of a table of the source, in one direction, or one segment of such a band. The sheet name is the table identifier `p<page>_tb<table>-<band>[-<segment>]` used as `source_sheet` and `source_sheets` elsewhere in this dataset. The rows of each sheet are organized as follows:

| Row | Label in column A | Contents |
|---|---|---|
| 1–6 | `table_id`, `page`, `table_name`, `line_name`, `direction_raw`, `direction` | The table identifier, the page, the title and line name of the table, and the direction as printed (for example 上リ列車) and as `outbound` or `inbound`. |
| 7 | `trip_id` | The column of the train in the printed table, counted from the left. Each train takes four spreadsheet columns: `dep_time`, `dep_pm`, `arr_time`, `arr_pm`. |
| 8 | `trip_label_header` | What is printed at the head of the column (train number, train type, marks), transcribed as printed. |
| 9 | `trip_num` | The train number of the column (see "Provenance of times, train numbers and coordinates"). |
| 10 | `trip_num_source` | How the train number was determined (see "Provenance of times, train numbers and coordinates"). |
| 11 | `trip_num_note` | For a number taken from another table, that table and the rule that matched the train (for example `from p0094_tb001-2 (match=dep@天王寺 6.43, 城東線)`). |
| 12 | `確認メモ` (notes) | Printed text that is not a time, and short descriptions of the table, in Japanese. Paragraphs start with a tag: 【原本注記】 a note printed vertically in the table, in the form 「printed text」＝station 著 or 發 time（午前, 午後 or 時間帯不明）; 【表全体】 the table as a whole; 【運航頻度】 how often a ship sails; 【海里】 and 【浬程】 distances; 【運賃】 fares; 【凡例】 the legend; and others. Text beginning 此間 is the printed text of a box such as 此間12分毎ニ運轉 (see 5 below). |
| 13 | `stop_order`, … | Column headings. |
| 14– | | Each row represents one station: `stop_order`, `stop_name`, `stop_type` (`station`, `port`, or for example `branch:鹽竈線` for a junction with a branch line), then the four cells of each train. |

### How times are written

Times are written as in the source, hours and minutes separated by a point: `8.31` is 8:31, `4.40` is 4:40, and `7.00` is 7:00. In the workbooks, some time cells hold numbers and others hold text; in a number cell the trailing zero of the value is lost, so 4:40 is `4.4` and 7:00 is `7` (a spreadsheet may still show `4.40`, depending on the cell format). `transcription_long.csv` writes every time with two-digit minutes. `dep_pm` and `arr_pm` are `1` for p.m. and `0` for a.m. (the source prints p.m. times in bold). A suffix such as `/二日目` (second day) or `/土曜日` (Saturday) gives the day of a sailing that takes more than one day. Transfer marks (＊ beside a time) and the underline that marks a train's last station are not transcribed; the times are written without them, and the marks were read from the page images when `extras/physical_trains.csv` was built.

### `transcription_long.csv`

`transcription_long.csv` combines the transcription of the workbooks into one long table. Each row represents one combination of sheet, train column and station with a printed value; the columns are `file`, `sheet`, `page`, `table_name`, `line_name`, `direction_raw`, `direction`, `column` (row 7), `trip_label_header` (row 8), `trip_label` (row 9 of the workbook before numbering), `trip_num`, `trip_num_source`, `trip_num_note`, `note` (rows 9–12), `stop_order`, `stop_name`, `stop_type`, `dep_time`, `dep_pm`, `arr_time`, `arr_pm`. A train column with no value at any station (for example a column that holds only a vertical note) has one row with the station fields empty. The table 東京・橫濱港間 on p. 31 has no trains: its time columns are marked “當分運轉休止” (service suspended for the time being). Its two sheets (`p0031_tb002-1` and `p0031_tb002-2`) have no train columns and so no rows.

## Details of the integrated layer (`integrated/`)

### `integrated_stop_times.csv`

The columns of `integrated_stop_times.csv` are `trip_id` and `stop_id` (the identifiers used in the feed), `gtfs_trip_key` (the trip key), `line_name`, `direction`, `trip_num`, `stop_sequence`, `stop_name`, `stop_type`, `dep_time` and `arr_time` (`HH:MM`, continuing past 24:00 after midnight, with times printed in other time systems converted to Japan time as in the feed), and `source_sheet`. `trip_id` is empty for 54 sailings of the dated shipping tables (pp. 189–192) that the feed merges into another trip of the same table with the same printed times (`merged_same_times_in_table` in `extras/printed_sailings.csv`); the 28 sailings merged with a sailing of another table have no rows in this layer.

### Differences from the feed

The feed differs from this layer in four ways:

1. It adds computed times (`extras/estimated_stop_times.csv`).
2. It moves trips with one timed stop to `extras/single_stop_trips.csv`.
3. It adds the template trips of `gtfs/frequencies.txt`.
4. It gives every stop that has a time both an arrival and a departure time. Where only one is printed, the feed repeats it; where a through train continues in another table, it takes the time printed there. `extras/stop_time_source.csv` gives the source of each time.

## Details of the GTFS layer (`gtfs/`)

This section gives numbered notes on using the GTFS feed in `gtfs/`.

### 1. Service days

`calendar.txt` treats the April 1925 timetable as operating on every day from 1925-03-28 to 1925-04-30. This is a modeling convention: because operating days are not specified for most services, it allows journey planning for any date in April 1925. The period begins four days before April so that a journey on 1 April can use trains and ships that left earlier (the longest trip, a ship from 大阪 to 那覇, takes 90.5 hours and ends at 104:30). Long journeys (Tokyo to Seoul, Harbin, …) take two to five days, so a router must allow journeys longer than one day (in OpenTripPlanner, `maxJourneyDuration`).

Services for which the source specifies operating days are also included as daily services, and are listed in `extras/operating_days.csv` along with the information printed in the source:
- The dated shipping tables (pp. 189–192) print 145 sailings with their dates (`extras/printed_sailings.csv`). The times are printed once per table, so sailings of different ships or companies with the same times share one trip: 95 sailings are carried by 14 trips. The remaining 50 have fewer than two printed times: 44 have no printed time (only 午前/午後, "a.m./p.m.", or 隨時都合, "as convenient") and are listed only in `extras/printed_sailings.csv`; the one printed time of the other 6 is kept as a one-stop trip in `extras/single_stop_trips.csv`.
- 16 ferry trips run on fixed days of the month, on alternate days, or daily with days off.
- 147 trains are marked 不 (irregular); their operating days are not printed.

`tools/make_printed_days_gtfs.py` writes a copy of the feed in which these services run only on their printed days (`calendar_dates.txt`; each dated sailing becomes its own trip). Use it when the days matter, for example to check a historical journey. Irregular trains are kept every day by default (`--irregular representative` or `drop` to change this), and sailings after 30 April are left out unless `--include-after-period`. A printed operating date does not establish that the service actually ran that day.

For every ferry trip except one, `extras/service_frequency.csv` gives what the source prints about how often it sails, including the trips for which it prints nothing (`記載なし`); those are assumed to sail daily. The exception is the estimated trip of the cruise round Lake Biwa, a frequency-only service, whose source text is in `extras/frequency_sections.csv`.

### 2. Times after 24:00

For trips continuing past midnight, the hour count continues beyond 24:00 (`26:30:00`), so a trip that started on an earlier day may still be running on the query day (multi-day trips reach 104:30); the calendar period starts on 1925-03-28 for this reason. `examples/route_1925.py` runs each trip on earlier days as well and does not read the calendar.

### 3. Stops, parent stations and transfers

`stops.txt` has one stop per *(station name, line)*, so the same physical station appears as a separate stop for each line. Stops that can be regarded as the same station are grouped together, and each group is called a parent station. In `stops.txt`, a parent station is a row of its own (`location_type=1`), and the `parent_station` of each stop holds the `stop_id` of its parent station. `transfers.txt` gives the transfer times: 0 minutes between stops of the same parent station, and 1–13 minutes on foot between nearby parent stations (at most 1 km between their nearest stops; 80 m per minute, rounded up to whole minutes), or up to 39 minutes between stations of the same name that stand apart (see below). The walking time is measured once for each pair of parent stations, between their two nearest stops (leaving out pairs of neighboring stops on the same line and stops placed between neighboring stations by the printed mileages, `interpolated_mileage`), and applies to all their stops.

Stops with the same name within 5 km of one another are grouped under one parent station (the source often prints one name for a town's stations; names are compared without the region tag, with old and new character forms treated as the same); where stops of one name form more than one such group, a stop joins the nearest group. In two cases, stops with the same name are treated as different stations and get separate parent stations, joined by a walk (in this version at most 3.1 km, 39 minutes):

- both positions come from a source that points at the station itself, and they are more than 300 m apart;
- one or both positions are representative points (such as a village or shore point near a port, which may be off by up to about 1 km), and they are more than 300 m plus 1 km for each such point apart.


Examples of stops with the same name that get separate parent stations are the railway station and port at 敦賀, 高知 or 博多, and the stations of two railways at 中野 (中央本線 and 西武鐵道新宿線). The island port 宮島〈嚴島〉 and the station 宮島 of 山陽本線, about 2 km apart across water, are separate parent stations with no walking transfer. The validator lists transfers between stops more than 2 km apart as `transfer_distance_above_2_km` (an information notice). Some stops of different names less than 50 m apart also share a parent station (for example 岩國 and 岩國驛, 市驛 and 和歌山市, 大阪 and 大阪（天保山）). Some pairs less than 50 m apart are not joined, such as pairs that would make one trip pass the same parent station twice; these are usually linked by a 1-minute walk. The parent station of each stop is given by `parent_station` in `stops.txt`. Without `transfers.txt`, no transfer between lines is possible. Some routers do not create transfers from this file; for OpenTripPlanner, see 12 below.

The grouping of stops into parent stations and the walking transfers are calculated from the coordinates in `gtfs/stops.txt` according to the rules above. Where a coordinate is a representative point (`place` in `extras/stop_coord_source.csv`; see "Station coordinates and their sources" in `README.md`), the walking time is only approximate: a walk may join stops that stood farther apart in 1925, and stops some way apart may share a parent station.

### 4. Through trains

Trains that cross a line boundary without a change of train in the printed timetable are split into one trip per line (the source numbers trains per line). `extras/physical_trains.csv` groups the trips of one physical train, so riding them in sequence need not be counted as a transfer. This is not written as GTFS `block_id`: the trips of one train may overlap on a shared stretch of line (both line tables print it), and each trip keeps the clock of its own day; `block_id` allows neither. Five `physical_train_id`s list only one trip. For four of them the other trip has a single timed stop and is in `extras/single_stop_trips.csv` instead; for the fifth (東海道本線 71, `PT_p0015_tb001_30_1`) the other part is a band printed under a composite line heading (東海道及山陽本線) whose times are all in other trips, so it is not a trip of its own.

### 5. Frequencies

The source gives some services as a headway rather than as individual times, in two forms. A "timetable box" stands in a table in place of train columns and states the headway, such as "此間12分毎ニ運轉" (every 12 minutes in between); a "frequency-only service" is described in text outside the timetables with only the first and last departures, the headway and the running time. In GTFS, both are represented by a single trip made for this purpose, together with the period and headway at which it repeats; this trip is called a "template trip". The template trip is in `trips.txt` and `stop_times.txt`, and the period and headway are in `frequencies.txt`. GTFS software takes the stops of the template trip and the running times between them, and repeats it at the headway over the period given in `frequencies.txt` to make the individual trips. These services are **estimated**: the source specifies the headway but not each departure time. Frequency-only services on a line are assigned to a separate route. Where such a route has the same name as a timetable route, its `route_long_name` names the stretch(es) printed in the source (for example 駿豆鐵道線, 沼津驛・三島町間). The template trips of boxes inside a timetable are likewise on a route of their own, never on the route of the printed trips: it has the same `route_short_name`, and `route_long_name` ends in 頻度の推定便 ("trips estimated from a headway"; for example 山手線, 品川・池袋間・頻度の推定便). Some routers treat every trip that shares a route and stop pattern with a frequency-based trip as frequency-based and would otherwise skip the printed trips. The original text and interpretation of each headway box and frequency-only service are in `extras/frequency_box.csv`, `extras/frequency_sections.csv` and `extras/frequency_only.csv` (see "Details of the derived tables (`extras/`)" below).

`exact_times` in `frequencies.txt` is `1` where the departures are fixed: boxes that give the minute past each hour (`②毎時○分`), and boxes that list the departure times. It is `0` where the source gives only a headway, or says only that trains leave every hour at minutes it does not give (`②毎時各分`): one departure per interval, without fixed departure times.

### 6. Computed times

`extras/estimated_stop_times.csv` lists every computed time: `departure_only_terminal` (tables that print only departures from the terminus plus a total running time; arrival = departure + printed running time) and `frequency_section_template` (frequency-only services; intermediate stops interpolated by the straight-line distances between the coordinates of consecutive stops, except as noted below). All remaining times are either printed or copied from the other printed time at the same stop.

`gtfs/stop_times.txt` marks approximate times with the standard GTFS field `timepoint`: `1` where at least one time of the stop is printed in the source, `0` for computed times, for the template trips of frequency-based services and where no time is available for the stop. `timepoint` indicates whether a time is exact or approximate, rather than whether it was printed; `extras/stop_time_source.csv` tells this for each time (`printed`, `copied`, `computed`, `template`; see "Provenance of times, train numbers and coordinates"). The rows with `timepoint` `0` therefore outnumber the rows of `estimated_stop_times.csv`: not listed there are the template trips of headway boxes, which copy the running times of a printed train, and the first stop and the stops without times of each template trip of a frequency-only service. The times listed there as `frequency_section_template` are `template` in `stop_time_source.csv`.

Where the source prints only the arrival or only the departure at a stop, GTFS requires both fields, so the missing time is copied from the one provided (`copied`); equal times therefore do not mean a stop of zero minutes.

Some intermediate stops of the template trips of frequency-only services have no times: where the source prints running times for other, overlapping stretches of the same line, times are not interpolated, so that no computed time contradicts a printed one. GTFS permits missing times at intermediate stops. Some routers (e.g. OpenTripPlanner) interpolate them and let passengers board and alight there, while `examples/route_1925.py` skips these stops.

### 7. Time zones

The source uses several local time standards. Where it states a time difference (South Manchuria and the China coast are 1 hour behind Japan and Korea, and 26 minutes behind Harbin; Harbin time is thus 34 minutes behind Japan time), those times are converted to Japan time (+60 min and +34 min). Times for which the source specifies no offset (Taiwan, the Russian Far East, overseas ports on ferry routes) are as printed. `agency_timezone` is Asia/Tokyo, so software reads these times as Japan time. In 1925 Taiwan kept Western Standard Time (UTC+8), one hour behind Japan time (Imperial Ordinance No. 167 of 1895, in force from 1 January 1896 to 30 September 1937); the source does not say which time its Taiwanese tables use, so they are not converted. If these values are interpreted as Taiwan time, add 60 minutes to convert them to Japan time.

### 8. Station and line names

#### Names as printed

Station and line names are as transcribed from the source, in Japanese script only; romanized names are not provided. The railways in Korea are named as printed (滿鐵京仁線 and so on).

#### Old and new character forms

Station and line names contain both old and new character forms (for example, the station names in `stops.txt` include 驛, 鐵 and 靑 beside 青 and 横). In small type the scans do not always show whether the old or the new form is printed. To check the accuracy of the published transcription, 60 station names were sampled at random from 20 of the 178 workbooks (3 of them transcribed by hand) and compared with the source: two were transcribed in the modern form where the source prints the old one (青森 for 靑森, 横手 for 橫手; both on p. 126, transcribed by LLM agents). All pages were also checked against the scans by hand, but similar cases may remain.

Where a station name or line name is spelled with both the old and the new form of a character whose two forms this dataset treats as the same character, one spelling is used for every station or line of that name: the spellings are first unified within each line to the more frequent one, and then across lines to the one that is then more frequent. A station can therefore appear in a form that its own pages do not print (for example 大內 of 宇和島鐵道線 is given as 大内, the form of 大内 of 國東鐵道線); other variant spellings (for example 瀬峯 and 瀬峰, and 本郷 and 本鄕, which are different stations) are kept as transcribed.

To search for a station using its modern spelling, consult `extras/stop_name_variants.csv`, which gives each name in modern character forms and the spellings printed in the transcription.

#### Region tags and regions of lines

Stations of the same name in different regions are distinguished by a region tag, such as `〈朝鮮〉`, added to the station name; the region tag `〈嚴島〉` marks the island port 宮島〈嚴島〉, across water from the station 宮島 of 山陽本線 (see 3 above).

The region assigned to each line is recorded in `extras/route_region.csv` (the GTFS files keep to the standard fields); Hokkaido (北海道) is given separately from 内地, although it was part of Japan proper.

#### Composite line names

The source often prints one band for trains that run over two or more lines, under a composite line heading such as 東海道及山陽本線. Where a band can be divided at a boundary station, its trips are assigned to the routes of the component lines. Some trips stay on a route named by the composite heading: where the band cannot be divided at a single station (for example 臺灣總督府鐵道縦貫線及臺中線, a band that leaves one line for another and returns to it), and where the band is the only place in the feed that keeps a through ride or a printed time (see section 4 of `KNOWN_ISSUES.md`). Their times and stops are as printed.

### 9. Identifiers

Identifiers take the forms `ST…` for `stop_id`, `PS…` for parent stations, `RT…` for `route_id` and `TR…` for `trip_id`.

To build the GTFS data, trips were told apart by a name that joins the line name, the direction (`outbound` or `inbound`) and the train number with `__` (for example `東海道本線__outbound__1`). This name is called the "trip key". Where no train number is printed, the train-number part is a provisional name beginning with `U`, and a second trip with the same number is marked with a suffix such as `_b`. Trip keys are in the columns `gtfs_trip_key` or `trip_key` of `extras/trip_source.csv` and other tables. Unlike `trip_id`, a trip key may change in later versions when a line name or train number is corrected.

### 10. Train numbers

`trip_short_name` contains the train number printed in the source. It is empty when the source prints no number (common on tramways and ferries). For some trips the number is not printed above the column itself but is carried over from another band or sheet that prints the same train (`trip_num_source` `inherited_same_line` or `inherited_diff_line` in `extras/trip_source.csv`; see "Provenance of times, train numbers and coordinates"). Train types (特急, 急行), classes and sleeping-car and dining-car marks are in `extras/trip_attributes.csv`.

### 11. Line shapes

#### Polylines for maps (`extras/route_lines.geojson`)

The line shapes are in `extras/route_lines.geojson`, for drawing maps: one line per line name that joins its stations in running order, with straight segments between stations, leaving out the segments where express trains skip stations; branches are separate parts of a `MultiLineString`. Its properties are `route_short_name`, `route_ids` (the routes of that name, separated by spaces; routes of frequency-only services are not included), `structure` (`path`, `branched`, `cycle` or `disconnected`), `n_stops`, and `length_km` (the total length of the segments). All its points are station coordinates in `gtfs/stops.txt`. These geometries do not represent the actual tracks and should not be used to measure trip distances.

#### Why `shapes.txt` is not included

The `gtfs/` feed does not include `shapes.txt`. These lines are a single line per route and do not follow trips on branches or through services, so as `shapes.txt` they would make tools measure trip lengths along the wrong path. Without shapes, tools draw straight lines between consecutive stops.

### 12. Use with OpenTripPlanner

#### Loading the feed and required settings

OpenTripPlanner 2.10 can load the feed without street-network data (checked with 2.10.0). Required settings: `transitServiceStart` and `transitServiceEnd` in `build-config.json` must include 1925 (by default every trip is dropped as out of period), and `routingDefaults.maxJourneyDuration` in `router-config.json` must be longer than the default 24 hours (see 1 above; the settings provided use 96 hours, enough for the journeys in the examples).

#### Journeys with long waits (`searchWindow`)

For journeys with long waits, before departure or at a connection, widen `routingDefaults.searchWindow` (for example to `"PT24H"`): among journeys with the same arrival, OpenTripPlanner returns the one that leaves latest, and if that departure falls outside the window it returns no journey. For example, for 東京 to 哈爾賓〈滿洲〉 on 1 April 1925 at 08:00, the train from the railway station 東京 that reaches 哈爾賓 earliest leaves at 20:30, so the journey is found only with a window longer than 12.5 hours.

#### Transfer settings

OpenTripPlanner does not generate transfer connections directly from `transfers.txt`. It generates its own walking transfers (from a street network or, without one, by straight-line distance between stops within `maxTransferDuration`, default 30 minutes) and uses `transfers.txt` only for the times of the transfers it has generated. Set `maxTransferDuration` in `build-config.json` to 45 minutes or more so that every pair in `transfers.txt` is generated (the farthest pairs are 3.1 km apart), and set `"otpFeatures": {"MinimumTransferTimeIsDefinitive": true}` in `otp-config.json` with `routingDefaults.transferSlack` `"PT0S"`, so that 0-minute transfers are not given 2 extra minutes (the source prints connections whose arrival and departure are in the same minute). For journeys with many changes of train and ship, raise `routingDefaults.maxNumberOfTransfers` above its default of 12 (the settings provided use 30).

#### Differences from `examples/route_1925.py`

OpenTripPlanner also generates walks between stations that are not paired in `transfers.txt`, based on the coordinates in `gtfs/stops.txt`, so its journeys can differ from those of `examples/route_1925.py`. No setting limits it to the transfers in this file: without its own walks, even the transfers within a parent station are lost. It also treats `exact_times=0` frequencies as a wait of a full headway, counts a through train that changes route as a transfer (see 4 above), and, without street data, cannot start or end a stop-to-stop search with a walk to another station.

### 13. Route types

`route_type` is `2` (rail) for all railways, including tramways and light railways (軌道), and `4` (ferry) for shipping services.

## Validation with gtfs-validator

MobilityData's gtfs-validator 8.0.1 reports no errors for `gtfs/`, but it produces the following warnings:

| Notice | Reason |
|---|---|
| `expired_calendar`, `feed_expiration_date7_days`, `trip_coverage_not_active_for_next7_days` | The feed describes historical services. |
| `mixed_case_recommended_field` | Names use Japanese characters; the check assumes Latin script. |
| `missing_bike_allowance` | Bicycle carriage is not applicable here. |
| `route_short_name_too_long` | Route names retain their printed forms. |

## Provenance of times, train numbers and coordinates

Each printed stop time in `gtfs/stop_times.txt` can be traced to a transcription cell, and each computed time or time of a template trip to the page and table it is based on. A time copied from the other time at the same stop has no separate source cell. Every station coordinate can be traced to its source (a computed position, to the printed mileages and the neighboring stations it was computed from). The transcription sheets are named `p<page>_tb<table>-<band>[-<segment>]` (the `table_id`).

### Stop times

**`timepoint` in `gtfs/stop_times.txt`** (standard GTFS field): `1` when at least one of the stop's times is printed in the source; `0` when the times are approximate, that is, computed from printed values (listed in `extras/estimated_stop_times.csv`), part of a template trip of a frequency-based service (`gtfs/frequencies.txt`), or empty.

**`extras/stop_time_source.csv`**: the provenance of each time in `gtfs/stop_times.txt`. Each row corresponds to a row of `gtfs/stop_times.txt`, in the same order (key: `trip_id`, `stop_sequence`).

| Column | Meaning |
|---|---|
| `arrival_source`, `departure_source` | `printed`: the time is printed in the source. `copied`: the source prints one time for this stop; GTFS requires both, so the other one is set equal (its page, sheet, column and row are empty; they are given for the printed time). Equal times therefore do not mean a stop of zero minutes. `computed`: calculated from printed values (see `basis`). `template`: a time of a template trip of a frequency-based service (see note 5 above). Empty: no time. |
| `arrival_page`, `arrival_sheet`, `arrival_column`, `arrival_row` (and `departure_…`) | Where the printed time is: the page of the 1925 volume (the page where the table begins; a table printed across two facing pages, such as pp. 9–10, gives the left-hand page even for times printed on the right-hand page), the transcription sheet, the column (the `trip_id` in row 7 of the sheet) and the row (the `stop_order` in column A). For `template` rows of a box such as "此間12分毎ニ運轉", the printed time of the train whose running times the template copies. For `computed` rows, the page and sheet that print the running time. |
| `arrival_time_system`, `arrival_jst_offset_min` (and `departure_…`) | For services abroad: the time system the source prints (for example 南滿洲及支那沿岸時刻) and the minutes added to give Japan time (see "Time zones" above). The printed time is the GTFS time minus this offset. `注記なし` means that the source states no time system for that service abroad (Taiwan, the Russian Far East, ports overseas); the time is as printed and the offset is empty. |
| `basis` | For computed and template rows, and for the stops without times of template trips: what the times are based on (for a frequency-only service, its `FQ…` identifier). |

The `printed` times are made from the transcribed values: converted to the 24-hour clock, counted past 24:00 after midnight (note 2 above), and converted to Japan time where the source uses another time standard (note 7 above). Where a digit could not be read with certainty in the scans (3, 8 and 9 in bold type are often alike), the reading that fits the neighboring trains and the other pages that print the same train was taken. A few transcribed values were corrected because they were judged to be misprints in the source; this was done only when other printings of the same train or the running times of neighboring trains established the correct value beyond reasonable doubt. The corrected values are also in the transcription, so the printed values are found only in `extras/misprint_corrections.csv`, together with the reasons (see "Files" above).

### Train numbers

**`trip_num_source` and `trip_num_sources` in `extras/trip_source.csv`**: how the train number of the trip was determined, taken from the transcription columns that contribute its printed times. `explicit_section` (printed at the head of the band), `explicit_header` (printed in the table header), `inherited_same_line` (carried over from another sheet of the same line and direction), `inherited_diff_line` (carried over from another line in the same table), `uncertain` (not printed and not determined; such trips have an empty `trip_short_name`). `trip_num_source` is the strongest value in this order; `trip_num_sources` lists every value, strongest first, separated by `|`. Both are empty for template trips.

### Station coordinates

**`extras/stop_coord_source.csv`**: the provenance of the coordinates in `gtfs/stops.txt`. Each row corresponds to a row of `gtfs/stops.txt`. Stops that appear only in `extras/single_stop_trips.csv` (trips with only one timed stop) are not in `gtfs/stops.txt`, so they have no row here (in this version, 青島〈支那〉 and 出雲今市). Their coordinates are the same as those of a stop of the same name in `gtfs/stops.txt`, and the row of that stop gives the source.

| Column | Meaning |
|---|---|
| `coord_class` | `station`: the position of the station itself, from a cited record. `place`: a representative point of a place or facility (neighborhood, village, port, shrine), not of the station itself; the point can come from a Wikipedia article on a town, a port or another station (for example a present-day station nearby), linked in `reference_id`. `estimated`: a computed position. `unrecorded` (not used in this version): the origin of the position was not recorded; a `reference`, if given, is a record the position agrees with. For ports, the landing place itself (a port or pier point on a map) counts as `station`. |
| `coord_method` | `station_article` (a station article in Wikipedia), `wikidata_station`, `n02_station` (MLIT railway data N02-25), `historical_gazetteer_station` (a station on a former 1:50,000 map, from the Historical Place Names Data), `topographic_map_reading` (read by the project from a former topographic map on Konjaku Map on the Web; `reference_label` gives the region, period, sheet and edition of the map), `station_point` (as `station_article`, but the title of the article is not recorded in `reference_label`), `place_point` (a representative point taken from the cited record: a place or facility, or the point of a station used for a port that ships call at or for a nearby stop), `wikidata_item` (a Wikidata item that is not the 1925 station), `adjacent_station` (placed at the position of another stop in this dataset, given in `reference_label` and `reference_stop_id`: a tram stop in front of a station, a station of another railway at the same place, or a stop placed at a port), `interpolated_mileage` (placed between neighboring stations in proportion to the mileages printed in 1925), `interpolated_track` (the same, along the present-day track in N02-25), `interpolated_order` (equal spacing along the stops listed in the source, which prints no mileage), `computed_position` (computed from neighboring stations), `unrecorded` (not used in this version), `parent_station` (a parent station takes the coordinates of `reference_stop_id`). |
| `reference`, `reference_id`, `reference_label` | The source, its identifier and the name of the item. Identifiers are permanent links to a Wikipedia or Wikidata revision, Wikidata item links, N02-25 station codes (`N02_005c`), 大字・町丁目コード of the MLIT address points, IDs of the Historical Place Names Data, GeoNames links, the frequency-only service (`FQ…`) whose listed stops were used, or, for points read on GSI Maps, the address of GSI Maps (`https://maps.gsi.go.jp/`). Empty for parent stations (see `reference_stop_id`). |
| `reference_distance_m` | Distance in meters between the coordinates in `gtfs/stops.txt` and the coordinates given in the referenced record, when the record gives coordinates. |
| `checked_within_km` | For positions that were accepted only after comparison with another record of the station's position (mostly representative points and estimated positions, and some station positions, most of them from Wikidata): the largest distance allowed in the comparison, in km. |
| `reference_stop_id` | For `adjacent_station` and `parent_station`: the stop whose coordinates are used. |
| `reference_note` | For a few positions, how the value was read from the cited source: `read from the coordinate field of the cited source with an obvious typo corrected`, `a coordinate given in the body of the cited source, not its main coordinate`, or `the cited revision shows this coordinate from Wikidata; it is not written in the revision text` (the article displays the coordinate held in Wikidata, which may change after the cited revision). Empty otherwise. |

The representative points and interpolated positions in this dataset were derived only from the sources listed under "Station coordinates and their sources" in `README.md` and the mileages printed in the 1925 timetable.

## Details of the derived tables (`extras/`)

This section describes the columns of ten tables in `extras/`: computed times (`estimated_stop_times.csv`), trips with a single timed stop (`single_stop_trips.csv`), regions of lines (`route_region.csv`), train types and headings (`trip_attributes.csv`), headway boxes (`frequency_box.csv`), frequency-only services (`frequency_sections.csv` and `frequency_only.csv`), frequencies of ferry services (`service_frequency.csv`) and operating days (`operating_days.csv` and `printed_sailings.csv`). They preserve information from the source that cannot be represented in the standard GTFS files. Text copied from the source is as transcribed; free text (such as notes) is in Japanese.

All of these tables except `route_region.csv` and `frequency_only.csv` have a `trip_id` column for the trip: a trip in `gtfs/trips.txt`, or, for a trip moved to `extras/single_stop_trips.csv`, the trip in that table.

### Computed times and trips with a single timed stop

#### `extras/estimated_stop_times.csv`

The approximate times in `gtfs/stop_times.txt` that are not printed in the source but computed from printed values (see 6 above). Each row corresponds to a row of `gtfs/stop_times.txt` with such times; the columns are `trip_id`, `stop_id`, `stop_name`, `stop_sequence`, `arrival_time` and `departure_time` (as in `gtfs/stop_times.txt`), `kind` (`departure_only_terminal` or `frequency_section_template`), `basis` (what the time was computed from) and `source_sheet` (the transcription sheet of the table).

#### `extras/single_stop_trips.csv`

The trips that have only one stop with a time and are therefore not in `gtfs/`, with their printed times. Each row represents one trip; the columns are `trip_id`, `route_id`, `line_name`, `direction_id`, `printed_number`, `gtfs_trip_key`, the stop (`stop_id`, `stop_name`, `stop_lat`, `stop_lon`), its `arrival_time` and `departure_time`, and `source_sheet`. A route or stop used only here is not in `gtfs/`.

### Lines and trains

#### `extras/route_region.csv`

The region of each route in 1925. Each row represents one route of `gtfs/routes.txt`; the columns are `route_id`, `route_short_name` and `route_long_name` (as in `gtfs/routes.txt`), and `region` (see "Files" above).

#### `extras/trip_attributes.csv`

The train type (特急, 急行), classes, sleeping-car and dining-car marks and other information printed in the column heading of each trip. Each row represents one printed trip (template trips are not included).

| Column | Meaning |
|---|---|
| `trip_id`, `trip_key`, `line_name`, `direction`, `trip_num` | The trip, and the trip key (see note 9 above) and its parts (line name, direction, train number). Where sailings with the same times were merged into one trip (see 1 above), several rows share a `trip_id` and differ in `trip_key`. |
| `kind` | `特急` (limited express) or `急行` (express) when the heading of the column marks the train as such; empty otherwise. |
| `classes` | Classes of accommodation printed (for example `1.2.3` for first, second and third class). |
| `sleeper`, `diner` | `1` when the heading marks a sleeping car (寝) or a dining car (食). |
| `label_header`, `label_section` | The heading printed at the top of the column and at the start of the band, as transcribed (`\|` separates the headings of different sheets). |
| `other_tokens` | Parts of the heading not read as a type, class or number (for example 不 for irregular trains, 直, a ship's name). |
| `source_sheets`, `note` | Transcription sheets; notes in Japanese, for example where a heading was taken from another printing of the same trip that was not used for its times (表頭の表記は、時刻には使わなかった同じ便の別の掲載（シート）から), or where a printed heading was not used because its number does not match the trip (便の番号と合わないので使わなかった表頭の表記). |

### Headway boxes and frequency-only services

#### `extras/frequency_box.csv`

The source text of the headway boxes such as "此間12分毎ニ運轉" printed between two columns of a timetable, and how each was read into `gtfs/frequencies.txt` (see 5 above). Each row represents one box. The transcription has an empty column where the box is.

| Column | Meaning |
|---|---|
| `box_id`, `page`, `sheet`, `columns` | Identifier (`FB…`), page, transcription sheet, and the empty column(s) (`trip_id` in row 7 of the sheet) that stand for the box. |
| `line_name`, `direction`, `direction_raw` | The line name of the table, its direction (`outbound` or `inbound`, as in the trip keys) and the direction as printed (for example 下リ, 高崎行). |
| `kind` | `①間隔` (a headway), `②毎時○分` (at a set minute past each hour), `②毎時各分` (every hour, at minutes not given), `③ノモノアリ（列挙）` (departure times listed in the box), `③ノモノアリ` and `対象外` (not converted). |
| `service_kind` | The type or destination of the trains in the box, when printed (for example 急, 可部行). |
| `interval_min_lo`, `interval_min_hi`, `minute_of_hour` | The headway in minutes (a range when printed as one) and the minute past the hour. |
| `anchor_stop`, `window_start`, `window_end` | The station the times refer to and the period covered, from the printed trains before and after the box. |
| `prev_column`, `next_column`, `prev_trip_key`, `next_trip_key` | The printed trains before and after the box (columns of the sheet and trip keys). |
| `template_trip_key`, `template_seq_from`, `template_seq_to` | The printed train whose running times the template trip copies, and the stops copied. |
| `trip_id` | The template trip in `gtfs/trips.txt`; empty when none was made (see `note`). |
| `gtfs_start_time`, `gtfs_end_time`, `headway_secs`, `exact_times` | The values written to `gtfs/frequencies.txt`. |
| `est_trips` | The estimated number of departures in the period (for reference; no trips are made for them). |
| `memo_raw`, `source`, `note` | The transcriber's note on the box, quoting the source; how the box was read (`memo`: from that note, `override`: read by hand from the source); notes. |

#### `extras/frequency_sections.csv`

How the frequency-only services were read into `gtfs/frequencies.txt` (see 5 above). Each row represents one direction of one service. A service that could not be converted as read but was given an estimated template trip has the rows as read (`trip_id` empty, with the reason in `note`) and an added row for each direction (`source` `estimate` or `estimate_ship`). Where only a printed running time was replaced by an estimate, the row itself has `source` `estimate`.

| Column | Meaning |
|---|---|
| `section_id` | The frequency-only service in `extras/frequency_only.csv` (`id`). |
| `page`, `line_name`, `direction` | Page, line name, and the direction of the template trip (`outbound` or `inbound`; may be empty for a service that was not converted). |
| `origin`, `destination`, `stations` | The end stations and the stations listed from one to the other. |
| `first_dep`, `last_dep`, `duration_min`, `pm_reading` | First and last departures from `origin` and the running time, as read, and how a.m. and p.m. were read (the source prints p.m. times in bold). |
| `interval_min_lo`, `interval_min_hi`, `headway_secs`, `exact_times`, `est_trips` | The printed headway in minutes, the values written to `gtfs/frequencies.txt`, and the estimated number of departures. |
| `trip_id` | The template trip in `gtfs/trips.txt`; empty when the service was not converted (see `note`). |
| `source`, `note` | `csv`: read from the source text; `estimate` and `estimate_ship`: the running time or the order of calls is not printed and was estimated (the basis is in `note`); `override`: corrected by hand. One service is `estimate` although a running time is printed: 惠美須町—宿院 of 阪堺線 (`FQ055`) prints about 6 minutes (約6分), which cannot be right for about 9 km and does not fit the other services of the same table, so 30 minutes is used; the printed value remains in `extras/frequency_only.csv` (`duration_raw`). |

#### `extras/frequency_only.csv`

The source text of the services printed as text without a timetable grid (first and last departures, headway, running time), the frequency-only services. Each row represents one service (some rows are other notes printed outside a grid). Most are tramways and city lines. This table was transcribed separately from the timetable sheets and was not part of the page-by-page human check.

| Column | Meaning |
|---|---|
| `id`, `page`, `position` | Identifier (`FQ…`), page, and position on the page. |
| `type` | `頻度だけを記した運行（時刻の格子なし）` for a frequency-only service (no timetable grid). The other values are text printed with a timetable: notes printed outside a grid (`格子の外の注記…`), a table that prints only first and last departures and a headway box (`頻度記載…`; the one of p. 36 is read into `extras/frequency_sections.csv`), and a grid whose times are in the transcription (`格子あり…`). |
| `line_name_raw`, `section_raw`, `text_raw` | The line name, the heading of the service and the full text as printed (line breaks as ／). |
| `stations` | The stations listed in the source (separated by ・; marks such as △ as printed). |
| `distance_fare_raw`, `first_last_raw`, `interval_raw`, `duration_raw` | The printed mileage and fare, first and last departures, headway, and running time. |
| `already_sheet` | The transcription sheet of the same table, if any (`N` or 無し: none). A few values add a short note in brackets, for example that the wording is copied into the note row of a transcription sheet. |
| `confidence`, `note` | Confidence of the reading (高 high, 中 medium; for 中 the `note` names the characters that could not be read); notes. |

### Ferry frequencies and operating days

#### `extras/service_frequency.csv`

How often each ferry trip sails, as stated in the source (daily, every other day, on fixed days of the month, and so on). Each row represents one combination of a ferry trip and a transcription sheet on which it appears.

| Column | Meaning |
|---|---|
| `trip_id`, `trip_key`, `line_name`, `direction`, `trip_num` | As in `extras/trip_attributes.csv`. |
| `frequency_kind` | `毎日` (every day), `隔日（偶數日）` / `隔日（奇數日）` (alternate days: even or odd dates), `毎月（指定日）` (set days of the month), `月に数便（列ごとに月日が刷られている）` (a few sailings a month with dates printed in each column; see `extras/printed_sailings.csv`), `記載なし` (not stated). |
| `frequency_raw`, `exceptions_raw` | The printed wording of the frequency and of days without service (for example 但毎週月曜日ニハ休航). |
| `source_sheet`, `table_name`, `direction_raw` | The transcription sheet, the table title and the direction as printed. |

#### `extras/operating_days.csv`

What the source prints about the operating days of trips not described as daily (see 1 above). Each row represents one trip. In `calendar.txt` these trips also run every day.

| Column | Meaning |
|---|---|
| `kind` | `printed_dates` (sailings of the dated shipping tables, pp. 189–192), `monthly` (set days of the month), `monthly_days_not_printed` (monthly, but the days of the return sailing are not printed), `alternate_days` (even or odd dates), `daily_except` (every day except printed days), `irregular` (trains marked 不; no operating days are printed). |
| `operating_days` | The days in machine-readable form: for `printed_dates`, the service dates separated by `;`; for `monthly`, `day:`*d* (several days separated by `,`); for `alternate_days`, `even` or `odd`; for `daily_except`, `except_day:`*d* (`last` is the last day of the month) or `except_weekday:`*day* (for example `Mon`); empty for `irregular` and `monthly_days_not_printed`. |
| `n_sailings` | For `printed_dates`, the number of sailings carried by the trip. |
| `printed_text`, `source_sheets`, `note` | What the source prints (for dated sailings: ship and dates at each port, joined by →), the transcription sheets, and a note. |

#### `extras/printed_sailings.csv`

For the sailings of the dated shipping tables (pp. 189–192), the dates printed for each port and the trip that represents each sailing (see 1 above). Each row represents one sailing.

| Column | Meaning |
|---|---|
| `sailing_id`, `page`, `source_sheet`, `column` | Identifier (*sheet*`#`*column*), page, transcription sheet and column. |
| `table_name`, `line_name`, `direction_raw` | Table heading, company line and direction as printed. |
| `ship`, `ports`, `printed_dates` | The ship's name, the ports of call and the date printed for each port (`\|` separates ports; an empty date means none is printed; `・` separates the dates of arrival and departure at one port). |
| `service_date` | The service date of the trip that carries the sailing: the date printed at the first stop that the sailing uses (`stop_sequences`), minus one day for each 24 hours in that stop's time (長崎 printed 4.5 with the time 33:00 gives 1925-04-04). It is used as the service date in `tools/make_printed_days_gtfs.py`. |
| `trip_id`, `stop_sequences` | The trip in `gtfs/trips.txt` that carries the sailing and the stop sequences it uses; empty when the sailing has no trip. |
| `how` | `own_trip` (the trip was made from this sailing), `merged_same_times_in_table` / `merged_same_times_same_company` / `merged_same_times_other_line` (the sailing has the same printed times as a sailing in the same table, of the same company, or of another company, and shares its trip), `no_printed_times` (no printed time, for example only 午前/午後; no trip), `dropped_single_stop` (one printed time; it is kept as a one-stop trip in `extras/single_stop_trips.csv`, and `trip_id` is empty). |
| `table_note`, `note` | Notes on the table and on the sailing. |

## Route-search network

`tools/make_router_data.py` builds, from `gtfs/` and `extras/` only, a route-search network: `router_data.json`, and `router_data.js` with the same data for a web page. Given the same feed, the script produces byte-identical files. The network introduces no additional transport information; it reorganizes the feed into a form that a journey planner can search directly.

### How the network is built

- Stations are the parent stations of `gtfs/stops.txt`. A journey may change trains within a station, and between stations only along the walking transfers of `gtfs/transfers.txt` (see 3 above).
- Each trip becomes a list of stations with times. Each template trip of `gtfs/frequencies.txt` is repeated from `start_time` every `headway_secs` until `end_time`; these runs are marked as estimated. In such a run, consecutive stops in the same station are merged into one.
- Trips listed under the same `physical_train_id` in `extras/physical_trains.csv` carry that identifier, so that staying on the train across a line boundary is not counted as a transfer (see 4 above).

### Contents of `router_data.json`

| Key | Contents |
|---|---|
| `groups` | Stations: `{stop_id: {"name", "lat", "lon"}}` for each parent station. |
| `name_to_groups` | `{name: [stop_id, …]}` for every stop name, including stop names that differ from the name of their station. One name may belong to stations far apart. |
| `trips` | One object per trip and per estimated run: `k` the trip key (`gtfs_trip_key` in `extras/trip_source.csv`; an estimated run adds `_freq` and a number), `t` the `trip_id` (for an estimated run, its template trip), `l` the line name, `d` `outbound` or `inbound`, `n` the train-number part of the trip key (as `original_trip_short_name` in `extras/trip_source.csv`) or, for an estimated run, the printed frequency (for example 此間12分毎), `s` the stations in stop order, `dep` and `arr` the departure and arrival times (`HH:MM`; `null` when not given; times of 24:00 and later continue the day on which the trip started), `est` 1 for an estimated run, `sn` stop names that differ from the station name (by position in `s`), `p` the `physical_train_id`. |
| `walks` | `{stop_id: [[stop_id, minutes], …]}`: walking transfers between stations. |
| `router_params` | Search rules to be applied by a program that searches this network (for example, among journeys with the same arrival, prefer fewer transfers). |
| `meta` | `source` (the name of the dataset), `feed_version`, and the numbers of stations and trips. |

Arrival times computed for departure-only trips (`extras/estimated_stop_times.csv`) are not marked in this file; use `t` and the `timepoint` column of `gtfs/stop_times.txt` to find them.
