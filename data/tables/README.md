# Manually curated tables (data/tables/)

Tables made by reading the source, which the build reads. Some column names and the text columns are in Japanese. Besides the keys and values that the code reads, the tables keep records for readers (page, sheet, grounds and notes).

The last column lists the scripts that read each table directly; others read the copies those scripts write.

| File | Contents | Read by |
|---|---|---|
| `renumbering.csv` | Trains whose number changes partway along one printed column: from the given station on, the stops get the new number (and, where given, a new line name) | `scripts/extract_stop_times.py`, `scripts/split_combined_trips.py` |
| `time_system_rules.csv` | Sheets, lines and stations printed in local time (South Manchuria and the China coast, Harbin), with the offset to Japan time | `scripts/time_system.py` (used by `scripts/extract_stop_times.py` and `scripts/build_gtfs_extras.py`) |
| `through_trains/link_judgments.csv` | Judgments, made by looking at the source, of whether the trips before and after a line boundary are the same train (`verdict`) | `scripts/split_combined_trips.py` (reads `from_trip_key`, `to_trip_key` and `verdict`) |
| `through_trains/physical_trains.csv` | Trains that run through several lines, built from the judgments above: the trips of each train in order | `scripts/generate_gtfs.py`, `scripts/generate_router_data.py`, `scripts/build_release_gtfs.py` (copied to `extras/physical_trains.csv` of the dataset) |
| `arrival_departure_rows/actions.csv` | Stations printed with an arrival row and a departure row that belong to different trains (a transfer mark or separate columns in the source): the trip to drop or to split | `scripts/split_combined_trips.py` |
| `arrival_departure_rows/merges.csv` | Stations printed with an arrival row and a departure row of the same train: the pairs merged into one stop | `scripts/split_combined_trips.py` |
| `departure_only_running_times.csv` | Tables that print only the departure at the first stop: the printed running time to the terminal, used to add the arrival there | `scripts/build_release_gtfs.py` |
| `frequency_box_overrides.csv` | Corrections to the reading of the "every N minutes" boxes of the source | `scripts/build_frequency_box.py` |
| `frequency_only/frequency_only.csv` | Text of the services printed only as frequency notes (first and last departures, interval, running time) | `scripts/build_frequency_sections.py`, `scripts/build_gtfs_extras.py` (copied next to the GTFS feed, and from there to `extras/frequency_only.csv` of the dataset) |
| `frequency_only/frequency_sections_estimates.csv` | Estimated times for frequency-only sections whose running time or times are not printed, with the grounds | `scripts/build_frequency_sections.py` |
| `frequency_only/frequency_sections_overrides.csv` | Corrections to the text of frequency-only sections | `scripts/build_frequency_sections.py` |
| `misprints.csv` | Cells corrected as misprints of the source, with the printed and the corrected values | `scripts/build_release_gtfs.py` (copied to `extras/misprint_corrections.csv` of the dataset) |
| `sailing_dates.csv` | Sailings printed with dates: ship, ports and printed dates | `scripts/release/operating_days.py` |

The `png` column of `through_trains/link_judgments.csv` names the cropped images of the source that were looked at for each judgment. The images are not included in this repository.
