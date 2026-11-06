"""Dictionary of old and new kanji forms

Collects old/new (variant) character differences for the same station or line.
Used by integration, interpolation, route search and others to align the spelling of station and line names.

Usage:
    from scripts.known_kanji_variants import VARIANTS, normalize, equivalent

    # Variant pairs in both directions (either side can be replaced)
    VARIANTS  # dict: old form -> new form, or spelling A -> spelling B

    # Normalize a station name (to a standard form, e.g. old -> new)
    normalize('廣嶋')  # → '廣島'

    # Whether two station names are the same station, differing only in variant characters
    equivalent('神戶', '神戸')  # → True
"""

# Pairs in both directions. Left and right are variants naming the same station.
# normalize() keeps the left side (old forms first).
# When adding a pair, check that two different stations on the same line do not end up with the same name.
KANJI_PAIRS = [
    # old form (left) / new form (right). The 1925 timetable normally prints the left (old) form
    ('瀨', '瀬'),       # 瀨野 ⇔ 瀬野 (p25/p27)
    ('廣島', '廣嶋'),    # 廣島 ⇔ 廣嶋 (p29/p30)
    ('廣嶋', '廣島'),    # reverse direction
    ('厚狭', '厚狹'),    # 厚狭 ⇔ 厚狹 (p29/p30)
    ('狹', '狭'),        # 狹 ⇔ 狭 at character level (若狹高濱, 若狹本鄕, ...). The scans cannot tell 狹 from 狭,
                         #   so the transcription may differ by page; downstream steps absorb it with this pair.
    ('八ッ', '八ツ'),    # 八ッ面 ⇔ 八ツ面 (p40)
    ('驛', '駅'),        # 驛 ⇔ 駅. `駅` is a postwar form not printed in 1925;
                         #   a safety net so that names written with it do not split downstream.
    ('釐', '裡'),        # 釐里 ⇔ 裡里 (p180 tb006)
    ('咸', '威'),        # 咸鏡線 ⇔ 威鏡線 (p180 tb009/tb010; the printed form is 咸)
    ('烏', '鳥'),        # 烏蘇里線 ⇔ 鳥蘇里線 (p185 tb008; the printed form is 烏)
    ('鑛', '鉱'),        # 平壌炭鑛線 ⇔ 平壌炭鉱線 (p180 tb008; the printed form is 鑛)
    ('譽', '誉'),        # 譽田 ⇔ 誉田 (p136 房總線)
    ('龜', '亀'),        # 龜山 ⇔ 亀山 (p49 tb003)
    ('橫', '横'),        # 橫濱 ⇔ 横濱 (p59/p60; the printed form is 橫)
    ('豐', '豊'),        # 豐田 ⇔ 豊田, 豐橋 ⇔ 豊橋 (p69/p70; the printed form is 豐)
    ('姫', '姬'),        # 姫路 ⇔ 姬路 (p57/p58, p59/p60)
    ('神戸', '神戶'),    # 神戸 ⇔ 神戶 (p57/p58; the printed form is 神戶)
    ('武蔵', '武藏'),    # 武蔵境 ⇔ 武藏境 (p69/p70; the printed form is 武藏)
    ('鶴崎', '鵝崎'),    # 鶴崎 ⇔ 鵝崎 (p161/p162)
    ('內', '内'),        # 黒松內 ⇔ 黒松内, 稚內 ⇔ 稚内 (p168/p170)
    ('凾', '函'),        # 凾館 ⇔ 函館, 凾館棧橋 ⇔ 函館棧橋
    #   The original uses 凾 or 函 depending on the page; the transcription follows it and this pair merges them downstream.
    ('棧', '桟'),        # 函館棧橋 ⇔ 函館桟橋 (p169/p170)
    ('穗', '穂'),        # 苗穗 ⇔ 苗穂, 樺穗 ⇔ 樺穂 (p112/p170)
    #   On some pages the scan cannot settle 穗 vs 穂; either transcription merges into one station downstream.
    ('臺', '台'),        # 臺東 ⇔ 台東, 臺中 ⇔ 台中
    ('鹽', '塩'),        # 鹽尻 ⇔ 塩尻, 鹽竈 ⇔ 塩竈
    ('輕', '軽'),        # 輕井澤 ⇔ 軽井澤, 阿波電氣輕便 ⇔ 軽便
    ('濱', '浜'),        # 横濱 ⇔ 横浜, 高濱 ⇔ 高浜
    ('儘', '尽'),        # 蛤儘 ⇔ 蛤尽 (example)
    ('縣', '県'),        # 銅山縣 ⇔ 銅山県
    ('臺中', '台中'),    # whole station names
    ('臺北', '台北'),
    ('臺南', '台南'),
    ('臺東', '台東'),

    # Line names: both forms occur in the 1925 timetable (p112/p113 etc.)
    ('鐵', '鐡'),        # 鐵道線 ⇔ 鐡道線 (水戸鐵/鐡道線 on p112 vs p113; the printed form is 鐵)
    ('關', '関'),        # 關西本線 ⇔ 関西本線 (関西本線 on p91, 關西本線 elsewhere; the printed form is 關)
    ('磐', '盤'),        # 常磐線 ⇔ 常盤線 (常盤線 on p3-4, 常磐線 elsewhere; the printed form is 磐)
    ('滿', '満'),        # 滿洲 ⇔ 満洲 (朝鮮及滿洲線 / 朝鮮及満洲線 on p5-6; the printed form is 滿)

    # Missing pairs found by matching against the mileage tables
    ('鐡', '鉄'),        # 鐡道線 ⇔ 鉄道線 (p36 駿豆鉄道線 ⇔ 駿豆鐵道線; chains with ('鐵','鐡'): 鐵→鐡→鉄)
    ('壤', '壌'),        # 平壤 ⇔ 平壌 (p180 滿鐵平壤炭鑛線 ⇔ 平壌 in the mileage CSV)
    ('樂', '楽'),        # 有樂町 ⇔ 有楽町 (p31)

    # The pairs below align old-form station and line names with new-form spellings (mileage tables, etc.).
    # The coordinate tables (data/knowledge/places/) do not normalize names, so an old-form station name needs its own
    # row in the stop-place table (stop_place.csv). This dictionary aligns spellings in integration, interpolation and route search.
    ('澤', '沢'),        # 小淵澤 ⇔ 小淵沢, 鳥澤 ⇔ 鳥沢, 白澤 ⇔ 白沢 (6 stations)
    ('ケ', 'ヶ'),        # 千駄ケ谷 ⇔ 千駄ヶ谷, 市ケ谷 ⇔ 市ヶ谷, 阿佐ケ谷 ⇔ 阿佐ヶ谷 (4 stations)
    ('豫', '予'),        # 伊豫三島 ⇔ 伊予三島, 伊豫三芳 ⇔ 伊予三芳 (4 stations)
    ('寶', '宝'),        # 寶達 ⇔ 宝達 (2 stations)
    ('曾', '曽'),        # 木曾福島 ⇔ 木曽福島, 木曾川 ⇔ 木曽川 (2 stations)
    ('國', '国'),        # 中國勝山 ⇔ 中国勝山, 國縫 ⇔ 国縫 (2 stations)
    ('萬', '万'),        # 萬字 ⇔ 万字 (2 stations)
    ('龍', '竜'),        # 龍王 ⇔ 竜王
    ('帶', '帯'),        # 帶織 ⇔ 帯織
    ('錢', '銭'),        # 錢函 ⇔ 銭函
    ('劍', '剣'),        # 劍淵 ⇔ 剣淵
    ('來', '来'),        # 早來 ⇔ 早来
    ('淺', '浅'),        # 遠淺 ⇔ 遠浅
    ('蠶', '蚕'),        # 蠶桑 ⇔ 蚕桑
    ('靑', '青'),        # 靑森 ⇔ 青森
    #   青島 on 宮崎鐵道線 and 靑島 on 支那國有鐵道膠濟本線 are on different lines, so their stops stay separate.
    ('瀧', '滝'),        # 瀧尾 ⇔ 滝尾、瀧川 ⇔ 滝川、下瀧 ⇔ 下滝
    ('惠', '恵'),        # 惠比壽 ⇔ 恵比寿
    ('壽', '寿'),        # 惠比壽 ⇔ 恵比寿
    ('澁', '渋'),        # 澁谷 ⇔ 渋谷
    ('條', '条'),        # 十條 ⇔ 十条
    ('藏', '蔵'),        # 武藏境 ⇔ 武蔵境
    ('黑', '黒'),        # 黑磯 ⇔ 黒磯、黑澤尻 ⇔ 黒澤尻、黑松內 ⇔ 黒松内
    #   The original prints 黑 (checked in large type in titles and running heads); the small type of the station
    #   column cannot tell 黑 from 黒, so the dictionary absorbs it.
    ('禮', '礼'),        # 波久禮 ⇔ 波久礼、牟禮 ⇔ 牟礼、禮受 ⇔ 礼受
    ('觀', '観'),        # 觀音寺 ⇔ 観音寺, 觀音 ⇔ 観音
    ('與', '与'),        # 長與 ⇔ 長与, 與野 ⇔ 与野, 與那原 ⇔ 与那原
    ('德', '徳'),        # 德田 ⇔ 徳田, 德島 ⇔ 徳島, 高德 ⇔ 高徳
    ('嚴', '厳'),        # 嚴木 ⇔ 厳木, 嚴原 ⇔ 厳原, 嚴島町 ⇔ 厳島町
    ('嶽', '岳'),        # 駒ヶ嶽 ⇔ 駒ヶ岳, 岸嶽 ⇔ 岸岳, 矢嶽 ⇔ 矢岳
    ('卷', '巻'),        # 花卷 ⇔ 花巻, 石卷 ⇔ 石巻
    ('溫', '温'),        # 粟津溫泉 ⇔ 粟津温泉, 溫泉電軌線 ⇔ 温泉電軌線, 仙南溫泉軌道線, 溫泉鐵道線
    ('邊', '辺'),        # 淵野邊 ⇔ 淵野辺
    ('靜', '静'),        # 靜 ⇔ 静 (水戸鐵道線), 靜岡 ⇔ 静岡
    ('濟', '済'),        # 膠濟本線 ⇔ 膠済, 濟南 ⇔ 済南
    ('稻', '稲'),        # 稻毛 ⇔ 稲毛, 稻荷山 ⇔ 稲荷山
    ('莊', '荘'),        # 羽後本莊 ⇔ 羽後本荘, 橫莊鐡道東線 ⇔ 横荘鐡道東線
]

# One-way special replacements (fixing transcription errors, etc.)
TRANSCRIPTION_FIXES = [
    # placeholder station name -> real station name (p56 福武電氣鐵道線)
    # applied to that page only, not as a global replacement
]

# Other spellings of the same line (not covered by KANJI_PAIRS)
# (alias, canonical): alias is unified to canonical
# Do not add suffix differences between different operators (e.g. 水戸線 vs 水戸鐵道線)
LINE_NAME_ALIASES = [
    ('北陸線', '北陸本線'),    # the official 1925 name is "北陸本線"; the short form also occurs
    # possible future additions (operator to be checked):
    # ('總武線', '總武本線'),  # fixed by hand on p136; could be added as a safety net
]

# One-way dictionary old -> new (for normalize)
_OLD_TO_NEW = {}
for old, new in KANJI_PAIRS:
    if old != new and old not in _OLD_TO_NEW:
        _OLD_TO_NEW[old] = new

# One-way dictionary new -> old (for two-way equivalent checks)
_NEW_TO_OLD = {v: k for k, v in _OLD_TO_NEW.items()}

# Whole-name alternative spellings (variation that variant characters cannot express). normalize() applies them
#   before character replacement. The same physical station is printed differently on different pages. When adding,
#   always check that two different stations on the same line do not end up with the same name.
#   key = alternative printed spelling -> value = representative spelling (the more common one in the transcription).
NAME_ALIASES = {
    '三宮': '三ノ宮',   # 三ノ宮 in Kobe. Only the p1 connection band west of Tokyo prints "三宮" (20 records); p2, p19, p21 print "三ノ宮" (84)
    '上山': '上ノ山',   # 奥羽本線, today's Kaminoyama-Onsen. The printing differs by page:
                       #   p125 (下リ, down) prints "上　山" (2 characters spaced out, blank in the middle);
                       #   p126 (上リ, up) prints "上ノ山" (3 characters). Both transcriptions follow the original.
                       #   NAME_ALIASES needs an exact match, so 上山田, 上三緒, 筑前山田 etc. are not affected.
}


def normalize(name: str, prefer_new: bool = False) -> str:
    """Normalize a station name.

    Args:
        name: station name
        prefer_new: True to unify to new forms (to match CSVs); False keeps old forms (as printed)

    Returns:
        normalized station name
    """
    if not name:
        return name
    result = NAME_ALIASES.get(name, name)
    if prefer_new:
        # all old forms to new forms
        for old, new in KANJI_PAIRS:
            result = result.replace(old, new)
    return result


def equivalent(a: str, b: str) -> bool:
    """Whether two station names are the same station, differing only in variant characters."""
    if a == b:
        return True
    # normalize both to new forms and compare
    return normalize(a, prefer_new=True) == normalize(b, prefer_new=True)


def suggest_replacement(target: str, candidates: list[str]) -> str | None:
    """Return the candidate matching target, allowing old/new form differences.

    Args:
        target: station name to look for
        candidates: list of candidates

    Returns:
        the matching candidate, or None
    """
    for c in candidates:
        if equivalent(target, c):
            return c
    return None


# Example / self test
if __name__ == '__main__':
    tests = [
        ('神戶', '神戸', True),
        ('武藏', '武蔵', True),
        ('豐田', '豊田', True),
        ('東京', '名古屋', False),
        ('臺中', '台中', True),
        ('黒松內', '黒松内', True),
    ]
    print("=== Self test ===")
    for a, b, expected in tests:
        result = equivalent(a, b)
        status = '✓' if result == expected else '✗'
        print(f"  {status} equivalent({a!r}, {b!r}) = {result} (expected {expected})")

    print(f"\n登録ペア数: {len(KANJI_PAIRS)}")
    print(f"旧字 → 新字 マッピング数: {len(_OLD_TO_NEW)}")
