export const $ = (id) => document.getElementById(id);

export function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

export function notice(id, message) {
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
