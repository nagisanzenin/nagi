'use strict';
// Burst page: survival chart (share of rounds still alive vs time) from data.json. No dependencies.
// Rounds are uncensored in Board 1 (every round ended before the 60 s cap); a censored round (death_s >= cap)
// is kept in the risk set to the end, which is the Kaplan-Meier estimate without censoring before the cap.
(function () {
  const root = document.getElementById('km');
  if (!root) return;
  const SERIES = { // colour follows the entity, fixed order; highlighted: Burst, K-call, Jev
    burst: { c: '#F5E642', w: 3, d: '' }, burst_proto: { c: '#F5E642', w: 3, d: '' },
    kcall: { c: '#36D988', w: 2.5, d: '' }, jev: { c: '#FF4D94', w: 2.5, d: '' },
    enormous_cl: { c: '#B7B4AC', w: 1.5, d: '6 4' }, enormous_v1: { c: '#8F8C85', w: 1.5, d: '2 4' },
    semif_4b: { c: '#6E6C67', w: 1.5, d: '10 4 2 4' }
  };
  const ORDER = ['burst', 'burst_proto', 'kcall', 'jev', 'enormous_cl', 'enormous_v1', 'semif_4b'];
  const NS = 'http://www.w3.org/2000/svg';
  let data, set = 'board1', game = 'rotorwash_ramp';

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function curve(deaths) { // step points [t, share alive after t]
    const n = deaths.length, ts = [...deaths].sort((a, b) => a - b), pts = [[0, 1]];
    let alive = n;
    for (let i = 0; i < n;) {
      const t = ts[i]; let k = 0;
      while (i < n && ts[i] === t) { k++; i++; }
      alive -= k; pts.push([t, alive / n]);
    }
    return pts;
  }
  function aliveAt(pts, t) { let v = 1; for (const [x, y] of pts) { if (x <= t) v = y; else break; } return v; }

  function draw() {
    const ds = data[set]; root.replaceChildren();
    const legend = document.getElementById('km-legend'); legend.replaceChildren();
    if (!ds) { root.innerHTML = '<p class="pending"><b>Pending</b>Filled from the confirmation run after the release gates.</p>'; return; }
    const deaths = ds.death_s[game], cap = ds.cap_s || 60;
    const players = ORDER.filter(p => deaths[p]);
    const maxT = Math.min(cap, Math.ceil((Math.max(...players.flatMap(p => deaths[p])) + 4) / 10) * 10);
    const W = Math.max(300, Math.min(960, root.clientWidth || 760)), H = W < 520 ? 250 : 330, L = 46, R = 12, T = 14, B = 44; // viewBox = CSS px, so text stays 12 px
    const x = t => L + (W - L - R) * t / maxT, y = v => T + (H - T - B) * (1 - v);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Share of rounds still alive vs time, ${data.games[game].label}` }, root);
    for (let v = 0; v <= 1.0001; v += 0.25) {
      el('line', { class: 'gl', x1: L, x2: W - R, y1: y(v), y2: y(v) }, svg);
      el('text', { x: L - 8, y: y(v) + 4, 'text-anchor': 'end' }, svg).textContent = Math.round(v * 100) + '%';
    }
    for (let t = 0; t <= maxT; t += 10) {
      el('line', { class: 'ax', x1: x(t), x2: x(t), y1: H - B, y2: H - B + 5 }, svg);
      el('text', { x: x(t), y: H - B + 20, 'text-anchor': t === 0 ? 'start' : t + 10 > maxT ? 'end' : 'middle' }, svg).textContent = t + ' s';
    }
    el('line', { class: 'ax', x1: L, x2: W - R, y1: H - B, y2: H - B }, svg);
    el('text', { x: W - R, y: H - 6, 'text-anchor': 'end' }, svg).textContent = 'time survived →';
    const curves = {};
    for (const p of players.slice().reverse()) { // highlighted series drawn last (on top)
      const pts = curves[p] = curve(deaths[p]), st = SERIES[p] || SERIES.semif_4b;
      let d = `M${x(0)},${y(1)}`, prev = 1;
      for (const [t, v] of pts.slice(1)) { d += `H${x(t)}`; if (v !== prev) d += `V${y(v)}`; prev = v; }
      d += `H${x(maxT)}`;
      el('path', { d, fill: 'none', stroke: '#111114', 'stroke-width': st.w + 2, 'stroke-linejoin': 'round' }, svg); // surface ring
      el('path', { d, fill: 'none', stroke: st.c, 'stroke-width': st.w, 'stroke-dasharray': st.d, 'stroke-linejoin': 'round' }, svg);
    }
    for (const p of players) {
      const li = document.createElement('li'), sw = document.createElement('i'), st = SERIES[p] || SERIES.semif_4b;
      sw.style.borderTopColor = st.c; if (st.d) sw.className = 'd';
      li.append(sw, document.createTextNode(data.players[p] ? data.players[p].label : p)); legend.append(li);
    }
    // hover / touch crosshair
    const cross = el('line', { x1: 0, x2: 0, y1: T, y2: H - B, stroke: '#F3EEDB', 'stroke-width': 1, opacity: 0 }, svg);
    const tip = document.createElement('div'); tip.className = 'tip'; root.append(tip);
    const hit = el('rect', { x: L, y: T, width: W - L - R, height: H - T - B, fill: 'transparent' }, svg);
    function move(ev) {
      const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
      const t = Math.max(0, Math.min(maxT, (px - L) / (W - L - R) * maxT));
      cross.setAttribute('x1', x(t)); cross.setAttribute('x2', x(t)); cross.setAttribute('opacity', .5);
      tip.innerHTML = `<b>t = ${t.toFixed(1)} s</b>` + players.map(p => `${(data.players[p] || {}).label || p}: ${Math.round(aliveAt(curves[p], t) * 100)}%`).join('<br>');
      tip.style.display = 'block';
      const left = (ev.clientX - r.left); tip.style.left = (left > r.width / 2 ? left - tip.offsetWidth - 12 : left + 12) + 'px'; tip.style.top = '8px';
    }
    hit.addEventListener('pointermove', move); hit.addEventListener('pointerdown', move);
    hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; cross.setAttribute('opacity', 0); });
    const note = document.getElementById('km-note');
    if (note && ds.note) note.textContent = ds.note;
  }

  function bind() {
    for (const b of document.querySelectorAll('[data-set]')) {
      if (b.dataset.set === 'confirmation' && data.confirmation) b.disabled = false;
      b.addEventListener('click', () => { if (b.disabled) return; set = b.dataset.set; sync(); draw(); });
    }
    for (const b of document.querySelectorAll('[data-game]')) b.addEventListener('click', () => { game = b.dataset.game; sync(); draw(); });
    if (data.confirmation) set = 'confirmation';
    sync(); draw();
    let rt, lastW = root.clientWidth;
    window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { if (root.clientWidth !== lastW) { lastW = root.clientWidth; draw(); } }, 150); });
  }
  function sync() {
    for (const b of document.querySelectorAll('[data-set]')) b.setAttribute('aria-pressed', String(b.dataset.set === set));
    for (const b of document.querySelectorAll('[data-game]')) b.setAttribute('aria-pressed', String(b.dataset.game === game));
  }
  const inline = document.getElementById('burst-data'); // preview build inlines data.json here
  (inline ? Promise.resolve(JSON.parse(inline.textContent)) : fetch('data.json').then(r => { if (!r.ok) throw Error(r.status); return r.json(); }))
    .then(d => { data = d; bind(); })
    .catch(() => { root.innerHTML = '<p class="note">Chart data could not be loaded; see the table view below.</p>'; });
})();
