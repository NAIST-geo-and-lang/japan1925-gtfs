# Japan1925-GTFS：処理のコード

この文書は `README.md` の日本語訳です。内容が異なる場合は、英語版を優先します。

このリポジトリには、データセット**Japan1925-GTFS**の作成に使ったコードと、人手で作った参照の表が入っています。Japan1925-GTFSは、1925年4月の全国時刻表に掲載された鉄道と船舶の定期の運行のデータセットで、Zenodoで公開しています（<https://doi.org/10.5281/zenodo.23200420>、v1.0）。

このリポジトリを使うと、公開したデータセットで経路検索を試すこと、公開した書き起こしのワークブックからデータセットを作り直すこと、データセットを説明する論文で報告した経路検索の検証をもう一度実行することができます。論文が公開されたら、ここに書誌情報を足します。

## はじめに：経路検索を試す

経路検索（`demo/route_planner/index.html`）は、公開したデータセットで経路を探し、地図の上に示すウェブページです。必要なのはPython 3（ほかのライブラリは要りません）とブラウザだけで、データセットを作り直す必要はありません。

### 1. このリポジトリとデータセットをダウンロードする

```sh
git clone https://github.com/NAIST-geo-and-lang/japan1925-gtfs.git
cd japan1925-gtfs
curl -fL -o japan1925-gtfs-v1.0.zip "https://zenodo.org/records/23200420/files/japan1925-gtfs-v1.0.zip?download=1"
python3 -c "import hashlib, sys; h = hashlib.md5(open('japan1925-gtfs-v1.0.zip', 'rb').read()).hexdigest(); print(h); sys.exit(h != '4419cf6daae9a7787ccf3894fb400088')" && unzip -q japan1925-gtfs-v1.0.zip
```

ZIPファイルは約21MB（展開すると160MB）です。4つ目のコマンドは、ZIPファイルのMD5チェックサムを表示し、Zenodoに記録された値（4419cf6daae9a7787ccf3894fb400088）と同じときだけ展開します。違う値が出たときは、もう一度ダウンロードしてください。<https://doi.org/10.5281/zenodo.23200420> からダウンロードして、このフォルダに展開してもかまいません。

### 2. 経路検索用のネットワークを作る

```sh
python3 japan1925-gtfs-v1.0/tools/make_router_data.py --feed japan1925-gtfs-v1.0 --out demo/route_planner
```

1秒ほどで終わります。データセットの `gtfs/` と `extras/` だけを読み、ページの隣に `router_data.js`（と、同じデータの `router_data.json`）を書き出します。

### 3. ページを開く

`demo/route_planner/index.html` をブラウザで開きます。ファイルを直接開けば動きます（ウェブサーバーは要りません）が、地図の表示にはインターネット接続が必要です。背景の地図は国土地理院の地理院タイルです。詳しい地図は日本とその周辺だけなので、台湾・樺太・朝鮮・満洲を拡大すると、背景の地図が消えます。ページの上の行に `データ: Japan1925-GTFS 20261026-ebd6f64c（駅 4576・便 22949）` と出ます。

出発の駅、到着の駅、出発の時刻を入れて「検索」を押すか、その下の「例」のどれかを押します。たとえば、東京→下關を08:00で探すと3つの経路が並び、1つ目は次のとおりです。

```text
08:15 発 → 08:05 着   23時間50分   乗換 0 回
東海道本線→山陽本線 3号   直通
```

東京を08:15に出て、翌日の08:05に下關に着きます（23時間50分、乗換0回）。乗るのは、東海道本線から山陽本線へ直通する3号です。選んだ経路の停車駅は右に並び、下の「▶ 出発」を押すと、地図の上を列車が動きます。ページの表示は日本語です。駅名は、時刻表の原本に記載された字体で入れます（たとえば下関でなく下關）。入力欄は、打つと駅名の候補を出します。

コマンドで探すときは、データセットの `examples/route_1925.py` を使います（データセットのREADMEを参照）。

## このリポジトリの中身

| 場所 | 中身 |
|---|---|
| `reproduce.sh` | 作成の全体を通して実行します：抽出 → 統合 → 座標を付けたGTFSデータの作成 → データセットの形にまとめる |
| `requirements.txt` | 作成の処理に使うPythonのパッケージ（検証だけで使うパッケージは、「経路検索の検証」のコマンドで入れます） |
| `scripts/` | 処理の各段（`extract_stop_times.py`・`integrate_stop_times.py`・`run_pipeline.sh` と、そこから呼ぶスクリプト） |
| `scripts/release/` | データセットの形にまとめる処理とその検査（`build_release_all.sh`）、データセットにそのまま写す文書と見本、ダウンロードの道具 |
| `data/tables/` | 作成の処理が読む人手の表：列車番号の付け替え、時刻系の規則、通し列車、著と發の2行、頻度だけを記した運行、誤植、航路の運航日など。説明は `data/tables/README.md` |
| `data/knowledge/places/` | 座標の表（場所、駅ごとの場所、計算した値、地図の読み取り）。説明は `data/knowledge/places/README.md` |
| `data/knowledge/public_release/` | 座標の検査が読む照合用の記録と、公開する番号を変えないための番号台帳。説明は `data/knowledge/public_release/README.md` |
| `data/knowledge/release_reference_coords.json` | 出典に挙げたWikipediaの版とWikidataの項目の座標を、前もってダウンロードしたもの。座標の検査が、公開した座標をこれと比べます |
| `data/distance/` | 時刻表に記載された哩程の表。座標の内挿と検査に使います |
| `demo/route_planner/index.html` | 経路検索（ウェブページ。「はじめに」を参照。検索の部分は検証でも使います） |
| `tests/` | 経路検索の検証（`route_search/`・`pyraptor/`・`opentripplanner/`）と、PythonのGTFSライブラリで読めるかの確認（`python_libraries/`） |

コードのコメントは英語です。スクリプトが画面に出すメッセージと、表の文の欄は日本語です。

## データセットの作り直し

作り直しには、Python 3.14、約1GBの空き容量、ダウンロードのためのインターネット接続が要ります。Pythonのパッケージは `requirements.txt` に書いてあります（openpyxl 3.1.5とshapely 2.1.2。公開したデータセットを作ったときのバージョンです）。作り直したフィードを検査するGTFS Validator 8.0.1とJava 17は、自動でダウンロードし、決めておいたSHA-256のチェックサムと照らしてから使います。

```bash
python3.14 -m venv .venv   # このリポジトリ用のPythonの環境（初めに1回）
source .venv/bin/activate
pip install -r requirements.txt
```

この環境を有効にしたまま、次を実行します。

```bash
python3 scripts/fetch_transcription.py              # 1. Zenodoからデータセットをダウンロードし、書き起こしのワークブックを置く
python3 scripts/release/fetch_external_sources.py   # 2.（任意）座標の最後の検査に使う参照データ
bash reproduce.sh                                   # 3. 作り直し（約15分）
```

「はじめに」でZIPファイルをダウンロードしてあれば、手順1を `python3 scripts/fetch_transcription.py --zip japan1925-gtfs-v1.0.zip` として実行すると、ダウンロードを省けます。

データセットは `data/gtfs_v1_release/` に書き出されます。Zenodoで公開したファイルと比べると、書き起こしのワークブック（`.xlsx`）以外はすべてバイト単位で同じです。ワークブックはセルの値が同じで、内部のXMLだけがわずかに違います（カーソルの位置と既定の書式の属性）。書式を整えたあとのワークブックに、書式を整える処理をもう一度当てるためです。

手順2では、公開した座標がどれも引用できる出典で説明できることを確かめるために、次の公開データをダウンロードします。スクリプトは、提供元が配っているファイルを直接ダウンロードします。実行すると、それぞれの提供元の利用の決まりに同意したことになります。

- 国土交通省「国土数値情報（鉄道データ）」N02-25（CC BY 4.0）：国土数値情報ダウンロードサイトの利用規約（<https://nlftp.mlit.go.jp/ksj/other/agreement.html>）
- 国土交通省「大字・町丁目位置参照情報」令和7年版（19.0b版）：位置参照情報ダウンロードサービスの利用約款（<https://nlftp.mlit.go.jp/isj/agreement.html>）
- GeoNames（CC BY 4.0）：<https://www.geonames.org/about.html>
- Natural Earth（パブリックドメイン）：<https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/LICENSE.md>

人間文化研究機構とH-GIS研究会の歴史地名データは、手でダウンロードする必要があります。入手先と置き場所は、スクリプトが表示します。これらのデータが無くても、作り直しはデータセットを書き出し、出典と照らせなかった駅を知らせます。Natural Earthの陸地のデータは、駅が陸の上にあるかを確かめるために作り直しの処理でも使うので、手順2を飛ばしたときは作り直しの処理がダウンロードします。

## 経路検索の検証

`reproduce.sh` は、作り直したデータセットから経路検索用のネットワークも作ります（`data/gtfs_v1_release_router/`）。その `router_data.js` は、「はじめに」で作るものとバイト単位で同じです。

検証は作り直したデータセットを読み、(ii)のほかは上の環境で実行します。(i)にはNode.js 18以降も要ります。(ii)で使うpyraptor 1.3.10はpandas 2.0より前のバージョンを求めるのでPython 3.11以前でしか動かず、(ii)は別の環境で実行します。下のコマンドは、論文の結果を出したときのバージョンを入れます（pyraptorはattrsを読み込みますが、依存として届け出ていません）。比べるのに約10分かかります。(iv)では、上の環境にgtfs-kit 13.0.1とpartridge 1.1.2を入れます。(iii)のOpenTripPlanner 2.10.0とJava 25は、初めて実行するときに自動でダウンロードし、決めておいたSHA-256のチェックサムと照らします。(iii)はグラフを作り、OpenTripPlannerのサーバーを最大4つ同時に、それぞれ最大4GBのメモリで動かします。サーバーは、このコンピューターからだけ使えます（ポート18090〜18094）。結果は `data/reports/opentripplanner_<日付>/` に書き出され、作業用のフォルダ（新しい一時フォルダ、または `OTP_WORK_DIR`）は実行のあとも残ります。

```bash
# (i) 基本の動き：行程が成り立つか、答えの分かっている検索、物理的にありえない区間
node tests/route_search/check_route_itineraries.js
python3 tests/route_search/check_route_expectations.py
python3 tests/route_search/check_route_data_quality.py --rq4-only

# (ii) pyraptorとの比較（別の環境 tests/pyraptor/venv で実行する）
cd tests/pyraptor
python3.11 -m venv venv
venv/bin/pip install pyraptor==1.3.10 pandas==1.5.3 numpy==1.26.4 attrs==26.1.0
venv/bin/python make_pyraptor_gtfs.py --release ../../data/gtfs_v1_release --out out/gtfs
venv/bin/python build_timetable.py --in out/gtfs --out out/timetable
venv/bin/python compare_route_planner.py --gtfs-dir out/gtfs --pyraptor-out out/timetable                         # 決まった14件
venv/bin/python compare_route_planner.py --gtfs-dir out/gtfs --pyraptor-out out/timetable --sample 300 --seed 1   # 無作為の300件
cd ../..

# (iii) OpenTripPlanner 2.10.0で使えるか（初めて実行するときにOpenTripPlannerとJava 25をダウンロードする）
bash tests/opentripplanner/run_otp_check.sh

# (iv) gtfs-kitとpartridgeで読めるか
pip install gtfs-kit==13.0.1 partridge==1.1.2
python3 tests/python_libraries/check_python_libs.py data/gtfs_v1_release
```

作り直したデータセットでは、検証は論文で報告した結果になります。

- (i) 175の検索のすべてで行程が成り立ち、答えの分かっている25の検索もすべて期待どおりです（どちらもFAIL 0）。145,297の区間に、物理的にありえないものはありません。
- (ii) 決まった14件は一致します。無作為の300件では、276件が一致し、16件はどちらも経路がなく、残りの8件はどちらかの探す上限に当たります。
- (iii) 320の検索のうち、OpenTripPlannerとデータセットの経路検索 `examples/route_1925.py` で、最も早く着く時刻、または経路が無いことが一致するのは、データセットにある設定で262件、頻度で表した便をすべて決まった時刻で走らせたときに269件です。OpenTripPlannerの既定の設定に、このフィードに要る2つの設定（1925年の便を残すことと、4日までの旅を探すこと）を足したときは256件です。
- (iv) どちらのライブラリも、GTFSのファイルをすべて読めます（路線541、便10,080）。

## ライセンス

作成の処理が読む表（`data/` の下のCSVとJSONのファイル）と、検証が使う表（`tests/` の下のCSVのファイル）には、公開したデータセットと同じく、クリエイティブ・コモンズ 表示 4.0 国際（CC BY 4.0）を適用しています。ほかのファイル（スクリプト、経路検索、設定ファイル、文書）にはMITライセンスを適用しています。`scripts/release/shinjitai_map.csv` の字の組のほとんどは、kyujipy（MITライセンス）から取っています。詳しくは `LICENSE` を参照してください。

## 引用

データセットを使うときは、次の形式で引用してください。

Ouchi, H., & Yamamoto, S. (2026). Japan1925-GTFS: a dataset of scheduled railway and ferry services from Japan's 1925 national timetable (Version v1.0) [Data set]. Zenodo. <https://doi.org/10.5281/zenodo.23200420>

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
