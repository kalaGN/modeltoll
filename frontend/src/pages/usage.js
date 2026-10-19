import { api } from "../shared/http/client.js";
import { $, setText, notice } from "../shared/lib/dom.js";
import { fmtInt, fmtTime, fmtMs } from "../shared/lib/format.js";
import { cell, row, messageRow, statusCell } from "../shared/ui/table.js";
import { initChrome } from "../shared/console/shell.js";
import { initBranding } from "../shared/console/branding.js";
import { lineChart, legend } from "../shared/ui/charts.js";
import { populateKeyFilter, readFilters, filterQuery, resetPages, pager } from "./reports/filters.js";

async function usagePage() {
  const state = { keyId: "", endpoint: "", dateFrom: "", dateTo: "", total: 0 };
  resetPages(state);

  const endpointSelect = $("endpoint-filter");
  [["", "全部接口"], ["/v1/predict", "/v1/predict"], ["/v1/customer-service/analyze", "/v1/customer-service/analyze"], ["/v1/chat/completions", "/v1/chat/completions"]]
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
    lineChart($("chart"), summary.series, ["succeeded", "failed"], ["#344b2d", "#dc2626"]);
    legend($("chart"), [["成功", "#344b2d"], ["失败", "#dc2626"]]);
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

void initBranding();
if (await initChrome()) await usagePage();
