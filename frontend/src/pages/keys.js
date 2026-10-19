import { api } from "../shared/http/client.js";
import { $, setText, notice } from "../shared/lib/dom.js";
import { fmtInt, fmtTime } from "../shared/lib/format.js";
import { cell, row, messageRow, statusCell } from "../shared/ui/table.js";
import { initChrome } from "../shared/console/shell.js";
import { initBranding } from "../shared/console/branding.js";
import { openModal, closeModal, initModals } from "../shared/ui/modal.js";

async function keysPage() {
  const tbody = $("rows");

  async function load() {
    messageRow(tbody, 6, "加载中…");
    const data = await api("/v1/api-keys");
    setText("stat-total", fmtInt(data.summary.total));
    setText("stat-active", fmtInt(data.summary.active));
    setText("stat-revoked", fmtInt(data.summary.revoked));
    if (!data.items.length) {
      messageRow(tbody, 6, "还没有 API Key，点击右上角申请一个。");
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
        const button = document.createElement("button");
        button.className = "rounded-lg border border-[#fecaca] px-3 py-1.5 text-xs text-[#b42318] hover:bg-[#fef2f2]";
        button.textContent = "删除";
        button.addEventListener("click", () => askDelete(item));
        actions.appendChild(button);
      }
      tbody.appendChild(row([
        cell(item.name || "未命名", "px-3 py-2"),
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
    const label = item.name ? `${item.name} · ${item.display}` : item.display;
    setText("revoke-target", `${label}（撤销后不可恢复，历史调用与费用仍会保留）`);
    openModal(modal);
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
        notice(modal.classList.contains("hidden") ? "error" : modal.id.replace("-modal", "-error"), error.message);
      } finally {
        yes.disabled = false;
        yes.textContent = "确认撤销";
      }
    }
    function close() {
      closeModal(modal);
    }
    $("revoke-confirm").onclick = confirm;
    $("revoke-cancel").onclick = close;
  }

  function askDelete(item) {
    const modal = $("delete-modal");
    const label = item.name ? `${item.name} · ${item.display}` : item.display;
    setText("delete-target", label);
    openModal(modal);
    const yes = $("delete-confirm");
    const cancel = $("delete-cancel");
    cancel.onclick = () => closeModal(modal);
    yes.onclick = async function () {
      yes.disabled = true;
      cancel.disabled = true;
      yes.textContent = "删除中…";
      try {
        await api(`/v1/api-keys/${item.id}`, { method: "DELETE" });
        closeModal(modal);
        notice("error", "");
        await load();
      } catch (error) {
        notice(modal.classList.contains("hidden") ? "error" : "delete-error", error.message);
      } finally {
        yes.disabled = false;
        cancel.disabled = false;
        yes.textContent = "确认删除";
      }
    };
  }

  $("create").addEventListener("click", function () {
    const modal = $("create-modal");
    const input = $("key-name");
    input.value = "";
    openModal(modal);
    input.focus();
    async function confirm() {
      const yes = $("create-confirm");
      yes.disabled = true;
      yes.textContent = "申请中…";
      try {
        const data = await api("/v1/api-keys", { method: "POST", body: { name: input.value.trim() } });
        close();
        notice("error", "");
        showSecret(data.secret, data.call_example);
        await load();
      } catch (error) {
        notice(modal.classList.contains("hidden") ? "error" : modal.id.replace("-modal", "-error"), error.message);
      } finally {
        yes.disabled = false;
        yes.textContent = "创建";
      }
    }
    function close() {
      closeModal(modal);
    }
    $("create-confirm").onclick = confirm;
    $("create-cancel").onclick = close;
  });

  function showSecret(secret, example) {
    setText("secret", secret);
    $("copy").textContent = "复制";
    openModal($("secret-modal"));
    $("copy").onclick = async function () {
      try {
        await navigator.clipboard.writeText(secret);
        $("copy").textContent = "已复制";
      } catch {
        $("copy").textContent = "复制失败，请手动选中";
      }
    };
    $("close").onclick = function () {
      closeModal($("secret-modal"));
      setText("secret", "");
    };
    if (example) setText("example", example.replaceAll(secret, "YOUR_API_KEY"));
  }

  notice("error", "");
  await load();
  if (!$("example").textContent) {
    setText("example", "申请 API Key 后，这里会给出与实际契约一致的调用示例。");
  }
}

void initBranding();
initModals();
if (await initChrome()) await keysPage();
