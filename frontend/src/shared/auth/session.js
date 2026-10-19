import { api } from "../http/client.js";

export async function requireSession({ admin = false } = {}) {
  const { user } = await api("/v1/auth/me");
  if (admin && !user.is_admin) {
    location.replace("/keys");
    return null;
  }
  return user;
}
