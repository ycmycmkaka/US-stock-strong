let allRows = [];
let filteredRows = [];
let currentSort = "rs_20d_vs_spy_pct_desc";

const summaryCard = document.getElementById("summaryCard");
const rulesCard = document.getElementById("rulesCard");
const searchInput = document.getElementById("searchInput");
const sortSelect = document.getElementById("sortSelect");
const resultsBody = document.getElementById("resultsBody");
const emptyState = document.getElementById("emptyState");
const countText = document.getElementById("countText");

function formatMarketCap(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  if (n >= 1_000_000_000_000) return `$${(n / 1_000_000_000_000).toFixed(2)}T`;
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  return `$${n.toFixed(0)}`;
}

function formatPrice(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `$${n.toFixed(2)}`;
}

function formatPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n.toFixed(1)}%`;
}

function pctClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "neutral";
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "neutral";
}

function marketCapBadgeClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "badge-marketcap-default";
  if (n >= 100_000_000_000) return "badge-marketcap-red";
  if (n >= 50_000_000_000) return "badge-marketcap-yellow";
  return "badge-marketcap-default";
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSummary(data) {
  const updated = data.generated_at || "Unknown";
  const count = Array.isArray(data.results) ? data.results.length : 0;

  summaryCard.innerHTML = `
    <div class="summary-label">最新符合條件短炒強勢股</div>
    <div class="summary-count">${count} 隻</div>
    <div class="summary-updated">最後更新：${escapeHtml(updated)}</div>
  `;
}

function renderRules(data) {
  const rules = data.rules || {};
  const benchmark = rules.benchmark_symbol || "SPY";

  const chips = [
    "只限美股",
    `市值 ≥ ${formatMarketCap(rules.market_cap_min || 0)}`,
    `5日跑贏 ${benchmark} ≥ ${Number(rules.rs_5d_vs_spy_min_pct ?? 3).toFixed(1)}%`,
    `20日跑贏 ${benchmark} ≥ ${Number(rules.rs_20d_vs_spy_min_pct ?? 8).toFixed(1)}%`,
    `距52週高位 ≤ ${Number(rules.max_dist_from_52w_high_pct ?? 2).toFixed(1)}%`
  ];

  const extra = [];
  if (Number.isFinite(Number(rules.spy_five_day_return_pct))) {
    extra.push(`${benchmark} 5D：${formatPct(rules.spy_five_day_return_pct)}`);
  }
  if (Number.isFinite(Number(rules.spy_twenty_day_return_pct))) {
    extra.push(`${benchmark} 20D：${formatPct(rules.spy_twenty_day_return_pct)}`);
  }

  rulesCard.innerHTML = `
    <div class="rules-title">目前條件</div>
    <div class="rule-chips">
      ${chips.map(chip => `<span class="rule-chip">${escapeHtml(chip)}</span>`).join("")}
    </div>
    <div class="rules-extra">${extra.map(escapeHtml).join(" ｜ ")}</div>
  `;
}

function sortRows(rows, sortKey) {
  const cloned = [...rows];

  switch (sortKey) {
    case "rs_20d_vs_spy_pct_desc":
      cloned.sort((a, b) => (Number(b.rs_20d_vs_spy_pct) || -Infinity) - (Number(a.rs_20d_vs_spy_pct) || -Infinity));
      break;
    case "rs_5d_vs_spy_pct_desc":
      cloned.sort((a, b) => (Number(b.rs_5d_vs_spy_pct) || -Infinity) - (Number(a.rs_5d_vs_spy_pct) || -Infinity));
      break;
    case "dist_from_52w_high_pct_desc":
      cloned.sort((a, b) => (Number(b.dist_from_52w_high_pct) || -Infinity) - (Number(a.dist_from_52w_high_pct) || -Infinity));
      break;
    case "market_cap_desc":
      cloned.sort((a, b) => (Number(b.market_cap) || -Infinity) - (Number(a.market_cap) || -Infinity));
      break;
    case "symbol_asc":
      cloned.sort((a, b) => String(a.symbol || "").localeCompare(String(b.symbol || "")));
      break;
    default:
      cloned.sort((a, b) => (Number(b.rs_20d_vs_spy_pct) || -Infinity) - (Number(a.rs_20d_vs_spy_pct) || -Infinity));
  }

  return cloned;
}

function renderTable(rows) {
  resultsBody.innerHTML = "";

  if (!rows.length) {
    emptyState.classList.remove("hidden");
    countText.textContent = "顯示 0 隻";
    return;
  }

  emptyState.classList.add("hidden");
  countText.textContent = `顯示 ${rows.length} 隻`;

  const html = rows.map((row) => {
    return `
      <tr>
        <td class="symbol-cell">${escapeHtml(row.symbol || "")}</td>
        <td class="company-cell">${escapeHtml(row.company || "")}</td>
        <td>${escapeHtml(row.exchange || "")}</td>
        <td>
          <span class="badge ${marketCapBadgeClass(row.market_cap)}">
            ${formatMarketCap(row.market_cap)}
          </span>
        </td>
        <td>
          <span class="badge badge-price">
            ${formatPrice(row.recent_close)}
          </span>
        </td>
        <td class="${pctClass(row.five_day_return_pct)}">${formatPct(row.five_day_return_pct)}</td>
        <td class="${pctClass(row.twenty_day_return_pct)}">${formatPct(row.twenty_day_return_pct)}</td>
        <td class="${pctClass(row.rs_5d_vs_spy_pct)}">${formatPct(row.rs_5d_vs_spy_pct)}</td>
        <td class="${pctClass(row.rs_20d_vs_spy_pct)}">${formatPct(row.rs_20d_vs_spy_pct)}</td>
        <td>${formatPrice(row.high_52w)}</td>
        <td class="${pctClass(row.dist_from_52w_high_pct)}">${formatPct(row.dist_from_52w_high_pct)}</td>
      </tr>
    `;
  }).join("");

  resultsBody.innerHTML = html;
}

function applySearchAndSort() {
  const keyword = (searchInput.value || "").trim().toLowerCase();

  filteredRows = allRows.filter((row) => {
    if (!keyword) return true;
    const symbol = String(row.symbol || "").toLowerCase();
    const company = String(row.company || "").toLowerCase();
    return symbol.includes(keyword) || company.includes(keyword);
  });

  filteredRows = sortRows(filteredRows, currentSort);
  renderTable(filteredRows);
}

async function loadData() {
  try {
    const response = await fetch(`results.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();

    renderSummary(data);
    renderRules(data);

    allRows = Array.isArray(data.results) ? data.results : [];
    currentSort = sortSelect.value || "rs_20d_vs_spy_pct_desc";
    applySearchAndSort();
  } catch (error) {
    console.error(error);
    summaryCard.innerHTML = `
      <div class="summary-label">載入失敗</div>
      <div class="summary-updated">請稍後再試</div>
    `;
    rulesCard.innerHTML = `
      <div class="rules-title">目前條件</div>
      <div class="rules-extra">未能讀取 results.json</div>
    `;
    resultsBody.innerHTML = "";
    emptyState.classList.remove("hidden");
    countText.textContent = "顯示 0 隻";
  }
}

searchInput.addEventListener("input", applySearchAndSort);

sortSelect.addEventListener("change", () => {
  currentSort = sortSelect.value;
  applySearchAndSort();
});

loadData();
