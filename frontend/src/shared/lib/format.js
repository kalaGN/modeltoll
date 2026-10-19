export const numberFormat = new Intl.NumberFormat("en-US");

export function fmtInt(value) {
  return numberFormat.format(Number(value ?? 0));
}

export function fmtTime(iso) {
  if (!iso) return "—";
  // 接口统一返回 UTC；无时区后缀时按 UTC 解析，避免浏览器按本地时区偏移后仍标注 UTC。
  const text = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : iso + "Z";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toISOString().slice(0, 19).replace("T", " ");
}

export function fmtAmount(value) {
  // 金额按价格规则保留 6 位小数；空窗口的 0 也要与明细同一位数。
  const text = String(value ?? "0");
  const [int, frac = ""] = text.split(".");
  return `${int}.${frac.padEnd(6, "0").slice(0, 6)}`;
}

export function fmtMs(value) {
  return value === null || value === undefined ? "—" : `${fmtInt(value)} ms`;
}
