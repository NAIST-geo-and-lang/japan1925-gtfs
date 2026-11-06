#!/usr/bin/env node
/**
 * route_planner_batch.js — run many searches with the journey planner of demo/route_planner and write the results as JSON
 *   (called by compare_route_planner.py; rarely used on its own)
 *
 * The search is not reimplemented. Like scripts/route_planner_probe.js, it extracts the search functions from the HTML
 *   and runs them. To use the same extraction markers, it loads the probe source and borrows buildEnv
 *   (the probe is not changed; only its trailing `process.exit(main());` is removed before evaluation).
 *
 * Input (JSON on stdin): {"html": "...", "data": "...", "out": "path of the result JSON", "variants": false,
 *                        "queries": [{"from": "大阪", "to": "京城〈朝鮮〉", "dep": "09:00"}, ...]}
 * Output (JSON at out), one record per search:
 *   {from, to, dep, from_gids, to_gids, found, dep_min, arr_min, dur_min_screen, transfers, legs, ms}
 *   dep_min and arr_min are minutes since 0:00 of the search day (plus 1440 for the next day), recomputed by replaying
 *   the returned itinerary leg by leg (a boarding time before the current time, or an alighting time before the boarding
 *   time, moves to the next day; the same counting as the embedded search core).
 *   When a leg has dayShift (PREV_DAY_BOARDING of the journey planner), the shifted time is used as is
 *   (a trip from the previous day is one day earlier).
 *   dur_min_screen is the travel time shown on the page (from end to end of buildAnimFrames).
 *
 * With "variants": true, each search also reports four alternative arrivals (arr_min) in variants (for diagnosing mismatches):
 *   noprune = without candidate pruning (at each station, only the earliest trip per line, direction and terminus)
 *   tr20 = transfer limit (MAX_TRANSFERS) raised to 20 / both = both changes
 *   prevday = also boards today's run of trips that left the previous day (PREV_DAY_BOARDING + PARETO_CONTINUATION,
 *     the same two flags as data built with ROUTER_PREV_DAY_BOARDING=1; identical to the base if the data has the flags)
 *   Built from the search core embedded in the HTML (between the ROUTER_CORE markers) by replacing the pruning line in
 *   memory (the HTML is not changed). If that line is not found, variants is {error}
 *   (if the search core changes, update NEEDLE below).
 */
'use strict';
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..', '..');
const PROBE = path.join(REPO, 'scripts', 'route_planner_probe.js');
const CORE_BEGIN = '// <<<ROUTER_CORE>>>';
const CORE_END = '// <<<END ROUTER_CORE>>>';
const NEEDLE = "const endKey = lineKey + '__' + stops[stops.length - 1] + (trip.est ? '__est' : '');";

function loadProbe() {
  let src = fs.readFileSync(PROBE, 'utf8').replace(/^#!.*\n/, '');
  const tail = 'process.exit(main());';
  const i = src.lastIndexOf(tail);
  if (i < 0) throw new Error(`${PROBE} の末尾に「${tail}」がありません（probe の形が変わったら、ここも合わせる）`);
  src = src.slice(0, i) + src.slice(i + tail.length);
  const fn = new Function('require', '__dirname', '__filename', src + '\nreturn { buildEnv };');
  return fn(require, path.dirname(PROBE), PROBE);
}

function loadVariants(htmlPath, DATA) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const b = html.indexOf(CORE_BEGIN), e = html.lastIndexOf(CORE_END);
  if (b < 0 || e < b) return { error: 'HTML に検索の中身の目印が見つからない' };
  const core = html.slice(html.indexOf('\n', b) + 1, e);
  if (core.split(NEEDLE).length !== 2) {
    return { error: '候補の絞り込みの行が見つからない（画面の検索が変わったら route_planner_batch.js の NEEDLE も合わせる）' };
  }
  const load = s => { const m = { exports: {} }; new Function('module', 'exports', s)(m, m.exports); return m.exports; };
  const Base = load(core), NoPrune = load(core.replace(NEEDLE, 'const endKey = String(tripIdx);'));
  return {
    routers: {
      noprune: NoPrune.createRouter(DATA),
      tr20: Base.createRouter(DATA, { MAX_TRANSFERS: 20 }),
      both: NoPrune.createRouter(DATA, { MAX_TRANSFERS: 20 }),
      // the same two flags as data built with ROUTER_PREV_DAY_BOARDING=1 (previous-day boarding alone loses paths that continue on the same train)
      prevday: Base.createRouter(DATA, { PREV_DAY_BOARDING: true, PARETO_CONTINUATION: true }),
    },
  };
}

// Replay the returned itinerary leg by leg and compute boarding and alighting times (minutes since 0:00 of the search day)
function replay(DATA, toMin, p, depMin) {
  let cur = depMin;
  const legs = p.map(l => {
    if (l.walk) {   // walking leg: no trip; advance the clock by the walking time
      const ed = cur, at = cur + l.walkMin;
      cur = at;
      return { l, t: null, ed, at, bd: ed };
    }
    const t = DATA.trips[l.tripIdx];
    const bd = toMin(t.dep[l.boardIdx]) ?? toMin(t.arr[l.boardIdx]);
    let ed;
    if (l.dayShift !== undefined) {
      ed = bd + l.dayShift;          // PREV_DAY_BOARDING: day shift set by the search (negative for a previous-day trip)
    } else {
      ed = bd;
      while (ed < cur) ed += 1440;
    }
    const am = toMin(t.arr[l.alightIdx]) ?? toMin(t.dep[l.alightIdx]);
    let at = (am != null) ? am + (ed - bd) : ed;
    while (at < ed) at += 1440;
    cur = at;
    return { l, t, ed, at, bd };
  });
  return { legs, arr: cur };
}

function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const { DATA, R } = loadProbe().buildEnv(input.html, input.data);
  const variants = input.variants ? loadVariants(input.html, DATA) : null;
  const out = [];
  for (const q of input.queries) {
    const rec = { from: q.from, to: q.to, dep: q.dep };
    const fg = R.resolveGroupIds(q.from), tg = R.resolveGroupIds(q.to);
    rec.from_gids = fg || null;
    rec.to_gids = tg || null;
    const depMin = R.toMin(q.dep);
    if (!fg || !tg || depMin == null) { rec.error = '駅名か時刻が読めない'; out.push(rec); continue; }
    const t0 = Date.now();
    const p = R.findRoute(fg, tg, depMin, {});
    rec.ms = Date.now() - t0;
    rec.found = !!p;
    if (p) {
      const rp = replay(DATA, R.toMin, p, depMin);
      rec.legs = rp.legs.map(({ l, t, ed, at, bd }) => (l.walk ? {
        key: '', line: '徒歩', num: String(l.walkMin), dir: '', est: false, walk: true,
        from: DATA.groups[l.boardStation].name, to: DATA.groups[l.alightStation].name,
        from_gid: l.boardStation, to_gid: l.alightStation, dep_min: ed, arr_min: at, day_shift: 0,
      } : {
        key: t.k, line: t.l, num: t.n, dir: t.d, est: !!t.est,
        from: R.stopName(DATA, t, l.boardIdx), to: R.stopName(DATA, t, l.alightIdx),
        from_gid: l.boardStation, to_gid: l.alightStation, dep_min: ed, arr_min: at,
        day_shift: (ed - bd) / 1440,   // days after the data's day of the boarded trip (0 = as written, negative = previous day)
      }));
      rec.dep_min = rec.legs[0].dep_min;
      rec.arr_min = rp.arr;
      rec.transfers = R.getRouter().countTransfers(p);
      const frames = R.buildAnimFrames(p, depMin);
      rec.dur_min_screen = frames[frames.length - 1][0] - frames[0][0];
    }
    if (variants) {
      if (variants.error) {
        rec.variants = { error: variants.error };
      } else {
        rec.variants = {};
        for (const [name, router] of Object.entries(variants.routers)) {
          const vp = router.findRoute(fg, tg, depMin, {});
          rec.variants[name] = vp ? replay(DATA, R.toMin, vp, depMin).arr : null;
        }
      }
    }
    out.push(rec);
  }
  fs.writeFileSync(input.out, JSON.stringify(out));
}

main();
