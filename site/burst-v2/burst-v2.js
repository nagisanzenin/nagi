'use strict';
// Burst V2 page: "Game Arena: V2 · V1 · Jev" table, read from the Arena page's own data (../arena/v2.json,
// schema nagi-arena-v2-update-v1). Claim labels are shown exactly as the JSON gives them. If the file is missing
// or malformed, the static link to ../arena/#v2 stays as it is. All JSON strings go through textContent.
(function () {
  const box = document.getElementById('arena-v2');
  if (!box || !window.fetch) return;
  const SRC = '../arena/v2.json';
  const BASE = new URL('../arena/', location.href);
  const ARMS = [['v2', 'Burst V2'], ['v1', 'Burst V1'], ['jev', 'Jev']];
  const isNum = x => typeof x === 'number' && isFinite(x);
  const fmt = (x, nd) => !isNum(x) ? '—' : Number.isInteger(nd) && nd >= 0 && nd <= 6 ? x.toFixed(nd) : x.toFixed(3);
  const OK_ABS = ['https://github.com/nagisanzenin/', 'https://huggingface.co/nagisanzeninz/'];
  const fmtP = p => !isNum(p) ? '—' : p >= 0.01 ? p.toFixed(3) : p >= 1e-4 ? p.toPrecision(3) : p.toExponential(1);
  const minus = s => String(s).replace(/^-/, '−');

  function el(tag, attrs, text) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function safeUrl(u) { // relative paths (resolved against the Arena page) or the project's own GitHub/HF pages
    if (typeof u !== 'string' || !u || u.startsWith('//')) return null;
    if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return OK_ABS.some(a => u.startsWith(a)) ? u : null;
    try { return new URL(u, BASE).href; } catch (e) { return null; }
  }
  function badge(claim, result) { // label text verbatim from the JSON
    const c = String(claim) + (result ? ' · ' + String(result) : '');
    const cls = result === 'PASS' || claim === 'shown' ? 'ok' : result === 'FAIL' || claim === 'not shown' ? 'bad' : 'mut';
    return el('span', { class: 'bdg ' + cls }, c);
  }
  function pairCell(g, b) {
    const td = el('td', { class: 'l' });
    const p = (g.pairs || []).find(q => q && q.a === 'v2' && (q.b === b || q.a_vs === b));
    if (!p) { td.textContent = '—'; return td; }
    const s = el('span', { class: 'pair' });
    s.append(el('b', null, 'W ' + minus(fmt(p.W, 3))), ' · t lower ' + minus(fmt(p.t_lb, 3)) + ' · p ' + fmtP(p.p));
    if (Number.isInteger(p.wins) && Number.isInteger(p.ties) && Number.isInteger(p.losses)) s.append(' · ' + p.wins + '/' + p.ties + '/' + p.losses);
    if (b === 'jev' && g.pairing_jev) s.append(' · ' + String(g.pairing_jev).toLowerCase());
    td.append(s, badge(p.claim, p.result));
    return td;
  }
  function render(d) {
    const wrap = el('div', { class: 'tw' });
    const t = el('table', { class: 'wrap' });
    t.append(el('caption', null, 'Game Arena · means per arm and paired comparisons (from the Arena page data)'));
    const hr = el('tr');
    ['Game', 'n', ...ARMS.map(a => a[1]), 'V2 vs V1', 'V2 vs Jev', 'Replay'].forEach(h => hr.append(el('th', { scope: 'col' }, h)));
    const thead = el('thead'); thead.append(hr); t.append(thead);
    const tb = el('tbody');
    for (const g of d.games) {
      if (!g || typeof g !== 'object') continue;
      const tr = el('tr');
      const name = el('td', { class: 'l' });
      name.append(el('b', null, String(g.label || g.game || '')));
      if (g.metric) name.append(el('span', { class: 'pair' }, String(g.metric) + (g.seeds ? ' · seeds ' + g.seeds : '')));
      const L = g.landings;
      if (L && typeof L === 'object') name.append(el('span', { class: 'pair' }, 'landed: ' + ARMS.map(([k, l]) => l + ' ' + (Number.isInteger(L[k]) ? L[k] : '—')).join(' · ')));
      tr.append(name, el('td', null, Number.isInteger(g.n) ? String(g.n) : '—'));
      const unit = typeof g.unit === 'string' && g.unit ? ' ' + g.unit : '';
      for (const [k] of ARMS) {
        const m = g.means ? g.means[k] : null;
        tr.append(el('td', null, isNum(m) ? minus(fmt(m, g.decimals)) + unit : '—'));
      }
      tr.append(pairCell(g, 'v1'), pairCell(g, 'jev'));
      const rp = el('td', { class: 'l' });
      const links = [['replay', 'Replay'], ['video', 'Video']].map(([k, l]) => [safeUrl(g[k]), l]).filter(x => x[0]);
      if (!links.length) rp.textContent = '—';
      links.forEach(([u, l], i) => { if (i) rp.append(' · '); rp.append(el('a', { href: u }, l + ' →')); });
      tr.append(rp);
      tb.append(tr);
    }
    t.append(tb); wrap.append(t);
    const frag = [wrap];
    const cr = d.claim_rule && typeof d.claim_rule === 'object' ? d.claim_rule : null;
    if (cr && (cr.v2_vs_v1 || cr.jev)) {
      const ul = el('ul', { class: 'notes' });
      if (cr.v2_vs_v1) ul.append(el('li', null, 'V2 vs V1: ' + String(cr.v2_vs_v1)));
      if (cr.jev) ul.append(el('li', null, 'Jev: ' + String(cr.jev)));
      frag.push(ul);
    }
    if (Array.isArray(d.notes) && d.notes.length) {
      const ul = el('ul', { class: 'notes' });
      d.notes.forEach(n => ul.append(el('li', null, String(n))));
      frag.push(ul);
    }
    box.prepend(...frag);
  }
  fetch(SRC, { cache: 'no-cache' })
    .then(r => (r.ok ? r.json() : null))
    .then(d => { if (d && d.schema === 'nagi-arena-v2-update-v1' && Array.isArray(d.games) && d.games.length) render(d); })
    .catch(() => {});
})();
