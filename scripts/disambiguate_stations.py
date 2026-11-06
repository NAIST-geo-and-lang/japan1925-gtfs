"""
disambiguate_stations.py

Detect different stations that share a name and add a region tag (conservative approach).

Strategy:
1. A line whose name clearly points overseas, to Hokkaido or to Karafuto is an "external line".
2. A station name that appears on both external lines and inland (Honshu, Shikoku, Kyushu) lines
   is treated as two different stations, and the external side gets a 〈region〉 tag.
3. Same-name stations within the inland area are handled separately:
   - tagged only when each line has a clear region;
   - lines that span several regions (Tokaido, San'yo, ...) are left out.

Input:
  4_integrated/integrated_stop_times.csv
Output:
  4_integrated/integrated_stop_times.csv (tagged)
  4_integrated/disambiguation_report.csv
"""

import csv
import os
import re
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTEGRATED = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'integrated_stop_times.csv')
REPORT = os.path.join(BASE_DIR, 'data', os.environ.get('INTEGRATED_DIR', '4_integrated'), 'disambiguation_report.csv')

# ---------------------------------------------------------------------------
# Line -> external region: only lines lying entirely outside mainland Japan
# ---------------------------------------------------------------------------
# Lines spanning inland regions (Tokaido, San'yo, ...) are not included;
# only lines that stay almost entirely within one region.

EXTERNAL_PATTERNS = [
    # Korea (lines entirely within the Korean peninsula)
    # "湖南" is limited to "湖南本線" because it clashes with 湖南鐵道線 in Shiga.
    # "兼二浦" and "馬山" are in Korea even on a line named 滿鐵...線, so they are matched before Manchuria.
    (re.compile(r'京釜|京義|京元|湖南本線|京仁|咸鏡|平元|圖們|淸津|裡里|咸興|京慶|大邱|金剛|順天|鎮海|長項|麗水|羅津|昌寧|京慶南|朝鮮線|兼二浦|馬山'), '朝鮮'),

    # Manchuria
    (re.compile(r'滿鐵|滿錢|安奉|奉吉|吉長|四洮|四平|敦圖|圖佳|拉濱|平齊|齊昂|京敦|京白|京圖|大鄭|京通|張錦|錦古|藍榆|滿州|満洲|新京|奉天.*線|哈爾.*線|滿洲線'), '滿洲'),

    # China proper
    (re.compile(r'支那|滬寧|滬杭|津浦|京漢|平漢|粵漢|京滬|京浦|京贛|淞滬|滬甬|滬太|蘇嘉|杭甬|寧波|徐淮|海蘭|青島|膠濟|膠州|博山|金浦|龍海|隴海|隴秦|寶天|汴洛|京津|平津|京山|京石|滬奉|湘鄂|湘桂|黔桂|湘黔|滇越|滇緬|滇桂|川滇|敘昆|杭江|蘇皖|江南|蘇鄂'), '支那'),

    # Taiwan
    (re.compile(r'臺灣|臺東|宜蘭|淡水|新店|平溪|集集|阿里山|蘇澳'), '臺灣'),

    # Karafuto (South Sakhalin)
    (re.compile(r'樺太|大泊|豐原'), '樺太'),

    # Russian Maritime Province
    (re.compile(r'鳥蘇里|シベリア|烏蘇里'), '露領'),

    # Hokkaido (lines within the island)
    (re.compile(r'宗谷|石北|根室|釧路|留萌|士幌|池北|渚滑|湧網|名寄|富良野|岩内|歌志内|夕張|幌内|手宮|江差|松前|札沼|千歳|室蘭|胆振|日高|静内|凾館|函館本線|函館・|函館・根室|長輪線|萬字線|上磯線'), '北海道'),

    # Chinese Eastern Railway (東支鐵道; centered on Harbin, crossing Manchuria)
    (re.compile(r'東支鐵道|中東鐵道|東清鐵道'), '滿洲'),
]

# Extra words that place 1925 line names in a region. The table above was built from postwar JNR line names and misses
#   old characters (內, 萠), so this adds Hokkaido private lines and branches (e.g. 留萠線, 定山溪鐵道線) and the
#   滿鐵 lines in Korea (e.g. 滿鐵湖南線). Affects line regions and station name tags.
#   The Korean words are matched before "滿鐵" (Manchuria). Default ON. Previous behavior = REGION_CLASSIFY_1925=0.
REGION_CLASSIFY_1925 = os.environ.get('REGION_CLASSIFY_1925', '1') == '1'
_REGION_FIRST_1925 = [(re.compile(r'平南|平壤|滿鐵湖南'), '朝鮮')]
_REGION_LAST_1925 = [
    (re.compile(r'網走|湧別|留[萠萌]|定山[溪渓]|天[鹽塩]|北海道|十勝|[壽寿]都|京極|苫小牧|岩[內内]|幌[內内]'
                r'|歌志[內内]|雄別|美唄|函館|雨龍|登別|相生線'), '北海道'),
]


# ---------------------------------------------------------------------------
# Same-name stations within one line
# ---------------------------------------------------------------------------
# The GTFS stop key is (stop_name, line_name), so two stations with the same name on the same line
# would merge into one stop. Example: "川口" on 東北本線 was both
#   - in Saitama (between 赤羽 and 蕨; p95, p97)
#   - in Iwate (between 好摩 and 沼宮内; p103)
# about 500 km apart.
#
# (sn, ln) cannot tell them apart, so each row is told apart by marker stations on the same trip
# (coordinates are not attached yet at this step).
#
# Format: (line name, station name) -> [ ({marker stations...}, tag), ... ]
#   A row gets the tag when the stations next to it on its trip intersect the markers.
#   Rows that match no rule stay untagged (the main station).
#
# The rules are currently empty: the Saitama station is printed "川口町" (the name until 1934) and the transcription follows
#   the original, so "川口" on 東北本線 is only the Iwate station. Previous behavior (split 川口 with the 〈岩手〉 tag)
#   = DISAMBIG_SAME_LINE_SPLIT_LEGACY=1. The row-level tagging is kept; new cases use the format of _SAME_LINE_SPLITS_LEGACY.
_SAME_LINE_SPLITS_LEGACY = {
    ('東北本線', '川口'): [
        ({'好摩', '沼宮内', '奥中山', '一戸', '盛岡', '厨川', '瀧澤'}, '岩手'),
    ],
}
SAME_LINE_SPLITS = (_SAME_LINE_SPLITS_LEGACY
                    if os.environ.get('DISAMBIG_SAME_LINE_SPLIT_LEGACY', '0') == '1' else {})

# Tag the island side of a same-name pair to separate it from the mainland station. The island port "宮島"
#   (a call of 大阪商船會社定期航路, i.e. Itsukushima) and the mainland station "宮島" (山陽本線, today's Miyajimaguchi)
#   share a name and are within 5 km; untagged, they would form one station group in the journey planner and one
#   parent station in the published dataset, allowing a 0-minute transfer across the sea.
#   Coordinates come from the 〈嚴島〉 row of the stop-place table (data/knowledge/places/stop_place.csv).
#   The station group key in generate_router_data.py keeps the tags from this table (ISLAND_TAG_NAMES).
#   Format: (station name, line name) -> tag. Default ON. Previous behavior = DISAMBIG_ISLAND_TAG=0.
ISLAND_TAGS = {
    ('宮島', '大阪商船會社定期航路'): '嚴島',
}
ISLAND_TAG_NAMES = {t for t in ISLAND_TAGS.values()}
ISLAND_TAG = os.environ.get('DISAMBIG_ISLAND_TAG', '1') == '1'


def classify_line(line_name):
    """Return the external region of a line name, or None for an inland line."""
    if REGION_CLASSIFY_1925:
        for pat, region in _REGION_FIRST_1925:
            if pat.search(line_name):
                return region
    for pat, region in EXTERNAL_PATTERNS:
        if pat.search(line_name):
            return region
    if REGION_CLASSIFY_1925:
        for pat, region in _REGION_LAST_1925:
            if pat.search(line_name):
                return region
    return None


# Station names treated as external even on inland lines, because no inland station has the same name
# (shared by this script and the warning in apply_agent_knowledge.py)
UNIQUE_FOREIGN = {
    '京城': '朝鮮', '釜山': '朝鮮', '平壤': '朝鮮',
    '永登浦': '朝鮮', '龍山': '朝鮮', '天安': '朝鮮',
    '成歡': '朝鮮', '鳥致院': '朝鮮',
    # 水原 also exists in Niigata (羽越線) -> left to case 1 (external+internal)
    '大田': '朝鮮',  # 大田 also exists on 山陰本線 (Shimane; see DO_NOT_TAG_ON_LINES); external here
    '長春': '滿洲', '哈爾賓': '滿洲', '奉天': '滿洲',
    '安東': '滿洲',  # 滿鐵安奉線 (Dandong)
    '大連': '滿洲',
    '浦鹽斯德': '滿洲',  # Vladivostok (Russian territory; see DISAMBIG_TAG_REGION_FIX)
}

# (sn, ln) pairs that have an inland station of the same name and must not get an external tag
DO_NOT_TAG_ON_LINES = {
    ('大田', '山陰本線'),
    ('水原', '羽越線'),
    # 安東 on 安濃鐵道線 (Mie) is a real inland station; p87 prints ●安東 twice as a junction.
    # Without this entry, '安東': '滿洲' in UNIQUE_FOREIGN would name it 安東〈滿洲〉.
    ('安東', '安濃鐵道線'),
}

# External stations reached from the mainland by ferry
FERRY_FOREIGN = {
    '函館': '北海道', '函館桟橋': '北海道', '凾館棧橋': '北海道',
    '釜山': '朝鮮', '大連': '滿洲', '浦鹽斯德': '滿洲',
}
FERRY_LINE_PATTERNS = [re.compile(r'連絡|汽船|聯絡|連絡船')]

# Align station name tags with the station's location. Default ON. Previous behavior = DISAMBIG_TAG_REGION_FIX=0.
#   (1) A continental station listed in UNIQUE_FOREIGN (a table written by station location) gets that region
#       (previously the most common region among the continental lines with that name, so 安東 on the north bank
#       of the Yalu got 〈朝鮮〉).
#   (2) 浦鹽斯德 (Vladivostok) is Russian territory (露領).
#   (3) The port 青島 (China) is separated from the inland 青島 (宮崎鐵道線), added to the tables like 安東 / 安濃鐵道線.
#   (4) A name on no inland line but on lines of two or more regions (落合 on 根室本線 and 樺太鐵道本線) also gets
#       region tags, only when an island region (Hokkaido, Karafuto, Taiwan, Russian territory) is involved.
#   (5) The same rule applies to stops of frequency-only sections (made by generate_gtfs.add_freq_section_stops),
#       e.g. 停車場前 on 函館水電線, which shares its name with an inland 停車場前.
DISAMBIG_TAG_REGION_FIX = os.environ.get('DISAMBIG_TAG_REGION_FIX', '1') == '1'
_ALWAYS_SEPARATE = {'北海道', '樺太', '臺灣', '露領'}
_CONTINENT_GROUP = {'朝鮮', '滿洲', '支那'}
if DISAMBIG_TAG_REGION_FIX:
    UNIQUE_FOREIGN['浦鹽斯德'] = '露領'
    FERRY_FOREIGN['浦鹽斯德'] = '露領'
    UNIQUE_FOREIGN['青島'] = '支那'          # station on 膠濟本線 and port of call of 大阪商船 and others
    DO_NOT_TAG_ON_LINES.add(('青島', '宮崎鐵道線'))   # 青島 in Miyazaki is an inland station
# 上海 (port of call of 日本郵船 and others) has no inland namesake (regardless of the switch). The port point is more than
# 1 km from the railway station (滬寧線), so they are not aligned as "the same place"; it is tagged by name (上海〈支那〉).
UNIQUE_FOREIGN['上海'] = '支那'


def freq_section_name_lines():
    """(6) Return the set of (station name, line name) for frequency-only section stops that go into GTFS
    (same condition as generate_gtfs.add_freq_section_stops: the section has a headway and at least 2 stations,
    including both ends, with coordinates in the coordinate tables; only the stations with coordinates).
    They are not in the integrated output, so they are counted here as lines on which a name appears
    (this separates the inland 筑紫 stop of a 九州鐵道線 section from 筑紫 on 留萠線)."""
    import build_frequency_sections as bfs
    import agent_knowledge as _ak   # counted with the coordinate tables, as in generate_gtfs
    out = set()
    for b in bfs.build():
        if not b.get('headway_secs'):
            continue
        line = b['line_name']
        names = [x for x in (b.get('stations') or '').split('・') if x]
        have = [nm for nm in names if _ak.lookup(nm, line)]   # no retry without the line name
        if len(have) < 2 or names[0] not in have or names[-1] not in have:
            continue
        out.update((nm, line) for nm in have)
    return out


def freq_section_stop_name(name, line, name_regions):
    """(5) Name of a frequency-only section stop (with a tag when one is added).
    name_regions = {base name: set of regions of the lines where the name appears ('内地' for inland)}."""
    if not DISAMBIG_TAG_REGION_FIX or '〈' in name:
        return name
    region = classify_line(line)
    if region and name_regions.get(name, set()) - {region}:
        return f'{name}〈{region}〉'
    return name


def is_ferry_line(ln):
    return any(p.search(ln) for p in FERRY_LINE_PATTERNS)


# ---------------------------------------------------------------------------
# Check and fix: one station split into a tagged and an untagged name
# ---------------------------------------------------------------------------
# classify_line() judges by the line name string, so private lines with no place hint in the name
# (定山溪鐵道線, 美唄鐵道線, 京極線, ...) and ferries crossing regions (連絡汽船, 稚泊航路) get None (inland).
# Then only one side of the same station gets a tag:
#     白石〈北海道〉(函館本線)  /  白石(定山溪鐵道線)      <- 0.02 km apart
#     函館棧橋〈北海道〉(函館本線) / 函館棧橋(連絡汽船)      <- 0.00 km apart
# Downstream, stop_name is also the key that decides whether stations on different lines are the same station
# (generate_router_data.build_groups groups only exact name matches),
# so a split breaks transfers (one cannot change from the Seikan ferry to 函館本線).
#
# Fix: no hand-written word list (a missed word would bring the problem back). Splits are counted from the data every
#   time, and names are aligned only after the coordinate tables (an input) confirm the same place.
#   - The check (count and print) always runs.
#   - The fix (align the names) is on by default. Previous behavior = DISAMBIG_UNIFY_SPLIT=0.
UNIFY_SPLIT = os.environ.get('DISAMBIG_UNIFY_SPLIT', '1') == '1'   # default ON
UNIFY_DIST_KM = float(os.environ.get('DISAMBIG_UNIFY_DIST_KM', '1.0'))


def _haversine_km(lat1, lon1, lat2, lon2):
    import math
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _kb_lookup(stop_name, line_name):
    """Look up the coordinate tables (data/knowledge/places/, scripts/agent_knowledge.py). None for stations without coordinates.
    The tables are an input of this script, so reading them is not circular."""
    try:
        import agent_knowledge
    except ImportError:
        import sys as _s
        _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            import agent_knowledge
        except ImportError:
            return None
    # Table inconsistencies (ValueError) and queries missing from the stop-place table (UnmappedQuery with
    # AGENT_KNOWN_STRICT=1) are not swallowed
    v = agent_knowledge.lookup(stop_name, line_name)
    return (v[0], v[1]) if v else None


def find_split_stations(final_name_of):
    """final_name_of: {(stop_name, line_name) -> name after tagging}

    List base names that appear both tagged and untagged, and check with the coordinate tables
    whether they are the same place (<= UNIFY_DIST_KM).

    Returns (split, unknown):
      split   = [((sn, ln), name to align to, distance km, the other (sn, ln))]  <- confirmed as the same station
      unknown = [((sn, ln), candidate names, reason)]                            <- no coordinates, cannot decide
    """
    by_base = defaultdict(lambda: {'tagged': [], 'plain': []})
    for (sn, ln), final in final_name_of.items():
        base = final.split('〈')[0]
        by_base[base]['tagged' if '〈' in final else 'plain'].append((sn, ln, final))

    split, unknown = [], []
    for base, g in sorted(by_base.items()):
        if not g['tagged'] or not g['plain']:
            continue
        for sn, ln, _f in sorted(g['plain']):
            if (sn, ln) in DO_NOT_TAG_ON_LINES:
                continue
            here = _kb_lookup(sn, ln)
            if here is None:
                unknown.append(((sn, ln), sorted({f for _, _, f in g['tagged']}), 'KB に自分の座標が無い'))
                continue
            best = None
            for tsn, tln, tfinal in sorted(g['tagged']):
                there = _kb_lookup(tsn, tln)
                if there is None:
                    continue
                d = _haversine_km(here[0], here[1], there[0], there[1])
                if best is None or d < best[0]:
                    best = (d, tfinal, (tsn, tln))
            if best is None:
                unknown.append(((sn, ln), sorted({f for _, _, f in g['tagged']}), 'KB に相手の座標が無い'))
            elif best[0] <= UNIFY_DIST_KM:
                split.append(((sn, ln), best[1], best[0], best[2]))
    return split, unknown


def detect_untagged_foreign(rows):
    """Given rows of stops_master or integrated_stop_times, return external stations (sn, ln)
    that were left untagged.
    Returns: list of (stop_name, line_name, reason)
    """
    issues = []
    for r in rows:
        sn = r.get('stop_name', '')
        ln = r.get('line_name', '')
        if not sn or '〈' in sn:
            continue
        if (sn, ln) in DO_NOT_TAG_ON_LINES:
            continue
        if sn in UNIQUE_FOREIGN:
            issues.append((sn, ln, 'unique_foreign'))
            continue
        if sn in FERRY_FOREIGN and is_ferry_line(ln):
            issues.append((sn, ln, 'ferry_foreign'))
            continue
        # External line: only a hint (the strict decision is left to main());
        # matching an external line pattern is enough here
        region = classify_line(ln)
        if region:
            issues.append((sn, ln, f'external_line:{region}'))
    return issues


def main():
    print('=== disambiguate_stations.py ===')

    # === Step 1: collect each (sn, ln) ===
    sn_lines = defaultdict(list)  # sn → [(ln, region_or_None)]
    seen = set()
    with open(INTEGRATED, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            key = (r['stop_name'], r['line_name'])
            if key in seen:
                continue
            seen.add(key)
            region = classify_line(r['line_name'])
            sn_lines[r['stop_name']].append((r['line_name'], region))
    if DISAMBIG_TAG_REGION_FIX:   # (6) also count frequency-only section stops (generate_gtfs adds them to GTFS)
        for key in sorted(freq_section_name_lines()):
            if key not in seen:
                seen.add(key)
                sn_lines[key[0]].append((key[1], classify_line(key[1])))

    # === Step 2: same name, different stations ===
    # A station on both external and inland lines -> tag the external side
    # A station in several external regions -> see case 2 below
    rename_plan = {}  # (sn, ln) → new_sn
    report_rows = []

    for sn, items in sn_lines.items():
        regions_present = set(r for _, r in items if r)
        has_internal = any(r is None for _, r in items)

        # Case 1: inland + external -> tag the external side
        #
        # Regions:
        #   - Hokkaido, Karafuto and Taiwan are separate islands/regions -> tagged separately
        #   - Korea, Manchuria and China are connected by land and lines mix (滿鐵 also runs in Korea)
        #     -> merged into one (the most frequent region is used)
        if has_internal and regions_present:
            from collections import Counter
            ALWAYS_SEPARATE = {'北海道', '樺太', '臺灣', '露領'}
            CONTINENT_GROUP = {'朝鮮', '滿洲', '支那'}

            # most frequent region within the continental group
            cont_counts = Counter(r for _, r in items if r in CONTINENT_GROUP)
            cont_primary = cont_counts.most_common(1)[0][0] if cont_counts else None

            for ln, region in items:
                if not region:
                    continue
                # avoid double tags on names already tagged (reruns)
                base = sn.split('〈')[0]
                if region in ALWAYS_SEPARATE:
                    new_sn = f'{base}〈{region}〉'
                elif region in CONTINENT_GROUP:
                    if DISAMBIG_TAG_REGION_FIX:   # (1)(2) prefer the table written by station location
                        new_sn = f'{base}〈{UNIQUE_FOREIGN.get(base, cont_primary)}〉'
                    else:
                        new_sn = f'{base}〈{cont_primary}〉'
                else:
                    new_sn = f'{base}〈{region}〉'
                if new_sn == sn:
                    continue  # already has the same tag
                rename_plan[(sn, ln)] = new_sn
                report_rows.append({
                    'original_name': sn,
                    'line_name': ln,
                    'region': region,
                    'reason': 'external+internal',
                    'new_name': new_sn,
                })

        # Case 2: several external regions only -> not tagged
        # Line names and locations disagree (滿鐵 lines also run in Korea, etc.),
        # so this cannot be decided automatically; such stations are checked by location.
        # (4) (DISAMBIG_TAG_REGION_FIX) Groups including an island region (Hokkaido, Karafuto, Taiwan, Russian territory)
        #   have no such disagreement, so each gets its region tag (落合 on 根室本線〈北海道〉 and 樺太鐵道本線〈樺太〉).
        #   Names shared only within the continent are still not tagged.
        elif DISAMBIG_TAG_REGION_FIX and not has_internal and len(regions_present) >= 2 \
                and regions_present & _ALWAYS_SEPARATE:
            from collections import Counter
            cont_counts = Counter(r for _, r in items if r in _CONTINENT_GROUP)
            cont_primary = cont_counts.most_common(1)[0][0] if cont_counts else None
            base = sn.split('〈')[0]
            for ln, region in items:
                tag_region = UNIQUE_FOREIGN.get(base, cont_primary) if region in _CONTINENT_GROUP else region
                new_sn = f'{base}〈{tag_region}〉'
                if new_sn == sn:
                    continue
                rename_plan[(sn, ln)] = new_sn
                report_rows.append({
                    'original_name': sn,
                    'line_name': ln,
                    'region': region,
                    'reason': 'external+external(island)',
                    'new_name': new_sn,
                })

    print(f'初回タグ: {len(rename_plan)} (sn, ln) ペア')

    rows_in = []
    with open(INTEGRATED, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        for r in reader:
            rows_in.append(r)

    # === Step 2: names that exist only outside the inland area are external even on inland lines ===
    # UNIQUE_FOREIGN / DO_NOT_TAG_ON_LINES are defined at module level
    base_to_tagged_name = {}
    for new_name in set(rename_plan.values()):
        base = new_name.split('〈')[0]
        base_to_tagged_name.setdefault(base, set()).add(new_name)

    additional_count = 0
    for r in rows_in:
        sn = r['stop_name']
        ln = r['line_name']
        if '〈' in sn:
            continue
        if (sn, ln) in rename_plan:
            continue
        if (sn, ln) in DO_NOT_TAG_ON_LINES:
            continue
        if sn in UNIQUE_FOREIGN:
            region = UNIQUE_FOREIGN[sn]
            target = f'{sn}〈{region}〉'
            rename_plan[(sn, ln)] = target
            additional_count += 1
            report_rows.append({
                'original_name': sn,
                'line_name': ln,
                'region': region,
                'reason': 'unique_foreign_name',
                'new_name': target,
            })

    # === Step 3: external stations reached from the mainland by ferry ===
    # FERRY_FOREIGN / FERRY_LINE_PATTERNS / is_ferry_line are defined at module level
    for r in rows_in:
        sn = r['stop_name']
        ln = r['line_name']
        if '〈' in sn or (sn, ln) in rename_plan:
            continue
        if sn in FERRY_FOREIGN and is_ferry_line(ln):
            region = FERRY_FOREIGN[sn]
            target = f'{sn}〈{region}〉'
            rename_plan[(sn, ln)] = target
            additional_count += 1
            report_rows.append({
                'original_name': sn,
                'line_name': ln,
                'region': region,
                'reason': 'ferry_line',
                'new_name': target,
            })

    # === Step 3.4: is one station split into a tagged and an untagged name? ===
    # The check always runs (so a missing word does not pass silently). The fix runs only with DISAMBIG_UNIFY_SPLIT=1.
    final_name_of = {}
    for r in rows_in:
        key = (r['stop_name'], r['line_name'])
        if '〈' in r['stop_name']:
            final_name_of.setdefault(key, r['stop_name'])
        else:
            final_name_of.setdefault(key, rename_plan.get(key, r['stop_name']))
    split, unknown = find_split_stations(final_name_of)
    if split or unknown:
        print(f'[タグの割れ] 同じ駅がタグ有り/無しに割れている: {len(split)} 組'
              f'（座標が引けず判定不能 {len(unknown)} 組）')
        for (sn, ln), target, d, other in split:
            print(f'   {"揃える" if UNIFY_SPLIT else "★要是正"}: {sn} ({ln}) → {target}'
                  f'  [{d:.2f}km / {other[1]}]')
        for (sn, ln), cands, why in unknown:
            print(f'   ?      : {sn} ({ln}) 候補 {cands}  ← {why}')
    unified_count = 0
    if UNIFY_SPLIT:
        for (sn, ln), target, d, other in split:
            rename_plan[(sn, ln)] = target
            unified_count += 1
            report_rows.append({
                'original_name': sn,
                'line_name': ln,
                'region': target.split('〈')[-1].rstrip('〉'),
                'reason': f'unify_split_station({d:.2f}km<-{other[1]})',
                'new_name': target,
            })
        print(f'[タグの割れ] 揃えた: {unified_count} (sn, ln) ペア')
    else:
        print('[タグの割れ] 是正は OFF（DISAMBIG_UNIFY_SPLIT=0 が指定されている。既定は ON）')

    # === Step 3.5: same-name stations within one line ===
    # (sn, ln) cannot separate them, so names are changed row by row.
    # The test is not "does the trip have a marker station" but the stations just before and after this stop:
    #   a through train (上野 -> 青森) has both 川口 on the same trip, so a trip-wide test would tag both.
    by_trip = defaultdict(list)
    for r in rows_in:
        by_trip[r['gtfs_trip_key']].append(r)
    around_of = {}
    for rs in by_trip.values():
        rs.sort(key=lambda x: int(x['stop_sequence']))
        for i, r in enumerate(rs):
            a = set()
            if i > 0:
                a.add(rs[i - 1]['stop_name'].split('〈')[0])
            if i + 1 < len(rs):
                a.add(rs[i + 1]['stop_name'].split('〈')[0])
            around_of[id(r)] = a
    same_line_count = 0
    for r in rows_in:
        base = r['stop_name'].split('〈')[0]
        rules = SAME_LINE_SPLITS.get((r['line_name'], base))
        if not rules or '〈' in r['stop_name']:
            continue
        stset = around_of.get(id(r), set())
        for markers, tag in rules:
            if stset & markers:
                r['stop_name'] = f'{base}〈{tag}〉'
                same_line_count += 1
                report_rows.append({
                    'original_name': base, 'line_name': r['line_name'],
                    'region': tag, 'reason': 'same_line_duplicate',
                    'new_name': r['stop_name'],
                })
                break
    print(f'同一線名の同名異駅タグ: {same_line_count} レコード')

    # === Step 3.6: tag the island side of same-name stations (DISAMBIG_ISLAND_TAG, default ON) ===
    if ISLAND_TAG:
        present = {(r['stop_name'], r['line_name']) for r in rows_in}
        island_count = 0
        for (sn, ln), tag in sorted(ISLAND_TAGS.items()):
            if (sn, ln) not in present or (sn, ln) in rename_plan:
                continue
            rename_plan[(sn, ln)] = f'{sn}〈{tag}〉'
            island_count += 1
            report_rows.append({
                'original_name': sn, 'line_name': ln, 'region': tag,
                'reason': 'island_same_name', 'new_name': f'{sn}〈{tag}〉',
            })
        print(f'島の側の同名駅タグ: {island_count} (sn, ln) ペア')

    # Listing "same-name stations whose neighbors never overlap" automatically is not used (express trains skip stations,
    #   so neighbors change even at one station; too many false positives). Coordinates are more reliable for this.

    print(f'追加タグ(unique_foreign + ferry): {additional_count}')
    print(f'最終タグ: {len(rename_plan)} (sn, ln) ペア')
    print(f'ユニーク new_name: {len(set(rename_plan.values()))}')

    n_renamed = 0
    for r in rows_in:
        key = (r['stop_name'], r['line_name'])
        if key in rename_plan:
            r['stop_name'] = rename_plan[key]
            n_renamed += 1
    print(f'リネーム済みレコード: {n_renamed}')

    with open(INTEGRATED, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_in)
    print(f'更新: {INTEGRATED}')

    # === Step 4: report ===
    report_rows.sort(key=lambda x: (x['original_name'], x['line_name']))
    with open(REPORT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['original_name', 'line_name', 'region',
                                            'reason', 'new_name'])
        w.writeheader()
        w.writerows(report_rows)
    print(f'レポート: {REPORT}')


if __name__ == '__main__':
    main()
