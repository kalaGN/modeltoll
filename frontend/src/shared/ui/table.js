export function cell(text, className = "px-3 py-2") {
  const td = document.createElement("td");
  td.className = className;
  td.textContent = text;
  return td;
}

export function row(cells) {
  const tr = document.createElement("tr");
  tr.className = "border-t border-[#f3f4f6]";
  cells.forEach((c) => tr.appendChild(typeof c === "string" ? cell(c) : c));
  return tr;
}

export function messageRow(tbody, colspan, text) {
  tbody.textContent = "";
  const tr = document.createElement("tr");
  const td = cell(text, "px-3 py-8 text-center text-sm text-[#6b7280]");
  td.colSpan = colspan;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

export const STATUS_LABEL = {
  accepted: "已受理",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  interrupted: "已中断",
  active: "可用",
  revoked: "已撤销",
};

export function statusCell(status) {
  const td = cell("");
  const badge = document.createElement("span");
  badge.className = `status-badge status-${status}`;
  badge.textContent = STATUS_LABEL[status] ?? status;
  const dot = document.createElement("span");
  const color =
    status === "succeeded" || status === "active"
      ? "bg-[#28743e]"
      : status === "failed" || status === "revoked" || status === "interrupted"
        ? "bg-[#b42318]"
        : "bg-[#d97706]";
  dot.className = `mr-2 inline-block h-2 w-2 rounded-full ${color}`;
  badge.insertBefore(dot, badge.firstChild);
  td.appendChild(badge);
  return td;
}
