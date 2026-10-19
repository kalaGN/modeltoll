import { api } from "../../shared/http/client.js";
import { $, notice } from "../../shared/lib/dom.js";
import { fmtInt } from "../../shared/lib/format.js";
import { cell } from "../../shared/ui/table.js";
import { initChrome } from "../../shared/console/shell.js";
import { initBranding } from "../../shared/console/branding.js";
import { CHART, niceMax, chartFrame, moneyTick, svgNode, emptyChart } from "../../shared/ui/charts.js";

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

void initBranding();
if (await initChrome()) await adminOverviewPage();
