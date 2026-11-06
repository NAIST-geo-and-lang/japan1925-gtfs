# Japan1925-GTFS

この文書は `README.md` の日本語訳です。内容が異なる場合は、英語版を優先します。

本データセットは、日本の全国時刻表『汽車時間表』（*Kishā Jikanhyō*）の創刊号（1925年4月号）に掲載された鉄道・軌道・船舶の運行情報を、公共交通データの標準形式GTFS（General Transit Feed Specification、<https://gtfs.org/>）で提供します。GTFSデータの元となった時刻表の書き起こしに加え、時刻と列車番号を原本まで、駅の座標を出典までたどれる記録も収録しています。

| | |
|---|---|
| **入手** | <https://doi.org/10.5281/zenodo.23200420>（ZIPファイル：約21MB、展開後は約160MB） |
| **対象地域** | 内地（北海道を含む）、樺太、朝鮮、台湾に加え、原本に掲載された満洲・中国・ロシア極東で接続する便 |
| **GTFSデータ** | 541路線・10,080便（原本に掲載された9,849便と、運転間隔に基づく雛形の便231便。雛形の便は `DETAILS.ja.md` の「5. 運転間隔」を参照）・停車地5,124（駅名と路線の組で定義し、4,576の親駅に集約）・停車時刻87,652件 |
| **原本** | 時刻表193ページ（1〜195ページのうち地図2ページを除く）を178冊のワークブックに書き起こし、全ページをスキャン画像と照合 |
| **運行カレンダー** | すべての便を1925-03-28から1925-04-30まで毎日運行するものとして設定（データ上の取り決め。`DETAILS.ja.md` の「1. 運行日」を参照） |
| **バージョン** | v1.0（`gtfs/feed_info.txt` の `feed_version` は `20261026-ebd6f64c`）。識別子はバージョン間で維持します。 |
| **ライセンス** | データはCC BY 4.0、`examples/` と `tools/` のスクリプト・設定ファイルはMITライセンス（`LICENSE` を参照）。駅の座標については、後述の出典表示も必要です。 |
| **引用** | Ouchi, H., & Yamamoto, S. (2026). Japan1925-GTFS: a dataset of scheduled railway and ferry services from Japan's 1925 national timetable (Version v1.0) [Data set]. Zenodo. <https://doi.org/10.5281/zenodo.23200420>（BibTeXは下の「利用条件と引用」の節を参照） |

本データセットが表すのは、**時刻表に掲載された運行予定**であり、特定の日に列車や船が実際に運行したことを示すものではありません。運行カレンダーや乗り換え時間、一部の時刻・座標には、データ作成上の取り決めや推定値を用いています（下の「利用上の注意」の節と、`DETAILS.ja.md` の「GTFSの層（`gtfs/`）の詳細」を参照）。GTFSに収録した時刻のうち、原本に記載されているものは、どれも原本のページ・表・列・行までたどれます（下の「CSV形式のファイルを使った分析の例」の節を参照）。

## 基本的な使い方

### 1. ファイルを手に入れる

<https://doi.org/10.5281/zenodo.23200420> からZIPファイルをダウンロードし、展開してください（約21MB、展開後は約160MB）。経路検索や交通ネットワークの分析に必要なファイルは `gtfs/`（4MB）にあります。`extras/` には出典情報やGTFSでは表現できない情報、`transcription/` には元の時刻表を書き起こしたデータ、`integrated/` には書き起こしからGTFSを作成する途中で統合した列車ごとのデータを収録しています。各フォルダとファイルの詳しい説明は、下の「データセットの中身」の節にあります。

### 2. 経路検索を試してみる

#### 経路の探し方

1で展開したフォルダの中で、同梱のスクリプト `examples/route_1925.py` を使い、東京を8時以降に出て下關へ行く経路を実際に探してみます（Python 3があれば、追加のライブラリを入れなくても動きます）。

```sh
python3 examples/route_1925.py 東京 下關 08:00
```

次のように表示されます。

```text
東京 -> 下關  depart 08:15  arrive 08:05 (+1 day)  (23 h 50 min, 0 transfers)
  ride: 東海道本線 3号  東京 08:15 -> 神戸 20:40
  through: 山陽本線 3号  神戸 20:46 -> 下關 08:05 (+1 day)
```

`depart` は出発、`arrive` は到着、`(+1 day)` は翌日、`transfers` は乗り換え回数を表します。`ride` は乗車する列車、`through` は乗り換えずに同じ列車で別の路線へ進む区間です。

#### 駅名の指定のしかた

駅は、原本に記載された字体の駅名で指定します（たとえば、下関ではなく下關）。指定できる駅名は `extras/stop_name_variants.csv` で確かめられます。`location_type` が `1` の行が駅で、`stop_name` 列が指定に使う駅名、`name_shinjitai` 列がそれを新字体に直したものです（〈滿洲〉のような地域タグは省いても指定できます）。

表の駅の行を抜き出した例：

```text
stop_id,stop_name,location_type,name_shinjitai,printed_names
...
PS00296,下關,1,下関,
PS01008,哈爾賓〈滿洲〉,1,哈爾賓〈満洲〉,
PS01873,廣島,1,広島,
PS02805,澁谷,1,渋谷,
...
```

名前の一部から駅を探すときは、`--list` を使います。次の例は、駅名に「高田」を含む駅を、路線とともに一覧にします。

```sh
python3 examples/route_1925.py --list 高田
```

次のように表示されます。

```text
PS03386 美濃高田 / 美濃高田（養老鐵道線）
PS03755 豐後高田 / 豐後高田（宇佐參宮鐵道線）
PS04284 高田 / 高田（信越本線）
PS04285 高田 / 高田（和歌山線）・高田（櫻井線）
PS04286 高田本山 / 高田本山（伊勢鐵道線）
PS04287 高田馬場 / 高田馬場（山手線）
```

各行の先頭の `PS…` は駅の番号（ID）で、そのあとに駅名と、路線ごとの停車地が続きます（駅と停車地の関係は、下の「3. GTFSに対応したソフトで使う」を参照）。「高田」という名前の駅は2つ（「信越本線」の `PS04284` と、「和歌山線」・「櫻井線」の `PS04285`）あります。経路を探すとき、同じ名前の駅がいくつもあれば、スクリプトはそのすべてを出発地や目的地として使い、実際に使った駅を乗った路線とともに表示します。

#### 何日もかかる行程

何日もかかる行程も探せます。次の例は、東京から列車と船を乗り継いで哈爾賓（ハルビン）まで行く、4日余りの行程です（`--days` は行程にかけてよい日数で、既定は5日）。

```sh
python3 examples/route_1925.py 東京 哈爾賓 08:00 --days 5
```

次のように表示されます。

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

`(+4 days)` は4日後です。満洲の時刻も、GTFSデータと同じく日本の時刻に直して表示しています。

### 3. GTFSに対応したソフトで使う

`gtfs/` には、`shapes.txt` を除く標準的なGTFSファイルが入っています。

- Pythonのライブラリgtfs-kit（<https://pypi.org/project/gtfs-kit/>）とpartridge（<https://pypi.org/project/partridge/>）は、`gtfs/` フォルダをそのまま読み込めます。gtfs-kitの使用例は `examples/with_gtfs_kit.py` を参照してください。
- OpenTripPlanner（<https://www.opentripplanner.org/>）や、Rのパッケージtidytransit（<https://cran.r-project.org/package=tidytransit>）・gtfstools（<https://cran.r-project.org/package=gtfstools>）など、GTFSをZIPファイルで読み込むソフトでは、`gtfs/` 内の9ファイルをZIPの最上位に配置してください。配布用アーカイブには `gtfs/` フォルダが含まれるため、そのままではGTFS用のZIPとして使用できません。作成手順は `examples/opentripplanner/README.ja.md` に記載しています。
- 同じ駅でも路線ごとに別の停車地（stop）を設け、*（駅名, 路線名）* の組ごとに管理しています。これらは親駅（parent station）にまとめています。`transfers.txt` には、同じ親駅内では0分、近隣の親駅間では徒歩1〜39分の乗り換え時間を記録しています。このファイルがないと、路線間の乗り換えができません（`DETAILS.ja.md` の「3. 停車地・親駅と乗り換え」）。
- 日付をまたぐ便では、時刻を24:00に戻さず加算し続けます（例：`26:30:00`、最大 `104:30:00`）。複数日にわたる便があるため、経路検索では前日以前に出発した便も対象とし、1日を超える行程を許可する必要があります（`DETAILS.ja.md` の「2. 24:00より後の時刻」）。
- OpenTripPlannerでは、運行対象期間に1925年を含め、1日を超える行程を検索できるようにする設定も必要です。必要な設定ファイルと、サーバーに経路を問い合わせるスクリプトを `examples/opentripplanner/` に用意しています（`DETAILS.ja.md` の「12. OpenTripPlannerでの使用」）。
- GTFSの標準規格を推進する国際的な非営利団体MobilityData（<https://mobilitydata.org/>）の検査ツールgtfs-validator 8.0.1（<https://github.com/MobilityData/gtfs-validator>）ではエラーは検出されませんでした。警告の内容は、`DETAILS.ja.md` の「gtfs-validatorによる検査」の節で説明しています。

### 4. 次に読むもの

`DETAILS.ja.md`（英語版は `DETAILS.md`）では、各ファイルの中身、`extras/`・`transcription/`・`integrated/` の表の列、データ作成上の取り決めを詳しく記載しています。`KNOWN_ISSUES.ja.md`（英語版は `KNOWN_ISSUES.md`）には、書き起こしの対象外とした情報、推定を含むデータ、原本にある不整合をまとめています。

## データセットの中身

### フォルダとファイル

| パス | 内容 |
|---|---|
| `gtfs/` | GTFSファイル：`agency`、`calendar`、`feed_info`、`routes`、`stops`、`trips`、`stop_times`、`frequencies`、`transfers`（`shapes` は含みません）。このフォルダ、または9ファイルをまとめたZIPをGTFS対応ソフトに渡します（上の「基本的な使い方」の節の項目3を参照）。 |
| `extras/` | GTFSの識別子で参照できる表を中心とした16個の表と、GeoJSONファイル1個。時刻・座標・列車番号の出典、通し列車、運行日と日付指定のある航路、列車の種別・等級、運転間隔のみが記載された運行の原文、計算で求めた時刻、原本の誤植の修正記録、駅名の別表記、地図表示用に駅を直線で結んだ路線形状などを収録しています。 |
| `examples/` | GTFSの使用例。Pythonの標準ライブラリだけで動く経路検索スクリプト、gtfs-kitを使った読み込み例、OpenTripPlanner 2の設定ファイル（`opentripplanner/`）を収録しています。 |
| `tools/` | Pythonの標準ライブラリだけで動くスクリプト2本。原本に記載された運行日に従うGTFSの派生版を作成するものと、`gtfs/` と `extras/` だけから駅・便・徒歩移動を1つのJSONファイルにまとめた経路検索用ネットワークを作成するものがあります。 |
| `transcription/` | 原本の時刻表の書き起こし。1ページまたは見開きごとのワークブック178冊（列車番号の付与前・付与後の2種類）と、全データをまとめた縦長形式のCSVを収録しています。 |
| `integrated/` | 書き起こしとGTFSデータの間の段階の停車時刻です。複数のシートに別々に書かれた同じ列車の情報を統合して1本の便にしています。また、「東海道及山陽本線」のように複数の路線をまとめた名前の便を、路線ごとに分けています。 |
| `README.ja.md` | この文書（英語版は `README.md`）。 |
| `DETAILS.ja.md` | ファイルと列の詳しい説明（英語版は `DETAILS.md`）。 |
| `KNOWN_ISSUES.ja.md` | 既知の問題と利用上の注意（英語版は `KNOWN_ISSUES.md`）。 |
| `LICENSE.ja.md` | ライセンス条件の日本語の参考訳（法的に効力を持つのは英語の `LICENSE`）。 |

### `extras/` の主な表

`extras/` の主な表は次のとおりです。

| ファイル | 用途 |
|---|---|
| `stop_time_source.csv` | 原本に記載された時刻のページ・シート・列・行、各時刻が原本の値・写した値・計算値・雛形の便の時刻のどれに当たるか、原本の時刻系と日本時刻との差 |
| `stop_coord_source.csv` | 各座標の取得方法（`station`・`place`・`estimated`）、出典と識別子 |
| `trip_source.csv` | 各便の元となった書き起こしシートと、列車番号を特定した方法 |
| `physical_trains.csv` | 原本では同じ通し列車として運行する便の対応関係（GTFSでは路線ごとに別の便として収録） |
| `operating_days.csv`、`printed_sailings.csv` | 原本で毎日運行とは記載されていない便。運行日・日付が指定された便や、運行日の記載がない不定期列車（不）を含みます（`gtfs/` のGTFSデータでは毎日運行として扱います）。 |
| `estimated_stop_times.csv` | 原本にある所要時間から計算した到着時刻や、頻度だけを記した運行の推定時刻（`DETAILS.ja.md` の「6. 計算した時刻」を参照） |
| `stop_name_variants.csv` | 駅名を新字体で検索するための表記情報 |
| `trip_attributes.csv`、`route_region.csv` | 列車の種別・等級、および各路線が属する1925年当時の地域 |

各ファイルと、`extras/`・`transcription/`・`integrated/` の表の列の詳しい説明は、`DETAILS.ja.md` の「ファイルの一覧」以降を参照してください。

## CSV形式のファイルを使った分析の例

### ファイルを読み込む

Pythonのライブラリpandas（<https://pandas.pydata.org/>）などのCSV読み込みツールを使えば、各ファイルを直接分析することもできます。

```python
import pandas as pd
routes = pd.read_csv('gtfs/routes.txt')
trips = pd.read_csv('gtfs/trips.txt', dtype={'trip_short_name': str})
n = trips.groupby('route_id').size().rename('trips')
routes.join(n, on='route_id').nlargest(3, 'trips')[['route_short_name', 'route_long_name', 'trips']]
# （行の番号は省いています）
#  route_short_name route_long_name  trips
#            東海道本線          東京・神戸間    304
#             東北本線             NaN    177
#             山陽本線             NaN    147
```

### 値を原本のページまで遡る

`gtfs/stop_times.txt` の各行に対応する出典情報は、`extras/stop_time_source.csv` に記録されています。原本に記載された時刻については、書き起こしデータのページ・シート・列・行まで確認できます。

```python
src = pd.read_csv('extras/stop_time_source.csv', dtype=str)
t = trips.merge(routes).query("route_short_name == '東海道本線' and trip_short_name == '3'").trip_id.iloc[0]
src.query("trip_id == @t and stop_sequence == '1'").iloc[0]
# （主な欄）stop_name 東京 · departure_source printed · departure_page 1 · departure_sheet p0001_tb001-1 · departure_column 3 · departure_row 1
```

例えば、東京を08:15に出発する特急3列車の時刻は、原本の1ページに掲載されています。書き起こしでは、`transcription/workbooks/p001-002.xlsx` のシート `p0001_tb001-1` の列車欄3列目（`departure_column` が3）に対応します。駅の座標は `extras/stop_coord_source.csv` から出典まで、便の列車番号は `extras/trip_source.csv` から原本まで、同じようにたどれます。

## データセットの作成方法

### 原本

原本は、鉄道省運輸局編纂・日本旅行文化協会発行の『汽車時間表』第1巻第1号（1925年4月号）です。作業には、JTBパブリッシングが2022年に刊行した復刻版『時刻表復刻版 1925年4月号 創刊号』（ISBN 978-4-533-15112-5）を使用しました。復刻版のうち、1925年当時の紙面を独自にスキャンして書き起こしています。スキャン画像や、復刻版で追加された表紙カバー・解説は本データセットに含めていません。

### 書き起こしと確認

書き起こしには共通の作業基準を用い、1〜22ページと178〜185ページの計30ページを人手で、それ以外をLLMエージェント（大規模言語モデルを利用するエージェント）で処理しました。全ページについて、スキャン画像との照合を人手と自動チェックの両方で実施しています。ただし、人手で書き起こした30ページは、同じ作業者が照合も担当したため、人手の確認は独立した検証ではありません。これらのページについてはLLMエージェントによる画像との照合も行いました。書き起こした時刻セルを無作為に500件抽出したところ、原本と異なるものが1件あり、公開前に修正しました。

スキャン画像で数字の判読が難しい場合（特に太字の3・8・9）は、前後の列車や同じ列車を掲載した別ページと整合する読み方を採用しました。原本の誤植と判断した値は、正しい値を確実に判断できる場合に限って修正し、`extras/misprint_corrections.csv` に記録しています。雛形の便を作成する元となる、頻度だけを記した運行の原文（`extras/frequency_only.csv`）は別途書き起こしたため、ページごとの照合対象には含まれていません。

### GTFSデータの作成

GTFSの作成時には、同じ列車が掲載された複数のシートを統合し、列車と路線の組ごとに1便を作成しました。また、原本に時差が明記されている地域の時刻を日本時刻に換算しています。`gtfs/agency.txt` では、事業者を「汽車時間表 1925年4月号（翻刻）」の1件に統一しており、鉄道省・私鉄・南満洲鉄道・船会社などの実際の運行事業者には割り当てていません。書き起こしと加工処理の詳細は `DETAILS.ja.md` を参照してください。

## 駅の座標とその出典

### 座標の求め方

駅の座標は、1925年当時の位置をおおよそ表すものです。`extras/stop_coord_source.csv` には、各停車地の座標の取得方法と出典・識別子を記録しています（`DETAILS.ja.md` の「時刻・列車番号・座標の出どころ」を参照）。

駅そのものの座標（`coord_class` が `station`）には、Wikipediaの駅記事（主に日本語版のほか、中国語版・韓国語版・ロシア語版。`reference_id` で参照した版を特定できます）、Wikidata、国土交通省「国土数値情報（鉄道データ）」N02-25、歴史地名データ（旧版5万分の1地形図に示された駅を含む）、「今昔マップ on the web」で本プロジェクトが旧版地形図から読み取った座標を使用しています。

これらの出典から駅そのものの位置を特定できない場合は、近隣の地名の代表点（`place`）や、前後の駅の位置から計算した推定座標（`estimated`）を用いています。推定には、主に1925年の時刻表に掲載された哩程（起点駅からの距離をマイルで示したもの）を利用しました。地名の代表点には、国土交通省の位置参照情報、Wikidata、町・港・近隣の現役駅に関するWikipedia記事、国土交通省の鉄道データN02-25、GeoNames、地理院地図（一部の港の発着地点）、歴史地名データ、旧版地形図の読み取り結果を使用しました。また、駅の所在地の大字を特定する際には、1926年版『鐵道停車場一覽』を参照しました。Wikipediaから取得したのは座標と記事の版の識別子だけで、地図サービスからは緯度・経度のみを読み取っています。記事本文や地図画像は収録していません。

### 出典の表示

利用条件に基づく出典表示は次のとおりです。

- 「国土数値情報（鉄道データ）」N02-25、国土交通省、CC BY 4.0。出典：国土交通省国土数値情報ダウンロードサイト（<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html>）。「国土数値情報（鉄道データ）」（国土交通省）（<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html>）を加工して作成
- 「大字・町丁目位置参照情報」、国土交通省（令和7年（2025年）版、19.0b版）。出典：位置参照情報ダウンロードサービス（国土交通省）（<https://nlftp.mlit.go.jp/isj/>）。「位置参照情報ダウンロードサービス」（国土交通省）（<https://nlftp.mlit.go.jp/isj/>）を加工して作成
- 地理院地図、国土地理院（出典：地理院地図（国土地理院）（<https://maps.gsi.go.jp/>））
- 歴史地名データ、人間文化研究機構（NIHU）とH-GIS研究会（旧5万分の1地形図と『大日本地名辞書』の地名）。加工して使っています。「歴史地名データ（人間文化研究機構・H-GIS研究会。旧5万分の1地形図・大日本地名辞書の地名）を加工して作成」。このデータセットは、人間文化研究機構とH-GIS研究会の研究成果を利用しています（<https://www.nihu.jp/ja/database/source_map/about.html>）。
- 今昔マップ on the web：谷 謙二 (2017) 「今昔マップ旧版地形図タイル画像配信・閲覧サービス」の開発. GIS-理論と応用, 25(1), 1–10
- Wikipedia（駅と地名の記事。版へのリンクは `reference_id`）、Wikidata（CC0）、GeoNames（geonames.org、CC BY 4.0）
- 『鐵道停車場一覽』1926年（大正15年）版、国立国会図書館、pid 1020981（<https://dl.ndl.go.jp/pid/1020981>。著作権の保護期間が満了したもの）

## 利用上の注意

- 本データセットは時刻表に掲載された運行予定を表しており、実際の運行実績を確認したものではありません。掲載されているからといって特定の日に運行したとは限らず、GTFSに収録されていないからといって運行がなかったとも限りません（`KNOWN_ISSUES.ja.md` の1〜3節を参照）。
- 運賃は構造化データとして書き起こしていませんが、`extras/frequency_only.csv` の原文には一部が残っています。航路表の船名・トン数・旅客定員の欄も対象外です（列見出しにある船名は収録）。表中の縦書き注記は停車時刻として扱わず、書き起こしの確認メモ（ワークブックの12行目）に残しています。ただし、注記の書き起こしは網羅的ではありません。
- 駅の座標は交通ネットワーク全体の分析や地図表示を想定した**概略位置**であり、数百メートル単位の位置精度を必要とする分析には適しません。`extras/stop_coord_source.csv` の `coord_class` で、駅自体の位置・近隣地名の代表点・推定位置を区別できます。
- 運転間隔に基づく便の発車時刻や、一部の途中駅の時刻は推定値です（`timepoint` が `0`）。原本に到着時刻か発車時刻の一方しかない場合は、GTFSに必要なもう一方の欄にも同じ時刻を入れています。このため、到着と発車が同時刻でも、停車時間が0分とは限りません。
- 原本で複数の路線をまとめて示した見出し（例：「臺灣總督府鐵道縦貫線及臺中線」）を、路線名として残した便もあります（`KNOWN_ISSUES.ja.md` の4節を参照）。

既知の問題の全項目と件数は `KNOWN_ISSUES.ja.md` にまとめています。

## 利用条件と引用

### 利用条件

`gtfs/` のGTFSデータ、`extras/` の補足表、`transcription/` の書き起こし、`integrated/` の統合データには、クリエイティブ・コモンズ 表示 4.0 国際（CC BY 4.0、<https://creativecommons.org/licenses/by/4.0/>）を適用しています。`examples/` と `tools/` のスクリプト・設定ファイルにはMITライセンスを適用しています。詳しくは `LICENSE` を参照してください（日本語の参考訳は `LICENSE.ja.md`）。駅の座標には前述の出典データを使用しているため、それぞれの利用条件に従った出典表示が必要です。

### 引用

このデータセットを引用する際は、次の形式を使用してください。

Ouchi, H., & Yamamoto, S. (2026). Japan1925-GTFS: a dataset of scheduled railway and ferry services from Japan's 1925 national timetable (Version v1.0) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.23200420

BibTeX形式では次のようになります。

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

## データセットのバージョン

このデータセットはv1.0です（`gtfs/feed_info.txt` の `feed_version` は `20261026-ebd6f64c`）。今後の修正はZenodoで新しいバージョンとして公開します。停車地・親駅・路線・便の識別子はバージョン間で維持し、削除した項目の識別子も再利用しません。

## 誤りの報告

誤りを見つけた場合は、`gtfs/feed_info.txt` に記載された連絡先に、該当する `trip_id` または `stop_id` と、可能であれば原本のページ番号を添えてご連絡ください。書き方の例は `KNOWN_ISSUES.ja.md` の「誤りの報告」にあります。
