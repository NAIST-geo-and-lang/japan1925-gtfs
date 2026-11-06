# Coordinate tables (data/knowledge/places/)

The master copy of the coordinates of stations, ports and stops. It holds only values that can be published. `scripts/agent_knowledge.py` looks up coordinates in these tables, and both `scripts/run_pipeline.sh` (the pipeline from the timetable to GTFS) and `scripts/release/build_release_all.sh` (the published dataset build) use them. The tables are checked when they are loaded, and a run stops if they break the rules.

Sources are recorded not as free text but as fixed terms and identifiers. The rules for the terms and identifier formats, for the combinations of use, point kind and coordinate kind, and for building the columns of the published coordinate source table (`extras/stop_coord_source.csv`) are in `scripts/kb_sources.py` (the published source table is not written by hand; it is built from these tables by rule). `scripts/kb_source_coords.py` looks up the coordinates of the cited source records by identifier (used by the coordinate gate, step 4e of `build_release_all.sh`).

All four tables are UTF-8 with BOM and CRLF line endings.

## places.csv — places table

One row per coordinate value, with one source per point. A place that no query uses is not allowed (loading stops).

| Column | Contents |
|---|---|
| `place_id` | Place number (e.g. `P00001`). Never changed once assigned; removed numbers are not reused |
| `lat`, `lon` | Latitude and longitude (WGS 84). Finite numbers within the extent of the timetable (latitude 20–55, longitude 105–150) |
| `point_kind` | What the point is: `station` (the station's own position; for a port, the landing place itself), `place` (representative point of a place or facility), `estimated` (calculated position) |
| `source_type` | Kind of source: `wikipedia_ja`, `wikipedia_zh`, `wikipedia_ko`, `wikipedia_ru`, `wikipedia_en` (a revision of a Wikipedia article), `wikidata`, `n02` (National Land Numerical Information N02-25, present-day railways), `isj` (Location Reference Information, 大字・町丁目位置参照情報), `isj_teishajo` (the same, with the 大字 chosen from 『鐵道停車場一覽』, 1926), `gazetteer` (Historical Place Names Data), `geonames`, `topo` (reading of an old topographic map), `gsi` (reading of GSI Maps), `computed` (calculated from neighboring stations with the 1925 mileages), `computed_track` (the same, along N02-25 railway lines), `printed_order` (in sections without mileages, evenly spaced by the printed station order) |
| `source_id` | Source identifier: Wikipedia revision number (oldid), Wikidata Q number, N02 station code (`N02_005c`), 大字・町丁目 code, Historical Place Names Data ID, GeoNames ID, frequency-only section number (`FQ…`). Empty for kinds without identifiers (`topo`, `gsi`, `computed`, `computed_track`) |
| `source_rev` | Wikidata revision number (when citing the revision that holds the value; otherwise empty) |
| `source_item` | What the source item is: `station` (a station item) or `place` (a place or facility item). Required for the Historical Place Names Data (it decides the method shown in the published dataset) |
| `label` | Name of the source item (article title, "station (line, company)" in N02, 大字 name, "name (attribute)" in the Historical Place Names Data, etc.). For map readings, a description of the map (area, period, sheet name, edition) |
| `distance_m` | Distance (m, integer) between the published coordinate and the coordinate of the source record. Empty if the source has no coordinate |
| `source_read` | How the source value was read: empty (the source's coordinate itself), `corrected_typo` (read from the source's coordinate field with an obvious typo corrected; e.g. 鞆), `body_coordinate` (a coordinate given in the article body, not in its coordinate field; e.g. 千葉), `wikidata_display` (the cited revision has no station coordinate in its text and the article displays the Wikidata coordinate: an empty `{{Coord}}` or an empty coordinate field in the station infobox). Output as a fixed English sentence in `reference_note` of the published dataset. For places with a value here, the gate does not compare `distance_m` with the source record; it checks the value according to the reading (see `scripts/release/check_coord_allowlist.py`) |
| `names` | Names of the stations that use this place (without 〈region〉 tags; for readers, not used for lookups) |
| `same_point_names` | The number of `names`: how many station names (without 〈region〉 tags) the queries using this place have. Counts not only rows using the point as their own position but also borrowing rows (`adjacent`) and representative-point rows (`place`) |
| `checked` | Result of the value check, in Japanese (copied from the coordinate gate, step 4e; places edited since then read "未確認", unchecked) |
| `checked_detail` | The publishable point used for the check |
| `edited` | Mark left when the row was edited (date and command; only on edited rows). The command named there, `edit_places.py`, is the editing tool used while the tables were made; it is not included in this repository |

## stop_place.csv — stop-place table

One row per query, "station name + line name", as printed in the timetable. Station and line names are as transcribed (with 〈region〉 tags and old character forms). Coordinates are looked up in this table, never by name: other lines of the same station, old-form names, names before a tag was added (names used during integration) and station names before a correction each have their own row pointing to the same place. In a rebuild (`AGENT_KNOWN_STRICT=1`, set by `scripts/kb_places_env.sh`), a query missing from this table stops the run.

| Column | Contents |
|---|---|
| `stop_name`, `line_name` | The query (neither empty, no leading or trailing spaces) |
| `place_id` | Place number. Empty = station without coordinates (interpolated with the 1925 mileages) |
| `coord_source` | Source of the assigned coordinates (written as is to `coord_source` in `stops_master.csv`): `agent_known` (a value from the coordinate tables), `release_proxy` (replaced by the representative point of a place that is not a station; only rows with `coord_kind` = proxy), `wikidata` (replaced by a Wikidata station item; only rows using a Wikidata station item as their own position), `legacy:wikipedia_ja` (a value taken from a Wikipedia station article by an earlier method) |
| `coord_kind` | Coordinate kind (decides interpolation anchors and how reliable station groups are), determined by use and point kind (see "Rules" below). Empty or `unknown` for rows without a place |
| `tolerance_km` | Tolerance allowed when checking the coordinates (km, positive) |
| `use` | How the point is used: `self` (the point is the station's own position), `adjacent` (borrows the point of another station in this data: a stop in front of a station, a station of another railway at the same place, a station borrowing a port point), `place` (the point serves as the representative point of a place, port or station front: a ship's port of call using a railway station point, a stop in front of a station using the point of another record) |
| `ref_stop` | For `use` = `adjacent`, the station whose point is borrowed ("station\|line"). The target must point to the same place and be a row that uses it as its own position or as a representative point (not a borrowing row, not the row itself) |
| `checked_within_km` | Range (km) used when the point was checked against station positions that are not published |
| `note` | Note for readers (**not read by the code**) |
| `matched_by` | Record of how the mapping was decided (some rows name `edit_places.py`, the editing tool, which is not included in this repository) |

### Rules (`scripts/kb_sources.py`; checked when the tables are loaded)

| Use | Point kind | `coord_kind` |
|---|---|---|
| `self` | `station` | `authority` |
| `self` | `place` | `proxy` (or `place_unverified`) |
| `self` | `estimated` (`computed`, `computed_track`) | `derived` |
| `self` | `estimated` (`printed_order`, evenly spaced by printed order) | `proxy` |
| `adjacent`, `place` | any | `proxy` |

The columns of the published coordinate source table are built by rule from the source in the places table and the use in the stop-place table (`release_columns` in `scripts/kb_sources.py`): `coord_class` = `point_kind` when `use` is `self`, otherwise `place`; `coord_method` = from the source kind and point kind (`adjacent_station` for `adjacent`); `reference`, `reference_id` = the name of the source kind and the URL with the identifier; `reference_label` = `label` ("name [Q number]" when citing a Wikidata revision; "station（line）" for `adjacent`); `reference_note` = the fixed sentence for `source_read`.

## derived.csv — derived values

One row per place placed by calculation (`point_kind` = `estimated`). Checks E and F of the coordinate gate (step 4e) recompute the values from this table and compare them (`note` is not read).

| Column | Contents |
|---|---|
| `place_id` | The calculated place |
| `method` | Kind of calculation (same as the place's `source_type`: `computed`, `computed_track`, `printed_order`) |
| `stop_name`, `line_name` | One of the queries that use the place (for readers) |
| `anchor_a`, `anchor_b` | Anchor stations (stop-place query keys "station\|line", rows with a place) |
| `fraction` | Fraction of the way from anchor A to B (for `printed_order`, position in the printed order / count). Empty = a calculation not expressible as a fraction (along N02 railway lines, extrapolation, etc.; see `note`) |
| `how` | What the fraction was read from |

## readings.csv — map readings

Values of the points read from old topographic maps (`topo`) and GSI Maps (`gsi`), with who read them and when. A place's value must equal (within 1 m) the latest row for that place, or loading stops; to move a value, add a reading. Check C of the coordinate gate (step 4e) compares these records with the published values. Columns: `place_id`, `lat`, `lon`, `source_type`, `label`, `read_by`, `read_on`. For rows carried over from earlier readings when the table was created, `read_on` is the date they were carried over.

## Values that cannot be published

Coordinates from sources whose terms do not allow redistribution are not included in these tables. Some points were checked against such positions while the tables were compiled (`checked_within_km`); those positions are not part of this repository.
