'use strict';
/* Game Arena: Nagi Burst V2 vs V1 vs Jev section. Renders every number from v2.json (built by build/make_v2.py). */
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  var ARMS = ['v2', 'v1', 'jev'];
  var D;

  function num(x, d) { return x == null ? '—' : (+x).toFixed(d); }
  function pv(p) {
    if (p >= 0.001) return p.toFixed(3);
    var e = Math.floor(Math.log10(p)), m = p / Math.pow(10, e);
    return m.toFixed(1) + '×10<sup>' + e + '</sup>';
  }
  function wtl(x) { return x.wins + '–' + x.ties + '–' + x.losses; }
  function label(a) { return D.players[a].label; }
  function pair(g, a, b) { return g.pairs.filter(function (x) { return x.a === a && x.b === b; })[0]; }

  function means() {
    $('#v2-means thead').innerHTML = '<tr><th scope="col">Game · metric</th><th scope="col">n</th>' +
      ARMS.map(function (a) { return '<th scope="col" class="arm-' + a + '">' + esc(label(a)) + '<span class="sub">' + esc(D.players[a].sub) + '</span></th>'; }).join('') + '</tr>';
    $('#v2-means tbody').innerHTML = D.games.map(function (g) {
      return '<tr><td><span class="who">' + esc(g.label) + '</span><span class="sub">' + esc(g.metric) + ' · seeds ' + esc(g.seeds) + '</span></td>' +
        '<td class="num">' + g.n + '</td>' +
        ARMS.map(function (a) {
          var ci = g.ci95[a], land = g.landings ? '<span class="sub">' + g.landings[a] + '/' + g.n + ' landed</span>' : '';
          return '<td class="num arm-' + a + '"><span class="big">' + num(g.means[a], g.decimals) + (g.unit ? ' ' + esc(g.unit) : '') + '</span>' +
            '<span class="ci">[' + num(ci[0], g.decimals) + ', ' + num(ci[1], g.decimals) + ']</span>' + land + '</td>';
        }).join('') + '</tr>';
    }).join('');
  }

  function h2h() {
    var cols = [['v2', 'v1'], ['v2', 'jev'], ['v1', 'jev']];
    $('#v2-h2h thead').innerHTML = '<tr><th scope="col">Game</th>' + cols.map(function (c) {
      var p = pair(D.games[0], c[0], c[1]);
      return '<th scope="col">' + esc(label(c[0])) + ' vs ' + esc(label(c[1])) + '<span class="sub">' + (p.claim === 'gate A' ? 'preregistered gate A' : 'descriptive, no claim') + '</span></th>';
    }).join('') + '</tr>';
    var rows = D.games.map(function (g) {
      return '<tr><td class="who">' + esc(g.label) + '</td>' + cols.map(function (c) {
        var x = pair(g, c[0], c[1]);
        var tag = x.claim === 'gate A' ? '<span class="tag ' + (x.result === 'PASS' ? 'pass' : 'fail') + '">gate A ' + esc(x.result) + '</span>' : '<span class="tag desc">descriptive</span>';
        return '<td class="num"><span class="big">' + Math.round(100 * x.W) + '%</span><span class="ci">' + wtl(x) + ' (W–T–L)</span>' +
          '<span class="ci">t lower 97.5% ' + num(x.t_lb, 3) + ' · p ' + pv(x.p) + '</span>' + tag + '</td>';
      }).join('') + '</tr>';
    });
    var o = D.overall;
    rows.push('<tr class="all"><td class="who">All three games<span class="sub">mean of the per-game W</span></td>' + cols.map(function (c) {
      var x = o[c[0] + '_vs_' + c[1]];
      return '<td class="num"><span class="big">' + Math.round(100 * x.theta) + '%</span><span class="ci">' + wtl(x) + ' over ' + x.n + ' seed-games</span><span class="ci">lower 97.5% ' + num(x.lb97_5, 3) + '</span></td>';
    }).join('') + '</tr>');
    $('#v2-h2h tbody').innerHTML = rows.join('');
  }

  function claims() {
    var pass = D.games.filter(function (g) { return pair(g, 'v2', 'v1').result === 'PASS'; }).length;
    $('#v2-claim-v1').innerHTML = esc(D.claim_rule.v2_vs_v1) + ' Result: <strong>' + pass + ' of ' + D.games.length + ' games PASS</strong> (' +
      D.games.map(function (g) { var x = pair(g, 'v2', 'v1'); return esc(g.label) + ' ' + wtl(x); }).join(', ') + ').';
    $('#v2-claim-jev').innerHTML = esc(D.claim_rule.jev) + ' Per game, V2 scored higher than Jev on ' +
      D.games.map(function (g) { var x = pair(g, 'v2', 'jev'); return x.wins + ' of ' + x.n + ' seeds in ' + esc(g.label) + (x.ties ? ' (' + x.ties + ' tie)' : ''); }).join(', ') + '.';
    var notes = D.notes.slice();
    var jt = D.games.map(function (g) { return esc(g.label) + ' ' + (100 * g.jev_profile.one_tick_share).toFixed(1) + '%'; }).join(', ');
    notes.splice(2, 0, 'Jev’s replies landed within one ' + D.meta.tick_ms + ' ms tick on ' + jt + ' of live requests (median latency ' +
      D.games.map(function (g) { return Math.round(g.jev_profile.latency_p50_ms) + ' ms'; }).join(' / ') + '). Speed is part of a live round, so this is part of Jev’s result, not an adjustment to it.');
    $('#v2-notes').innerHTML = notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('');
  }

  function pairing() {
    $('#v2-pair thead').innerHTML = '<tr><th>Game</th><th>Verdict</th><th>Same index + seed</th><th>Records sha256-pinned</th><th>Score recomputed equal</th><th>State-exact replay here</th><th>Exact replay in venue</th><th>Prompts regenerated (mismatch)</th></tr>';
    $('#v2-pair tbody').innerHTML = D.games.map(function (g) {
      var p = g.pairing_detail;
      return '<tr><td class="who">' + esc(g.label) + '</td><td><strong>' + esc(g.pairing_jev) + '</strong></td><td>' + p.same_index_and_seed + '/' + g.n + '</td><td>' + p.record_sha256_pinned + '/' + g.n +
        '</td><td>' + p.score_recomputed_equal + '/' + g.n + '</td><td>' + p.replay_exact_local_image + '/' + g.n + '</td><td>' + (p.replay_exact_in_venue ? 'yes' : 'no') +
        '</td><td>' + p.prompts_regenerated + ' (' + p.prompt_mismatch + ')</td></tr>';
    }).join('');
    $('#v2-pair-note').innerHTML = 'The Jev records were pinned in the V2 preregistration before V2 played. The same check the release ran on the V1 records (sha256 pin, rules id, frozen seed, exact replay, every prompt regenerated, score recomputed) was run on them in the release’s Linux image ' +
      '<code>' + esc(D.meta.jev_pair_check_image.tag) + '</code>. ' + esc(D.meta.jev_engine_identity) + '. Paired is not the same as a claim: the preregistration fixed the Jev comparison as descriptive before any data, and that is kept.';
  }

  function seeds() {
    $('#v2-seeds').innerHTML = D.games.map(function (g) {
      return '<h4 class="v2-h4">' + esc(g.label) + ' · ' + esc(g.metric) + '</h4><div class="table-wrap"><table class="v2-seed"><thead><tr><th>Index</th><th>Seed</th>' +
        ARMS.map(function (a) { return '<th>' + esc(label(a)) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        g.per_seed.map(function (s) {
          var best = Math.max(s.v2, s.v1, s.jev == null ? -1 : s.jev);
          return '<tr><td>' + s.index + '</td><td><code>' + s.seed + '</code></td>' + ARMS.map(function (a) {
            return '<td class="num' + (s[a] === best ? ' top' : '') + '">' + num(s[a], g.decimals) + '</td>';
          }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>';
    }).join('');
  }

  function clips() {
    $('#v2-clips').innerHTML = D.games.map(function (g) {
      var vid = g.video ? '<video controls preload="none" playsinline' + (g.poster ? ' poster="' + esc(g.poster) + '"' : '') + ' src="' + esc(g.video) + '" aria-label="' + esc(g.label) + ' replay, seed index ' + esc(g.video_seed_index) + ', three seats: ' + ARMS.map(label).map(esc).join(', ') + '"></video>' +
        '<figcaption>' + esc(g.label) + ' · seed index ' + esc(g.video_seed_index) + ' · ' + ARMS.map(function (a) { var s = g.per_seed.filter(function (r) { return r.index === g.video_seed_index; })[0]; return esc(label(a)) + ' ' + num(s[a], g.decimals); }).join(' · ') + ' · real time, slow-motion only at eliminations · seed picked by a fixed rule (median V2 − Jev margin, <a href="https://github.com/nagisanzenin/nagi/blob/main/bench/burst_v2/receipts/arena_v2_videos.json">receipt</a>)</figcaption>' : '';
      return '<figure class="v2-clip">' + vid + '<p class="small"><a href="' + esc(g.replay) + '">' + esc(g.label) + ': V2 replay records, all ' + g.n + ' seeds ↗</a></p></figure>';
    }).join('');
    var s = D.meta.sources_sha256;
    $('#v2-src').innerHTML = 'Generated by <code>' + esc(D.meta.generated_by) + '</code> from <code>bench/burst_v2/receipts/</code>: ' +
      Object.keys(s).map(function (k) { return '<a href="https://github.com/nagisanzenin/nagi/blob/main/bench/burst_v2/receipts/' + esc(k) + '">' + esc(k) + '</a> <code>' + s[k].slice(0, 12) + '…</code>'; }).join(' · ') +
      '. V2 replay pack: ' + D.meta.replay_pack.exact + '/' + D.meta.replay_pack.replayed + ' rounds replay exactly from the recorded controls. Page data: <a href="v2.json">v2.json</a>.';
  }

  function bind() {
    var m = { seeds: D.games.map(function (g) { return g.label + ' ' + g.seeds; }).join(' · '), v2sub: D.players.v2.sub };
    document.querySelectorAll('[data-v2]').forEach(function (e) { var k = e.getAttribute('data-v2'); if (k in m) e.textContent = m[k]; });
  }

  fetch('v2.json').then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
    D = d; bind(); means(); h2h(); claims(); pairing(); seeds(); clips();
  }).catch(function (e) {
    var t = $('#v2-means tbody'); if (t) t.innerHTML = '<tr><td>Could not load <a href="v2.json">v2.json</a> (' + esc(e.message) + ').</td></tr>';
  });
})();
