import { api } from "../../shared/http/client.js";
import { $, notice } from "../../shared/lib/dom.js";

export async function modelConnectionPage() {
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
