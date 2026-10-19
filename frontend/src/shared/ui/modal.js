import { $, notice } from "../lib/dom.js";

const modalReturnFocus = new Map();

export function openModal(modal) {
  modalReturnFocus.set(modal, document.activeElement);
  notice(modal.id.replace("-modal", "-error"), "");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  document.querySelector(".console-shell").inert = true;
  document.body.style.overflow = "hidden";
  modal.querySelector("input, button")?.focus();
}

export function closeModal(modal) {
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  document.querySelector(".console-shell").inert = false;
  document.body.style.overflow = "";
  const previous = modalReturnFocus.get(modal);
  if (previous?.isConnected) previous.focus();
  else $("create")?.focus();
  modalReturnFocus.delete(modal);
}

let initialized = false;

export function initModals() {
  if (initialized) return;
  initialized = true;
  document.addEventListener("keydown", function (event) {
    const modal = document.querySelector(".modal-overlay:not(.hidden)");
    if (!modal) return;
    if (event.key === "Escape" && modal.id !== "secret-modal") {
      const prefix = modal.id.replace("-modal", "");
      if (!$(prefix + "-confirm").disabled) $(prefix + "-cancel").click();
    }
    if (event.key !== "Tab") return;
    const controls = [...modal.querySelectorAll("button:not(:disabled), input:not(:disabled)")];
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });
}
