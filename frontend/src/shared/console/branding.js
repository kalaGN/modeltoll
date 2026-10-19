/* 品牌配置仅包含公开信息，读取失败保留页面默认品牌。 */
export function applyBranding(branding) {
  document.querySelectorAll('.brand').forEach((brand) => {
    brand.querySelector('strong').textContent = branding.name;
    brand.querySelector('small').textContent = branding.description;
    const mark = brand.querySelector('.brand-mark');
    let image = brand.querySelector('.brand-logo');
    if (!image) {
      image = document.createElement('img');
      image.className = 'brand-logo';
      image.alt = '';
      mark.after(image);
    }
    mark.toggleAttribute("hidden", Boolean(branding.logo_url));
    image.hidden = !branding.logo_url;
    if (branding.logo_url) {
      image.onerror = () => { image.hidden = true; mark.removeAttribute("hidden"); };
      image.src = branding.logo_url;
    } else image.removeAttribute('src');
    brand.setAttribute('aria-label', `${branding.name} 首页`);
  });
  document.querySelectorAll('[data-platform-name]').forEach(node => node.textContent = branding.name);
  const pageTitle = document.title.split(' · ')[0];
  document.title = `${pageTitle} · ${branding.name}`;
  const subtitle = document.getElementById('subtitle');
  if (subtitle) subtitle.textContent = location.pathname === '/register' ? `注册后即可登录 ${branding.name}。` : `使用邮箱和密码登录 ${branding.name}。`;
}

export async function initBranding() {
  try {
    const response = await fetch('/v1/platform/branding', {credentials: 'same-origin', cache: 'no-store'});
    if (response.ok) applyBranding((await response.json()).branding);
  } catch { /* 公开品牌不可用时保留默认品牌，不阻断登录。 */ }
}
