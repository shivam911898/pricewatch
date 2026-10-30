/* PriceWatch dashboard: live refresh, price-history chart, run-check button, add-product form. No framework. */
(() => {
  const cur = document.body.dataset.currency || '$';
  const HEADERS = { 'Content-Type': 'application/json', 'X-PriceWatch': '1' };
  const css = getComputedStyle(document.documentElement);
  const token = (name, fallback) => (css.getPropertyValue(name).trim() || fallback);
  // Categorical palette from the stylesheet (--s1..--s8); colour follows the store, not its rank.
  const FALLBACK = ['#4F46E5', '#14B8A6', '#F59E0B', '#EC4899', '#0EA5E9', '#84CC16', '#8B5CF6', '#EF4444'];
  const PALETTE = FALLBACK.map((c, i) => token('--s' + (i + 1), c));
  const INK = token('--text', '#0F172A'), MUTED = token('--muted', '#64748B'), GRID = token('--border', '#E2E8F0');
  const PRESETS = [
    { name: 'USB-C Charging Cable 2m', my_price: 11.49, store: 'AlphaMart', url: '/demo-store/alpha/4', css_selector: '.price', stock_selector: '.stock' },
    { name: 'Ceramic Coffee Mug Set', my_price: 32.0, store: 'BetaShop', url: '/demo-store/beta/api/5', json_path: 'product.price', stock_path: 'product.available' },
    { name: 'LED Desk Lamp', my_price: 38.5, store: 'AlphaMart', url: '/demo-store/alpha/6', css_selector: '.price', stock_selector: '.stock' },
  ];
  const FIELDS = ['name', 'my_price', 'store', 'url', 'css_selector', 'stock_selector', 'undercut_pct', 'drop_pct', 'json_path', 'stock_path', 'backend'];
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const plural = (n, word) => n + ' ' + word + (n === 1 ? '' : 's');
  let stores = [], products = [], selected = null, chart = null, lastSig = '', running = false;

  const money = v => (v == null ? '-' : cur + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

  /* ---------- toast ---------- */
  function toast(msg, kind) {
    const t = $('#toast');
    t.textContent = msg; t.className = 'toast' + (kind === 'bad' || kind === true ? ' bad' : kind === 'warn' ? ' warn' : ''); t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 5000);
  }

  function errText(d, status) {
    if (d && typeof d.detail === 'string') return d.detail;
    if (d && Array.isArray(d.detail)) return d.detail.map(e => ((e.loc || []).slice(-1)[0] || 'field') + ': ' + e.msg).join('; ');
    return 'Request failed (' + status + ')';
  }

  async function api(path, opts) {
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) { const err = new Error(errText(data, r.status)); err.detail = data && data.detail; err.status = r.status; throw err; }
    return data;
  }

  /* ---------- times: titles show the visitor's local time (the server renders UTC as a fallback) ---------- */
  function localizeTimes() {
    $$('time[datetime]').forEach(t => {
      const d = new Date(t.getAttribute('datetime'));
      if (!isNaN(d)) t.title = d.toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' });
    });
  }

  /* ---------- live sections ---------- */
  function focusKey() {
    const a = document.activeElement;
    if (!a || !a.closest || !a.closest('[data-slot]')) return null;
    if (a.dataset.chart) return '[data-chart="' + CSS.escape(a.dataset.chart) + '"]';
    if (a.dataset.del) return '[data-del="' + CSS.escape(a.dataset.del) + '"]';
    if (a.hasAttribute('data-run')) return '[data-slot] [data-run]';
    return null;
  }

  async function refresh() {
    const html = await (await fetch('fragment', { cache: 'no-store' })).text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const key = focusKey();
    doc.querySelectorAll('[data-slot]').forEach(n => {
      $$('[data-slot="' + n.dataset.slot + '"]').forEach(old => {
        if (old.outerHTML === n.outerHTML) return;               // nothing changed: keep focus, scroll and hover state
        const wrap = $('.table-wrap', old), left = wrap ? wrap.scrollLeft : 0, top = wrap ? wrap.scrollTop : 0;
        const fresh = n.cloneNode(true);
        old.replaceWith(fresh);
        const w2 = $('.table-wrap', fresh);
        if (w2) { w2.scrollLeft = left; w2.scrollTop = top; }
      });
    });
    if (key) { const el = $(key); if (el) el.focus({ preventScroll: true }); }
    localizeTimes();
    applyRunState();
    await syncFromTable();
  }

  async function syncFromTable() {
    const t = $('[data-slot="table"]');
    if (!t) return;
    stores = JSON.parse(t.dataset.stores || '[]');
    const list = JSON.parse(t.dataset.products || '[]');
    if (JSON.stringify(list) !== JSON.stringify(products)) {
      products = list;
      const sel = $('#chart-product');
      sel.replaceChildren(...products.map(p => { const o = document.createElement('option'); o.value = o.textContent = p; return o; }));
    }
    if (!products.includes(selected)) selected = products[0] || null;
    $('#chart-product').value = selected || '';
    markSelected();
    await loadChart();
  }

  function markSelected() {
    $$('tr[data-product]').forEach(tr => tr.classList.toggle('is-selected', tr.dataset.product === selected));
    $$('[data-chart]').forEach(b => {
      const on = b.dataset.chart === selected;
      b.classList.toggle('is-active', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.textContent = on ? 'Viewing' : 'View chart';
    });
  }

  /* ---------- chart ---------- */
  const fmtTime = (iso, multiDay) => {
    const d = new Date(iso);
    return multiDay
      ? d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  async function loadChart() {
    const empty = $('#chart-empty'), box = $('.chart-box'), sub = $('#chart-subtitle');
    if (!selected) {
      box.hidden = true; empty.hidden = false; empty.textContent = 'No products yet. Add one to start tracking its price history.';
      sub.textContent = 'Pick a product to see how each competitor’s price moved against yours.';
      return;
    }
    const d = await api('api/history?product=' + encodeURIComponent(selected));
    const sig = JSON.stringify(d) + stores.join('|');
    if (sig === lastSig) return;
    lastSig = sig;
    box.hidden = d.labels.length === 0; empty.hidden = d.labels.length !== 0;
    empty.textContent = 'No checks yet for this product. Run a check to start its history.';
    sub.replaceChildren(Object.assign(document.createElement('strong'), { textContent: selected }),
      document.createTextNode(' · ' + plural(d.labels.length, 'check') + ' · dashed line is your price (' + money(d.my_price) + ')'));
    const multiDay = d.labels.length > 1 && new Date(d.labels[0]).toDateString() !== new Date(d.labels[d.labels.length - 1]).toDateString();
    const labels = d.labels.map(l => fmtTime(l, multiDay));
    const datasets = d.series.map(s => {
      const color = PALETTE[Math.max(0, stores.indexOf(s.store)) % PALETTE.length];
      return { label: s.store, data: s.prices, stock: s.stock, borderColor: color, backgroundColor: color, borderWidth: 2.5, tension: 0.2,
        spanGaps: true, pointRadius: c => (s.stock[c.dataIndex] ? 3.5 : 8), pointHoverRadius: 7,
        pointStyle: c => (s.stock[c.dataIndex] ? 'circle' : 'crossRot'),
        pointBorderColor: c => (s.stock[c.dataIndex] ? '#fff' : color), pointBorderWidth: c => (s.stock[c.dataIndex] ? 2 : 3) };
    });
    datasets.push({ label: 'My price', data: labels.map(() => d.my_price), borderColor: INK, borderDash: [6, 4], borderWidth: 1.5,
      pointRadius: 0, pointHoverRadius: 0 });
    if (chart) {
      chart.data.labels = labels; chart.data.datasets = datasets; chart.update('none');
    } else if (window.Chart) {
      Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
      Chart.defaults.font.size = 12;
      Chart.defaults.color = MUTED;
      chart = new Chart($('#chart'), {
        type: 'line', data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { position: 'top', align: 'start', labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8, padding: 16 } },
            tooltip: {
              backgroundColor: '#fff', titleColor: INK, bodyColor: INK, borderColor: GRID, borderWidth: 1, padding: 12, cornerRadius: 10,
              boxPadding: 4, usePointStyle: true,
              callbacks: { label: c => c.dataset.label + ': ' + money(c.parsed.y) + (c.dataset.stock && c.dataset.stock[c.dataIndex] === false ? ' (out of stock)' : '') },
            },
          },
          scales: {
            x: { grid: { display: false }, border: { color: GRID }, ticks: { maxTicksLimit: 8, maxRotation: 0 } },
            y: { grace: '8%', grid: { color: GRID }, border: { display: false }, ticks: { callback: v => money(v) } },
          },
        },
      });
    }
    renderTable(d, labels);
  }

  function renderTable(d, labels) {
    const tbl = $('#chart-table');
    const head = ['Time', ...d.series.map(s => s.store), 'My price'];
    const rows = labels.map((l, i) => [l, ...d.series.map(s => money(s.prices[i]) + (s.stock[i] === false ? ' (out of stock)' : '')), money(d.my_price)]).reverse();
    const mk = (tag, cells) => { const tr = document.createElement('tr'); cells.forEach(c => { const e = document.createElement(tag); e.textContent = c; tr.append(e); }); return tr; };
    tbl.replaceChildren(mk('th', head), ...rows.map(r => mk('td', r)));
  }

  function showHistory() {
    const h = $('#history'), r = h.getBoundingClientRect();
    if (r.top >= 72 && r.bottom <= window.innerHeight) return;     // already fully visible: do not move the page
    h.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }

  async function select(product) {
    selected = product; $('#chart-product').value = product; lastSig = '';
    markSelected();
    await loadChart();
    showHistory();
  }

  /* ---------- run check ---------- */
  function applyRunState() {
    $$('[data-run]').forEach(b => {
      b.classList.toggle('is-busy', running); b.disabled = running; b.setAttribute('aria-busy', running ? 'true' : 'false');
      const label = $('.btn-label', b); if (label) label.textContent = running ? 'Checking...' : 'Run check now';
    });
  }

  async function runNow() {
    if (running) return;
    running = true; applyRunState();
    try {
      // The demo store answers in milliseconds; keep the spinner up briefly so the click visibly registers.
      const [r] = await Promise.all([api('api/run', { method: 'POST', headers: HEADERS }), new Promise(res => setTimeout(res, 600))]);
      const parts = ['Checked ' + plural(r.checked, 'page') + ', ' + plural(r.alerts, 'new alert')];
      if (r.errors) parts.push(r.errors + ' failed');
      if (r.skipped) parts.push(r.skipped + ' skipped');
      toast(parts.join(', '), r.errors ? 'warn' : 'ok');
      await refresh();
    } catch (e) { toast(e.message, 'bad'); }
    running = false; applyRunState();
  }

  async function onClick(e) {
    const del = e.target.closest('[data-del]');
    if (del) {
      if (!confirm('Remove "' + del.dataset.del + '" and its history?')) return;
      try { await api('api/products?name=' + encodeURIComponent(del.dataset.del), { method: 'DELETE', headers: HEADERS }); await refresh(); toast('Removed ' + del.dataset.del + '.'); }
      catch (err) { toast(err.message, 'bad'); }
      return;
    }
    if (e.target.closest('[data-run]')) { runNow(); return; }
    const row = e.target.closest('tr[data-product]');
    if (row && !e.target.closest('a')) await select(row.dataset.product);
  }

  /* ---------- add-product form (client hints; the server validates again) ---------- */
  const val = (f, k) => ((f.elements[k] && f.elements[k].value) || '').trim();
  const RULES = {
    name: v => (!v ? 'Enter a product name.' : v.length > 80 ? 'Use 80 characters or fewer.' : ''),
    my_price: v => { const n = parseFloat(v); return !v ? 'Enter your price.' : !(n > 0) ? 'Enter a price above 0.' : n >= 1e6 ? 'Enter a price below 1,000,000.' : ''; },
    store: v => (!v ? 'Enter the competitor name.' : v.length > 60 ? 'Use 60 characters or fewer.' : ''),
    url: v => (!v ? 'Enter the product page address.' : !/^(https?:\/\/|\/)/i.test(v) ? 'Start with https:// (or / for the demo store).' : ''),
    undercut_pct: v => (v && !(parseFloat(v) >= 0 && parseFloat(v) <= 100) ? 'Enter a number from 0 to 100.' : ''),
    drop_pct: v => (v && !(parseFloat(v) >= 0 && parseFloat(v) <= 100) ? 'Enter a number from 0 to 100.' : ''),
    json_path: v => (v && !/^[\w-]+(\.[\w-]+)*$/.test(v) ? 'Use a path like product.price or items.0.price.' : ''),
    stock_path: v => (v && !/^[\w-]+(\.[\w-]+)*$/.test(v) ? 'Use a path like product.available.' : ''),
  };

  function setFieldError(f, name, msg) {
    const wrap = f.querySelector('[data-field="' + name + '"]'); if (!wrap) return;
    const out = $('#e-' + name, wrap), input = f.elements[name];
    out.textContent = msg; out.hidden = !msg;
    wrap.classList.toggle('has-error', !!msg);
    if (input) input.setAttribute('aria-invalid', msg ? 'true' : 'false');
    if (msg && wrap.closest('details')) wrap.closest('details').open = true;
  }

  function clearErrors(f) { FIELDS.forEach(k => setFieldError(f, k, '')); }

  function validate(f) {
    const errs = {};
    Object.keys(RULES).forEach(k => { const m = RULES[k](val(f, k)); if (m) errs[k] = m; });
    const agent = f.elements.backend && !f.elements.backend.disabled && f.elements.backend.value === 'browser_agent';
    if (!agent && !val(f, 'css_selector') && !val(f, 'json_path') && !errs.css_selector) errs.css_selector = 'Give a CSS selector, or open Advanced and give a JSON path.';
    return errs;
  }

  // Map a server message to the field it is about; anything else stays a form-level message.
  const FIELD_OF = [[/first check failed/i, null], [/product limit/i, 'name'], [/competitors per product/i, 'store'], [/json path/i, 'json_path'],
    [/selector/i, 'css_selector'], [/backend/i, 'backend'], [/url|demo store|public demo|private|local address|robots/i, 'url']];
  function showServerError(f, err) {
    const msg = $('#form-msg'); let general = '';
    if (Array.isArray(err.detail)) {
      err.detail.forEach(d => { const k = (d.loc || []).slice(-1)[0]; if (FIELDS.includes(k)) setFieldError(f, k, d.msg); else general = general || d.msg; });
    } else {
      const hit = FIELD_OF.find(([re]) => re.test(err.message));
      if (hit && hit[1]) setFieldError(f, hit[1], err.message);
      else {
        general = err.message.replace(/\b\w+Error:\s*/, '');
        // The first check ran and could not read the page: point at the field the visitor most likely needs to fix.
        if (/first check failed/i.test(general) && /selector/i.test(general)) setFieldError(f, 'css_selector', 'This selector did not match anything on the page.');
        else if (/first check failed/i.test(general) && /json|path/i.test(general)) setFieldError(f, 'json_path', 'This path was not found in the response.');
      }
    }
    msg.className = 'form-msg bad';
    msg.textContent = general || 'Not saved. Check the highlighted field.';
    const first = f.querySelector('.has-error input, .has-error select'); if (first) first.focus();
  }

  function fillDemo() {
    const have = new Set(products.map(p => p.toLowerCase()));
    const p = PRESETS.find(x => !have.has(x.name.toLowerCase())) || PRESETS[0];
    const f = $('#add-form');
    ['name', 'my_price', 'store', 'url', 'css_selector', 'stock_selector', 'json_path', 'stock_path'].forEach(k => { f.elements[k].value = p[k] == null ? '' : p[k]; });
    if (p.json_path) f.querySelector('details').open = true;
    clearErrors(f); $('#form-msg').className = 'form-msg'; $('#form-msg').textContent = '';
  }

  async function submitForm(e) {
    e.preventDefault();
    const f = e.target, msg = $('#form-msg'), btn = $('#btn-add'), label = $('.btn-label', btn);
    clearErrors(f); msg.className = 'form-msg'; msg.textContent = '';
    const errs = validate(f);
    if (Object.keys(errs).length) {
      Object.entries(errs).forEach(([k, m]) => setFieldError(f, k, m));
      msg.className = 'form-msg bad'; msg.textContent = 'Fix the highlighted ' + (Object.keys(errs).length === 1 ? 'field' : 'fields') + ' and try again.';
      const first = f.querySelector('.has-error input, .has-error select'); if (first) first.focus();
      return;
    }
    const v = k => val(f, k);
    const body = { name: v('name'), my_price: parseFloat(v('my_price')), store: v('store'), url: v('url') };
    ['css_selector', 'stock_selector', 'json_path', 'stock_path'].forEach(k => { if (v(k)) body[k] = v(k); });
    ['undercut_pct', 'drop_pct'].forEach(k => { if (v(k)) body[k] = parseFloat(v(k)); });
    if (!f.elements.backend.disabled) body.backend = f.elements.backend.value;
    btn.disabled = true; btn.classList.add('is-busy'); label.textContent = 'Checking the page...';
    try {
      const r = await api('api/products', { method: 'POST', headers: HEADERS, body: JSON.stringify(body) });
      msg.className = 'form-msg ok';
      if (r.pending) msg.textContent = r.message;
      else {
        const last = r.last || {};
        msg.textContent = 'Added "' + r.product + '". First check: ' + (last.error ? last.error : (last.store + ' ' + money(last.price) + (last.in_stock ? ', in stock' : ', out of stock'))) +
          (r.alerts ? ' - ' + plural(r.alerts, 'alert') + ' fired.' : '.');
      }
      toast('Added ' + r.product, 'ok');
      f.reset(); selected = r.product; lastSig = '';
      await refresh();
    } catch (err) { showServerError(f, err); }
    btn.disabled = false; btn.classList.remove('is-busy'); label.textContent = 'Add & check now';
  }

  /* ---------- wire up ---------- */
  const reset = $('#btn-reset');
  if (reset) reset.addEventListener('click', async () => {
    if (!confirm('Restore the original demo products and history?')) return;
    reset.disabled = true;
    try { await api('api/demo/reset', { method: 'POST', headers: HEADERS }); lastSig = ''; await refresh(); toast('Demo reset.', 'ok'); }
    catch (err) { toast(err.message, 'bad'); }
    reset.disabled = false;
  });
  const fill = $('#btn-fill');
  if (fill) fill.addEventListener('click', fillDemo);
  document.addEventListener('click', onClick);
  const form = $('#add-form');
  form.addEventListener('submit', submitForm);
  form.addEventListener('focusout', e => {                              // inline hint as soon as a field is left
    const k = e.target.name; if (!RULES[k]) return;
    const invalid = e.target.getAttribute('aria-invalid') === 'true';
    if (!val(form, k) && !invalid) return;                              // an untouched empty field is only flagged on submit
    setFieldError(form, k, RULES[k](val(form, k)));
  });
  form.addEventListener('input', e => { if (e.target.getAttribute('aria-invalid') === 'true') setFieldError(form, e.target.name, ''); });
  $('#chart-product').addEventListener('change', e => { selected = e.target.value; lastSig = ''; markSelected(); loadChart(); });
  setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh().catch(() => {}); });
  localizeTimes();
  syncFromTable().catch(err => toast(err.message, 'bad'));
})();
