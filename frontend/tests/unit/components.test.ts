import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import Modal from "../../src/components/Modal.vue";
import LoginPage from "../../src/pages/auth/LoginPage.vue";
import KeysPage from "../../src/pages/console/KeysPage.vue";
import * as client from "../../src/api/client";

beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value: vi.fn(function (this: HTMLDialogElement) {
        this.open = true;
      }),
    },
    close: {
      configurable: true,
      value: vi.fn(function (this: HTMLDialogElement) {
        this.open = false;
      }),
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});
it("modal respects busy Escape behavior and restores focus", async () => {
  const button = document.createElement("button");
  document.body.appendChild(button);
  button.focus();
  const wrapper = mount(Modal, {
    attachTo: document.body,
    props: { id: "fixture", title: "确认", busy: true },
  });
  await wrapper.find("dialog").trigger("cancel");
  expect(wrapper.emitted("close")).toBeUndefined();
  await wrapper.setProps({ busy: false });
  await wrapper.find("dialog").trigger("cancel");
  expect(wrapper.emitted("close")).toHaveLength(1);
  wrapper.unmount();
  expect(document.activeElement).toBe(button);
});
it("login waits for CSRF, displays server errors and supports register mode", async () => {
  vi.spyOn(client, "ensureCsrf").mockResolvedValue();
  vi.spyOn(client, "api").mockRejectedValue(
    new client.ApiError(401, "邮箱或密码不正确"),
  );
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/login", component: LoginPage },
      { path: "/register", component: LoginPage },
    ],
  });
  await router.push("/login");
  await router.isReady();
  const wrapper = mount(LoginPage, { global: { plugins: [router] } });
  await flushPromises();
  expect((wrapper.get("#submit").element as HTMLButtonElement).disabled).toBe(
    false,
  );
  await wrapper.get("#email").setValue("fixture@example.invalid");
  await wrapper.get("#password").setValue("synthetic-password");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  expect(wrapper.get("[role=alert]").text()).toBe("邮箱或密码不正确");
  await wrapper.get("#reveal").trigger("click");
  expect(wrapper.get("#password").attributes("type")).toBe("text");
  await router.push("/register");
  await flushPromises();
  expect(wrapper.get("#title").text()).toBe("创建账号");
  wrapper.unmount();
});
it("key creation keeps secret only in the temporary dialog and masks examples", async () => {
  vi.spyOn(client, "api").mockImplementation(async (path, options) => {
    if (options?.method === "POST")
      return {
        secret: "SYNTHETIC_KEY_NOT_VALID",
        call_example: "Bearer SYNTHETIC_KEY_NOT_VALID",
      } as never;
    return { items: [], summary: { total: 0, active: 0, revoked: 0 } } as never;
  });
  const wrapper = mount(KeysPage, { attachTo: document.body });
  await flushPromises();
  await wrapper.get("#create").trigger("click");
  await wrapper.get("#key-name").setValue("fixture");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  expect(wrapper.get("#secret").text()).toBe("SYNTHETIC_KEY_NOT_VALID");
  expect(wrapper.get("#example").text()).toBe("Bearer YOUR_API_KEY");
  await wrapper.get("#secret-modal").trigger("cancel");
  expect(wrapper.find("#secret").exists()).toBe(true);
  await wrapper.get("#close").trigger("click");
  expect(wrapper.find("#secret").exists()).toBe(false);
  wrapper.unmount();
});
