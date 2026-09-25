(function () {
  'use strict';
  var GAMES = [['rotorwash', 'Rotorwash'], ['lightcycle', 'Lightcycle'], ['stack', 'Stack']];
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === 'style') n.style.cssText = attrs[k]; else n.setAttribute(k, attrs[k]);
    }
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  function bind(key, val) {
    document.querySelectorAll('[data-bind="' + key + '"]').forEach(function (n) { n.textContent = val; });
  }
  function fmt(n) { return n.toLocaleString('en-US'); }
  function ms(m) {
    var a = Math.round(m.p50_ms_min), b = Math.round(m.p50_ms_max);
    return a === b ? a + ' ms' : a + '–' + b + ' ms';
  }

  /* ---------- leaderboard ---------- */
  function board(id, run, max) {
    var ol = document.getElementById(id);
    ol.innerHTML = '';
    var prev = null, rank = 0;
    run.models.forEach(function (m, i) {
      if (!prev || prev.points !== m.points) rank = i + 1;
      prev = m;
      var li = el('li', {'class': 'row' + (i === 0 ? ' first' : ''), style: '--c:' + m.color});
      var segs = GAMES.map(function (g) {
        var p = m.games[g[0]].points;
        return p ? '<i style="width:' + (p / max.max_points * 100).toFixed(2) + '%" title="' + g[1] + ' ' + p + '"></i>' : '';
      }).join('');
      var per = GAMES.map(function (g) { return '<span>' + g[1] + ' <em>' + m.games[g[0]].points + '</em></span>'; }).join('');
      li.innerHTML =
        '<div class="row-top"><span class="rank">' + rank + '</span>' +
        '<div class="who"><b>' + esc(m.name) + '</b><small>' + esc(m.sub) + '</small></div>' +
        '<div class="pts"><b>' + m.points + '</b><small>/' + max.max_points + '</small></div></div>' +
        '<div class="bar90" role="img" aria-label="' + m.points + ' of ' + max.max_points + ' points">' + segs + '</div>' +
        '<div class="meta"><span>Round wins <em>' + m.wins + '/' + max.max_wins + '</em></span>' + per +
        '<span>P50 <em>' + ms(m) + '</em></span></div>';
      ol.appendChild(li);
    });
  }

  /* ---------- per-game tables ---------- */
  function gameTable(id, run, g, withSurvival) {
    var t = document.getElementById(id);
    var rows = run.models.slice().sort(function (a, b) {
      var x = a.games[g], y = b.games[g];
      return (y.points - x.points) || (y.wins - x.wins) || ((y.survival_median_s || 0) - (x.survival_median_s || 0));
    });
    var head = '<thead><tr><th scope="col">Model</th><th scope="col">Pts</th><th scope="col">Wins<span class="u">/10</span></th>' +
      (withSurvival ? '<th scope="col">Airborne<span class="u"> s</span><span class="sr-only"> (median)</span></th>' : '') +
      '<th scope="col">P50<span class="u"> ms</span></th></tr></thead>';
    var body = rows.map(function (m, i) {
      var r = m.games[g];
      return '<tr' + (i === 0 ? ' class="lead"' : '') + ' style="--c:' + m.color + '"><td><i></i>' + esc(m.name).replace(/^Nagi-/, '<span class="pre">Nagi-</span>') + '</td>' +
        '<td class="pt">' + r.points + '</td><td>' + r.wins + '</td>' +
        (withSurvival ? '<td>' + r.survival_median_s.toFixed(1) + '</td>' : '') +
        '<td>' + Math.round(r.p50_ms) + '</td></tr>';
    }).join('');
    t.insertAdjacentHTML('beforeend', head + '<tbody>' + body + '</tbody>');
  }

  /* ---------- rotorwash survival chart ---------- */
  function survivalChart(run) {
    var fig = document.getElementById('survival-chart');
    var e = run.models.filter(function (m) { return m.name === 'Nagi-ENORMOUS'; })[0];
    var j = run.models.filter(function (m) { return m.name === 'Jev'; })[0];
    var se = e.games.rotorwash.survival_s, sj = j.games.rotorwash.survival_s;
    var maxV = Math.ceil(Math.max.apply(null, se.concat(sj)) / 20) * 20;
    var W = Math.round(Math.max(300, Math.min(680, fig.clientWidth || 340))), H = W > 500 ? 190 : 150, L = 26, B = 18, T = 6, gw = (W - L) / se.length, bw = Math.min(16, gw * 0.3);
    var s = '<svg viewBox="0 0 ' + W + ' ' + (H + B) + '" role="img" aria-label="Seconds airborne in each of 10 rounds. ENORMOUS: ' +
      se.join(', ') + '. Jev: ' + sj.join(', ') + '.">';
    for (var v = 0; v <= maxV; v += 20) {
      var y = T + (H - T) * (1 - v / maxV);
      s += '<line class="grid" x1="' + L + '" x2="' + W + '" y1="' + y + '" y2="' + y + '"/>' +
        '<text class="ax" x="' + (L - 6) + '" y="' + (y + 3) + '" text-anchor="end">' + v + '</text>';
    }
    se.forEach(function (_, i) {
      var cx = L + gw * i + gw / 2;
      [[se[i], e.color, -bw - 1], [sj[i], j.color, 1]].forEach(function (d) {
        var h = (H - T) * d[0] / maxV;
        s += '<rect x="' + (cx + d[2]).toFixed(1) + '" y="' + (H - h).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) +
          '" rx="2" fill="' + d[1] + '"><title>Round ' + (i + 1) + ': ' + d[0] + ' s</title></rect>';
      });
      s += '<text class="ax" x="' + cx + '" y="' + (H + 13) + '" text-anchor="middle">' + (i + 1) + '</text>';
    });
    s += '</svg>';
    var cap = fig.querySelector('figcaption');
    cap.innerHTML = 'Seconds airborne, rounds 1–10 <span class="k" style="--c:' + e.color + '">ENORMOUS</span><span class="k" style="--c:' + j.color + '">Jev</span>';
    fig.insertAdjacentHTML('beforeend', s);
  }

  function endings(run) {
    var names = {ceiling: 'ceiling', terrain: 'terrain', tail_strike: 'tail strike', rotor_stall: 'rotor stall'};
    var parts = run.models.map(function (m) {
      var c = m.games.rotorwash.crashes || {};
      return esc(m.name) + ': ' + Object.keys(c).map(function (k) { return c[k] + ' ' + (names[k] || k); }).join(', ');
    });
    var others = run.models.filter(function (m) { return m.name === 'OpenJev' || m.name === 'Laya'; })
      .map(function (m) { return m.games.rotorwash.survival_max_s; });
    document.getElementById('rw-endings').innerHTML = 'How rounds ended. ' + parts.join(' · ') +
      '. OpenJev and Laya never flew longer than ' + Math.max.apply(null, others).toFixed(1) + ' s. No model completed a sling-load delivery.';
  }

  function render(d) {
    var V = d.vendors, N = d.nagi_lines;
    var find = function (run, n) { return run.models.filter(function (m) { return m.name === n; })[0]; };
    var e = find(V, 'Nagi-ENORMOUS'), j = find(V, 'Jev');
    bind('v.e.points', e.points); bind('v.e.wins', e.wins);
    bind('rw.e.med', e.games.rotorwash.survival_median_s.toFixed(1));
    bind('rw.j.med', j.games.rotorwash.survival_median_s.toFixed(1));
    bind('rw.sw', V.paired_vs_enormous.rotorwash.Jev.survival_w_l[0]);
    bind('lc.e.wins', e.games.lightcycle.wins);
    bind('st.e.wins', e.games.stack.wins);
    bind('sha', d.records.sha256);

    var total = 0;
    [V, N].forEach(function (run) { run.models.forEach(function (m) { total += m.replies.ok + m.replies.late + m.replies.invalid + m.replies.error; }); });
    bind('replies', fmt(total));

    board('board-vendors', V, d.scoring);
    board('board-nagi', N, d.scoring);
    gameTable('t-rotorwash', V, 'rotorwash', true);
    gameTable('t-lightcycle', V, 'lightcycle', false);
    gameTable('t-stack', V, 'stack', false);
    survivalChart(V);
    endings(V);

    var asc = N.models.slice().sort(function (a, b) { return a.points - b.points; });
    var ne = find(N, 'Nagi-ENORMOUS');
    var otherMed = N.models.filter(function (m) { return m !== ne; }).map(function (m) { return m.games.rotorwash.survival_median_s; });
    document.getElementById('family-line').innerHTML = 'Score rises with the model line: ' +
      asc.map(function (m) { return '<strong style="color:' + m.color + '">' + m.points + '</strong>'; }).join(' → ') +
      ' points. The biggest gap is closed-loop helicopter control: ENORMOUS won ' + ne.games.rotorwash.wins +
      ' of 10 Rotorwash rounds, median ' + ne.games.rotorwash.survival_median_s.toFixed(1) + ' s airborne vs ' +
      Math.min.apply(null, otherMed).toFixed(1) + '–' + Math.max.apply(null, otherMed).toFixed(1) + ' s for the other lines.';
  }

  fetch('data.json').then(function (r) { return r.json(); }).then(render).catch(function () {
    document.querySelectorAll('.board .loading').forEach(function (n) {
      n.innerHTML = 'Could not load <a href="data.json">data.json</a>. The tables are also in <a href="https://github.com/nagisanzenin/nagi/tree/main/bench/arena_live">bench/arena_live</a>.';
    });
  });


  /* ---------- lab notes (rounds.json: derived per-round data) ---------- */
  var GNAME = {rotorwash: 'Rotorwash', lightcycle: 'Lightcycle Royale', stack: 'Stack Attack'};
  function pfmt(p) { return p < 0.001 ? '<0.001' : p >= 0.9995 ? '1' : p.toFixed(3); }
  function outcome(g, x) {
    if (g === 'rotorwash') return x.score_m + ' m, ' + x.airborne_s + ' s airborne, ended: ' + x.end.replace('_', ' ') +
      (x.vortex_ring ? ', vortex ring ×' + x.vortex_ring : '') + (x.rpm_droop ? ', RPM droop ×' + x.rpm_droop : '');
    if (g === 'lightcycle') return (x.out_s == null ? 'survived' : 'out at ' + x.out_s + ' s (' + x.end + ')') + ', boosts ' + x.boosts + ', near misses ' + x.near_misses;
    return (x.out_s == null ? 'survived' : 'topped out at ' + x.out_s + ' s') + ', ' + x.pieces + ' pieces, ' + x.lines + ' lines, ' + x.sent + ' rows sent';
  }
  function entropy(counts) {
    var ks = Object.keys(counts), n = 0, h = 0;
    ks.forEach(function (k) { n += counts[k]; });
    ks.forEach(function (k) { var p = counts[k] / n; if (p > 0) h -= p * Math.log(p); });
    return {n: n, h: h};
  }
  var OPTS = {
    collective: ['down2', 'down1', 'hold', 'up1', 'up2'], cyclic: ['aft2', 'aft1', 'center', 'fwd1', 'fwd2'],
    winch: ['up', 'hold', 'down'], move: ['straight', 'left', 'right', 'boost_straight', 'boost_left', 'boost_right'],
    rotation: ['rot0', 'rotR', 'rot2', 'rotL'], column: ['c0', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8', 'c9']
  };
  var KEYS = {rotorwash: ['collective', 'cyclic', 'winch'], lightcycle: ['move'], stack: ['rotation', 'column']};
  var PAL = ['#5BA8F5', '#7CE0C3', '#A3D65C', '#F2D25C', '#F08A4B', '#E0569B', '#B58CFF', '#9AA5B8', '#4FC3F7', '#FFB4A2'];
  function ramp(i) { return PAL[i % PAL.length]; }

  function labRender(R, D, lu) {
    var colors = {}, order = D[lu].models.map(function (m) { colors[m.name] = m.color; return m.name; });
    var L = R[lu];
    // heatmap
    var heat = document.getElementById('lab-heat'), hs = '';
    GAMES.forEach(function (gg) {
      var g = gg[0], rs = L[g].rounds;
      hs += '<div><h4>' + GNAME[g] + '</h4><div class="scroll"><table><thead><tr><th></th>' +
        rs.map(function (r) { return '<th title="seed ' + r.seed + '">' + r.round + '</th>'; }).join('') + '<th>pts</th></tr></thead><tbody>';
      order.forEach(function (m) {
        var tot = 0;
        hs += '<tr><th class="m" style="--c:' + colors[m] + '"><i></i>' + esc(m.replace(/^Nagi-/, '')) + '</th>';
        rs.forEach(function (r) {
          var x = r.players[m]; tot += x.points;
          var a = [1, .62, .34, .12][x.place - 1];
          hs += '<td style="background:color-mix(in srgb,' + colors[m] + ' ' + Math.round(a * 100) + '%, transparent)" title="' +
            esc(m + ' · round ' + r.round + ' · place ' + x.place + ' · ' + outcome(g, x)) + '">' + x.place + '</td>';
        });
        hs += '<td class="sum">' + tot + '</td></tr>';
      });
      hs += '</tbody></table></div></div>';
    });
    heat.innerHTML = hs;
    // tests
    var t = '<thead><tr><th scope="col">Game</th><th scope="col">ENORMOUS vs</th><th scope="col">W–L–T</th><th scope="col">sign p</th><th scope="col">Holm p</th></tr></thead><tbody>';
    GAMES.forEach(function (gg) {
      var g = gg[0], P = L[g].paired_vs_enormous;
      order.forEach(function (m) {
        var x = P[m]; if (!x) return;
        var sig = x.p_holm < 0.05;
        t += '<tr style="--c:' + colors[m] + '"><td>' + GNAME[g] + '</td><td><i></i>' + esc(m) + '</td><td>' + x.w + '–' + x.l + '–' + x.t +
          '</td><td>' + pfmt(x.p) + '</td><td class="pt"' + (sig ? ' style="color:var(--teal)"' : '') + '>' + pfmt(x.p_holm) + '</td></tr>';
        if (x.airborne) t += '<tr style="--c:' + colors[m] + '"><td>↳ airborne time</td><td><i></i>' + esc(m) + '</td><td>' + x.airborne.w + '–' + x.airborne.l +
          '</td><td>' + pfmt(x.airborne.p) + '</td><td>—</td></tr>';
      });
    });
    document.getElementById('lab-tests').innerHTML = t + '</tbody>';
    // latency histograms (pooled over games) + table
    var edges = R.lat_edges_ms, nb = edges.length + 1, fig = document.getElementById('lab-lat'), W = 600, H = 34, s = '';
    order.forEach(function (m) {
      var hist = new Array(nb).fill(0);
      GAMES.forEach(function (gg) { L[gg[0]].models[m].lat_hist.forEach(function (c, i) { hist[i] += c; }); });
      var mx = Math.max.apply(null, hist), bw = W / nb;
      var bars = hist.map(function (c, i) {
        var hh = c ? Math.max(1.5, H * c / mx) : 0;
        return '<rect x="' + (i * bw + 1).toFixed(1) + '" y="' + (H - hh).toFixed(1) + '" width="' + (bw - 2).toFixed(1) + '" height="' + hh.toFixed(1) + '" rx="1.5" fill="' + colors[m] + '"><title>' +
          (i === 0 ? '< ' + edges[0] : i === nb - 1 ? '≥ ' + edges[nb - 2] : edges[i - 1] + '–' + edges[i]) + ' ms: ' + c + '</title></rect>';
      }).join('');
      s += '<div class="lat-row"><b style="color:' + colors[m] + '">' + esc(m.replace(/^Nagi-/, '')) + '</b><svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" style="height:' + H + 'px" role="img" aria-label="' + esc(m) + ' latency histogram">' + bars + '</svg></div>';
    });
    var ticks = [10, 20, 40, 80, 160, 320, 640, 1280].map(function (v) {
      var i = edges.indexOf(v); return i < 0 ? '' : '<span style="left:' + ((i + 1) / nb * 100).toFixed(1) + '%">' + (v >= 1000 ? v / 1000 + ' s' : v) + '</span>';
    }).join('');
    fig.innerHTML = s + '<div class="lat-row"><span></span><div class="lat-ax">' + ticks + '</div></div>';
    var lt = '<thead><tr><th scope="col">Model</th><th scope="col">Game</th><th scope="col">n</th><th scope="col">P50</th><th scope="col">P90</th><th scope="col">P99</th><th scope="col">max<span class="u"> ms</span></th></tr></thead><tbody>';
    order.forEach(function (m) {
      GAMES.forEach(function (gg, k) {
        var x = L[gg[0]].models[m];
        lt += '<tr style="--c:' + colors[m] + '"><td>' + (k === 0 ? '<i></i>' + esc(m) : '') + '</td><td style="font-family:var(--sans)">' + gg[1] + '</td><td>' + fmt(x.n_decisions) + '</td><td class="pt">' +
          x.lat_p50 + '</td><td>' + x.lat_p90 + '</td><td>' + x.lat_p99 + '</td><td>' + x.lat_max + '</td></tr>';
      });
    });
    document.getElementById('lab-lat-t').innerHTML = lt + '</tbody>';
    // policy fingerprint
    var ps = '';
    GAMES.forEach(function (gg) {
      KEYS[gg[0]].forEach(function (key) {
        var opts = OPTS[key];
        ps += '<div><h4>' + GNAME[gg[0]] + ' · ' + key + '</h4><div class="pol-legend">' +
          opts.map(function (o, i) { return '<span style="--c:' + ramp(i, opts.length) + '">' + o + '</span>'; }).join('') + '</div>';
        order.forEach(function (m) {
          var c = L[gg[0]].models[m].actions[key] || {}, e = entropy(c);
          var hn = e.n ? e.h / Math.log(opts.length) : 0;
          ps += '<div class="pol-row"><b style="color:' + colors[m] + '">' + esc(m.replace(/^Nagi-/, '')) + '</b><div class="pol-bar">' +
            opts.map(function (o, i) {
              var v = c[o] || 0; return v ? '<i style="width:' + (v / e.n * 100).toFixed(2) + '%;background:' + ramp(i, opts.length) + '" title="' + o + ': ' + v + ' (' + (v / e.n * 100).toFixed(1) + '%)"></i>' : '';
            }).join('') + '</div><em' + (hn < 0.005 ? ' class="zero"' : '') + '>H ' + hn.toFixed(2) + '</em></div>';
        });
        ps += '</div>';
      });
    });
    document.getElementById('lab-pol').innerHTML = '<div class="pol">' + ps + '</div>';
  }

  Promise.all([fetch('rounds.json').then(function (r) { return r.json(); }), fetch('data.json').then(function (r) { return r.json(); })])
    .then(function (a) {
      var R = a[0], D = a[1], btns = document.querySelectorAll('.lab-tabs button');
      btns.forEach(function (b) {
        b.addEventListener('click', function () {
          btns.forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
          labRender(R, D, b.dataset.lu);
        });
      });
      labRender(R, D, 'vendors');
    }).catch(function () {
      document.getElementById('lab-heat').innerHTML = '<p class="note">Could not load <a href="rounds.json">rounds.json</a>.</p>';
    });

  // mechanism specs: open on wide screens, collapsed on phones
  if (window.innerWidth < 700) document.querySelectorAll('details.spec').forEach(function (d) { d.open = false; });

  /* ---------- media ---------- */
  var checked = {};
  function exists(url) {
    if (!(url in checked)) {
      checked[url] = fetch(url, {method: 'HEAD'}).then(function (r) { return r.ok; }).catch(function () { return false; });
    }
    return checked[url];
  }
  function srcOf(v) { var s = v.querySelector('source'); return s ? s.getAttribute('src') : v.getAttribute('src'); }
  function prepare(phone) {
    var v = phone.querySelector('video');
    var url = srcOf(v);
    return exists(url).then(function (ok) {
      if (srcOf(v) !== url) return ok;        // tab switched meanwhile
      phone.classList.toggle('missing', !ok);
      if (ok && v.dataset.poster && !v.getAttribute('poster')) v.setAttribute('poster', v.dataset.poster);
      return ok;
    });
  }
  document.querySelectorAll('.phone video').forEach(function (v) {
    v.addEventListener('error', function () { v.closest('.phone').classList.add('missing'); }, true);
    var s = v.querySelector('source');
    if (s) s.addEventListener('error', function () { v.closest('.phone').classList.add('missing'); });
    // one game video at a time (the teaser is separate)
    v.addEventListener('play', function () {
      if (v.id === 'teaser') return;
      document.querySelectorAll('.phone.autoplay video').forEach(function (o) { if (o !== v) autoPause(o); });
    });
  });

  var lazy = [].slice.call(document.querySelectorAll('.phone:not([data-media="teaser"])'));
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (ents) {
      ents.forEach(function (en) { if (en.isIntersecting) { io.unobserve(en.target); prepare(en.target); } });
    }, {rootMargin: '600px 0px'});
    lazy.forEach(function (p) { io.observe(p); });
  } else lazy.forEach(prepare);

  /* game videos: play muted when scrolled into view, pause when scrolled away.
     A viewer who pauses by hand keeps it paused; our own pauses set v._auto. */
  function autoPause(v) { if (!v.paused) { v._auto = true; v.pause(); } }
  function inView(en) {
    return en.isIntersecting && (en.intersectionRatio >= 0.5 || en.intersectionRect.height >= innerHeight * 0.5);
  }
  if (!reduceMotion && 'IntersectionObserver' in window) {
    var auto = new IntersectionObserver(function (ents) {
      ents.forEach(function (en) {
        var p = en.target, v = p.querySelector('video');
        if (inView(en)) {
          prepare(p).then(function (ok) { if (ok && !v._userPaused) v.play().catch(function () {}); });
        } else autoPause(v);
      });
    }, {threshold: [0, 0.25, 0.5, 0.75]});
    document.querySelectorAll('.phone.autoplay').forEach(function (p) {
      var v = p.querySelector('video');
      auto.observe(p);
      v.addEventListener('pause', function () {
        if (v._auto) { v._auto = false; return; }
        if (!v.ended && document.visibilityState === 'visible') v._userPaused = true;
      });
      v.addEventListener('play', function () { v._userPaused = false; });
    });
  }

  /* hero teaser: autoplay only when motion is welcome, and only while on screen */
  var teaser = document.getElementById('teaser');
  var tPhone = teaser.closest('.phone');
  var toggle = tPhone.querySelector('.motion-toggle');
  var userPaused = reduceMotion;
  function setToggle() {
    var playing = !teaser.paused;
    toggle.textContent = playing ? '❚❚' : '▶';
    toggle.setAttribute('aria-label', playing ? 'Pause teaser' : 'Play teaser');
  }
  prepare(tPhone).then(function (ok) {
    if (!ok) return;
    toggle.hidden = false;
    teaser.addEventListener('play', setToggle);
    teaser.addEventListener('pause', setToggle);
    toggle.addEventListener('click', function () {
      if (teaser.paused) { userPaused = false; teaser.play().catch(function () {}); }
      else { userPaused = true; teaser.pause(); }
    });
    if (!reduceMotion) teaser.play().catch(function () {});
    setToggle();
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (ents) {
        if (userPaused) return;
        if (ents[0].isIntersecting) teaser.play().catch(function () {}); else teaser.pause();
      }).observe(tPhone);
    }
  });

  /* Players with three parts: pick one game, or "All 3" plays them back to back */
  var PARTS = [['rotorwash', 'Rotorwash'], ['lightcycle', 'Lightcycle Royale'], ['stack', 'Stack Attack']];
  document.querySelectorAll('.player').forEach(function (fig) {
    var prefix = fig.dataset.prefix, label = fig.dataset.label;
    var phone = fig.querySelector('.phone'), v = phone.querySelector('video'), src = v.querySelector('source');
    var cap = fig.querySelector('.now'), btns = fig.querySelectorAll('.tabs button');
    var idx = 0, all = fig.dataset.mode === 'all';
    function update() {
      btns.forEach(function (b) {
        var isAll = b.hasAttribute('data-all');
        b.setAttribute('aria-pressed', String(isAll ? all : (!all && +b.dataset.i === idx)));
        b.classList.toggle('cur', all && !isAll && +b.dataset.i === idx);
      });
      cap.textContent = all
        ? 'Part ' + (idx + 1) + ' of 3 · ' + PARTS[idx][1] + ' · plays on automatically'
        : PARTS[idx][1] + ' · full rounds, with sound';
    }
    function load(k, autoplay) {
      idx = k;
      var n = prefix + '_' + PARTS[k][0];
      autoPause(v);
      src.setAttribute('src', 'media/' + n + '.mp4');
      v.removeAttribute('poster');
      v.dataset.poster = 'media/' + n + '.jpg';
      v.setAttribute('aria-label', PARTS[k][1] + ': ' + label);
      phone.dataset.media = n;
      v.load();
      update();
      // call play() inside the click itself (iOS needs the gesture); a missing file shows the placeholder
      if (autoplay) v.play().catch(function () {});
      prepare(phone);
    }
    v.addEventListener('ended', function () { if (all && idx < PARTS.length - 1) load(idx + 1, true); });
    btns.forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.hasAttribute('data-all')) { all = true; load(0, true); }
        else { all = false; load(+b.dataset.i, false); }
      });
    });
    update();
  });
})();
