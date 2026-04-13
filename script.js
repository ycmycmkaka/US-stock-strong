let allRows = [];

function formatMoney(num) {
  if (num == null || Number.isNaN(num)) return '-';
  const abs = Math.abs(num);
  if (abs >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
  return `$${num.toFixed(2)}`;
}

function formatPrice(num) {
  if (num == null || Number.isNaN(num)) return '-';
  return `$${num.toFixed(2)}`;
}

function formatPct(num) {
  if (num == null || Number.isNaN(num)) return '-';
  const sign = num > 0 ? '+' : '';
  return `${sign}${num.toFixed(1)}%`;
}

function sortRows(rows, mode) {
  const map = {
    return_2m_pct_desc: (a, b) => (b.return_2m_pct ?? -Infinity) - (a.return_2m_pct ?? -Infinity),
    distance_to_52w_high_pct_asc: (a, b) => (a.distance_to_52w_high_pct ?? Infinity) - (b.distance_to_52w_high_pct ?? Infinity),
    market_cap_desc: (a, b) => (b.market_cap ?? -Infinity) - (a.market_cap ?? -Infinity),
    symbol_asc: (a, b) => (a.symbol || '').localeCompare(b.symbol || '')
  };
  return [...rows].sort(map[mode] || map.return_2m_pct_desc);
}

function renderRules(data) {
  const card = document.getElementById('rulesCard');
  const rules = data.rules || {};
  const chips = [
    '只限美股',
    `市值 ≥ ${formatMoney(rules.market_cap_min || 0)}`,
    `2個月升幅 > ${rules.min_2m_return_pct ?? 0}%`,
    '現價 > 50MA',
    '50MA > 200MA',
    `距52週高位 ≤ ${rules.max_pct_below_52w_high ?? 0}%`
  ];
  card.innerHTML = `<h2>目前條件</h2><div class="rule-list">${chips.map(x => `<span class="rule-chip">${x}</span>`).join('')}</div>`;
}

function renderSummary(data) {
  const el = document.getElementById('summaryCard');
  const count = (data.results || []).length;
  const updated = data.generated_at || '-';
  el.innerHTML = `<strong>${count} 隻</strong><div>最新符合條件強勢股</div><div style="margin-top:8px;">最後更新：${updated}</div>`;
}

function renderTable() {
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  const sortMode = document.getElementById('sortSelect').value;
  let rows = allRows.filter(r => {
    const text = `${r.symbol || ''} ${r.company || ''}`.toLowerCase();
    return text.includes(search);
  });
  rows = sortRows(rows, sortMode);

  const body = document.getElementById('resultsBody');
  const empty = document.getElementById('emptyState');
  const countText = document.getElementById('countText');

  countText.textContent = `顯示 ${rows.length} 隻`;

  if (!rows.length) {
    body.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  body.innerHTML = rows.map(r => `
    <tr>
      <td>
        <div class="ticker">${r.symbol ?? '-'}</div>
        <div class="company">${r.sector ?? ''}</div>
      </td>
      <td>${r.company ?? '-'}</td>
      <td>${r.exchange ?? '-'}</td>
      <td>${formatMoney(r.market_cap)}</td>
      <td>${formatPrice(r.current_price)}</td>
      <td>${formatPrice(r.ma50)}</td>
      <td>${formatPrice(r.ma200)}</td>
      <td>${formatPrice(r.high_52w)}</td>
      <td class="${(r.distance_to_52w_high_pct ?? 999) <= 15 ? 'good' : ''}">${formatPct(-1 * (r.distance_to_52w_high_pct ?? 0))}</td>
      <td class="good">${formatPct(r.return_2m_pct)}</td>
    </tr>
  `).join('');
}

async function init() {
  try {
    const res = await fetch(`results.json?ts=${Date.now()}`);
    const data = await res.json();
    allRows = data.results || [];
    renderRules(data);
    renderSummary(data);
    renderTable();
  } catch (err) {
    document.getElementById('summaryCard').innerHTML = '<strong>載入失敗</strong><div>未能讀取 results.json</div>';
  }
}

document.getElementById('searchInput').addEventListener('input', renderTable);
document.getElementById('sortSelect').addEventListener('change', renderTable);
init();
