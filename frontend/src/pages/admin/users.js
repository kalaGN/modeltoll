import { api } from "../../shared/http/client.js";
import { $, notice } from "../../shared/lib/dom.js";
import { fmtInt, fmtTime } from "../../shared/lib/format.js";
import { cell, row, messageRow } from "../../shared/ui/table.js";
import { initChrome } from "../../shared/console/shell.js";
import { initBranding } from "../../shared/console/branding.js";

async function adminUsersPage() {
  if (document.body.dataset.page !== 'admin-users') return;
  const limit = 20;
  const lists = Object.fromEntries(['users', 'keys', 'audit'].map(name => [name,
    {page: 1, total: 0, hasMore: false, ready: false, busy: false, version: 0}]));
  const dialog = $('management-dialog');
  let selected = null, pending = null, mutating = false;
  let filters = {q: '', status: ''};
  const labels = {active: '已启用', disabled: '已停用', revoked: '已撤销', deleted: '已删除'};

  function pagination(name) {
    const state = lists[name];
    const unavailable = mutating || state.busy || !state.ready || (name === 'keys' && !selected);
    $(`${name}-prev`).disabled = unavailable || state.page <= 1;
    $(`${name}-next`).disabled = unavailable || !state.hasMore || state.page >= 10000;
    $(`${name}-page-label`).textContent = !state.ready ? '暂无分页数据'
      : `第 ${state.page} 页 · 共 ${fmtInt(state.total)} 条 · 每页 ${limit} 条`;
  }
  function controls() {
    Object.keys(lists).forEach(pagination);
    const reading = Object.values(lists).some(state => state.busy);
    $('management-refresh').disabled = mutating || reading;
    $('users-filter').querySelectorAll('input,select,button').forEach(node => {
      node.disabled = mutating || lists.users.busy;
    });
    document.querySelectorAll('[data-admin-action]').forEach(node => {
      node.disabled = mutating || (node.dataset.adminAction === 'user-status' && lists.users.busy)
        || (node.dataset.adminAction === 'revoke' && lists.keys.busy);
    });
  }
  function actionButton(text, type, action) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'button-secondary';
    button.textContent = text; button.dataset.adminAction = type;
    button.addEventListener('click', () => { if (!mutating) action(); });
    return button;
  }
  function status(status) {
    const td = cell('');
    const badge = document.createElement('span');
    badge.className = 'status-badge'; badge.textContent = labels[status] ?? status;
    if (status === 'active') badge.classList.add('status-active');
    else badge.classList.add('status-revoked');
    td.appendChild(badge); return td;
  }
  function showConfirmation(operation) {
    if (mutating || dialog.open) return;
    // 快照固定目标，后续列表刷新/切换不会改变本次操作对象。
    pending = {...operation};
    $('management-title').textContent = operation.title;
    $('management-description').textContent = operation.description;
    $('management-confirm').textContent = operation.title;
    $('management-reason').value = '';
    notice('management-error', ''); dialog.showModal();
    $('management-reason').focus();
  }
  function userRows(items) {
    const body = $('users-rows'); body.textContent = '';
    if (!items.length) return messageRow(body, 6, '没有符合搜索条件的用户。');
    items.forEach(user => {
      const actionCell = cell('');
      const actions = document.createElement('div'); actions.className = 'admin-row-actions';
      actionCell.appendChild(actions);
      const view = actionButton(selected?.id === user.id ? '查看中' : '查看 Key', 'view', () => {
        selected = {...user}; lists.keys.page = 1;
        $('keys-owner').textContent = `当前用户：${user.email}`;
        load('keys');
        // 本地标签更新，不重新发起用户列表读取。
        body.querySelectorAll('[data-admin-action="view"]').forEach(button => {
          button.textContent = button.dataset.userId === user.id ? '查看中' : '查看 Key';
          button.setAttribute('aria-pressed', String(button.dataset.userId === user.id));
        });
      });
      view.dataset.userId = user.id; view.setAttribute('aria-pressed', String(selected?.id === user.id));
      actions.appendChild(view);
      if (!user.is_admin) {
        const next = user.status === 'active' ? 'disabled' : 'active';
        actions.appendChild(actionButton(next === 'disabled' ? '停用用户' : '启用用户', 'user-status', () => {
          showConfirmation({kind: 'status', id: user.id, email: user.email, status: next,
            title: next === 'disabled' ? '确认停用用户' : '确认启用用户',
            description: next === 'disabled' ? `将停用 ${user.email} 并撤销其现有登录会话，阻止新调用；历史账务保留。`
              : `将启用 ${user.email}。用户需重新登录，未撤销的 API Key 将恢复可用。`});
        }));
      } else {
        const note = document.createElement('span'); note.className = 'settings-help';
        note.textContent = '管理员受保护'; actions.appendChild(note);
      }
      body.appendChild(row([cell(user.email), cell(user.is_admin ? '管理员' : '普通用户'), status(user.status),
        cell(fmtTime(user.created_at)), cell(fmtTime(user.last_login_at)), actionCell]));
    });
  }
  function keyRows(items, owner) {
    const body = $('keys-rows'); body.textContent = '';
    if (!items.length) return messageRow(body, 7, '此用户尚无 API Key。');
    items.forEach(key => {
      const actions = cell('');
      if (key.status === 'active') actions.appendChild(actionButton('撤销 Key', 'revoke', () => {
        showConfirmation({kind: 'revoke', id: key.id, userId: owner.id, email: owner.email,
          title: '确认撤销 Key', description: `将撤销 ${owner.email} 的密钥 ${key.name}（${key.display}）。此操作不可恢复，调用和费用历史保留。`});
      }));
      else actions.textContent = '无需操作';
      body.appendChild(row([cell(key.name), cell(key.display), status(key.status), cell(fmtTime(key.created_at)),
        cell(fmtTime(key.last_used_at)), cell(fmtTime(key.deleted_at || key.revoked_at)), actions]));
    });
  }
  function auditRows(items) {
    const body = $('audit-rows'); body.textContent = '';
    if (!items.length) return messageRow(body, 7, '尚无管理操作审计记录。');
    items.forEach(event => {
      const reason = cell(event.reason); reason.className = 'admin-audit-reason';
      body.appendChild(row([cell(fmtTime(event.created_at)), cell(event.actor_email), cell(event.target_email),
        cell(event.action === 'user.status_changed' ? '用户状态变更' : '撤销 Key'),
        cell(`${labels[event.previous_status] ?? event.previous_status} → ${labels[event.new_status] ?? event.new_status}`),
        reason, cell(event.target_key_id || '—')]));
    });
  }
  async function load(name) {
    const state = lists[name];
    const version = ++state.version;
    const owner = selected ? {...selected} : null;
    const page = state.page;
    if (name === 'keys' && !owner) {
      state.ready = false; state.busy = false;
      messageRow($('keys-rows'), 7, '选择用户后查看其脱敏密钥。');
      $('keys-state').textContent = '尚未选择用户'; controls(); return true;
    }
    state.busy = true; state.ready = false; controls();
    $(`${name}-state`).textContent = '正在加载…';
    messageRow($(`${name}-rows`), name === 'users' ? 6 : 7, '正在加载…');
    const params = new URLSearchParams({page, limit});
    let path;
    if (name === 'users') {
      if (filters.q) params.set('q', filters.q);
      if (filters.status) params.set('status', filters.status);
      path = '/v1/admin/users';
    } else if (name === 'keys') path = `/v1/admin/users/${encodeURIComponent(owner.id)}/api-keys`;
    else path = '/v1/admin/audit-events';
    try {
      const data = await api(`${path}?${params}`);
      if (version !== state.version || (name === 'keys' && owner.id !== selected?.id)) return false;
      state.page = data.page; state.total = data.total; state.hasMore = data.has_more; state.ready = true;
      if (name === 'users') userRows(data.items);
      else if (name === 'keys') keyRows(data.items, owner);
      else auditRows(data.items);
      $(`${name}-state`).textContent = data.items.length ? '已更新' : '暂无数据';
      return true;
    } catch (error) {
      if (version !== state.version || (name === 'keys' && owner.id !== selected?.id)) return false;
      $(`${name}-state`).textContent = `读取失败：${error.message}`;
      messageRow($(`${name}-rows`), name === 'users' ? 6 : 7, '数据读取失败，请点击“刷新列表”重试。');
      return false;
    } finally {
      if (version === state.version) { state.busy = false; controls(); }
    }
  }
  async function refresh() { return Promise.all(Object.keys(lists).map(load)); }
  Object.keys(lists).forEach(name => {
    ['prev', 'next'].forEach(direction => {
      $(`${name}-${direction}`).addEventListener('click', () => {
        if ($(`${name}-${direction}`).disabled) return;
        lists[name].page += direction === 'next' ? 1 : -1; load(name);
      });
    });
  });
  $('users-filter').addEventListener('submit', event => {
    event.preventDefault(); if (mutating || lists.users.busy) return;
    filters = {q: $('users-query').value.trim(), status: $('users-status').value};
    lists.users.page = 1; load('users');
  });
  $('users-reset').addEventListener('click', () => {
    if (mutating || lists.users.busy) return;
    $('users-query').value = ''; $('users-status').value = '';
    filters = {q: '', status: ''}; lists.users.page = 1; load('users');
  });
  $('management-refresh').addEventListener('click', () => {
    if (!$('management-refresh').disabled) refresh();
  });
  $('management-cancel').addEventListener('click', () => {
    if (!mutating) { pending = null; dialog.close(); }
  });
  dialog.addEventListener('cancel', event => { if (mutating) event.preventDefault(); else pending = null; });
  $('management-form').addEventListener('submit', async event => {
    event.preventDefault(); if (mutating || !pending) return;
    const reason = $('management-reason').value.trim();
    if (!reason || reason.length > 200) return notice('management-error', '请填写 1–200 个字符的原因。');
    const operation = {...pending}; mutating = true; controls();
    ['management-confirm', 'management-cancel', 'management-reason'].forEach(id => $(id).disabled = true);
    $('management-confirm').textContent = '正在提交…'; notice('management-error', '');
    try {
      const data = operation.kind === 'status'
        ? await api(`/v1/admin/users/${encodeURIComponent(operation.id)}/status`, {method: 'PATCH', body: {status: operation.status, reason}})
        : await api(`/v1/admin/api-keys/${encodeURIComponent(operation.id)}/revoke`, {method: 'POST', body: {reason}});
      if (operation.kind === 'status' && selected?.id === operation.id) selected = {...data.user};
      pending = null; dialog.close();
      if (data.changed) lists.audit.page = 1;
      const result = await refresh();
      $('management-feedback').textContent = (data.changed ? '操作已生效并记录审计。' : '目标已是该状态，未重复变更或记录审计。')
        + (result.every(Boolean) ? '列表已刷新。' : '部分列表刷新失败，请手动刷新确认。');
    } catch (error) { notice('management-error', error.message); }
    finally {
      mutating = false; controls();
      ['management-confirm', 'management-cancel', 'management-reason'].forEach(id => $(id).disabled = false);
      $('management-confirm').textContent = operation.title;
    }
  });
  await refresh();
}

void initBranding();
if (await initChrome()) await adminUsersPage();
