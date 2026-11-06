# Known issues and limitations

The Japanese version is available in `KNOWN_ISSUES.ja.md`. If the two versions differ, this English version takes precedence.

> All counts refer to this release of the feed. "(`DETAILS.md`, note n)" refers to item n under "Details of the GTFS layer (`gtfs/`)" in `DETAILS.md`.

This document describes information omitted from the feed, values represented approximately, and known inconsistencies in the source that have been retained. The stops and times included in `gtfs/` are based on the printed timetable. For the modeling conventions—including service dates, stops defined separately for each line, and frequency-based services—see "Details of the GTFS layer (`gtfs/`)" in `DETAILS.md`.

## 1. What was not transcribed or is not included

- **Pages outside the timetable section** (covers, tables of contents, and advertisements), as well as the two **map pages** (pp. 33 and 44).
- **Fares** were not transcribed as structured data from any table. Fares appear in the dataset only within the original wording of frequency-only services (`DETAILS.md`, note 5; `extras/frequency_only.csv`, columns `text_raw` and `distance_fare_raw`) and are preserved as printed.
- **Additional columns in the shipping tables**—ship names, tonnage, and passenger capacity—were not transcribed. Ship names appearing in column headings were retained (pp. 187–192; in `extras/trip_attributes.csv`, and for the dated sailings in `extras/printed_sailings.csv`).
- **Mileages** were transcribed separately and used to estimate station locations (see Section 7), check running speeds and station names, and identify boundary stations in composite line headings. The mileage transcriptions are not included in this release.
- **Vertically printed notes in the tables**, such as a train departure time at a station not listed in the table, are retained in the notes of the transcription (row 12 of the workbooks) rather than converted to stop times. These notes have not been transcribed exhaustively. Approximately 800 such notes are included (971 when duplicates across sheets of the same table are counted). About 400 were identified by searching the scans with a tool that detects the characters 著 (arrival) and 發 (departure); notes without these characters (such as train names alone), or with faintly printed characters, may have been missed. For 63 notes (119 counting the copies), whether the time is a.m. or p.m. is recorded as unknown.

## 2. Services that are not in the feed

- **No trips could be generated for 14 frequency-only services** because the source lacks the numerical information required. Their original wording is preserved in `extras/frequency_only.csv` and `extras/frequency_sections.csv`.
  - 土佐電氣線 伊野線, 後免線 and 棧橋線 (Kochi): the source gives running times but describes the frequency only as 「頻繁ニ運轉」 ("frequent service"), without specifying a headway. Consequently, the Kochi tramway services are absent from the feed.
  - 京阪電氣鐵道和歌山線 京橋–車庫前, and 伊豫鐵道電氣線 道後–江ノ口 and 道後–古町: headways are printed, but neither running times nor mileages are given.
  - Eight sightseeing cruises on Lake Biwa (琵琶湖遊覽): running times are not provided.

  Nine other frequency-only services without printed running times or full timetables are included in the feed with estimated times (`DETAILS.md`, notes 5 and 6; `source` `estimate` or `estimate_ship` in `extras/frequency_sections.csv`).
- **50 dated sailings** have fewer than two printed times and therefore have no corresponding trip in `gtfs/` (`DETAILS.md`, note 1): 44 without any printed time are listed only in `extras/printed_sailings.csv`, and the remaining 6, each with one printed time, are preserved as single-stop trips in `extras/single_stop_trips.csv`.
- **20 trips with only one timed stop** cannot be used for journey planning and are stored in `extras/single_stop_trips.csv`.
- **The 「此間22分毎ニ運轉」 box for 金石電氣鐵道線 (p. 63)** could not be converted into trips (`extras/frequency_box.csv`, both directions: 中橋 departures 06:02–20:20 and 大野港 departures 06:34–20:52). Because the table gives only the departure time at the first stop of each trip, no trip with two timed stops is available as a template; the feed therefore supplies estimated arrivals for the individually printed trips in this table (`DETAILS.md`, note 6), but generates no trips for the frequency box. As a result, the feed contains no trips for this line between those hours.

## 3. Printed values that are not in the feed

### Several printings of the same train

The same train often appears in several places in the source:

- the detailed table, which prints the trains of a line with times at every station;
- summary bands, which repeat trains printed in detail elsewhere, at the main stations only;
- connection bands, which print connections to other lines at the end of a line or at a junction;
- joint tables, which combine connections over several lines and sea routes.

A band is a block of rows of a table for one line or stretch of a line (see "How the dataset is organized" in `DETAILS.md`). The feed generally retains a single trip for such a train, incorporating any times that appear only in one of the bands. If two tables disagree about a time at the same stop for the same train, the feed retains one value—usually the one from the detailed table—while the alternative remains in the transcription.

### Comparing the transcription with the feed

The feed is built by a program that, following fixed rules, combines the printings of the same train in several places of the source into one trip. To check that no printed time was lost unintentionally in this process (for example, by being treated as a duplicate), the transcription and the feed were compared by station, arrival/departure, and time. Of the printed times in the transcription, 31 are not in the feed (including `extras/single_stop_trips.csv`) under their original station names. They were not lost by accident: the same train can have different station names or times in different places, and the feed keeps only one of them. There are two such cases:

- Abbreviated station names (12 times): the joint table on p. 5 abbreviates the stations of six Peking–Hankow line trains as 北京 and 漢口, whereas the table on p. 184 lists the same trains and times under 北京前門 and 漢口大智門. The feed retains only the trips from p. 184.
- Different times (19 times): the time of the same train at the same stop differs by 1 to 60 minutes between tables. For example, 東北本線 train 207 departs 郡山 at 19:08 on pp. 3 and 101 but at 19:09 in the detailed table on p. 99, and the feed uses 19:09. All 19 are listed in the table under "Times that differ between tables" below. The scans confirm that these discrepancies are present in the printed source.

Because the comparison does not distinguish train numbers, it does not flag a printed time if that time appears for a different train at the same station in the feed. One such case has been identified: the band of p. 75 prints 東海道本線 29 at 靜岡 as dep. 00:15, whereas the detailed table (p. 11) and the feed give dep. 02:15. The feed records 00:15 at 靜岡 only for train 13. The printed source was checked and does show 00:15 on p. 75; this is treated as a misprint.

### Times that differ between tables

In the table below, "dep." means departure and "arr." means arrival.

| Line (as printed) | Train | Stop | Printed but omitted | Value in feed |
|---|---|---|---|---|
| 中國鐵道線 | 18 | 津山口 | dep. 17:04 (p. 51) | dep. 17:05 (p. 51) |
| 信越本線 | 108 | 長岡 | dep. 23:20 (p. 4) | dep. 22:20 (p. 116, p. 118) |
| 北陸本線 | 773 | 米原 | arr. 20:53 (p. 61) | arr. 20:59 (p. 58, p. 60) |
| 奥羽本線 | 702 | 秋田 | dep. 17:38 (p. 3, p. 128, p. 130) | dep. 17:33 (p. 126) |
| 奥羽本線 | 706 | 新庄 | dep. 16:19 (p. 128) | dep. 16:18 (p. 3, p. 126) |
| 山陰本線 | 610 | 豐岡 | arr. 22:38 (p. 74) | arr. 22:33 (p. 54, p. 76) |
| 山陽及東海道本線 | 32 | 米原 | arr. 19:36 (p. 57) | arr. 19:38 (p. 2, p. 17, p. 21) |
| 山陽本線 | 207 | 廣島 | arr. 18:25 (p. 23) | arr. 18:26 (p. 25) |
| 山陽本線 | 211 | 三田尻 | arr. 20:47 (p. 25) | dep. 21:45 (p. 29) |
| 山陽本線 | 49 | 小郡 | arr. 16:47 (p. 25) | arr. 16:41 (p. 19, p. 23) |
| 山陽本線 | 56 | 宮島 | dep. 12:09 (p. 21) | dep. 12:06 (p. 27) |
| 山陽本線 | 7 | 三田尻 | arr. 19:43 (p. 25) | arr. 19:49 (p. 19, p. 23) |
| 山陽本線／東海道及山陽本線 | 23 | 宮島 | arr. 00:59 (p. 19, p. 86) | arr. 00:58 (p. 26) |
| 東北本線 | 207 | 郡山 | dep. 19:08 (p. 3, p. 101) | dep. 19:09 (p. 99) |
| 東北本線 | 771 | 大宮 | arr. 19:33 (p. 115) | arr. 19:38 (p. 95) |
| 東海道本線 | 9 | 濱松 | arr. 00:00 (p. 13) | arr. 00:09 (p. 11) |
| 羽越線 | 517 | 秋田 | arr. 18:18 (p. 4) | arr. 18:19 (p. 133, p. 134) |
| 羽越線 | 9 | 砂越 | dep. 15:33 (p. 135) | dep. 15:34 (p. 134) |
| 高崎線 | 109 | 高崎 | arr. 10:00 (p. 122) | arr. 10:03 (p. 115) |

For 山陽本線 train 211, the detailed table (p. 29) gives only a departure time at 三田尻 (21:45). At 20:47, the time shown in the band, the train would still be between 虹ケ濱 and 下松; the band entry is therefore treated as a misprint.

### Transcription errors

The transcription was checked against the scans cell by cell; values that disagreed with the printed source were corrected, and values not present in the source were removed. Because exhaustive automated verification is not possible, a small number of such errors may remain.

## 4. Trains, train numbers, and routes

- **Routes with composite line names.** The source prints some bands under composite line headings that name two or more lines, such as 東海道及山陽本線. Where such a band can be divided at a boundary station, its trips are assigned to the component lines, but 175 trips under 12 composite line headings keep the composite name. In `routes.txt` these are 16 routes, because routes are split where one line name covers separate physical routes. These bands either cannot be split at a single boundary station or are the only representation in the feed of a through journey (see next item) or a time not printed elsewhere (`DETAILS.md`, note 8). The stop sequences and times are retained as printed. The 12 composite headings are:
  - 山陰及東海道線
  - 山陰本線及舞鶴線
  - 支那國有鐵道滬寧及滬杭甬線
  - 支那國有鐵道粤漢及株萍線
  - 支那國有鐵道隴海及汴洛線
  - 東北及信越線高崎線
  - 東北本線及常磐線
  - 東海道及山陰線
  - 東海道及山陽本線
  - 滿鐵京元線及咸鏡線南部
  - 滿鐵滿洲本線・旅順線及營口線
  - 臺灣總督府鐵道縦貫線及臺中線
- **Through-service bands retained alongside individual line trips.** Twenty-two timetable bands showing a single train across two lines (for example 東北本線及常磐線 801, 東北及信越線高崎線 102 and 東海道及山陰線 27) are retained as separate trips, even though all their printed stops and times also appear in the corresponding trips for the individual lines under the same train number. Each band is grouped with trips of those lines in `extras/physical_trains.csv` (`DETAILS.md`, note 4), but the individual line trips are not directly linked at the boundary: either continuity could not be confirmed or, as with train 801, the trips have no shared station at which a connection could be made. The separate band trip is therefore needed to represent the through journey. Bands whose through journeys are already represented by the individual line trips were removed as duplicates.
- **A train shown under two numbers becomes two trips.** When the source lists one train under two numbers and specifies the sections to which each number applies (for example the column of 東海道本線 71 is noted 「米原・明石間第六七一列車」 and that of 671 「靜岡・米原間第七一列車」; likewise 73 and 673), a separate trip is retained for each number. Consequently, the same physical train appears twice between 名古屋 and 大阪.
- **Trips whose printed stops and times are duplicated by another trip.** The following are nevertheless retained:
  - Nine short trips (two timed stops each) on 總武本線 between 兩國橋 and 千葉 or 佐倉 have all their printed stops and times contained in longer trips with different numbers. Both are retained because the source prints both train numbers: the bands of the 房總線, 東金線 and 成田線 tables (pp. 136–137) print them under the numbers of their own trains (for example 107) and the 總武本線 table (p. 137) under its numbers (for example 7). They may represent coupled trains or one train operating under two numbers; the source does not resolve this ambiguity.
  - Four trips of tables that print only the departures from one station (鞍手軌道線 and 本庄電氣軌道線) each share their sole printed departure time and station with a train of another railway, but represent distinct trains.
  - Among the dated 日本郵船 sailings to 上海, the sailing of 上海丸 printed with 長崎 on April 5 and without a date or time at 神戸 starts at 長崎 at the same time of day as the sailings from 神戸 call there. Because `calendar.txt` treats all sailings as daily, the 長崎–上海 section appears twice (`DETAILS.md`, note 1; the printed dates are in `extras/printed_sailings.csv`).
  - The four 朝鮮線 bands (1, 2, 7, and 8) in the joint table on p. 5 show 京釜本線 and 京義本線 trains at the same times. Because they name the station 釜山 where the tables of those lines print 釜山（棧橋）, the records are not matched to the same trains and are retained as separate trips; the through ride from 釜山 to 奉天 is given by the trips of 京釜本線, 京義本線 and 滿鐵安奉線 in `extras/physical_trains.csv`.
- **Through trains** are split into one trip per line (`DETAILS.md`, note 4). `extras/physical_trains.csv` links trips only where the source confirms that the same train continues across a line boundary. Uncertain connections are treated as transfers.
- **Irregular trains** (不, 147 trains) run every day in `calendar.txt`; their actual operating days are not specified in the source (`DETAILS.md`, note 1).

## 5. Times

- **Times in other time zones.** The source prints times in Manchuria, on the China coast and elsewhere in local time. Times are converted to Japan time only where the source specifies the time difference. Times for Taiwan, the Russian Far East, and overseas ferry ports remain as printed (`DETAILS.md`, note 7).
- **Estimated times.** Trips of frequency-based services and terminal arrival times calculated for tables that list departures only are estimates (`DETAILS.md`, notes 5 and 6; `timepoint` `0`, `extras/estimated_stop_times.csv`). Times are unavailable for some intermediate stops on frequency-only services (`DETAILS.md`, note 6).
- **Questionable times retained as printed.** A printed time was corrected only when other listings of the same train or the running times of neighboring trains established the intended value beyond reasonable doubt (for example 支那國有鐵道道淸線 7, 淸化 is printed 6:36 and corrected to 9:36, which `stop_times.txt` gives as 10:36 in Japan time (`DETAILS.md`, note 7), and 東海道本線 104, 東京 is printed 8:40 and given as 8:50). Other suspicious times were checked against the printed volume and retained unchanged. One particularly striking case is the first 東京-bound sailing of 東京灣汽船 (p. 193), 横須賀 12:00 → 横濱 12:20 (about 18 km in a straight line in 20 minutes; the opposite direction takes 2 hours 50 minutes). Trains 6 and 8 of 支那國有鐵道京綏線 take 110 and 99 minutes from 靑龍橋 to 南口 (78 minutes for the other trains) as printed. One station name also retains an apparent source misprint: 橫養, in the table of sailings to 甲浦 on p. 194, where the other table of the same page prints 撫養; the stop is assigned the coordinates and parent station of 撫養.
- **A time printed as a range.** For the 隱岐汽船 sailing from 境 to 西鄕 (p. 187), 知々井 is printed "2.00 乃至 3.00" (between 2 and 3 p.m.); the upper bound, 15:00, was used because the lower bound would imply zero travel time for the 1 nautical mile from 崎 (printed 14:00).

## 6. Station names

- **Old and new character forms.** Station names are as transcribed (`DETAILS.md`, note 8). In small print, the scans do not always allow old and new character forms to be distinguished. In a random sample of 60 station names taken to check the accuracy of the published transcription, two were transcribed in the modern form where the source prints the old one (青森 for 靑森 and 横手 for 橫手; both on p. 126, transcribed by LLM agents); these readings were retained. All pages were also checked against the scans by hand, but similar cases may remain. `extras/stop_name_variants.csv` gives every name in modern forms, allowing searches using modern spellings.
- **Characters indistinguishable in the scans.** Three station names retain their transcribed readings even though the names used in 1925 were probably different: 通遼堡 (滿鐵安奉線; probably 通遠堡, as in the 1926 edition of 『鐵道停車場一覽』), 灘縣 (支那國有鐵道膠濟本線; probably 濰縣, today 潍坊) and 綏遼城 (支那國有鐵道京綏線; probably 綏遠城, today Hohhot). The scans do not reliably distinguish 遼 from 遠 or 灘 from 濰, even when compared with clearly printed examples elsewhere in the volume. The coordinates correspond to the stations believed to have been intended.

## 7. Coordinates

Station coordinates represent approximate locations of stations in 1925. For each stop, `extras/stop_coord_source.csv` records how its coordinates were obtained (`coord_class`: `station`, `place`, `estimated`).

### Stations whose 1925 position is uncertain

The following are known cases in which the position in the feed may be up to approximately 4.5 km from the station's 1925 location:

| Station (line) | Position in this dataset | Why the 1925 position is uncertain |
|---|---|---|
| 播州赤穂 (赤穗鐵道線) | the station that opened in 1951 (`place`) | the 1925 station was moved in the early Shōwa period; its exact location is not documented |
| 根本 (東濃鐵道線) | the replacement station opened in 1952 (`place`) | the 1925 station closed with the regauging of 1928 |
| 大貞公園 (耶馬溪鐵道線) | the station at its post-1944 location, about 800 m from the original (`place`) | the earlier location is not documented |
| 姫, 大藪口 (東濃鐵道線) | along the line between neighboring stations (`estimated`) | the line was realigned in 1928 |
| 廣見 (東濃鐵道線) | a point representing the present-day district (`place`) | as above |
| 矢澤 (岩手輕便鐵道線) | the coordinates given in the station's Wikipedia article, which does not mention a relocation (`station`) | the line was regauged and partially realigned after 1936 |
| 小山田 (岩手輕便鐵道線) | as above (`station`) | as above |
| 花房, 黑木 (菊池軌道線) | estimated from the printed mileages or from neighboring stations (`estimated`) | the line was subsequently realigned |
| 筑後原町 (東肥鐵道線), 字中村 (船木鐵道線), 岩方 (長岡鐵道線), 眞尾 (防石鐵道線), 片濱 (藤相鐵道線), 稻荷山 (中國鐵道線), 周村 (支那國有鐵道膠濟本線), 卡倫 (支那國有鐵道吉長線) | a village, district or town point (`place`) | no redistributable source was found for the station's location; the straight-line distance to a neighboring station is more than 15% longer than the printed mileage |
| 藤 (十勝鐵道線) | estimated along the line between neighboring stations (`estimated`) | as above |
| 溜川, 博山 (支那國有鐵道膠濟線博山支線); 溜川 (支那國有鐵道膠濟線溜川炭礦線) | a town point (`place`) | no redistributable source was found for the stations' locations; the representative town points are approximately 3 km from the stations shown on current maps |
| 水晶觀音 (溫泉鐵道線) | along the line between neighboring stations (`estimated`) | the line ran along the coast, while the straight line between the neighboring stations runs inland; the estimated point may be about 2.5 km from the actual stop |
| 橋頭 (滿鐵安奉線) | along the line between neighboring stations (`estimated`) | no redistributable source was found for the station's location; the estimated position may be about 2 km away |
| 二日市下町, 二日市中町, 假又 (太宰府軌道線); 兵庫田, 成出, 道下 (福島飯坂電氣軌道線) | a point along the tramway identified from a historical topographic map (`place`) | the map shows the tramway but not these stops; the point represents the most likely stop location |
| 手井 (樺太鐵道西海岸線) | along the line between neighboring stations (`estimated`) | the 1925 station stood in the town about 1 km south of the present station; no redistributable source was found for its location |
| 稚內 (宗谷本線, 天鹽北線) | on the line about 1 km north of present-day 南稚内 station, where the sources describe the site (`estimated`) | the terminus of 1925 (renamed 南稚内 in 1939) was moved about 1 km south in 1952; no source specifies its former location, and the historical topographic maps available to the project do not cover the area |
| 高雄村 (赤穗鐵道線) | along the line between neighboring stations (`estimated`) | the line closed in 1951; no redistributable source was found for the station's location, and the historical topographic maps available to the project do not cover the area |
| 友枝, 下唐原, 中唐原, 黑土, 鮎返 (宇島鐵道線) | along the line between neighboring stations (`estimated`) | the line closed in 1936; as above |
| 原井 (宇島鐵道線) | a village point (`place`, 大字原井) | as above |
| 福金 (滿鐵安奉線) | between 本溪湖 and the present 福金 station, by the printed mileage (`estimated`) | the present station was built in 1934; no source documents the location of the 1925 station |
| 犬山 (名古屋鐵道線) | the present station (`station`) | the station moved to its present site in April 1927; the cited article states, without providing a source, that it first stood a little to the west, perhaps by several tens of meters to 150 m |
| 耳取 (栃尾鐵道線) | the stop as it was when the line closed (`station`) | the cited article reports, citing the official gazette at the time of opening, that the stop stood about 0.3 mile (about 0.5 km) farther north, whereas a 1915 guidebook places it near the later location; the straight line from this position to 上見附 is longer than the mileage printed in 1925 (1.2 miles), consistent with a location farther north |

### Sections longer than the printed mileage

Across all consecutive stops on rail and tram trips, 55 segments have straight-line distances that exceed the printed mileages by more than 15% and more than 0.3 km.

For 34 of these segments, at least one endpoint has a `place` or `estimated` coordinate, potentially inaccurate by several hundred meters: 久居–相川 (中勢鐵道線); 稻荷山–稻荷 (中國鐵道線); 高屋–下出部 (井笠鐵道線); 太平–藤 (十勝鐵道線); 安雲–廣瀬橋 (宇島鐵道線); 林–椋本 (安濃鐵道線); 内多–曾根 (安濃鐵道線); 分部–跡部 (安濃鐵道線); 內子–五十崎 (愛媛鐵道線); 周村–張店 (支那國有鐵道膠濟本線); 明王寺–田殿口 (有田鐵道線); 北關–筑後原町 (東肥鐵道線); 本吉–矢部川 (東肥鐵道線); 射和–中万 (松阪電車線); 兼城–高嶺 (沖繩縣營鐵道糸滿線); 高嶺–世名城 (沖繩縣營鐵道糸滿線); 津嘉山–國場 (沖繩縣營鐵道糸滿線); 梁森–磐城金山 (白棚鐵道線); 磐城金山–古關 (白棚鐵道線); 志戸平溫泉前–志戸平 (盛岡電氣工業線); 船木町–字中村 (船木鐵道線); 片濱–遠州川崎町 (藤相鐵道線); 遠州川崎町–細江 (藤相鐵道線); 上吉田–神戸村 (藤相鐵道線); 橫内–駿河岡部 (藤相鐵道線); 濱口–鬼津 (蘆屋鐵道線); 谷地–藤助新田 (谷地軌道線); 岩方–與板 (長岡鐵道線); 上除–日越 (長岡鐵道線); 初瀬–黑崎 (長谷鐵道線); 奈美–眞尾 (防石鐵道線); 中原–古川 (阿波電氣軌道線); 高畠–竹ノ森 (高畠鐵道線); 阿佐ケ谷–荻窪 (西武鐵道新宿線).

For the remaining 21 segments, both endpoints have station coordinates from cited records: 富士根町–入山瀬 (富士身延鐵道線); 身延–甲斐大島 (富士身延鐵道線); セメント町–南中川 (小野田鐵道線); 板橋–池袋 (山手線); 金町–龜有 (常磐線); 喜多山–新谷 (愛媛鐵道線); 播鐵大門–河合西 (播丹鐵道線); 漢口大智門–漢口江岸 (支那國有鐵道京漢線); 川口町–赤羽 (東北本線); 田尻–小牛田 (東北本線); 白坂–下野豐原 (東北本線); 上見附–耳取 (栃尾鐵道線); 三方原–追分 (濱松鐵道線); 小豆餅–錢取 (濱松鐵道線); 信濃荒井–西松本 (筑摩電氣鐵道線); 錦糸町–兩國橋 (總武本線); 羽塚–西尾 (西尾鐵道線); 外川–犬吠 (銚子鐵道線); 立道–池谷 (阿波電氣軌道線); 北飯山–飯山 (飯山鐵道線); 立田–後免 (高知鐵道線). In these cases, the discrepancy may reflect an error in the printed mileage or an undocumented station relocation after 1925. Shipping routes were excluded from this comparison because their printed distances do not always refer to consecutive ports of call.

### Stops located on maps surveyed in 1929–1930

The stops served by frequency-only services in Tokyo (モスリン裏, 新町 and 砂町 of 城東電氣軌道線, 多摩川 of 目黑蒲田電鐵線, and 中野, 妙法寺口, 馬橋 and 阿佐ケ谷 of 西武鐵道新宿線) were located using topographic maps surveyed in 1929–1930, several years after the timetable was published.

### Ports

Ports are located at their 1925 landing sites (a pier, quay, or beach reached by lighter) wherever the site can be identified from a source. Where the site could not be identified, the port was placed at a nearby village or town, or at the location of its name on a historical topographic map; such coordinates may be up to about 0.5 km from the landing site. For 15 ports the landing place was read on former topographic maps (Konjaku Map on the Web); where the maps do not indicate a landing site (北條, 館山, 鴨川, 中原 and 下浦), a nearby point was selected instead. Eleven ports fall outside the coverage of those maps (穴水, 佐伯, 八幡濱, 油津, 由良, 稚內, 知々井, 宇出津, 嚴原, 能登小木 and 別府 of 隱岐汽船會社定期航路); their coordinates were estimated near the present-day port using GSI Maps and may differ from the 1925 landing site. 大泊 and 本斗 (樺太) and 青島 (支那) also have approximate coordinates. The timetable names the Kobe port of call of 大阪商船會社定期航路 only as 三ノ宮; it is placed at メリケン波止場, the wharf at the foot of the street from 三ノ宮 station of 1925, which is an interpretive choice.

### Stops outside Japan proper

For stations outside Japan proper, some stops share coordinates or are located at present-day stations: 濟南府 and 濟南 share the point of 濟南 station (`station`); 株洲 of 株萍路 and 株洲 of 粤漢路 (about 1.5 km apart in 1925) share the point of the present 株洲 station; and 蒲圻 is placed at the present station, which was moved south in 1971. For several other stations, no redistributable source identifies the 1925 location. These were placed at present-day stations or representative town points: 馬山 (滿鐵馬山線; the present station, moved inland in 1977 from the 1925 station by the sea), 豐臺 (支那國有鐵道京綏線; the station building of 2022, about 1 km east of the 1925 building), and 咸寧, 長沙東站 (粤漢線) and 閘口 (滬寧及滬杭甬線), each placed about 1–2 km from the site of the earlier station. 大庄 (臺灣總督府鐵道臺東北線) is placed between its neighboring stations by the printed mileage (`estimated`), also about 1–2 km from the site of the earlier station. Similarly, 清津 (滿鐵咸鏡線北部) is placed at the station of 1942, about 0.8 km by rail from the 1925 station, which stood toward the port; 元山 (滿鐵京元線 and 滿鐵咸鏡線南部) at the station of 1975, moved an unrecorded distance from the 1913 station; 南京 (支那國有鐵道滬寧及滬杭甬線) at the 下關 station rebuilt on another site in 1931, probably within 1 km of the 1908 station; 臺北 (臺灣總督府鐵道) at the station of 1989, about 250 m east-northeast of the 1901 station building; and 萍郷 (支那國有鐵道粤漢及株萍線) at a town point, while the 1925 station stood by the west gate of the old town. 黄河北岸 (支那國有鐵道京漢線) is placed at the middle of the Yellow River bridge of 1905; the station stood at the north end of the bridge, about 1.5 km away. 鎭南浦 (滿鐵平南線) is placed at the present station (`station`): no relocation is documented, but its location may nevertheless differ from that in 1925.

In total, 39 railway stops outside Japan proper are represented by town, district, or present-day locations rather than the sites of their 1925 stations (`place` in `extras/stop_coord_source.csv`): 北京前門, 黄河北岸 (支那國有鐵道京漢線); 北京西直門, 豐臺 (支那國有鐵道京綏線); 井陘縣, 娘子關 (支那國有鐵道正太線); 南京, 閘口 (支那國有鐵道滬寧及滬杭甬線); 安源, 株洲（株萍路）, 株洲（粤漢路）, 萍郷 (支那國有鐵道粤漢及株萍線); 咸寧, 蒲圻, 長沙東站 (支那國有鐵道粤漢線); 周村 (支那國有鐵道膠濟本線); 博山, 溜川 (支那國有鐵道膠濟線博山支線); 溜川, 溜川炭礦 (支那國有鐵道膠濟線溜川炭礦線); 淸化, 道口 (支那國有鐵道道淸線); 運河〈支那〉 (支那國有鐵道隴海及汴洛線); 元山 (滿鐵京元線); 元山 (滿鐵京元線及咸鏡線南部); 清津 (滿鐵咸鏡線北部); 元山 (滿鐵咸鏡線南部); 鶴橋 (滿鐵湖南線); 馬山 (滿鐵馬山線); 大泊〈樺太〉 (樺太鐵道本線); 卡倫 (支那國有鐵道吉長線); 鄭家屯 (支那國有鐵道四洮線); 撫順 (滿鐵撫順線); 大連〈滿洲〉 (滿鐵滿洲本線・旅順線及營口線); 臺北 (臺灣總督府鐵道宜蘭線); 臺北 (臺灣總督府鐵道淡水線); 臺北 (臺灣總督府鐵道縦貫線及臺中線); 花蓮港 (臺灣總督府鐵道臺東北線); 里壠 (臺灣總督府鐵道臺東南線).

### Walking transfers

Transfer times between stations are calculated from the coordinates in `gtfs/stops.txt` (`DETAILS.md`, note 3); where a stop is represented by an approximate place point, walking times are likewise approximate. Three walking transfers cross waterways that had no bridges in 1925: from the two stops at 戸畑 (鹿兒島本線 and 九州電氣軌道線 支線) to the port of 若松 across the mouth of 洞海灣 (11–12 minutes), and the port of 天保山 (大阪) to 櫻島 (西成線) across the mouth of the 安治川 (5 minutes). Passengers would have crossed by ferry, but the modeled transfer times reflect walking distances and exclude ferry waiting times.

## Reporting problems

Please report errors to the contact listed in `gtfs/feed_info.txt`. Include the `trip_id` or `stop_id` and, if available, the relevant page of the source. For example (the values only illustrate the format and are not a known error):

```
Subject: Error report for Japan1925-GTFS

Version: the feed_version in gtfs/feed_info.txt
File: gtfs/stop_times.txt
Trip and stop: trip_id TR05802 (東海道本線 train 3), stop_id ST04756 (靜岡)
Value in the feed: departure 12:57
Value in the source: departure 12:47 (p. 11 of the source)
```
