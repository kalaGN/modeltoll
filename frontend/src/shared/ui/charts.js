import { numberFormat } from "../lib/format.js";

export const SVG = "http://www.w3.org/2000/svg";
export const CHART = { width: 560, height: 180, left: 40, right: 10, top: 14, bottom: 28 };

export function svgNode(tag, attrs, text) {
  const node = document.createElementNS(SVG, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (text !== undefined) node.textContent = text;
  return node;
}

export function niceMax(values) {
  const peak = Math.max(0, ...values);
  if (peak <= 0) return 1;          // 金额与 Token 都可能是小数，不能固定下限为 1
  const magnitude = 10 ** Math.floor(Math.log10(peak));
  return Math.ceil(peak / magnitude) * magnitude;
}

export function chartFrame(svg, series, max, tickLabel, inset = false) {
  svg.textContent = "";
  const { width, height, left, right, top, bottom } = CHART;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const label = tickLabel ?? ((v) => numberFormat.format(Math.round(v)));
  for (let step = 0; step <= 4; step += 1) {
    const y = top + (plotHeight * step) / 4;
    svg.appendChild(svgNode("line", { x1: left, y1: y, x2: width - right, y2: y, stroke: "#e4e7dc" }));
    svg.appendChild(
      svgNode("text", { x: left - 6, y: y + 4, "text-anchor": "end", fill: "#687064", "font-size": "10" },
        label((max * (4 - step)) / 4))
    );
  }
  if (series.length <= 1) {
    svg.appendChild(xLabel(series[0]?.date ?? "", inset ? left + plotWidth / 2 : left, height - 8, "middle"));
    return plotHeight;
  }
  const seen = new Set();
  const stride = Math.max(1, Math.ceil(series.length / 8));
  series.forEach((point, index) => {
    if (index % stride !== 0 && index !== series.length - 1) return;
    const x = left + plotWidth * (inset ? (index + 0.5) / series.length : index / (series.length - 1));
    const anchor = index === 0 ? "start" : index === series.length - 1 ? "end" : "middle";
    const key = Math.round(x);
    if (seen.has(key)) return;
    seen.add(key);
    svg.appendChild(xLabel(point.date.slice(5), x, height - 8, anchor));
  });
  return plotHeight;
}

export function xLabel(text, x, y, anchor) {
  return svgNode("text", { x, y, "text-anchor": anchor, fill: "#687064", "font-size": "10" }, text);
}

export function emptyChart(svg, message) {
  svg.textContent = "";
  svg.setAttribute("viewBox", `0 0 ${CHART.width} ${CHART.height}`);
  svg.appendChild(svgNode("text", { x: CHART.width / 2, y: CHART.height / 2, "text-anchor": "middle", fill: "#687064", "font-size": "13" }, message));
}

export function lineChart(svg, series, keys, colors) {
  if (!series.length) return emptyChart(svg, "所选范围内暂无调用趋势");
  const values = series.flatMap((p) => keys.map((k) => Number(p[k] ?? 0)));
  const max = niceMax(values);
  const plotHeight = chartFrame(svg, series, max);
  const plotWidth = CHART.width - CHART.left - CHART.right;
  keys.forEach((key, seriesIndex) => {
    const points = series.map((point, index) => {
      const x = series.length === 1 ? CHART.left + plotWidth / 2 : CHART.left + (plotWidth * index) / (series.length - 1);
      const y = CHART.top + plotHeight - (Number(point[key] ?? 0) / max) * plotHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    svg.appendChild(svgNode("polyline", {
      points: points.join(" "),
      fill: "none",
      stroke: colors[seriesIndex],
      "stroke-width": "2",
      "stroke-linejoin": "round",
    }));
    series.forEach((point, index) => {
      const [x, y] = points[index].split(",");
      svg.appendChild(svgNode("circle", { cx: x, cy: y, r: "3", fill: colors[seriesIndex] }));
    });
  });
}

export function moneyTick(value) {
  const text = value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  return `¥${text === "-0" ? "0" : text}`;
}

export function barChart(svg, series, key) {
  if (!series.length) return emptyChart(svg, "所选范围内暂无费用");
  const values = series.map((p) => Number(p[key] ?? 0));
  const max = niceMax(values);
  const plotHeight = chartFrame(svg, series, max, moneyTick);
  const plotWidth = CHART.width - CHART.left - CHART.right;
  const slot = plotWidth / series.length;
  const barWidth = Math.min(28, Math.max(6, slot * 0.55));
  series.forEach((point, index) => {
    const amount = Number(point[key] ?? 0);
    const height = (amount / max) * plotHeight;
    svg.appendChild(svgNode("rect", {
      x: CHART.left + slot * index + (slot - barWidth) / 2,
      y: CHART.top + plotHeight - height,
      width: barWidth,
      height: Math.max(amount > 0 ? 2 : 0, height),
      rx: "3",
      fill: "#344b2d",
      opacity: amount > 0 ? "0.9" : "0.25",
    }));
  });
}

export function legend(svg, items) {
  items.forEach(([label, color], index) => {
    const x = CHART.width - 150 + index * 80;
    svg.appendChild(svgNode("rect", { x, y: 4, width: 8, height: 8, rx: 2, fill: color }));
    svg.appendChild(svgNode("text", { x: x + 12, y: 11, fill: "#6b7280", "font-size": "10" }, label));
  });
}
