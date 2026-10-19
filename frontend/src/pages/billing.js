import { api } from "../shared/http/client.js";
import { $, setText, notice } from "../shared/lib/dom.js";
import { fmtInt, fmtTime, fmtAmount } from "../shared/lib/format.js";
import { cell, row, messageRow } from "../shared/ui/table.js";
import { initChrome } from "../shared/console/shell.js";
import { initBranding } from "../shared/console/branding.js";
import { barChart } from "../shared/ui/charts.js";
import { populateKeyFilter, readFilters, filterQuery, resetPages, pager } from "./reports/filters.js";

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

void initBranding();
if (await initChrome()) await billingPage();
