import { shallowRef } from "vue";
import { api } from "../api/client";
import type { User } from "../api/types";

export const currentUser = shallowRef<User | null>(null);
export async function readSession() {
  currentUser.value = (await api<{ user: User }>("/v1/auth/me")).user;
  return currentUser.value;
}
export async function logout() {
  await api("/v1/auth/logout", { method: "POST", body: {} });
  currentUser.value = null;
}
