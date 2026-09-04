let dataStore = null;
let allRows = [];
let filteredRows = [];
let currentMode = "momentum";
let currentSort = "";

const summaryCard = document.getElementById("summaryCard");
const rulesCard = document.getElementById("rulesCard");
const searchInput = document.getElementById("searchInput");
const sortSelect = document.getElementById("sortSelect");
const resultsHead = document.getElementById("resultsHead");
const resultsBody = document.getElementById("resultsBody");
const emptyState = document.getElementById("emptyState");
const countText = document.getElementById("countText");
const tableTitle = document.getElementById("tableTitle");
const tableHint = document.getElementById("tableHint");
const subtitle = document.getElementById("subtitle");
const tabs = [...document.querySelectorAll(".tab")];

function formatMarketCap(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";

  if (n >= 1_000_000_000_000) {
    return `$${(n / 1_000_000_000_000).toFixed(2)}T`;
  }

  if (n >= 1_000_000_000) {
    return `$${(n / 1_000_000_000).toFixed(2)}B`;
  }

  if (n >= 1_000_000) {
    return `$${(n / 1_000_000).toFixed(2)}M`;
  }

  return `$${n.toFixed(0)}`;
}

function formatDollarVolume(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";

  if (n >= 1_000_000_000) {
    return `$${(n / 1_000_000_000).toFixed(2)}B`;
  }

  if (n >= 1_000_000) {
    return `$${(n / 1_000_000).toFixed(1)}M`;
  }

  if (n >= 1_000) {
    return `$${(n / 1_000).toFixed(1)}K`;
  }

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

function signedPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";

  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
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

  if (!Number.isFinite(n)) {
    return "badge-marketcap-default";
  }

  if (n >= 100_000_000_000) {
    return "badge-marketcap-red";
  }

  if (n >= 50_000_000_000) {
    return "badge-marketcap-yellow";
  }

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

function getModeRows() {
  if (!dataStore) return [];

  if (currentMode === "breakout") {
    return Array.isArray(dataStore.breakout_results)
      ? dataStore.breakout_results
      : [];
  }

  if (Array.isArray(dataStore.momentum_results)) {
    return dataStore.momentum_results;
  }

  return Array.isArray(dataStore.results)
    ? dataStore.results
    : [];
}

function getRules() {
  const rules = dataStore?.rules || {};

  if (currentMode === "momentum") {
    return rules.momentum || rules;
  }

  return rules.breakout_setup || {};
}

function renderSummary() {
  const updated = dataStore?.generated_at || "Unknown";

  const momentumCount = Array.isArray(dataStore?.momentum_results)
    ? dataStore.momentum_results.length
    : (
        Array.isArray(dataStore?.results)
          ? dataStore.results.length
          : 0
      );

  const breakoutCount = Array.isArray(dataStore?.breakout_results)
    ? dataStore.breakout_results.length
    : 0;

  const label =
    currentMode === "breakout"
      ? "最新符合條件突破蓄勢股"
      : "最新符合條件短炒強勢股";

  const count =
    currentMode === "breakout"
      ? breakoutCount
      : momentumCount;

  summaryCard.innerHTML = `
    <div class="summary-label">
      ${label}
    </div>

    <div class="summary-count">
      ${count} 隻
    </div>

    <div class="summary-updated">
      最後更新：${escapeHtml(updated)}
    </div>
  `;
}

function renderRules() {
  const rules = getRules();

  if (currentMode === "breakout") {
    const excludeDays = Number(
      rules.exclude_recent_trading_days ?? 30
    );

    const bandPct = Number(
      rules.latest_close_band_pct ?? 5
    );

    const breakoutWindow = Number(
      rules.breakout_window_days ?? 30
    );

    const holdDays = Number(
      rules.hold_days ?? 10
    );

    const holdRequired = Number(
      rules.hold_required_days ?? 8
    );

    const maDays = Number(
      rules.ma_days ?? 200
    );

    const dollarDays = Number(
      rules.avg_dollar_volume_days ?? 10
    );

    const chips = [
      "只限美股",

      `市值 ≥ ${formatMarketCap(
        rules.market_cap_min ?? 5_000_000_000
      )}`,

      `最新收市 > MA${maDays}`,

      `距舊3年高位 ±${bandPct.toFixed(0)}%`,

      `${breakoutWindow}日內至少1日收市突破舊頂`,

      `${holdDays}日中 ≥ ${holdRequired}日收市企穩舊頂以上`,

      `${dollarDays}日平均成交額 > ${formatDollarVolume(
        rules.avg_dollar_volume_min ?? 20_000_000
      )}`
    ];

    rulesCard.innerHTML = `
      <div class="rules-title">
        突破蓄勢條件
      </div>

      <div class="rule-chips breakout-chips">
        ${chips
          .map(
            chip =>
              `<span class="rule-chip rule-chip-breakout">
                ${escapeHtml(chip)}
              </span>`
          )
          .join("")}
      </div>

      <div class="rules-extra">
        舊3年高位＝過去3年內最高 High，
        但排除最近 ${excludeDays} 個交易日。
        突破定義＝收市價正式高於舊頂。
      </div>
    `;

    return;
  }

  const benchmark =
    dataStore?.benchmark_symbol ||
    rules.benchmark_symbol ||
    "SPY";

  const chips = [
    "只限美股",

    `市值 ≥ ${formatMarketCap(
      rules.market_cap_min || 0
    )}`,

    `5日跑贏 ${benchmark} ≥ ${Number(
      rules.rs_5d_vs_spy_min_pct ?? 3
    ).toFixed(1)}%`,

    `20日跑贏 ${benchmark} ≥ ${Number(
      rules.rs_20d_vs_spy_min_pct ?? 8
    ).toFixed(1)}%`,

    `距52週高位 ≤ ${Number(
      rules.max_dist_from_52w_high_pct ?? 2
    ).toFixed(1)}%`
  ];

  const extra = [];

  if (
    Number.isFinite(
      Number(rules.spy_five_day_return_pct)
    )
  ) {
    extra.push(
      `${benchmark} 5D：${formatPct(
        rules.spy_five_day_return_pct
      )}`
    );
  }

  if (
    Number.isFinite(
      Number(rules.spy_twenty_day_return_pct)
    )
  ) {
    extra.push(
      `${benchmark} 20D：${formatPct(
        rules.spy_twenty_day_return_pct
      )}`
    );
  }

  rulesCard.innerHTML = `
    <div class="rules-title">
      目前條件
    </div>

    <div class="rule-chips">
      ${chips
        .map(
          chip =>
            `<span class="rule-chip">
              ${escapeHtml(chip)}
            </span>`
        )
        .join("")}
    </div>

    <div class="rules-extra">
      ${extra.map(escapeHtml).join(" ｜ ")}
    </div>
  `;
}

function setSortOptions() {
  if (currentMode === "breakout") {
    sortSelect.innerHTML = `
      <option value="dist_old_abs_asc">
        按最接近舊3年高位
      </option>

      <option value="hold_days_desc">
        按企穩日數 ↓
      </option>

      <option value="avg_dollar_volume_desc">
        按10日平均成交額 ↓
      </option>

      <option value="market_cap_desc">
        按市值 ↓
      </option>

      <option value="symbol_asc">
        按代號 A→Z
      </option>
    `;

    currentSort = "dist_old_abs_asc";

  } else {

    sortSelect.innerHTML = `
      <option value="rs_20d_vs_spy_pct_desc">
        按跑贏SPY(20D) ↓
      </option>

      <option value="rs_5d_vs_spy_pct_desc">
        按跑贏SPY(5D) ↓
      </option>

      <option value="dist_from_52w_high_pct_desc">
        按接近52週高位 ↑
      </option>

      <option value="market_cap_desc">
        按市值 ↓
      </option>

      <option value="symbol_asc">
        按代號 A→Z
      </option>
    `;

    currentSort = "rs_20d_vs_spy_pct_desc";
  }

  sortSelect.value = currentSort;
}

function renderTableHead() {
  if (currentMode === "breakout") {
    resultsHead.innerHTML = `
      <tr>
        <th>代號</th>
        <th>公司</th>
        <th>交易所</th>
        <th>市值</th>
        <th>最近收市</th>
        <th>MA200</th>
        <th>舊3年高位</th>
        <th>舊頂日期</th>
        <th>首次突破日期</th>
        <th>距舊頂</th>
        <th>10日企穩</th>
        <th>10日平均成交額</th>
      </tr>
    `;

  } else {

    resultsHead.innerHTML = `
      <tr>
        <th>代號</th>
        <th>公司</th>
        <th>交易所</th>
        <th>市值</th>
        <th>最近收市</th>
        <th>5日回報</th>
        <th>20日回報</th>
        <th>跑贏SPY(5D)</th>
        <th>跑贏SPY(20D)</th>
        <th>52週高位</th>
        <th>距52週高位</th>
      </tr>
    `;
  }
}

function sortRows(rows, sortKey) {
  const cloned = [...rows];

  switch (sortKey) {
    case "rs_20d_vs_spy_pct_desc":
      cloned.sort(
        (a, b) =>
          (Number(b.rs_20d_vs_spy_pct) || -Infinity) -
          (Number(a.rs_20d_vs_spy_pct) || -Infinity)
      );
      break;

    case "rs_5d_vs_spy_pct_desc":
      cloned.sort(
        (a, b) =>
          (Number(b.rs_5d_vs_spy_pct) || -Infinity) -
          (Number(a.rs_5d_vs_spy_pct) || -Infinity)
      );
      break;

    case "dist_from_52w_high_pct_desc":
      cloned.sort(
        (a, b) =>
          Math.abs(
            Number(a.dist_from_52w_high_pct) ||
              Infinity
          ) -
          Math.abs(
            Number(b.dist_from_52w_high_pct) ||
              Infinity
          )
      );
      break;

    case "dist_old_abs_asc":
      cloned.sort(
        (a, b) =>
          Math.abs(
            Number(a.dist_from_old_high_pct) ||
              Infinity
          ) -
          Math.abs(
            Number(b.dist_from_old_high_pct) ||
              Infinity
          )
      );
      break;

    case "hold_days_desc":
      cloned.sort(
        (a, b) =>
          (Number(b.hold_days_met) || 0) -
          (Number(a.hold_days_met) || 0)
      );
      break;

    case "avg_dollar_volume_desc":
      cloned.sort(
        (a, b) =>
          (Number(b.avg_dollar_volume_10d) || 0) -
          (Number(a.avg_dollar_volume_10d) || 0)
      );
      break;

    case "market_cap_desc":
      cloned.sort(
        (a, b) =>
          (Number(b.market_cap) || -Infinity) -
          (Number(a.market_cap) || -Infinity)
      );
      break;

    case "symbol_asc":
      cloned.sort(
        (a, b) =>
          String(a.symbol || "").localeCompare(
            String(b.symbol || "")
          )
      );
      break;

    default:
      break;
  }

  return cloned;
}

function renderMomentumRows(rows) {
  return rows
    .map(
      row => `
        <tr>
          <td class="symbol-cell">
            ${escapeHtml(row.symbol || "")}
          </td>

          <td class="company-cell">
            ${escapeHtml(row.company || "")}
          </td>

          <td>
            ${escapeHtml(row.exchange || "")}
          </td>

          <td>
            <span
              class="badge ${marketCapBadgeClass(
                row.market_cap
              )}"
            >
              ${formatMarketCap(row.market_cap)}
            </span>
          </td>

          <td>
            <span class="badge badge-price">
              ${formatPrice(row.recent_close)}
            </span>
          </td>

          <td
            class="${pctClass(
              row.five_day_return_pct
            )}"
          >
            ${formatPct(row.five_day_return_pct)}
          </td>

          <td
            class="${pctClass(
              row.twenty_day_return_pct
            )}"
          >
            ${formatPct(row.twenty_day_return_pct)}
          </td>

          <td
            class="${pctClass(
              row.rs_5d_vs_spy_pct
            )}"
          >
            ${formatPct(row.rs_5d_vs_spy_pct)}
          </td>

          <td
            class="${pctClass(
              row.rs_20d_vs_spy_pct
            )}"
          >
            ${formatPct(row.rs_20d_vs_spy_pct)}
          </td>

          <td>
            ${formatPrice(row.high_52w)}
          </td>

          <td
            class="${pctClass(
              row.dist_from_52w_high_pct
            )}"
          >
            ${formatPct(
              row.dist_from_52w_high_pct
            )}
          </td>
        </tr>
      `
    )
    .join("");
}

function renderBreakoutRows(rows) {
  return rows
    .map(row => {
      const dist = Number(
        row.dist_from_old_high_pct
      );

      const distanceClass =
        Number.isFinite(dist) &&
        Math.abs(dist) <= 2
          ? "near-high"
          : pctClass(dist);

      return `
        <tr>
          <td class="symbol-cell">
            ${escapeHtml(row.symbol || "")}
          </td>

          <td class="company-cell">
            ${escapeHtml(row.company || "")}
          </td>

          <td>
            ${escapeHtml(row.exchange || "")}
          </td>

          <td>
            <span
              class="badge ${marketCapBadgeClass(
                row.market_cap
              )}"
            >
              ${formatMarketCap(row.market_cap)}
            </span>
          </td>

          <td>
            <span class="badge badge-price">
              ${formatPrice(row.recent_close)}
            </span>
          </td>

          <td>
            ${formatPrice(row.ma200)}
          </td>

          <td>
            <span class="badge badge-old-high">
              ${formatPrice(row.old_3y_high)}
            </span>
          </td>

          <td>
            ${escapeHtml(
              row.old_3y_high_date || "-"
            )}
          </td>

          <td>
            ${escapeHtml(
              row.first_breakout_date || "-"
            )}
          </td>

          <td class="${distanceClass}">
            ${signedPct(
              row.dist_from_old_high_pct
            )}
          </td>

          <td>
            <span class="hold-badge">
              ${escapeHtml(
                row.hold_days_met ?? "-"
              )}/${escapeHtml(
                row.hold_days_total ?? 10
              )}
            </span>
          </td>

          <td class="dollar-volume">
            ${formatDollarVolume(
              row.avg_dollar_volume_10d
            )}
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderTable(rows) {
  resultsBody.innerHTML = "";

  if (!rows.length) {
    emptyState.classList.remove("hidden");
    countText.textContent = "顯示 0 隻";
    return;
  }

  emptyState.classList.add("hidden");

  countText.textContent =
    `顯示 ${rows.length} 隻`;

  resultsBody.innerHTML =
    currentMode === "breakout"
      ? renderBreakoutRows(rows)
      : renderMomentumRows(rows);
}

function applySearchAndSort() {
  const keyword =
    (searchInput.value || "")
      .trim()
      .toLowerCase();

  filteredRows = allRows.filter(row => {
    if (!keyword) return true;

    const symbol =
      String(row.symbol || "")
        .toLowerCase();

    const company =
      String(row.company || "")
        .toLowerCase();

    return (
      symbol.includes(keyword) ||
      company.includes(keyword)
    );
  });

  filteredRows =
    sortRows(
      filteredRows,
      currentSort
    );

  renderTable(filteredRows);
}

function updateModeUI() {
  tabs.forEach(tab =>
    tab.classList.toggle(
      "active",
      tab.dataset.mode === currentMode
    )
  );

  if (currentMode === "breakout") {
    subtitle.textContent =
      "突破蓄勢｜30日內突破舊3年高位、MA200、高位企穩及成交額";

    tableTitle.textContent =
      "突破蓄勢候選股";

    tableHint.textContent =
      "重點：最近30日已收市突破舊頂，而且最近10日大部分時間企穩舊頂以上。";

  } else {

    subtitle.textContent =
      "短炒強勢股｜市值、5日/20日跑贏 SPY、貼近 52 週高位";

    tableTitle.textContent =
      "符合條件股票";

    tableHint.textContent =
      "";
  }

  setSortOptions();
  renderSummary();
  renderRules();
  renderTableHead();

  allRows =
    getModeRows();

  applySearchAndSort();
}

async function loadData() {
  try {
    const response =
      await fetch(
        `results.json?t=${Date.now()}`,
        {
          cache: "no-store"
        }
      );

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`
      );
    }

    dataStore =
      await response.json();

    updateModeUI();

  } catch (error) {

    console.error(error);

    summaryCard.innerHTML = `
      <div class="summary-label">
        載入失敗
      </div>

      <div class="summary-updated">
        請稍後再試
      </div>
    `;

    rulesCard.innerHTML = `
      <div class="rules-title">
        目前條件
      </div>

      <div class="rules-extra">
        未能讀取 results.json
      </div>
    `;

    resultsBody.innerHTML = "";

    emptyState.classList.remove(
      "hidden"
    );

    countText.textContent =
      "顯示 0 隻";
  }
}

tabs.forEach(tab => {
  tab.addEventListener(
    "click",
    () => {
      currentMode =
        tab.dataset.mode;

      searchInput.value =
        "";

      updateModeUI();
    }
  );
});

searchInput.addEventListener(
  "input",
  applySearchAndSort
);

sortSelect.addEventListener(
  "change",
  () => {
    currentSort =
      sortSelect.value;

    applySearchAndSort();
  }
);

loadData();
