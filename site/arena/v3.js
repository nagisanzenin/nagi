'use strict';
/* Game Arena v3: renders every table and chart from v3.json (built by build/make_v3.py). */
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var el = function (tag, attrs, html) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) { if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
    if (html != null) e.innerHTML = html;
    return e;
  };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  var pct = function (x) { return x == null ? '—' : Math.round(100 * x) + '%'; };
  var sec = function (x) { return x == null ? '—' : (+x).toFixed(1) + ' s'; };
  var NS = 'http://www.w3.org/2000/svg';
  var D, P, G;

  function board() {
    var tb = $('#board tbody'); tb.replaceChildren();
    D.players.forEach(function (p) {
      var tr = el('tr', { 'class': p.kind === 'nagi' ? 'nagi' : '' });
      var lo = p.ci95[0], hi = p.ci95[1];
      tr.innerHTML = '<td class="rank">' + p.rank + '</td>' +
        '<td><span class="who">' + esc(p.label) + '</span><span class="sub">' + esc(p.sub) + '</span></td>' +
        '<td class="num"><span class="big">' + pct(p.composite) + '</span><span class="ci">[' + pct(lo) + ', ' + pct(hi) + ']</span>' +
        '<span class="cibar" role="img" aria-label="95% interval ' + pct(lo) + ' to ' + pct(hi) + '"><s></s><i style="left:' + (100 * lo) + '%;width:' + (100 * (hi - lo)) + '%"></i><b style="left:' + (100 * p.composite) + '%"></b></span></td>' +
        G.map(function (g) { return '<td class="num">' + pct(p.games[g.id].win) + '</td>'; }).join('');
      tb.append(tr);
    });
    D.unranked.forEach(function (u) {
      var tr = el('tr', { 'class': 'unranked' });
      tr.innerHTML = '<td class="rank">–</td><td><span class="who">' + esc(u.label) + '</span><span class="sub">Not ranked: failed its own conformance gate before play</span></td><td>not ranked</td><td>—</td><td>—</td><td>—</td>';
      tb.append(tr);
      $('#unranked-note').innerHTML = '<strong>' + esc(u.label) + ':</strong> ' + esc(u.reason);
    });
    var c = D.champion;
    $('#champ-rule').textContent = 'Rule: ' + c.rule + ' External competitors that played: ' + c.externals.join(', ') + '. Top Nagi entry: ' + c.champion + '.';
    $('#champ-table thead').innerHTML = '<tr><th>#</th><th>Nagi entry</th>' + G.map(function (g) { return '<th>vs externals · ' + esc(g.name) + '</th>'; }).join('') + '<th>Composite</th><th>ΣRMST (s)</th><th>Mean level</th></tr>';
    $('#champ-table tbody').innerHTML = c.table.map(function (t) {
      return '<tr><td class="rank">' + t.rank + '</td><td class="who">' + esc(t.label) + '</td>' + G.map(function (g) { return '<td>' + pct(t.per_game[g.id]) + '</td>'; }).join('') +
        '<td><strong>' + pct(t.composite) + '</strong></td><td>' + t.rmst_sum.toFixed(1) + '</td><td>' + t.mean_level.toFixed(2) + '</td></tr>';
    }).join('');
  }

  function anchors() {
    $('#anchors tbody').innerHTML = G.map(function (g) {
      var a = g.anchors, f = function (r) { return sec(r[0]) + ' · L' + r[1]; };
      return '<tr><td>' + esc(g.name) + '</td><td>' + f(a.naive) + '</td><td>' + f(a.heuristic) + '</td><td>' + f(a.planner) + '</td><td>' + a.seeds + '</td></tr>';
    }).join('');
  }

  /* ---------- survival curves ---------- */
  var W = 340, H = 230, L = 34, R = 10, T = 22, B = 30;
  var xs = function (t) { return L + (W - L - R) * Math.min(t, 60) / 60; };
  var ys = function (s) { return T + (H - T - B) * (1 - s); };
  function stepPath(km) {
    var d = 'M' + xs(0) + ',' + ys(1), prev = 1;
    km.forEach(function (pt) { var t = pt[0], s = pt[1]; d += 'H' + xs(t).toFixed(1); if (s !== prev) { d += 'V' + ys(s).toFixed(1); prev = s; } });
    var end = km.length ? km[km.length - 1][0] : 0;
    if (prev > 0) d += 'H' + xs(60);  // censored rounds stay at their level to the cap
    else if (end < 60) { /* curve ends at the last failure */ }
    return d;
  }
  function aliveAt(km, t) { var s = 1; km.forEach(function (pt) { if (pt[0] <= t) s = pt[1]; }); return s; }
  function svgEl(tag, a) { var e = document.createElementNS(NS, tag); for (var k in a) e.setAttribute(k, a[k]); return e; }
  function pairCount(g, a, b) {
    var ta = P[a].games[g].t_fail, tb = P[b].games[g].t_fail, w = 0, t = 0, l = 0;
    Object.keys(ta).forEach(function (k) { if (!(k in tb)) return; var x = ta[k], y = tb[k]; if (x > y) w++; else if (x === y) t++; else l++; });
    return { w: w, t: t, l: l };
  }
  function drawKM() {
    var a = $('#pa').value, b = $('#pb').value, grid = $('#km'); grid.replaceChildren();
    G.forEach(function (g) {
      var fig = el('figure', { 'class': 'km' });
      fig.append(el('figcaption', null, esc(g.name)));
      var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': g.name + ' survival curves: ' + P[a].label + ' vs ' + P[b].label });
      for (var k = 0; k < 6; k++) {
        if (k % 2 === 0) svg.append(svgEl('rect', { 'class': 'lvl', x: xs(10 * k), y: T, width: xs(10) - xs(0), height: H - T - B }));
        var lt = svgEl('text', { x: xs(10 * k + 5), y: T - 8, 'text-anchor': 'middle' }); lt.textContent = 'L' + (k + 1); svg.append(lt);
      }
      [0, 0.5, 1].forEach(function (s) {
        svg.append(svgEl('line', { 'class': 'grid', x1: L, x2: W - R, y1: ys(s), y2: ys(s) }));
        var t = svgEl('text', { x: L - 6, y: ys(s) + 3, 'text-anchor': 'end' }); t.textContent = (100 * s) + '%'; svg.append(t);
      });
      [0, 10, 20, 30, 40, 50, 60].forEach(function (t) {
        var tx = svgEl('text', { x: xs(t), y: H - B + 14, 'text-anchor': 'middle' }); tx.textContent = t; svg.append(tx);
      });
      var xl = svgEl('text', { x: W - R, y: H - 4, 'text-anchor': 'end' }); xl.textContent = 'seconds'; svg.append(xl);
      [['N', g.anchors.naive[0]], ['H', g.anchors.heuristic[0]], ['P', g.anchors.planner[0]]].forEach(function (an) {
        svg.append(svgEl('line', { 'class': 'anchor', x1: xs(an[1]), x2: xs(an[1]), y1: T, y2: H - B }));
        var t = svgEl('text', { x: xs(an[1]) + 3, y: T + 10 }); t.textContent = an[0]; svg.append(t);
      });
      D.players.forEach(function (p) {
        if (p.id === a || p.id === b) return;
        var path = svgEl('path', { 'class': 'ctx', d: stepPath(p.games[g.id].km) });
        var ti = svgEl('title', {}); ti.textContent = p.label; path.append(ti); svg.append(path);
      });
      svg.append(svgEl('path', { 'class': 'lb', d: stepPath(P[b].games[g.id].km) }));
      svg.append(svgEl('path', { 'class': 'la', d: stepPath(P[a].games[g.id].km) }));
      var cross = svgEl('line', { 'class': 'cross', x1: 0, x2: 0, y1: T, y2: H - B, visibility: 'hidden' }); svg.append(cross);
      fig.append(svg);
      var read = el('p', { 'class': 'read', 'aria-live': 'polite' });
      var base = 'Median failure: ' + esc(P[a].label) + ' ' + sec(P[a].games[g.id].median_t) + ', ' + esc(P[b].label) + ' ' + sec(P[b].games[g.id].median_t) + '. Hover or tap the chart to read a time.';
      read.innerHTML = base; fig.append(read);
      var pc = pairCount(g.id, a, b);
      fig.append(el('p', { 'class': 'pair' }, esc(P[a].label) + ' outlasted ' + esc(P[b].label) + ' on <strong>' + pc.w + '</strong> of ' + (pc.w + pc.t + pc.l) + ' seeds' + (pc.t ? ', tied on ' + pc.t : '') + ' → ' + pct(D.pairwise[g.id][a][b]) + '.'));
      function move(ev) {
        var r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) * W / r.width;
        var t = Math.max(0, Math.min(60, (x - L) / (W - L - R) * 60));
        cross.setAttribute('x1', xs(t)); cross.setAttribute('x2', xs(t)); cross.setAttribute('visibility', 'visible');
        read.innerHTML = 'At ' + t.toFixed(1) + ' s (Level ' + Math.min(6, Math.floor(t / 10) + 1) + '): ' + esc(P[a].label) + ' <strong>' + pct(aliveAt(P[a].games[g.id].km, t)) + '</strong> alive · ' + esc(P[b].label) + ' <strong>' + pct(aliveAt(P[b].games[g.id].km, t)) + '</strong> alive.';
      }
      svg.addEventListener('pointermove', move);
      svg.addEventListener('pointerdown', move);
      svg.addEventListener('pointerleave', function () { cross.setAttribute('visibility', 'hidden'); read.innerHTML = base; });
      grid.append(fig);
    });
  }
  function survival() {
    ['#pa', '#pb'].forEach(function (s) {
      $(s).innerHTML = D.players.map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.label) + '</option>'; }).join('');
    });
    $('#pa').value = D.players[0].id;
    var jev = D.players.filter(function (p) { return p.label === 'Jev'; })[0];
    $('#pb').value = jev ? jev.id : D.players[1].id;
    ['#pa', '#pb'].forEach(function (s) {
      $(s).addEventListener('change', function () {
        if ($('#pa').value === $('#pb').value) { var o = s === '#pa' ? '#pb' : '#pa'; $(o).value = D.players.filter(function (p) { return p.id !== $(s).value; })[0].id; }
        drawKM();
      });
    });
    drawKM();
    var ts = ['10', '20', '30', '40', '50', '60'];
    $('#alive thead').innerHTML = '<tr><th>Player · game</th>' + ts.map(function (t) { return '<th>' + t + ' s</th>'; }).join('') + '</tr>';
    var rows = '';
    G.forEach(function (g) {
      D.players.forEach(function (p) {
        rows += '<tr><td>' + esc(p.label) + ' · ' + esc(g.name) + '</td>' + ts.map(function (t) { return '<td>' + pct(p.games[g.id].alive_at[t]) + '</td>'; }).join('') + '</tr>';
      });
    });
    $('#alive tbody').innerHTML = rows;
  }

  /* ---------- games ---------- */
  function games() {
    var host = $('#game-list'); host.replaceChildren();
    G.forEach(function (g, gi) {
      var art = el('article', { 'class': 'game', id: 'g-' + g.id });
      var copy = el('div');
      copy.innerHTML = '<p class="eyebrow">Game ' + (gi + 1) + '</p><h3 style="font-size:26px">' + esc(g.name) + '</h3><p class="small" style="font-size:15px;color:var(--nagi-bone)">' + esc(g.what) + '</p><p class="ctl">' + esc(g.controls) + '</p>';
      var rows = D.players.slice().sort(function (x, y) { return y.games[g.id].win - x.games[g.id].win; }).map(function (p) {
        var s = p.games[g.id];
        return '<tr class="' + (p.kind === 'nagi' ? 'nagi' : '') + '"><td class="who">' + esc(p.label) + '</td><td>' + pct(s.win) + '</td><td>' + sec(s.median_t) + '</td><td>L' + (+s.median_level) + '</td><td>' + s.rmst.toFixed(1) + '</td><td>' + s.ladder.toFixed(2) + '</td>' + (g.wall ? '<td>' + s.at_wall + '/' + s.n + '</td>' : '') + '</tr>';
      }).join('');
      copy.innerHTML += '<div class="table-wrap"><table><caption class="sr-only">' + esc(g.name) + ' results</caption><thead><tr><th>Player</th><th>Win rate</th><th>Median survived</th><th>Median level</th><th>RMST ≤60 s</th><th>Ladder</th>' + (g.wall ? '<th>Ended at ' + g.wall.t.toFixed(1) + ' s</th>' : '') + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
      if (g.wall) {
        var champ = P[D.players[0].id].games[g.id].at_wall;
        copy.innerHTML += '<p class="wall"><strong>Clustered end times.</strong> ' + esc(g.wall.note) + ' ' + esc(D.players[0].label) + ' ended ' + champ + ' of ' + P[D.players[0].id].games[g.id].n + ' rounds at exactly that time. Players failing on the same tick tie (½). ' + (g.wall.cause ? esc(g.wall.cause) : 'Per-round causes of failure are in the records, not in this summary.') + '</p>';
      }
      var outs = Object.keys(D.out_order[g.id]).map(function (seed) {
        var row = D.out_order[g.id][seed];
        return '<li><b>seed ' + seed + '</b>' + row.map(function (x, i) { return '<span' + (i === row.length - 1 ? ' class="last"' : '') + '>' + esc(x[1]) + ' ' + (+x[0]).toFixed(1) + ' s</span>'; }).join(' → ') + '</li>';
      }).join('');
      var ids = D.players.map(function (p) { return p.id; });
      var mx = '<tr><th>Row outlasted column</th>' + ids.map(function (id) { return '<th>' + esc(P[id].label) + '</th>'; }).join('') + '</tr>';
      var mb = ids.map(function (r) {
        return '<tr><td class="who">' + esc(P[r].label) + '</td>' + ids.map(function (c) {
          if (r === c) return '<td class="self">·</td>';
          var v = D.pairwise[g.id][r][c]; return '<td class="' + (v >= 0.7 ? 'hi' : v <= 0.3 ? 'lo' : '') + '">' + pct(v) + '</td>';
        }).join('') + '</tr>';
      }).join('');
      copy.innerHTML += '<details><summary>Out order per seed (first out → last standing)</summary><div class="in"><ol class="outs">' + outs + '</ol></div></details>' +
        '<details><summary>Pairwise win rates</summary><div class="in"><div class="table-wrap"><table class="mx"><caption class="sr-only">' + esc(g.name) + ' pairwise win rates</caption><thead>' + mx + '</thead><tbody>' + mb + '</tbody></table></div><p class="small">Share of the shared seeds on which the row player failed later than the column player; ties count ½.</p></div></details>';
      var fig = el('figure', { 'class': 'clip' });
      fig.innerHTML = '<div class="phone"><video controls muted playsinline preload="none" poster="' + esc(g.clip.poster) + '" aria-label="' + esc(g.name) + ': replay of seed index ' + g.clip.seed_index + '"><source src="' + esc(g.clip.src) + '" type="video/mp4"></video>' +
        '<div class="cover" aria-hidden="true"><span>' + esc(g.name) + '</span><small>▶ Replay · seed ' + g.clip.seed_index + '</small></div><div class="ph" aria-hidden="true"><span>' + esc(g.name) + '</span><small>Clip publishing soon</small></div></div>' +
        '<figcaption>' + esc(g.clip.players.join(' · ')) + '. Seed index ' + g.clip.seed_index + ', picked by a fixed rule (the lower-median round of the top Nagi entry), not by outcome. Replayed from the scored records.</figcaption>';
      art.append(copy, fig); host.append(art);
      var v = fig.querySelector('video'), src = fig.querySelector('source'), ph = fig.querySelector('.phone');
      var miss = function () { ph.classList.add('missing'); };
      v.addEventListener('error', miss, true); src.addEventListener('error', miss);
      // preload="none" never fetches, so probe the file once to show the placeholder when it is absent
      if (window.fetch) fetch(g.clip.src, { method: 'HEAD', cache: 'no-store' }).then(function (r) { if (!r.ok) miss(); }).catch(miss);
      // until the poster frame exists, label the player so it is not an empty black box
      var im = new Image(); im.onerror = function () { ph.classList.add('noposter'); }; im.src = g.clip.poster;
      v.addEventListener('play', function () { ph.classList.remove('noposter'); });
    });
  }

  /* ---------- fresh-seed confirmation (receipt numbers verbatim, shown to 3 decimals as in the report) ---------- */
  function confirmation() {
    var C = D.confirmation, sec_ = $('#confirm');
    if (!C) { if (sec_) sec_.hidden = true; return; }
    var p1 = function (x) { return (100 * x).toFixed(1) + '%'; };
    var pv = function (x) { return x < 0.0001 ? '< 0.0001' : x < 0.01 ? x.toFixed(4) : x.toFixed(2); };
    var ok = function (b) { return b ? '<b class="pass">PASS</b>' : '<b class="fail">not met</b>'; };
    var n = C.n_per_game[G[0].id];
    var set = function (k, v) { document.querySelectorAll('[data-c="' + k + '"]').forEach(function (e) { e.textContent = v; }); };
    set('seeds', C.seeds); set('theta', p1(C.theta)); set('ci', p1(C.lb975) + ' to ' + p1(C.ub975)); set('n', n); set('p', pv(C.gates.C1.signflip_p));
    var bar = $('#c-bar'), lo = C.lb975, hi = C.ub975;
    bar.setAttribute('aria-label', '95% interval ' + p1(lo) + ' to ' + p1(hi) + '; dashed line at 50%');
    bar.querySelector('i').setAttribute('style', 'left:' + (100 * lo) + '%;width:' + (100 * (hi - lo)) + '%');
    bar.querySelector('b').setAttribute('style', 'left:' + (100 * C.theta) + '%');
    var g = C.gates;
    $('#c-gates').innerHTML =
      '<li>' + ok(g.V_rt.passed) + '<span><strong>Validity.</strong> Records replay exactly, every cell valid, ' + g.V_rt.voids + ' void rounds.</span></li>' +
      '<li>' + ok(g.R_RT.passed) + '<span><strong>Release gate.</strong> Not clearly worse than Jev: lower 97.5% bound ' + p1(g.R_RT.lb975) + ' &gt; 35%.</span></li>' +
      '<li>' + ok(g.C1.passed) + '<span><strong>Superiority.</strong> Lower bound ' + p1(g.C1.lb975) + ' &gt; 50% and sign-flip p ' + pv(g.C1.signflip_p) + ' ≤ 0.025: Burst outperforms Jev in real-time head-to-heads over the three games.</span></li>';
    $('#c-same').innerHTML = '<strong>' + esc(C.player) + '</strong> is ' + esc(C.same_as) + ' under its release name: ' + esc(C.same_note.replace(/^The released name of [^:]*: /, '')) + ' Its opponent is Jev only, so this is not a leaderboard.';
    $('#c-games thead').innerHTML = '<tr><th>Game</th><th>Burst outlasted Jev</th><th>Lower 97.5% bound</th><th>Sign-flip p</th><th>Holm level</th><th>Per-game claim</th><th>RMST ≤60 s · Burst / Jev</th></tr>';
    $('#c-games tbody').innerHTML = G.map(function (gm) {
      var x = C.per_game[gm.id];
      return '<tr class="' + (x.passed ? 'nagi' : '') + '"><td class="who">' + esc(gm.name) + '<span class="sub">n = ' + x.n + ' seed indices' + (x.at_wall ? ' · ended at ' + gm.wall.t.toFixed(1) + ' s: Burst ' + x.at_wall.burst + ', Jev ' + x.at_wall.jev : '') + '</span></td>' +
        '<td><span class="big">' + p1(x.W) + '</span></td><td>' + p1(x.lb) + '</td><td>' + pv(x.signflip_p) + '</td><td>' + x.holm_alpha.toFixed(4) + '</td>' +
        '<td>' + (x.passed ? '<b class="pass">significant</b>' : '<b class="fail">not significant</b>') + '</td>' +
        '<td>' + x.rmst.toFixed(1) + ' s / ' + x.rmst_jev.toFixed(1) + ' s</td></tr>';
    }).join('');
    var bg = C.per_game.booster_gauntlet, bgw = G.filter(function (x) { return x.id === 'booster_gauntlet'; })[0];
    if (bg && bg.at_wall && bgw && bgw.wall) {
      $('#c-note').innerHTML += ' Booster’s margin comes from not crashing, not from landing (' + bgw.wall.t.toFixed(1) + ' s is the first hop’s landing deadline). ' + esc(bg.cause || '');
    }
    $('#c-estimand').innerHTML = '<strong>Estimand.</strong> ' + esc(C.estimand);
    $('#c-steps').innerHTML =
      '<li><strong>Release gate (R-RT):</strong> ' + esc(g.R_RT.rule) + '.</li>' +
      '<li><strong>Superiority (C1):</strong> ' + esc(g.C1.rule) + '; tested only after the release gate passed.</li>' +
      '<li><strong>Per game (C2):</strong> ' + esc(C.c2_rule) + '.</li>' +
      '<li><strong>Validity:</strong> ' + esc(g.V_rt.rule) + '.</li>';
    var sc = C.screen_0_9;
    $('#c-screen').innerHTML = '<strong>Why fresh seeds.</strong> On the selection seeds 0–9 the same pairing read ' + p1(sc.vs_jev.theta) + ' (' + esc(sc.label) + '); on fresh seeds it is ' + p1(C.theta) + '. A second real-time run of the same player on seeds 0–9 scored ' + p1(sc.retest_vs_board1.theta) + ' [' + p1(sc.retest_vs_board1.lb975) + ', ' + p1(sc.retest_vs_board1.ub975) + '] against its own Board 1 records, consistent with 50%: that spread is run-to-run noise in real-time play. The drop from the selection seeds is what selection bias plus that noise look like; only the fresh-seed number is the estimate.';
  }

  function latency() {
    $('#lat thead').innerHTML = '<tr><th>Player</th>' + G.map(function (g) { return '<th>' + esc(g.name) + '<br>p50 · fresh · stale · resets</th>'; }).join('') + '<th>3-vs-1</th></tr>';
    $('#lat tbody').innerHTML = D.players.map(function (p) {
      return '<tr class="' + (p.kind === 'nagi' ? 'nagi' : '') + '"><td class="who">' + esc(p.label) + '</td>' + G.map(function (g) {
        var s = p.games[g.id]; return '<td>' + Math.round(s.p50_ms) + ' ms · ' + pct(s.fresh) + ' · ' + s.stale + ' · ' + s.expiry + '</td>';
      }).join('') + '<td>' + (p.inflation_p50 == null ? '—' : p.inflation_p50.toFixed(2) + '×') + '</td></tr>';
    }).join('');
  }

  function domain() {
    $('#domain thead').innerHTML = '<tr><th>Player</th>' + G.map(function (g) { return '<th>' + esc(g.name) + '</th>'; }).join('') + '</tr>';
    $('#domain tbody').innerHTML = D.players.map(function (p) {
      return '<tr><td class="who">' + esc(p.label) + '</td>' + G.map(function (g) {
        var x = p.in_domain[g.id];
        return '<td>' + (p.kind !== 'nagi' ? 'not audited' : x.length ? esc(x.join(', ')) : 'none') + '</td>';
      }).join('') + '</tr>';
    }).join('');
  }

  fetch('v3.json').then(function (r) { if (!r.ok) throw Error('v3.json unavailable'); return r.json(); }).then(function (d) {
    D = d; G = d.games; P = {}; d.players.forEach(function (p) { P[p.id] = p; });
    document.querySelectorAll('[data-meta="board"]').forEach(function (e) { e.textContent = d.meta.board; });
    var sha = $('[data-meta="sha"]'); if (sha) { sha.textContent = d.meta.source_sha256.slice(0, 16) + '…'; sha.title = d.meta.source_sha256; }
    var job = $('[data-meta="job"]'); if (job) job.textContent = d.meta.job;
    var np = $('[data-bind="nplayers"]'); if (np) np.textContent = d.players.length;
    board(); confirmation(); anchors(); survival(); games(); latency(); domain();
  }).catch(function (e) {
    $('#board tbody').innerHTML = '<tr><td colspan="6">The results could not be loaded. All numbers are in <a href="v3.json">v3.json</a>.</td></tr>';
    console.error(e);
  });
})();
