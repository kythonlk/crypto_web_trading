// Orbit MT5 Trading Workspace - Dynamic Frontend & JWT Authentication Controller

// --- JWT Authentication State & Helpers ---
const TOKEN_KEY = "orbit_jwt_token";
const USER_KEY = "orbit_jwt_username";

function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setAuthSession(token, username) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, username || "admin");
}

function clearAuthSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// Wrapper for authenticated fetch with automatic 401 handling
async function authFetch(url, options = {}) {
  const token = getAuthToken();
  const headers = {
    ...(options.headers || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    // Token is invalid or expired
    clearAuthSession();
    showAuthOverlay(true);
    showToast("Session expired or unauthorized. Please sign in.", true);
    throw new Error("Unauthorized");
  }

  return response;
}

function showAuthOverlay(show = true) {
  const overlay = document.querySelector("#auth-overlay");
  if (!overlay) return;
  if (show) {
    overlay.classList.remove("hidden");
    document.querySelector("#login-password")?.focus();
  } else {
    overlay.classList.add("hidden");
  }
}

// Global UI State
let currentMarketFilter = "all";
let currentChartPeriod = "LIVE";
let marketsData = [];
let botState = {
  is_paused: false,
  strategy: "trend",
  equity: 100000.0,
  balance: 100000.0,
};

// Toast notification helper
let toastTimer;
function showToast(text, isError = false) {
  const el = document.querySelector("#toast");
  if (!el) return;
  el.textContent = text;
  el.className = `fixed bottom-5 left-1/2 -translate-x-1/2 rounded-lg border px-5 py-3 text-sm shadow-2xl z-[200] ${
    isError
      ? "border-rose-500/30 bg-[#291316] text-rose-200"
      : "border-lime-300/30 bg-[#162214] text-lime-200"
  }`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3500);
}

// Format numbers
function formatMoney(num, digits = 2) {
  if (isNaN(num)) return "$0.00";
  return (
    "$" +
    Number(num).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
  );
}

// --- 1. Login Form Submission ---
document.querySelector("#login-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.querySelector("#login-username")?.value.trim();
  const password = document.querySelector("#login-password")?.value.trim();
  const errorEl = document.querySelector("#login-error");
  const btn = document.querySelector("#login-btn");
  const btnText = document.querySelector("#login-btn-text");

  if (!username || !password) return;

  if (errorEl) errorEl.classList.add("hidden");
  if (btn) btn.disabled = true;
  if (btnText) btnText.textContent = "Verifying...";

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    const data = await res.json();
    if (res.ok && data.success && data.token) {
      setAuthSession(data.token, data.username);
      showAuthOverlay(false);
      updateUserDisplay(data.username);
      showToast(`Welcome back, ${data.username}! JWT session active.`);
      // Start polling immediately
      fetchStatus();
      fetchPositions();
      fetchMarkets();
      renderLiveChart();
    } else {
      if (errorEl) {
        errorEl.textContent = data.error || "Invalid username or password.";
        errorEl.classList.remove("hidden");
      }
    }
  } catch (err) {
    if (errorEl) {
      errorEl.textContent = "Unable to connect to authentication server.";
      errorEl.classList.remove("hidden");
    }
  } finally {
    if (btn) btn.disabled = false;
    if (btnText) btnText.textContent = "Sign In with JWT";
  }
});

// Logout Handler
document.querySelector("#logout-btn")?.addEventListener("click", () => {
  clearAuthSession();
  showAuthOverlay(true);
  showToast("Logged out successfully.");
});

function updateUserDisplay(username) {
  const el = document.querySelector("#user-display");
  if (el) el.textContent = username || localStorage.getItem(USER_KEY) || "admin";
}

// --- 2. Live Polling: Status & Account Metrics ---
async function fetchStatus() {
  if (!getAuthToken()) return;
  try {
    const res = await authFetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    const acc = data.account || {};
    const equity = acc.equity || 100000.0;
    const balance = acc.balance || 100000.0;
    botState.equity = equity;
    botState.balance = balance;
    botState.is_paused = !!data.is_paused;
    botState.strategy = data.strategy || "trend";

    // Equity Card
    const eqEl = document.querySelector("#equity-val");
    if (eqEl) {
      const parts = equity.toFixed(2).split(".");
      eqEl.innerHTML = `$${Number(parts[0]).toLocaleString()}<span class="text-slate-500">.${parts[1]}</span>`;
    }
    const eqSub = document.querySelector("#equity-subtext");
    if (eqSub) {
      eqSub.textContent = `Balance: ${formatMoney(balance)}`;
    }
    const chartEq = document.querySelector("#chart-equity");
    if (chartEq) {
      chartEq.innerHTML = `${formatMoney(equity)} <span id="chart-pnl-pill" class="ml-2 text-xs ${data.today_pnl >= 0 ? "text-lime-300" : "text-rose-400"} font-semibold">${data.today_pnl >= 0 ? "+" : ""}${data.today_pnl_pct}%</span>`;
    }

    // Today's PnL Card
    const pnlEl = document.querySelector("#today-pnl");
    if (pnlEl) {
      const pnlSign = data.today_pnl >= 0 ? "+" : "-";
      pnlEl.textContent = `${pnlSign}$${Math.abs(data.today_pnl).toFixed(2)}`;
      pnlEl.className = `value ${data.today_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`;
    }
    const pnlPct = document.querySelector("#today-pnl-pct");
    if (pnlPct) {
      pnlPct.innerHTML = `<span class="${data.today_pnl >= 0 ? "text-emerald-400" : "text-rose-400"} font-medium">${data.today_pnl >= 0 ? "+" : ""}${data.today_pnl_pct}%</span> session return`;
    }

    // Daily Drawdown Card
    const ddVal = document.querySelector("#drawdown-val");
    if (ddVal) {
      ddVal.innerHTML = `${data.drawdown_pct.toFixed(2)}<span class="text-slate-500">%</span>`;
    }
    const ddLimit = data.risk_settings?.max_daily_drawdown_pct || 3.0;
    const limitLabel = document.querySelector("#limit-label");
    if (limitLabel) limitLabel.textContent = `${ddLimit.toFixed(2)}%`;
    const ddBar = document.querySelector("#drawdown-bar");
    if (ddBar) {
      const fillPct = Math.min(100, Math.max(0, (data.drawdown_pct / ddLimit) * 100));
      ddBar.style.width = `${fillPct}%`;
      ddBar.className = `h-full rounded transition-all duration-500 ${fillPct > 70 ? "bg-rose-500" : "bg-amber-300"}`;
    }

    // Connection Banner & Algo Status
    const statusText = document.querySelector("#connection-status-text");
    if (statusText) {
      if (data.connected) {
        statusText.innerHTML = `<span class="mr-2 text-emerald-400">●</span> <strong>Connected to MT5:</strong> Account ${acc.login || "113061165"} (${acc.server || "MetaQuotes-Demo"}) · Symbol: ${data.symbol || "EURUSD"} (${data.timeframe || "M15"})`;
      } else {
        statusText.innerHTML = `<span class="mr-2 text-rose-400">●</span> MT5 Disconnected. Attempting reconnection...`;
      }
    }

    const algoPill = document.querySelector("#algo-status-pill");
    const modalAlgoStatus = document.querySelector("#modal-algo-status");
    if (algoPill) {
      if (data.algo_trading_allowed) {
        algoPill.textContent = "Algo ON";
        algoPill.className = "text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-semibold";
      } else {
        algoPill.textContent = "Algo OFF";
        algoPill.className = "text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-semibold";
      }
    }
    if (modalAlgoStatus) {
      modalAlgoStatus.innerHTML = data.algo_trading_allowed
        ? `<strong class="text-emerald-400">ENABLED</strong>`
        : `<strong class="text-amber-300">DISABLED (Click 'Algo Trading' in MT5 toolbar)</strong>`;
    }

    // Strategy & Bot State
    const botBadge = document.querySelector("#bot-status-badge");
    const toggleBtn = document.querySelector("#bot-toggle-btn");
    const toggleText = document.querySelector("#toggle-text");
    const toggleIcon = document.querySelector("#toggle-icon");
    if (botBadge && toggleBtn) {
      if (data.is_paused) {
        botBadge.textContent = "PAUSED";
        botBadge.className = "rounded px-2 py-0.5 text-[10px] font-semibold bg-amber-500/20 text-amber-300";
        if (toggleText) toggleText.textContent = "Resume Trading Bot";
        if (toggleIcon) toggleIcon.textContent = "▶";
      } else {
        botBadge.textContent = "RUNNING";
        botBadge.className = "rounded px-2 py-0.5 text-[10px] font-semibold bg-emerald-500/20 text-emerald-300";
        if (toggleText) toggleText.textContent = "Pause Trading Bot";
        if (toggleIcon) toggleIcon.textContent = "⏸";
      }
    }

    // Live Signal Monitor
    const sig = data.latest_signal || {};
    const sigBadge = document.querySelector("#signal-badge");
    if (sigBadge) {
      sigBadge.textContent = sig.action || "HOLD";
      if (sig.action === "BUY") {
        sigBadge.className = "px-2 py-0.5 rounded font-bold text-xs bg-emerald-500/20 text-emerald-300";
      } else if (sig.action === "SELL") {
        sigBadge.className = "px-2 py-0.5 rounded font-bold text-xs bg-rose-500/20 text-rose-300";
      } else {
        sigBadge.className = "px-2 py-0.5 rounded font-bold text-xs bg-amber-500/20 text-amber-300";
      }
    }
    const rsiEl = document.querySelector("#signal-rsi");
    if (rsiEl) rsiEl.textContent = sig.rsi ? Number(sig.rsi).toFixed(1) : "--";
    const emaEl = document.querySelector("#signal-ema50");
    if (emaEl) emaEl.textContent = sig.ema_fast ? Number(sig.ema_fast).toFixed(4) : "--";
    const atrEl = document.querySelector("#signal-atr");
    if (atrEl) atrEl.textContent = sig.atr ? Number(sig.atr).toFixed(4) : "--";
    const reasonEl = document.querySelector("#signal-reason");
    if (reasonEl) reasonEl.textContent = sig.reason || "Scanning market conditions...";

    // Risk Label
    const riskLabel = document.querySelector("#risk-label");
    if (riskLabel && data.risk_settings) {
      riskLabel.textContent = `${Number(data.risk_settings.max_risk_per_trade_pct).toFixed(2)}%`;
    }

    // Strategy select dropdown sync
    const stratSelect = document.querySelector("#strategy-select");
    if (stratSelect && stratSelect.value !== data.strategy) {
      stratSelect.value = data.strategy;
    }
  } catch (err) {
    // Handled in authFetch if 401
  }
}

// --- 3. Live Polling: Positions ---
async function fetchPositions() {
  if (!getAuthToken()) return;
  try {
    const res = await authFetch("/api/positions");
    if (!res.ok) return;
    const positions = await res.json();

    const countEl = document.querySelector("#positions-count");
    const subEl = document.querySelector("#positions-sub");
    const tableCount = document.querySelector("#positions-table-count");
    const tbody = document.querySelector("#positions-tbody");

    const buyCount = positions.filter((p) => p.order_type === "BUY").length;
    const sellCount = positions.filter((p) => p.order_type === "SELL").length;

    if (countEl) countEl.innerHTML = `${positions.length} <span class="text-base text-slate-500">active</span>`;
    if (subEl) subEl.textContent = `${buyCount} BUY · ${sellCount} SELL`;
    if (tableCount) tableCount.textContent = `${positions.length} active`;

    // Visual indicators
    const bar1 = document.querySelector("#pos-bar-1");
    const bar2 = document.querySelector("#pos-bar-2");
    if (bar1) bar1.className = `h-1.5 rounded ${positions.length > 0 ? "bg-lime-300" : "bg-slate-800"}`;
    if (bar2) bar2.className = `h-1.5 rounded ${positions.length > 1 ? "bg-lime-300" : "bg-slate-800"}`;

    if (!tbody) return;

    if (positions.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="10" class="text-center py-8 text-slate-500">
            No open positions at this moment. The trading bot is actively evaluating M15 candles for high-probability setups.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = positions
      .map(
        (p) => `
        <tr class="hover:bg-white/[.02] transition">
          <td class="font-mono text-slate-400">#${p.ticket}</td>
          <td class="font-semibold text-white">${p.symbol}</td>
          <td class="${p.order_type === "BUY" ? "text-emerald-400" : "text-rose-400"} font-semibold">${p.order_type}</td>
          <td>${p.volume} lot</td>
          <td class="font-mono">${Number(p.open_price).toFixed(5)}</td>
          <td class="font-mono">${Number(p.current_price).toFixed(5)}</td>
          <td class="font-mono text-slate-400">${p.sl > 0 ? Number(p.sl).toFixed(5) : "None"}</td>
          <td class="font-mono text-slate-400">${p.tp > 0 ? Number(p.tp).toFixed(5) : "None"}</td>
          <td class="${p.profit >= 0 ? "text-emerald-400" : "text-rose-400"} font-semibold font-mono">
            ${p.profit >= 0 ? "+" : ""}$${Number(p.profit).toFixed(2)}
          </td>
          <td class="text-right">
            <button onclick="closePosition(${p.ticket})" class="px-2.5 py-1 text-[11px] rounded bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 border border-rose-500/20 transition">
              Close
            </button>
          </td>
        </tr>
      `,
      )
      .join("");
  } catch (err) {
    // Handled in authFetch
  }
}

// Global close position function
window.closePosition = async function (ticket) {
  if (!confirm(`Are you sure you want to close position #${ticket}?`)) return;
  try {
    const res = await authFetch("/api/positions/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticket }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Position #${ticket} closed successfully.`);
      fetchPositions();
      fetchStatus();
    } else {
      showToast(`Failed to close position: ${data.error || "Unknown error"}`, true);
    }
  } catch (err) {
    showToast(`Error closing position: ${err.message}`, true);
  }
};

// --- 4. Live Polling: Market Watch ---
async function fetchMarkets() {
  if (!getAuthToken()) return;
  try {
    const res = await authFetch("/api/markets");
    if (!res.ok) return;
    marketsData = await res.json();
    renderMarkets(currentMarketFilter);
  } catch (err) {
    // Handled
  }
}

function renderMarkets(filter = "all") {
  const grid = document.querySelector("#market-grid");
  if (!grid || !marketsData.length) return;

  const filtered = marketsData.filter((m) => filter === "all" || m.category === filter);
  grid.innerHTML = filtered
    .map(
      (m) => `
      <article class="bg-[#10161e] p-5 hover:bg-[#121a24] transition">
        <div class="flex items-center gap-3">
          <span class="grid h-9 w-9 place-items-center rounded-full text-xl" style="color:${m.color};background:${m.color}15">
            ${m.icon}
          </span>
          <div>
            <h3 class="text-xs font-semibold text-white">${m.symbol}</h3>
            <p class="mt-0.5 text-[10px] text-slate-500">${m.name}</p>
          </div>
        </div>
        <div class="mt-5 flex justify-between items-end">
          <div>
            <p class="text-lg font-medium text-white">${m.price}</p>
            <p class="mt-1 text-xs ${m.change_24h.startsWith("+") ? "text-emerald-400" : "text-rose-400"}">
              ${m.change_24h} <span class="text-slate-600">24h</span>
            </p>
          </div>
          <div class="text-right">
            <span class="text-[10px] text-slate-500">Spread: ${m.spread || 0}</span>
            <svg viewBox="0 0 90 28" class="h-8 w-20 mt-1" aria-hidden="true">
              <path
                d="${m.change_24h.startsWith("+") ? "M0 24 L15 18 L30 20 L45 10 L60 14 L75 5 L90 2" : "M0 4 L15 8 L30 6 L45 16 L60 12 L75 22 L90 26"}"
                fill="none"
                stroke="${m.change_24h.startsWith("+") ? "#34d399" : "#fb7185"}"
                stroke-width="1.8"
              />
            </svg>
          </div>
        </div>
      </article>
    `,
    )
    .join("");
}

// --- 5. Dynamic Chart Rendering with Period Switching ---
async function renderLiveChart() {
  if (!getAuthToken()) return;
  const chartEl = document.querySelector("#chart");
  if (!chartEl) return;

  try {
    const res = await authFetch(`/api/chart?period=${currentChartPeriod}`);
    if (!res.ok) return;
    const data = await res.json();
    const history = data.equity_history || [];

    const baseEq = botState.equity || 100000.0;
    const width = 700;
    const height = 180;
    const topY = 35;

    if (currentChartPeriod === "LIVE") {
      if (history.length < 2) {
        // Draw baseline placeholder
        const pts = Array.from({ length: 40 }, (_, i) => [
          20 + i * 18,
          180 - Math.sin(i * 0.3) * 12,
        ]);
        const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        chartEl.innerHTML = `
          <defs>
            <linearGradient id="fade" x2="0" y2="1">
              <stop stop-color="#bef264" stop-opacity=".18"/>
              <stop offset="1" stop-color="#bef264" stop-opacity="0"/>
            </linearGradient>
          </defs>
          ${[40, 90, 140, 190, 230]
            .map(
              (y, i) =>
                `<line x1="20" y1="${y}" x2="720" y2="${y}" stroke="#ffffff08" stroke-dasharray="4 5"/>
                 <text x="732" y="${y + 4}" fill="#596579" font-size="10">${(baseEq + (4 - i) * 100).toLocaleString()}</text>`,
            )
            .join("")}
          <path d="${line} L722,230 L20,230 Z" fill="url(#fade)"/>
          <path d="${line}" stroke="#bef264" stroke-width="2.3" fill="none"/>
        `;
        return;
      }

      const equities = history.map((h) => h.equity);
      const minVal = Math.min(...equities) * 0.9995;
      const maxVal = Math.max(...equities) * 1.0005;
      const range = maxVal - minVal || 1.0;

      const pts = history.map((h, i) => {
        const x = 20 + (i / (history.length - 1)) * width;
        const y = topY + height - ((h.equity - minVal) / range) * height;
        return [x, y];
      });

      const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
      const lastX = pts[pts.length - 1][0];

      chartEl.innerHTML = `
        <defs>
          <linearGradient id="fade" x2="0" y2="1">
            <stop stop-color="#bef264" stop-opacity=".2"/>
            <stop offset="1" stop-color="#bef264" stop-opacity="0"/>
          </linearGradient>
        </defs>
        ${[0, 0.25, 0.5, 0.75, 1.0]
          .map((frac) => {
            const y = topY + height * (1 - frac);
            const val = minVal + range * frac;
            return `
              <line x1="20" y1="${y.toFixed(1)}" x2="720" y2="${y.toFixed(1)}" stroke="#ffffff08" stroke-dasharray="4 5"/>
              <text x="732" y="${(y + 4).toFixed(1)}" fill="#596579" font-size="10">${val.toFixed(0)}</text>
            `;
          })
          .join("")}
        <path d="${line} L${lastX.toFixed(1)},230 L20,230 Z" fill="url(#fade)"/>
        <path d="${line}" stroke="#bef264" stroke-width="2.3" fill="none"/>
        ${history
          .slice(-5)
          .map((h, idx) => {
            const x = 20 + (idx / 4) * width;
            return `<text x="${x.toFixed(1)}" y="258" fill="#596579" font-size="10">${h.time}</text>`;
          })
          .join("")}
      `;
    } else {
      // 1D or 1W simulated multi-bar curves
      const is1D = currentChartPeriod === "1D";
      const labels = is1D
        ? ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"]
        : ["Mon", "Tue", "Wed", "Thu", "Fri", "Sun"];
      const seed = is1D ? 3.5 : 8.2;
      const count = 55;

      const pts = Array.from({ length: count }, (_, i) => {
        const x = 20 + (i / (count - 1)) * width;
        const norm = Math.sin(i * 0.25 + seed) * 35 + Math.cos(i * 0.12) * 20;
        const y = 140 - norm;
        return [x, y];
      });

      const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
      chartEl.innerHTML = `
        <defs>
          <linearGradient id="fade" x2="0" y2="1">
            <stop stop-color="#bef264" stop-opacity=".18"/>
            <stop offset="1" stop-color="#bef264" stop-opacity="0"/>
          </linearGradient>
        </defs>
        ${[40, 85, 130, 175, 220]
          .map(
            (y, i) =>
              `<line x1="20" y1="${y}" x2="720" y2="${y}" stroke="#ffffff08" stroke-dasharray="4 5"/>
               <text x="732" y="${y + 4}" fill="#596579" font-size="10">${(baseEq + (3 - i) * 150).toLocaleString()}</text>`,
          )
          .join("")}
        <path d="${line} L720,230 L20,230 Z" fill="url(#fade)"/>
        <path d="${line}" stroke="#bef264" stroke-width="2.3" fill="none"/>
        ${labels
          .map((l, i) => `<text x="${20 + i * (width / (labels.length - 1))}" y="258" fill="#596579" font-size="10">${l}</text>`)
          .join("")}
      `;
    }

    const updateTime = document.querySelector("#chart-update-time");
    if (updateTime) {
      updateTime.textContent = `Mode: ${currentChartPeriod} · Synced`;
    }
  } catch (err) {
    // Handled
  }
}

// Chart Period click handler
document.querySelectorAll("[data-period]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("[data-period]").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    currentChartPeriod = btn.dataset.period;
    renderLiveChart();
  });
});

// --- 6. Bot Pause / Resume Toggle ---
document.querySelector("#bot-toggle-btn")?.addEventListener("click", async () => {
  try {
    const res = await authFetch("/api/bot/toggle", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(`Trading Bot ${data.state}!`);
      fetchStatus();
    }
  } catch (err) {
    showToast("Failed to toggle bot state", true);
  }
});

// --- 7. Strategy Select dropdown change ---
document.querySelector("#strategy-select")?.addEventListener("change", async (e) => {
  const newStrategy = e.target.value;
  try {
    const res = await authFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy: newStrategy }),
    });
    const data = await res.json();
    if (data.success) {
      const descEl = document.querySelector("#strategy-desc");
      if (descEl) {
        descEl.textContent =
          newStrategy === "trend"
            ? "EMA 50/200 trend alignment, RSI momentum confirmation, and dynamic ATR volatility stops."
            : "Donchian breakout with ADX momentum strength and volatility filter.";
      }
      showToast(`Strategy model updated: ${newStrategy.toUpperCase()}`);
      fetchStatus();
    }
  } catch (err) {
    showToast("Failed to update strategy", true);
  }
});

// --- 8. Settings Modal (Form Submit & Pre-fill) ---
document.querySelector("#settings-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const risk = Number(document.querySelector("#risk-input")?.value || 1.0);
  const limit = Number(document.querySelector("#limit-input")?.value || 3.0);
  const strategy = document.querySelector("#modal-strategy-select")?.value || "trend";

  try {
    const res = await authFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ risk, limit, strategy }),
    });
    const data = await res.json();
    if (data.success) {
      document.querySelector("#settings")?.close();
      showToast("Live risk settings saved successfully!");
      fetchStatus();
    }
  } catch (err) {
    showToast("Error updating settings", true);
  }
});

// Open Risk Settings modal handler
document.querySelectorAll("[data-settings]").forEach((b) =>
  b.addEventListener("click", () => {
    const settingsModal = document.querySelector("#settings");
    if (settingsModal) {
      const stratIn = document.querySelector("#modal-strategy-select");
      if (stratIn) stratIn.value = botState.strategy;
      settingsModal.showModal();
    }
  }),
);

// Close Modals handler
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", () => b.closest("dialog")?.close()),
);

// Open Connection info modal
document.querySelector("#connect")?.addEventListener("click", () => {
  document.querySelector("#connection")?.showModal();
});

// Market filter tabs
document.querySelectorAll("[data-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("[data-filter]").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    currentMarketFilter = btn.dataset.filter;
    renderMarkets(currentMarketFilter);
  });
});

// Sidebar Navigation Active Highlight
document.querySelectorAll(".nav[href^='#']").forEach((link) => {
  link.addEventListener("click", (e) => {
    document.querySelectorAll(".nav").forEach((n) => n.classList.remove("active"));
    link.classList.add("active");
  });
});

// Export Data Snapshot
document.querySelector("#export")?.addEventListener("click", () => {
  const snapshot = {
    timestamp: new Date().toISOString(),
    account: "113061165",
    server: "MetaQuotes-Demo",
    equity: botState.equity,
    balance: botState.balance,
    strategy: botState.strategy,
    markets: marketsData,
  };
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `orbit-mt5-snapshot-${Date.now()}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast("Snapshot exported successfully.");
});

// UTC Clock
function updateClock() {
  const el = document.querySelector("#clock");
  if (el) {
    el.textContent = new Date().toLocaleTimeString("en-GB", { timeZone: "UTC" }) + " UTC";
  }
}
updateClock();
setInterval(updateClock, 1000);

// --- 9. Initial Authentication Check & Bootstrapping ---
async function initApp() {
  const token = getAuthToken();
  if (!token) {
    showAuthOverlay(true);
    return;
  }

  // Verify existing token with backend
  try {
    const res = await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const data = await res.json();
      showAuthOverlay(false);
      updateUserDisplay(data.username);
      // Fetch initial data
      fetchStatus();
      fetchPositions();
      fetchMarkets();
      renderLiveChart();
    } else {
      clearAuthSession();
      showAuthOverlay(true);
    }
  } catch (err) {
    // Backend may be starting
    showAuthOverlay(true);
  }
}

// Start polling timers
setInterval(fetchStatus, 1500);
setInterval(fetchPositions, 2000);
setInterval(fetchMarkets, 3500);
setInterval(renderLiveChart, 8000);

// Bootstrap
initApp();
