const CSRF_COOKIE = "laya_csrf";

function readCookie(name) {
  const prefix = name + "=";
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(prefix))
    ?.slice(prefix.length) ?? "";
}

async function api(path, { method = "GET", body = null } = {}) {
  const headers = {};
  if (body !== null) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = readCookie(CSRF_COOKIE);
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === null ? undefined : JSON.stringify(body),
  });
  if (response.status === 401) {
    location.href = "/login";
    throw new Error("登录状态已过期，正在跳转。");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw errorFrom(response.status, data);
  return data;
}

function errorFrom(status, data) {
  if (typeof data.message === "string") return new Error(data.message);
  if (Array.isArray(data.detail)) {
    return new Error(`输入有误：${data.detail.map((i) => i.msg).filter(Boolean).join("；")}`);
  }
  if (typeof data.detail === "string") return new Error(data.detail);
  if (data.detail && typeof data.detail.message === "string") return new Error(data.detail.message);
  return new Error(`请求失败（${status}），请稍后重试。`);
}

const $ = (id) => document.getElementById(id);

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

function notice(id, message) {
  const node = $(id);
  if (!node) return;
  if (message) {
    node.textContent = message;
    node.classList.remove("hidden");
  } else {
    node.textContent = "";
    node.classList.add("hidden");
  }
}

const numberFormat = new Intl.NumberFormat("en-US");

function fmtInt(value) {
  return numberFormat.format(Number(value ?? 0));
}

function fmtTime(iso) {
  if (!iso) return "—";
  // 接口统一返回 UTC；无时区后缀时按 UTC 解析，避免浏览器按本地时区偏移后仍标注 UTC。
  const text = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : iso + "Z";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toISOString().slice(0, 19).replace("T", " ");
}

function fmtAmount(value) {
  // 金额按价格规则保留 6 位小数；空窗口的 0 也要与明细同一位数。
  const text = String(value ?? "0");
  const [int, frac = ""] = text.split(".");
  return `${int}.${frac.padEnd(6, "0").slice(0, 6)}`;
}

function fmtMs(value) {
  return value === null || value === undefined ? "—" : `${fmtInt(value)} ms`;
}

function cell(text, className = "px-3 py-2") {
  const td = document.createElement("td");
  td.className = className;
  td.textContent = text;
  return td;
}

function row(cells) {
  const tr = document.createElement("tr");
  tr.className = "border-t border-[#f3f4f6]";
  cells.forEach((c) => tr.appendChild(typeof c === "string" ? cell(c) : c));
  return tr;
}

function messageRow(tbody, colspan, text) {
  tbody.textContent = "";
  const tr = document.createElement("tr");
  const td = cell(text, "px-3 py-8 text-center text-sm text-[#6b7280]");
  td.colSpan = colspan;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

const STATUS_LABEL = {
  accepted: "已受理",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  interrupted: "已中断",
  active: "可用",
  revoked: "已撤销",
};

function statusCell(status) {
  const td = cell(`${STATUS_LABEL[status] ?? status}`);
  const dot = document.createElement("span");
  const color =
    status === "succeeded" || status === "active"
      ? "bg-[#16a34a]"
      : status === "failed" || status === "revoked" || status === "interrupted"
        ? "bg-[#dc2626]"
        : "bg-[#d97706]";
  dot.className = `mr-2 inline-block h-2 w-2 rounded-full ${color}`;
  td.insertBefore(dot, td.firstChild);
  return td;
}

async function initChrome() {
  const account = $("account");
  const logout = $("logout");
  try {
    const data = await api("/v1/auth/me");
    if (account) account.textContent = data.user.email;
  } catch (error) {
    if (account) account.textContent = "未登录";
    return;
  }
  if (logout) {
    logout.addEventListener("click", async function () {
      logout.disabled = true;
      try {
        await api("/v1/auth/logout", { method: "POST", body: {} });
      } catch {
        /* 会话已失效时直接跳转 */
      }
      location.href = "/login";
    });
  }
}

const SVG = "http://www.w3.org/2000/svg";
const CHART = { width: 560, height: 180, left: 40, right: 10, top: 14, bottom: 28 };

function svgNode(tag, attrs, text) {
  const node = document.createElementNS(SVG, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (text !== undefined) node.textContent = text;
  return node;
}

function niceMax(values) {
  const peak = Math.max(0, ...values);
  if (peak <= 0) return 1;          // 金额与 Token 都可能是小数，不能固定下限为 1
  const magnitude = 10 ** Math.floor(Math.log10(peak));
  return Math.ceil(peak / magnitude) * magnitude;
}

function chartFrame(svg, series, max, tickLabel) {
  svg.textContent = "";
  const { width, height, left, right, top, bottom } = CHART;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const label = tickLabel ?? ((v) => numberFormat.format(Math.round(v)));
  for (let step = 0; step <= 4; step += 1) {
    const y = top + (plotHeight * step) / 4;
    svg.appendChild(svgNode("line", { x1: left, y1: y, x2: width - right, y2: y, stroke: "#eef2f7" }));
    svg.appendChild(
      svgNode("text", { x: left - 6, y: y + 4, "text-anchor": "end", fill: "#9ca3af", "font-size": "10" },
        label((max * (4 - step)) / 4))
    );
  }
  if (series.length <= 1) {
    svg.appendChild(xLabel(series[0]?.date ?? "", left, height - 8, "middle"));
    return plotHeight;
  }
  const seen = new Set();
  const stride = Math.max(1, Math.ceil(series.length / 8));
  series.forEach((point, index) => {
    if (index % stride !== 0 && index !== series.length - 1) return;
    const x = left + (plotWidth * index) / (series.length - 1);
    const anchor = index === 0 ? "start" : index === series.length - 1 ? "end" : "middle";
    const key = Math.round(x);
    if (seen.has(key)) return;
    seen.add(key);
    svg.appendChild(xLabel(point.date.slice(5), x, height - 8, anchor));
  });
  return plotHeight;
}

function xLabel(text, x, y, anchor) {
  return svgNode("text", { x, y, "text-anchor": anchor, fill: "#9ca3af", "font-size": "10" }, text);
}

function emptyChart(svg, message) {
  svg.textContent = "";
  svg.setAttribute("viewBox", `0 0 ${CHART.width} ${CHART.height}`);
  svg.appendChild(svgNode("text", { x: CHART.width / 2, y: CHART.height / 2, "text-anchor": "middle", fill: "#9ca3af", "font-size": "13" }, message));
}

function lineChart(svg, series, keys, colors) {
  if (!series.length) return emptyChart(svg, "所选范围内暂无调用趋势");
  const values = series.flatMap((p) => keys.map((k) => Number(p[k] ?? 0)));
  const max = niceMax(values);
  const plotHeight = chartFrame(svg, series, max);
  const plotWidth = CHART.width - CHART.left - CHART.right;
  keys.forEach((key, seriesIndex) => {
    const points = series.map((point, index) => {
      const x = series.length === 1 ? CHART.left + plotWidth / 2 : CHART.left + (plotWidth * index) / (series.length - 1);
      const y = CHART.top + plotHeight - (Number(point[key] ?? 0) / max) * plotHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    svg.appendChild(svgNode("polyline", {
      points: points.join(" "),
      fill: "none",
      stroke: colors[seriesIndex],
      "stroke-width": "2",
      "stroke-linejoin": "round",
    }));
    series.forEach((point, index) => {
      const [x, y] = points[index].split(",");
      svg.appendChild(svgNode("circle", { cx: x, cy: y, r: "3", fill: colors[seriesIndex] }));
    });
  });
}

function moneyTick(value) {
  const text = value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  return `¥${text === "-0" ? "0" : text}`;
}

function barChart(svg, series, key) {
  if (!series.length) return emptyChart(svg, "所选范围内暂无费用");
  const values = series.map((p) => Number(p[key] ?? 0));
  const max = niceMax(values);
  const plotHeight = chartFrame(svg, series, max, moneyTick);
  const plotWidth = CHART.width - CHART.left - CHART.right;
  const slot = plotWidth / series.length;
  const barWidth = Math.min(28, Math.max(6, slot * 0.55));
  series.forEach((point, index) => {
    const amount = Number(point[key] ?? 0);
    const height = (amount / max) * plotHeight;
    svg.appendChild(svgNode("rect", {
      x: CHART.left + slot * index + (slot - barWidth) / 2,
      y: CHART.top + plotHeight - height,
      width: barWidth,
      height: Math.max(amount > 0 ? 2 : 0, height),
      rx: "3",
      fill: "#2563eb",
      opacity: amount > 0 ? "0.9" : "0.25",
    }));
  });
}

function legend(svg, items) {
  items.forEach(([label, color], index) => {
    const x = CHART.width - 150 + index * 80;
    svg.appendChild(svgNode("rect", { x, y: 4, width: 8, height: 8, rx: 2, fill: color }));
    svg.appendChild(svgNode("text", { x: x + 12, y: 11, fill: "#6b7280", "font-size": "10" }, label));
  });
}

function query(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function keysPage() {
  const tbody = $("rows");

  async function load() {
    messageRow(tbody, 5, "加载中…");
    const data = await api("/v1/api-keys");
    setText("stat-total", fmtInt(data.summary.total));
    setText("stat-active", fmtInt(data.summary.active));
    setText("stat-revoked", fmtInt(data.summary.revoked));
    if (!data.items.length) {
      messageRow(tbody, 5, "还没有 API Key，点击右上角申请一个。");
      return;
    }
    tbody.textContent = "";
    data.items.forEach((item) => {
      const actions = document.createElement("td");
      actions.className = "px-3 py-2";
      if (item.status === "active") {
        const button = document.createElement("button");
        button.className = "rounded-lg border border-[#fecaca] px-3 py-1.5 text-xs text-[#dc2626] hover:bg-[#fef2f2]";
        button.textContent = "撤销";
        button.addEventListener("click", () => askRevoke(item));
        actions.appendChild(button);
      } else {
        actions.textContent = "—";
        actions.className = "px-3 py-2 text-[#9ca3af]";
      }
      tbody.appendChild(row([
        cell(item.display, "px-3 py-2 font-mono text-[13px]"),
        statusCell(item.status),
        cell(fmtTime(item.created_at)),
        cell(fmtTime(item.last_used_at)),
        actions,
      ]));
    });
  }

  function askRevoke(item) {
    const modal = $("revoke-modal");
    setText("revoke-target", `${item.display}（撤销后不可恢复，历史调用与费用仍会保留）`);
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    async function confirm() {
      const yes = $("revoke-confirm");
      yes.disabled = true;
      yes.textContent = "撤销中…";
      try {
        await api(`/v1/api-keys/${item.id}/revoke`, { method: "POST", body: { confirm: true } });
        close();
        notice("error", "");
        await load();
      } catch (error) {
        notice("error", error.message);
      } finally {
        yes.disabled = false;
        yes.textContent = "确认撤销";
      }
    }
    function close() {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    }
    $("revoke-confirm").onclick = confirm;
    $("revoke-cancel").onclick = close;
  }

  $("create").addEventListener("click", async function () {
    const button = $("create");
    button.disabled = true;
    button.textContent = "申请中…";
    try {
      const data = await api("/v1/api-keys", { method: "POST", body: {} });
      showSecret(data.secret, data.call_example);
      await load();
    } catch (error) {
      notice("error", error.message);
    } finally {
      button.disabled = false;
      button.textContent = "申请 API Key";
    }
  });

  function showSecret(secret, example) {
    setText("secret", secret);
    $("secret-modal").classList.remove("hidden");
    $("secret-modal").classList.add("flex");
    $("copy").onclick = async function () {
      try {
        await navigator.clipboard.writeText(secret);
        $("copy").textContent = "已复制";
      } catch {
        $("copy").textContent = "复制失败，请手动选中";
      }
    };
    $("close").onclick = function () {
      $("secret-modal").classList.add("hidden");
      $("secret-modal").classList.remove("flex");
      setText("secret", "");
    };
    if (example) setText("example", example);
  }

  notice("error", "");
  await load();
  if (!$("example").textContent) {
    setText("example", "申请 API Key 后，这里会给出与实际契约一致的调用示例。");
  }
}

const PAGE_SIZE = 20;

async function populateKeyFilter() {
  const select = $("key-filter");
  if (!select) return;
  const data = await api("/v1/api-keys");
  data.items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.display}${item.status === "revoked" ? "（已撤销）" : ""}`;
    select.appendChild(option);
  });
}

function readFilters(state) {
  state.dateFrom = $("date-from")?.value ?? "";
  state.dateTo = $("date-to")?.value ?? "";
  state.keyId = $("key-filter")?.value ?? "";
  state.pageSize = $("page-size")?.value || PAGE_SIZE;
}

function filterQuery(state, extra = {}) {
  return query({
    from: state.dateFrom,
    to: state.dateTo,
    api_key_id: state.keyId,
    limit: state.pageSize,
    ...extra,
  });
}

function resetPages(state) {
  state.index = 0;
  state.cursor = "";
  state.cursors = { 0: "" };
  state.hasOlder = false;
}

function pager(state, render) {
  $("prev").disabled = state.index === 0;
  $("next").disabled = !state.hasOlder;
  $("page-info").textContent = `第 ${state.index + 1} 页 · 共 ${fmtInt(state.total)} 条`;
  $("prev").onclick = async function () {
    if (state.index === 0) return;
    state.index -= 1;
    state.cursor = state.cursors[state.index];
    await render();
  };
  $("next").onclick = async function () {
    if (!state.hasOlder) return;
    state.index += 1;
    state.cursor = state.cursors[state.index] ?? "";
    await render();
  };
}

async function usagePage() {
  const state = { keyId: "", endpoint: "", dateFrom: "", dateTo: "", total: 0 };
  resetPages(state);

  const endpointSelect = $("endpoint-filter");
  [["", "全部接口"], ["/v1/predict", "/v1/predict"], ["/v1/customer-service/analyze", "/v1/customer-service/analyze"]]
    .forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      endpointSelect.appendChild(option);
    });

  async function render() {
    const tbody = $("rows");
    messageRow(tbody, 7, "加载中…");
    const tail = state.cursor ? `&cursor=${encodeURIComponent(state.cursor)}` : "";
    const base = filterQuery(state, { endpoint: state.endpoint });
    const [summary, calls] = await Promise.all([
      api(`/v1/usage/summary${base}`),
      api(`/v1/usage/calls${base}${tail}`),
    ]);
    const totals = summary.totals;
    state.total = totals.calls_total;
    setText("stat-calls", fmtInt(totals.calls_total));
    setText("stat-succeeded", fmtInt(totals.calls_succeeded));
    setText("stat-failed", fmtInt(totals.calls_failed));
    setText("stat-tokens", fmtInt(totals.input_tokens));
    setText("range", `${fmtTime(summary.range.from)} 至 ${fmtTime(summary.range.to)}（UTC）`);
    setText("in-progress", fmtInt(totals.calls_in_progress));
    setText("pending", fmtInt(totals.billing_pending_count));
    lineChart($("chart"), summary.series, ["succeeded", "failed"], ["#2563eb", "#dc2626"]);
    legend($("chart"), [["成功", "#2563eb"], ["失败", "#dc2626"]]);
    if (!calls.items.length) {
      messageRow(tbody, 7, "所选范围内暂无调用记录。");
    } else {
      tbody.textContent = "";
      calls.items.forEach((item) => {
        tbody.appendChild(row([
          cell(item.request_id.slice(0, 8), "px-3 py-2 font-mono text-[13px]"),
          cell(item.api_key, "px-3 py-2 font-mono text-[13px]"),
          cell(item.endpoint),
          cell(fmtTime(item.started_at)),
          statusCell(item.status),
          cell(item.input_tokens === null ? "—" : fmtInt(item.input_tokens)),
          cell(fmtMs(item.duration_ms)),
        ]));
      });
    }
    state.hasOlder = Boolean(calls.has_more && calls.next_cursor);
    if (state.hasOlder) state.cursors[state.index + 1] = calls.next_cursor;
    pager(state, render);
  }

  async function applyFilters() {
    readFilters(state);
    state.endpoint = $("endpoint-filter")?.value ?? "";
    resetPages(state);
    notice("error", "");
    try {
      await render();
    } catch (error) {
      notice("error", error.message);
    }
  }
  $("apply").addEventListener("click", applyFilters);
  $("page-size").addEventListener("change", applyFilters);

  await populateKeyFilter();
  readFilters(state);
  try {
    await render();
  } catch (error) {
    notice("error", error.message);
  }
}

async function billingPage() {
  const state = { keyId: "", dateFrom: "", dateTo: "", total: 0 };
  resetPages(state);

  async function render() {
    const tbody = $("rows");
    messageRow(tbody, 6, "加载中…");
    const base = filterQuery(state);
    const tail = state.cursor ? `&cursor=${encodeURIComponent(state.cursor)}` : "";
    const [summary, charges] = await Promise.all([
      api(`/v1/billing/summary${base}`),
      api(`/v1/billing/charges${base}${tail}`),
    ]);
    const totals = summary.totals;
    state.total = totals.charge_count;
    const price = summary.price;
    if (price && price.version) {
      setText(
        "price-banner",
        `当前单价 ¥${price.unit_price_yuan} / ${fmtInt(price.unit_tokens)} 输入 Token（价格版本 ${price.version}，币种 ${price.currency}）`
      );
      setText("price-formula", `费用 = 计费输入 Token ÷ ${fmtInt(price.unit_tokens)} × ¥${price.unit_price_yuan}，结果保留 6 位小数。`);
      setText("price-policy", `计费策略版本：${price.billing_policy_version}`);
    } else {
      setText("price-banner", "暂无适用价格规则，调用将被拒绝。");
    }
    setText("stat-tokens", fmtInt(totals.billable_tokens));
    setText("stat-amount", `¥ ${fmtAmount(totals.charged_amount_yuan)}`);
    setText("stat-charges", fmtInt(totals.charge_count));
    setText("stat-calls", fmtInt(totals.calls_total));
    setText("pending", fmtInt(totals.billing_pending_count));
    setText("range", `${fmtTime(summary.range.from)} 至 ${fmtTime(summary.range.to)}（UTC）`);
    barChart($("chart"), summary.series, "amount_yuan");
    if (!charges.items.length) {
      messageRow(tbody, 6, "所选范围内暂无费用明细。");
    } else {
      tbody.textContent = "";
      charges.items.forEach((item) => {
        tbody.appendChild(row([
          cell(item.request_id.slice(0, 8), "px-3 py-2 font-mono text-[13px]"),
          cell(item.api_key, "px-3 py-2 font-mono text-[13px]"),
          cell(fmtInt(item.billable_tokens)),
          cell(`${fmtInt(item.unit_tokens)} / ¥${item.unit_price_yuan}`),
          cell(item.pricing_version),
          cell(`¥ ${item.amount_yuan}`, "px-3 py-2 text-right font-medium"),
        ]));
      });
    }
    state.hasOlder = Boolean(charges.has_more && charges.next_cursor);
    if (state.hasOlder) state.cursors[state.index + 1] = charges.next_cursor;
    pager(state, render);
  }

  async function applyFilters() {
    readFilters(state);
    resetPages(state);
    notice("error", "");
    try {
      await render();
    } catch (error) {
      notice("error", error.message);
    }
  }
  $("apply").addEventListener("click", applyFilters);
  $("page-size").addEventListener("change", applyFilters);

  await populateKeyFilter();
  readFilters(state);
  try {
    await render();
  } catch (error) {
    notice("error", error.message);
  }
}

const PAGES = { keys: keysPage, usage: usagePage, billing: billingPage };

document.addEventListener("DOMContentLoaded", async function () {
  await initChrome();
  const page = PAGES[document.body.dataset.page];
  if (page) await page();
});
