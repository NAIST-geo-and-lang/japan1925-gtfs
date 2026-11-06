#!/usr/bin/env node
/**
 * check_route_itineraries.js — are returned itineraries valid, and do the times on the page match? (RQ1, RQ2)
 *
 * The search logic is not reimplemented: `buildEnv` of `scripts/route_planner_probe.js` runs the search functions
 *   embedded in the HTML (what the page runs) as is. The page side (`buildAnimFrames`, the candidate list and the
 *   trip panel) is also extracted from the HTML and run, so the check follows any change to the implementation.
 *
 * RQ1 is the itinerary itself valid (applied to `findRoute` and to every candidate of `findMultipleRoutes`)
 *   1. legs connect: the station (group) alighted at equals the station boarded next
 *   2. boarding index < alighting index (no going back within a trip); both ends match the trip's stops
 *   3. boarding and alighting only at timed stops (never at a stop with neither dep nor arr)
 *   4. starts at the query origin, ends at the destination, departs no earlier than the query time
 *   5. order of times: next boarding >= previous alighting (after adding dayShift)
 *   Also checks for duplicate candidates (exactly the same legs).
 *   Any case is a FAIL (the first thing to break when the search is changed).
 *
 * RQ2 do the times on the page match a replay of the itinerary
 *   Reference: times from replaying the itinerary leg by leg (`replay`), except that when it starts with a walk,
 *   the walk ends at the departure of the first trip (the page's rule: no hours of waiting at the origin).
 *   (a) `buildAnimFrames` of `demo/route_planner` (map animation and travel time):
 *       number of points equals number of stops, times at leg boundaries match, times never go backwards.
 *   (c) the candidate list (runSearch / selectCandidate): each card's times, travel time and transfers match the
 *       itinerary shown when the card is clicked.
 *   (d) the trip panel (renderTripPanel): transfer waits and "same train" marks follow countTransfers.
 *   Legs carry `dayShift` (negative for a previous-day trip); if it is mishandled the search is right but the page
 *   shows wrong times. Any mismatch is a FAIL.
 *
 * Three more measures from the same searches (none of them FAIL; numbers to compare with the previous run)
 *   RQ5 transfer slack: alighting time to next boarding (continuing on the same through train, same `p`, excluded).
 *       A 0-minute transfer between different station names (merged by `ROUTER_GROUP_NEAR`) is clearly wrong since
 *       walking takes time. Merging stops at 50 m (farther pairs are joined by walking links), so normally 0 cases.
 *       0 minutes between the same station name follows the printed timetable (arrival and departure printed in the
 *       same minute).
 *   RQ6 detours and waits: distance ridden / straight-line origin-destination distance (only for 20 km or more),
 *       and waits of 10 hours or more.
 *   RQ7 reliance on estimated trips: share of itineraries using at least one `est` trip (expanded from `frequencies.txt`).
 *       The share in the printed timetable is counted on the GTFS before expansion: the journey planner data expands
 *       each frequency box ("此間○分毎") into one trip per headway, so counting expanded trips greatly overstates it.
 *   RQ6 and RQ7 count candidate 1 only (the top of the page, the route users actually see).
 *     RQ5 uses all candidates (more connections make 0-minute cases easier to find).
 *
 * Usage:
 *   node tests/route_search/check_route_itineraries.js                  # default: data/gtfs_v1_release_router/router_data.js
 *   node tests/route_search/check_route_itineraries.js --data <router_data.js|json>
 *   node tests/route_search/check_route_itineraries.js --sample 300 --seed 3
 *   node tests/route_search/check_route_itineraries.js --routes 3       # candidates per query (3, as on the page)
 *
 * Queries: all rows of the expectations table (tests/route_search/expectations.csv) + N random queries (fixed seed)
 *   + a few queries that produce walking legs (between the two ends of walking links), where the page breaks most easily.
 * Exit code: 1 if there is a FAIL
 */
'use strict';
const fs = require('fs');
const path = require('path');

const BASE = path.dirname(path.dirname(__dirname));
const PROBE = path.join(BASE, 'scripts', 'route_planner_probe.js');
const TABLE = path.join(BASE, 'tests', 'route_search', 'expectations.csv');
const MAX_SHOW = 15;
const OD_MIN_KM = 20.0;      // RQ6: minimum straight-line origin-destination distance for detour ratios
const LONG_WAIT_MIN = 600;   // RQ6: "long wait" = 10 hours

function parseArgs(argv) {
  const o = {
    data: path.join(BASE, 'data', 'gtfs_v1_release_router', 'router_data.js'),
    html: path.join(BASE, 'demo', 'route_planner', 'index.html'),
    sample: 120, walkSample: 30, seed: 7, routes: 3, minTrips: 10, screenSample: 40,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--data') o.data = argv[++i];
    else if (a === '--html') o.html = argv[++i];
    else if (a === '--sample') o.sample = parseInt(argv[++i], 10);
    else if (a === '--walk-sample') o.walkSample = parseInt(argv[++i], 10);
    else if (a === '--seed') o.seed = parseInt(argv[++i], 10);
    else if (a === '--routes') o.routes = parseInt(argv[++i], 10);
    else if (a === '--screen-sample') o.screenSample = parseInt(argv[++i], 10);
    else throw new Error('知らない引数: ' + a);
  }
  return o;
}

/** Borrow buildEnv from the probe (evaluated with only its trailing `process.exit(main());` removed). */
function loadProbe() {
  let src = fs.readFileSync(PROBE, 'utf8').replace(/^#!.*\n/, '');
  const tail = 'process.exit(main());';
  const i = src.lastIndexOf(tail);
  if (i < 0) throw new Error(PROBE + ' の末尾に「' + tail + '」がありません（probe の形が変わったら、ここも合わせる）');
  src = src.slice(0, i) + src.slice(i + tail.length);
  return new Function('require', '__dirname', '__filename', src + '\nreturn { buildEnv };')(
    require, path.dirname(PROBE), PROBE);
}

/**
 * Extract the candidate list (runSearch / selectCandidate) of demo/route_planner/index.html and run it in node.
 * Not reimplemented either: the HTML code is evaluated as is, with a stub DOM.
 *   The candidate list lives in the DOM, so RQ2-a (buildAnimFrames) does not exercise it; it is run here.
 */
function loadDemoUI(htmlPath, DATA, R) {
  if (!fs.existsSync(htmlPath)) return { skip: htmlPath + ' が無い' };
  const html = fs.readFileSync(htmlPath, 'utf8');
  const s = html.indexOf('// ===== UI bindings =====');
  const e = html.indexOf("document.getElementById('search-btn').onclick = runSearch;");
  if (s < 0 || e < 0 || e <= s) return { skip: 'UI bindings の目印が見つからない' };

  const mkEl = (tag) => ({
    tagName: tag, className: '', dataset: {}, style: {}, children: [], _html: '', textContent: '',
    onclick: null,
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; this.children = []; },
    appendChild(c) { this.children.push(c); return c; },
    insertAdjacentHTML(pos, h) { this._html = (pos === 'afterbegin') ? h + this._html : this._html + h; },
    classList: { add() {}, remove() {} },
  });
  const els = {};
  const document = {
    getElementById(id) { return els[id] || (els[id] = mkEl('div')); },
    createElement(tag) { return mkEl(tag); },
    querySelectorAll(sel) {
      const list = (els['candidate-list'] || mkEl('div')).children;
      return sel === '.candidate' ? list.filter(c => c.className === 'candidate') : [];
    },
  };
  const shown = { path: null };
  // The page's escape function for names put into HTML (esc), taken from the HTML as it is
  //   (pages without it get one that returns the text unchanged)
  const es = html.indexOf('    function esc(s) {');
  const ee = es < 0 ? -1 : html.indexOf('\n    }\n', es);
  const esc = ee > es ? new Function(html.slice(es, ee + 6) + '; return esc;')() : (x => String(x));
  const ui = new Function('DATA', 'document', 'setTimeout', 'findMultipleRoutes', 'getRouter',
    'buildAnimFrames', 'lineColor', 'fmtClock', 'fmtDuration', 'toMin', 'resolveGroupIds', 'showRoute',
    'tripLabel', 'esc',
    html.slice(s, e) + '; return { runSearch, selectCandidate };')(
    DATA, document, (fn) => fn(), R.findMultipleRoutes, R.getRouter, R.buildAnimFrames,
    () => '#888', R.fmtClock, R.fmtDuration, R.toMin, R.resolveGroupIds, (p) => { shown.path = p; },
    R.tripLabel, esc);

  // The demo's trip panel (renderTripPanel).
  //   currentDepMin / currentArrMin / lastDepMin are outer variables set by showRoute, so pass them as arguments.
  const ps = html.indexOf('    function renderTripPanel(path) {');
  const pe = ps < 0 ? -1 : html.indexOf('\n    function ', ps + 10);
  const panelSrc = (ps >= 0 && pe > ps) ? html.slice(ps, pe) : null;

  return {
    /** Render the trip panel and return its sections (walk, transfer wait, same train) in order */
    panel(path, depMin, arrMin) {
      if (!panelSrc) return null;
      const box = {};
      ['tp-title', 'tp-sub', 'tp-legs'].forEach(id => { box[id] = mkEl('div'); });
      const doc = { getElementById: (id) => box[id] || mkEl('div'), createElement: mkEl };
      const fn = new Function('DATA', 'document', 'stopName', 'lineColor', 'fmtClock', 'fmtDuration',
        'getRouter', 'toMin', 'currentArrMin', 'currentDepMin', 'lastDepMin', 'tripLabel', 'esc',
        panelSrc + '; return renderTripPanel;')(
        DATA, doc, R.stopName, () => '#888', R.fmtClock, R.fmtDuration, R.getRouter, R.toMin,
        arrMin, depMin, depMin, R.tripLabel, esc);
      fn(path);
      return { sub: box['tp-sub'].innerHTML, marks: box['tp-legs'].children.map(c => c.className + '|' + c.textContent) };
    },

    /** Search and return the rendered candidate cards (card.html = card content, card.path = itinerary shown on click) */
    run(from, to, depStr) {
      // The input elements were captured at extraction (const originInput = ...), so set values instead of recreating them
      document.getElementById('origin-input').value = from;
      document.getElementById('dest-input').value = to;
      document.getElementById('time-input').value = depStr;
      document.getElementById('candidate-list').innerHTML = '';
      ui.runSearch();
      const list = els['candidate-list'].children;
      const cards = list.filter(c => c.className === 'candidate');
      const notes = list.filter(c => c.className === 'vp-none').map(c => c.textContent);
      const out = [];
      for (let i = 0; i < cards.length; i++) {
        shown.path = null;
        ui.selectCandidate(i);          // the itinerary shown on click must match the card
        out.push({ html: cards[i].innerHTML, path: shown.path });
      }
      return { cards: out, notes, empty: /no-result/.test(els['candidate-list'].innerHTML) };
    },
  };
}

/** Read (from, to, dep) from the expectations table (empty if absent) */
function tableQueries() {
  if (!fs.existsSync(TABLE)) return [];
  const txt = fs.readFileSync(TABLE, 'utf8').replace(/^﻿/, '');
  const lines = txt.split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',');
  const ci = { from: head.indexOf('from'), to: head.indexOf('to'), dep: head.indexOf('dep') };
  return lines.slice(1).map(l => {
    const c = l.split(',');
    return { from: c[ci.from], to: c[ci.to], dep: c[ci.dep], src: '期待値表' };
  }).filter(q => q.from && q.to && q.dep);
}

function rndFactory(seed) {
  let x = (seed >>> 0) || 1;
  return () => { x ^= x << 13; x >>>= 0; x ^= x >> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; };
}
const hhmm = m => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');

/** Straight-line distance between two points (km): 111 km per degree, longitude scaled by latitude (same as RQ4) */
function km(a, b) {
  if (!a || !b || a.lat == null || b.lat == null) return null;
  const dy = (a.lat - b.lat) * 111.0;
  const dx = (a.lon - b.lon) * 111.0 * Math.cos((a.lat + b.lat) / 2 * Math.PI / 180);
  return Math.sqrt(dx * dx + dy * dy);
}
/** Quantile of a list of numbers (p = 0 to 1) */
function q(xs, p) {
  if (!xs.length) return null;
  const a = xs.slice().sort((x, y) => x - y);
  return a[Math.min(a.length - 1, Math.floor(p * (a.length - 1) + 0.5))];
}

/** Random queries (chosen as in tests/pyraptor: stations served by at least minTrips trips, fixed seed) */
function sampleQueries(DATA, n, rnd, minTrips) {
  const served = {};
  DATA.trips.forEach(t => new Set(t.s).forEach(g => { served[g] = (served[g] || 0) + 1; }));
  const names = Object.keys(DATA.name_to_groups).filter(nm =>
    DATA.name_to_groups[nm].reduce((s, g) => s + (served[g] || 0), 0) >= minTrips).sort();
  const out = [];
  while (out.length < n && names.length > 1) {
    const a = names[Math.floor(rnd() * names.length)], b = names[Math.floor(rnd() * names.length)];
    const ga = new Set(DATA.name_to_groups[a]);
    if (DATA.name_to_groups[b].some(g => ga.has(g))) continue;
    out.push({ from: a, to: b, dep: hhmm(4 * 60 + Math.floor(rnd() * ((23 - 4) * 60 / 5)) * 5), src: '無作為' });
  }
  return out;
}

/** Queries likely to produce walking legs: between the two ends of walking links (where the page breaks most easily) */
function walkQueries(DATA, n, rnd) {
  const pairs = [];
  for (const g of Object.keys(DATA.walks || {})) {
    for (const [h] of DATA.walks[g]) {
      const a = DATA.groups[g].name, b = DATA.groups[h].name;
      if (a === b) continue;
      const ga = DATA.name_to_groups[a], gb = DATA.name_to_groups[b];
      if (!ga || !gb || gb.some(x => ga.includes(x))) continue;
      pairs.push([a, b]);
    }
  }
  pairs.sort((p, q) => (p[0] + p[1] < q[0] + q[1] ? -1 : 1));
  const out = [];
  for (let i = 0; i < n && pairs.length; i++) {
    const [a, b] = pairs[Math.floor(rnd() * pairs.length)];
    out.push({ from: a, to: b, dep: hhmm(6 * 60 + Math.floor(rnd() * (14 * 60 / 5)) * 5), src: '徒歩' });
  }
  return out;
}

/** Replay an itinerary leg by leg (same counting as replay in tests/pyraptor/route_planner_batch.js) */
function replay(DATA, toMin, p, depMin) {
  let cur = depMin;
  const legs = [];
  for (const l of p) {
    if (l.walk) { const ed = cur, at = cur + l.walkMin; cur = at; legs.push({ l, ed, at }); continue; }
    const t = DATA.trips[l.tripIdx];
    const bd = toMin(t.dep[l.boardIdx]) ?? toMin(t.arr[l.boardIdx]);
    let ed;
    if (l.dayShift !== undefined) ed = bd + l.dayShift;
    else { ed = bd; while (ed < cur) ed += 1440; }
    const am = toMin(t.arr[l.alightIdx]) ?? toMin(t.dep[l.alightIdx]);
    let at = (am != null) ? am + (ed - bd) : ed;
    while (at < ed) at += 1440;
    cur = at;
    legs.push({ l, t, ed, at, bd });
  }
  return { legs, dep: legs.length ? legs[0].ed : depMin, arr: cur };
}

/**
 * Times the page should show (the reference). Same as the replay, except that when the itinerary starts with a walk,
 * the walk is placed to end at the departure of the first trip (no waiting at the origin, the page's rule).
 * An itinerary that is all walking starts at the query time.
 */
function screenTimes(rp, p, depMin) {
  const exp = rp.legs.map(x => ({ ed: x.ed, at: x.at }));
  if (p.length && p[0].walk) {
    const k = p.findIndex(l => !l.walk);
    const t0 = (k > 0) ? rp.legs[k].ed - p[0].walkMin : depMin;
    const d = t0 - exp[0].ed;
    exp[0] = { ed: exp[0].ed + d, at: exp[0].at + d };
  }
  return { exp, dep: exp.length ? exp[0].ed : depMin, arr: exp.length ? exp[exp.length - 1].at : depMin };
}

/**
 * Share of estimated trips in the printed timetable, counted on the GTFS before expansion (`meta.gtfs_dir`).
 * Counted on expanded trips, one frequency box ("此間○分毎") becomes hundreds of trips and the share is overstated.
 * Returns null if the GTFS cannot be read (then only the expanded counts are printed).
 */
function printedShare(DATA) {
  const gd = DATA.meta && DATA.meta.gtfs_dir;
  if (!gd) return null;
  const dir = path.join(BASE, 'data', gd);
  const isEst = id => id.startsWith('TQ') || id.startsWith('TF');   // TQ = template trips of frequency-only sections, TF = template trips of frequency boxes ("此間N分毎")
  const count = (file, col) => {
    const lines = fs.readFileSync(path.join(dir, file), 'utf8').split('\n');
    const i = lines[0].split(',').indexOf(col);   // look up the column by name (the first column of trips.txt is route_id)
    if (i < 0) throw new Error(file + ' に ' + col + ' 列が無い');
    let est = 0, all = 0;
    for (let k = 1; k < lines.length; k++) {
      if (!lines[k].trim()) continue;
      all++;
      if (isEst(lines[k].split(',')[i] || '')) est++;
    }
    return { est, all };
  };
  try {
    return { trips: count('trips.txt', 'trip_id'), stops: count('stop_times.txt', 'trip_id') };
  } catch (e) {
    return null;
  }
}

function main() {
  const o = parseArgs(process.argv.slice(2));
  const { DATA, R } = loadProbe().buildEnv(o.html, o.data);
  const toMin = R.toMin;
  const dui = loadDemoUI(o.html, DATA, R);
  const rnd = rndFactory(o.seed);
  const queries = tableQueries()
    .concat(sampleQueries(DATA, o.sample, rnd, o.minTrips))
    .concat(walkQueries(DATA, o.walkSample, rnd));

  console.log('データ ' + path.relative(BASE, o.data)
    + (DATA.meta ? '（' + DATA.meta.gtfs_dir + ' / GTFS ' + (DATA.meta.gtfs_stop_times_mtime || '?') + '）'
                 : '（素性の記録なし）'));
  console.log('画面 (a) ' + path.relative(BASE, o.html)
    + '　(c) ' + (dui.skip ? '見ない（' + dui.skip + '）'
                          : path.relative(BASE, o.html) + ' の候補一覧・先頭 ' + o.screenSample + ' 検索'));
  const cnt = s => queries.filter(q => q.src === s).length;
  console.log('検索 ' + queries.length + ' 件（期待値表 ' + cnt('期待値表') + '＋無作為 ' + cnt('無作為')
    + '＋徒歩まわり ' + cnt('徒歩') + '・seed ' + o.seed + '）／1 検索あたり候補 ' + o.routes + ' 本まで');

  const bad = { rq1: [], dup: [], anim: [], ui: [], panel: [] };
  let nPath = 0, nFound = 0, nAbs = 0, nWalk = 0;
  let qi = -1, nUI = 0, nCard = 0, nVpExtra = 0, nVpNone = 0, nPanel = 0;
  const junctions = [];   // RQ5 connections (all candidates)
  const tops = [];        // RQ6 and RQ7: candidate 1 only

  for (const q of queries) {
    qi++;
    const fg = R.resolveGroupIds(q.from), tg = R.resolveGroupIds(q.to);
    if (!fg || !tg) { bad.rq1.push('  FAIL 駅名が引けない: ' + q.from + ' / ' + q.to); continue; }
    const depMin = toMin(q.dep);
    const paths = R.findMultipleRoutes(fg, tg, depMin, o.routes);
    const one = R.findRoute(fg, tg, depMin, {});
    if (one) nFound++;
    if (one && paths.length) {   // the first result of findMultipleRoutes should equal findRoute
      const a = replay(DATA, toMin, one, depMin).arr, b = replay(DATA, toMin, paths[0], depMin).arr;
      if (a !== b) bad.rq1.push('  FAIL ' + q.from + '→' + q.to + ' ' + q.dep + '發: 候補1 の到着 '
        + b + ' が findRoute の ' + a + ' と違う');
    }
    // Candidate order: earliest arrival first; for the same arrival, the later departure first.
    //   No candidate that only leaves earlier and waits longer for the same arrival (allowed if it has fewer transfers).
    for (let pi = 1; pi < paths.length; pi++) {
      const a0 = replay(DATA, toMin, paths[pi - 1], depMin), a1 = replay(DATA, toMin, paths[pi], depMin);
      const s0 = screenTimes(a0, paths[pi - 1], depMin), s1 = screenTimes(a1, paths[pi], depMin);
      if (s1.arr < s0.arr) {
        bad.rq1.push('  FAIL ' + q.from + '→' + q.to + ' ' + q.dep + '發: 候補' + (pi + 1)
          + ' の到着が候補' + pi + ' より早い（到着の早い順になっていない）');
      } else if (s1.arr === s0.arr && s1.dep > s0.dep
                 && R.getRouter().countTransfers(paths[pi]) <= R.getRouter().countTransfers(paths[pi - 1])) {
        bad.rq1.push('  FAIL ' + q.from + '→' + q.to + ' ' + q.dep + '發: 候補' + pi
          + ' は候補' + (pi + 1) + ' と同じ到着で早く出るだけ（待つだけの候補）');
      }
    }

    const sigs = new Set();
    for (let pi = 0; pi < paths.length; pi++) {
      const p = paths[pi];
      nPath++;
      if (p.some(l => l.walk)) nWalk++;
      const label = q.from + '→' + q.to + ' ' + q.dep + '發 候補' + (pi + 1);

      // ---------------- RQ1 ----------------
      const why = [];
      if (!p.length) why.push('区間が 0 本');
      for (let i = 0; i < p.length; i++) {
        const l = p[i];
        if (i > 0 && p[i - 1].alightStation !== l.boardStation) why.push('区間' + i + ': 降りた駅と次に乗る駅が違う');
        if (l.walk) {
          if (l.boardStation === l.alightStation) why.push('区間' + i + ': 徒歩の行き先が同じ駅');
          if (!(l.walkMin > 0)) why.push('区間' + i + ': 徒歩の分数が 0 以下');
          continue;
        }
        const t = DATA.trips[l.tripIdx];
        if (!t) { why.push('区間' + i + ': 便が無い'); continue; }
        if (!(l.boardIdx < l.alightIdx)) why.push('区間' + i + ': 乗る位置 ≧ 降りる位置');
        if (t.s[l.boardIdx] !== l.boardStation) why.push('区間' + i + ': 乗る駅が便の停車と違う');
        if (t.s[l.alightIdx] !== l.alightStation) why.push('区間' + i + ': 降りる駅が便の停車と違う');
        if ((toMin(t.dep[l.boardIdx]) ?? toMin(t.arr[l.boardIdx])) == null) why.push('区間' + i + ': 時刻の無い駅で乗っている');
        if ((toMin(t.arr[l.alightIdx]) ?? toMin(t.dep[l.alightIdx])) == null) why.push('区間' + i + ': 時刻の無い駅で降りている');
      }
      const rp = replay(DATA, toMin, p, depMin);
      for (let i = 1; i < rp.legs.length; i++) {
        if (rp.legs[i].ed < rp.legs[i - 1].at) why.push('区間' + i + ': 前に降りた時刻より前に乗っている');
      }
      if (p.length) {
        if (!fg.includes(p[0].boardStation)) why.push('起点が問い合わせの出発駅でない');
        if (!tg.includes(p[p.length - 1].alightStation)) why.push('終点が問い合わせの到着駅でない');
        if (rp.dep < depMin) why.push('出発が問い合わせの時刻より前');
      }
      if (why.length) bad.rq1.push('  FAIL ' + label + ': ' + [...new Set(why)].join(' / '));

      const sig = p.map(l => l.walk ? 'w:' + l.boardStation + '-' + l.alightStation
                                    : l.tripIdx + ':' + l.boardIdx + '-' + l.alightIdx).join('|');
      if (sigs.has(sig)) bad.dup.push('  FAIL ' + label + ': 前の候補とまったく同じ行程');
      sigs.add(sig);
      if (!p.length) continue;

      // ---------------- RQ2 ----------------
      const S = screenTimes(rp, p, depMin);
      // Compare absolute times only when every leg has dayShift (data with PREV_DAY_BOARDING).
      // For older data without it the page recomputes day crossings, so compare offsets from the departure only.
      const abs = p.every(l => l.walk || l.dayShift !== undefined);
      if (abs) nAbs++;

      // (a) buildAnimFrames
      const frames = R.buildAnimFrames(p, depMin);
      const wa = [];
      const want = p.reduce((s, l) => s + (l.walk ? 2 : l.alightIdx - l.boardIdx + 1), 0);
      if (!frames || frames.length !== want) {
        wa.push('点の数 ' + (frames ? frames.length : 'なし') + ' ≠ 停車の数 ' + want);
      } else {
        const off = abs ? 0 : frames[0][0] - S.dep;
        let b = 0;
        for (let i = 0; i < p.length; i++) {
          const span = p[i].walk ? 1 : p[i].alightIdx - p[i].boardIdx;
          if (frames[b][0] !== S.exp[i].ed + off) {
            wa.push('区間' + i + ' の乗る時刻 ' + frames[b][0] + ' ≠ ' + (S.exp[i].ed + off));
          }
          if (frames[b + span][0] !== S.exp[i].at + off) {
            wa.push('区間' + i + ' の降りる時刻 ' + frames[b + span][0] + ' ≠ ' + (S.exp[i].at + off));
          }
          b += span + 1;
        }
        for (let i = 1; i < frames.length; i++) {
          if (frames[i][0] < frames[i - 1][0]) { wa.push('時刻が前へ戻る'); break; }
        }
        if (frames[frames.length - 1][0] - frames[0][0] !== S.arr - S.dep) {
          wa.push('所要 ' + (frames[frames.length - 1][0] - frames[0][0]) + ' 分 ≠ ' + (S.arr - S.dep) + ' 分');
        }
      }
      if (wa.length) bad.anim.push('  FAIL ' + label + ': ' + [...new Set(wa)].join(' / '));

      // ---------------- RQ5 transfer slack (all candidates) ----------------
      let prevRide = -1;
      for (let i = 0; i < p.length; i++) {
        if (p[i].walk) continue;
        if (prevRide >= 0) {
          const a = DATA.trips[p[prevRide].tripIdx], b = DATA.trips[p[i].tripIdx];
          const viaWalk = p.slice(prevRide + 1, i).some(l => l.walk);
          // continuing on the same through train (same condition as isContinuation in the embedded search core) is not a transfer
          const cont = !viaWalk && !!(a.p && b.p && a.p === b.p && p[prevRide].tripIdx !== p[i].tripIdx);
          if (!cont) {
            const fromName = R.stopName(DATA, a, p[prevRide].alightIdx);
            const toName = R.stopName(DATA, b, p[i].boardIdx);
            junctions.push({
              slack: rp.legs[i].ed - rp.legs[i - 1].at, viaWalk, fromName, toName,
              where: fromName + (fromName === toName ? '' : '→' + toName),
              what: a.l + ' ' + a.n + ' → ' + b.l + ' ' + b.n, label,
            });
          }
        }
        prevRide = i;
      }

      // ---------------- RQ6 and RQ7 (candidate 1 only, the route users actually see) ----------------
      if (pi === 0) {
        let ride = 0, bad6 = false, nEst = 0, nRide = 0;
        for (const l of p) {
          if (l.walk) {
            const d = km(DATA.groups[l.boardStation], DATA.groups[l.alightStation]);
            if (d == null) bad6 = true; else ride += d;
            continue;
          }
          const t = DATA.trips[l.tripIdx];
          nRide++;
          if (t.est) nEst++;
          for (let j = l.boardIdx; j < l.alightIdx; j++) {
            const d = km(DATA.groups[t.s[j]], DATA.groups[t.s[j + 1]]);
            if (d == null) bad6 = true; else ride += d;
          }
        }
        const od = km(DATA.groups[p[0].boardStation], DATA.groups[p[p.length - 1].alightStation]);
        tops.push({
          label, rideKm: bad6 ? null : ride, odKm: od,
          durMin: S.arr - S.dep, nEst, nRide,
        });
      }
    }

    // ---------------- RQ2-d trip panel (the demo's renderTripPanel, in the DOM) ----------------
    // Checks that transfer waits and "same train" marks follow the same rule as countTransfers,
    //   catching a continuation of the same through train (only the line name changes) shown as a transfer.
    if (!dui.skip && qi < o.screenSample) {
      for (let pi2 = 0; pi2 < paths.length; pi2++) {
        const p2 = paths[pi2];
        if (!p2.length) continue;
        const rp2 = replay(DATA, toMin, p2, depMin);
        const S2 = screenTimes(rp2, p2, depMin);
        const wd = [];
        try {
          const got = dui.panel(p2, S2.dep, S2.arr);
          if (!got) { wd.push('renderTripPanel が切り出せない'); }
          else {
            nPanel++;
            const wantTr = R.getRouter().countTransfers(p2);
            const mr = /乗換 (\d+)回/.exec(got.sub);
            if (!mr) wd.push('「乗換 N回」が出ていない');
            else if (parseInt(mr[1], 10) !== wantTr) wd.push('乗換 ' + mr[1] + ' 回 ≠ ' + wantTr + ' 回');
            // build the expected section for each leg boundary
            const want = [];
            for (let i = 1; i < p2.length; i++) {
              if (p2[i].walk) continue;   // walking legs are drawn as their own section ("徒歩 N 分", walk N min)
              const cont = !p2[i - 1].walk && R.getRouter().isContinuation(p2.slice(0, i), p2[i].tripIdx);
              const wait = S2.exp[i].ed - S2.exp[i - 1].at;
              if (cont) want.push('stay');
              else if (wait > 0) want.push('transfer');
            }
            const gotMarks = got.marks.filter(m => /leg-wait/.test(m))
              .map(m => /leg-stay/.test(m) ? 'stay' : 'transfer');
            if (gotMarks.join(',') !== want.join(',')) {
              wd.push('乗換／同じ列車のままの並びが [' + gotMarks.join(',') + '] ＝ [' + want.join(',') + '] でない');
            }
          }
        } catch (err) {
          wd.push('例外 ' + err.message);
        }
        if (wd.length) {
          bad.panel.push('  FAIL ' + q.from + '→' + q.to + ' ' + q.dep + '發 候補' + (pi2 + 1)
            + ': ' + [...new Set(wd)].join(' / '));
        }
      }
    }

    // ---------------- RQ2-c candidate list (the demo page, in the DOM) ----------------
    // Not exercised by RQ2-a (buildAnimFrames): checks that a card's times match the itinerary shown
    //   when the card is clicked (misaligned order).
    if (!dui.skip && qi < o.screenSample) {
      nUI++;
      const wc = [];
      try {
        const r = dui.run(q.from, q.to, q.dep);
        if (!r.cards.length && paths.length) wc.push('候補一覧が空（検索は ' + paths.length + ' 本）');
        for (let i = 0; i < r.cards.length; i++) {
          const c = r.cards[i];
          if (!c.path) { wc.push('カード' + (i + 1) + ' を押しても行程が出ない'); continue; }
          const fr = R.buildAnimFrames(c.path, depMin);
          const wantClock = R.fmtClock(fr[0][0]) + ' 発 → ' + R.fmtClock(fr[fr.length - 1][0]) + ' 着';
          if (c.html.indexOf(wantClock) < 0) {
            wc.push('カード' + (i + 1) + ' に「' + wantClock + '」が無い（押したときに出る行程と違う）');
          }
          const wantDur = R.fmtDuration(fr[fr.length - 1][0] - fr[0][0]);
          if (c.html.indexOf('>' + wantDur + '<') < 0) wc.push('カード' + (i + 1) + ' の所要「' + wantDur + '」が無い');
          const wantTr = '乗換 ' + R.getRouter().countTransfers(c.path) + ' 回';
          if (c.html.indexOf(wantTr) < 0) wc.push('カード' + (i + 1) + ' の「' + wantTr + '」が無い');
          // Number of ride rows on the card = number of trains ridden = transfers + 1,
          //   catching a continuation of the same through train (only the line name changes) shown as a separate row.
          const nRide = (c.html.match(/leg leg-ride/g) || []).length;
          const wantRide = c.path.some(l => !l.walk) ? R.getRouter().countTransfers(c.path) + 1 : 0;
          if (nRide !== wantRide) {
            wc.push('カード' + (i + 1) + ' の乗る行 ' + nRide + ' ≠ 乗った列車 ' + wantRide + ' 本（乗換＋1）');
          }
        }
        nCard += r.cards.length;
        nVpExtra += Math.max(0, r.cards.length - paths.length);
        nVpNone += r.notes.length;
      } catch (err) {
        wc.push('例外 ' + err.message);
      }
      if (wc.length) {
        bad.ui.push('  FAIL ' + q.from + '→' + q.to + ' ' + q.dep + '發: ' + [...new Set(wc)].join(' / '));
      }
    }
  }

  const show = (title, rows) => {
    console.log('\n' + title);
    rows.slice(0, MAX_SHOW).forEach(x => console.log(x));
    if (rows.length > MAX_SHOW) console.log('   …ほか ' + (rows.length - MAX_SHOW) + ' 件');
    console.log('   FAIL ' + rows.length);
  };
  console.log('\n候補 ' + nPath + ' 本（経路が見つかった検索 ' + nFound + '・徒歩を含む候補 ' + nWalk
    + '・時刻そのものを比べた候補 ' + nAbs + '）');
  show('■ RQ1 行程が成り立っているか', bad.rq1.concat(bad.dup));
  show('■ RQ2-a 地図と所要のもと（buildAnimFrames）', bad.anim);
  if (!dui.skip) {
    show('■ RQ2-c 候補一覧（demo の runSearch・' + nUI + ' 検索／カード ' + nCard
      + ' 枚＝うち「ほかの見方」で増えた ' + nVpExtra + ' 枚・行けない見方 ' + nVpNone + ' 件）', bad.ui);
    show('■ RQ2-d 行程パネル（demo の renderTripPanel・' + nPanel + ' 本）', bad.panel);
  }

  // ---------------- RQ5 transfer slack ----------------
  const slacks = junctions.map(j => j.slack);
  const zeroDiff = junctions.filter(j => !j.viaWalk && j.slack <= 0 && j.fromName !== j.toName);
  console.log('\n■ RQ5 乗換の余裕（全候補・同じ物理列車の続きは除く）');
  console.log('   乗り継ぎ ' + junctions.length + '（うち徒歩をはさむ ' + junctions.filter(j => j.viaWalk).length + '）'
    + '／0 分以下 ' + slacks.filter(x => x <= 0).length
    + '・5 分未満 ' + slacks.filter(x => x < 5).length
    + '・中央値 ' + q(slacks, 0.5) + ' 分');
  const seen5 = new Set();
  const zeroU = zeroDiff.filter(j => {
    if (seen5.has(j.where + j.what)) return false;
    seen5.add(j.where + j.what);
    return true;
  });
  console.log('   ★駅名が違う 0 分（歩く時間が要るのに 0 分）' + zeroDiff.length + ' 件'
    + (zeroDiff.length ? '（同じ乗り継ぎをまとめると ' + zeroU.length + '）' : '')
    + '　※近接の併合は 50m まで（それ以上は徒歩の辺）。同じ駅名どうしの 0 分は原本どおり');
  zeroU.slice(0, MAX_SHOW).forEach(j => console.log('      ' + j.slack + ' 分  ' + j.where + '  ' + j.what));
  if (zeroU.length > MAX_SHOW) console.log('      …ほか ' + (zeroU.length - MAX_SHOW) + ' 種');

  // ---------------- RQ6 detours and waits ----------------
  const det = tops.filter(t => t.rideKm != null && t.odKm != null && t.odKm >= OD_MIN_KM)
    .map(t => ({ r: t.rideKm / t.odKm, t }));
  const rs = det.map(x => x.r);
  const waits = junctions.filter(j => j.slack >= LONG_WAIT_MIN).sort((a, b) => b.slack - a.slack);
  const f2 = x => (x == null ? '-' : x.toFixed(2));
  console.log('\n■ RQ6 迂回と待ち（候補1 だけ・直線 ' + OD_MIN_KM + 'km 以上の ' + det.length + ' 本）');
  console.log('   迂回率（乗った距離 ÷ 直線）中央値 ' + f2(q(rs, 0.5)) + '・90% ' + f2(q(rs, 0.9))
    + '・最大 ' + f2(q(rs, 1.0)));
  det.sort((a, b) => b.r - a.r).slice(0, 5).forEach(x => console.log(
    '      ' + f2(x.r) + ' 倍  ' + x.t.label + '（乗車 ' + Math.round(x.t.rideKm) + 'km／直線 '
    + Math.round(x.t.odKm) + 'km・' + x.t.durMin + '分）'));
  const seen6 = new Set();
  const waitsU = waits.filter(j => {
    const k = j.where + j.what + j.slack;
    if (seen6.has(k)) return false;
    seen6.add(k);
    return true;
  });
  console.log('   ' + (LONG_WAIT_MIN / 60) + ' 時間超の待ち合わせ ' + waits.length + ' 件（全候補。同じ乗り継ぎをまとめると '
    + waitsU.length + '）');
  waitsU.slice(0, 5).forEach(j => console.log(
    '      ' + Math.floor(j.slack / 60) + '時間' + (j.slack % 60) + '分  ' + j.where + '  ' + j.what));

  // ---------------- RQ7 reliance on estimated trips ----------------
  const nEstTrip = DATA.trips.filter(t => t.est).length;
  const useEst = tops.filter(t => t.nEst > 0);
  const allEst = tops.filter(t => t.nRide > 0 && t.nEst === t.nRide);
  const pct = (a, b) => (b ? Math.round(a / b * 100) : 0) + '%';
  const pct1 = (a, b) => (b ? (a / b * 100).toFixed(1) : '0.0') + '%';
  const ps = printedShare(DATA);
  console.log('\n■ RQ7 推定便（原本が「此間○分毎」としか刷っていない区間）への依存');
  if (ps) {
    // print the share in the printed timetable first (expanded counts shown first would look much larger)
    console.log('   ★原本の紙面では 便 ' + ps.trips.all.toLocaleString() + ' のうち雛形便 ' + ps.trips.est
      + '（' + pct1(ps.trips.est, ps.trips.all) + '）／時刻のマス ' + ps.stops.all.toLocaleString()
      + ' のうち ' + ps.stops.est.toLocaleString() + '（' + pct1(ps.stops.est, ps.stops.all) + '）');
    console.log('   （経路検索は雛形便を間隔で広げるので 便 ' + DATA.trips.length.toLocaleString()
      + ' のうち ' + nEstTrip.toLocaleString() + '＝' + pct(nEstTrip, DATA.trips.length)
      + ' に見えるが、もとは ' + ps.trips.est + ' 本＝約 ' + Math.round(nEstTrip / ps.trips.est) + ' 倍）');
  } else {
    console.log('   データの便 ' + DATA.trips.length.toLocaleString() + ' のうち推定便 '
      + nEstTrip.toLocaleString() + '（' + pct(nEstTrip, DATA.trips.length) + '）'
      + '　※展開する前の GTFS が読めないので紙面での割合は出せない');
  }
  console.log('   候補1 ' + tops.length + ' 本のうち推定便を 1 本でも使う ' + useEst.length
    + '（' + pct(useEst.length, tops.length) + '）／全区間が推定便 ' + allEst.length + ' 本');

  const n = bad.rq1.length + bad.dup.length + bad.anim.length
          + bad.ui.length + bad.panel.length;
  console.log(n ? '\n★要対応 ' + n + ' 件（RQ1・RQ2。RQ5〜RQ7 は前回と比べるための数で FAIL は出さない）'
                : '\n✅ 要対応なし（RQ1・RQ2。RQ5〜RQ7 は前回と比べるための数）');
  return n ? 1 : 0;
}

process.exit(main());
