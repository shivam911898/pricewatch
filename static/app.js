/* PriceWatch dashboard: live refresh, price-history chart, add-product form. No framework. */
(() => {
  const cur = document.body.dataset.currency || '$';
  const demo = document.body.dataset.demo === '1';
  const HEADERS = { 'Content-Type': 'application/json', 'X-PriceWatch': '1' };
  // Categorical palette, fixed order, assigned per store (colour follows the entity, not its rank).
  const PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
  const PRESETS = [
    { name: 'USB-C Charging Cable 2m', my_price: 11.49, store: 'AlphaMart', url: '/demo-store/alpha/4', css_selector: '.price', stock_selector: '.stock' },
    { name: 'Ceramic Coffee Mug Set', my_price: 32.0, store: 'BetaShop', url: '/demo-store/beta/api/5', json_path: 'product.price', stock_path: 'product.available' },
    { name: 'LED Desk Lamp', my_price: 38.5, store: 'AlphaMart', url: '/demo-store/alpha/6', css_selector: '.price', stock_selector: '.stock' },
  ];
  const $ = (s, r = document) => r.querySelector(s);
  let stores = [], products = [], selected = null, chart = null, lastSig = '';

  const money = v => (v == null ? '-' : cur + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

  function toast(msg, bad) {
    const t = $('#toast');
    t.textContent = msg; t.className = 'toast' + (bad ? ' bad' : ''); t.hidden = false;
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
    if (!r.ok) throw new Error(errText(data, r.status));
    return data;
  }

  /* ---------- live sections ---------- */
  async function refresh() {
    const html = await (await fetch('fragment', { cache: 'no-store' })).text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('[data-slot]').forEach(n => {
      document.querySelectorAll('[data-slot="' + n.dataset.slot + '"]').forEach(old => old.replaceWith(n.cloneNode(true)));
    });
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
    await loadChart();
  }

  /* ---------- chart ---------- */
  const fmtTime = (iso, multiDay) => {
    const d = new Date(iso);
    return multiDay
      ? d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  async function loadChart() {
    const empty = $('#chart-empty'), box = $('.chart-box');
    if (!selected) { box.hidden = true; empty.hidden = false; return; }
    const d = await api('api/history?product=' + encodeURIComponent(selected));
    const sig = JSON.stringify(d) + stores.join('|');
    if (sig === lastSig) return;
    lastSig = sig;
    box.hidden = d.labels.length === 0; empty.hidden = d.labels.length !== 0;
    const multiDay = d.labels.length > 1 && new Date(d.labels[0]).toDateString() !== new Date(d.labels[d.labels.length - 1]).toDateString();
    const labels = d.labels.map(l => fmtTime(l, multiDay));
    const datasets = d.series.map(s => {
      const color = PALETTE[Math.max(0, stores.indexOf(s.store)) % PALETTE.length];
      return { label: s.store, data: s.prices, stock: s.stock, borderColor: color, backgroundColor: color, borderWidth: 2, tension: 0.15,
        spanGaps: true, pointRadius: c => (s.stock[c.dataIndex] ? 4 : 8), pointHoverRadius: 8,
        pointStyle: c => (s.stock[c.dataIndex] ? 'circle' : 'crossRot'),
        pointBorderColor: c => (s.stock[c.dataIndex] ? '#fff' : color), pointBorderWidth: c => (s.stock[c.dataIndex] ? 2 : 3) };
    });
    datasets.push({ label: 'My price', data: labels.map(() => d.my_price), borderColor: '#14171f', borderDash: [6, 4], borderWidth: 1.5,
      pointRadius: 0, pointHoverRadius: 0 });
    if (chart) {
      chart.data.labels = labels; chart.data.datasets = datasets; chart.update('none');
    } else if (window.Chart) {
      Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
      Chart.defaults.color = '#566074';
      chart = new Chart($('#chart'), {
        type: 'line', data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { position: 'top', align: 'start', labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
            tooltip: { callbacks: { label: c => c.dataset.label + ': ' + money(c.parsed.y) + (c.dataset.stock && c.dataset.stock[c.dataIndex] === false ? ' (out of stock)' : '') } },
          },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } },
            y: { grace: '8%', grid: { color: '#eceef3' }, ticks: { callback: v => money(v) } },
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

  /* ---------- actions ---------- */
  async function runNow() {
    const b = $('#btn-run');
    b.disabled = true; b.textContent = 'Checking...';
    try {
      const r = await api('api/run', { method: 'POST', headers: HEADERS });
      toast('Checked ' + r.checked + ' page(s), ' + r.alerts + ' new alert(s)' + (r.errors ? ', ' + r.errors + ' failed' : '') + '.', r.errors > 0);
      await refresh();
    } catch (e) { toast(e.message, true); }
    b.disabled = false; b.textContent = 'Run check now';
  }

  async function onClick(e) {
    const del = e.target.closest('[data-del]');
    if (del) {
      if (!confirm('Remove "' + del.dataset.del + '" and its history?')) return;
      try { await api('api/products?name=' + encodeURIComponent(del.dataset.del), { method: 'DELETE', headers: HEADERS }); await refresh(); toast('Removed.'); }
      catch (err) { toast(err.message, true); }
      return;
    }
    const row = e.target.closest('tr[data-product]');
    if (row && !e.target.closest('a')) {
      selected = row.dataset.product; $('#chart-product').value = selected; lastSig = '';
      await loadChart(); $('#history').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  function fillDemo() {
    const have = new Set(products.map(p => p.toLowerCase()));
    const p = PRESETS.find(x => !have.has(x.name.toLowerCase())) || PRESETS[0];
    const f = $('#add-form');
    ['name', 'my_price', 'store', 'url', 'css_selector', 'stock_selector', 'json_path', 'stock_path'].forEach(k => { f.elements[k].value = p[k] == null ? '' : p[k]; });
    if (p.json_path) f.querySelector('details').open = true;
  }

  async function submitForm(e) {
    e.preventDefault();
    const f = e.target, msg = $('#form-msg'), btn = $('#btn-add');
    const v = k => (f.elements[k].value || '').trim();
    const body = { name: v('name'), my_price: parseFloat(v('my_price')), store: v('store'), url: v('url') };
    ['css_selector', 'stock_selector', 'json_path', 'stock_path'].forEach(k => { if (v(k)) body[k] = v(k); });
    ['undercut_pct', 'drop_pct'].forEach(k => { if (v(k)) body[k] = parseFloat(v(k)); });
    if (!f.elements.backend.disabled) body.backend = f.elements.backend.value;
    btn.disabled = true; btn.textContent = 'Checking the page...'; msg.className = 'form-msg'; msg.textContent = '';
    try {
      const r = await api('api/products', { method: 'POST', headers: HEADERS, body: JSON.stringify(body) });
      msg.className = 'form-msg ok';
      if (r.pending) msg.textContent = r.message;
      else {
        const last = r.last || {};
        msg.textContent = 'Added "' + r.product + '". First check: ' + (last.error ? last.error : (last.store + ' ' + money(last.price) + (last.in_stock ? ', in stock' : ', out of stock'))) +
          (r.alerts ? ' - ' + r.alerts + ' alert(s) fired.' : '.');
      }
      f.reset(); selected = r.product; lastSig = '';
      await refresh();
    } catch (err) { msg.className = 'form-msg bad'; msg.textContent = err.message; }
    btn.disabled = false; btn.textContent = 'Add & check now';
  }

  /* ---------- wire up ---------- */
  $('#btn-run').addEventListener('click', runNow);
  const reset = $('#btn-reset');
  if (reset) reset.addEventListener('click', async () => {
    if (!confirm('Restore the original demo products and history?')) return;
    reset.disabled = true;
    try { await api('api/demo/reset', { method: 'POST', headers: HEADERS }); lastSig = ''; await refresh(); toast('Demo reset.'); }
    catch (err) { toast(err.message, true); }
    reset.disabled = false;
  });
  const fill = $('#btn-fill');
  if (fill) fill.addEventListener('click', fillDemo);
  document.addEventListener('click', onClick);
  $('#add-form').addEventListener('submit', submitForm);
  $('#chart-product').addEventListener('change', e => { selected = e.target.value; lastSig = ''; loadChart(); });
  setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh().catch(() => {}); });
  syncFromTable().catch(err => toast(err.message, true));
})();
