let allRows = [];
let filteredRows = [];
let currentSort = "rs_2m_vs_spy_pct_desc";

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
  if (!Number.isFinite(n)) return "";
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "";
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
    <div class="summary-label">最新符合條件相對強勢股</div>
    <div class="summary-count">${count} 隻</div>
    <div class="summary-updated">最後更新：${escapeHtml(updated)}</div>
  `;
}

function renderRules(data) {
  const rules = data.rules || {};

  const marketCapText = rules.market_cap_min
    ? `市值 ≥ ${formatMarketCap(rules.market_cap_min)}`
    : "市值條件 -";

  const benchmark = rules.benchmark_symbol || "SPY";

  const chips = [
    "只限美股",
    marketCapText,
    `2個月跑贏 ${benchmark} ≥ ${Number(rules.rs_2m_vs_spy_min_pct ?? 10).toFixed(1)}%`,
    `1個月跑贏 ${benchmark} ≥ ${Number(rules.rs_1m_vs_spy_min_pct ?? 5).toFixed(1)}%`,
    `距3個月高位 ≤ ${Number(rules.max_dist_from_3m_high_pct ?? 15).toFixed(1)}%`,
  ];

  const extraInfo = [];
  if (Number.isFinite(Number(rules.spy_one_month_return_pct))) {
    extraInfo.push(`${benchmark} 1M：${formatPct(rules.spy_one_month_return_pct)}`);
  }
  if (Number.isFinite(Number(rules.spy_two_month_return_pct))) {
    extraInfo.push(`${benchmark} 2M：${formatPct(rules.spy_two_month_return_pct)}`);
  }

  rulesCard.innerHTML = `
    <div class="rules-title">目前條件</div>
    <div class="rule-chips">
      ${chips.map((chip) => `<span class="rule-chip">${escapeHtml(chip)}</span>`).join("")}
    </div>
    ${extraInfo.length ? `<div class="rules-extra">${extraInfo.map(escapeHtml).join(" ｜ ")}</div>` : ""}
  `;
}

function sortRows(rows, sortKey) {
  const cloned = [...rows];

  switch (sortKey) {
    case "rs_2m_vs_spy_pct_desc":
      cloned.sort((a, b) => (Number(b.rs_2m_vs_spy_pct) || -Infinity) - (Number(a.rs_2m_vs_spy_pct) || -Infinity));
      break;
    case "rs_1m_vs_spy_pct_desc":
      cloned.sort((a, b) => (Number(b.rs_1m_vs_spy_pct) || -Infinity) - (Number(a.rs_1m_vs_spy_pct) || -Infinity));
      break;
    case "dist_from_3m_high_pct_desc":
      cloned.sort((a, b) => (Number(b.dist_from_3m_high_pct) || -Infinity) - (Number(a.dist_from_3m_high_pct) || -Infinity));
      break;
    case "market_cap_desc":
      cloned.sort((a, b) => (Number(b.market_cap) || -Infinity) - (Number(a.market_cap) || -Infinity));
      break;
    case "symbol_asc":
      cloned.sort((a, b) => String(a.symbol || "").localeCompare(String(b.symbol || "")));
      break;
    default:
      cloned.sort((a, b) => (Number(b.rs_2m_vs_spy_pct) || -Infinity) - (Number(a.rs_2m_vs_spy_pct) || -Infinity));
      break;
  }

  return cloned;
}

function renderTable(rows) {
  resultsBody.innerHTML = "";

  if (!rows.length) {
    emptyState.classList.remove("hidden");
    countText.textContent = "0 隻";
    return;
  }

  emptyState.classList.add("hidden");
  countText.textContent = `${rows.length} 隻`;

  const html = rows.map((row) => {
    const symbol = escapeHtml(row.symbol || "");
    const company = escapeHtml(row.company || "");
    const exchange = escapeHtml(row.exchange || "");

    return `
      <tr>
        <td>${symbol}</td>
        <td>${company}</td>
        <td>${exchange}</td>
        <td>${formatMarketCap(row.market_cap)}</td>
        <td>${formatPrice(row.current_price)}</td>
        <td class="${pctClass(row.one_month_return_pct)}">${formatPct(row.one_month_return_pct)}</td>
        <td class="${pctClass(row.two_month_return_pct)}">${formatPct(row.two_month_return_pct)}</td>
        <td class="${pctClass(row.rs_1m_vs_spy_pct)}">${formatPct(row.rs_1m_vs_spy_pct)}</td>
        <td class="${pctClass(row.rs_2m_vs_spy_pct)}">${formatPct(row.rs_2m_vs_spy_pct)}</td>
        <td>${formatPrice(row.high_3m)}</td>
        <td class="${pctClass(row.dist_from_3m_high_pct)}">${formatPct(row.dist_from_3m_high_pct)}</td>
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
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    renderSummary(data);
    renderRules(data);

    allRows = Array.isArray(data.results) ? data.results : [];
    currentSort = sortSelect.value || "rs_2m_vs_spy_pct_desc";
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
    countText.textContent = "0 隻";
  }
}

searchInput.addEventListener("input", applySearchAndSort);

sortSelect.addEventListener("change", () => {
  currentSort = sortSelect.value;
  applySearchAndSort();
});

loadData();
