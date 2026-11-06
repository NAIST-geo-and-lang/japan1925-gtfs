#!/usr/bin/env node
/**
 * route_planner_probe.js — run the search of the journey planner page (demo/route_planner/index.html) from the terminal
 *
 * The logic is not reimplemented.
 *   The range from `function toMin(` to `// ===== Display =====` in the HTML is extracted as is and run with
 *   `new Function`, so the results follow any change to the HTML.
 *   (The search core itself is embedded in the HTML between `// <<<ROUTER_CORE>>>` and `// <<<END ROUTER_CORE>>>`.)
 *
 * Usage:
 *   node scripts/route_planner_probe.js search 大阪 京城 09:00
 *   node scripts/route_planner_probe.js sweep  大阪 京城 --step 5
 *   node scripts/route_planner_probe.js sweep  大阪 京城 --data2 <another router_data.js>   # compare two data files
 *   node scripts/route_planner_probe.js audit                                              # all departure times for representative pairs
 *
 * Common options:
 *   --html <path>   default demo/route_planner/index.html
 *   --data <path>   default data/gtfs_v1_release_router/router_data.js
 *                   (.json also works: read as JSON when there is no `var X =`)
 *   --max <min>     threshold for "too long" in audit (default 2880 = 48 hours)
 *
 * Exit code: 1 if audit finds a problem (for use from CI etc.)
 */
'use strict';
const fs = require('fs');
const path = require('path');

const BASE = path.dirname(__dirname);

// ------------------------------------------------------------------
// Arguments
// ------------------------------------------------------------------
function parseArgs(argv) {
  const opt = {
    html: path.join(BASE, 'demo/route_planner/index.html'),
    data: path.join(BASE, 'data/gtfs_v1_release_router/router_data.js'),
    data2: null, step: 15, max: 2880, _: [],
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--html') opt.html = argv[++i];
    else if (a === '--data') opt.data = argv[++i];
    else if (a === '--data2') opt.data2 = argv[++i];
    else if (a === '--step') opt.step = parseInt(argv[++i], 10);
    else if (a === '--max') opt.max = parseInt(argv[++i], 10);
    else opt._.push(a);
  }
  return opt;
}

// ------------------------------------------------------------------
// Extract the implementation (not reimplemented)
// ------------------------------------------------------------------
const SRC_BEGIN = ['    function toMin(s) {', 'function toMin(s) {'];
const SRC_END = ['    // ===== Display =====', '// ===== Display ====='];

function extractRouter(htmlPath) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  let s = -1, e = -1;
  for (const m of SRC_BEGIN) { s = html.indexOf(m); if (s >= 0) break; }
  for (const m of SRC_END) { e = html.indexOf(m); if (e >= 0) break; }
  if (s < 0 || e < 0 || e <= s) {
    throw new Error(
      `${htmlPath} からルータ部分を切り出せません。` +
      '（目印＝"function toMin(" 〜 "// ===== Display ====="。HTML 側を変えたらここも合わせる）');
  }
  return html.slice(s, e);
}

function loadData(dataPath) {
  const raw = fs.readFileSync(dataPath, 'utf8');
  const DATA = raw.trimStart().startsWith('{')
    ? JSON.parse(raw)
    : (new Function(raw + '; return ROUTER_DATA;'))();
  DATA.groupTrips = {};
  DATA.trips.forEach((t, ti) =>
    t.s.forEach(g => (DATA.groupTrips[g] = DATA.groupTrips[g] || []).push(ti)));
  return DATA;
}

function buildEnv(htmlPath, dataPath) {
  const src = extractRouter(htmlPath);
  const DATA = loadData(dataPath);
  const stationNames = Object.keys(DATA.name_to_groups).sort();
  const R = (new Function('DATA', 'stationNames', src +
    '; return { toMin, fmtClock, fmtDuration, resolveGroupIds,' +
    ' findRoute, findMultipleRoutes, buildAnimFrames, getRouter, stopName, tripLabel };'))(DATA, stationNames);
  return { DATA, R };
}

// ------------------------------------------------------------------
// Search (travel time computed as on the page: from end to end of buildAnimFrames)
// ------------------------------------------------------------------
function search(env, from, to, depStr, maxRoutes = 3) {
  const { DATA, R } = env;
  const fg = R.resolveGroupIds(from), tg = R.resolveGroupIds(to);
  if (!fg || !tg) return { error: `駅名が見つかりません（from=${from} to=${to}）` };
  const routes = R.findMultipleRoutes(fg, tg, R.toMin(depStr), maxRoutes);
  return {
    routes: routes.map(pathLegs => {
      const frames = R.buildAnimFrames(pathLegs, R.toMin(depStr));
      const dep = frames[0][0], arr = frames[frames.length - 1][0];
      return {
        depMin: dep, arrMin: arr, durMin: arr - dep,
        dep: R.fmtClock(dep), arr: R.fmtClock(arr), dur: R.fmtDuration(arr - dep),
        // transfers counted as on the page (continuing on the same through train, same p, is not counted; legs.length - 1 without p)
        transfers: R.getRouter().countTransfers(pathLegs),
        legs: pathLegs.map(l => {
          if (l.walk) {   // walking leg: no trip
            return {
              walk: true, line: '徒歩', num: String(l.walkMin), dir: '', est: false,
              from: DATA.groups[l.boardStation].name, to: DATA.groups[l.alightStation].name,
              dep: '', arr: '',
            };
          }
          const t = DATA.trips[l.tripIdx];
          return {
            line: t.l, num: t.n, dir: t.d, est: !!t.est,
            from: (R.stopName ? R.stopName(DATA, t, l.boardIdx) : DATA.groups[l.boardStation].name),
            to: (R.stopName ? R.stopName(DATA, t, l.alightIdx) : DATA.groups[l.alightStation].name),
            dep: t.dep[l.boardIdx] || t.arr[l.boardIdx],
            arr: t.arr[l.alightIdx] || t.dep[l.alightIdx],
          };
        }),
      };
    }),
  };
}

function fmtLeg(l) {
  if (l.walk) return `徒歩 ${l.num} 分 : ${l.from} → ${l.to}`;
  // est: estimated trip expanded from frequencies.txt (the frequency box "此間○分毎ニ運轉"), not a printed time
  const num = l.est ? `${l.num}（推定）` : (l.num || '(番号なし)');
  return `${l.line} ${num} : ${l.from} ${l.dep} → ${l.to} ${l.arr}`;
}

function printRoutes(label, res) {
  console.log('=== ' + label);
  if (res.error) { console.log('  ' + res.error); return; }
  if (!res.routes.length) { console.log('  経路が見つかりません'); return; }
  res.routes.forEach((r, i) => {
    const nEst = r.legs.filter(l => l.est).length;
    console.log(`  候補${i + 1}: ${r.dep} 発 → ${r.arr} 着  ${r.dur}（${r.durMin}分・乗車 ${r.legs.length} 本・乗換 ${r.transfers} 回${nEst ? `・うち推定便 ${nEst} 本` : ''}）`);
    r.legs.forEach(l => console.log('     ' + fmtLeg(l)));
  });
}

// ------------------------------------------------------------------
// Representative origin-destination pairs for audit (main lines, overseas connections and ships)
// ------------------------------------------------------------------
const AUDIT_PAIRS = [
  ['東京', '京都'], ['東京', '下關'], ['大阪', '京城'], ['東京', '青森'],
  ['東京', '長崎'], ['大阪', '高松'], ['東京', '札幌'], ['京都', '金澤'],
];

function audit(opt) {
  const env = buildEnv(opt.html, opt.data);
  const bad = [];
  console.log(`代表 ${AUDIT_PAIRS.length} 組 × 出発 ${Math.ceil(1440 / opt.step)} 通り`
    + `（${opt.step} 分刻み）／長すぎ判定 ${opt.max} 分`);
  for (const [from, to] of AUDIT_PAIRS) {
    const durs = [];
    for (let m = 0; m < 1440; m += opt.step) {
      const dep = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
      const res = search(env, from, to, dep, 1);
      if (res.error) { console.log(`  ${from}→${to}: ${res.error}`); break; }
      if (!res.routes.length) continue;
      durs.push({ dep, ...res.routes[0] });
    }
    if (!durs.length) continue;
    const best = Math.min(...durs.map(d => d.durMin));
    for (const d of durs) {
      // "too long" = above the threshold and more than twice the day's best (a wrong route, not just waiting)
      if (d.durMin > opt.max && d.durMin > best * 2) {
        bad.push({ from, to, ...d, best });
      }
    }
    const worst = durs.reduce((a, b) => (b.durMin > a.durMin ? b : a));
    console.log(`  ${from} → ${to}: 最短 ${best} 分 / 最長 ${worst.durMin} 分（${worst.dep} 発）`);
  }
  if (bad.length) {
    console.log(`\n❌ 不自然に長い経路 ${bad.length} 件（閾値 ${opt.max} 分かつ最短の2倍超）`);
    for (const b of bad.slice(0, 20)) {
      console.log(`  ${b.from}→${b.to} ${b.dep} 発: ${b.dur}（最短 ${b.best} 分）`);
      b.legs.forEach(l => console.log('     ' + fmtLeg(l)));
    }
    if (bad.length > 20) console.log(`  … 他 ${bad.length - 20} 件`);
    return 1;
  }
  console.log('\n✅ 不自然に長い経路は無し');
  return 0;
}

function sweep(opt, from, to) {
  const a = buildEnv(opt.html, opt.data);
  const b = opt.data2 ? buildEnv(opt.html, opt.data2) : null;
  console.log(`${from} → ${to}（${opt.step} 分刻み）` + (b ? '　※ data と data2 の比較' : ''));
  let diff = 0;
  for (let m = 0; m < 1440; m += opt.step) {
    const dep = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
    const ra = search(a, from, to, dep, 1);
    const da = ra.routes && ra.routes.length ? ra.routes[0].durMin : null;
    if (!b) { console.log(`  ${dep}  ${da == null ? '経路なし' : da + '分'}`); continue; }
    const rb = search(b, from, to, dep, 1);
    const db = rb.routes && rb.routes.length ? rb.routes[0].durMin : null;
    if (da !== db) { diff++; console.log(`  ${dep}  data ${da}分 / data2 ${db}分　差 ${da - db}`); }
  }
  if (b) console.log(diff ? `  → 食い違い ${diff} 通り` : '  → 全時刻で一致');
  return 0;
}

function main() {
  const opt = parseArgs(process.argv.slice(2));
  const cmd = opt._[0];
  if (!cmd || cmd === 'help') {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0]);
    return 0;
  }
  if (cmd === 'search') {
    const [, from, to, dep] = opt._;
    if (!from || !to) { console.error('search <出発駅> <到着駅> [HH:MM]'); return 2; }
    const env = buildEnv(opt.html, opt.data);
    printRoutes(`${opt.data}  ${from} → ${to}  発 ${dep || '08:00'}`,
      search(env, from, to, dep || '08:00'));
    if (opt.data2) {
      const env2 = buildEnv(opt.html, opt.data2);
      printRoutes(`${opt.data2}  ${from} → ${to}  発 ${dep || '08:00'}`,
        search(env2, from, to, dep || '08:00'));
    }
    return 0;
  }
  if (cmd === 'sweep') {
    const [, from, to] = opt._;
    if (!from || !to) { console.error('sweep <出発駅> <到着駅> [--step N] [--data2 …]'); return 2; }
    return sweep(opt, from, to);
  }
  if (cmd === 'audit') return audit(opt);
  console.error('不明なコマンド: ' + cmd + '（search / sweep / audit / help）');
  return 2;
}

process.exit(main());
