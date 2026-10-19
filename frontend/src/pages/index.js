import { api } from "../shared/http/client.js";

try {
  const { user } = await api("/v1/auth/me");
  location.replace(user.is_admin ? "/admin" : "/keys");
} catch (error) {
  document.getElementById("status").textContent = error.message;
}
