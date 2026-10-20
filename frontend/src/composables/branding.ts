import { reactive } from "vue";
import { api } from "../api/client";
import type { Branding } from "../api/types";
export const branding = reactive<Branding>({
  name: "Laya",
  description: "模型 API 平台",
  logo_url: "",
});
export function applyBranding(value: Branding) {
  Object.assign(branding, value);
  document.title = value.name + " · 模型 API 平台";
}
export async function loadBranding() {
  try {
    applyBranding(
      (await api<{ branding: Branding }>("/v1/platform/branding")).branding,
    );
  } catch {
    /* Default branding never blocks sign-in. */
  }
}
