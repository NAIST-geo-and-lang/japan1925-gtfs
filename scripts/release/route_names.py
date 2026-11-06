#!/usr/bin/env python3
"""route_names.py — Give routes of frequency-only sections (RQ…) a section name (route_long_name) in the published
dataset, so they can be told apart from routes with the same name.

Called from scripts/build_release_gtfs.py (not run on its own). Writes nothing outside the published dataset.

Targets: frequency-only routes whose route_short_name is shared with another route (without a section name the
  validator reports duplicate_route_name).
Section name, written "○○・○○間" (between A and B) as for timetable routes:
  1. If all sections of the route share one heading (the leading "○○・○○間" of line_name_raw in frequency_only.csv,
     i.e. the heading of the printed table), use it.
  2. Otherwise build "○○・○○間" from each section's ends (origin/destination in frequency_sections.csv) and join them
     with "、" in section order.
Routes that already have a route_long_name are left as they are.
"""
import re
from collections import Counter, defaultdict

HEADING = re.compile(r'^([^（(]+?間)[（(]')


def freq_route_long_names(routes, sections, freq_only):
    """routes: rows of routes.txt; sections: rows of frequency_sections.csv; freq_only: rows of frequency_only.csv.
    Return {route_id: section name} for the routes that get one."""
    n_name = Counter(r['route_short_name'] for r in routes)
    heading = {}
    for r in freq_only:
        m = HEADING.match(r.get('line_name_raw', ''))
        if m:
            heading[r['id']] = m.group(1)
    by_line = defaultdict(list)
    for s in sections:
        by_line[s['line_name']].append(s)
    out = {}
    for r in routes:
        if not r['route_id'].startswith('RQ') or n_name[r['route_short_name']] < 2 or r.get('route_long_name'):
            continue
        secs = by_line.get(r['route_short_name'], [])
        if not secs:
            continue
        heads = {heading.get(s['section_id']) for s in secs}
        if len(heads) == 1 and None not in heads:
            out[r['route_id']] = heads.pop()
            continue
        parts, seen = [], set()
        for s in sorted(secs, key=lambda s: s['section_id']):      # within a section, keep table order (down, then up)
            pair = frozenset((s['origin'], s['destination']))
            if pair in seen:
                continue
            seen.add(pair)
            parts.append(f"{s['origin']}・{s['destination']}間")
        out[r['route_id']] = '、'.join(parts)
    return out
