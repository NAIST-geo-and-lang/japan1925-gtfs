# OpenTripPlanner 2でこのGTFSデータを使う

この文書は `README.md` の日本語訳です。内容が異なる場合は、英語版を優先します。

このフォルダには、OpenTripPlanner（OTP）をこのGTFSデータに合わせて設定するファイルと、OTPに行程を問い合わせるスクリプトがあります。

| ファイル | 中身 |
|---|---|
| `build-config.json`、`router-config.json`、`otp-config.json` | 1925年の時刻表をOTPで使うのに必要な設定（下の表） |
| `plan_with_otp.py` | 動いているサーバーに、駅名と時刻で行程を問い合わせるPythonのスクリプト（標準ライブラリだけで動きます） |

これらの設定が無いと、OTPはすべての便を「運行の期間外」として捨てます。既定では、今日の前後数年の便しか残さないためです。OpenTripPlanner 2.10.0とJava 25で、道路のデータなしで確かめました（道路のデータが無いと、OTPは近くの駅どうしを直線で歩きます）。下の手順はmacOSで確かめました。WindowsとLinuxのコマンドは、それぞれの実機では確かめていません。

| ファイル | 設定 | 理由 |
|---|---|---|
| `build-config.json` | `transitServiceStart`・`transitServiceEnd` を1925年に | 1925年の便を残す（既定では捨てられます） |
| | `maxTransferDuration` を45分に | 同じ名前で離れて立つ駅どうしの、長めの徒歩を許す（`transfers.txt` を参照） |
| | `transitFeeds` | `gtfs.zip`（2の節で作ります）を、`J1925` という名前（feedId）で読む |
| `router-config.json` | `maxJourneyDuration` を96時間に | 4日までかかる行程（船・通し列車）のため。既定は24時間。もっと長い行程には大きくしてください |
| | `searchWindow` を24時間に | 出発前や乗り換えで長く待つ行程を見つけるため。幅が狭いと、OTPが何も返さないことがあります |
| | `transferSlack` を0に | 原本には、到着と出発が同じ分の乗り継ぎが記載されているため |
| | `maxNumberOfTransfers` を30に | 列車や船を何度も乗り継ぐ行程のため。既定は12 |
| `otp-config.json` | `MinimumTransferTimeIsDefinitive` | OTPが求めた徒歩の時間のほうが長くても、`transfers.txt` の分数をそのまま使う（既定では長いほうを使います） |

## 1. Java 25を入れる

OpenTripPlanner 2.10はJava 25向けに作られています。古いJavaでは、`UnsupportedClassVersionError` と出てすぐに止まります。Eclipse Temurinは、無料で使えるJava 25の配布版の1つです。

macOSでは、Homebrewで入れます（<https://adoptium.net/temurin/releases/?version=25>の `.pkg` のインストーラーでもかまいません）。

```sh
brew install --cask temurin@25
```

Windowsでは、次のコマンドで入れます（同じページの `.msi` のインストーラーでもかまいません）。

```powershell
winget install EclipseAdoptium.Temurin.25.JDK
```

Linuxでは、<https://adoptium.net/installation/linux/>に書かれたとおりにAdoptiumのリポジトリを足してから入れます（同じページの `.tar.gz` でもかまいません）。

```sh
sudo apt install temurin-25-jdk    # Debian, Ubuntu
sudo dnf install temurin-25-jdk    # Fedora, RHEL
```

入れたら、バージョンを確かめます。

```sh
java -version
```

`openjdk version "25...` と表示される必要があります。古いJavaが既定のまま残るときは、下のコマンドの `java` の代わりに、新しいJavaをフルパスで呼んでください（macOSでは `/usr/libexec/java_home -v 25` がそのフォルダを表示します。プログラムはその中の `bin/java` です）。

## 2. OpenTripPlannerとGTFSデータを用意する

ここから先のコマンドは、すべてこのフォルダ（展開したデータセットの `examples/opentripplanner/`）で動かします。まずターミナルを開いて、このフォルダへ移ります。「ダウンロード」フォルダに展開した場合は、次のとおりです。

```sh
cd ~/Downloads/japan1925-gtfs-v1.0/examples/opentripplanner
```

Windows（PowerShell）では、次のとおりです。

```powershell
cd $HOME\Downloads\japan1925-gtfs-v1.0\examples\opentripplanner
```

JSONのファイル3つは、もうこのフォルダにあります。OTPのプログラム（約190MB）を足します。

```sh
curl -O https://repo1.maven.org/maven2/org/opentripplanner/otp-shaded/2.10.0/otp-shaded-2.10.0.jar
```

（Windowsでは、`curl` の代わりに `curl.exe` と打ってください。Windows PowerShell 5.1では、`curl` は別のコマンドを指します。）

次に、2つ上の階層にあるデータセットの `gtfs/` フォルダから、GTFSデータをzipにまとめた `gtfs.zip`（`build-config.json` が読む名前）を作ります。このフォルダに前に作った `gtfs.zip` があれば、先に消してください。`zip` は、すでにあるzipを置き換えずに、中身を足していくためです。

```sh
zip -X -j gtfs.zip ../../gtfs/*.txt
```

Windows（PowerShell）では、次のとおりです。

```powershell
Compress-Archive -Path ..\..\gtfs\* -DestinationPath gtfs.zip
```

9つのファイルは、フォルダに入れずにzipの一番上に置く必要があります。`gtfs` フォルダそのものを圧縮すると（macOSのFinderの「圧縮」や、Windowsの「送る＞圧縮（zip形式）フォルダー」など）、ファイルが `gtfs/` フォルダの中に入り、3の節のグラフの組み立てが `missing required entity: type=org.onebusaway.gtfs.model.Agency filename=agency.txt` と出て止まります。zipの中身は、次のコマンドで確かめられます。

```sh
unzip -l gtfs.zip
```

Windows（PowerShell）では、次のとおりです。

```powershell
tar -tf gtfs.zip
```

`agency.txt`、`stop_times.txt` などが、前に `gtfs/` が付かずに並んでいれば大丈夫です。これで、このフォルダには次のファイルがそろいます。

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

## 3. グラフを組み立てて、サーバーを起動する

まず、グラフ（OTPが経路を探すための網）を組み立てて保存します（数秒かかります）。

```sh
java -Xmx4G -jar otp-shaded-2.10.0.jar --build --save .
```

このフォルダに `graph.obj`（約4MB）ができ、ログの最後のほうに次のような行が出れば、組み立てはうまくいっています（時刻は違います）。

```text
13:02:32.046 INFO [main]  (SerializedGraphObject.java:284) Graph written: graph.obj
13:02:32.046 INFO [main]  (OTPMain.java:179) Done building graph. Exiting.
```

次に、グラフを読み込んでサーバーを起動します。

```sh
java -Xmx4G -jar otp-shaded-2.10.0.jar --load --serve .
```

ログに次のような行が出たら、サーバーは問い合わせを受け付けられます。

```text
12:58:57.207 INFO [main]  (GrizzlyServer.java:146) Grizzly server running.
```

サーバーは、Ctrl-Cで止めるまでそのウィンドウで動き続けます。行程の問い合わせ（4の節）は、別のターミナルのウィンドウから行ってください。どちらのログにも `WARN` の行がいくつか出ますが、気にしなくてかまいません。たとえば `Limiting transit service days to time period: [1925-01-01, 1926-01-01)`（`build-config.json` の1925年の設定から出ます）や `FEATURES THAT SHOULD BE TURNED OFF IN PRODUCTION` です。

2つの手順を `--build --serve` とまとめないでください。このデータでは、OpenTripPlanner 2.10.0が、どの行程の問い合わせにもエラー（`Index ... out of bounds for length 0`）を返します。

## 4. 行程を問い合わせる

別のターミナルのウィンドウを開いて、もう一度このフォルダへ移り（2の節の `cd` のコマンド）、`plan_with_otp.py` を出発地・目的地・出発時刻を付けて動かします。引数は `examples/route_1925.py` と同じです（Windowsでは、`python3` の代わりに `python` か `py` と打ってください）。

```sh
python3 plan_with_otp.py 東京 下關 08:00
```

サーバーの答えが、次のように表示されます。

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

departは出発、arriveは到着、(+1 day) は翌日、transfersは乗り換えの回数、rideは乗った列車です。

行程は、到着の早い順に並びます。到着が同じなら、乗り換えの少ないもの、次に出発の遅いものが先です。スクリプトは駅名を、データセットの `gtfs/stops.txt`（`../../gtfs/`）で引きます。スクリプトをほかの場所に写したときは、`--gtfs` で `gtfs/` フォルダの場所を指定してください。いくつもの駅にあたる名前（「東京」は鉄道の駅 `PS02298` と汽船の乗り場 `PS04524` の両方、「高田」は2つの駅）は、それぞれの駅で問い合わせ、どの行程にも使った駅を示します。名前に「高田」を含む駅の一覧は、次のコマンドで表示します。

```sh
python3 plan_with_otp.py --list 高田
```

ほかのオプションは、`--date`（既定1925-04-01）、`--window`（既定 `PT24H`。指定した時刻から、どれだけ後までの出発をOTPが探すか）、`--first`（表示する行程の数。既定3）、`--url`（既定 `http://localhost:8080`）、`--feed`（既定 `J1925`。`build-config.json` に書いたフィードの識別子）です。次のコマンドは、列車と船で哈爾賓（ハルビン）へ行き、4日後に着く行程を見つけます。

```sh
python3 plan_with_otp.py 東京 哈爾賓〈滿洲〉 08:00
```

同じ問い合わせは、GraphQLのAPI（<http://localhost:8080/otp/gtfs/v1>）に直接送ることもできます（スクリプトが問い合わせの中身を示しています）。OTPが用意する、問い合わせを試せるページGraphiQL（<http://localhost:8080/graphiql>）からも送れます。駅は、`J1925:` のあとに `stops.txt` の親駅（`location_type` が1）の識別子を続けて指定します。

## `examples/route_1925.py` との違い

- OTPは、神戸での「東海道本線」の3から「山陽本線」の3への乗り継ぎを、乗り換えと数えます。このGTFSデータではこれを同じ通し列車として記録しており（`extras/physical_trains.csv`）、`route_1925.py` は乗り換えと数えません。
- 道路のデータが無いと、OTPは駅の座標から直線で駅どうしを歩き、`transfers.txt` から乗り換えを作りません。`MinimumTransferTimeIsDefinitive` は、`transfers.txt` の分数をそのまま使うようにするだけです。`route_1925.py` は `transfers.txt` だけを使います。
- `exact_times=0` の運転間隔で表された運行（`frequencies.txt`）では、OTPは1間隔分まるごと待ちます。`route_1925.py` は、`frequencies.txt` の `start_time` から1間隔ごとに発車があるものとして、次の発車に乗ります。
- 長く待つ行程は、`searchWindow` の中に入るときだけ現れます。たとえば1925年4月1日 08:00の東京 → 哈爾賓〈滿洲〉では、鉄道の東京駅から最も早く着く列車が20:30に出るので、幅を12.5時間より広くしたとき（上の設定では24時間）だけ見つかります。

`DETAILS.ja.md` の「12. OpenTripPlannerでの使用」も見てください。
