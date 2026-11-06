# Using the feed with OpenTripPlanner 2

The Japanese version is available in `README.ja.md`. If the two versions differ, this English version takes precedence.

This folder configures OpenTripPlanner (OTP) for this feed and asks it for journeys.

| File | What it is |
|---|---|
| `build-config.json`, `router-config.json`, `otp-config.json` | the settings OTP needs for a 1925 timetable (table below) |
| `plan_with_otp.py` | a standard-library Python script that asks the running server for journeys by station name and time |

Without the settings OTP drops every trip as "out of service period", because by default it keeps only trips within a few years of today. Tested with OpenTripPlanner 2.10.0 on Java 25, without street data (OTP then walks between nearby stations in a straight line). The steps below were run on macOS; the Windows and Linux commands have not been tested on those systems.

| File | Setting | Why |
|---|---|---|
| `build-config.json` | `transitServiceStart` / `transitServiceEnd` = 1925 | keep the 1925 trips (by default they are dropped) |
| | `maxTransferDuration` = 45 min | allow the longer walks between stations of the same name that stand apart (see `transfers.txt`) |
| | `transitFeeds` | read `gtfs.zip` (made in section 2) under the feed id `J1925` |
| `router-config.json` | `maxJourneyDuration` = 96 h | journeys of up to four days (ferries, through trains); the default is 24 h; raise it for longer journeys |
| | `searchWindow` = 24 h | find journeys with long waits before departure or at a connection; with a short window OTP may return nothing |
| | `transferSlack` = 0 | the printed connections allow 0 minutes between arrival and departure |
| | `maxNumberOfTransfers` = 30 | journeys with many changes of train and ship; the default is 12 |
| `otp-config.json` | `MinimumTransferTimeIsDefinitive` | use the minutes of `transfers.txt` as they are, even where OTP's own walking time is longer (by default OTP uses the longer of the two) |

## 1. Install Java 25

OpenTripPlanner 2.10 is compiled for Java 25; with an older Java the program stops at once with `UnsupportedClassVersionError`. Eclipse Temurin is a free build of Java 25.

On macOS, with Homebrew (or use the `.pkg` installer from https://adoptium.net/temurin/releases/?version=25):

```sh
brew install --cask temurin@25
```

On Windows (or use the `.msi` installer from the same page):

```powershell
winget install EclipseAdoptium.Temurin.25.JDK
```

On Linux, after adding the Adoptium repository as described at https://adoptium.net/installation/linux/ (or use the `.tar.gz` from the same page):

```sh
sudo apt install temurin-25-jdk    # Debian, Ubuntu
sudo dnf install temurin-25-jdk    # Fedora, RHEL
```

Then check the version:

```sh
java -version
```

It must print `openjdk version "25...`. If an older Java stays the default on your computer, call the new one by its full path instead of `java` in the commands below (on macOS `/usr/libexec/java_home -v 25` prints its folder; the program is `bin/java` inside it).

## 2. Get OpenTripPlanner and the feed

All the commands from here on are run in this folder, `examples/opentripplanner/` of the unpacked dataset. Open a terminal and go to it first. If you unpacked the archive in your Downloads folder:

```sh
cd ~/Downloads/japan1925-gtfs-v1.0/examples/opentripplanner
```

On Windows (PowerShell):

```powershell
cd $HOME\Downloads\japan1925-gtfs-v1.0\examples\opentripplanner
```

The three JSON files are already here. Add the OTP program (about 190 MB):

```sh
curl -O https://repo1.maven.org/maven2/org/opentripplanner/otp-shaded/2.10.0/otp-shaded-2.10.0.jar
```

(On Windows type `curl.exe` instead of `curl`: in Windows PowerShell 5.1, `curl` is another command.)

Then make the feed into a zip, `gtfs.zip` (the name that `build-config.json` reads), from the dataset's `gtfs/` folder, two levels up. If an older `gtfs.zip` is in this folder, delete it first: `zip` adds to an existing zip instead of replacing it.

```sh
zip -X -j gtfs.zip ../../gtfs/*.txt
```

On Windows (PowerShell):

```powershell
Compress-Archive -Path ..\..\gtfs\* -DestinationPath gtfs.zip
```

The nine files must sit at the top of the zip, not inside a folder. Compressing the `gtfs` folder itself (for example with "Compress" in the macOS Finder, or "Send to > Compressed (zipped) folder" in Windows) puts them inside a folder `gtfs/`, and the build in section 3 then stops with `missing required entity: type=org.onebusaway.gtfs.model.Agency filename=agency.txt`. To check the zip:

```sh
unzip -l gtfs.zip
```

On Windows (PowerShell):

```powershell
tar -tf gtfs.zip
```

It should list `agency.txt`, `stop_times.txt` and the other files without `gtfs/` in front of them. The folder now holds:

```text
build-config.json
gtfs.zip
otp-config.json
otp-shaded-2.10.0.jar
plan_with_otp.py
README.ja.md
README.md
router-config.json
```

## 3. Build the graph and start the server

First build the graph and save it (a few seconds):

```sh
java -Xmx4G -jar otp-shaded-2.10.0.jar --build --save .
```

The build has worked when the folder now holds `graph.obj` (about 4 MB) and these lines appear near the end of the log (the times differ):

```text
13:02:32.046 INFO [main]  (SerializedGraphObject.java:284) Graph written: graph.obj
13:02:32.046 INFO [main]  (OTPMain.java:179) Done building graph. Exiting.
```

Then load the graph and start the server:

```sh
java -Xmx4G -jar otp-shaded-2.10.0.jar --load --serve .
```

The server is ready for questions when the log shows a line like this one:

```text
12:58:57.207 INFO [main]  (GrizzlyServer.java:146) Grizzly server running.
```

The server keeps running in that window until you stop it with Ctrl-C, so ask for journeys (section 4) from another terminal window. A few `WARN` lines in both logs are expected and can be ignored, for example `Limiting transit service days to time period: [1925-01-01, 1926-01-01)` (the 1925 setting of `build-config.json`) and `FEATURES THAT SHOULD BE TURNED OFF IN PRODUCTION`.

Do not combine the two steps as `--build --serve`: with this feed OpenTripPlanner 2.10.0 then answers every journey query with an error (`Index ... out of bounds for length 0`).

## 4. Ask for journeys

Open another terminal window, go to this folder again (the `cd` command of section 2), and run `plan_with_otp.py` with an origin, a destination and a departure time, the same arguments as `examples/route_1925.py` (on Windows type `python` or `py` instead of `python3`):

```sh
python3 plan_with_otp.py 東京 下關 08:00
```

It prints what the server answers:

```text
東京 [PS02298] -> 下關 [PS00296]  depart 08:15  arrive 08:05 (+1 day)  (23 h 50 min, 1 transfer)
  ride: 東海道本線 3号  東京 08:15 -> 神戸 20:40
  ride: 山陽本線 3号  神戸 20:46 -> 下關 08:05 (+1 day)

東京 [PS02298] -> 下關 [PS00296]  depart 08:45  arrive 08:30 (+1 day)  (23 h 45 min, 1 transfer)
  ride: 東海道本線 1号  東京 08:45 -> 神戸 21:00
  ride: 山陽本線 1号  神戸 21:06 -> 下關 08:30 (+1 day)

東京 [PS02298] -> 下關 [PS00296]  depart 20:10  arrive 21:38 (+1 day)  (25 h 28 min, 1 transfer)
  ride: 東海道本線 5号  東京 20:10 -> 神戸 09:44 (+1 day)
  ride: 山陽本線 5号  神戸 09:51 (+1 day) -> 下關 21:38 (+1 day)
```

`ride` is a train boarded.

Journeys are listed by arrival; for the same arrival, the one with fewer transfers and then the later departure comes first. The script looks the station names up in the dataset's `gtfs/stops.txt` (`../../gtfs/`); if you copy it elsewhere, give that folder with `--gtfs`. A name that belongs to several stations (東京 is both the railway station `PS02298` and the steamer pier `PS04524`; 高田 is two stations) is tried for each of them, and every journey shows the stations used. To list the stations whose name contains 高田:

```sh
python3 plan_with_otp.py --list 高田
```

Other options: `--date` (default 1925-04-01), `--window` (default `PT24H`, how long after the given time OTP looks for departures), `--first` (journeys to show, default 3), `--url` (default `http://localhost:8080`), `--feed` (default `J1925`, the feed id in `build-config.json`). This finds the journey to Harbin by train and ferry, arriving four days later:

```sh
python3 plan_with_otp.py 東京 哈爾賓〈滿洲〉 08:00
```

The same questions can be put to the GraphQL API directly at http://localhost:8080/otp/gtfs/v1 (the script shows the query), or in GraphiQL, an interactive query page that OTP serves at http://localhost:8080/graphiql. Stations are addressed as `J1925:` followed by the parent station id of `stops.txt` (`location_type` 1).

## Differences from `examples/route_1925.py`

- OTP counts the change from 東海道本線 3 to 山陽本線 3 at 神戸 as a transfer; the feed records it as the same physical train (`extras/physical_trains.csv`), which `route_1925.py` does not count.
- Without street data OTP walks between stations in a straight line from their coordinates and does not use `transfers.txt` to create connections; `MinimumTransferTimeIsDefinitive` only makes its minutes count as they are. `route_1925.py` uses `transfers.txt` alone.
- For headway-based services with `exact_times=0` (`frequencies.txt`), OTP waits a full headway; `route_1925.py` assumes a departure at `start_time` and every headway after it, and boards the next one.
- Journeys with a long wait appear only when they fall inside `searchWindow`; for example, for 東京 → 哈爾賓〈滿洲〉 at 08:00 on 1925-04-01, the train from the railway station 東京 that arrives earliest leaves at 20:30, so the journey is found only with a window longer than 12.5 hours (24 hours above).

See also note 12 of `DETAILS.md`.
