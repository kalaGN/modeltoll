async function adminOverviewPage() {
  const now = new Date();
  const end = now.toISOString().slice(0, 10);
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - 6)).toISOString().slice(0, 10);
  $('admin-from').value = start; $('admin-to').value = end;
  const refresh = $('admin-refresh');
  let busy = false;
  async function render() {
    if (busy) return;
    busy = true; refresh.disabled = true;
    notice('error', ''); $('overview-state').textContent = '加载中…';
    try {
      const params = new URLSearchParams({from: $('admin-from').value, to: $('admin-to').value});
      const data = await api(`/v1/admin/overview?${params}`);
      const totals = data.totals;
      $('stat-users').textContent = fmtInt(totals.users);
      $('stat-keys').textContent = fmtInt(totals.active_keys);
      $('stat-calls').textContent = fmtInt(totals.calls);
      $('stat-amount').textContent = `¥ ${Number(totals.amount_yuan).toFixed(6)}`;
      // 稀疏数据补齐日期，避免把跨日记录画成连续相邻日期。
      const indexed = new Map(data.series.map(row => [row.date, row]));
      const first = new Date(data.range.from);
      first.setUTCHours(0, 0, 0, 0);
      const upper = new Date(data.range.to);
      const series = [];
      for (let date = first; date < upper; date = new Date(date.getTime() + 86400000)) {
        const day = date.toISOString().slice(0, 10);
        series.push(indexed.get(day) ?? {date: day, calls: 0, amount_yuan: '0'});
      }
      drawAdminChart($('admin-calls-chart'), series, 'calls', false);
      drawAdminChart($('admin-money-chart'), series, 'amount_yuan', true);
      $('admin-daily').textContent = '';
      series.forEach(point => {
        const row = document.createElement('tr');
        row.append(cell(point.date), cell(fmtInt(point.calls)), cell(`¥ ${Number(point.amount_yuan).toFixed(6)}`));
        $('admin-daily').appendChild(row);
      });
      $('overview-state').textContent = totals.calls ? '已更新' : '所选时间暂无调用';
    } catch (error) {
      notice('error', error.message);
      $('overview-state').textContent = '读取失败，请重试';
      ['users', 'keys', 'calls', 'amount'].forEach(key => $(`stat-${key}`).textContent = '—');
      emptyChart($('admin-calls-chart'), '数据读取失败');
      emptyChart($('admin-money-chart'), '数据读取失败');
      $('admin-daily').textContent = '';
    } finally { busy = false; refresh.disabled = false; }
  }
  $('overview-filter').addEventListener('submit', event => { event.preventDefault(); render(); });
  refresh.addEventListener('click', render);
  await render();
}

function drawAdminChart(svg, series, key, money) {
  if (!series.length) return emptyChart(svg, '所选时间暂无数据');
  const values = series.map(row => Number(row[key]));
  const max = niceMax(values);
  const height = chartFrame(svg, series, max, money ? moneyTick : undefined, true);
  const width = CHART.width - CHART.left - CHART.right;
  const points = series.map((row, index) => {
    const x = CHART.left + width * (index + 0.5) / series.length;
    const y = CHART.top + height * (1 - Number(row[key]) / max);
    return [x, y];
  });
  if (money) svg.appendChild(svgNode('polyline', {points: points.map(point => point.join(',')).join(' '), fill: 'none', stroke: '#87ac24', 'stroke-width': 2}));
  points.forEach(([x, y], index) => {
    const node = money
      ? svgNode('circle', {cx: x, cy: y, r: 3, fill: '#87ac24'})
      : svgNode('rect', {x: x - width / series.length * 0.28, y, width: width / series.length * 0.56, height: CHART.top + height - y, rx: 2, fill: index === points.length - 1 ? '#c9e959' : '#344b2d'});
    node.appendChild(svgNode('title', {}, `${series[index].date}：${money ? '¥ ' : ''}${series[index][key]}`));
    svg.appendChild(node);
  });
}

async function adminSettingsPage() {
  const name = $('platform-name'), description = $('platform-description');
  const upload = $('platform-logo'), save = $('save-settings');
  let savedLogo = '', logoChange = null, ready = false, fileReadVersion = 0;
  function preview() {
    $('preview-name').textContent = name.value.trim() || '平台名称';
    $('preview-description').textContent = description.value.trim();
    const source = logoChange === null ? savedLogo : logoChange;
    ['preview-logo', 'logo-thumbnail'].forEach(id => { $(id).hidden = !source; if (source) $(id).src = source; else $(id).removeAttribute('src'); });
    $('preview-default').hidden = Boolean(source);
    $('current-logo').querySelector('span').hidden = Boolean(source);
  }
  async function load() {
    try {
      const data = await api('/v1/platform/branding');
      name.value = data.branding.name; description.value = data.branding.description;
      savedLogo = data.branding.logo_url; ready = true; save.disabled = false;
      $('settings-status').textContent = '配置已加载'; preview();
    } catch (error) { notice('error', error.message); $('settings-status').textContent = '读取配置失败，请刷新重试'; }
  }
  name.addEventListener('input', preview); description.addEventListener('input', preview);
  $('reset-logo').addEventListener('click', () => {
    fileReadVersion += 1; logoChange = ''; upload.value = ''; save.disabled = !ready;
    notice('error', ''); $('settings-status').textContent = '已选择默认 Logo，保存后生效'; preview();
  });
  upload.addEventListener('change', () => {
    const file = upload.files[0];
    const version = ++fileReadVersion;
    notice('error', '');
    if (!file) { save.disabled = !ready; return; }
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) {
      notice('error', '请选择不超过 2 MB 的 PNG、JPEG 或 WebP 图片'); upload.value = ''; save.disabled = !ready; return;
    }
    save.disabled = true;
    const reader = new FileReader();
    reader.onload = () => { if (version !== fileReadVersion) return; logoChange = reader.result; save.disabled = !ready; $('settings-status').textContent = 'Logo 已选择，保存后生效'; preview(); };
    reader.onerror = () => { if (version !== fileReadVersion) return; notice('error', '无法读取图片，请重新选择'); save.disabled = !ready; };
    reader.readAsDataURL(file);
  });
  $('settings-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!ready || save.disabled) return;
    const controls = [...$('settings-form').querySelectorAll('input,textarea,button')];
    controls.forEach(control => control.disabled = true);
    notice('error', ''); $('settings-status').textContent = '保存中…';
    try {
      const data = await api('/v1/admin/settings', {method: 'PUT', body: {name: name.value, description: description.value, logo_data_url: logoChange}});
      name.value = data.branding.name; description.value = data.branding.description;
      savedLogo = data.branding.logo_url; logoChange = null; upload.value = '';
      applyBranding(data.branding); preview(); $('settings-status').textContent = '配置已保存';
    } catch (error) { notice('error', error.message); $('settings-status').textContent = '保存失败，修改内容已保留'; }
    finally { controls.forEach(control => control.disabled = false); }
  });
  await load();
  await modelConnectionPage();
}

async function modelConnectionPage() {
  const form = $('connection-form');
  const save = $('save-connection'), test = $('test-connection');
  const controls = [...form.querySelectorAll('input,button')];
  let ready = false;
  function payload() {
    return {base_url: $('model-base-url').value.trim(), model: $('model-name').value.trim(),
      timeout_seconds: Number($('model-timeout').value), enabled: $('model-enabled').checked};
  }
  function metadata(data) {
    $('model-runtime').textContent = data.runtime === 'external'
      ? '运行模式：仅外部模型，不加载本地 Laya。' : '运行模式：本地 Laya + 外部模型连接。';
    $('model-credential').textContent = data.credential_configured
      ? '服务器已配置上游凭据（不会在页面显示）。' : '服务器未配置上游凭据，适用于不要求认证的本地服务。';
  }
  async function action(method, path) {
    if (!ready || save.disabled || !form.reportValidity()) return;
    const body = payload();
    controls.forEach(node => node.disabled = true);
    notice('connection-error', '');
    $('connection-status').textContent = method === 'PUT' ? '保存中…' : '测试中，请等待上游响应…';
    try {
      const data = await api(path, {method, body});
      if (method === 'PUT') metadata(data);
      $('connection-status').textContent = method === 'PUT' ? '模型连接已保存，新请求立即使用新配置。' : `连接成功，模型 ${data.model} 可用；尚未保存修改。`;
    } catch (error) {
      notice('connection-error', error.message);
      $('connection-status').textContent = '操作失败，输入内容已保留。';
    } finally { controls.forEach(node => node.disabled = false); }
  }
  form.addEventListener('submit', event => { event.preventDefault(); action('PUT', '/v1/admin/model-connection'); });
  test.addEventListener('click', () => action('POST', '/v1/admin/model-connection/test'));
  try {
    const data = await api('/v1/admin/model-connection');
    metadata(data);
    if (data.connection) {
      $('model-base-url').value = data.connection.base_url;
      $('model-name').value = data.connection.model;
      $('model-timeout').value = data.connection.timeout_seconds;
      $('model-enabled').checked = data.connection.enabled;
    }
    $('connection-status').textContent = data.connection ? '连接配置已加载。' : '尚未配置上游，填写后先测试连接。';
    ready = true; save.disabled = false; test.disabled = false;
  } catch (error) {
    notice('connection-error', error.message);
    $('connection-status').textContent = '配置读取失败，请刷新重试。';
  }
}
