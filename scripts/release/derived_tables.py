#!/usr/bin/env python3
"""
Copy three kinds of derived tables that standard GTFS files cannot express into extras/ of the published dataset.
Called from item 19 of scripts/build_release_gtfs.py (RELEASE_DERIVED_TABLES=1, default). The source tables
(CSV files in GTFS_DIR) are not changed.
Column descriptions: "Details of the derived tables (extras/)" in scripts/release/DETAILS_release.md.

  1. trip_attributes.csv (train type and facilities per trip: limited express, express, classes, sleeper, diner marks)
  2. service_frequency.csv (sailing frequency per ship trip: daily, alternate days, monthly, printed dates, not stated)
     -> Both are keyed by the internal trip_key, so a trip_id column is prepended (relabel_stable_ids rewrites it to
        published IDs). Ship trips merged into one for identical times (RELEASE_MERGE_SAME_SAILINGS) get the ID of the
        trip carrying those times. Trips missing from the published dataset (there should be none) get an empty trip_id.
  3. Frequency source text and interpretation: frequency_box.csv (frequency boxes "此間○分毎" in tables),
     frequency_sections.csv (interpretation of frequency-only sections), frequency_only.csv (their source text)
     -> The template trip column template_trip_id is renamed trip_id (relabeled to published IDs). prev_trip_id/
        next_trip_id of frequency_box are column numbers of the transcription sheet (row 7), so they are renamed
        prev_column/next_column to avoid confusion with GTFS trip_id.
  - In free-text fields, parenthetical notes and sentences containing internal record words (MARKERS) are dropped;
    stop if any remain.
  - With RELEASE_SCRUB_ALL_EXTRAS=1 (build_release_gtfs.py, default), the same scrubbing is applied to every CSV in
    extras/ (scrub_extras), the ★ marks are removed, and finally all published files are checked for remaining
    words and ★ (check_release_text).
"""
import csv
import os
import re

TRIP_KEYED = ('trip_attributes.csv', 'service_frequency.csv')
FREQ_TABLES = ('frequency_box.csv', 'frequency_sections.csv', 'frequency_only.csv')
FILES = TRIP_KEYED + FREQ_TABLES
RENAME = {'frequency_box.csv': {'template_trip_id': 'trip_id', 'prev_trip_id': 'prev_column',
                                'next_trip_id': 'next_column'},
          'frequency_sections.csv': {'template_trip_id': 'trip_id'}}
# Words kept out of the published dataset (internal work records): record numbers, approvals, internal work folders.
MARKERS = re.compile(r'§\d+-\d+|チェックリスト|決裁|確認作業/')
_PAREN = re.compile(r'（[^（）]*）')


def _read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def _write(path, fields, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fields})


def scrub(text):
    """Drop parenthetical notes and sentences containing internal record words; return the text unchanged if none.
    In a full-width parenthesis （…）, only the parts (split at "・" or "／") containing a word are dropped; if all
    parts go, the parenthesis goes. Then sentences (split at "。") still containing a word are dropped."""
    if not text or not MARKERS.search(text):
        return text

    def paren(m):
        inner = m.group(0)[1:-1]
        if not MARKERS.search(inner):
            return m.group(0)
        parts = re.split(r'([・／])', inner)
        keep, sep = [], ''
        for i, p in enumerate(parts):
            if i % 2:                       # separator
                sep = p
                continue
            if p.strip() and not MARKERS.search(p):
                keep.append((sep if keep else '') + p)
            sep = ''
        return f'（{"".join(keep)}）' if keep else ''
    text = _PAREN.sub(paren, text)
    sentences = re.findall(r'[^。]*。|[^。]+$', text)
    text = ''.join(s for s in sentences if not MARKERS.search(s))
    return re.sub(r'[ 　]{2,}', ' ', text).strip()


def build(gtfs_dir, out_dir, key_of, kept, single_ids, merged):
    """Copy the derived tables of GTFS_DIR to out_dir (extras/ of the published dataset).
    key_of: internal trip_id -> internal key; kept: trips kept in the published trips.txt; single_ids: trips moved to
    single_stop_trips.csv; merged: {merged ship trip: trip carrying its times}. Return a summary (counts etc.)."""
    id_of_key = {k: tid for tid, k in key_of.items()}
    in_release = set(kept) | set(single_ids)

    def public_tid(tid):
        tid = merged.get(tid, tid)
        return tid if tid in in_release else ''

    summary, scrubbed = {}, []
    for name in FILES:
        src = os.path.join(gtfs_dir, name)
        if not os.path.exists(src):
            summary[name] = 'なし'
            continue
        fields, rows = _read(src)
        ren = RENAME.get(name, {})
        fields = [ren.get(f, f) for f in fields]
        rows = [{ren.get(k, k): v for k, v in r.items()} for r in rows]
        if name in TRIP_KEYED:
            fields = ['trip_id'] + fields
            for r in rows:
                r['trip_id'] = public_tid(id_of_key.get(r['trip_key'], ''))
        elif 'trip_id' in fields:           # template trips: only those kept in the published trips.txt
            for r in rows:
                if r['trip_id'] and r['trip_id'] not in kept:
                    r['trip_id'] = ''
        rid = next((f for f in ('box_id', 'section_id', 'id', 'trip_key') if f in fields), fields[0])
        for r in rows:
            for k in fields:
                v = r.get(k) or ''
                s = scrub(v)
                if s != v:
                    scrubbed.append((name, r.get(rid, ''), k))
                    r[k] = s
        left = [(r.get(rid, ''), k) for r in rows for k in fields if MARKERS.search(r.get(k) or '')]
        if left:
            raise SystemExit(f'派生表 {name}: 公開物に出さない言葉が残っている: {left[:5]}')
        _write(os.path.join(out_dir, name), fields, rows)
        n_tid = sum(1 for r in rows if r.get('trip_id')) if 'trip_id' in fields else None
        summary[name] = f'{len(rows)} 行' + (f'（trip_id あり {n_tid}）' if n_tid is not None else '')
    return summary, scrubbed


# Apply the same scrubbing to every table in extras/ (used with RELEASE_SCRUB_ALL_EXTRAS=1 in build_release_gtfs.py).
#   Also remove ★ (an internal "attention" mark, not a symbol of the original). Sentences with ★ carry real
#   explanations, so only the mark is removed, not the sentence.
STAR = '★'
MARKERS_ALL = re.compile(MARKERS.pattern + '|' + STAR)


def scrub_all(text):
    """scrub, then remove ★ marks. Return the text unchanged if it has neither words nor marks."""
    if not text or not MARKERS_ALL.search(text):
        return text
    s = scrub(text)
    if STAR in s:
        s = re.sub(r'[ 　]{2,}', ' ', s.replace(STAR, '')).strip()
    return s


# Rewrite internal work words (RELEASE_REWRITE_WORK_WORDS=1 in build_release_gtfs.py, on by default). Separately from
#   MARKERS, internal version names, task names, issue numbers and internal file names in free text of the tables are
#   reworded for outside readers (dropping whole sentences would also lose explanations of how values were read).
#   "読み直し" (re-reading) and "是正" (correction) stay as explanations of how a value was read.
WORK_WORDS = re.compile(r'v3|過去ログ|座標作業|(?<![A-Za-z])[A-Z]-\d{2}(?!\d)|\.xlsx|_estimates\.csv|確認メモ|機械走査|overrides')
WORK_REWRITES = [
    (re.compile(r'（v3 に (?:近代デジタル交通網)?(p\d+)\.xlsx なし）'), r'（\1 の転記なし）'),
    (re.compile(r'v3 シート'), '転記のシート'),
    (re.compile(r'v3 に(は?)シートあり'), r'転記に\1シートあり'),
    (re.compile(r'v3 の'), '転記の'),
    (re.compile(r'v3 で'), '転記で'),
    (re.compile(r'v3 に'), '転記に'),
    (re.compile(r'過去ログで'), '以前の作業の記録で'),
    (re.compile(r'（座標作業 p\d+ の指摘）'), '（座標の確認での指摘）'),
    (re.compile(r'・座標作業 p\d+ の指摘'), '・座標の確認での指摘'),
    (re.compile(r'推定の表 frequency_sections_estimates\.csv ?'), '推定の根拠の表'),
    # work-procedure words
    (re.compile(r'（S8＝overrides に書く）'), ''),
    (re.compile(r'機械走査に出ない'), '自動の読み取りでは拾えない'),
    (re.compile(r'確認メモ'), '転記の注記'),
]


# Second table (RELEASE_REWRITE_WORK_WORDS_2 in build_release_gtfs.py, on by default): rewords work dates, names of
#   transcription rules, names of tables not in the published dataset and internal integration terms in free text.
#   "読み直し" and "是正" stay as explanations; only their dates are removed.
WORK_WORDS_2 = re.compile(r'2026-\d{2}-\d{2}|規約「|推定の根拠の表|採用外シート|trip_num \d|読まなかった表記|'
                          r'コーパスの慣習|に是正（座標の確認での指摘）')
WORK_REWRITES_2 = [
    (re.compile(r'規約「1 箱＝1 空列」に合わせて空列は 1 本にしました（2026-\d{2}-\d{2} に 2 本→1 本へ是正）'),
     '転記では 1 つの箱を空の列 1 本で表すので、空列は 1 本にしました'),
    (re.compile(r'（2026-\d{2}-\d{2} (\d+ ?dpi で確認)）'), r'（\1）'),
    (re.compile(r'下の 2026-\d{2}-\d{2} の追記'), 'あとの追記'),
    (re.compile(r'2026-\d{2}-\d{2} の読み直し'), '読み直し'),
    (re.compile(r'2026-\d{2}-\d{2} に原本の現物で'), '原本の現物で'),
    (re.compile(r'2026-\d{2}-\d{2} 原本'), '原本'),
    (re.compile(r'2026-\d{2}-\d{2} に'), ''),
    (re.compile(r'（2026-\d{2}-\d{2}）'), ''),
    (re.compile(r'（2026-\d{2}-\d{2}・'), '（'),
    (re.compile(r'／2026-\d{2}-\d{2} '), '／'),
    (re.compile(r'推定の根拠の表で'), '推定（extras/frequency_sections.csv の source が estimate の行）で'),
    (re.compile(r'推定の根拠の表に'), '推定（extras/frequency_sections.csv の source が estimate の行）に'),
    (re.compile(r'表記は採用外シートから'), '表頭の表記は、統合で使わなかった同じ便の別の掲載（シート）から'),
    (re.compile(r'番号が合わないので読まなかった表記'), '便の番号と合わないので使わなかった表頭の表記'),
    (re.compile(r'trip_num (\d)'), r'番号 \1'),
    # applied after the date rewrites above, so these two come last (leaving only how the station name was read)
    (re.compile(r'（原本は旧字 鄕・コーパスの慣習で 郷）'), '（原本は旧字 鄕）'),
    (re.compile(r'／原本 600dpi で (.+?) に是正（座標の確認での指摘）'), r'／原本の 600 dpi の複写で \1 と読み直した'),
]


# Third table (RELEASE_REWRITE_WORK_WORDS_3; the extras tables in build_release_gtfs.py and the transcription notes
#   (row 12) in package_layers.py; on by default): rewords names used only inside the work into the wording of the
#   published documents (e.g. 箱 -> 運転間隔の欄, 区画 -> 頻度だけを記した運行, 転記 -> 書き起こし, 空列 -> 空の列,
#   下流 -> GTFS データ, 仕様/規約 -> 書き起こしの決まり) and drops 型B and sentences about internal work.
#   Values (times, station names, quotes from the original) are unchanged.
#   Applied only to FREE_TEXT_COLS (notes, memos, basis, classification text), not to station names (箱根, 箱崎) or
#   source text (text_raw).
FREE_TEXT_COLS = {'basis', 'memo_raw', 'note', 'kind', 'type', 'already_sheet', 'position', 'printed_text',
                  'frequency_raw', 'frequency_kind', 'pm_reading', 'table_note'}
WORK_WORDS_3 = re.compile(
    r'区画|型[BD](?![A-Za-z0-9])|下流|上流の|仕様|規約|転記|トラッカー|統合の段|統合で使わなかった|シート化|空列|頻度便|頻度箱|'
    r'雛形便|行帯|列ピッチ|手掛かり|以前の作業の記録|指示の|本CSV|窓 \d/\d|S9 |書き起こし対象外|は対象外|此間箱|」の箱|（箱）|'
    r'(?:この|原本の|直前の)箱|箱の(?:幅|位置|便)|箱付き|箱が 2|自動の読み取り')
_TRIGGER_3 = re.compile(r'箱|区画|型[BD]|下流|上流|仕様|規約|転記|トラッカー|統合|シート化|空列|頻度便|雛形便|行帯|手掛かり|'
                        r'以前の作業|指示|本CSV|窓|対象外|自動の読み取り|trip_id=')
WORK_REWRITES_3 = [(re.compile(p), r) for p, r in [
    # --- headway field (箱)
    (r'（原本の頻度記載・空列）', '（書き起こしでは空の列）'),
    (r'」の箱＝空列（頻度便は長野方面）', '」の運転間隔の欄＝空の列（運転間隔で走る便は長野方面）'),
    (r'」の箱（頻度記載）なので空列にしている', '」の運転間隔の欄なので空の列にしている'),
    (r'」の箱＝空列', '」の運転間隔の欄＝空の列'),
    (r'」の箱（', '」の運転間隔の欄（'),
    (r'」の箱）', '」の運転間隔の欄）'),
    (r'」の箱付き）', '」の運転間隔の欄付き）'),
    (r'」の箱がある型で、指示の「対象外」に当たる可能性が高い。', '」の運転間隔の欄がある表。'),
    (r'」の箱が 2 つ入る形', '」の運転間隔の欄が 2 つ入る形'),
    (r'（列でなく行帯の注記）', '（列でなく、表の行にまたがる注記）'),
    (r'の囲み（箱）があります', 'の運転間隔の欄があります'),
    (r'原本での箱の幅は 2 列ぶん（列ピッチ [\d.]+px に対し実測 [\d.]+px）ですが、', '原本での欄の幅は 2 列ぶんですが、'),
    (r'規約「1 箱＝1 空列」に合わせて空列は 1 本にしました', '書き起こしでは 1 つの欄を空の列 1 本で表すので、空の列は 1 本にしました'),
    (r'転記では 1 つの箱を空の列 1 本で表すので、空列は 1 本にしました', '書き起こしでは 1 つの欄を空の列 1 本で表すので、空の列は 1 本にしました'),
    (r'はこの箱に含まれるため', 'はこの欄に含まれるため'),
    (r'箱の位置に他の帯の便が', '欄の位置に他の帯の便が'),
    (r'（原本の箱。', '（原本の運転間隔の欄。'),
    (r'」欄（頻度箱）＝時刻は無いので空列', '」の運転間隔の欄＝時刻は無いので空の列'),
    (r'此間箱=', '此間の欄＝'),
    (r'原本の箱は上段', '原本の運転間隔の欄は上段'),
    (r'＝頻度便は長野方面のみで柏原区間に箱の便は無い', '＝運転間隔で走る便は長野方面のみで、柏原の区間には無い'),
    (r'此間○分毎の箱。転記にはシートあり）', '此間○分毎の運転間隔の欄。書き起こしにシートあり）'),
    (r'此間○分毎の箱＝書き起こし対象外）', '此間○分毎の運転間隔の欄。書き起こしていない）'),
    (r'S9 格子＋箱 窓 (\d)/3＝', r'時刻の格子と運転間隔の欄の表。3 つの時間帯の \1 つ目＝'),
    (r'（間隔は直前の箱）', '（間隔は直前の欄）'),
    (r'メモが隣の列にあるので自動の読み取りでは拾えない・雛形便 (\S+) のこのシートの区間が',
     r'メモが隣の列にあるので、人が原本を読んで値を決めた・雛形にする便 \1 の、このシートの区間が'),
    # --- frequency-only services (区画)
    (r'頻度だけの区画・', '頻度だけを記した運行・'),
    (r'頻度記載のみの区画（時刻の格子なし）', '頻度だけを記した運行（時刻の格子なし）'),
    (r'頻度記載のみの区画は無い', '頻度だけを記した運行は無い'),
    (r'同じスキャンの左半分（p143）にも 土佐電氣線（非連帶線）の頻度記載区画があるが p143 は対象外なので拾っていない。', ''),
    (r'（区画全文は同区画の 1 行目）', '（全文はこの運行の 1 行目）'),
    (r'（区画全文は同区画の先頭行）', '（全文はこの運行の先頭行）'),
    (r'同区画 1 行目の続き', '同じ運行の 1 行目の続き'),
    (r'text_raw は区画全文', 'text_raw は全文'),
    (r'時刻の格子が無い「区画」は無く', '時刻の格子が無い運行は無く'),
    (r'p192 の 3 区画（', 'p192 の 3 つの表（'),
    (r'はいずれも月日の格子を持ちシート化済み', 'はいずれも月日の格子を持ち、書き起こしにシートがある'),
    (r'琵琶湖の 2 区画はシート化されていない', '琵琶湖の 2 つの運行はシートにしていない'),
    (r'（別区画）', '（別の運行）'),
    (r'本区画のシートは無い', 'この運行のシートは無い'),
    (r'区画全体に掛かる書き方', '表全体に掛かる書き方'),
    (r' ?以前の作業の記録で「頻度ベースの前例」と呼ばれた区画はこれと思われる（ページ内で時刻の格子が無い区画はこれ 1 つ）。', ''),
    (r'以前の作業の記録で p104 とされていた西武鐵道大宮線は', '西武鐵道大宮線は'),
    (r'p98\.pdf は見開きで', 'p98 のスキャン画像は見開きで'),
    (r'所要と哩程が両方刷られた区画の中央値', '所要と哩程が両方刷られた運行の中央値'),
    (r'同じ区画の本線（', '同じ表の本線（'),
    (r'この区画だけ向きごとに行を分けた', 'この運行だけ向きごとに行を分けた'),
    (r'の 2 区画は、運航概要と運賃だけで時刻の格子が無い（航路ページ仕様の型D＝頻度記載のみ）ためシート化していない',
     'の 2 つは、運航概要と運賃だけで時刻の格子が無い（頻度だけを記した運行）ため、シートにしていない'),
    (r'。手掛かりの「[^」]*」と一致／已斐町→己斐町（表題の大活字 600dpi で 己 を確認・座標の確認での指摘）',
     '。已斐町を己斐町に直した（表題の大活字を 600dpi で見て 己 と確認）'),
    # --- shipping table type (型B)
    (r'（航路仕様 型B）', ''),
    (r'（航路ページ仕様の型B）', ''),
    (r'【表の型】型B（マス目は月日）。', '【表の型】マス目は月日。'),
    (r'・型B）', '）'),
    (r'の表（型B）の', 'の表の'),
    # --- later processing (下流), earlier sheet (上流)
    (r'下流の stop_times に', 'GTFS の stop_times.txt に'),
    (r'（下流の深夜越え補正で翌朝になる）', '（GTFS データを作るときに、0 時を越えた翌朝の時刻にしている）'),
    (r'日次サフィックスは付けず、下流の深夜越え補正に任せている', '日次の印（/初日 など）は付けず、GTFS データを作るときの 0 時越えの補正に任せている'),
    (r'（下流では0時00分になる）', '（GTFS データでは 0 時 00 分になる）'),
    (r'（下流では12時50分）', '（GTFS データでは 12 時 50 分）'),
    (r'上流の中越線シートと同じ時刻を複製している', '上の中越線のシートと同じ時刻を写している'),
    # --- transcription rules (仕様, 規約)
    (r'仕様どおり時刻の後ろに', '書き起こしの決まりどおり時刻の後ろに'),
    (r'は仕様どおり対象外', 'は書き起こしていない'),
    (r'転記規約どおり除去した', '書き起こしの決まりどおり除いた'),
    (r'規約どおり空欄にした', '書き起こしの決まりどおり空欄にした'),
    (r'表番号は採番規約で振ったが、(.*?)で規約と食い違う',
     r'表番号は書き起こしの決まり（上から下、同じ高さは左から右）で振ったが、\1でこの決まりと食い違う'),
    # --- work records, internal stage names
    (r'異体字辞書に（靑,青）が登録済みなので統合の段で吸収される）。', '靑 と 青 は、GTFS データでは同じ字として扱う。'),
    (r'表頭の表記は、統合で使わなかった同じ便の別の掲載', '表頭の表記は、時刻には使わなかった同じ便の別の掲載'),
    # --- not transcribed (対象外)
    (r'は書き起こし対象外', 'は書き起こしていない'),
    (r'は転記対象外', 'は書き起こしていない'),
    (r'なので転記対象外', 'なので書き起こしていない'),
    (r'とあるが対象外）', 'とあるが書き起こしていない）'),
    (r'は対象外。', 'は書き起こしていない。'),
    (r'（転記の側で区間ごとに分けて写す）', '（書き起こしの側で区間ごとに分けて写している）'),
    # --- 転記 -> 書き起こし (after the rewrites above)
    (r'（転記の注記）', '（書き起こしの注記から）'),
    (r'本CSVでは転記しない（already_sheet 参照）', 'この表には写していない（already_sheet を参照）'),
    (r'シート化済み', '書き起こしにシートあり'),
    (r'転記済み', '書き起こし済み'),
    (r'転記した', '書き起こした'),
    (r'転記', '書き起こし'),
    (r'空列', '空の列'),
    (r'雛形便', '雛形の便'),
]]
# extras only: trip_id in text copied from source notes (a transcription sheet column) becomes "書き起こしの列"
# (transcription column) to avoid confusion with GTFS trip_id
WORK_REWRITES_3_EXTRAS = [(re.compile(r'trip_id=(\d+)＝'), r'書き起こしの列 \1＝')]


def rewrite_work_words_3(text, extras=False):
    if not text or not _TRIGGER_3.search(text):
        return text
    for pat, rep in WORK_REWRITES_3 + (WORK_REWRITES_3_EXTRAS if extras else []):
        text = pat.sub(rep, text)
    return text


def rewrite_work_words(text, second=False):
    if not text:
        return text
    if WORK_WORDS.search(text):
        for pat, rep in WORK_REWRITES:
            text = pat.sub(rep, text)
    if second and WORK_WORDS_2.search(text):
        for pat, rep in WORK_REWRITES_2:
            text = pat.sub(rep, text)
    return text


def scrub_extras(extras_dir, rewrite_work=False, rewrite_work2=False, rewrite_work3=False):
    """Apply scrub_all to every field of every CSV in extras/ and rewrite only changed files (with _write, like the
    other published CSVs). With rewrite_work=True, also reword internal work words (rewrite_work_words); with
    rewrite_work3=True, also apply rewrite_work_words_3 to FREE_TEXT_COLS. Return {file name: changed fields}."""
    changed = {}
    for name in sorted(os.listdir(extras_dir)):
        if not name.endswith('.csv'):
            continue
        p = os.path.join(extras_dir, name)
        fields, rows = _read(p)
        n = 0
        for r in rows:
            for k in fields:
                v = r.get(k) or ''
                s = scrub_all(v)
                if rewrite_work:
                    s = rewrite_work_words(s, second=rewrite_work2)
                if rewrite_work3 and k in FREE_TEXT_COLS:
                    s = rewrite_work_words_3(s, extras=True)
                if s != v:
                    r[k] = s
                    n += 1
        if n:
            _write(p, fields, rows)
            changed[name] = n
    return changed


def check_work_words(out_dir, second=False, third=False):
    """Stop if internal work words remain in extras/*.csv (WORK_WORDS; also WORK_WORDS_2 with second, and
    WORK_WORDS_3 in FREE_TEXT_COLS with third). Used with RELEASE_REWRITE_WORK_WORDS=1."""
    left = []
    ex = os.path.join(out_dir, 'extras')
    for name in sorted(os.listdir(ex)) if os.path.isdir(ex) else []:
        if name.endswith('.csv'):
            with open(os.path.join(ex, name), encoding='utf-8-sig') as f:
                text = f.read()
            left += [f'extras/{name}:{m.group(0)}' for m in WORK_WORDS.finditer(text)]
            if second:
                left += [f'extras/{name}:{m.group(0)}' for m in WORK_WORDS_2.finditer(text)]
            if third:
                fields, rows = _read(os.path.join(ex, name))
                left += [f'extras/{name}:{k}:{m.group(0)}' for r in rows for k in fields if k in FREE_TEXT_COLS
                         for m in WORK_WORDS_3.finditer(r.get(k) or '')]
    if left:
        raise SystemExit(f'公開版の付表に内部の作業の言葉が残っている（{len(left)}）: {left[:10]}')
    return 0


def check_release_text(out_dir, allow=(), final=False):
    """Stop if internal record words or ★ remain in any text file of the published dataset (GTFS, extras, README,
    examples). allow: strings removed before checking (values written for publication, such as the contact email
    in feed_info.txt)."""
    left = []
    for root, _dirs, files in sorted(os.walk(out_dir)):
        for fn in sorted(files):
            # LICENSE has no extension, so match it by name
            if not (fn.endswith(('.txt', '.csv', '.md', '.py', '.geojson', '.json')) or fn == 'LICENSE'):
                continue
            p = os.path.join(root, fn)
            with open(p, encoding='utf-8-sig', errors='replace') as f:
                text = f.read()
            for a in allow:
                if a:
                    text = text.replace(a, '')
            left += [f'{os.path.relpath(p, out_dir)}:{m.group(0)}' for m in MARKERS_ALL.finditer(text)]
    if left:
        raise SystemExit(f'公開版に内部の記録の言葉が残っている（{len(left)}）: {left[:10]}')
    if final:
        check_placeholders(out_dir)
    return 0


# In the final build (the one that inserts the DOI), stop on leftover placeholders. Only files that hold placeholders
#   are checked (free text in extras uses 〔…〕 for notes of the original, so it is not checked).
PLACEHOLDER_FILES = ('README.md', 'README.ja.md', 'DETAILS.md', 'DETAILS.ja.md', 'LICENSE', 'LICENSE.ja.md',
                     os.path.join('gtfs', 'agency.txt'), os.path.join('gtfs', 'feed_info.txt'))
PLACEHOLDER = re.compile(r'DRAFT|example\.org|〔(?:Authors|year|Title|feed_version|copyright holder|…)〕')


def check_placeholders(out_dir):
    """Stop if placeholders remain in README, LICENSE, agency.txt or feed_info.txt (the DRAFT note,
    https://example.org, 〔Authors〕〔year〕〔Title〕〔feed_version〕〔copyright holder〕, the DOI's 〔…〕).
    Called only with RELEASE_FINAL=1 in build_release_gtfs.py."""
    left = []
    for name in PLACEHOLDER_FILES:
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            with open(p, encoding='utf-8-sig', errors='replace') as f:
                left += [f'{name}:{m.group(0)}' for m in PLACEHOLDER.finditer(f.read())]
    if left:
        raise SystemExit(f'最後の作り直し（RELEASE_FINAL=1）なのに仮の値が残っている（{len(left)}）: {left[:10]}')
    return 0


def check_public_ids(out_dir):
    """After relabeling to published IDs (relabel_stable_ids), stop if an internal ID remains in trip_id of the
    derived tables."""
    left = []
    for name in FILES:
        p = os.path.join(out_dir, name)
        if not os.path.exists(p):
            continue
        for r in _read(p)[1]:
            v = r.get('trip_id') or ''
            if v and not re.match(r'TR\d', v):
                left.append(f'{name}:{v}')
    if left:
        raise SystemExit(f'派生表に内部の番号が残っている: {left[:5]}')
