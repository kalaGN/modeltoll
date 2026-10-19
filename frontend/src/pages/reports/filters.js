import { api } from "../../shared/http/client.js";
import { $ } from "../../shared/lib/dom.js";
import { fmtInt } from "../../shared/lib/format.js";
import { query } from "../../shared/lib/query.js";

export const PAGE_SIZE = 20;

export async function populateKeyFilter() {
  const select = $("key-filter");
  if (!select) return;
  const data = await api("/v1/api-keys");
  data.items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.name ? item.name + " · " : "未命名 · "}${item.display}`
      + (item.status === "revoked" ? "（已撤销）" : "");
    select.appendChild(option);
  });
}

export function readFilters(state) {
  state.dateFrom = $("date-from")?.value ?? "";
  state.dateTo = $("date-to")?.value ?? "";
  state.keyId = $("key-filter")?.value ?? "";
  state.pageSize = $("page-size")?.value || PAGE_SIZE;
}

export function filterQuery(state, extra = {}) {
  return query({
    from: state.dateFrom,
    to: state.dateTo,
    api_key_id: state.keyId,
    limit: state.pageSize,
    ...extra,
  });
}

export function resetPages(state) {
  state.index = 0;
  state.cursor = "";
  state.cursors = { 0: "" };
  state.hasOlder = false;
}

export function pager(state, render) {
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
