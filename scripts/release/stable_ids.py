"""
Keep published GTFS IDs stable across versions.

Internal IDs (S…, G…, R…, T…) are reassigned in name/key order on every build, so fixing one station name shifts
every later ID. The published dataset instead looks IDs up in an ID registry.

  Registry: data/knowledge/public_release/id_registry/registry.csv (in git; UTF-8 with BOM, CRLF)
    columns: kind, key, public_id, lat, lon, line, first_seen, last_seen, note
    kind: stop (station = station name|line name) / station (parent station = key of its representative stop) /
          route / trip
  Published IDs: stop ST00001, parent station PS00001, route RT0001, trip TR00001 (prefixes differ from internal IDs)
  Shape IDs: SH_<published route ID>

How IDs are assigned:
  1. If the key is in the registry, use its ID.
  2. For a stop key not in the registry, check for a rename: if it pairs one-to-one with a registry stop missing
     this time, on the same line and within RENAME_KM, treat it as a rename and keep the ID (pairs listed in
     renames.csv take precedence).
  2b. (With RELEASE_ID_PARENT_INHERIT=1) for a parent-station key not in the registry, go through its child stops
     from the smallest (oldest) ID and take over the ID of the parent each belonged to in the previous version
     (parent_station_children.csv) if it is unused this time (keeps IDs when grouping changes).
  3. Anything left gets new IDs after the registry's largest, in key order (IDs of removed items are never reused).
  The registry is rewritten only with RELEASE_WRITE_ID_REGISTRY=1 (default: read-only; new IDs go to the report).
  Report: data/knowledge/public_release/id_registry/id_report.csv
"""
import csv
import math
import os
import re
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REG_DIR = os.environ.get('RELEASE_ID_REGISTRY_DIR') or os.path.join(BASE_DIR, 'data', 'knowledge', 'public_release', 'id_registry')   # another location only for trials
REGISTRY = os.path.join(REG_DIR, 'registry.csv')
RENAMES = os.path.join(REG_DIR, 'renames.csv')
REPORT = os.path.join(REG_DIR, 'id_report.csv')
MAP_OUT = os.path.join(REG_DIR, 'internal_id_map.csv')   # written on every build; not part of the published dataset
RENAME_KM = float(os.environ.get('RELEASE_ID_RENAME_KM', '1.0'))
# Keep parent-station IDs. A parent-station key is the key of the group's representative stop, so when grouping
#   changes (the representative disappears) the key changes and would get a new ID. When ON, for a parent key not
#   in the registry, go through its child stops from the smallest (oldest) ST… ID and take over the ID of the
#   parent each belonged to in the previous version, if unused (previous parent-child map = PARENT_CHILDREN).
#   build_release_gtfs.py sets it from RELEASE_ID_PARENT_INHERIT (on by default; 0 = previous behavior, new IDs).
#   Initial value False = previous behavior (when this module is used alone).
PARENT_INHERIT = False
# When writing the registry, a parent-station takeover replaces the old key's row like a rename does (first_seen
#   is kept; note gets "引き継ぎ＝元の鍵 <old key>"), and writing stops if one published ID appears on two rows. No effect
#   when the registry is not written (default). On by default. Previous behavior (replace rename rows only) =
#   RELEASE_ID_REGISTRY_INHERIT_REPLACE=0.
INHERIT_REPLACE = os.environ.get('RELEASE_ID_REGISTRY_INHERIT_REPLACE', '1') == '1'
PARENT_CHILDREN = os.path.join(REG_DIR, 'parent_station_children.csv')
PC_FIELDS = ['stop_id', 'parent_station', 'stop_key', 'parent_key', 'source', 'seen']
FIELDS = ['kind', 'key', 'public_id', 'lat', 'lon', 'line', 'first_seen', 'last_seen', 'note']
PREFIX = {'stop': ('ST', 5), 'station': ('PS', 5), 'route': ('RT', 4), 'trip': ('TR', 5)}


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _km(a, b):
    if not (a[0] and a[1] and b[0] and b[1]):
        return float('inf')
    la1, lo1, la2, lo2 = map(float, (a[0], a[1], b[0], b[1]))
    return 6371.0 * math.radians(1) * math.hypot(la1 - la2, (lo1 - lo2) * math.cos(math.radians(la1)))


def assign(items, today=None):
    """items = {kind: {key: {'lat','lon','line'}}} (lat/lon/line are used for stops only).
    Return ({kind: {key: public_id}}, report rows)."""
    today = today or date.today().isoformat()
    reg = _read(REGISTRY)
    by_kind = {k: {} for k in PREFIX}
    for r in reg:
        by_kind.setdefault(r['kind'], {})[r['key']] = r
    renames = {(r['kind'], r['old_key']): r['new_key'] for r in _read(RENAMES)}
    out, report = {}, []
    for kind, keys in items.items():
        pre, width = PREFIX[kind]
        known = by_kind.get(kind, {})
        got = {}
        for k in keys:
            if k in known:
                got[k] = known[k]['public_id']
        # rename = a registry key missing this time -> a key present this time but not in the registry
        gone = {k: v for k, v in known.items() if k not in keys}
        new = [k for k in keys if k not in got]
        for (kd, old), nk in renames.items():
            if kd == kind and old in gone and nk in new:
                got[nk] = gone.pop(old)['public_id']
                new.remove(nk)
                report.append({'kind': kind, 'key': nk, 'public_id': got[nk], '判定': '改名（改名表）', '元の鍵': old})
        if kind == 'stop':
            cand = {}
            for nk in new:
                line = keys[nk].get('line', '')
                hits = [ok for ok, ov in gone.items() if ov.get('line') == line and
                        _km((keys[nk].get('lat'), keys[nk].get('lon')), (ov.get('lat'), ov.get('lon'))) <= RENAME_KM]
                if len(hits) == 1:
                    cand[nk] = hits[0]
            used = {}
            for nk, ok in cand.items():
                used.setdefault(ok, []).append(nk)
            for ok, nks in sorted(used.items()):
                if len(nks) == 1:
                    nk = nks[0]
                    got[nk] = gone.pop(ok)['public_id']
                    new.remove(nk)
                    report.append({'kind': kind, 'key': nk, 'public_id': got[nk], '判定': '改名（同じ線・座標が近い）', '元の鍵': ok})
        if kind == 'station' and PARENT_INHERIT and new:
            # take over the previous parent ID of a child stop (oldest child first; if two parents want the same ID,
            # the one with the older child wins)
            prev = {}
            for r in _read(PARENT_CHILDREN):
                prev.setdefault(r['stop_id'], r['parent_station'])
            stop_pid = out.get('stop', {})
            gone_pid = {v['public_id']: k for k, v in gone.items()}

            def stnum(m):
                return int(re.sub(r'\D', '', stop_pid.get(m, '')) or 10 ** 9)
            order = sorted(new, key=lambda nk: (min((stnum(m) for m in keys[nk].get('members', [])), default=10 ** 9), nk))
            for nk in order:
                for m in sorted(keys[nk].get('members', []), key=lambda m: (stnum(m), m)):
                    pid = prev.get(stop_pid.get(m, ''))
                    if pid and pid in gone_pid:
                        ok = gone_pid.pop(pid)
                        got[nk] = gone.pop(ok)['public_id']
                        new.remove(nk)
                        report.append({'kind': kind, 'key': nk, 'public_id': got[nk],
                                       '判定': f'引き継ぎ（子の驛 {stop_pid.get(m, "")} {m} の前の親の驛）', '元の鍵': ok})
                        break
        nums = [int(re.sub(r'\D', '', v['public_id']) or 0) for v in known.values()]
        nxt = max(nums, default=0) + 1
        for nk in sorted(new):
            got[nk] = f'{pre}{nxt:0{width}d}'
            nxt += 1
            report.append({'kind': kind, 'key': nk, 'public_id': got[nk], '判定': '新しい番号', '元の鍵': ''})
        for ok in sorted(gone):
            report.append({'kind': kind, 'key': ok, 'public_id': gone[ok]['public_id'], '判定': '今回は無い（番号は使い回さない）', '元の鍵': ''})
        out[kind] = got
    # update the registry (only with RELEASE_WRITE_ID_REGISTRY=1)
    if os.environ.get('RELEASE_WRITE_ID_REGISTRY', '0') == '1':
        rows = {(r['kind'], r['key']): r for r in reg}
        moved = ('改名', '引き継ぎ') if INHERIT_REPLACE else ('改名',)
        renamed_from = {(r['kind'], r['key']): r['元の鍵'] for r in report if r['判定'].startswith(moved)}
        how = {(r['kind'], r['key']): ('引き継ぎ' if r['判定'].startswith('引き継ぎ') else '改名')
               for r in report if r['判定'].startswith(moved)}
        for kind, got in out.items():
            for k, pid in got.items():
                meta = items[kind][k]
                old = rows.get((kind, k)) or rows.pop((kind, renamed_from.get((kind, k), '')), None)
                note = (old or {}).get('note', '')
                if (kind, k) in renamed_from:
                    note = (note + '／' if note else '') + f'{today} {how[(kind, k)]}＝元の鍵 {renamed_from[(kind, k)]}'
                rows[(kind, k)] = {'kind': kind, 'key': k, 'public_id': pid,
                                   'lat': meta.get('lat', '') if kind == 'stop' else '',
                                   'lon': meta.get('lon', '') if kind == 'stop' else '',
                                   'line': meta.get('line', '') if kind == 'stop' else '',
                                   'first_seen': (old or {}).get('first_seen') or today, 'last_seen': today, 'note': note}
        if INHERIT_REPLACE:
            seen_pid = {}
            for r in rows.values():
                seen_pid.setdefault(r['public_id'], []).append(r['key'])
            dup = {p: ks for p, ks in seen_pid.items() if len(ks) > 1}
            if dup:
                p, ks = sorted(dup.items())[0]
                raise SystemExit(f'番号台帳を書く前に止めた：同じ公開番号が 2 行以上 {len(dup)} 組（例 {p}＝{" ／ ".join(ks)}）')
        os.makedirs(REG_DIR, exist_ok=True)
        with open(REGISTRY, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\r\n')
            w.writeheader()
            order = {k: i for i, k in enumerate(PREFIX)}
            for r in sorted(rows.values(), key=lambda r: (order.get(r['kind'], 9), r['public_id'])):
                w.writerow({k: r.get(k, '') for k in FIELDS})
        if PARENT_INHERIT:
            # save this version's parent-child map over the previous one (rows of stops missing this time are kept,
            # so they can be found if the stop comes back)
            pc = {r['stop_id']: r for r in _read(PARENT_CHILDREN)}
            for pk, meta in items.get('station', {}).items():
                ps = out.get('station', {}).get(pk)
                for m in meta.get('members', []):
                    st = out.get('stop', {}).get(m)
                    if ps and st:
                        pc[st] = {'stop_id': st, 'parent_station': ps, 'stop_key': m, 'parent_key': pk,
                                  'source': '公開版づくり（台帳を書いたとき）', 'seen': today}
            with open(PARENT_CHILDREN, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, fieldnames=PC_FIELDS, lineterminator='\r\n')
                w.writeheader()
                w.writerows(sorted(pc.values(), key=lambda r: r['stop_id']))
    os.makedirs(REG_DIR, exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['kind', 'key', 'public_id', '判定', '元の鍵'], lineterminator='\r\n')
        w.writeheader()
        w.writerows(report)
    return out, report
