import { api } from "../../shared/http/client.js";
import { $, notice } from "../../shared/lib/dom.js";
import { initChrome } from "../../shared/console/shell.js";
import { initBranding, applyBranding } from "../../shared/console/branding.js";
import { modelConnectionPage } from "./model-connection.js";

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

void initBranding();
if (await initChrome()) await adminSettingsPage();
