const state = { currentSymbol: null };

// ---- company avatars (generated monogram, no external image fetch) ----

const AVATAR_PALETTE = ["#5b7fff", "#8b6bff", "#22a6b3", "#2fbf74", "#eaad3f", "#ef5a63", "#d4af6a", "#3f8ee0"];
const AVATAR_STOPWORDS = /\b(Limited|Ltd\.?|Private|Pvt\.?|Company|Corporation|Corp\.?|Industries|India|Bank|Group)\b/gi;

function avatarInitials(name, symbol) {
  const words = (name || "").replace(AVATAR_STOPWORDS, "").trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (symbol || "??").replace(/\.NS$|\.BO$/, "").slice(0, 2).toUpperCase();
}

function avatarColor(symbol) {
  let hash = 0;
  for (let i = 0; i < (symbol || "").length; i++) hash = symbol.charCodeAt(i) + ((hash << 5) - hash);
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
}

// ---- generic chart helpers (plain CSS, no library) ----

// segments: [{label, value, color}]. centerText optional.
function donutHtml(segments, centerText) {
  const clean = segments.filter((s) => s.value > 0);
  const total = clean.reduce((sum, s) => sum + s.value, 0) || 1;
  let acc = 0;
  const stops = clean
    .map((s) => {
      const start = (acc / total) * 100;
      acc += s.value;
      const end = (acc / total) * 100;
      return `${s.color} ${start}% ${end}%`;
    })
    .join(", ");
  const legend = clean
    .map(
      (s) => `
      <div class="donut-legend-item">
        <span class="dot" style="background:${s.color};"></span>
        <span>${s.label}</span>
        <span class="donut-legend-val">${((s.value / total) * 100).toFixed(1)}%</span>
      </div>`
    )
    .join("");
  return `
    <div class="donut-wrap">
      <div class="donut" style="background: conic-gradient(${stops});">
        ${centerText ? `<div class="donut-center">${centerText}</div>` : ""}
      </div>
      <div class="donut-legend">${legend}</div>
    </div>
  `;
}

// Price-history line chart with hover crosshair + tooltip. `points`:
// [{date, close}], ascending by date. Renders into `container`.
let _lineChartSeq = 0;
function renderLineChart(container, points) {
  if (!points || points.length < 2) {
    container.innerHTML = '<div class="empty">Not enough price history available.</div>';
    return;
  }
  const W = 640, H = 200, padTop = 14, padBottom = 26, plotH = H - padTop - padBottom;
  const closes = points.map((p) => p.close);
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = max - min || 1;
  const n = points.length;
  const xAt = (i) => (i / (n - 1)) * W;
  const yAt = (v) => padTop + (1 - (v - min) / range) * plotH;

  const linePoints = points.map((p, i) => `${xAt(i).toFixed(2)},${yAt(p.close).toFixed(2)}`).join(" L");
  const areaPath = `M0,${(padTop + plotH).toFixed(2)} L${linePoints} L${W},${(padTop + plotH).toFixed(2)} Z`;
  const gradId = `lc-grad-${++_lineChartSeq}`;

  const first = points[0], last = points[points.length - 1];
  const changePct = first.close ? ((last.close - first.close) / first.close) * 100 : 0;
  const lineColor = changePct >= 0 ? "var(--green)" : "var(--red)";

  container.innerHTML = `
    <div class="line-chart-wrap">
      <svg class="line-chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <defs>
          <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${changePct >= 0 ? "#2fbf74" : "#ef5a63"}" stop-opacity="0.28"/>
            <stop offset="100%" stop-color="${changePct >= 0 ? "#2fbf74" : "#ef5a63"}" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <path d="${areaPath}" fill="url(#${gradId})" stroke="none"></path>
        <polyline points="${linePoints}" fill="none" stroke="${lineColor}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></polyline>
        <circle class="lc-endpoint" cx="${xAt(n - 1)}" cy="${yAt(last.close)}" r="4" fill="${lineColor}" stroke="var(--bg-elevated)" stroke-width="2"></circle>
        <line class="lc-crosshair" x1="0" y1="${padTop}" x2="0" y2="${padTop + plotH}" stroke="var(--border)" stroke-width="1" opacity="0"></line>
        <circle class="lc-hover-dot" r="4" fill="${lineColor}" stroke="var(--bg-elevated)" stroke-width="2" opacity="0"></circle>
      </svg>
      <div class="line-chart-tooltip"><div class="lct-date"></div><div class="lct-price"></div></div>
    </div>
    <div class="range-endlabels" style="margin-top:2px;">
      <span>${first.date}</span>
      <span style="color:${changePct >= 0 ? "var(--green)" : "var(--red)"};font-weight:600;">${changePct >= 0 ? "+" : ""}${changePct.toFixed(1)}% over period</span>
      <span>${last.date}</span>
    </div>
  `;

  const svg = container.querySelector(".line-chart-svg");
  const crosshair = container.querySelector(".lc-crosshair");
  const hoverDot = container.querySelector(".lc-hover-dot");
  const tooltip = container.querySelector(".line-chart-tooltip");
  const wrap = container.querySelector(".line-chart-wrap");

  function onMove(evt) {
    const rect = svg.getBoundingClientRect();
    const relX = ((evt.clientX - rect.left) / rect.width) * W;
    const idx = Math.max(0, Math.min(n - 1, Math.round((relX / W) * (n - 1))));
    const px = xAt(idx), py = yAt(points[idx].close);
    crosshair.setAttribute("x1", px);
    crosshair.setAttribute("x2", px);
    crosshair.setAttribute("opacity", "1");
    hoverDot.setAttribute("cx", px);
    hoverDot.setAttribute("cy", py);
    hoverDot.setAttribute("opacity", "1");
    tooltip.querySelector(".lct-date").textContent = points[idx].date;
    tooltip.querySelector(".lct-price").textContent = `₹${fmt(points[idx].close)}`;
    tooltip.classList.add("visible");
    tooltip.style.left = `${(px / W) * rect.width}px`;
    tooltip.style.top = `${(py / H) * rect.height}px`;
  }
  function onLeave() {
    crosshair.setAttribute("opacity", "0");
    hoverDot.setAttribute("opacity", "0");
    tooltip.classList.remove("visible");
  }
  svg.addEventListener("mousemove", onMove);
  svg.addEventListener("mouseleave", onLeave);
}

// segments: [{label, value, color}]
function stackBarHtml(segments) {
  const clean = segments.filter((s) => s.value > 0);
  const total = clean.reduce((sum, s) => sum + s.value, 0) || 1;
  const bar = clean.map((s) => `<div class="stackbar-seg" style="width:${(s.value / total) * 100}%;background:${s.color};"></div>`).join("");
  const legend = clean
    .map((s) => `<div class="stackbar-legend-item"><span class="dot" style="background:${s.color};"></span>${s.label} <b>${s.value}</b></div>`)
    .join("");
  return `<div class="stackbar">${bar}</div><div class="stackbar-legend">${legend}</div>`;
}

function avatarInitialsHtml(symbol, name, size) {
  const initials = avatarInitials(name, symbol);
  const bg = avatarColor(symbol || name || "");
  return `<div class="avatar avatar-${size}" style="background:${bg};">${initials}</div>`;
}

// Real logo when we have one (from yfinance's website -> Clearbit), falling
// back to the generated initials badge if there's no logo on file, or if the
// image fails to load (onerror swaps it out client-side).
function avatarHtml(symbol, name, size = "md", logoUrl) {
  if (!logoUrl) return avatarInitialsHtml(symbol, name, size);
  const initials = avatarInitials(name, symbol);
  const bg = avatarColor(symbol || name || "");
  return `<img src="${logoUrl}" alt="" class="avatar avatar-${size} avatar-img" data-initials="${initials}" data-bg="${bg}" data-size="${size}" onerror="window.__avatarFallback(this)">`;
}

window.__avatarFallback = function (imgEl) {
  const div = document.createElement("div");
  div.className = `avatar avatar-${imgEl.dataset.size}`;
  div.style.background = imgEl.dataset.bg;
  div.textContent = imgEl.dataset.initials;
  imgEl.replaceWith(div);
};

// ---- field descriptions (hover tooltips) ----

const DESCRIPTIONS = {
  // KPI grid
  "Price": "Last traded price on the exchange.",
  "Market Cap": "Total market value of all outstanding shares (price × shares outstanding).",
  "P/E (TTM)": "Price-to-Earnings using trailing twelve months' actual earnings. Higher = market is paying more per rupee/dollar of current profit.",
  "P/E (Fwd)": "Price-to-Earnings using next year's estimated earnings. Useful for comparing growth stocks where trailing earnings understate the picture.",
  "P/B": "Price-to-Book: market cap divided by book (net asset) value. Below 1 can mean the market values the company below its accounting net worth.",
  "ROE %": "Return on Equity: net income as a % of shareholders' equity — how efficiently the company turns equity capital into profit.",
  "D/E": "Debt-to-Equity: total debt relative to shareholders' equity. Higher = more balance-sheet leverage and financial risk.",
  "Rev Growth %": "Year-over-year revenue growth rate.",
  "52W Range": "Lowest and highest closing price over the past 52 weeks — gives a sense of where the current price sits in its recent range.",
  "Analyst Target": "Average of sell-side analysts' 12-month price targets for this stock.",
  "Consensus": "Aggregated sell-side analyst rating (e.g. strong buy, buy, hold, sell).",
  "Next Earnings": "Next scheduled quarterly/annual results date, where available.",

  // Raw data table
  "Name": "Full legal/registered name of the company.",
  "Sector": "Broad economic sector the company is classified under (e.g. Energy, Technology).",
  "Industry": "More specific industry classification within the sector.",
  "Country": "Country where the company is headquartered.",
  "Exchange": "Stock exchange this listing trades on.",
  "Currency": "Currency the price and financials are quoted in.",
  "Employees": "Full-time employee headcount, most recently reported.",
  "Business Summary": "Company's own description of what it does, as filed/published.",
  "Current Price": "Latest traded price.",
  "Previous Close": "Closing price on the last trading session.",
  "Open": "Price at market open for the current session.",
  "Day Low": "Lowest price traded so far in the current session.",
  "Day High": "Highest price traded so far in the current session.",
  "52-Week Low": "Lowest closing price in the past 52 weeks.",
  "52-Week High": "Highest closing price in the past 52 weeks.",
  "50-Day Avg": "50-day simple moving average of the closing price — a short-term trend indicator.",
  "200-Day Avg": "200-day simple moving average of the closing price — a long-term trend indicator.",
  "Volume": "Number of shares traded in the most recent session.",
  "Avg Volume (10d)": "Average daily trading volume over the last 10 sessions.",
  "Beta": "Volatility relative to the broader market — 1 means it moves with the market, above 1 means more volatile, below 1 means less.",
  "Enterprise Value": "Market cap plus net debt — the theoretical takeover cost, capital-structure-neutral.",
  "P/E (Trailing)": "Price ÷ trailing twelve months' EPS.",
  "P/E (Forward)": "Price ÷ next year's estimated EPS.",
  "PEG Ratio": "P/E divided by expected earnings growth rate — a P/E adjusted for growth; near 1 is often considered fairly priced.",
  "Price/Book": "Market cap ÷ book value of equity.",
  "Price/Sales (TTM)": "Market cap ÷ trailing twelve months' revenue — useful for unprofitable companies where P/E doesn't apply.",
  "EV/Revenue": "Enterprise Value ÷ revenue — capital-structure-neutral valuation multiple on the top line.",
  "EV/EBITDA": "Enterprise Value ÷ EBITDA — a common cross-company valuation multiple that ignores financing and depreciation policy differences.",
  "EPS (Trailing)": "Earnings per share over the trailing twelve months.",
  "EPS (Forward)": "Analyst-estimated earnings per share for the next year.",
  "Book Value/Share": "Shareholders' equity divided by shares outstanding.",
  "Revenue/Share": "Total revenue divided by shares outstanding.",
  "Gross Margin": "Gross profit (revenue minus cost of goods sold) as a % of revenue.",
  "Operating Margin": "Operating profit as a % of revenue — profitability from core operations before interest and tax.",
  "Net Margin": "Net income as a % of revenue — the bottom-line profitability after all costs.",
  "EBITDA Margin": "EBITDA as a % of revenue.",
  "Return on Assets": "Net income as a % of total assets — how efficiently assets generate profit.",
  "Return on Equity": "Net income as a % of shareholders' equity.",
  "Revenue Growth (YoY)": "Revenue growth versus the same period a year ago.",
  "Earnings Growth (YoY)": "Earnings growth versus the same period a year ago.",
  "Earnings Growth (QoQ)": "Earnings growth versus the prior quarter.",
  "Total Cash": "Cash and cash equivalents on the balance sheet.",
  "Total Debt": "Total interest-bearing debt (short- and long-term) on the balance sheet.",
  "Debt/Equity": "Total debt relative to shareholders' equity — a leverage/solvency measure.",
  "Current Ratio": "Current assets ÷ current liabilities — ability to cover short-term obligations. Below 1 can signal liquidity stress.",
  "Quick Ratio": "Like the current ratio but excludes inventory — a stricter short-term liquidity measure.",
  "Total Revenue": "Total revenue over the trailing twelve months.",
  "EBITDA": "Earnings before interest, tax, depreciation and amortization — a proxy for operating cash generation.",
  "Operating Cash Flow": "Cash generated from core business operations.",
  "Free Cash Flow": "Operating cash flow minus capital expenditure — cash available after reinvesting in the business.",
  "Dividend Rate": "Annualized dividend per share in absolute currency terms.",
  "Dividend Yield": "Annual dividend per share as a % of the current price.",
  "Payout Ratio": "% of earnings paid out as dividends.",
  "Ex-Dividend Date": "Date on/after which a buyer is not entitled to the next declared dividend.",
  "5Y Avg Div Yield": "Average dividend yield over the trailing 5 years.",
  "Shares Outstanding": "Total number of shares currently issued.",
  "Float Shares": "Shares available for public trading, excluding closely-held/restricted stock.",
  "Held by Insiders": "% of shares held by company insiders (promoters, management, directors).",
  "Held by Institutions": "% of shares held by institutional investors (mutual funds, FIIs, etc.).",
  "Shares Short": "Number of shares currently sold short.",
  "# Analysts": "Number of sell-side analysts covering this stock.",
  "Consensus Rating": "Aggregated analyst recommendation.",
  "Target Low": "Lowest 12-month price target among covering analysts.",
  "Target Mean": "Average 12-month price target among covering analysts.",
  "Target High": "Highest 12-month price target among covering analysts.",
};

function tipAttrs(label, baseClass) {
  const desc = DESCRIPTIONS[label];
  const cls = desc ? [baseClass, "has-tip"].filter(Boolean).join(" ") : baseClass;
  const clsAttr = cls ? ` class="${cls}"` : "";
  const tipAttr = desc ? ` data-tip="${desc.replace(/"/g, "&quot;")}"` : "";
  return clsAttr + tipAttr;
}

// ---- helpers ----

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed: ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

function fmt(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (typeof n !== "number") return n;
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + "M";
  return n.toFixed(digits);
}

// Rule-based truncation (first ~2 sentences), not AI summarization — keeps
// long free-text fields like Yahoo's business summary to a glance-length blurb.
function summarizeText(text, maxSentences = 2, maxChars = 260) {
  const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
  let result = sentences.slice(0, maxSentences).join(" ").trim();
  if (result.length > maxChars) result = result.slice(0, maxChars).trim() + "…";
  else if (sentences.length > maxSentences) result += " …";
  return result;
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById(`view-${name}`).classList.remove("hidden");
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
  const btn = document.querySelector(`.nav-btn[data-view="${name}"]`);
  if (btn) btn.classList.add("active");
}

// ---- watchlist view ----

// Generic type-ahead dropdown: as the user types into `inputEl`, queries the
// local NSE universe (Indian companies only, no network round trip beyond
// localhost) and shows matches in `dropdownEl` positioned under the input.
function setupAutocomplete(inputEl, dropdownEl, onPick) {
  let debounceTimer = null;

  function hide() {
    dropdownEl.classList.add("hidden");
    dropdownEl.innerHTML = "";
  }

  async function runQuery(q) {
    if (!q.trim()) {
      hide();
      return;
    }
    try {
      const data = await api(`/api/universe?q=${encodeURIComponent(q)}&limit=10`);
      dropdownEl.innerHTML = "";
      if (!data.results.length) {
        dropdownEl.appendChild(el('<div class="ac-empty">No matching NSE-listed companies.</div>'));
      } else {
        data.results.forEach((r) => {
          const item = el(`
            <div class="ac-item">
              ${avatarHtml(r.nse_symbol, r.name, "sm")}
              <div class="name"><span class="symbol">${r.nse_symbol}</span> — ${r.name}</div>
              <span class="add-hint">Add</span>
            </div>
          `);
          item.addEventListener("mousedown", (e) => {
            e.preventDefault();
            onPick(r);
            hide();
          });
          dropdownEl.appendChild(item);
        });
      }
      dropdownEl.classList.remove("hidden");
    } catch (e) {
      dropdownEl.innerHTML = `<div class="ac-empty">Error: ${e.message}</div>`;
      dropdownEl.classList.remove("hidden");
    }
  }

  inputEl.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const q = inputEl.value;
    debounceTimer = setTimeout(() => runQuery(q), 150);
  });
  inputEl.addEventListener("focus", () => {
    if (inputEl.value.trim()) runQuery(inputEl.value);
  });
  document.addEventListener("click", (e) => {
    if (e.target !== inputEl) hide();
  });
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide();
  });
}

setupAutocomplete(
  document.getElementById("search-input"),
  document.getElementById("search-dropdown"),
  async (r) => {
    await api("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ symbol: r.symbol, name: r.name, sector: null }),
    });
    document.getElementById("search-input").value = "";
    loadWatchlist();
  }
);

// ---- portfolio view ----

let _selectedHolding = null;

setupAutocomplete(
  document.getElementById("holding-search-input"),
  document.getElementById("holding-search-dropdown"),
  (r) => {
    _selectedHolding = r;
    document.getElementById("holding-search-input").value = `${r.nse_symbol} — ${r.name}`;
    document.getElementById("holding-selected").textContent = `Selected: ${r.nse_symbol} — ${r.name}`;
    document.getElementById("holding-add-btn").disabled = false;
  }
);

document.getElementById("holding-search-input").addEventListener("input", () => {
  _selectedHolding = null;
  document.getElementById("holding-add-btn").disabled = true;
  document.getElementById("holding-selected").textContent = "No company selected yet — search above.";
});

document.getElementById("holding-add-btn").addEventListener("click", async () => {
  if (!_selectedHolding) return;
  const qty = parseFloat(document.getElementById("holding-qty").value);
  const price = parseFloat(document.getElementById("holding-price").value);
  const date = document.getElementById("holding-date").value;
  if (!qty || !price) return;
  await api("/api/holdings", {
    method: "POST",
    body: JSON.stringify({
      symbol: _selectedHolding.symbol,
      name: _selectedHolding.name,
      quantity: qty,
      buy_price: price,
      buy_date: date || null,
    }),
  });
  document.getElementById("holding-search-input").value = "";
  document.getElementById("holding-qty").value = "";
  document.getElementById("holding-price").value = "";
  document.getElementById("holding-date").value = "";
  document.getElementById("holding-selected").textContent = "No company selected yet — search above.";
  document.getElementById("holding-add-btn").disabled = true;
  _selectedHolding = null;
  loadHoldings();
});

const QUALITATIVE_OPTIONS = {
  management_quality: ["good", "average", "poor"],
  governance_risk: ["low", "medium", "high"],
  regulatory_risk: ["low", "medium", "high"],
  competitive_moat: ["strong", "moderate", "weak"],
};
const QUALITATIVE_LABELS = {
  management_quality: "Management Quality",
  governance_risk: "Governance Risk",
  regulatory_risk: "Regulatory / Policy Risk",
  competitive_moat: "Competitive Moat",
};

function selectOptionsHtml(field, current) {
  const opts = QUALITATIVE_OPTIONS[field]
    .map((v) => `<option value="${v}" ${current === v ? "selected" : ""}>${v[0].toUpperCase()}${v.slice(1)}</option>`)
    .join("");
  return `<option value="">—</option>${opts}`;
}

async function loadHoldings() {
  const box = document.getElementById("holdings-list");
  const summaryEl = document.getElementById("holdings-summary");
  box.innerHTML = '<div class="empty">Loading…</div>';
  const holdings = await api("/api/holdings");
  if (!holdings.length) {
    summaryEl.textContent = "";
    box.innerHTML = '<div class="empty">No holdings yet — add one above.</div>';
    return;
  }

  let totalInvested = 0, totalCurrent = 0;
  holdings.forEach((h) => {
    if (h.invested_value) totalInvested += h.invested_value;
    if (h.current_value) totalCurrent += h.current_value;
  });
  const totalPnl = totalCurrent - totalInvested;
  const totalPnlPct = totalInvested ? (totalPnl / totalInvested) * 100 : 0;
  summaryEl.innerHTML = `Invested <strong>₹${fmt(totalInvested)}</strong> · Current <strong>₹${fmt(totalCurrent)}</strong> · P&amp;L <strong class="${totalPnl >= 0 ? "pnl-pos" : "pnl-neg"}">${totalPnl >= 0 ? "+" : ""}₹${fmt(totalPnl)} (${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(1)}%)</strong>`;

  box.innerHTML = "";

  // Allocation — weight of each holding in the portfolio by current value,
  // as both a donut (shape of the whole) and a bar list (exact figures).
  if (totalCurrent > 0 && holdings.length > 1) {
    const sortedByValue = holdings.slice().sort((a, b) => (b.current_value || 0) - (a.current_value || 0));
    const donutPanel = el(`<div style="margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid var(--border-soft);"></div>`);
    donutPanel.innerHTML = donutHtml(
      sortedByValue.map((h) => ({
        label: h.company_symbol.replace(/\.NS$/, ""),
        value: h.current_value || 0,
        color: avatarColor(h.company_symbol),
      })),
      `₹${fmt(totalCurrent)}`
    );
    box.appendChild(donutPanel);

    const allocPanel = el(`<div class="hbar-chart" style="margin-bottom:20px;padding-bottom:18px;border-bottom:1px solid var(--border-soft);"></div>`);
    sortedByValue.forEach((h) => {
        const weightPct = ((h.current_value || 0) / totalCurrent) * 100;
        allocPanel.appendChild(el(`
          <div class="hbar-row">
            <div class="hbar-label">${h.company_symbol.replace(/\.NS$/, "")}</div>
            <div class="hbar-track"><div class="hbar-fill" style="width:${Math.max(2, weightPct)}%"></div></div>
            <div class="hbar-value">${weightPct.toFixed(1)}%</div>
          </div>
        `));
      });
    box.appendChild(allocPanel);
  }

  const maxAbsPnlPct = Math.max(...holdings.map((h) => Math.abs(h.pnl_pct || 0)), 1);

  holdings.forEach((h) => {
    const pnlClass = h.pnl >= 0 ? "pnl-pos" : "pnl-neg";
    const holisticLabel = h.holistic_recommendation ? h.holistic_recommendation.label : "—";
    const holisticClass = holisticLabel.toLowerCase().replace(/\s+/g, "-");

    const row = el(`
      <div class="holding-row">
        <div class="holding-summary">
          <div class="meta row-with-avatar">
            ${avatarHtml(h.company_symbol, h.company_name, "md", h.logo_url)}
            <div>
              <span class="symbol">${h.company_symbol}</span> — <span class="name">${h.company_name || ""}</span>
              <div class="name">Qty ${h.quantity} @ ₹${fmt(h.buy_price)}${h.buy_date ? " on " + h.buy_date : ""}</div>
            </div>
          </div>
          <div class="holding-figures">
            <div class="holding-figure"><div class="label">Current</div><div class="value">₹${fmt(h.current_price)}</div></div>
            <div class="holding-figure"><div class="label">P&amp;L</div><div class="value ${pnlClass}">${h.pnl >= 0 ? "+" : ""}₹${fmt(h.pnl)} (${h.pnl_pct >= 0 ? "+" : ""}${fmt(h.pnl_pct)}%)</div></div>
          </div>
          <span class="rec-badge rec-holding rec-${holisticClass}">${holisticLabel}</span>
          <button class="secondary toggle-btn">Details</button>
          <button class="danger delete-btn">Remove</button>
        </div>
        <div class="dbar-track" style="margin:0 4px 12px;">
          <div class="dbar-neg-side" style="width:${h.pnl < 0 ? Math.min(50, (Math.abs(h.pnl_pct || 0) / maxAbsPnlPct) * 50) : 0}%;"></div>
          <div class="dbar-pos-side" style="width:${h.pnl >= 0 ? Math.min(50, (Math.abs(h.pnl_pct || 0) / maxAbsPnlPct) * 50) : 0}%;"></div>
          <div class="dbar-zero"></div>
        </div>
        <div class="holding-details hidden"></div>
      </div>
    `);

    row.querySelector(".delete-btn").addEventListener("click", async () => {
      await api(`/api/holdings/${h.id}`, { method: "DELETE" });
      loadHoldings();
    });

    const detailsEl = row.querySelector(".holding-details");
    row.querySelector(".toggle-btn").addEventListener("click", () => {
      detailsEl.classList.toggle("hidden");
      if (!detailsEl.classList.contains("hidden") && !detailsEl.dataset.loaded) {
        renderHoldingDetails(detailsEl, h);
        detailsEl.dataset.loaded = "1";
      }
    });

    box.appendChild(row);
  });
}

function renderHoldingDetails(detailsEl, h) {
  const q = h.qualitative || {};
  const financialReasoning = (h.financial_recommendation?.reasoning || []).map((r) => `<li>${r}</li>`).join("");
  const cautions = (h.holistic_recommendation?.cautions || []).map((c) => `<li class="caution-item">${c}</li>`).join("");
  const positives = (h.holistic_recommendation?.positives || []).map((p) => `<li class="positive-item">${p}</li>`).join("");

  detailsEl.innerHTML = "";
  detailsEl.appendChild(el(`
    <div class="holding-detail-block">
      <div class="section-title">Financial Signal (${h.financial_recommendation?.label || "—"})</div>
      <ul class="rec-reasoning">${financialReasoning}</ul>

      <div class="section-title" style="margin-top:16px;">Non-Financial Factors (your assessment)</div>
      <div class="qual-grid">
        <div>
          <label>${QUALITATIVE_LABELS.management_quality}</label>
          <select data-field="management_quality">${selectOptionsHtml("management_quality", q.management_quality)}</select>
        </div>
        <div>
          <label>${QUALITATIVE_LABELS.governance_risk}</label>
          <select data-field="governance_risk">${selectOptionsHtml("governance_risk", q.governance_risk)}</select>
        </div>
        <div>
          <label>${QUALITATIVE_LABELS.regulatory_risk}</label>
          <select data-field="regulatory_risk">${selectOptionsHtml("regulatory_risk", q.regulatory_risk)}</select>
        </div>
        <div>
          <label>${QUALITATIVE_LABELS.competitive_moat}</label>
          <select data-field="competitive_moat">${selectOptionsHtml("competitive_moat", q.competitive_moat)}</select>
        </div>
      </div>
      <label style="margin-top:10px;display:block;">Future Prospects</label>
      <textarea data-field="future_prospects" placeholder="Your outlook on where this business is headed...">${q.future_prospects || ""}</textarea>
      <label style="margin-top:10px;display:block;">Other Notes</label>
      <textarea data-field="notes" placeholder="Any other non-financial considerations...">${q.notes || ""}</textarea>
      <button class="qual-save-btn" style="margin-top:10px;">Save & Recompute Consensus</button>
      <span class="qual-saved-msg name" style="margin-left:10px;"></span>

      ${cautions ? `<div class="section-title" style="margin-top:16px;">Cautions</div><ul class="rec-reasoning">${cautions}</ul>` : ""}
      ${positives ? `<div class="section-title" style="margin-top:16px;">Positives</div><ul class="rec-reasoning">${positives}</ul>` : ""}
      <div class="rec-disclaimer" style="margin-top:14px;">${h.holistic_recommendation?.disclaimer || ""}</div>
    </div>
  `));

  detailsEl.querySelector(".qual-save-btn").addEventListener("click", async () => {
    const payload = {};
    detailsEl.querySelectorAll("[data-field]").forEach((elm) => {
      payload[elm.dataset.field] = elm.value;
    });
    await api(`/api/company/${encodeURIComponent(h.company_symbol)}/qualitative`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    detailsEl.querySelector(".qual-saved-msg").textContent = "Saved — recomputing…";
    loadHoldings();
  });
}

async function loadWatchlist() {
  const box = document.getElementById("watchlist-table");
  box.innerHTML = '<div class="empty">Loading…</div>';
  const companies = await api("/api/watchlist");
  if (!companies.length) {
    box.innerHTML = '<div class="empty">No companies yet — search above to add one.</div>';
    return;
  }
  box.innerHTML = "";
  for (const c of companies) {
    const row = el(`
      <div class="watch-row">
        <div class="meta row-with-avatar">
          ${avatarHtml(c.symbol, c.name, "md")}
          <div>
            <span class="symbol">${c.symbol}</span> — <span class="name">${c.name || ""}</span>
            <div class="name">${c.sector || ""}</div>
          </div>
        </div>
        <div class="watch-actions" style="display:flex;gap:8px;align-items:center;">
          <span class="rec-badge rec-pill">…</span>
          <span class="badge">loading…</span>
          <button class="secondary open-btn">Open</button>
          <button class="danger remove-btn">Remove</button>
        </div>
      </div>
    `);
    row.querySelector(".open-btn").addEventListener("click", () => openCompany(c.symbol));
    row.querySelector(".remove-btn").addEventListener("click", async () => {
      await api(`/api/watchlist/${encodeURIComponent(c.symbol)}`, { method: "DELETE" });
      loadWatchlist();
    });
    box.appendChild(row);

    api(`/api/company/${encodeURIComponent(c.symbol)}`)
      .then((data) => {
        const badge = row.querySelector(".badge");
        const price = data.snapshot.price;
        const n = data.concerns.length;
        badge.textContent = `${price !== null && price !== undefined ? "₹" + fmt(price) : "—"} · ${n} flag${n === 1 ? "" : "s"}`;
        if (n >= 2) badge.classList.add("high");
        else if (n === 1) badge.classList.add("medium");
        else badge.classList.add("low");

        if (data.snapshot.logo_url) {
          const avatarEl = row.querySelector(".avatar");
          if (avatarEl) avatarEl.outerHTML = avatarHtml(c.symbol, c.name, "md", data.snapshot.logo_url);
        }

        const recBadge = row.querySelector(".rec-pill");
        if (data.recommendation) {
          recBadge.textContent = data.recommendation.label;
          recBadge.classList.add(`rec-${data.recommendation.label.toLowerCase()}`);
        } else {
          recBadge.remove();
        }
      })
      .catch(() => {
        row.querySelector(".badge").textContent = "no data";
        const recBadge = row.querySelector(".rec-pill");
        if (recBadge) recBadge.remove();
      });
  }
}

// ---- company workspace view ----

async function openCompany(symbol, name) {
  if (name) {
    try {
      await api(`/api/company/${encodeURIComponent(symbol)}/ensure`, {
        method: "POST",
        body: JSON.stringify({ name }),
      });
    } catch (e) {
      // fall through — the snapshot fetch below will surface any real error
    }
  }
  const activeBtn = document.querySelector(".nav-btn.active");
  state.returnView = activeBtn ? activeBtn.dataset.view : "watchlist";
  state.currentSymbol = symbol;
  showView("company");
  const content = document.getElementById("company-content");
  content.innerHTML = '<div class="empty">Loading…</div>';

  let data;
  try {
    data = await api(`/api/company/${encodeURIComponent(symbol)}`);
  } catch (e) {
    content.innerHTML = `<div class="empty">Error loading ${symbol}: ${e.message}</div>`;
    return;
  }
  const s = data.snapshot;

  const rangeLow = s["52w_low"], rangeHigh = s["52w_high"], rangePrice = s.price;
  let rangeChart = `<div class="value">₹${fmt(rangeLow)} – ₹${fmt(rangeHigh)}</div>`;
  if (rangeLow !== null && rangeHigh !== null && rangePrice !== null && rangeHigh > rangeLow) {
    const pct = Math.max(0, Math.min(100, ((rangePrice - rangeLow) / (rangeHigh - rangeLow)) * 100));
    rangeChart = `
      <div class="range-current">₹${fmt(rangePrice)} <span style="color:var(--text-faint);font-weight:400;">now</span></div>
      <div class="range-track"><div class="range-fill" style="width:${pct}%"></div><div class="range-marker" style="left:${pct}%"></div></div>
      <div class="range-endlabels"><span>₹${fmt(rangeLow)} low</span><span>₹${fmt(rangeHigh)} high</span></div>
    `;
  }

  const converted = s.orig_currency && s.orig_currency !== "INR" && s.currency === "INR";
  const fxNote = converted
    ? `<div class="name" style="margin-top:8px;">All ₹ figures converted from ${s.orig_currency} at 1 ${s.orig_currency} = ₹${s.fx_rate} (live FX via yfinance).</div>`
    : "";

  content.innerHTML = "";
  content.appendChild(el(`
    <div class="panel">
      <div class="row-with-avatar" style="margin-bottom:14px;">
        ${avatarHtml(s.symbol, s.name, "lg", s.logo_url)}
        <h2 style="margin:0;font-size:16px;color:var(--text);text-transform:none;letter-spacing:0;">${s.name} (${s.symbol})</h2>
      </div>
      <div class="kpi-grid">
        <div class="kpi"><div${tipAttrs("Price", "label")}>Price</div><div class="value">₹${fmt(s.price)}</div></div>
        <div class="kpi"><div${tipAttrs("Market Cap", "label")}>Market Cap</div><div class="value">₹${fmt(s.market_cap)}</div></div>
        <div class="kpi"><div${tipAttrs("P/E (TTM)", "label")}>P/E (TTM)</div><div class="value">${fmt(s.pe_trailing)}</div></div>
        <div class="kpi"><div${tipAttrs("P/E (Fwd)", "label")}>P/E (Fwd)</div><div class="value">${fmt(s.pe_forward)}</div></div>
        <div class="kpi"><div${tipAttrs("P/B", "label")}>P/B</div><div class="value">${fmt(s.price_to_book)}</div></div>
        <div class="kpi"><div${tipAttrs("ROE %", "label")}>ROE %</div><div class="value">${fmt(s.roe_pct)}</div></div>
        <div class="kpi"><div${tipAttrs("D/E", "label")}>D/E</div><div class="value">${fmt(s.debt_to_equity)}</div></div>
        <div class="kpi"><div${tipAttrs("Rev Growth %", "label")}>Rev Growth %</div><div class="value">${fmt(s.revenue_growth_pct)}</div></div>
        <div class="kpi range-chart"><div${tipAttrs("52W Range", "label")}>52W Range</div>${rangeChart}</div>
        <div class="kpi"><div${tipAttrs("Analyst Target", "label")}>Analyst Target</div><div class="value">₹${fmt(s.target_mean_price)}</div></div>
        <div class="kpi"><div${tipAttrs("Consensus", "label")}>Consensus</div><div class="value">${s.analyst_recommendation || "—"}</div><div class="kpi-disclaimer">Street views shown for reference only — not our call. Do your own research.</div></div>
        <div class="kpi"><div${tipAttrs("Next Earnings", "label")}>Next Earnings</div><div class="value">${s.next_earnings_date || "—"}</div></div>
      </div>
      ${fxNote}
    </div>
  `));

  // Price history line chart
  const historyPanel = el(`
    <div class="panel">
      <h2>Price History</h2>
      <div class="period-row">
        <button class="period-btn" data-period="1mo">1M</button>
        <button class="period-btn" data-period="3mo">3M</button>
        <button class="period-btn active" data-period="6mo">6M</button>
        <button class="period-btn" data-period="1y">1Y</button>
        <button class="period-btn" data-period="2y">2Y</button>
      </div>
      <div id="price-history-chart"><div class="empty">Loading…</div></div>
    </div>
  `);
  content.appendChild(historyPanel);
  const chartBox = historyPanel.querySelector("#price-history-chart");

  async function loadHistory(period) {
    chartBox.innerHTML = '<div class="empty">Loading…</div>';
    try {
      const points = await api(`/api/company/${encodeURIComponent(symbol)}/history?period=${period}`);
      renderLineChart(chartBox, points);
    } catch (e) {
      chartBox.innerHTML = `<div class="empty">Could not load price history: ${e.message}</div>`;
    }
  }
  historyPanel.querySelectorAll(".period-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      historyPanel.querySelectorAll(".period-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      loadHistory(btn.dataset.period);
    });
  });
  loadHistory("6mo");

  const rec = data.recommendation;
  if (rec) {
    const recClass = rec.label.toLowerCase();
    const reasonItems = rec.reasoning.map((r) => `<li>${r}</li>`).join("");
    content.appendChild(el(`
      <div class="panel rec-panel rec-${recClass}">
        <div class="rec-top">
          <div class="rec-badge rec-${recClass}">${rec.label}</div>
          <div class="rec-upside">${rec.upside_pct !== null && rec.upside_pct !== undefined ? `Target implies ${rec.upside_pct > 0 ? "+" : ""}${rec.upside_pct}%` : ""}</div>
        </div>
        <ul class="rec-reasoning">${reasonItems}</ul>
        <div class="rec-disclaimer">${rec.disclaimer}</div>
      </div>
    `));
  }

  const concernsPanel = el(`<div class="panel"><h2>Concern Flags</h2><div id="concerns-box"></div></div>`);
  content.appendChild(concernsPanel);
  const cbox = concernsPanel.querySelector("#concerns-box");
  if (!data.concerns.length) {
    cbox.appendChild(el('<div class="empty">No rule-based concerns flagged.</div>'));
  } else {
    data.concerns.forEach((c) => {
      cbox.appendChild(el(`<div class="concern-item"><span class="badge ${c.severity}">${c.severity}</span> ${c.message}</div>`));
    });
  }

  // Margins chart — pulled from the same Profitability group shown in Raw
  // Data below, visualized instead of read as four separate table rows.
  const profGroup = (data.raw || []).find((g) => g.group === "Profitability");
  if (profGroup) {
    const wanted = [
      ["grossMargins", "Gross"],
      ["operatingMargins", "Operating"],
      ["profitMargins", "Net"],
      ["ebitdaMargins", "EBITDA"],
    ];
    const rows = wanted
      .map(([key, label]) => ({ label, value: profGroup.fields.find((f) => f.key === key)?.value }))
      .filter((r) => typeof r.value === "number");
    if (rows.length) {
      const maxAbs = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
      const marginsPanel = el(`<div class="panel"><h2>Margins</h2><div class="hbar-chart"></div></div>`);
      const chartBox = marginsPanel.querySelector(".hbar-chart");
      rows.forEach((r) => {
        const widthPct = Math.max(2, (Math.abs(r.value) / maxAbs) * 100);
        chartBox.appendChild(el(`
          <div class="hbar-row">
            <div class="hbar-label">${r.label}</div>
            <div class="hbar-track"><div class="hbar-fill" style="width:${widthPct}%; background:${r.value < 0 ? "var(--red)" : "var(--accent)"};"></div></div>
            <div class="hbar-value">${r.value.toFixed(1)}%</div>
          </div>
        `));
      });
      content.appendChild(marginsPanel);
    }
  }

  // Ownership pie — insiders vs institutions vs public float, from the same
  // Ownership & Shares group shown in Raw Data below.
  const ownGroup = (data.raw || []).find((g) => g.group === "Ownership & Shares");
  if (ownGroup) {
    const insiders = ownGroup.fields.find((f) => f.key === "heldPercentInsiders")?.value;
    const institutions = ownGroup.fields.find((f) => f.key === "heldPercentInstitutions")?.value;
    if (typeof insiders === "number" || typeof institutions === "number") {
      const ins = insiders || 0;
      const inst = institutions || 0;
      const other = Math.max(0, 100 - ins - inst);
      const ownershipPanel = el(`
        <div class="panel">
          <h2>Ownership</h2>
          ${donutHtml(
            [
              { label: "Insiders / Promoters", value: ins, color: "var(--accent)" },
              { label: "Institutions", value: inst, color: "var(--gold)" },
              { label: "Public / Other", value: other, color: "var(--panel-3)" },
            ],
            "Held<br>by"
          )}
        </div>
      `);
      content.appendChild(ownershipPanel);
    }
  }

  // Raw data — every equity-research parameter yfinance exposes, grouped
  const rawPanel = el(`<div class="panel"><h2>Raw Data (All Parameters)</h2><div id="raw-box"></div></div>`);
  content.appendChild(rawPanel);
  const rawBox = rawPanel.querySelector("#raw-box");
  if (!data.raw || !data.raw.length) {
    rawBox.appendChild(el('<div class="empty">No raw data available.</div>'));
  } else {
    data.raw.forEach((group) => {
      const rows = group.fields
        .map((f) => {
          let displayValue = f.value === null || f.value === undefined || f.value === "" ? "—" : String(f.value);
          if (f.key === "longBusinessSummary" && typeof f.value === "string") displayValue = summarizeText(f.value);
          return `<tr><td${tipAttrs(f.label)}>${f.label}</td><td>${displayValue}</td></tr>`;
        })
        .join("");
      rawBox.appendChild(el(`
        <div style="margin-bottom:14px;">
          <div class="section-title">${group.group}</div>
          <table><tbody>${rows}</tbody></table>
        </div>
      `));
    });
  }

  // Thesis
  const thesisPanel = el(`
    <div class="panel">
      <h2>Thesis & Catalysts</h2>
      <label>Thesis</label>
      <textarea id="thesis-text" placeholder="Investment thesis..."></textarea>
      <label style="margin-top:8px;display:block;">Key Risks</label>
      <textarea id="thesis-risks" placeholder="Key risks..."></textarea>
      <label style="margin-top:8px;display:block;">Catalysts</label>
      <textarea id="thesis-catalysts" placeholder="Catalysts to watch..."></textarea>
      <button id="thesis-save-btn" style="margin-top:10px;">Save</button>
      <span id="thesis-saved-msg" class="name" style="margin-left:10px;"></span>
    </div>
  `);
  content.appendChild(thesisPanel);
  const thesis = await api(`/api/company/${encodeURIComponent(symbol)}/thesis`);
  thesisPanel.querySelector("#thesis-text").value = thesis.thesis_text || "";
  thesisPanel.querySelector("#thesis-risks").value = thesis.risks || "";
  thesisPanel.querySelector("#thesis-catalysts").value = thesis.catalysts || "";
  thesisPanel.querySelector("#thesis-save-btn").addEventListener("click", async () => {
    await api(`/api/company/${encodeURIComponent(symbol)}/thesis`, {
      method: "PUT",
      body: JSON.stringify({
        thesis_text: thesisPanel.querySelector("#thesis-text").value,
        risks: thesisPanel.querySelector("#thesis-risks").value,
        catalysts: thesisPanel.querySelector("#thesis-catalysts").value,
      }),
    });
    const msg = thesisPanel.querySelector("#thesis-saved-msg");
    msg.textContent = "Saved.";
    setTimeout(() => (msg.textContent = ""), 2000);
  });

  // Estimates vs actuals
  const estPanel = el(`
    <div class="panel">
      <h2>Estimates vs Actuals</h2>
      <div class="form-row">
        <input id="est-period" type="text" placeholder="Period (e.g. Q1 FY26)">
        <input id="est-eps" type="number" step="any" placeholder="Est. EPS">
        <input id="est-rev" type="number" step="any" placeholder="Est. Revenue">
        <button id="est-add-btn">Add estimate</button>
      </div>
      <div id="est-table" style="margin-top:12px;"></div>
    </div>
  `);
  content.appendChild(estPanel);

  async function renderEstimates() {
    const estimates = await api(`/api/company/${encodeURIComponent(symbol)}/estimates`);
    const box = estPanel.querySelector("#est-table");
    if (!estimates.length) {
      box.innerHTML = '<div class="empty">No estimates logged yet.</div>';
      return;
    }
    let rows = estimates.map((e) => {
      const epsVar = e.est_eps && e.actual_eps ? (((e.actual_eps - e.est_eps) / Math.abs(e.est_eps)) * 100).toFixed(1) + "%" : "—";
      const revVar = e.est_revenue && e.actual_revenue ? (((e.actual_revenue - e.est_revenue) / Math.abs(e.est_revenue)) * 100).toFixed(1) + "%" : "—";
      return `
        <tr>
          <td>${e.period_label}</td>
          <td>${fmt(e.est_eps)}</td>
          <td><input type="number" step="any" class="actual-eps-input" data-id="${e.id}" value="${e.actual_eps ?? ""}" style="width:80px;"></td>
          <td>${epsVar}</td>
          <td>${fmt(e.est_revenue)}</td>
          <td><input type="number" step="any" class="actual-rev-input" data-id="${e.id}" value="${e.actual_revenue ?? ""}" style="width:90px;"></td>
          <td>${revVar}</td>
        </tr>
      `;
    }).join("");
    box.innerHTML = `
      <table>
        <thead><tr><th>Period</th><th>Est. EPS</th><th>Actual EPS</th><th>Var %</th><th>Est. Rev</th><th>Actual Rev</th><th>Var %</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
    box.querySelectorAll(".actual-eps-input, .actual-rev-input").forEach((inp) => {
      inp.addEventListener("change", async () => {
        const id = inp.dataset.id;
        const epsInput = box.querySelector(`.actual-eps-input[data-id="${id}"]`);
        const revInput = box.querySelector(`.actual-rev-input[data-id="${id}"]`);
        await api(`/api/estimates/${id}/actuals`, {
          method: "PUT",
          body: JSON.stringify({
            actual_eps: epsInput.value === "" ? null : parseFloat(epsInput.value),
            actual_revenue: revInput.value === "" ? null : parseFloat(revInput.value),
          }),
        });
        renderEstimates();
      });
    });
  }
  await renderEstimates();

  estPanel.querySelector("#est-add-btn").addEventListener("click", async () => {
    const period = estPanel.querySelector("#est-period").value.trim();
    if (!period) return;
    const eps = estPanel.querySelector("#est-eps").value;
    const rev = estPanel.querySelector("#est-rev").value;
    await api(`/api/company/${encodeURIComponent(symbol)}/estimates`, {
      method: "POST",
      body: JSON.stringify({
        period_label: period,
        est_eps: eps === "" ? null : parseFloat(eps),
        est_revenue: rev === "" ? null : parseFloat(rev),
      }),
    });
    estPanel.querySelector("#est-period").value = "";
    estPanel.querySelector("#est-eps").value = "";
    estPanel.querySelector("#est-rev").value = "";
    renderEstimates();
  });

  // Notes
  const notesPanel = el(`
    <div class="panel">
      <h2>Research Notes</h2>
      <textarea id="note-input" placeholder="Add a note..."></textarea>
      <button id="note-add-btn" style="margin-top:8px;">Add note</button>
      <div id="notes-list" style="margin-top:14px;"></div>
    </div>
  `);
  content.appendChild(notesPanel);

  async function renderNotes() {
    const notes = await api(`/api/company/${encodeURIComponent(symbol)}/notes`);
    const box = notesPanel.querySelector("#notes-list");
    if (!notes.length) {
      box.innerHTML = '<div class="empty">No notes yet.</div>';
      return;
    }
    box.innerHTML = "";
    notes.forEach((n) => {
      box.appendChild(el(`
        <div class="note-item">
          <div class="note-time">${new Date(n.created_at).toLocaleString()}</div>
          <div>${n.body.replace(/</g, "&lt;")}</div>
        </div>
      `));
    });
  }
  await renderNotes();

  notesPanel.querySelector("#note-add-btn").addEventListener("click", async () => {
    const input = notesPanel.querySelector("#note-input");
    const body = input.value.trim();
    if (!body) return;
    await api(`/api/company/${encodeURIComponent(symbol)}/notes`, {
      method: "POST",
      body: JSON.stringify({ body }),
    });
    input.value = "";
    renderNotes();
  });
}

// ---- calendar view ----

async function loadCalendar() {
  const box = document.getElementById("calendar-list");
  box.innerHTML = '<div class="empty">Loading…</div>';
  const events = await api("/api/events");
  if (!events.length) {
    box.innerHTML = '<div class="empty">No events yet.</div>';
    return;
  }
  const today = new Date().toISOString().slice(0, 10);
  box.innerHTML = "";
  events.forEach((e) => {
    const overdue = e.event_date < today;
    box.appendChild(el(`
      <div class="event-row">
        <div class="meta">
          <span class="symbol">${e.event_date}</span> — ${e.event_type}${e.company_symbol ? " · " + e.company_symbol : ""}
          <div class="name">${e.description || ""}</div>
        </div>
        <span class="badge ${overdue ? "" : "low"}">${overdue ? "past" : "upcoming"}</span>
      </div>
    `));
  });
}

// ---- daily screen view (Nifty 50 Top Buys / Top Sells) ----

function buildScreenRow(r, rank, maxAbsUpside) {
  const upside = r.upside_pct !== null && r.upside_pct !== undefined ? `${r.upside_pct > 0 ? "+" : ""}${r.upside_pct}%` : "—";
  const flagCount = r.high_flags + r.medium_flags;
  const flagText = flagCount ? `${flagCount} flag${flagCount === 1 ? "" : "s"}` : "no flags";
  const flagClass = r.high_flags > 0 ? "high" : r.medium_flags > 0 ? "medium" : "low";
  const upsideColor = r.upside_pct > 0 ? "var(--green)" : r.upside_pct < 0 ? "var(--red)" : "var(--text-faint)";
  const barWidth = r.upside_pct !== null && r.upside_pct !== undefined && maxAbsUpside
    ? Math.max(3, (Math.abs(r.upside_pct) / maxAbsUpside) * 100)
    : 0;
  const row = el(`
    <div class="result-row screen-row">
      <div class="meta row-with-avatar">
        <span class="name" style="color:var(--text-faint);font-family:var(--font-mono);">#${rank}</span>
        ${avatarHtml(r.symbol, r.name, "sm", r.logo_url)}
        <div>
          <span class="symbol">${r.symbol}</span> — <span class="name">${r.name}</span>
          <div class="name">${r.industry || ""}</div>
        </div>
      </div>
      <div style="display:flex;gap:14px;align-items:center;">
        <span class="badge">₹${fmt(r.price)}</span>
        <div style="width:70px;">
          <div class="hbar-track" style="height:6px;"><div class="hbar-fill" style="width:${barWidth}%;background:${upsideColor};"></div></div>
          <div style="font-family:var(--font-mono);font-size:10.5px;color:${upsideColor};margin-top:3px;text-align:right;">${upside}</div>
        </div>
        <span class="rec-badge rec-pill rec-${(r.label || "").toLowerCase()}">${r.label || "—"}</span>
        <span class="badge ${flagClass}">${flagText}</span>
      </div>
    </div>
  `);
  row.addEventListener("click", () => openCompany(r.symbol, r.name));
  return row;
}

async function loadDailyScreen(forceRefresh = false) {
  const metaEl = document.getElementById("screen-meta");
  const cautionEl = document.getElementById("screen-caution");
  const buysBox = document.getElementById("screen-buys");
  const sellsBox = document.getElementById("screen-sells");
  metaEl.textContent = forceRefresh
    ? "Refreshing — scanning Nifty 50 live, this can take a little while…"
    : "Loading…";
  buysBox.innerHTML = "";
  sellsBox.innerHTML = "";

  const data = await api(`/api/daily-screen${forceRefresh ? "?refresh=1" : ""}`);

  metaEl.textContent = `${data.universe} (${data.universe_size} stocks) — as of ${new Date(data.computed_at).toLocaleString()}${data.errors.length ? ` · ${data.errors.length} lookup error(s)` : ""}`;
  cautionEl.textContent = data.caution;

  const distEl = document.getElementById("screen-distribution");
  if (data.label_counts) {
    distEl.innerHTML = stackBarHtml([
      { label: "Buy", value: data.label_counts.Buy || 0, color: "var(--green)" },
      { label: "Hold", value: data.label_counts.Hold || 0, color: "var(--amber)" },
      { label: "Sell", value: data.label_counts.Sell || 0, color: "var(--red)" },
    ]);
  }

  const allUpsides = [...data.top_buys, ...data.top_sells].map((r) => Math.abs(r.upside_pct || 0));
  const maxAbsUpside = Math.max(...allUpsides, 1);

  buysBox.innerHTML = "";
  if (!data.top_buys.length) buysBox.appendChild(el('<div class="empty">No data yet — click Refresh Now.</div>'));
  else data.top_buys.forEach((r, i) => buysBox.appendChild(buildScreenRow(r, i + 1, maxAbsUpside)));

  sellsBox.innerHTML = "";
  if (!data.top_sells.length) sellsBox.appendChild(el('<div class="empty">No data yet — click Refresh Now.</div>'));
  else data.top_sells.forEach((r, i) => sellsBox.appendChild(buildScreenRow(r, i + 1, maxAbsUpside)));
}

document.getElementById("screen-refresh-btn").addEventListener("click", () => loadDailyScreen(true));

// ---- wiring ----

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    showView(view);
    if (view === "watchlist") loadWatchlist();
    if (view === "calendar") loadCalendar();
    if (view === "screen") loadDailyScreen();
    if (view === "portfolio") loadHoldings();
  });
});

document.getElementById("back-btn").addEventListener("click", () => {
  const view = state.returnView || "watchlist";
  showView(view);
  if (view === "portfolio") loadHoldings();
  else if (view === "screen") loadDailyScreen();
  else if (view === "calendar") loadCalendar();
  else loadWatchlist();
});

document.getElementById("event-add-btn").addEventListener("click", async () => {
  const symbol = document.getElementById("event-symbol").value.trim();
  const type = document.getElementById("event-type").value.trim();
  const date = document.getElementById("event-date").value;
  const desc = document.getElementById("event-desc").value.trim();
  if (!type || !date) return;
  await api("/api/events", {
    method: "POST",
    body: JSON.stringify({
      company_symbol: symbol || null,
      event_type: type,
      event_date: date,
      description: desc || null,
    }),
  });
  document.getElementById("event-symbol").value = "";
  document.getElementById("event-type").value = "";
  document.getElementById("event-date").value = "";
  document.getElementById("event-desc").value = "";
  loadCalendar();
});

loadWatchlist();
